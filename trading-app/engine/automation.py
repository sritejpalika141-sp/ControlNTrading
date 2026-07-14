import json
import os
import time
import logging
import pytz
import traceback
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from engine.notifier import trigger_webhook_background

IST = pytz.timezone('Asia/Kolkata')

class TradingState:
    @property
    def trades_today(self):
        return self.paper_trades_today if getattr(self, 'paper_trading', True) else self.live_trades_today

    @trades_today.setter
    def trades_today(self, value):
        if getattr(self, 'paper_trading', True):
            self.paper_trades_today = value
        else:
            self.live_trades_today = value

    @property
    def pnl_today(self):
        return self.paper_pnl_today if getattr(self, 'paper_trading', True) else self.live_pnl_today

    @pnl_today.setter
    def pnl_today(self, value):
        if getattr(self, 'paper_trading', True):
            self.paper_pnl_today = value
        else:
            self.live_pnl_today = value

    def __init__(self, user_id, state_file=None):
        self.user_id = str(user_id)
        self.state_file = f"logs/trading_state_{self.user_id}.json"
        
        # Concurrency lock for order placement
        import asyncio
        self.order_lock = asyncio.Lock()
        
        self.automation_enabled = False
        # Risk Management Settings
        self.max_trades_per_day = 10  # Total trades allowed per day (high limit since strategies run in parallel)
        self.max_loss_per_day = 2500.0
        self.daily_profit_target = 5000.0
        self.max_loss_trades_per_day = 2  # Max LOSING trades per day (default 2) — stops all trading when reached
        self.loss_trades_today = 0  # Counter for losing trades today
        self.webhook_url = ""
        self.live_trades_today = 0
        self.paper_trades_today = 0
        self.live_pnl_today = 0.0
        self.paper_pnl_today = 0.0
        self.last_reset_date = datetime.now(IST).date().isoformat()
        self.eod_report_sent_date = ""
        self.holiday_report_sent_date = ""
        self.active_auto_trades = []
        self.closed_trades_today = []
        self.traded_strikes_today = []
        self.skipped_signals = [] # List of sig_id strings
        self.active_symbols = ["NSE:NIFTY50-INDEX"]
        self.hard_exit_triggered = False
        self.last_trade_time = 0.0 # Unix timestamp
        self.last_loss_time = 0.0  # Unix timestamp
        self.last_trade_close_time = 0.0  # When last trade closed (for dynamic cooldown)
        self.last_trade_result = ""  # 'profit', 'loss', 'manual', 'breakeven'
        self.cooldown_period_mins = 0 
        self.profit_target_met = False
        # Configurable SL limits (user can change via Settings UI)
        self.max_sl_trending = 15.0
        self.max_sl_range = 10.0
        self.trail_sl_type = "swing_low" # "step" or "swing_low"
        self.trail_sl_step = 5.0
        self.trade_lots = 1
        self.stock_lots = 1
        self.mcx_lots = 1
        self.enabled_symbols = ["NSE:NIFTY50-INDEX"]
        # Symbols the news auto-injector added during the day (stocks / commodities / currency).
        # These are purged automatically at end-of-day so the watchlist resets to the user's base
        # symbols each night; the agent re-adds fresh picks the next session.
        self.agent_added_symbols = []
        self.paper_trading = True
        self.paper_positions = []
        self.paper_orders = []
        self.paper_funds = {"availableBalance": 1000000.0, "realizedPnl": 0.0}
        self.active_strategies = ["Strategy 1: OB + FVG", "Strategy 2: 9:26 - 180 Buy", "Strategy 3: 5-Minute ORB", "Strategy 4: Wisdom-Aligned Pullback", "Strategy 5: Optimized Aerospace Mean Reversion", "Strategy 6: Gap Fill Reversal", "Strategy 7: Swing-Pivot Breakout", "Strategy 8: Smart Money Concepts", "Strategy 9: 9-EMA Momentum Scalper"]
        # Strategy 2 Specific State (9:26 - 9:35 - 180 Buy)
        self.strat_926_expired = False
        self.strat_926_strikes = None
        self.strat_926_triggered = False
        
        # Strategy 3 Specific State (5-Minute ORB)
        self.strat_orb_triggered = False
        self.strat_orb_expired = False

        # Strategy 1 specific state — only 1 trade per day
        self.strat_1_triggered = False
        
        # Strategy 6 Specific State (Gap Fill)
        self.strat_6_trades_today = 0
        self.strat_6_confirmed = False
        self.strat_6_gap_data = None
        self.strat_6_confirmation_data = None
        self.strat_7_trades_today = 0
        self.strat_7_pending_order = None
        self.strat_7_was_stopout = False
        self.strat_7_awaiting_confirmation = None
        
        # Pre-Market AI Oracle State
        self.use_ai_oracle = False
        self.ai_daily_bias = ""
        
        # Live multi-strategy signals array (transient, UI only)
        self.live_signals = []
        
        # Ensure logs directory exists
        if not os.path.exists("logs"):
            os.makedirs("logs")
            
        self.load()

    def load(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    today_ist = datetime.now(IST).date().isoformat()
                    saved_date = data.get("last_reset_date", "")
                    if saved_date != today_ist:
                        # Date changed — always reset on load (don't wait for 9 AM)
                        print(f"📅 State file date ({saved_date}) != today ({today_ist}). Resetting counters.", flush=True)
                        self.reset_day()
                    else:
                        self.automation_enabled = data.get("automation_enabled", False)
                        
                        # Handle migration from old trades_today
                        legacy_trades = data.get("trades_today", 0)
                        legacy_pnl = data.get("pnl_today", 0.0)
                        is_paper = data.get("paper_trading", True)
                        self._paper_trading = is_paper
                        
                        self.live_trades_today = data.get("live_trades_today", 0 if is_paper else legacy_trades)
                        self.paper_trades_today = data.get("paper_trades_today", legacy_trades if is_paper else 0)
                        self.live_pnl_today = data.get("live_pnl_today", 0.0 if is_paper else legacy_pnl)
                        self.paper_pnl_today = data.get("paper_pnl_today", legacy_pnl if is_paper else 0.0)
                        self.active_auto_trades = data.get("active_auto_trades", [])
                        self.closed_trades_today = data.get("closed_trades_today", [])
                        self.traded_strikes_today = data.get("traded_strikes_today", [])
                        self.skipped_signals = data.get("skipped_signals", [])
                        self.active_symbols = data.get("active_symbols", ["NSE:NIFTY50-INDEX"])
                        self.enabled_symbols = data.get("enabled_symbols", ["NSE:NIFTY50-INDEX"])
                        self.agent_added_symbols = data.get("agent_added_symbols", [])
                        self.hard_exit_triggered = data.get("hard_exit_triggered", False)
                        self.last_reset_date = saved_date
                        self.eod_report_sent_date = data.get("eod_report_sent_date", "")
                        self.holiday_report_sent_date = data.get("holiday_report_sent_date", "")
                        # D4: restore the nightly-learning guard so it survives restart.
                        self.nightly_learning_date = data.get("nightly_learning_date", "")
                        # Load configurable risk parameters
                        self.max_trades_per_day = data.get("max_trades_per_day", 10)
                        self.max_loss_per_day = data.get("max_loss_per_day", 2500.0)
                        self.max_loss_trades_per_day = data.get("max_loss_trades_per_day", 2)
                        self.loss_trades_today = data.get("loss_trades_today", 0)
                        self.max_sl_trending = data.get("max_sl_trending", 15.0)
                        self.max_sl_range = data.get("max_sl_range", 10.0)
                        self.trail_sl_type = data.get("trail_sl_type", "swing_low")
                        self.trail_sl_step = data.get("trail_sl_step", 5.0)
                        self.daily_profit_target = data.get("daily_profit_target", 5000.0)
                        self.webhook_url = data.get("webhook_url", "")
                        self.trade_lots = data.get("trade_lots", 1)
                        self.paper_trading = data.get("paper_trading", True)
                        self.paper_positions = data.get("paper_positions", [])
                        self.paper_orders = data.get("paper_orders", [])
                        self.paper_funds = data.get("paper_funds", {"availableBalance": 1000000.0, "realizedPnl": 0.0})
                        self.active_strategies = data.get("active_strategies", ["Strategy 1: OB + FVG", "Strategy 2: 9:26 - 180 Buy", "Strategy 3: 5-Minute ORB", "Strategy 4: Wisdom-Aligned Pullback", "Strategy 5: Optimized Aerospace Mean Reversion", "Strategy 6: Gap Fill Reversal", "Strategy 7: Swing-Pivot Breakout", "Strategy 8: Smart Money Concepts", "Strategy 9: 9-EMA Momentum Scalper"])
                        self.strat_orb_triggered = data.get("strat_orb_triggered", False)
                        self.strat_orb_expired = data.get("strat_orb_expired", False)
                        self.strat_926_triggered = data.get("strat_926_triggered", False)
                        self.strat_926_expired = data.get("strat_926_expired", False)
                        self.strat_926_strikes = data.get("strat_926_strikes", None)
                        self.strat_1_triggered = data.get("strat_1_triggered", False)
                        
                        self.strat_6_trades_today = data.get("strat_6_trades_today", 0)
                        self.strat_6_confirmed = data.get("strat_6_confirmed", False)
                        self.strat_6_gap_data = data.get("strat_6_gap_data", None)
                        self.strat_6_confirmation_data = data.get("strat_6_confirmation_data", None)
                        self.strat_7_trades_today = data.get("strat_7_trades_today", 0)
                        self.strat_7_pending_order = data.get("strat_7_pending_order", None)
                        self.strat_7_was_stopout = data.get("strat_7_was_stopout", False)
                        self.strat_7_awaiting_confirmation = data.get("strat_7_awaiting_confirmation", None)

                        self.use_ai_oracle = data.get("use_ai_oracle", False)
                        self.ai_daily_bias = data.get("ai_daily_bias", "")

                        self.last_trade_close_time = data.get("last_trade_close_time", 0.0)
                        self.last_trade_result = data.get("last_trade_result", "")
                        print(f"📂 Loaded state: trades={self.trades_today}, loss_trades={self.loss_trades_today}/{self.max_loss_trades_per_day}, lots={self.trade_lots}, active_trades={len(self.active_auto_trades)}, strategies={self.active_strategies}", flush=True)
            except Exception as e:
                print(f"⚠️ State load error: {e}. Resetting.", flush=True)
                self.reset_day()
        else:
            self.reset_day()

    def save(self):
        import asyncio
        data_dict = {
            "automation_enabled": self.automation_enabled,
            "live_trades_today": self.live_trades_today,
            "paper_trades_today": self.paper_trades_today,
            "live_pnl_today": self.live_pnl_today,
            "paper_pnl_today": self.paper_pnl_today,
            "last_reset_date": self.last_reset_date,
            "eod_report_sent_date": self.eod_report_sent_date,
            "holiday_report_sent_date": getattr(self, "holiday_report_sent_date", ""),
            # D4: persist the nightly-learning "already ran today" guard so it survives a
            # process restart and nightly learning cannot double-run after a restart.
            "nightly_learning_date": getattr(self, "nightly_learning_date", ""),
            "max_trades_per_day": self.max_trades_per_day,
            "max_loss_per_day": getattr(self, "max_loss_per_day", 1500.0),
            "max_loss_trades_per_day": self.max_loss_trades_per_day,
            "loss_trades_today": self.loss_trades_today,
            "daily_profit_target": self.daily_profit_target,
            "webhook_url": self.webhook_url,
            "max_sl_trending": self.max_sl_trending,
            "max_sl_range": self.max_sl_range,
            "trail_sl_type": getattr(self, "trail_sl_type", "swing_low"),
            "trail_sl_step": self.trail_sl_step,
            "trade_lots": self.trade_lots,
            "paper_trading": self.paper_trading,
            "paper_positions": self.paper_positions,
            "paper_orders": self.paper_orders,
            "paper_funds": self.paper_funds,
            "active_auto_trades": self.active_auto_trades,
            "closed_trades_today": getattr(self, "closed_trades_today", []),
            "profit_target_met": self.profit_target_met,
            "traded_strikes_today": self.traded_strikes_today,
            "skipped_signals": self.skipped_signals,
            "active_symbols": self.active_symbols,
            "enabled_symbols": getattr(self, "enabled_symbols", ["NSE:NIFTY50-INDEX"]),
            "agent_added_symbols": getattr(self, "agent_added_symbols", []),
            "hard_exit_triggered": self.hard_exit_triggered,
            "active_strategies": self.active_strategies,
            "strat_orb_triggered": self.strat_orb_triggered,
            "strat_orb_expired": self.strat_orb_expired,
            "strat_926_triggered": self.strat_926_triggered,
            "strat_926_expired": self.strat_926_expired,
            "strat_926_strikes": self.strat_926_strikes,
            "strat_1_triggered": getattr(self, "strat_1_triggered", False),
            "strat_6_trades_today": getattr(self, "strat_6_trades_today", 0),
            "strat_6_confirmed": getattr(self, "strat_6_confirmed", False),
            "strat_6_gap_data": getattr(self, "strat_6_gap_data", None),
            "strat_6_confirmation_data": getattr(self, "strat_6_confirmation_data", None),
            "strat_7_trades_today": getattr(self, "strat_7_trades_today", 0),
            "strat_7_pending_order": getattr(self, "strat_7_pending_order", None),
            "strat_7_was_stopout": getattr(self, "strat_7_was_stopout", False),
            "strat_7_awaiting_confirmation": getattr(self, "strat_7_awaiting_confirmation", None),
            "use_ai_oracle": getattr(self, "use_ai_oracle", False),
            "ai_daily_bias": getattr(self, "ai_daily_bias", ""),
            "last_trade_close_time": self.last_trade_close_time,
            "last_trade_result": self.last_trade_result
        }

        async def _async_db_update():
            try:
                from models import Database
                if str(self.user_id).isdigit():
                    await Database.upsert_paper_pnl(int(self.user_id), self.last_reset_date, self.paper_pnl_today, self.paper_trades_today)
                    await Database.upsert_daily_pnl(int(self.user_id), self.last_reset_date, self.live_pnl_today, self.live_trades_today)
            except Exception as e:
                print(f"⚠️ Error saving daily PnL to DB: {e}", flush=True)

        async def _async_save():
            if not os.path.exists("logs"):
                os.makedirs("logs")
            try:
                import aiofiles
                async with aiofiles.open(self.state_file, 'w') as f:
                    await f.write(json.dumps(data_dict))
            except ImportError:
                with open(self.state_file, 'w') as f:
                    json.dump(data_dict, f)
            
            # Throttle DB writes to once every 30s
            now = time.time()
            last_db = getattr(self, '_last_db_save', 0.0)
            if now - last_db > 30.0:
                self._last_db_save = now
                await _async_db_update()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_save())
        except RuntimeError:
            if not os.path.exists("logs"):
                os.makedirs("logs")
            with open(self.state_file, 'w') as f:
                json.dump(data_dict, f)
            # Cannot safely block and run async DB update without an event loop
            pass

    def reset_day(self):
        """Reset all daily counters for a fresh trading day."""
        prev_date = self.last_reset_date
        
        # Explicitly save the final PnL for the previous day before wiping stats
        try:
            from models import Database
            if str(self.user_id).isdigit():
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(Database.upsert_paper_pnl(int(self.user_id), prev_date, self.paper_pnl_today, self.paper_trades_today))
                    loop.create_task(Database.upsert_daily_pnl(int(self.user_id), prev_date, self.live_pnl_today, self.live_trades_today))
                except RuntimeError:
                    pass
        except Exception as e:
            print(f"⚠️ Error explicitly saving final daily PnL to DB: {e}", flush=True)


        self.live_trades_today = 0
        self.paper_trades_today = 0
        self.live_pnl_today = 0.0
        self.paper_pnl_today = 0.0
        self.active_auto_trades = []
        self.closed_trades_today = []
        self.traded_strikes_today = []
        self.skipped_signals = []
        self.hard_exit_triggered = False
        self.profit_target_met = False
        self.last_loss_time = 0.0
        self.last_trade_close_time = 0.0
        self.last_trade_result = ""
        self.loss_trades_today = 0  # Reset loss trade counter
        self.paper_positions = []
        self.paper_orders = []
        self.paper_funds = {"availableBalance": 1000000.0, "realizedPnl": 0.0}
        # Reset Strategy 2 State
        self.strat_926_expired = False
        self.strat_926_strikes = None
        self.strat_926_triggered = False
        # Reset Strategy 3 State
        self.strat_orb_expired = False
        self.strat_orb_triggered = False
        # Reset Strategy 1 State
        self.strat_1_triggered = False
        # Reset Strategy 4 State
        self.strat_4_trades = 0
        # Reset Strategy 6 State
        self.strat_6_trades_today = 0
        self.strat_6_confirmed = False
        self.strat_6_gap_data = None
        self.strat_6_confirmation_data = None
        self.strat_7_trades_today = 0
        self.strat_7_pending_order = None
        self.strat_7_was_stopout = False
        self.strat_7_awaiting_confirmation = None
        # Reset AI Bias
        self.ai_daily_bias = ""
        # Preserve automation_enabled and active_symbols across resets
        if not hasattr(self, 'active_symbols') or not self.active_symbols:
            self.active_symbols = ["NSE:NIFTY50-INDEX"]
        self.last_reset_date = datetime.now(IST).date().isoformat()
        
        trigger_webhook_background(self.webhook_url, f"🔄 Daily Reset occurred for {self.last_reset_date}.", title="System Reset")
        
        self.save()
        new_date = self.last_reset_date
        print(f"🔄 Daily Reset: {prev_date} → {new_date} | Trades: 0/{self.max_trades_per_day} | PnL: ₹0 | Automation: {'ON' if self.automation_enabled else 'OFF'}", flush=True)

        # Prune daily PnL history in database older than 6 months
        try:
            from models import Database
            if str(self.user_id).isdigit():
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(Database.prune_pnl_history(int(self.user_id), months_limit=6))
                except RuntimeError:
                    pass
        except Exception as e:
            print(f"⚠️ Error pruning daily PnL: {e}", flush=True)

    def check_daily_reset(self):
        """Check if a new trading day has started and reset if needed.
        Called every loop iteration at runtime."""
        today = datetime.now(IST).date().isoformat()
        if self.last_reset_date != today:
            # Only reset after 9:00 AM IST to avoid premature midnight resets
            now_ist = datetime.now(IST)
            if now_ist.hour >= 9:
                self.reset_day()
                return True
        return False

    def add_skipped_signal(self, sig_id):
        if sig_id not in self.skipped_signals:
            self.skipped_signals.append(sig_id)
            self.save()

    def add_symbol(self, symbol, enable=False, by_agent=False):
        """Add a symbol to the watchlist. If enable=True, also mark it auto-trade-enabled
        (ticks its checkbox) so the automation loop trades it — used by the news auto-injector
        for stocks. If by_agent=True, tag it for automatic end-of-day purge. Backward-compatible:
        enable/by_agent default to False (watchlist-only, permanent)."""
        if not hasattr(self, 'active_symbols'): self.active_symbols = ["NSE:NIFTY50-INDEX"]
        changed = False
        if symbol not in self.active_symbols:
            self.active_symbols.append(symbol)
            changed = True
        if enable:
            if not hasattr(self, 'enabled_symbols'): self.enabled_symbols = ["NSE:NIFTY50-INDEX"]
            if symbol not in self.enabled_symbols:
                self.enabled_symbols.append(symbol)
                changed = True
        if by_agent:
            if not hasattr(self, 'agent_added_symbols'): self.agent_added_symbols = []
            if symbol not in self.agent_added_symbols:
                self.agent_added_symbols.append(symbol)
                changed = True
        if changed:
            self.save()

    def purge_agent_symbols(self, only=None):
        """End-of-day cleanup: remove agent-auto-added scrips from the watchlist AND the enabled
        list, and un-tag them. User-added symbols and the base NIFTY symbol are untouched.

        only=None purges all agent scrips; only='equity' purges only NSE (non-MCX/CDS) scrips;
        only='mcx' purges only MCX/CDS scrips. This lets the equity session (cleaned at ~15:30) and
        the MCX session (cleaned at ~23:45, since crude trades till 23:30) each clear their own
        agent scrips without touching the other market's still-open scrips. Returns the list purged."""
        agent_syms = list(getattr(self, "agent_added_symbols", []) or [])
        if not agent_syms:
            return []
        purged = []
        for sym in agent_syms:
            is_mcx = sym.startswith("MCX:") or sym.startswith("CDS:")
            if only == "equity" and is_mcx:
                continue
            if only == "mcx" and not is_mcx:
                continue
            purged.append(sym)
        for sym in purged:
            if sym in getattr(self, "active_symbols", []):
                self.active_symbols.remove(sym)
            if sym in getattr(self, "enabled_symbols", []):
                self.enabled_symbols.remove(sym)
            if sym in self.agent_added_symbols:
                self.agent_added_symbols.remove(sym)
        if purged:
            self.save()
        return purged

    def remove_symbol(self, symbol):
        if not hasattr(self, 'active_symbols'): self.active_symbols = ["NSE:NIFTY50-INDEX"]
        if symbol in self.active_symbols:
            self.active_symbols.remove(symbol)
            self.save()

    def has_active_trade_for_strategy(self, strategy_name):
        """Check if a specific strategy already has an active trade running.
        Each strategy can have at most 1 active trade at a time.
        Different strategies CAN trade simultaneously."""
        for t in self.active_auto_trades:
            t_strat = t.get("strategy", "") or ""
            # Match by strategy prefix (e.g. "Strategy 1" matches "Strategy 1: OB + FVG")
            if strategy_name and t_strat and (
                t_strat == strategy_name or
                t_strat.startswith(strategy_name.split(":")[0]) or
                strategy_name.startswith(t_strat.split(":")[0])
            ):
                return True
        return False

    def can_trade(self, strategy_name="", signal_type=""):
        # AI Bias Filtering
        if self.use_ai_oracle and self.ai_daily_bias and signal_type:
            if "BUY" in signal_type and self.ai_daily_bias == "BEARISH":
                return False, "Blocked by AI Oracle (BEARISH bias)"
            if "SELL" in signal_type and self.ai_daily_bias == "BULLISH":
                return False, "Blocked by AI Oracle (BULLISH bias)"
                
        # Check for daily reset first
        self.check_daily_reset()

        if not self.automation_enabled:
            return False, "Automation disabled"
        if self.hard_exit_triggered:
            return False, "Max loss exit triggered — no more trades today"
        if self.trades_today >= self.max_trades_per_day:
            return False, f"Daily trade limit reached ({self.max_trades_per_day})"
        if self.pnl_today <= -self.max_loss_per_day:
            return False, f"Daily loss limit reached (₹{self.max_loss_per_day})"
        
        # ═══ MAX LOSS TRADES CHECK ═══
        # If we've hit the max number of LOSING trades today, stop all trading
        if self.loss_trades_today >= self.max_loss_trades_per_day:
            return False, f"Max loss trades reached ({self.loss_trades_today}/{self.max_loss_trades_per_day}) — no more trades today"
        
        # ═══ DYNAMIC COOLDOWN ═══
        # After any trade closes, wait before taking the next one
        now = time.time()
        if self.last_trade_close_time > 0:
            elapsed_mins = (now - self.last_trade_close_time) / 60
            cooldown_mins = self._get_cooldown_minutes()
            remaining = cooldown_mins - elapsed_mins
            if remaining > 0:
                mins = int(remaining)
                secs = int((remaining - mins) * 60)
                return False, f"⏳ Cooldown: {mins}m {secs}s remaining ({self.last_trade_result})"

        # Double-fire protection (10s buffer between any trade action)
        if now - self.last_trade_time < 10:
            return False, "Rate limiting trades (10s buffer)"
        
        # ═══ PER-STRATEGY ACTIVE TRADE LOCK ═══
        # Block only if THIS specific strategy already has an active trade
        # Other strategies are free to trade simultaneously
        if strategy_name and self.has_active_trade_for_strategy(strategy_name):
            return False, f"Active trade in progress for {strategy_name.split(':')[0].strip()}"
            
        return True, "OK"

    def _get_cooldown_minutes(self):
        """Dynamic cooldown based on last trade result."""
        cooldown_map = {
            "profit": 3.0,   # 3 minutes after profit
            "loss": 5.0,     # 5 minutes after loss  
            "manual": 2.0,   # 2 minutes after manual exit
            "breakeven": 3.0 # 3 minutes after breakeven
        }
        return cooldown_map.get(self.last_trade_result, 3.0)

    def record_trade(self):
        # Increment trade count IMMEDIATELY on entry to prevent exceeding daily limit
        self.last_trade_time = time.time()
        if self.paper_trading:
            self.paper_trades_today += 1
        else:
            self.live_trades_today += 1
        print(f"📊 Trade opened: trades_today={self.trades_today}/{self.max_trades_per_day}", flush=True)
        self.save()

    def record_trade_close(self, result="loss", pos=None, exit_price=0.0, pnl=0.0, reason=""):
        """Record when a trade closes. result = 'profit', 'loss', 'manual', 'breakeven'
        NOTE: Trade count is incremented on OPEN (record_trade), NOT here."""
        self.last_trade_close_time = time.time()
        self.pnl_today += pnl
        
        if pnl > 0:
            self.last_trade_result = 'profit'
        elif pnl < 0:
            self.last_trade_result = 'loss'
        else:
            self.last_trade_result = 'breakeven'
            
        # Send Webhook Alert
        if pos:
            strategy_label = pos.get('strategy', 'Unknown Strategy') or 'Unknown Strategy'
            result_emoji = '✅' if pnl > 0 else '🟥' if pnl < 0 else '▪️'
            trend_emoji = '📈' if pnl > 0 else '📉'
            msg = (
                f"{result_emoji} <b>TRADE CLOSED</b>\n"
                f"\n"
                f"🎯 <b>Strategy:</b> {strategy_label}\n"
                f"📊 <b>Symbol:</b> {pos['symbol']}\n"
                f"🔄 <b>Side:</b> {pos['side']}\n"
                f"💰 <b>Exit Price:</b> ₹{exit_price}\n"
                f"{trend_emoji} <b>PnL:</b> ₹{pnl:.2f}\n"
                f"📌 <b>Reason:</b> {reason}"
            )
            trigger_webhook_background(self.webhook_url, msg, title="Trade Closed")
            
            if not hasattr(self, 'closed_trades_today'):
                self.closed_trades_today = []
            self.closed_trades_today.append({
                "symbol": pos.get("symbol", "Unknown"),
                "pnl": pnl
            })
        
        if result == "loss":
            self.last_loss_time = time.time()
            self.loss_trades_today += 1
            print(f"📉 Loss trade #{self.loss_trades_today}/{self.max_loss_trades_per_day} recorded. {'⛔ MAX LOSS TRADES REACHED — stopping for the day!' if self.loss_trades_today >= self.max_loss_trades_per_day else ''}", flush=True)
        elif result == "profit":
            if getattr(self, 'paper_trading', True):
                self.paper_trades_today = max(0, getattr(self, 'paper_trades_today', 0) - 1)
            else:
                self.live_trades_today = max(0, getattr(self, 'live_trades_today', 0) - 1)
            print(f"🎉 Profitable trade closed! Reclaiming 1 trade limit. Current trades: {self.trades_today}/{self.max_trades_per_day}", flush=True)
        
        # ADDITIVE trade-outcome tracking (win-rate recording). Best-effort ONLY — this must
        # NEVER affect trade execution/exit logic. Any failure is caught and logged.
        try:
            self._record_trade_outcome_async(pos=pos, exit_price=exit_price, pnl=pnl)
        except Exception as e:
            print(f"⚠️ Trade-outcome tracking skipped (non-fatal): {e}", flush=True)

        self.save()
        cooldown = self._get_cooldown_minutes()
        print(f"⏳ Trade closed ({result}). Dynamic cooldown: {cooldown} minutes before next trade.", flush=True)

    def _record_trade_outcome_async(self, pos=None, exit_price=0.0, pnl=0.0):
        """Fire-and-forget scheduler for ADDITIVE win-rate recording at trade close.

        Looks up the still-present active-trade dict by symbol (removal happens AFTER
        record_trade_close) to recover strategy + entry context, then schedules the async
        DB write on the running event loop. Wrapped so a DB failure never breaks the close.
        """
        symbol = None
        if isinstance(pos, dict):
            symbol = pos.get("symbol")
        if not symbol:
            return

        active = next((t for t in self.active_auto_trades if t.get("symbol") == symbol), None)
        strategy = (active.get("strategy") if active else None) or (pos.get("strategy") if isinstance(pos, dict) else None)
        if not strategy:
            # No strategy name -> nothing meaningful to attribute the outcome to.
            return

        entry_price = float(active.get("entry_price", 0.0)) if active else 0.0
        entry_regime = (active.get("entry_regime") if active else None) or "NEUTRAL"
        entry_trend = (active.get("entry_trend") if active else None) or "N/A"
        market_trend = f"regime={entry_regime};trend={entry_trend}"

        raw_entry_time = active.get("entry_time") if active else None
        try:
            if isinstance(raw_entry_time, (int, float)):
                entry_time_str = datetime.fromtimestamp(raw_entry_time, IST).strftime("%Y-%m-%d %H:%M:%S")
            elif raw_entry_time:
                entry_time_str = str(raw_entry_time)
            else:
                entry_time_str = ""
        except Exception:
            entry_time_str = str(raw_entry_time) if raw_entry_time else ""
        exit_time_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

        from models import Database

        async def _persist():
            try:
                await Database.record_trade_outcome(
                    strategy_name=strategy, symbol=symbol,
                    entry_time=entry_time_str, exit_time=exit_time_str,
                    entry_price=entry_price, exit_price=float(exit_price or 0.0),
                    pnl=float(pnl or 0.0), vix=0.0, market_trend=market_trend,
                )
            except Exception as e:
                print(f"⚠️ record_trade_outcome DB write failed (non-fatal): {e}", flush=True)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist())
        except RuntimeError:
            # No running loop (e.g. called from a sync/test context) — run to completion.
            try:
                asyncio.run(_persist())
            except Exception as e:
                print(f"⚠️ record_trade_outcome fallback run failed (non-fatal): {e}", flush=True)

    def record_loss(self):
        self.last_loss_time = time.time()
        self.save()

    def update_pnl(self, current_pnl):
        # Prevent "ghost" PnL from yesterday bleeding into today before Fyers clears it
        now = datetime.now(IST)
        if now.hour < 9 or (now.hour == 9 and now.minute < 15):
            return

        # We track realized + unrealized for the day
        if getattr(self, 'paper_trading', True):
            self.paper_pnl_today = current_pnl
        else:
            self.live_pnl_today = current_pnl
        if self.pnl_today >= self.daily_profit_target:
            self.profit_target_met = True
        self.save()

    def add_active_trade(self, symbol, entry_price, sl_points, side, sl_order_id, tgt_order_id, strategy=None, target_1=None, target_2=None, target_points=0.0, sl_order_type=4, fvl_target=None, bars_held=0, entry_time=None, latest_hl_lh=None, qty=0, entry_trend=None):
        sl_price = entry_price - sl_points if side.upper() == "BUY" else entry_price + sl_points
        target_price = entry_price + target_points if side.upper() == "BUY" else entry_price - target_points
        # ADDITIVE: capture market context at ENTRY so trade-outcome tracking can later answer
        # "which regime/trend combos actually win". market_regime is a module-level global in state.py.
        try:
            import state as _state_mod
            entry_regime = getattr(_state_mod, "market_regime", "NEUTRAL")
        except Exception:
            entry_regime = "NEUTRAL"
        self.active_auto_trades.append({
            "symbol": symbol,
            "entry_price": entry_price,
            "qty": qty,
            "entry_regime": entry_regime,
            "entry_trend": entry_trend,
            "sl_points": sl_points,
            "sl_price": sl_price,
            "target_points": target_points,
            "target_price": target_price,
            "side": side,
            "sl_order_id": sl_order_id,
            "tgt_order_id": tgt_order_id,
            "sl_order_type": sl_order_type,
            "strategy": strategy,
            "target_1": target_1,
            "target_2": target_2,
            "fvl_target": fvl_target,
            "bars_held": bars_held,
            "entry_time": entry_time or time.time(),
            "trailed": False,
            "last_trail_step": 0,
            "opened_at": time.time(),
            "latest_hl_lh": latest_hl_lh
        })
        
        # Send Webhook Alert
        target_str = f"₹{target_price:.2f}" if target_points > 0 else "Trailing SL"
        strategy_label = strategy or 'Unknown Strategy'
        qty_str = f"📦 <b>Qty:</b> {qty}\n" if qty > 0 else ""
        msg = (
            f"🟢 <b>TRADE OPENED</b>\n"
            f"\n"
            f"🎯 <b>Strategy:</b> {strategy_label}\n"
            f"📊 <b>Symbol:</b> {symbol}\n"
            f"🔄 <b>Side:</b> {side}\n"
            f"{qty_str}"
            f"💵 <b>Entry:</b> ₹{entry_price:.2f}\n"
            f"🛡️ <b>Stop Loss:</b> ₹{sl_price:.2f} ({sl_points:.1f}pts)\n"
            f"🎯 <b>Target:</b> {target_str}"
        )
        trigger_webhook_background(self.webhook_url, msg, title="Trade Executed")
        
        self.save()

    def update_trade_sl_price(self, sl_order_id, new_sl):
        for t in self.active_auto_trades:
            if t["sl_order_id"] == sl_order_id:
                t["sl_price"] = new_sl
                break
        self.save()

    def mark_trade_trailed(self, sl_order_id):
        for t in self.active_auto_trades:
            if t["sl_order_id"] == sl_order_id:
                t["trailed"] = True
                break
        self.save()

    def update_trade_trail_step(self, sl_order_id, step):
        for t in self.active_auto_trades:
            if t["sl_order_id"] == sl_order_id:
                t["last_trail_step"] = step
                break
        self.save()

    def remove_active_trade(self, symbol):
        self.active_auto_trades = [t for t in self.active_auto_trades if t["symbol"] != symbol]
        self.save()

    def get_trading_config(self):
        """Return current configurable trading parameters."""
        return {
            "max_trades_per_day": self.max_trades_per_day,
            "max_daily_loss": self.max_loss_per_day,
            "max_loss_trades_per_day": getattr(self, 'max_loss_trades_per_day', 2),
            "daily_profit_target": self.daily_profit_target,
            "webhook_url": self.webhook_url,
            "max_sl_trending": self.max_sl_trending,
            "max_sl_range": self.max_sl_range,
            "trail_sl_step": self.trail_sl_step,
            "trade_lots": self.trade_lots,
            "stock_lots": getattr(self, "stock_lots", 1),
            "mcx_lots": getattr(self, "mcx_lots", 1),
            "enabled_symbols": getattr(self, "enabled_symbols", ["NSE:NIFTY50-INDEX"]),
            "paper_trading": self.paper_trading,
            "active_strategies": self.active_strategies,
            "use_ai_oracle": getattr(self, "use_ai_oracle", False),
            "ai_daily_bias": getattr(self, "ai_daily_bias", "")
        }

    def update_trading_config(self, config):
        """Update configurable trading parameters from user input."""
        if "max_trades_per_day" in config:
            self.max_trades_per_day = max(1, int(config["max_trades_per_day"]))
        if "max_daily_loss" in config:
            self.max_loss_per_day = max(100.0, float(config["max_daily_loss"]))
        if "max_loss_trades_per_day" in config:
            self.max_loss_trades_per_day = max(1, int(config["max_loss_trades_per_day"]))
        if "daily_profit_target" in config:
            self.daily_profit_target = max(500.0, float(config["daily_profit_target"]))
        if "webhook_url" in config:
            self.webhook_url = str(config["webhook_url"]).strip()
        if "max_sl_trending" in config:
            self.max_sl_trending = max(3.0, float(config["max_sl_trending"]))
        if "max_sl_range" in config:
            self.max_sl_range = max(3.0, float(config["max_sl_range"]))
        if "trail_sl_step" in config:
            self.trail_sl_step = max(1.0, float(config["trail_sl_step"]))
        if "trade_lots" in config:
            self.trade_lots = max(1, int(config["trade_lots"]))
        if "stock_lots" in config:
            self.stock_lots = max(1, int(config["stock_lots"]))
        if "mcx_lots" in config:
            self.mcx_lots = max(1, int(config["mcx_lots"]))
        if "enabled_symbols" in config:
            self.enabled_symbols = config["enabled_symbols"]
        if "paper_trading" in config:
            self.paper_trading = bool(config["paper_trading"])
        if "active_strategies" in config:
            self.active_strategies = list(config["active_strategies"])
        if "use_ai_oracle" in config:
            self.use_ai_oracle = bool(config["use_ai_oracle"])
        if "ai_daily_bias" in config:
            self.ai_daily_bias = str(config["ai_daily_bias"])
        self.save()
        print(f"⚙️ Trading config updated: MaxLossTrades={self.max_loss_trades_per_day}, Lots={self.trade_lots}, PaperTrading={self.paper_trading}, MaxLoss=₹{self.max_loss_per_day}, ProfitTarget=₹{self.daily_profit_target}, SL_Trend={self.max_sl_trending}pts, SL_Range={self.max_sl_range}pts, Trail_Step={self.trail_sl_step}pts", flush=True)

    def check_and_send_eod_report(self):
        """Check if market is closed for the day and send EOD report."""
        if not self.webhook_url:
            return

        now = datetime.now(IST)
        current_date_str = now.date().isoformat()
        
        # Check if time is >= 15:30 IST
        market_end_today = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        # Only send if market has closed today AND we haven't sent it yet today
        if now >= market_end_today and self.eod_report_sent_date != current_date_str:
            closed_trades = getattr(self, 'closed_trades_today', [])
            msg = (
                f"📊 <b>End of Day Report</b>\n\n"
                f"🗓️ Date: {current_date_str}\n"
                f"💰 <b>Total PnL Today:</b> ₹{self.pnl_today:.2f}\n"
                f"📈 <b>Total Trades Taken:</b> {len(closed_trades)}"
            )
            
            if closed_trades:
                msg += "\n\n<b>Trade Breakdown:</b>\n"
                for i, t in enumerate(closed_trades, 1):
                    p_icon = "🟢" if t['pnl'] > 0 else "🔴" if t['pnl'] < 0 else "⚪"
                    msg += f"{i}. {t['symbol']}: {p_icon} ₹{t['pnl']:.2f}\n"
            
            trigger_webhook_background(self.webhook_url, msg, title="Market Closed")
            
            self.eod_report_sent_date = current_date_str
            self.save()
            print(f"📊 EOD Report sent for User {self.user_id} on {current_date_str}")

    def check_and_send_holiday_report(self):
        """Check if today is a market holiday and send Telegram alert once a day."""
        if not self.webhook_url:
            return

        from state import get_holiday_reason
        reason = get_holiday_reason()
        if not reason:
            return

        now = datetime.now(IST)
        current_date_str = now.date().isoformat()

        # Send holiday alert starting at 9:00 AM IST on the holiday
        alert_time_today = now.replace(hour=9, minute=0, second=0, microsecond=0)

        # Get holiday_report_sent_date (handle dynamic property creation)
        sent_date = getattr(self, "holiday_report_sent_date", "")

        if now >= alert_time_today and sent_date != current_date_str:
            msg = (
                f"⚠️ <b>Market Trading is Closed today</b>\n\n"
                f"🗓️ Date: {current_date_str}\n"
                f"🛑 <b>Status:</b> Market Holiday\n"
                f"📌 <b>Reason:</b> {reason}\n"
                f"🌐 <b>Details:</b> Refer to www.nseindia.com for segment holidays."
            )
            
            trigger_webhook_background(self.webhook_url, msg, title="Market Holiday Alert")
            
            self.holiday_report_sent_date = current_date_str
            self.save()
            print(f"🛑 Market Holiday Report sent to Telegram for User {self.user_id} on {current_date_str}: {reason}", flush=True)

    def check_and_run_nightly_learning(self):
        """Trigger Nightly Learning Agent once per day after market close (15:35 IST)."""
        now = datetime.now(IST)
        current_date_str = now.date().isoformat()
        
        # Run at 15:35 to ensure all EOD reports and flushes are done
        market_end_learning = now.replace(hour=15, minute=35, second=0, microsecond=0)
        
        sent_date = getattr(self, "nightly_learning_date", "")
        
        if now >= market_end_learning and sent_date != current_date_str:
            print(f"🌙 Triggering Nightly Learning for User {self.user_id}...", flush=True)
            import asyncio
            from engine.nightly_learning import run_nightly_learning
            
            # Fire and forget task to avoid blocking the state loop
            try:
                # We need the main event loop to run this async task
                from state import main_loop
                if main_loop and main_loop.is_running():
                    main_loop.create_task(run_nightly_learning(self, self.user_id))
                else:
                    asyncio.create_task(run_nightly_learning(self, self.user_id))
            except Exception as e:
                print(f"Failed to launch Nightly Learning task: {e}", flush=True)
                
            self.nightly_learning_date = current_date_str
            self.save()
