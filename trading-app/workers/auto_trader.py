"""
Automated trading background tasks.

- `trailing_monitor`: monitors active auto-trades, enforces max-loss exit, and
  trails ALL stops with the LOCKED 3×1m option-candle rule (no strategy overrides).
- `calculate_smart_sl`: LOCKED initial SL = same rule as trail (entry − last-3 1m low).
- `execute_auto_trade`: places a confirmed auto-trade (BUY-only policy) with
  canonical smart SL for EVERY strategy (signal sl_points are ignored for placement).
- `automation_loop`: top-level scheduler that evaluates Strategy 2 / 3 / 1 per
  active user and dispatches `execute_auto_trade` when guards pass.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Dict, Tuple

from state import (
    IST,
    USER_CONTEXTS,
    broadcast_log,
    get_lot_size,
    get_user_cache,
    get_user_state,
    is_market_open,
    logger,
    DAILY_DRAWDOWN_LIMIT_PCT,
)
from engine.api_queue import api_queue
from engine.notifier import trigger_webhook_background
from engine.logger import log_signal, log_trade
from engine.strategy_926 import evaluate_926_strategy
from engine.strategy_orb import evaluate_orb_strategy
from engine.strategy_wisdom import evaluate_wisdom_strategy
from engine.strategy_5 import evaluate_strat5_strategy
from engine.strikes import get_strike_recommendations
from engine.ws_feed import ws_feed
from engine.risk_orchestrator import orchestrator as risk_orchestrator
from datetime import timedelta
from fyers_client import compute_sl_limit_price, get_price_tick, round_to_tick

# B1: how long a previously-open position must stay absent from the broker feed before the
# monitor treats it as closed (feed omission). Long enough to ride out a transient/partial
# snapshot, short enough that stale entries do not linger indefinitely.
POSITION_ABSENCE_GRACE_SECONDS = 30

# 03-08-26 fix: Crude Evening Momentum / EIA Volatility used to market-buy the instant their raw
# signal fired — which, on MCX's frequently choppy/range-bound sessions, meant buying right at the
# local extreme of the move just before it mean-reverted. Raw signals now queue as a pending order
# and must (1) survive one more candle without reversing (confirmation) and (2) wait for price to
# retrace back toward the signal level (pullback entry, cheaper premium + proof the level holds)
# before actually trading. See run_crude_strats() in execute_auto_trade().
CRUDE_PENDING_MAX_CANDLES = 4       # give up waiting for confirmation/pullback after this many new candles
CRUDE_PULLBACK_ATR_MULT = 0.4       # retracement target, as a multiple of recent avg candle range
CRUDE_PULLBACK_MIN_POINTS = 1.0     # floor so the retracement target is never ~0 in a dead-quiet tape

# Strategies that FADE the move (buy PE after gap-up / sell strength). In a one-sided market
# they fight the trend and bleed — hard-disabled at execute + stripped from active list on load.
_FADE_STRATEGY_PREFIXES = (
    "Strategy 5: Optimized Aerospace Mean Reversion",
    "Strategy 6: Gap Fill Reversal",
)

def _is_fade_strategy(name: str) -> bool:
    n = name or ""
    return any(n.startswith(p) or p in n for p in _FADE_STRATEGY_PREFIXES)


async def _is_chase_entry(client, strike_symbol: str, entry_price: float) -> Tuple[bool, str]:
    """True if entry is at/near the last-5 one-min highs (buy-high / chase after expansion)."""
    try:
        candles = await api_queue.enqueue(2, client.get_historical, strike_symbol, "1", 1)
        if not candles or len(candles) < 3 or entry_price <= 0:
            return False, ""
        recent = candles[-5:] if len(candles) >= 5 else candles
        local_high = max(float(c.get("high") or 0) for c in recent)
        if local_high <= 0:
            return False, ""
        # Within 0.8% of the local high = chasing the spike
        if entry_price >= local_high * 0.992:
            return True, f"entry ₹{entry_price:.2f} near 5×1m high ₹{local_high:.2f}"
        return False, ""
    except Exception as e:
        logger.warning(f"Anti-chase check failed for {strike_symbol}: {e}")
        return False, ""


# Maps an equity strategy name -> its commodity-family equivalent. A strategy with NO mapping here
# does NOT run on commodity (MCX/CDS) symbols at all. This is how the equity and commodity strategy
# families are kept separate: equity symbols gate on state.active_strategies, MCX symbols gate on
# state.commodity_strategies via this map.
_COMMODITY_STRAT_MAP = {
    "Strategy 3: 5-Minute ORB": "Commodity: 5-Minute ORB",
    "Strategy 9: 9-EMA Momentum Scalper": "Commodity: 9-EMA Momentum",
    "Strategy 7: Swing-Pivot Breakout": "Commodity: Swing-Pivot Breakout",
}

# ── Pending-entry-order watchdog (owner rule 27-07-26): cancel an order not EXECUTED within 2 min ──
# Entry orders are placed as LIMIT Cover Orders (limit_price forces LIMIT), so an entry can rest
# unfilled if the market moves away. We track each placed ENTRY order id + placement time; a
# background watchdog cancels any that is still pending after PENDING_ORDER_TIMEOUT so stale price
# levels don't tie up margin. A FILLED entry (which now holds a position + live SL leg) is removed
# untouched — the watchdog never cancels the SL leg.
PENDING_ENTRY_ORDERS = {}          # str(order_id) -> {"ts": epoch, "symbol": str, "user_id": int}
PENDING_ORDER_TIMEOUT = 120        # seconds (2 minutes)

# ═══════════════════════════════════════════════════════════════════════════
# LOCKED OWNER RULE (03-08-26) — DO NOT CHANGE without explicit owner approval
# Initial SL and Trailing SL (TSL) are IDENTICAL for EVERY strategy, always:
#   BUY option → stop trigger = lowest low of the last 3 one-minute OPTION candles
#   Trail only RAISES the stop from that level (never widens, never %/ATR/1R/BE
#   strategy-specific trail). Signal-provided sl_points are IGNORED at placement.
# ═══════════════════════════════════════════════════════════════════════════
CANONICAL_SL_LOOKBACK = 3
CANONICAL_SL_RESOLUTION = "1"


def track_pending_order(order_id, symbol, user_id, sl_order_id=None, tgt_order_id=None):
    """Register a just-placed entry order for the 2-minute fill watchdog."""
    if order_id:
        try:
            PENDING_ENTRY_ORDERS[str(order_id)] = {
                "ts": time.time(), 
                "symbol": symbol, 
                "user_id": int(user_id),
                "sl_order_id": sl_order_id,
                "tgt_order_id": tgt_order_id
            }
        except Exception:
            pass


async def pending_order_watchdog():
    """Cancel entry orders not executed within PENDING_ORDER_TIMEOUT (2 min). Only cancels orders
    still PENDING/TRANSIT; filled/cancelled/rejected orders are simply untracked. Fyers order
    status: 2=traded(filled), 1=cancelled, 5=rejected, 6=pending, 4=transit."""
    import asyncio
    while True:
        try:
            await asyncio.sleep(15)
            if not PENDING_ENTRY_ORDERS:
                continue
            now = time.time()
            due = [(oid, m) for oid, m in list(PENDING_ENTRY_ORDERS.items())
                   if now - m.get("ts", 0) >= PENDING_ORDER_TIMEOUT]
            for oid, meta in due:
                uid = meta.get("user_id", 1)
                client = USER_CONTEXTS.get(uid) or USER_CONTEXTS.get(int(uid)) or USER_CONTEXTS.get(str(uid))
                if not client:
                    PENDING_ENTRY_ORDERS.pop(oid, None)
                    continue
                try:
                    orders = await api_queue.enqueue(2, client.get_orders) or []
                    o = next((x for x in orders if str(x.get("id")) == str(oid)), None)
                    status = o.get("status") if o else None
                    if status == 2:
                        logger.info(f"⏱️ Order watchdog: {oid} ({meta['symbol']}) already FILLED — untracking.")
                        PENDING_ENTRY_ORDERS.pop(oid, None)
                    elif o is None or status in (1, 5):
                        PENDING_ENTRY_ORDERS.pop(oid, None)  # gone/cancelled/rejected already
                    else:
                        # still pending/transit after 2 min -> cancel it
                        res = await asyncio.to_thread(client.cancel_order, oid)
                        ok = isinstance(res, dict) and (res.get("success") or res.get("s") == "ok")
                        
                        # Cancel associated SL and TGT orders if any
                        sl_oid = meta.get("sl_order_id")
                        tgt_oid = meta.get("tgt_order_id")
                        if sl_oid:
                            await asyncio.to_thread(client.cancel_order, sl_oid)
                        if tgt_oid:
                            await asyncio.to_thread(client.cancel_order, tgt_oid)

                        logger.info(f"🚫 Order watchdog: cancelled {oid} ({meta['symbol']}) — not executed within {PENDING_ORDER_TIMEOUT}s (ok={ok}).")
                        try:
                            await broadcast_log(f"🚫 {meta['symbol']} order not filled in 2 min — cancelled.", "warning", user_id=uid)
                        except Exception:
                            pass
                        PENDING_ENTRY_ORDERS.pop(oid, None)
                except Exception as e:
                    logger.warning(f"Order watchdog error for {oid}: {e}")
                    PENDING_ENTRY_ORDERS.pop(oid, None)  # never retry-loop forever on one order
        except Exception as e:
            logger.error(f"pending_order_watchdog loop error: {e}")


def _strat_enabled_for(state, equity_strat_name: str, symbol: str) -> bool:
    """Asset-class-aware strategy gate. For an equity/index/stock symbol, the (equity) strategy is
    enabled iff it's in state.active_strategies. For an MCX/CDS commodity symbol, the strategy runs
    iff it has a commodity-family equivalent that's enabled in state.commodity_strategies — so the
    two families are fully independent and never affect each other."""
    is_commodity = symbol.startswith("MCX:") or symbol.startswith("CDS:")
    if is_commodity:
        com_name = _COMMODITY_STRAT_MAP.get(equity_strat_name)
        return bool(com_name) and com_name in getattr(state, "commodity_strategies", [])
    return equity_strat_name in getattr(state, "active_strategies", [])


def _strat3_orb_window_ok(now_str: str) -> bool:
    """Strategy 3 (5-Min ORB) evaluation window check -- pure, no side effects, no I/O.
    Matches strategy_orb.py's own 10:30:00 expiry boundary exactly (see strategy_orb.py:83).
    Extracted so the window-widen fix is unit-testable without driving automation_loop()."""
    return "09:20:00" <= now_str <= "10:30:00"


def _opt_base(s):
    """Alpha-prefix of an option/futures symbol, e.g. 'MCX:CRUDEOIL26AUG7500PE' -> 'CRUDEOIL',
    'NSE:NIFTY50-INDEX' -> 'NIFTY', 'NSE:NIFTY2680424600CE' -> 'NIFTY'. Reliably means "same
    underlying" for both index/stock options and commodity options."""
    s = (s or "").upper().split(":")[-1]
    base = ""
    for ch in s:
        if ch.isalpha():
            base += ch
        else:
            break
    return base


def is_symbol_expiry_today(sym: str) -> bool:
    """Checks if the given Fyers option symbol expires today."""
    now = datetime.now(IST)
    yy = now.strftime("%y")
    
    # Weekly format
    month_map = {10: "O", 11: "N", 12: "D"}
    m_code = month_map.get(now.month, str(now.month))
    dd = now.strftime("%d")
    today_weekly = f"{yy}{m_code}{dd}"
    
    # Monthly format
    mmm = now.strftime("%b").upper()
    today_monthly = f"{yy}{mmm}"
    
    # Check if either today's weekly or monthly code is in the symbol
    # Fyers format is e.g. NSE:NIFTY2661623500CE
    return f"NIFTY{today_weekly}" in sym or f"NIFTY{today_monthly}" in sym


def aggregate_position_pnl(positions):
    """B2: sum the `pl` field across positions WITHOUT silently treating a missing/malformed
    `pl` as ₹0.

    A broker response missing `pl` (or with a non-numeric value) must not make the max-loss
    emergency-exit check look better than reality. Returns a 3-tuple:
      (total_pnl, incomplete, bad_symbols)
    where `total_pnl` sums only the positions whose `pl` is a valid number, `incomplete` is
    True when at least one position had a missing/non-numeric `pl` (so callers can alert and
    treat the aggregate as unreliable rather than acting on a falsely-small loss), and
    `bad_symbols` lists the offending positions' symbols for the alert message.
    """
    total = 0.0
    incomplete = False
    bad_symbols = []
    for p in (positions or []):
        raw = p.get("pl", None)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            # Missing, None, string, or bool -> not a trustworthy numeric P&L.
            incomplete = True
            bad_symbols.append(p.get("symbol", "?"))
            continue
        total += raw
    return total, incomplete, bad_symbols


async def trailing_monitor():
    """Background task to monitor active auto-trades, trail SL, and enforce max loss limit."""

    while True:
        # B3: isolate each user's iteration in its own try/except so one user's malformed
        # data or unexpected exception cannot abort the monitoring tick for every other user.
        # A failure here logs and `continue`s to the next user instead of unwinding the loop.
        for u_id, client in list(USER_CONTEXTS.items()):
            try:
                state = get_user_state(u_id)
                MAX_LOSS_LIMIT = -abs(state.max_loss_per_day)

                if not state.active_auto_trades:
                    continue

                try:
                    if not await api_queue.enqueue(2, client.is_authenticated):
                        continue
                except Exception:
                    continue

                # ═══════════════════════════════════════════
                # RISK CONTROLS (per user policy)
                #  - Per-trade risk = each trade's own SL (CO leg + 3-candle trail).
                #  - CATASTROPHIC single-trade seatbelt: only if a trade's SL FAILED and its live
                #    loss runs away to -₹5,500 do we force-close ONLY that trade (never the whole
                #    day). Bad-tick guarded so a contaminated LTP can't trigger it (Issue 2).
                #  - Daily stop is on REALIZED (booked) loss: when closed-trade losses cross the
                #    daily limit (max_loss_per_day, e.g. ₹2,500) stop the day. Winning trades never
                #    count. No more full-day shutdown on a single open trade's temporary dip.
                # ═══════════════════════════════════════════
                CATASTROPHIC_SINGLE_TRADE = -5500.0

                cache = get_user_cache(u_id)
                positions = cache.get("active_positions", [])
                has_open = any(p.get("netQty", 0) != 0 or p.get("qty", 0) != 0 for p in positions)

                # (1) Single-trade catastrophic seatbelt — SL-failure last resort (bad-tick guarded).
                if state.active_auto_trades and ws_feed.is_connected():
                    _quotes = ws_feed.get_quotes_from_ws([t["symbol"] for t in state.active_auto_trades])
                    for t in list(state.active_auto_trades):
                        sym = t["symbol"]
                        ltp = (_quotes.get(sym, {}) or {}).get("lp", 0)
                        if ltp <= 0:
                            continue
                        entry = t["entry_price"]
                        side = t.get("side", "BUY")
                        qty_val = t.get("qty", 0) or (state.trade_lots * get_lot_size(sym))
                        _pos = next((p for p in positions if p.get("symbol") == sym), None)
                        if _pos:
                            qty_val = abs(_pos.get("qty", qty_val))
                        trade_mtm = (ltp - entry) * qty_val if side == "BUY" else (entry - ltp) * qty_val
                        if trade_mtm <= CATASTROPHIC_SINGLE_TRADE:
                            # Issue 2 bad-tick guard: re-confirm with a FRESH quote before acting.
                            _fresh = await api_queue.enqueue(2, client.get_quote, sym)
                            _fltp = (_fresh or {}).get("lp", 0)
                            if _fltp <= 0:
                                continue
                            _fmtm = (_fltp - entry) * qty_val if side == "BUY" else (entry - _fltp) * qty_val
                            if _fmtm > CATASTROPHIC_SINGLE_TRADE:
                                logger.warning(f"⚠️ Catastrophic MTM for {sym} NOT confirmed by fresh quote (tick={ltp}, fresh={_fltp}) — ignoring as bad tick.")
                                continue
                            logger.warning(f"🚨 Catastrophic loss on {sym}: ₹{_fmtm:.0f} <= ₹{CATASTROPHIC_SINGLE_TRADE:.0f} — force-closing THIS trade only (SL failed).")
                            await broadcast_log(f"🚨 Force-closing {sym}: catastrophic loss ₹{abs(_fmtm):.0f} (SL failed).", "error", user_id=u_id, telegram_alert=True)
                            try:
                                _cqty = abs(_pos.get("qty", qty_val)) if _pos else int(qty_val)
                                _exit_side = "SELL" if side == "BUY" else "BUY"
                                _prod = "INTRADAY"
                                if client._is_option_symbol(sym):
                                    if _pos:
                                        _prod = client._position_product(_pos) or client.resolve_exit_product(sym)
                                    else:
                                        _prod = client.resolve_exit_product(sym)
                                    if _exit_side != "SELL":
                                        logger.error(f"Catastrophic close blocked for {sym}: options buy-only (refusing BUY-to-cover)")
                                        continue
                                await api_queue.enqueue(
                                    1, client.place_order,
                                    symbol=sym, qty=_cqty, side=_exit_side,
                                    order_type="MARKET", product=_prod, is_exit=True,
                                    sl_points=0.0, target_points=0.0,
                                )
                            except Exception as _e:
                                logger.error(f"Catastrophic force-close error for {sym}: {_e}")
                            _cat_strat = ""
                            try:
                                _at = next((t for t in state.active_auto_trades if t.get("symbol") == sym), None)
                                _cat_strat = (_at or {}).get("strategy", "") or ""
                            except Exception:
                                _cat_strat = ""
                            state.record_trade_close(
                                "loss",
                                pos={"side": side, "symbol": sym, "strategy": _cat_strat},
                                exit_price=_fltp, pnl=_fmtm,
                                reason="Catastrophic SL-failure force-close",
                            )
                            state.remove_active_trade(sym)
                            state.save()

                # (2) Floating P&L for the UI ONLY (never used to STOP the day).
                if not has_open and state.trades_today == 0:
                    total_pnl = 0.0
                else:
                    total_pnl, pnl_incomplete, bad_pl_symbols = aggregate_position_pnl(positions)
                    if pnl_incomplete:
                        logger.error(f"⚠️ Incomplete P&L for user {u_id}: positions missing/malformed 'pl': {bad_pl_symbols}")
                state.update_pnl(total_pnl)

                # ═══════════════════════════════════════════
                # GLOBAL KILL SWITCH (TOTAL PNL = REALIZED + FLOATING)
                # ═══════════════════════════════════════════
                # If TOTAL daily PnL drops below the max limit, we physically lock the database
                # and block fyers_client from executing ANY trades until manually reset tomorrow.
                from engine.api_queue import api_queue
                from models import Database
                if total_pnl <= -abs(state.max_loss_per_day):
                    if not Database.is_kill_switch_active():
                        logger.critical(f"🛑 [CIRCUIT BREAKER] TOTAL PNL ₹{total_pnl:.0f} hit limit -₹{abs(state.max_loss_per_day):.0f}. ENGAGING KILL SWITCH!")
                        Database.engage_kill_switch(f"Max Loss Breached: ₹{total_pnl:.0f}")
                        
                        await broadcast_log(f"🛑 SYSTEM LOCKED: Max loss ₹{abs(total_pnl):.0f} reached. Kill Switch Active.", "error", user_id=u_id, telegram_alert=True)
                        state.automation_enabled = False
                        state.hard_exit_triggered = True
                        state.square_off_in_progress = True
                        
                        # Liquidate everything instantly
                        for _p in [p for p in positions if p.get("qty", 0) != 0]:
                            try:
                                _cqty = abs(_p.get("qty", 0))
                                _sym = _p.get("symbol", "")
                                _net = client._position_net_qty(_p) if hasattr(client, "_position_net_qty") else int(_p.get("qty", 0) or 0)
                                # Options buy-only: only SELL to close longs; never BUY-to-cover a short.
                                if client._is_option_symbol(_sym):
                                    if _net <= 0:
                                        logger.error(f"Kill-Switch skip {_sym}: no long option to close (buy-only)")
                                        continue
                                    _side_str = "SELL"
                                    _prod = client._position_product(_p) or client.resolve_exit_product(_sym)
                                else:
                                    _side_str = "SELL" if _net > 0 else "BUY"
                                    _prod = client._position_product(_p) or "INTRADAY"
                                await api_queue.enqueue(
                                    1, client.place_order,
                                    symbol=_sym, qty=_cqty, side=_side_str,
                                    order_type="MARKET", product=_prod, is_exit=True,
                                    sl_points=0.0, target_points=0.0,
                                )
                            except Exception as _e:
                                logger.error(f"Kill-Switch Liquidation error: {_e}")
                        
                        # Cancel all pending orders
                        try:
                            _orders = await api_queue.enqueue(2, client.client.orderbook)
                            if isinstance(_orders, dict) and "orderBook" in _orders:
                                for _ord in _orders["orderBook"]:
                                    if _ord.get("status") in (1, 6): # Pending
                                        await api_queue.enqueue(2, client.client.cancel_order, {"id": _ord["id"]})
                        except Exception as _e:
                            logger.error(f"Kill-Switch Cancel Pending error: {_e}")
                            
                        state.active_auto_trades = []
                        state.square_off_in_progress = False
                        state.save()
                    continue

                # (3) Daily REALIZED-loss stop: stop the whole day ONLY when BOOKED losses cross the
                # limit. Winning trades never count toward it.
                DAILY_LOSS_LIMIT = -abs(state.max_loss_per_day)
                realized_pnl = sum(float(ct.get("pnl", 0) or 0) for ct in getattr(state, "closed_trades_today", []))
                if realized_pnl <= DAILY_LOSS_LIMIT:
                    logger.warning(f"🚨 DAILY REALIZED-LOSS LIMIT: booked ₹{realized_pnl:.0f} <= ₹{DAILY_LOSS_LIMIT:.0f} — stopping for the day.")
                    await broadcast_log(f"🛑 Daily loss limit hit: booked loss ₹{abs(realized_pnl):.0f}. Trading stopped for the day.", "error", user_id=u_id, telegram_alert=True)
                    state.automation_enabled = False
                    state.hard_exit_triggered = True
                    state.square_off_in_progress = True
                    for _p in [p for p in positions if p.get("qty", 0) != 0]:
                        try:
                            _sym = _p.get("symbol", "")
                            _net = client._position_net_qty(_p)
                            if client._is_option_symbol(_sym):
                                if _net <= 0:
                                    continue
                                _side = "SELL"
                                _prod = client._position_product(_p) or client.resolve_exit_product(_sym)
                            else:
                                _side = "SELL" if _net > 0 else "BUY"
                                _prod = client._position_product(_p) or "INTRADAY"
                            await api_queue.enqueue(
                                1, client.place_order,
                                symbol=_sym, qty=abs(_p.get("qty", 0)),
                                side=_side, order_type="MARKET", product=_prod,
                                is_exit=True, sl_points=0.0, target_points=0.0,
                            )
                        except Exception as _e:
                            logger.error(f"Daily-stop square-off error: {_e}")
                    state.active_auto_trades = []
                    state.square_off_in_progress = False
                    state.save()

                    await broadcast_log("🛑 AUTOMATION DISABLED — Max loss limit hit. All positions exited.", "error")
                    continue

                # ═══════════════════════════════════════════
                # CLEANUP COMPLETED TRADES
                # ═══════════════════════════════════════════
                completed_trades = []
                for t in state.active_auto_trades:
                    # Skip cleanup if the trade was opened less than 20 seconds ago
                    if time.time() - t.get("opened_at", 0) < 20:
                        continue
                    sym = t["symbol"]
                    pos = next((p for p in positions if p.get("symbol") == sym), None)
                    if pos is not None and abs(pos.get("qty", 0)) == 0:
                        # Position present in feed with qty 0 -> definitively closed.
                        t.pop("missing_since", None)
                        completed_trades.append((sym, pos))
                    elif pos is None:
                        # B1: the broker feed omitted this previously-open position. Many brokers
                        # drop a fully-closed position from the snapshot instead of reporting
                        # qty==0, so treat sustained absence as a completion candidate — but only
                        # after a grace period so a transient empty/partial feed does not misfire.
                        missing_since = t.get("missing_since")
                        if missing_since is None:
                            t["missing_since"] = time.time()
                        elif time.time() - missing_since >= POSITION_ABSENCE_GRACE_SECONDS:
                            logger.warning(
                                f"🧹 Position {sym} absent from broker feed for "
                                f">{POSITION_ABSENCE_GRACE_SECONDS}s — treating as closed (feed omission)."
                            )
                            completed_trades.append((sym, None))
                    else:
                        # Present and still open -> reset any pending absence timer.
                        t.pop("missing_since", None)

                if completed_trades:
                    for sym, pos in completed_trades:
                        if pos is not None:
                            trade_pnl = pos.get("pl", 0)
                            # Usually if we bought, we sell to exit, so sellAvg is the exit price.
                            exit_price = pos.get("sellAvg", pos.get("buyAvg", 0))
                        else:
                            # Issue 3: broker dropped the closed position from the feed. Recover the
                            # REAL realized P&L (fresh positions -> trade book) so a WIN isn't logged
                            # as breakeven — which would starve the win-rate / self-improvement.
                            trade_pnl, exit_price, _src = await _recover_closed_pnl(client, sym)
                            logger.info(f"🔎 Recovered closed P&L for {sym}: ₹{trade_pnl:.2f} (source={_src}).")
                        _active_trade = next((t for t in state.active_auto_trades if t.get("symbol") == sym), None)
                        pos_info = {"side": "BUY", "symbol": sym, "strategy": _active_trade.get("strategy", "") if _active_trade else ""}
                        # Outcome-integrity guard: a broker position dict without sellAvg/buyAvg makes
                        # exit_price 0, and that 0 was being PERSISTED as a real outcome (see the
                        # 08-Jul swarm_trade_records rows: exit_price=0, pnl=0, on a +Rs2,2287 day).
                        # Recover from the last traded price and, either way, make the gap VISIBLE
                        # instead of silently writing a zero that corrupts win-rate analysis.
                        if not exit_price or exit_price <= 0:
                            _fallback = 0
                            try:
                                from engine.ws_feed import ws_feed as _wsf
                                _fallback = _wsf.get_ltp(sym) or 0
                            except Exception:
                                _fallback = 0
                            if _fallback > 0:
                                logger.warning(f"⚠️ exit_price missing for {sym} (broker dict had no sellAvg/buyAvg) "
                                               f"— using last traded price {_fallback}.")
                                exit_price = _fallback
                            else:
                                logger.warning(f"⚠️ exit_price UNAVAILABLE for {sym} — outcome will be recorded "
                                               f"WITHOUT a valid exit price; treat this row as unreliable.")
                        # PnL RECOVERY: If broker returns pl=0 but we have valid entry/exit prices,
                        # compute PnL manually. This prevents the "₹0 PnL on a winning day" corruption.
                        if trade_pnl == 0 and exit_price > 0:
                            _active_trade = next((t for t in state.active_auto_trades if t.get("symbol") == sym), None)
                            _entry = float(_active_trade.get("entry_price", 0)) if _active_trade else 0
                            if _entry > 0 and exit_price > _entry:
                                trade_pnl = round(exit_price - _entry, 2)
                                logger.warning(f"⚠️ {sym} broker pl=0 but entry={_entry}, exit={exit_price} → recovered PnL=₹{trade_pnl:.2f}")
                            elif _entry > 0 and exit_price < _entry:
                                trade_pnl = round(exit_price - _entry, 2)
                                logger.warning(f"⚠️ {sym} broker pl=0 but entry={_entry}, exit={exit_price} → recovered PnL=₹{trade_pnl:.2f}")
                        if trade_pnl == 0:
                            logger.warning(f"⚠️ {sym} closed with pnl=0 — verify this is a genuine breakeven "
                                           f"and not a P&L-recovery failure (this corrupts win-rate stats).")
                        if trade_pnl > 0:
                            # Profitable trade
                            state.record_trade_close("profit", pos=pos_info, exit_price=exit_price, pnl=trade_pnl, reason="Trailing Stop/Target Hit")  # 3 min cooldown
                            await broadcast_log(f"🎉 Trade PROFIT ₹{trade_pnl:.2f}! ⏳ Cooldown: 3 minutes before next trade.", "success", user_id=u_id, telegram_alert=True)
                        elif trade_pnl < 0:
                            # Loss trade
                            state.record_trade_close("loss", pos=pos_info, exit_price=exit_price, pnl=trade_pnl, reason="Stop Loss Hit")  # 5 min cooldown
                            await broadcast_log(f"📉 Trade LOSS ₹{trade_pnl:.2f}. ⏳ Cooldown: 5 minutes before next trade.", "warning", user_id=u_id, telegram_alert=True)
                        else:
                            # Breakeven
                            state.record_trade_close("breakeven", pos=pos_info, exit_price=exit_price, pnl=trade_pnl, reason="Breakeven Exit")  # 3 min cooldown
                            await broadcast_log(f"➖ Trade BREAKEVEN. ⏳ Cooldown: 3 minutes before next trade.", "info")
                        state.remove_active_trade(sym)
                    logger.info(f"🧹 Cleaned up completed trades: {[s for s, _ in completed_trades]}")

                # ═══════════════════════════════════════════
                # TRAILING SL MONITOR (10-Point Step Trailing)
                # ═══════════════════════════════════════════
                symbols = [t["symbol"] for t in state.active_auto_trades]
                if not symbols:
                    await asyncio.sleep(5)
                    continue

                # Try to get quotes from WS feed first
                quotes = ws_feed.get_quotes_from_ws(symbols) if ws_feed.is_connected() else {}
                missing_symbols = [s for s in symbols if s not in quotes]

                if missing_symbols:
                    rest_quotes = await api_queue.enqueue(2, client.get_quotes, missing_symbols)
                    quotes.update(rest_quotes)

                for t in state.active_auto_trades:
                    sym = t["symbol"]
                    quote = quotes.get(sym, {})
                    ltp = quote.get("lp", 0)
                    logger.info(f"🔍 TEMP-DEBUG trailing tick: sym={sym} ltp={ltp} sl_price={t.get('sl_price')} "
                                f"target_price={t.get('target_price')} side={t.get('side')} paper_trading={state.paper_trading} "
                                f"in_ws_quotes={sym in quotes} missing={sym in missing_symbols}")

                    if ltp == 0:
                        continue

                    entry = t["entry_price"]
                    side = t.get("side", "BUY")
                    pos = next((p for p in positions if p.get("symbol") == sym), None)
                    # Use the traded qty stored on the trade. If missing, compute from lot_size × lots.
                    traded_qty = t.get("qty", 0)
                    if traded_qty <= 0:
                        if "NIFTY" in sym or "BANKNIFTY" in sym:
                            traded_qty = state.trade_lots * get_lot_size(sym)
                        elif sym.startswith("MCX:") or sym.startswith("CDS:"):
                            traded_qty = getattr(state, "mcx_lots", 1) * get_lot_size(sym)
                        else:
                            traded_qty = getattr(state, "stock_lots", 1) * get_lot_size(sym)
                    # Prefer the real open position qty from broker if available
                    active_qty = abs(pos.get("qty", traded_qty)) if pos else traded_qty

                    # ═══════════════════════════════════════════
                    # PAPER-MODE SL/TARGET AUTO-FILL (04-08-26 fix)
                    # A real broker SL/target order auto-executes the instant price crosses it —
                    # every trailing block below only ever MOVES that resting order via
                    # client.modify_order(). Paper mode has no broker to do that autonomous
                    # execution, so a paper position's SL/TSL was being trailed correctly but never
                    # actually closed, no matter how far price ran past it (observed live: a paper
                    # NIFTY position ran to -₹4,238 unrealized with its SL still PENDING at a price
                    # crossed long ago). Simulates the fill by placing the closing paper order
                    # directly once LTP crosses the trade's current sl_price/target_price — reuses
                    # the SAME client.place_order() paper-mode branch a real exit would use, so the
                    # existing CLEANUP COMPLETED TRADES block above picks it up next tick exactly
                    # like any other completed trade (ledger, cooldown, broadcast — all unchanged).
                    # ═══════════════════════════════════════════
                    if state.paper_trading:
                        cur_sl = t.get("sl_price")
                        cur_tgt = t.get("target_price")
                        hit_sl = bool(cur_sl) and ((ltp <= cur_sl) if side == "BUY" else (ltp >= cur_sl))
                        hit_tgt = bool(cur_tgt) and ((ltp >= cur_tgt) if side == "BUY" else (ltp <= cur_tgt))
                        if hit_sl or hit_tgt:
                            _reason = "Paper SL hit" if hit_sl else "Paper target hit"
                            logger.info(f"📄 {_reason} for {sym}: LTP {ltp} vs SL {cur_sl} / TGT {cur_tgt} — closing paper position.")
                            try:
                                from engine.api_queue import api_queue as _apiq
                                await _apiq.enqueue(
                                    1, client.place_order, symbol=sym, qty=active_qty,
                                    side=("SELL" if side == "BUY" else "BUY"), order_type="MARKET",
                                    product="INTRADAY"
                                )
                            except Exception as _pe:
                                logger.error(f"Paper SL/target close failed for {sym}: {_pe}")
                            continue

                    # Strategy 1 / all strategies: TSL is ONLY the global 3×1m trail below
                    # (LOCKED owner rule 03-08-26 — no Variant-L / 1R / breakeven trail overrides).

                    # Strategy 5 (Aerospace) Time Stop Monitoring (exit-only; TSL is global 3×1m)
                    if t.get("strategy") == "Strategy 5: Optimized Aerospace Mean Reversion":
                        # Time Guardrail: 45 bars (3 minutes per bar = 135 minutes)
                        entry_time = t.get("entry_time", time.time())
                        bars_held = (time.time() - entry_time) / 180.0
                        
                        if bars_held >= 45.0:
                            logger.info(f"⏳ Strategy 5 Time Stop Hit for {sym} (Bars held: {bars_held:.1f}). Exiting.")
                            await broadcast_log(f"⏳ Strategy 5 Time Stop Hit for {sym}! Exiting...", "warning", user_id=u_id)
                            # Cancel CO SL if exists (Phase 1 Item D1: use the real cancel_order
                            # method — the previous call targeted a method that never existed and
                            # silently no-op'd, leaving the broker-side stop order live).
                            sl_order_id = t.get("sl_order_id")
                            cancelled_ok = True
                            if sl_order_id:
                                try:
                                    result = await api_queue.enqueue(2, client.cancel_order, sl_order_id)
                                    cancelled_ok = bool(result and result.get("success"))
                                    if not cancelled_ok:
                                        # Cancel failed — the position may already be flat (SL/target hit).
                                        # Confirm broker-side before dropping bookkeeping.
                                        try:
                                            live_positions = await api_queue.enqueue(1, client.get_positions)
                                            pos_now = next((p for p in live_positions if p.get("symbol") == sym), None)
                                            cancelled_ok = pos_now is None or abs(pos_now.get("qty", 0)) == 0
                                        except Exception as pos_err:
                                            logger.error(f"Strategy 5 position-confirm error for {sym}: {pos_err}")
                                            cancelled_ok = False
                                except Exception as e:
                                    logger.error(f"Error cancelling Strategy 5 CO: {e}")
                                    cancelled_ok = False
                            if cancelled_ok:
                                state.remove_active_trade(sym)
                            else:
                                logger.warning(f"⚠️ Strategy 5 exit for {sym}: CO cancel unconfirmed and position not flat — keeping trade for re-evaluation next tick")
                            continue
                            
                    # Strategy 6 (Gap Fill) Force Exit at 1:30 PM
                    if t.get("strategy") == "Strategy 6: Gap Fill Reversal":
                        now = datetime.now(IST)
                        if now.hour > 13 or (now.hour == 13 and now.minute >= 30):
                            logger.info(f"⏳ Strategy 6 Time Cutoff Hit (1:30 PM) for {sym}. Force exiting.")
                            await broadcast_log(f"⏳ Strategy 6 Time Cutoff (1:30 PM) hit for {sym}! Force exiting...", "warning", user_id=u_id)
                            # Cancel CO SL if exists (Phase 1 Item D1: use the real cancel_order method).
                            sl_order_id = t.get("sl_order_id")
                            cancelled_ok = True
                            if sl_order_id:
                                try:
                                    result = await api_queue.enqueue(2, client.cancel_order, sl_order_id)
                                    cancelled_ok = bool(result and result.get("success"))
                                    if not cancelled_ok:
                                        # Cancel failed — the position may already be flat. Confirm broker-side.
                                        try:
                                            live_positions = await api_queue.enqueue(1, client.get_positions)
                                            pos_now = next((p for p in live_positions if p.get("symbol") == sym), None)
                                            cancelled_ok = pos_now is None or abs(pos_now.get("qty", 0)) == 0
                                        except Exception as pos_err:
                                            logger.error(f"Strategy 6 position-confirm error for {sym}: {pos_err}")
                                            cancelled_ok = False
                                except Exception as e:
                                    logger.error(f"Error cancelling Strategy 6 CO: {e}")
                                    cancelled_ok = False
                            if cancelled_ok:
                                state.remove_active_trade(sym)
                            else:
                                logger.warning(f"⚠️ Strategy 6 exit for {sym}: CO cancel unconfirmed and position not flat — keeping trade for re-evaluation next tick")
                            continue

                        # FVL/ATR trail REMOVED (LOCKED 03-08-26): Strategy 6 uses the same
                        # global 3×1m TSL as every other strategy — fall through below.

                    # Strategy 3 / 9: optional T2 profit-target EXIT only.
                    # T1 breakeven trail + unconditional continue REMOVED so global 3×1m TSL always runs.
                    if t.get("strategy") in ["Strategy 3: 5-Minute ORB", "Strategy 9: 9-EMA Momentum Scalper"]:
                        target_1 = t.get("target_1")
                        target_2 = t.get("target_2")

                        if target_1 and target_2:
                            is_target_2_hit = False

                            if side == "BUY":
                                if ltp >= target_2:
                                    is_target_2_hit = True
                            else:  # SELL
                                if ltp <= target_2:
                                    is_target_2_hit = True

                            if is_target_2_hit:
                                logger.info(f"🎯 Strategy 3 Target 2 Hit for {sym} at ₹{ltp} (Target: ₹{target_2})! Exiting.")
                                trade_pnl = (ltp - entry) if side == "BUY" else (entry - ltp)
                                await broadcast_log(f"🛑 Trailing SL Hit for {sym} at ₹{ltp}! Profit: +₹{trade_pnl}", "warning", user_id=u_id, telegram_alert=True)

                                # Cancel SL order
                                sl_order_id = t.get("sl_order_id")
                                if sl_order_id:
                                    try:
                                        await api_queue.enqueue(2, client.cancel_order, sl_order_id)
                                    except Exception as e:
                                        logger.error(f"Error cancelling SL order: {e}")

                                # Exit position (options: SELL-to-close only, matching product book)
                                exit_side = "SELL" if side == "BUY" else "BUY"
                                qty = t.get("qty", 0)
                                if qty <= 0:
                                    if "NIFTY" in sym or "BANKNIFTY" in sym:
                                        qty = state.trade_lots * get_lot_size(sym)
                                    elif sym.startswith("MCX:") or sym.startswith("CDS:"):
                                        qty = getattr(state, "mcx_lots", 1) * get_lot_size(sym)
                                    else:
                                        qty = getattr(state, "stock_lots", 1) * get_lot_size(sym)
                                if pos:
                                    qty = abs(pos.get("qty", qty))

                                if client._is_option_symbol(sym):
                                    if exit_side != "SELL":
                                        logger.error(f"Strategy 3 exit blocked for {sym}: options buy-only")
                                        continue
                                    product_type = (
                                        client._position_product(pos) if pos else ""
                                    ) or client.resolve_exit_product(sym, "INTRADAY")
                                else:
                                    product_type = "INTRADAY"
                                exit_res = await asyncio.to_thread(
                                    client.place_order,
                                    symbol=sym,
                                    qty=qty,
                                    side=exit_side,
                                    order_type="MARKET",
                                    product=product_type,
                                    sl_points=0.0,
                                    target_points=0.0,
                                    is_exit=True,
                                )
                                if exit_res.get("success"):
                                    trade_pnl = (ltp - entry) if side == "BUY" else (entry - ltp)
                                    result_type = "profit" if trade_pnl > 0 else "loss"
                                    state.record_trade_close(
                                        result_type,
                                        pos={"side": side, "symbol": sym, "strategy": t.get("strategy", "")},
                                        exit_price=ltp, pnl=trade_pnl,
                                        reason="Strategy 3 Target Hit",
                                    )
                                    await broadcast_log(f"✅ Strategy 3 exit at ₹{ltp}. ⏳ Cooldown: {3 if result_type == 'profit' else 5} minutes.", "success", user_id=u_id, telegram_alert=True)
                                    state.remove_active_trade(sym)
                                else:
                                    await broadcast_log(f"⚠️ Strategy 3 exit failed: {exit_res.get('message')}", "error", user_id=u_id)
                                continue
                            # T1 hit no longer moves SL to breakeven — 3×1m TSL owns the stop.

                    # Strategy 7: structural spot HL/LH trail DISABLED (LOCKED 03-08-26).
                    # Option stop is trailed solely by global 3×1m candle rule below.

                    # Global Trailing Stoploss — LOCKED: EVERY strategy, last-3×1m option candles
                    now = time.time()
                    last_swing_check = t.get("last_swing_check", 0)
                    
                    is_expiry = is_symbol_expiry_today(sym)
                    
                    # Always use 1-min chart for trailing SL (CANONICAL — identical to initial SL)
                    timeframe = CANONICAL_SL_RESOLUTION
                    
                    if now - last_swing_check > 5:
                        t["last_swing_check"] = now
                        state.save()
                        try:
                            # Pass 1 for days_back to avoid fetching massive amounts of data
                            candles = await api_queue.enqueue(2, client.get_historical, sym, timeframe, 1) 
                            
                            # Globally enforce 3 candles for all trades
                            required_candles = CANONICAL_SL_LOOKBACK
                            
                            if candles and len(candles) >= required_candles:
                                recent = candles[-required_candles:]
                                
                                if side == "BUY":
                                    lowest_low = min(c["low"] for c in recent)

                                    # #2 RESPECT MANUAL SL: the user may tighten the SL in the Fyers
                                    # terminal to cut losses. Sync our tracked sl_price to the
                                    # broker's ACTUAL SL trigger (throttled ~20s) BEFORE trailing, so
                                    # the 3-candle trail never LOOSENS a stop the user tightened — it
                                    # can only raise it further from the user's level.
                                    _now2 = time.time()
                                    if t.get("sl_order_id") and (_now2 - t.get("last_broker_sl_sync", 0) > 20):
                                        t["last_broker_sl_sync"] = _now2
                                        try:
                                            _ob = await api_queue.enqueue(2, client.get_orders)
                                            _slo = next((o for o in (_ob or []) if str(o.get("id")) == str(t.get("sl_order_id"))), None)
                                            if _slo:
                                                _btrig = float(_slo.get("stopPrice", 0) or 0)
                                                _cur = float(t.get("sl_price", 0) or 0)
                                                if _btrig > 0 and abs(_btrig - _cur) >= 0.05:
                                                    logger.info(f"🖐️ Manual SL change detected for {sym}: ₹{_cur} -> ₹{_btrig} — adopting broker value.")
                                                    await broadcast_log(f"🖐️ Manual SL change adopted for {sym}: ₹{_btrig}", "info", user_id=client.user_id)
                                                    t["sl_price"] = _btrig
                                                    state.update_trade_sl_price(t.get("sl_order_id"), _btrig)
                                        except Exception as _e:
                                            logger.warning(f"Broker SL sync failed for {sym}: {_e}")

                                    current_sl_price = t.get("sl_price", entry - t.get("sl_points", 0))

                                    # Trail SL up if the new swing low is higher than current SL and below LTP
                                    if lowest_low > current_sl_price and lowest_low < ltp:
                                        new_sl_price = round_to_tick(lowest_low, get_price_tick(sym))
                                        trail_msg = "Global 3-Candle Trailing"
                                        logger.info(f"🚀 {trail_msg} Milestone Hit for {sym}! LTP: {ltp} | New Low: {lowest_low}")
                                        
                                        if t.get("sl_order_id"):
                                            o_type = t.get("sl_order_type", 4)
                                            # Owner rule: SL-L limit is exactly 0.5 below trigger (close long)
                                            _lim = compute_sl_limit_price(new_sl_price, exit_side=-1, symbol=sym) if o_type == 4 else 0
                                            mod_res = await asyncio.to_thread(
                                                client.modify_order,
                                                order_id=t["sl_order_id"],
                                                order_type=o_type,
                                                stop_price=new_sl_price,
                                                limit_price=_lim,
                                                qty=active_qty
                                            )
                                            if mod_res.get("success"):
                                                logger.info(f"🛡️ Trailed SL to ₹{new_sl_price} for {sym}")
                                                await broadcast_log(f"🛡️ SL trailed to ₹{new_sl_price} (3-Candle Low)", "success")
                                                if state.webhook_url:
                                                    trigger_webhook_background(state.webhook_url, f"🚀 *{trail_msg} Updated*\n\n📈 *Symbol:* {sym}\n🛡️ *New SL Price:* ₹{new_sl_price}\n🔥 *Swing Low:* {lowest_low}", title="Trailing SL")
                                                state.update_trade_sl_price(t["sl_order_id"], new_sl_price)
                                                try:
                                                    from models import Database
                                                    await Database.record_trade_trail(sym, new_sl_price, user_id=u_id)
                                                except Exception as _te:
                                                    logger.warning(f"ledger trail-record skipped for {sym}: {_te}")
                                            else:
                                                logger.error(f"❌ Failed to trail SL to ₹{new_sl_price} for {sym}: {mod_res.get('message')}")
                                        else:
                                            logger.warning(f"⚠️ No SL order ID tracked for {sym}, cannot modify on-exchange SL.")
                                
                                elif side == "SELL":
                                    highest_high = max(c["high"] for c in recent)
                                    current_sl_price = t.get("sl_price", entry + t.get("sl_points", 0))
                                        
                                    # Trail SL down if new swing high is lower than current SL
                                    if highest_high < current_sl_price and highest_high > ltp:
                                        new_sl_price = round_to_tick(highest_high, get_price_tick(sym))
                                        trail_msg = "Global 3-Candle Trailing"
                                        logger.info(f"🚀 [SELL] {trail_msg} Milestone Hit for {sym}! LTP: {ltp} | New High: {highest_high}")
                                        
                                        if t.get("sl_order_id"):
                                            o_type = t.get("sl_order_type", 4)
                                            # Owner rule: SL-L limit is exactly 0.5 above trigger (close short)
                                            _lim = compute_sl_limit_price(new_sl_price, exit_side=1, symbol=sym) if o_type == 4 else 0
                                            mod_res = await asyncio.to_thread(
                                                client.modify_order,
                                                order_id=t["sl_order_id"],
                                                order_type=o_type,
                                                stop_price=new_sl_price,
                                                limit_price=_lim,
                                                qty=active_qty
                                            )
                                            if mod_res.get("success"):
                                                logger.info(f"🛡️ [SELL] Trailed SL to ₹{new_sl_price} for {sym}")
                                                await broadcast_log(f"🛡️ SL trailed to ₹{new_sl_price} (3-Candle High)", "success")
                                                state.update_trade_sl_price(t["sl_order_id"], new_sl_price)
                                                try:
                                                    from models import Database
                                                    await Database.record_trade_trail(sym, new_sl_price, user_id=u_id)
                                                except Exception as _te:
                                                    logger.warning(f"ledger trail-record skipped for {sym}: {_te}")
                                            else:
                                                logger.error(f"❌ [SELL] Failed to trail SL to ₹{new_sl_price} for {sym}: {mod_res.get('message')}")
                                        else:
                                            logger.warning(f"⚠️ [SELL] No SL order ID tracked for {sym}, cannot modify on-exchange SL.")
                        except Exception as e:
                            logger.error(f"⚠️ Error in 3-Candle trailing logic for {sym}: {e}")


            except Exception as e:
                # B3: per-user isolation — log this user's failure and move to the next user
                # so a single malformed state does not stop every other user's max-loss /
                # trailing checks in this tick.
                logger.error(f"Trailing monitor error for user {u_id}: {e}")
                continue

        await asyncio.sleep(1)  # Monitor every 1 second for fast trailing


async def calculate_smart_sl(strike_symbol: str, entry_ltp: float, trend: str, client) -> Dict:
    """
    LOCKED OWNER RULE (03-08-26) — Initial SL for EVERY strategy.

    Identical structure to trailing_monitor TSL:
      BUY → distance = entry − lowest of last 3 one-minute OPTION candles
      (Trail raises that absolute stop; this function returns the distance for place_order.)

    Do NOT widen with % premium / ATR / progressive 4–5 lookback.
    Do NOT add strategy-specific offsets (−2, VIX, 10–20 clamp) here or at call sites.
    """
    is_trending = "BULL" in trend.upper() or "BEAR" in trend.upper()

    def _pkg(sl_pts: float, method: str) -> Dict:
        _min = 0.5 if entry_ltp >= 5 else max(0.05, round(entry_ltp * 0.05, 2))
        sl_pts = max(round(float(sl_pts), 2), _min)
        if entry_ltp > 0:
            sl_pts = min(sl_pts, round(entry_ltp * 0.80, 2))
        tgt = round(sl_pts * (2 if is_trending else 1.5), 1)
        return {"sl_points": sl_pts, "target_points": tgt, "method": method}

    try:
        candles = await api_queue.enqueue(2, client.get_historical, strike_symbol, CANONICAL_SL_RESOLUTION, 2)
        if candles and len(candles) >= CANONICAL_SL_LOOKBACK:
            recent = candles[-CANONICAL_SL_LOOKBACK:]
            swing_low = min(c["low"] for c in recent)
            dist = round(entry_ltp - swing_low, 2)
            if dist > 0:
                logger.info(
                    f"📊 SL {strike_symbol}: 3×1m low={swing_low:.2f} → "
                    f"{dist:.2f} pts below entry {entry_ltp} [3_candle_1m_low]"
                )
                return _pkg(dist, "3_candle_1m_low")
            # Swing low at/above entry (gap / bad print) — use last closed candle range as distance.
            last = recent[-1]
            fallback = round(max(last["high"] - last["low"], entry_ltp * 0.02, 0.5), 2)
            logger.warning(
                f"📊 SL {strike_symbol}: 3×1m low {swing_low:.2f} >= entry {entry_ltp} — "
                f"using last-bar range {fallback:.2f} pts"
            )
            return _pkg(fallback, "3_candle_1m_low_fallback_range")

        # Not enough candles yet — small premium-relative fallback (not the old 12% floor).
        fb = max(round(entry_ltp * 0.03, 2), 1.0) if entry_ltp > 0 else 5.0
        logger.warning(f"📊 SL {strike_symbol}: <3 one-min candles — fallback {fb:.2f} pts")
        return _pkg(fb, "insufficient_candles_fallback")

    except Exception as e:
        logger.error(f"Smart SL calculation error: {e}")
        return _pkg(max(round(entry_ltp * 0.03, 2), 2.0) if entry_ltp > 0 else 5.0, "error_fallback")


async def _recover_closed_pnl(client, sym):
    """Issue 3: recover a closed trade's REAL realized P&L when the broker has dropped the position
    from the live positions feed — so a WIN isn't logged as breakeven (which starves the win-rate /
    self-improvement). Tries a fresh positions fetch (the closed position usually lingers with
    qty=0 + realized 'pl'), then the trade book (sell proceeds - buy cost).
    Returns (pnl, exit_price, source)."""
    # 1) Fresh positions — closed position often still present at qty=0 with realized pl.
    try:
        fresh = await api_queue.enqueue(1, client.get_positions)
        fp = next((p for p in (fresh or []) if p.get("symbol") == sym), None)
        if fp is not None and fp.get("pl") is not None:
            return float(fp.get("pl", 0) or 0), float(fp.get("sellAvg", fp.get("buyAvg", 0)) or 0), "positions"
    except Exception:
        pass
    # 2) Trade book — reconstruct realized P&L from the day's fills for this symbol.
    try:
        tb = await api_queue.enqueue(2, client.get_trade_book)
        buy_val = buy_qty = sell_val = sell_qty = 0.0
        last_price = 0.0
        for f in (tb or []):
            if f.get("symbol") != sym:
                continue
            q = float(f.get("tradedQty", f.get("qty", 0)) or 0)
            px = float(f.get("tradePrice", f.get("price", 0)) or 0)
            sd = f.get("side", 0)
            last_price = px or last_price
            if sd == 1 or str(sd).upper() == "BUY":
                buy_val += q * px; buy_qty += q
            elif sd == -1 or str(sd).upper() == "SELL":
                sell_val += q * px; sell_qty += q
        if buy_qty > 0 and sell_qty > 0:
            return round(sell_val - buy_val, 2), last_price, "tradebook"
    except Exception:
        pass
    return 0.0, 0.0, "unknown"


async def _affordable_to_place(client, strike_symbol, qty, side, product_type, entry_price, sl_points):
    """FINAL balance gate (owner rule 28-07-26): before an order is SENT, confirm the broker has
    enough margin for THIS exact order. Returns (ok, required, available). If the margin API can't
    give a real number (0/error), returns ok=True so a transient API blip never freezes all trading
    — the broker's own margin check remains the ultimate backstop; this gate just stops the common
    case of knowingly sending an unaffordable order (which would be rejected for Margin Shortfall)."""
    try:
        m = await asyncio.to_thread(client.check_margin, strike_symbol, qty, side, product_type, entry_price, sl_points)
        required = float((m or {}).get("total_margin", 0) or 0)
        available = float((m or {}).get("available_margin", 0) or 0)
        if available <= 0:
            f = await api_queue.enqueue(2, client.get_funds) or {}
            available = float(f.get("equityAmount", 0) or 0) + float(f.get("commodityAmount", 0) or 0)
        if required <= 0:
            return True, required, available  # margin unknown -> don't block; broker gates
        return (required <= available), required, available
    except Exception as e:
        logger.warning(f"Final affordability check failed for {strike_symbol}: {e}")
        return True, 0.0, 0.0


def _passes_quality_gate(strike_symbol, entry_price, sl_points, qty, state):
    """Pre-trade quality/risk gate (owner directive 30-07-26 — stop the daily bleed). Returns
    (ok: bool, reason: str). Two checks:
      1. JUNK FILTER — reject near-worthless deep-OTM options (premium < ₹5). These decay straight
         to zero and were being over-traded (e.g. ICICIBANK ₹0.05 lottery tickets, 11 in 11 min).
      2. PER-TRADE RUPEE RISK CAP — sl_points × qty must fit the budget (half the daily max-loss,
         floor ₹500). A single stop-out can't blow a big hole, and trades whose safe stop is
         unaffordable (big-lot crude) are SKIPPED rather than taken with a whipsaw-tight stop."""
    try:
        ep = float(entry_price or 0)
    except (TypeError, ValueError):
        ep = 0.0
    if ep < 5.0:
        return False, f"premium ₹{ep} < ₹5 floor (junk/deep-OTM)"
    # Per-trade cap = 60% of the daily max-loss budget (floor ₹1000). One bad trade can't burn more
    # than ~60% of the day, and instruments whose noise-surviving stop is unaffordable (big-lot crude)
    # are skipped rather than taken with a whipsaw-tight stop. Scales with the user's max-loss setting,
    # so raising that setting is the knob to allow larger-risk trades (e.g. crude).
    max_risk = max(1000.0, float(getattr(state, "max_loss_per_day", 2500.0) or 2500.0) * 0.6)
    risk = float(sl_points or 0) * float(qty or 0)
    if risk > max_risk:
        return False, f"risk ₹{risk:.0f} (SL {sl_points}pts × {qty}) > per-trade cap ₹{max_risk:.0f}"
    return True, ""


async def _record_entry_to_ledger(client, underlying, strike_symbol, side, qty, entry_price,
                                  sl_points, sl_method, target_points, product, regime, trend,
                                  order_id, strategy_name, entry_reason=""):
    """Best-effort: write the OPEN row to the executed-trades ledger the moment an order is placed.
    Recording at ENTRY (not close) is what makes trade tracking reliable — the strategy, SL and entry
    reason are captured here where they are always known. NEVER raises into the trade path."""
    try:
        from models import Database
        now = datetime.now(IST)
        await Database.record_trade_entry(
            user_id=client.user_id, strategy_name=strategy_name, symbol=strike_symbol,
            underlying=underlying, side=side, qty=qty, entry_price=entry_price,
            entry_time=now.strftime("%Y-%m-%d %H:%M:%S"), sl_points=sl_points, sl_method=sl_method,
            target_points=target_points, product=product, regime=regime, trend=trend,
            entry_order_id=str(order_id or ""), trade_date=now.strftime("%Y-%m-%d"),
            entry_reason=str(entry_reason or ""))
    except Exception as e:
        logger.warning(f"ledger entry-record skipped for {strike_symbol}: {e}")


async def _execute_shadow_trade(client, state, strategy_name, strike_symbol, entry_price, sl_points,
                                 sl_method, target_points, qty, underlying, regime, trend, entry_reason=""):
    """SHADOW MODE (03-08-26): records a shadow-listed strategy's signal as a fully SIMULATED trade.
    Writes the ENTRY ledger row directly and tracks it in state.shadow_trades for
    check_shadow_trades() to close later — it NEVER calls client.place_order and NEVER touches
    active_auto_trades / paper_positions / paper_orders, so it cannot cross-contaminate real trades,
    the account's live/paper broker state, or any of the real order-management systems (SL Guardian,
    trailing_monitor, the position-cleanup loop). Purpose: let a strategy with no real track record
    yet accumulate genuine market-reactive executed_trades ledger rows, risk-free, toward
    nightly_learning's MIN_TRADES_FOR_LEARNING gate."""
    try:
        now = datetime.now(IST)
        sl_price = round(entry_price - sl_points, 2)
        target_price = round(entry_price + target_points, 2) if target_points else None
        await _record_entry_to_ledger(
            client, underlying, strike_symbol, "BUY", qty, entry_price, sl_points, sl_method,
            target_points, "SHADOW", regime, trend, f"SHADOW-{int(now.timestamp())}", strategy_name,
            entry_reason=f"[SHADOW] {entry_reason}")
        state.shadow_trades.append({
            "symbol": strike_symbol, "underlying": underlying, "strategy": strategy_name,
            "side": "BUY", "entry_price": entry_price, "sl_price": sl_price,
            "target_price": target_price, "qty": qty, "entry_time": now.timestamp(),
        })
        state.save()
        logger.info(f"👻 SHADOW TRADE: {strategy_name} BUY {strike_symbol} @ ₹{entry_price} | "
                    f"SL ₹{sl_price} | TGT {f'₹{target_price}' if target_price else 'none'} — "
                    f"simulated, no real order placed.")
        await broadcast_log(
            f"👻 Shadow (paper): {strategy_name} BUY {strike_symbol} @ ₹{entry_price} — no real order placed.",
            "info", user_id=client.user_id,
        )
    except Exception as e:
        logger.error(f"Shadow trade recording failed for {strike_symbol}: {e}")


async def execute_auto_trade(symbol: str, sig: Dict, analysis: Dict, client):
    """Execute an automated trade based on confirmed signal with smart SL.
    POLICY: Only BUY trades on CE/PE options. SELL trades are blocked."""
    try:
        state = get_user_state(client.user_id)

        # ═══════════════════════════════════════════
        # GUARD: Cooldown after failed trade attempts
        # ═══════════════════════════════════════════
        last_fail = getattr(state, "_last_trade_fail_time", 0)
        if last_fail and (datetime.now(IST).timestamp() - last_fail) < 60:
            return  # Silent skip — still in cooldown after a failed attempt

        # ═══════════════════════════════════════════
        # GUARD: Block if this strategy already has an active trade
        # ═══════════════════════════════════════════
        strategy_name = sig.get("strategy", "")
        if strategy_name and state.has_active_trade_for_strategy(strategy_name):
            return

        # ═══════════════════════════════════════════
        # GUARD: Verify symbol is enabled for auto-trade
        # ═══════════════════════════════════════════
        enabled_symbols = getattr(state, "enabled_symbols", ["NSE:NIFTY50-INDEX"])
        if symbol not in enabled_symbols:
            return

        # ═══════════════════════════════════════════
        # PORTFOLIO: max concurrent index option positions (risk cap)
        # ═══════════════════════════════════════════
        _max_index_opts = int(getattr(state, "max_concurrent_index_options", 2) or 2)
        _active = getattr(state, "active_auto_trades", []) or []
        _index_opt_count = sum(
            1
            for t in _active
            if (t.get("symbol") or "").upper().endswith(("CE", "PE"))
            and any(x in (t.get("symbol") or "").upper() for x in ("NIFTY", "BANKNIFTY"))
        )
        if _index_opt_count >= _max_index_opts:
            logger.info(
                f"⏭️ Portfolio cap: {_index_opt_count}/{_max_index_opts} index options open — skipping {strategy_name}"
            )
            return

        # ═══════════════════════════════════════════
        # POLICY: BUY ONLY — Block all SELL trades
        # ═══════════════════════════════════════════
        requested_side = sig.get("side", "BUY")
        if requested_side.upper() != "BUY":
            return

        # ═══════════════════════════════════════════
        # REGIME LOCKOUT: Block trades in flat/choppy markets
        # ═══════════════════════════════════════════
        norm_analysis = analysis if isinstance(analysis, dict) else {}
        trend_info = norm_analysis.get("trend", {})
        if isinstance(trend_info, str):
            current_trend = trend_info.upper()
        elif isinstance(trend_info, dict):
            current_trend = (trend_info.get("trend", "") or "").upper()
        else:
            current_trend = "NEUTRAL"

        strategy_name = sig.get("strategy", "")
        # Strategy 1 (OB+FVG) directional consistency.
        # FIX 5: the old rule ALSO returned outright on NEUTRAL/RANGE/SIDEWAYS/CHOPPY. That blocked
        # Strategy 1 on the majority of days (NSE regime is frequently CHOPPY_SIDEWAYS, and 133 of
        # 159 days were flat). Two reasons it's now relaxed:
        #   1. The Variant L backtest that justified this configuration (confluence-only +
        #      breakeven-trail, 57.6% win, max DD -113 pts) was measured WITHOUT this lockout, so
        #      keeping it means live behaviour does not match what was actually validated.
        #   2. With AI now bounded (FIX 1), an unavailable/slow provider yields NEUTRAL far more
        #      often — under the old rule that silently became a permanent block.
        # Directional consistency is KEPT: never buy a CALL into a bearish trend or vice-versa.
        # Counter-trend setups are already filtered upstream in signals.py.
        if "Strategy 1" in strategy_name:
            sig_type = sig.get("type", "").upper()
            if "BULL" in current_trend and sig_type != "CALL":
                return
            if "BEAR" in current_trend and sig_type != "PUT":
                return

        # ═══════════════════════════════════════════
        # DIRECTIONAL REGIME GATE (owner directive 26-07-26) — trade WITH the trend only:
        #   • UPTREND   -> BUY CE only  (block PUT)
        #   • DOWNTREND -> BUY PE only  (block CALL)
        #   • SIDEWAYS  -> NO new trades
        # The direction comes from the UNDERLYING's own 15m structure via detect_trend (deterministic
        # EMA crossover + higher-highs/lows) — NOT the rate-limited AI regime — so a slow/failed AI can
        # never permanently block or mis-direct trading. Applies to EVERY strategy and asset class.
        # NOTE: in a choppy/sideways market (common) this correctly places NO trades — fewer but
        # higher-quality, with-trend entries. This is the intended risk-reducing behaviour.
        # ═══════════════════════════════════════════
        _dir = "NEUTRAL"
        _gate_data_ok = False
        _gate_ncandles = 0
        try:
            from engine.key_levels import detect_trend
            _uc = await api_queue.enqueue(2, client.get_historical, symbol, "15", 5)
            _gate_ncandles = len(_uc) if _uc else 0
            if _uc and len(_uc) >= 20:
                _dir = (detect_trend(_uc).get("trend", "NEUTRAL") or "NEUTRAL").upper()
                _gate_data_ok = True
            else:
                # VISIBILITY: a short/empty 15m history is NOT a real sideways market — it is a data
                # gap. Without this log, MCX/FX symbols whose history feed is thin would be silently
                # blocked and look like "no signal". Surface it distinctly so it can be diagnosed.
                logger.warning(f"⚠️ Directional gate: {symbol} — only {_gate_ncandles} 15m candles (<20); "
                               f"cannot read trend → treating as no-trade (DATA GAP, not a real sideways).")
        except Exception as _de:
            logger.warning(f"⚠️ Directional gate trend calc FAILED for {symbol}: {_de} → no-trade (data error, not sideways).")
        _sig_type = sig.get("type", "").upper()
        if "BULL" in _dir:
            if _sig_type != "CALL":
                logger.info(f"⏭️ Directional gate: {symbol} UPTREND — CALL only, skipping {_sig_type}.")
                return
        elif "BEAR" in _dir:
            if _sig_type != "PUT":
                logger.info(f"⏭️ Directional gate: {symbol} DOWNTREND — PUT only, skipping {_sig_type}.")
                return
        else:
            if _gate_data_ok:
                logger.info(f"⏭️ Directional gate: {symbol} SIDEWAYS/NEUTRAL ({_gate_ncandles} candles) — no new trades (trend-only policy).")
            else:
                logger.info(f"⏭️ Directional gate: {symbol} blocked — trend UNREADABLE ({_gate_ncandles} 15m candles); not a market call, a data gap.")
            return

        # ═══════════════════════════════════════════
        # MTF ALIGNMENT GATE (5m trend must match CE/PE direction)
        # ═══════════════════════════════════════════
        from engine.execution_gates import check_mtf_gate

        _mtf_ok, _mtf_reason = await check_mtf_gate(client, symbol, sig.get("type", ""), api_queue)
        if not _mtf_ok:
            logger.info(f"⏭️ MTF gate: {symbol} {sig.get('type')} — {_mtf_reason}")
            await broadcast_log(
                f"⏭️ MTF gate: skipped {sig.get('type')} on {symbol} — {_mtf_reason}",
                "info",
                user_id=client.user_id,
            )
            return

        # ═══════════════════════════════════════════
        # ANTI-CHASE GATE (owner 03-08-26) — why one-sided markets still lost:
        # Directional gate lets WITH-trend CE/PE through, but breakout strategies buy AFTER
        # the move (near the local high). Option premium mean-reverts → SL. Block entries
        # whose price is already at/near the last-5 one-min highs (buy-high).
        # Fade strategies (S5/S6) are also disabled on load — they fight one-sided days.
        # ═══════════════════════════════════════════
        _fade = _is_fade_strategy(strategy_name)
        if _fade:
            logger.info(f"⏭️ Fade strategy blocked ({strategy_name}) — mean-reversion disabled in one-sided policy.")
            await broadcast_log(
                f"⏭️ Skipped {strategy_name}: fade/mean-reversion disabled (trend-only policy).",
                "info", user_id=client.user_id,
            )
            return

        # ═══════════════════════════════════════════
        # STRATEGY 2: Direct Option Trade (skip strike selection)
        # ═══════════════════════════════════════════
        if sig.get("is_direct_option"):
            strike_info = sig.get("strike_info", {})
            strike_symbol = strike_info.get("symbol")
            if not strike_symbol:
                logger.error("Direct option trade missing symbol!")
                await broadcast_log(f"❌ {sig.get('strategy', 'Strategy 2')}: Missing symbol", "error", user_id=client.user_id)
                return

            # Fetch fresh LTP
            fresh_quote = await api_queue.enqueue(2, client.get_quote, strike_symbol)
            entry_price = fresh_quote.get("lp", 0) if fresh_quote else 0
            if entry_price <= 0:
                entry_price = strike_info.get("ltp", sig.get("entry_price", 180))

            _chase, _chase_why = await _is_chase_entry(client, strike_symbol, entry_price)
            if _chase:
                logger.info(f"⏭️ Anti-chase: skip {strike_symbol} — {_chase_why}")
                await broadcast_log(
                    f"⏭️ Skipped {strike_symbol}: chasing local high ({_chase_why}). Wait for pullback.",
                    "info", user_id=client.user_id,
                )
                return

            from engine.execution_gates import passes_microstructure_spread

            _spread_ok, _spread_reason = passes_microstructure_spread(fresh_quote)
            if not _spread_ok:
                logger.info(f"⏭️ Microstructure gate: {strike_symbol} — {_spread_reason}")
                await broadcast_log(
                    f"⏭️ Wide spread: skipped {strike_symbol} — {_spread_reason}",
                    "info",
                    user_id=client.user_id,
                )
                return

            # LOCKED (03-08-26): EVERY strategy — including direct-option S2/S3/S4/S5 —
            # uses calculate_smart_sl (last-3×1m option low). Signal sl_points are ignored.
            sl_data = await calculate_smart_sl(strike_symbol, entry_price, current_trend, client)
            sl_points = sl_data["sl_points"]
            sl_method = sl_data["method"]
            # Calculate qty explicitly if not provided
            if strike_symbol and strike_symbol.startswith("MCX:"):
                lots = getattr(state, "mcx_lots", 1)
            elif strike_symbol and ("-EQ" in strike_symbol):
                lots = getattr(state, "stock_lots", 1)
            else:
                lots = getattr(state, "trade_lots", 1)
            
            default_qty = lots * get_lot_size(strike_symbol)
            qty = sig.get("qty", default_qty)

            # Determine product and targets based on strategy
            is_orb = sig.get("strategy") == "Strategy 3: 5-Minute ORB"

            # User directive: ALL strategies place INTRADAY orders only (not CO/MARGIN).
            product_type = "INTRADAY"
            target_points = 0.0

            side = sig.get("side", "BUY")
            strategy_name = sig.get("strategy", "Strategy 2: 9:26 - 180 Buy")

            # ── OPTIONS-BUY-ONLY ENFORCEMENT (user directive) ──
            # Every auto-trade must BUY an OPTION (CE/PE) INTRADAY — never sell/write, and
            # never a future/equity/index. Applies to ALL asset classes (index/stock/commodity/
            # currency options all end CE/PE; FUT/-EQ/-INDEX are rejected). Reject off-policy orders
            # rather than place them live.
            _sym_u = (strike_symbol or "").upper()
            if not (_sym_u.endswith("CE") or _sym_u.endswith("PE")):
                logger.error(f"⛔ Options-buy-only guard: {strike_symbol} is not a CE/PE option — trade REJECTED.")
                await broadcast_log(f"⛔ Rejected non-option order ({strike_symbol}) — options-buy-only policy.", "error")
                return
            if side != "BUY":
                logger.warning(f"⚠️ Options-buy-only guard: forced side to BUY (signal said {side}) for {strike_symbol}.")
                side = "BUY"

            # QUALITY / RISK GATE — block junk cheap options and cap per-trade rupee risk.
            _qok, _qreason = _passes_quality_gate(strike_symbol, entry_price, sl_points, qty, state)
            if not _qok:
                logger.info(f"⏭️ Quality gate: skip {strike_symbol} — {_qreason}.")
                await broadcast_log(f"⏭️ Skipped {strike_symbol}: {_qreason}.", "info", user_id=client.user_id)
                return

            # FINAL BALANCE GATE — do not send if the broker can't afford this exact order.
            _ok, _req, _av = await _affordable_to_place(client, strike_symbol, qty, side, product_type, entry_price, sl_points)
            if not _ok:
                logger.warning(f"🛑 Insufficient balance for {strike_symbol}: needs ₹{_req:.0f}, have ₹{_av:.0f} — trade NOT sent.")
                await broadcast_log(f"🛑 Insufficient balance: {strike_symbol} needs ₹{_req:.0f}, have ₹{_av:.0f} — trade skipped.", "error", user_id=client.user_id)
                return

            logger.info(f"🚀 {strategy_name} TRADE: {sig['type']} {side} {strike_symbol} @ ₹{entry_price} | SL: {sl_points}pts ({sl_method}) | TGT: {target_points}pts | Product: {product_type}")
            # AI / researcher strategies stay paper until graduated (is_paper_trading=0).
            force_ai_paper = bool(sig.get("paper_trade_only")) or str(strategy_name or "").startswith("AI_strategy_")
            shadow_exec = (state.is_shadow_strategy(strategy_name) or force_ai_paper) and not state.paper_trading
            if force_ai_paper and not state.paper_trading:
                await broadcast_log(
                    f"🧪 AI paper: {strategy_name} {side} {strike_symbol} — live account unchanged until graduated.",
                    "info",
                    user_id=client.user_id,
                )
            elif shadow_exec:
                await broadcast_log(
                    f"👻 Shadow (paper): {strategy_name} {side} {strike_symbol} — live account unchanged.",
                    "info",
                    user_id=client.user_id,
                )
            await broadcast_log(
                f"🚀 {strategy_name}: {sig['type']} {side} {strike_symbol} @ ₹{entry_price} | SL: {sl_points}pts | Product: {product_type}",
                "success"
            )

            prev_paper = state.paper_trading
            if shadow_exec:
                state.paper_trading = True
            try:
                result = await asyncio.to_thread(
                    client.place_order,
                    symbol=strike_symbol,
                    qty=qty,
                    side=side,
                    order_type="MARKET",
                    product=product_type,
                    sl_points=sl_points,
                    target_points=target_points
                )

                if result.get("success"):
                    track_pending_order(
                        result.get("order_id"),
                        strike_symbol,
                        client.user_id,
                        sl_order_id=result.get("sl_order_id"),
                        tgt_order_id=result.get("tgt_order_id")
                    )
                    state.record_trade()
                    state.add_active_trade(
                        symbol=strike_symbol,
                        entry_price=entry_price,
                        sl_points=sl_points,
                        side=side,
                        sl_order_id=result.get("sl_order_id", ""),
                        tgt_order_id=result.get("tgt_order_id", ""),
                        strategy=strategy_name,
                        target_1=sig.get("target_1") if is_orb else None,
                        target_2=sig.get("target_2") if is_orb else None,
                        sl_order_type=result.get("sl_order_type", 4),
                        qty=qty,
                        entry_trend=current_trend
                    )
            finally:
                if shadow_exec:
                    state.paper_trading = prev_paper

            if result.get("success"):
                await _record_entry_to_ledger(
                    client, symbol, strike_symbol, side, qty, entry_price, sl_points,
                    sl_method, target_points,
                    product_type, getattr(state, "market_regime", "NEUTRAL"), current_trend,
                    result.get("order_id"), strategy_name,
                    entry_reason=sig.get("reason", "") or sig.get("signal_reason", ""))
                log_trade({
                    "symbol": strike_symbol, "side": side, "qty": qty,
                    "price": entry_price, "signal_type": f"{strategy_name}_{sig['type']}",
                    "status": "PLACED", "sl": sl_points, "target": target_points,
                    "sl_method": sl_method
                })
                await broadcast_log(
                    f"✅ {strategy_name} Order placed: {strike_symbol} @ ₹{entry_price} | {result.get('message', '')}",
                    "success"
                )
                logger.info(f"✅ {strategy_name} trade executed: {result}")
                if not result.get("sl_order_id"):
                    logger.error(f"🚨 CRITICAL: {strategy_name} trade WITHOUT Stop Loss! {strike_symbol}")
                    await broadcast_log(
                        f"🚨 CRITICAL: Trade {strike_symbol} has NO STOP LOSS! Square off or place SL manually NOW. Msg: {result.get('message', '')}",
                        "error", user_id=client.user_id, telegram_alert=True
                    )
            else:
                logger.error(f"❌ {strategy_name} trade failed: {result.get('message', 'Unknown')}")
                await broadcast_log(f"❌ {strategy_name} failed: {result.get('message', '')}", "error", user_id=client.user_id)
                if result.get("emergency_exit"):
                    await broadcast_log(
                        f"🚨 Entry for {strike_symbol} was squared off because SL could not be placed — capital protected.",
                        "error", user_id=client.user_id, telegram_alert=True
                    )
            return  # Exit — Strategy 2 is done

        # ═══════════════════════════════════════════
        # STRATEGY 1: Standard OB + FVG Trade Flow
        # ═══════════════════════════════════════════
        spot = analysis.get("spot", 0)
        expiry = analysis.get("expiry")
        if not expiry:
            # Fallback for strategies that don't pass analysis dict (like Strategy 4, 6)
            spot = spot or sig.get("entry_price", 0)
            if spot <= 0:
                # Most strategies hand execute_auto_trade a minimal analysis dict ({"trend": ...})
                # with no spot, and during a Fyers REST cooldown get_analysis returns None. Without
                # a spot, find_nearest_expiry is skipped -> "No expiry found" -> every auto-trade is
                # skipped even though the WebSocket quote has a live spot. find_nearest_expiry is
                # programmatic (only needs a spot to pick the ATM), so pull the WS-backed live quote
                # here. get_quote is served from the WS tick cache and does NOT depend on the REST
                # rate limit.
                try:
                    _q = await api_queue.enqueue(2, client.get_quote, symbol)
                    if _q and _q.get("lp", 0) > 0:
                        spot = _q["lp"]
                except Exception as e:
                    logger.error(f"Live-quote spot fallback failed for {symbol}: {e}")
            if spot > 0:
                try:
                    expiry = await api_queue.enqueue(2, client.find_nearest_expiry, spot, symbol)
                except Exception as e:
                    logger.error(f"Fallback expiry fetch failed: {e}")

        if not expiry:
            logger.warning(f"No expiry found for {symbol}. Skipping auto-trade.")
            await broadcast_log(f"⚠️ No expiry found for auto-trade", "warning", user_id=client.user_id)
            return

        # ═══════════════════════════════════════════
        # SPOT VALIDATION — Don't trade stale signals
        # ═══════════════════════════════════════════
        entry_zone_top = sig.get("entry_zone_top", sig.get("entry_price", spot))
        entry_zone_bottom = sig.get("entry_zone_bottom", sig.get("entry_price", spot) - 50)

        if sig.get("type") == "CALL":
            # For CALL: spot should not be far below the entry zone
            if spot < entry_zone_bottom - 20:
                logger.info(f"⏭️ SPOT VALIDATION: Spot {spot} dropped below entry zone {entry_zone_bottom}. Signal stale.")
                await broadcast_log(f"⏭️ Signal stale: Spot ₹{spot:.0f} below entry zone ₹{entry_zone_bottom:.0f}", "warning", user_id=client.user_id)
                return
        elif sig.get("type") == "PUT":
            # For PUT: spot should not be far above the entry zone
            if spot > entry_zone_top + 20:
                logger.info(f"⏭️ SPOT VALIDATION: Spot {spot} rose above entry zone {entry_zone_top}. Signal stale.")
                await broadcast_log(f"⏭️ Signal stale: Spot ₹{spot:.0f} above entry zone ₹{entry_zone_top:.0f}", "warning", user_id=client.user_id)
                return

        # ═══════════════════════════════════════════
        # SELECT STRIKE
        # ═══════════════════════════════════════════
        option_chain = analysis.get("option_chain")
        if not option_chain:
            try:
                option_chain = await asyncio.to_thread(
                    client.get_option_chain_strikes, spot, expiry["code"] if expiry else None, 5, base_symbol=symbol
                )
            except Exception as e:
                logger.error(f"Option chain fetch failed: {e}")
                await broadcast_log(f"❌ Option chain error: {str(e)[:80]}", "error", user_id=client.user_id)
                return

        dte = expiry.get("dte", 5)
        recommendations = get_strike_recommendations(option_chain, sig["type"], spot, dte, exclude_symbols=state.traded_strikes_today)

        if not recommendations:
            logger.warning(f"No suitable strikes found for {sig['type']} at spot {spot}")
            await broadcast_log(f"⚠️ No strikes found for {sig['type']}", "warning", user_id=client.user_id)
            state._last_trade_fail_time = datetime.now(IST).timestamp()
            return

        # ═══════════════════════════════════════════
        # MARGIN-AWARE STRIKE SELECTION
        # A small account may not afford the ATM strike (esp. crude, where 1 lot's margin ≈
        # premium × 100). Pick the best-DELTA strike whose ACTUAL Fyers margin fits available
        # funds. Efficiency: one margin call on the ATM yields the premium→margin multiplier;
        # every other strike is then estimated analytically and only the FINAL pick is confirmed
        # with a second margin call. If the near chain has nothing affordable, widen once to reach
        # deeper (cheaper) OTM strikes. If still nothing fits, skip + back off (no spam-rejects).
        # ═══════════════════════════════════════════
        _lots = (getattr(state, "mcx_lots", 1) if symbol.startswith(("MCX:", "CDS:"))
                 else getattr(state, "stock_lots", 1) if symbol.endswith("-EQ")
                 else getattr(state, "trade_lots", 1))

        def _qty_for(sym):
            try:
                return max(1, int(_lots) * int(get_lot_size(sym)))
            except Exception:
                return max(1, int(_lots))

        _sl_pts = float(sig.get("sl", sig.get("sl_points", 12)) or 12)

        async def _margin_of(rec):
            _p = float(rec.get("ltp", 0) or 0)
            if _p <= 0:
                return None, _p, 0.0
            try:
                _m = await asyncio.to_thread(
                    client.check_margin, rec.get("symbol", symbol), _qty_for(rec.get("symbol", symbol)),
                    "BUY", "CO", _p, _sl_pts
                )
                return float(_m.get("total_margin", 0) or 0), _p, float(_m.get("available_margin", 0) or 0)
            except Exception:
                return None, _p, 0.0

        def _pick_affordable(recs, mult, budget):
            """Best-delta strike whose estimated margin fits: most expensive strike with
            premium×mult ≤ budget (closest to ATM among the affordable ones)."""
            aff = [r for r in recs if float(r.get("ltp", 0) or 0) > 0
                   and float(r.get("ltp")) * mult <= budget]
            return max(aff, key=lambda r: float(r.get("ltp")), default=None)

        best_strike = None
        _atm = recommendations[0]
        _res = await _margin_of(_atm)
        _atm_margin = _res[0]
        _atm_prem = _res[1]
        _api_avail = _res[2] if len(_res) > 2 else 0.0

        # Available margin: prefer the value the margin API reports; fall back to get_funds.
        _avail = _api_avail
        if _avail <= 0:
            try:
                _f = await api_queue.enqueue(2, client.get_funds) or {}
                _avail = float(_f.get("equityAmount", 0) or 0) + float(_f.get("commodityAmount", 0) or 0)
            except Exception:
                _avail = 0.0
        _budget = _avail * 0.95  # 5% headroom for slippage / SL buffer

        if _atm_margin and _atm_margin > 0 and _avail > 0:
            if _atm_margin <= _budget:
                best_strike = _atm  # ATM fits — ideal pick
            else:
                _mult = _atm_margin / _atm_prem if _atm_prem > 0 else 0
                # Try the near chain first, then a wide chain for deeper OTM strikes.
                _pools = [recommendations]
                try:
                    _wide = await asyncio.to_thread(
                        client.get_option_chain_strikes, spot,
                        expiry["code"] if expiry else None, 14, base_symbol=symbol
                    )
                    _wide_recs = get_strike_recommendations(
                        _wide, sig["type"], spot, dte, exclude_symbols=state.traded_strikes_today
                    )
                    if _wide_recs:
                        _pools.append(_wide_recs)
                except Exception as _we:
                    logger.warning(f"Wide-chain margin fallback fetch failed for {symbol}: {_we}")

                for _pool in _pools:
                    _cand = _pick_affordable(_pool, _mult, _budget) if _mult > 0 else None
                    if not _cand:
                        continue
                    # Confirm the estimate with a real margin call before committing.
                    _cres = await _margin_of(_cand)
                    _cmargin = _cres[0]
                    if _cmargin and 0 < _cmargin <= _budget:
                        best_strike = _cand
                        if _pool is not recommendations:
                            recommendations = _pool
                        logger.info(
                            f"💰 Margin-aware: picked {_cand.get('symbol')} (₹{_cand.get('ltp')}, "
                            f"margin ₹{_cmargin:.0f}) over ATM {_atm.get('symbol')} "
                            f"(margin ₹{_atm_margin:.0f}) to fit ₹{_avail:.0f}."
                        )
                        break

            if best_strike is None:
                logger.warning(
                    f"⏭️ No affordable {sig['type']} strike for {symbol}: ATM margin ₹{_atm_margin:.0f} "
                    f"> budget ₹{_budget:.0f} (avail ₹{_avail:.0f}); no cheaper strike fits. Backing off."
                )
                await broadcast_log(
                    f"⏭️ {symbol}: no strike fits margin (have ₹{_avail:.0f}). Skipping.",
                    "warning", user_id=client.user_id
                )
                state._last_trade_fail_time = datetime.now(IST).timestamp()  # reuse the 60s backoff
                return
        else:
            # Margin API unavailable — fall back to the original ATM pick; the broker still gates.
            best_strike = recommendations[0]

        strike_symbol = best_strike.get("symbol")

        if not strike_symbol:
            logger.warning(f"Invalid strike data: {best_strike}")
            return

        # ═══════════════════════════════════════════
        # FETCH FRESH LIVE LTP (with candle fallback)
        # ═══════════════════════════════════════════
        entry_price = 0

        # Try 1: Live quote
        fresh_quote = await api_queue.enqueue(2, client.get_quote, strike_symbol)
        if fresh_quote and fresh_quote.get("lp", 0) > 0:
            entry_price = fresh_quote["lp"]
            logger.info(f"📊 Fresh LTP for {strike_symbol}: ₹{entry_price}")

        from engine.execution_gates import passes_microstructure_spread

        if fresh_quote and entry_price > 0:
            _spread_ok, _spread_reason = passes_microstructure_spread(fresh_quote)
            if not _spread_ok:
                logger.info(f"⏭️ Microstructure gate: {strike_symbol} — {_spread_reason}")
                await broadcast_log(
                    f"⏭️ Wide spread: skipped {strike_symbol} — {_spread_reason}",
                    "info",
                    user_id=client.user_id,
                )
                return

        # Try 2: Cached LTP from option chain
        if entry_price <= 0:
            entry_price = best_strike.get("ltp", 0)
            if entry_price > 0:
                logger.info(f"📊 Cached LTP for {strike_symbol}: ₹{entry_price}")

        # Try 3: Historical candle fallback (latest 1-min close)
        if entry_price <= 0:
            try:
                candle_data = await asyncio.to_thread(
                    client.get_historical, strike_symbol, "1", 1
                )
                if candle_data and len(candle_data) > 0:
                    entry_price = candle_data[-1].get("close", 0)
                    if entry_price > 0:
                        logger.info(f"📊 Candle fallback LTP for {strike_symbol}: ₹{entry_price}")
            except Exception as e:
                logger.warning(f"Candle fallback failed for {strike_symbol}: {e}")

        # B5: the former "Try 4" branch fabricated an entry price from a hand-rolled
        # Black-Scholes-flavored guess (a sum of an intrinsic-value estimate and a time-value
        # estimate) and then placed a LIVE market order at that guessed premium — a
        # stale/synthetic price can be far off the real fill.
        # That fallback is removed. When no real quote (Try 1-2) or recent candle (Try 3) is
        # available, entry_price stays <= 0 and the trade is SKIPPED this cycle (below), matching
        # the fail-safe already used elsewhere in this function. No fabricated-price live orders.

        if entry_price <= 0:
            logger.warning(f"Invalid entry price for {strike_symbol} — no real quote/candle available; skipping trade this cycle (no fabricated-price order).")
            await broadcast_log(f"⚠️ Cannot get a real price for {strike_symbol}. Skipping trade this cycle.", "warning", user_id=client.user_id)
            return

        # ═══════════════════════════════════════════
        # GUARD: one open position per underlying (broker-truth + in-memory)
        # Prevents a SECOND strike on a symbol we already hold (e.g. SBIN 1050PE + 1040PE both
        # open, or three different-strike CRUDEOIL PE positions from two different strategies —
        # 03-08-26: this happened live, 3 concurrent same-direction CRUDEOIL positions, because
        # the broker positions feed can lag a just-placed order by more than the gap between two
        # strategies' signals). Checks BOTH the broker's LIVE positions AND state.active_auto_trades
        # (this process's own authoritative record of what it just placed) — the in-memory check
        # is immune to broker feed lag/staleness, the broker check catches trades placed outside
        # this process. Both the held position and the new strike are OPTION symbols, so comparing
        # their alpha prefixes (SBIN / NIFTY / BANKNIFTY / CRUDEOIL …) reliably means "same underlying".
        # ═══════════════════════════════════════════
        _new_base = _opt_base(strike_symbol)
        if _new_base:
            for _t in (getattr(state, "active_auto_trades", []) or []):
                if _opt_base(_t.get("symbol", "")) == _new_base:
                    logger.info(f"⏭️ Already tracking {_t.get('symbol')} ({_new_base}) — skipping duplicate strike {strike_symbol}.")
                    await broadcast_log(f"⏭️ Skipped {strike_symbol}: already in a {_new_base} position.", "warning", user_id=client.user_id)
                    return
        try:
            _live_positions = await api_queue.enqueue(1, client.get_positions)
            for _p in (_live_positions or []):
                if _p.get("qty", 0) != 0 and _opt_base(_p.get("symbol", "")) == _new_base and _new_base:
                    logger.info(f"⏭️ Already holding {_p.get('symbol')} ({_new_base}) — skipping duplicate strike {strike_symbol}.")
                    await broadcast_log(f"⏭️ Skipped {strike_symbol}: already in a {_new_base} position.", "warning", user_id=client.user_id)
                    return
        except Exception as e:
            logger.warning(f"Position dedup check failed for {strike_symbol}: {e}")

        # ═══════════════════════════════════════════
        # SMART SL — LOCKED canonical 3×1m for EVERY strategy (incl. Strategy 1)
        # Signal/strategy-specific SL math (−2, VIX, 10–20 clamp, % premium, ORB width)
        # is IGNORED. Entry may still prefer last-candle high for Strategy 1.
        # ═══════════════════════════════════════════
        trend_info = analysis.get("trend", {})
        # Safety: analysis["trend"] can be a STRING (many strategies pass {"trend": "NEUTRAL"}) or a
        # dict. Calling .get() on a string crashed execute_auto_trade with "'str' object has no
        # attribute 'get'" (112 failed auto-trades in the logs).
        if isinstance(trend_info, str):
            current_trend = trend_info.upper()
        elif isinstance(trend_info, dict):
            current_trend = (trend_info.get("trend", "") or "").upper()
        else:
            current_trend = "NEUTRAL"

        # ── ENTRY PRICE (LOCKED owner 03-08-26): NEVER buy at candle HIGH ──
        # Old Strategy 1 path set entry = last 1m option high → systematic buy-high → SL.
        # Entry stays at quote LTP / mid from above. Flag ignored if still set by old signals.
        if sig.get("use_1m_option_candle"):
            logger.warning(
                f"⚠️ Ignoring use_1m_option_candle high-entry for {strike_symbol} — "
                f"keeping LTP ₹{entry_price} (buy-high disabled)"
            )

        _chase, _chase_why = await _is_chase_entry(client, strike_symbol, entry_price)
        if _chase:
            logger.info(f"⏭️ Anti-chase: skip {strike_symbol} — {_chase_why}")
            await broadcast_log(
                f"⏭️ Skipped {strike_symbol}: chasing local high ({_chase_why}). Wait for pullback.",
                "info", user_id=client.user_id,
            )
            return

        sl_data = await calculate_smart_sl(strike_symbol, entry_price, current_trend, client)
        sl_points = sl_data["sl_points"]
        sl_method = sl_data["method"]
        target_points = 0.0
        logger.info(f"📊 CANONICAL SL: {sl_points}pts via {sl_method} (strategy={sig.get('strategy')})")

        # User directive: ALL strategies place INTRADAY orders only (not CO/MARGIN/BO).
        product_type = "INTRADAY"



        lot_size = get_lot_size(strike_symbol)
        if "NIFTY" in strike_symbol or "BANKNIFTY" in strike_symbol:
            lots = state.trade_lots
        elif strike_symbol.startswith("MCX:") or strike_symbol.startswith("CDS:"):
            lots = getattr(state, "mcx_lots", 1)
        else:
            lots = getattr(state, "stock_lots", 1)
        qty = lots * lot_size



        # QUALITY / RISK GATE — block junk cheap options and cap per-trade rupee risk.
        _qok, _qreason = _passes_quality_gate(strike_symbol, entry_price, sl_points, qty, state)
        if not _qok:
            logger.info(f"⏭️ Quality gate: skip {strike_symbol} — {_qreason}.")
            await broadcast_log(f"⏭️ Skipped {strike_symbol}: {_qreason}.", "info", user_id=client.user_id)
            return

        # SHADOW MODE (03-08-26): a strategy on state.shadow_strategies records this as a fully
        # simulated trade (ledger entry + state.shadow_trades) and returns here — it never reaches
        # the broker. See _execute_shadow_trade()/check_shadow_trades() for why this is isolated
        # from real order management rather than reusing the account-wide paper_trading toggle.
        if state.is_shadow_strategy(sig.get("strategy", "")):
            await _execute_shadow_trade(
                client, state, strategy_name=sig.get("strategy", ""), strike_symbol=strike_symbol,
                entry_price=entry_price, sl_points=sl_points, sl_method=sl_method,
                target_points=target_points, qty=qty, underlying=symbol,
                regime=getattr(state, "market_regime", "NEUTRAL"), trend=current_trend,
                entry_reason=sig.get("reason", "") or sig.get("signal_reason", ""),
            )
            return

        # FINAL BALANCE GATE — do not send if the broker can't afford this exact order.
        _ok, _req, _av = await _affordable_to_place(client, strike_symbol, qty, "BUY", product_type, entry_price, sl_points)
        if not _ok:
            logger.warning(f"🛑 Insufficient balance for {strike_symbol}: needs ₹{_req:.0f}, have ₹{_av:.0f} — trade NOT sent.")
            await broadcast_log(f"🛑 Insufficient balance: {strike_symbol} needs ₹{_req:.0f}, have ₹{_av:.0f} — trade skipped.", "error", user_id=client.user_id)
            return

        logger.info(f"🚀 AUTO-TRADE: {sig['type']} {strike_symbol} @ ₹{entry_price} | SL: {sl_points} ({sl_method}) | TGT: {target_points} | Product: INTRADAY")
        await broadcast_log(
            f"🚀 AUTO-TRADE: {sig['type']} {strike_symbol} @ ₹{entry_price} | SL: {sl_points}pts | TGT: {target_points}pts | Method: {sl_method}",
            "success"
        )

        # ═══════════════════════════════════════════
        # PLACE ORDER
        # ═══════════════════════════════════════════
        result = await asyncio.to_thread(
            client.place_order,
            symbol=strike_symbol,
            qty=qty,
            side="BUY",
            order_type="MARKET",
            product=product_type,
            limit_price=entry_price,  # Pass pre-fetched price to avoid double-quote
            sl_points=sl_points,
            target_points=target_points
        )

        if result.get("success"):
            track_pending_order(
                result.get("order_id"), 
                strike_symbol, 
                client.user_id,
                sl_order_id=result.get("sl_order_id"),
                tgt_order_id=result.get("tgt_order_id")
            )
            state.record_trade()
            state.add_active_trade(
                symbol=strike_symbol,
                entry_price=entry_price,
                sl_points=sl_points,
                side="BUY",
                sl_order_id=result.get("sl_order_id", ""),
                tgt_order_id=result.get("tgt_order_id", ""),
                sl_order_type=result.get("sl_order_type", 4),
                strategy=sig.get("strategy", "Strategy 1: OB + FVG"),
                fvl_target=sig.get("fvl_target"),
                bars_held=0,
                entry_time=datetime.now(IST).timestamp(),
                latest_hl_lh=sig.get("latest_hl_lh"),
                qty=qty,
                entry_trend=current_trend
            )

            await _record_entry_to_ledger(
                client, symbol, strike_symbol, "BUY", qty, entry_price, sl_points, sl_method,
                target_points, product_type, getattr(state, "market_regime", "NEUTRAL"),
                current_trend, result.get("order_id"), sig.get("strategy", "Strategy 1: OB + FVG"),
                entry_reason=sig.get("reason", "") or sig.get("signal_reason", ""))

            log_trade({
                "symbol": strike_symbol,
                "side": "BUY",
                "qty": qty,
                "price": entry_price,
                "signal_type": f"AUTO_{sig['type']}",
                "status": "PLACED",
                "sl": sl_points,
                "target": target_points,
                "sl_method": sl_method
            })
            best_strike["strike"] = strike_symbol
            best_strike["entry"] = entry_price
            best_strike["sl"] = max(0, entry_price - sl_points)
            best_strike["target"] = (entry_price + target_points) if target_points > 0 else 0
            log_signal([sig], spot, f"🟢 AUTO EXECUTED ({sig['type']})", best_strike)

            await broadcast_log(
                f"✅ Order placed: {strike_symbol} @ ₹{entry_price} | SL: {sl_points}pts | {result.get('message', '')}",
                "success", user_id=client.user_id, telegram_alert=True
            )
            logger.info(f"✅ Auto-trade executed: {result}")

            # Track the strike so it isn't traded again today
            if strike_symbol not in state.traded_strikes_today:
                state.traded_strikes_today.append(strike_symbol)
                state.save()

            # CRITICAL: Warn if SL was not placed (margin shortfall, API error, etc.). Push to
            # Telegram so the owner is pinged immediately to square off / attach a stop by hand —
            # the catastrophic-loss seatbelt in trailing_monitor is the only automatic backstop for
            # a naked trade, and it only fires at a large loss. (A safe automatic square-off needs an
            # orderbook re-check first to avoid orphaning a real-but-uncaptured CO SL leg into a short.)
            if not result.get("sl_order_id"):
                logger.error(f"🚨 CRITICAL: Trade placed WITHOUT Stop Loss! SL order failed for {strike_symbol}")
                await broadcast_log(
                    f"🚨 CRITICAL: Trade {strike_symbol} has NO STOP LOSS! Square off or place SL manually NOW. Msg: {result.get('message', '')}",
                    "error", user_id=client.user_id, telegram_alert=True
                )
        else:
            fail_msg = result.get('message', 'Unknown error')
            logger.error(f"❌ Auto-trade failed: {fail_msg}")
            await broadcast_log(f"❌ Auto-trade failed: {fail_msg}", "error", user_id=client.user_id)
            # Prevent repeated retries on the same strike after a failure
            if strike_symbol not in state.traded_strikes_today:
                state.traded_strikes_today.append(strike_symbol)
            # Set a cooldown to prevent immediate re-trigger
            state._last_trade_fail_time = datetime.now(IST).timestamp()

    except Exception as e:
        logger.error(f"Auto-trade execution error: {e}")
        await broadcast_log(f"❌ Auto-trade error: {str(e)[:100]}", "error", user_id=client.user_id)
        # Set cooldown on exception too
        try:
            state._last_trade_fail_time = datetime.now(IST).timestamp()
        except Exception:
            pass


async def automation_loop():
    """Continuously monitor symbols and execute AI-confirmed signals simultaneously."""
    from app import get_analysis

    logger.info("🤖 Automation Loop Started (VIBE Swarm Mode - Concurrent).")
    
    # Helper Tasks for Concurrent Execution
    async def check_shadow_trades(client, state, u_id):
        """SHADOW MODE (03-08-26): closes simulated trades (from _execute_shadow_trade) when price
        crosses SL/target, or force-closes after a max hold window so nothing lingers untracked
        forever. Fully self-contained — only ever reads/writes state.shadow_trades and the ledger,
        never touches the broker, active_auto_trades, or paper_positions/paper_orders."""
        shadow_trades = getattr(state, "shadow_trades", None)
        if not shadow_trades:
            return
        MAX_SHADOW_HOLD_SECONDS = 6 * 3600  # generous — covers any single session incl. crude evening
        from models import Database
        now_ts = datetime.now(IST).timestamp()
        remaining = []
        changed = False
        for t in shadow_trades:
            try:
                sym = t["symbol"]
                quote = await api_queue.enqueue(3, client.get_quote, sym)
                ltp = float(quote.get("lp", 0)) if quote else 0.0
                exit_price = None
                exit_reason = None
                if ltp > 0 and ltp <= t["sl_price"]:
                    exit_price, exit_reason = ltp, "Shadow SL hit"
                elif ltp > 0 and t.get("target_price") and ltp >= t["target_price"]:
                    exit_price, exit_reason = ltp, "Shadow target hit"
                elif now_ts - t.get("entry_time", now_ts) > MAX_SHADOW_HOLD_SECONDS:
                    exit_price = ltp if ltp > 0 else t["entry_price"]
                    exit_reason = "Shadow max-hold timeout"
                if exit_price is not None:
                    pnl = round((exit_price - t["entry_price"]) * t.get("qty", 0), 2)
                    ok = await Database.record_trade_exit(sym, exit_price, pnl, exit_reason, user_id=u_id)
                    logger.info(f"👻 SHADOW CLOSE: {t.get('strategy')} {sym} @ ₹{exit_price} "
                                f"| PnL ₹{pnl:.2f} ({exit_reason}) | ledger={'ok' if ok else 'no OPEN row found'}")
                    changed = True
                else:
                    remaining.append(t)
            except Exception as _te:
                logger.error(f"Shadow trade check failed for {t.get('symbol')}: {_te}")
                remaining.append(t)
        if changed:
            state.shadow_trades = remaining
            state.save()

    async def eval_strat_2(client, state, u_id):
        try:
            analysis_nifty = await get_analysis("NSE:NIFTY50-INDEX", client=client)
            trend_dict = analysis_nifty.get("trend", {}) if analysis_nifty else {"trend": "NEUTRAL"}
            # Safety: trend_dict can be a string (AI fallback) or a dict
            if isinstance(trend_dict, str):
                current_trend_str = trend_dict.upper()
            elif isinstance(trend_dict, dict):
                current_trend_str = (trend_dict.get("trend", "") or "NEUTRAL").upper()
            else:
                current_trend_str = "NEUTRAL"
            sig_926 = await evaluate_926_strategy(client, state, current_trend=current_trend_str)
            if sig_926:
                can_trade, reason = state.can_trade("Strategy 2", signal_type=sig_926['type'], symbol=sig_926.get('symbol', 'NSE:NIFTY50-INDEX'))
                if can_trade:
                    await risk_orchestrator.propose_trade("Strategy 2", sig_926['symbol'], sig_926, {"trend": trend_dict}, client, state)
        except Exception as e:
            logger.error(f"Error in Strategy 2 loop: {e}")

    async def eval_strat_3(client, state, u_id):
        try:
            if not getattr(state, "strat_orb_triggered", False):
                from datetime import datetime
                from state import IST
                now = datetime.now(IST).strftime("%H:%M:%S")
                if _strat3_orb_window_ok(now):
                    for symbol in state.active_symbols:
                        # Asset-aware gate: equity ORB (active_strategies) vs commodity ORB
                        # (commodity_strategies). Skips symbols whose family/strategy is disabled.
                        if not _strat_enabled_for(state, "Strategy 3: 5-Minute ORB", symbol):
                            continue
                        analysis = await get_analysis(symbol, client=client)
                        if analysis and "candles_5m" in analysis:
                            candles_5m = analysis["candles_5m"]
                            if candles_5m:
                                sig_orb = await evaluate_orb_strategy(client, state, symbol, candles_5m, vix=15.0)
                                if sig_orb:
                                    can_trade, reason = state.can_trade("Strategy 3", signal_type=sig_orb['type'], symbol=symbol)
                                    if can_trade:
                                        await risk_orchestrator.propose_trade("Strategy 3", symbol, sig_orb, {"trend": "NEUTRAL"}, client, state)
                                        break
        except Exception as e:
            logger.error(f"Error in Strategy 3 loop: {e}")

    async def eval_strat_5(client, state, u_id):
        try:
            if "Strategy 5: Optimized Aerospace Mean Reversion" in state.active_strategies:
                sig_strat5 = await evaluate_strat5_strategy(client, state)
                if sig_strat5:
                    can_trade, reason = state.can_trade("Strategy 5", signal_type=sig_strat5['type'], symbol=sig_strat5.get('symbol', 'NSE:NIFTY50-INDEX'))
                    if can_trade:
                        await risk_orchestrator.propose_trade("Strategy 5", sig_strat5.get('symbol', 'NSE:NIFTY50-INDEX'), sig_strat5, {"trend": "N/A"}, client, state)
        except Exception as e:
            logger.error(f"Error in Strategy 5 loop: {e}")
            
    async def eval_symbol_strats(client, state, u_id, symbol):
        try:
            analysis = await get_analysis(symbol, client=client)
            if not analysis: return

            spot = analysis.get("spot", 0)
            candles_5m = analysis.get("candles_5m", [])
            candles_1m = analysis.get("candles_1m", [])
            
            async def run_strat_4():
                if _strat_enabled_for(state, "Strategy 4: Wisdom-Aligned Pullback", symbol):
                    c1h = analysis.get("candles_1h", [])
                    cd = analysis.get("candles_daily", [])
                    if candles_5m and c1h and cd:
                        sig = await evaluate_wisdom_strategy(client, state, symbol, candles_5m, c1h, cd, vix=15.0)
                        if sig and state.can_trade("Strategy 4", signal_type=sig['type'], symbol=symbol)[0]:
                            await risk_orchestrator.propose_trade("Strategy 4", symbol, sig, {"trend": sig.get("metadata", {}).get("trend", "NEUTRAL")}, client, state)
                            
            async def run_strat_6():
                if _strat_enabled_for(state, "Strategy 6: Gap Fill Reversal", symbol) and spot and candles_5m:
                    from engine.strategy_gap import evaluate_gap_fill_strategy
                    has_sig, sig = await evaluate_gap_fill_strategy(spot, candles_5m, analysis, state.active_symbols, client, state)
                    if has_sig and state.can_trade("Strategy 6", signal_type=sig['type'], symbol=symbol)[0]:
                        await risk_orchestrator.propose_trade("Strategy 6", symbol, sig, {"trend": "NEUTRAL"}, client, state)

            async def run_strat_7():
                if _strat_enabled_for(state, "Strategy 7: Swing-Pivot Breakout", symbol) and spot and candles_5m:
                    # Pending logic
                    pending = getattr(state, "strat_7_pending_order", None)
                    if pending:
                        pending["candles_alive"] = pending.get("candles_alive", 0) + 1
                        from datetime import datetime
                        from datetime import time as dtime
                        from state import IST
                        now_t = datetime.now(IST).time()
                        # NSE hard-exit at 15:15 cancels equity pendings only — MCX/CDS continue into evening.
                        _is_com_pending = symbol.startswith(("MCX:", "CDS:"))
                        _nse_eod = (not _is_com_pending) and now_t >= dtime(15, 15)
                        if pending["candles_alive"] > 3 or _nse_eod:
                            state.strat_7_pending_order = None
                        else:
                            triggered = False
                            if pending["direction"] == "CE" and spot >= pending["trigger_price"]: triggered = True
                            elif pending["direction"] == "PE" and spot <= pending["trigger_price"]: triggered = True
                            if triggered and state.can_trade("Strategy 7", signal_type=pending['type'], symbol=symbol)[0]:
                                sig = {"strategy": "Strategy 7", "type": pending["type"].replace("PENDING_", ""), "confidence": 95, "entry_price": pending["trigger_price"], "sl_price": pending["sl_price"], "metadata": {"trend": "NEUTRAL"}}
                                await risk_orchestrator.propose_trade("Strategy 7", symbol, sig, {"trend": "NEUTRAL"}, client, state)
                                state.strat_7_pending_order = None
                        state.save()
                    else:
                        from engine.strategy_swing import evaluate_swing_pivot_strategy
                        _is_com = symbol.startswith(("MCX:", "CDS:"))
                        has_sig, sig = await evaluate_swing_pivot_strategy(spot, candles_5m, analysis, state.active_symbols, client, state, is_commodity=_is_com)
                        if has_sig:
                            state.strat_7_pending_order = {"direction": "CE" if "CE" in sig["type"] else "PE", "type": sig["type"], "trigger_price": sig["trigger_price"], "sl_price": sig["sl_price"], "candles_alive": 0}
                            state.save()

            async def run_strat_8():
                if _strat_enabled_for(state, "Strategy 8: Smart Money Concepts", symbol) and spot and candles_1m:
                    from engine.strategy_8 import evaluate_strategy_8
                    has_sig, sig = await evaluate_strategy_8(symbol, spot, candles_1m, candles_5m, analysis, client, state)
                    if has_sig and state.can_trade("Strategy 8", signal_type=sig.get("type", "CALL"), symbol=symbol)[0]:
                        await risk_orchestrator.propose_trade("Strategy 8", symbol, sig, {"trend": "NEUTRAL"}, client, state)
                        
            async def run_strat_9():
                if _strat_enabled_for(state, "Strategy 9: 9-EMA Momentum Scalper", symbol) and spot and candles_5m:
                    from engine.strategy_9 import evaluate_strategy_9
                    has_sig, sig = await evaluate_strategy_9(symbol, spot, candles_5m, analysis, client, state)
                    if has_sig and state.can_trade("Strategy 9", signal_type=sig.get("type", "CALL"), symbol=symbol)[0]:
                        await risk_orchestrator.propose_trade("Strategy 9", symbol, sig, {"trend": "NEUTRAL"}, client, state)
                        
            async def run_strat_10():
                if _strat_enabled_for(state, "Strategy 10: Adaptive ADX Engine", symbol) and spot and candles_5m:
                    from engine.strategy_10 import evaluate_strategy_10
                    has_sig, sig = await evaluate_strategy_10(symbol, spot, candles_5m, analysis, client, state)
                    if has_sig and state.can_trade("Strategy 10: Adaptive ADX Engine", signal_type=sig.get("type", "CALL"), symbol=symbol)[0]:
                        await risk_orchestrator.propose_trade("Strategy 10: Adaptive ADX Engine", symbol, sig, {"trend": sig.get("metadata", {}).get("regime", "NEUTRAL")}, client, state)

            async def run_strat_11():
                if _strat_enabled_for(state, "Strategy 11: FRVP LVN Vacuum", symbol) and spot and candles_5m:
                    from engine.strategy_11_frvp import evaluate_frvp_strategy
                    sig = await evaluate_frvp_strategy(client, state, symbol, candles_5m, candles_1m=candles_1m, vix=15.0)
                    if sig and state.can_trade("Strategy 11: FRVP LVN Vacuum", signal_type=sig.get("type", "CALL"), symbol=symbol)[0]:
                        await risk_orchestrator.propose_trade("Strategy 11: FRVP LVN Vacuum", symbol, sig, {"trend": sig.get("direction", "NEUTRAL")}, client, state)

            async def run_strat_1():
                # Strategy 1 is equity OB/FVG only — never on MCX/CDS (was buying crude at highs).
                if symbol.startswith(("MCX:", "CDS:")):
                    return
                if "Strategy 1: OB + FVG" not in state.active_strategies or not analysis.get("signals"):
                    return
                trade_placed = False
                for sig in analysis["signals"]:
                        if trade_placed: break
                        if sig.get("type") not in ("CALL", "PUT"): continue
                        tech_conf = sig.get("confidence", 0)
                        if tech_conf < 50: continue
                        trend_info = analysis.get("trend", {})
                        # Safety: trend_info can be a string or dict depending on code path
                        if isinstance(trend_info, str):
                            current_trend = trend_info.upper()
                        elif isinstance(trend_info, dict):
                            current_trend = (trend_info.get("trend", "") or "").upper()
                        else:
                            current_trend = "NEUTRAL"
                        # Trend alignment: skip counter-trend signals
                        if sig["type"] == "CALL" and "BEAR" in current_trend: continue
                        if sig["type"] == "PUT" and "BULL" in current_trend: continue
                        # NEUTRAL/SIDEWAYS: allow high-confidence signals (>= 75) instead of blocking all
                        # Previously this blocked ALL signals in NEUTRAL, which was the #1 reason for
                        # zero trades when AI always said BEARISH and conflicted with math.
                        if ("NEUTRAL" in current_trend or "SIDEWAYS" in current_trend) and tech_conf < 75: continue
                        if state.profit_target_met and tech_conf < 85: continue
                        
                        can_trade, reason = state.can_trade("Strategy 1", signal_type=sig['type'], symbol=symbol)
                        if not can_trade: continue
                        
                        # FIX 3: "AI unavailable" must not act as an AI veto. Signal confidence is
                        # 60 + trend_strength/5 (typically 60-75), so most signals fall in the 60-69
                        # band that REQUIRED ai_confidence >= 50. Whenever the AI provider was
                        # rate-limited, ai_confidence defaulted to 0 and every one of those signals
                        # was silently dropped — a major contributor to "no trades placed".
                        _ai_conf = sig.get("ai_confidence", 0) or 0
                        _ai_down = sig.get("ai_status") in ("unavailable", "skipped", "timeout", "error")
                        if tech_conf >= 70 or (tech_conf >= 50 and _ai_conf >= 50) or (_ai_down and tech_conf >= 60):
                            print(f"📡 Strat1 SIGNAL: {sig['type']} {symbol} conf={tech_conf} trend={current_trend}", flush=True)
                            await risk_orchestrator.propose_trade("Strategy 1", symbol, sig, analysis, client, state)
                            break
                            
            async def run_crude_strats():
                # The evening/EIA crude strategies are the ONLY ones designed for the MCX evening
                # session — the ORB/9-EMA/Swing commodity variants are hard-gated to NSE daytime
                # hours (<=14:15/15:15), so before this, crude had NO strategy that ran in its
                # actual session. Each strategy self-gates by time (evening window / EIA Wednesday)
                # and returns NO TRADE outside it. Signals route through the SAME propose_trade path
                # as every other strategy, so strike/SL/qty and all safety rails apply unchanged.
                if not (symbol.startswith("MCX:") and "CRUDE" in symbol.upper()):
                    return
                if not (spot and candles_5m):
                    return
                coms = getattr(state, "commodity_strategies", [])

                def _crude_atr(candles, lookback=10):
                    lb = candles[-(lookback + 1):-1] if len(candles) > 1 else []
                    if len(lb) < 3:
                        return 0.0
                    return sum(c["high"] - c["low"] for c in lb) / len(lb)

                def _queue_crude_pending(strategy_name, sig):
                    atr = _crude_atr(candles_5m)
                    retrace = max(atr * CRUDE_PULLBACK_ATR_MULT, CRUDE_PULLBACK_MIN_POINTS)
                    signal_price = candles_5m[-1]["close"]
                    entry_trigger = round(
                        signal_price + retrace if sig["type"] == "PUT" else signal_price - retrace, 1
                    )
                    state.crude_pending_order = {
                        "type": sig["type"],
                        "strategy_name": strategy_name,
                        "sig_strategy": sig.get("strategy", strategy_name),
                        "reason": sig.get("reason", ""),
                        "confidence": sig.get("confidence", 80),
                        "asset_class": sig.get("asset_class", "COMMODITY_OPTIONS"),
                        "signal_price": signal_price,
                        "entry_trigger": entry_trigger,
                        "candles_at_signal": len(candles_5m),
                        "confirmed": False,
                    }
                    state.save()
                    print(f"🛢️ CRUDE {sig['type']} signal queued ({strategy_name}) — awaiting confirmation "
                          f"candle + pullback to {entry_trigger} (signal @ {signal_price}, {symbol}).", flush=True)

                # ── Resolve a pending crude entry (confirmation candle + pullback trigger) FIRST.
                # No fresh signal is evaluated while one is in flight — a pending order already
                # claims this underlying, and a second signal here would just race it.
                pending = getattr(state, "crude_pending_order", None)
                if pending:
                    try:
                        n_new = len(candles_5m) - pending.get("candles_at_signal", len(candles_5m))
                        if n_new > CRUDE_PENDING_MAX_CANDLES:
                            print(f"🛢️ Crude pending {pending['type']} expired unconfirmed/untriggered ({symbol}).", flush=True)
                            state.crude_pending_order = None
                            state.save()
                            return
                        if not pending.get("confirmed"):
                            if n_new < 1:
                                return  # still waiting for the confirmation candle to close
                            # CONFIRMATION CANDLE: the candle after the raw signal must not have
                            # already reversed past the signal level — else it was a fake-out and
                            # we drop it instead of chasing a reversal.
                            latest_close = candles_5m[-1]["close"]
                            still_valid = (latest_close <= pending["signal_price"]) if pending["type"] == "PUT" \
                                else (latest_close >= pending["signal_price"])
                            if not still_valid:
                                print(f"🛢️ Crude pending {pending['type']} failed confirmation — reversed ({symbol}).", flush=True)
                                state.crude_pending_order = None
                                state.save()
                                return
                            pending["confirmed"] = True
                            state.save()
                        # PULLBACK TRIGGER: wait for price to retrace back toward the signal level
                        # before actually buying — cheaper entry, and proof the level is holding as
                        # support/resistance rather than paying the peak/trough premium outright.
                        triggered = (spot >= pending["entry_trigger"]) if pending["type"] == "PUT" \
                            else (spot <= pending["entry_trigger"])
                        if not triggered:
                            return
                        if not state.can_trade(pending["strategy_name"], signal_type=pending["type"], symbol=symbol)[0]:
                            state.crude_pending_order = None
                            state.save()
                            return
                        sig = {
                            "type": pending["type"], "side": "BUY", "strategy": pending["sig_strategy"],
                            "reason": f"{pending['reason']} (confirmed pullback entry)",
                            "confidence": pending["confidence"], "asset_class": pending["asset_class"],
                        }
                        print(f"🛢️ CRUDE {pending['type']} PULLBACK ENTRY: {symbol} @ ~{spot} "
                              f"(signal was {pending['signal_price']}).", flush=True)
                        await risk_orchestrator.propose_trade(pending["strategy_name"], symbol, sig, {"trend": "NEUTRAL"}, client, state)
                        state.crude_pending_order = None
                        state.save()
                    except Exception as _pe:
                        logger.error(f"Crude pending-order error for {symbol}: {_pe}")
                        state.crude_pending_order = None
                        state.save()
                    return

                try:
                    if "Commodity: Evening Momentum" in coms:
                        from engine.strategy_crude_evening import generate_signal as _crude_evening
                        sig = _crude_evening(candles=candles_5m)
                        if sig and sig.get("type") in ("CALL", "PUT") and \
                           state.can_trade("Commodity: Evening Momentum", signal_type=sig["type"], symbol=symbol)[0]:
                            _queue_crude_pending("Commodity: Evening Momentum", sig)
                            return
                    if "Commodity: EIA Volatility (Wed)" in coms:
                        from engine.strategy_crude_eia import generate_signal as _crude_eia
                        sig = _crude_eia(candles=candles_5m)
                        if sig and sig.get("type") in ("CALL", "PUT") and \
                           state.can_trade("Commodity: EIA Volatility (Wed)", signal_type=sig["type"], symbol=symbol)[0]:
                            _queue_crude_pending("Commodity: EIA Volatility (Wed)", sig)
                except Exception as _ce:
                    logger.error(f"Crude strategy error for {symbol}: {_ce}")

            async def run_ai_strategies():
                # Strategy Researcher candidates (AI_strategy_N ↔ engine/strategy_auto_*.py).
                # Paper-only until graduated; must be enabled in state.active_strategies.
                try:
                    active = getattr(state, "active_strategies", []) or []
                    if not any(str(s).startswith("AI_strategy_") for s in active):
                        return
                    if not candles_5m:
                        return
                    from engine.ai_strategy_registry import evaluate_enabled_ai_strategies
                    cd = analysis.get("candles_daily", [])
                    hits = await evaluate_enabled_ai_strategies(
                        client, state, symbol, candles_5m, candles_daily=cd, vix=15.0,
                    )
                    for ai_name, sig in hits:
                        can_trade, reason = state.can_trade(
                            ai_name, signal_type=sig.get("type", "CALL"), symbol=symbol
                        )
                        if not can_trade:
                            logger.info(f"⏭️ {ai_name} blocked: {reason}")
                            continue
                        logger.info(
                            f"🤖 AI strategy signal: {ai_name} {sig.get('type')} {symbol} "
                            f"(paper={sig.get('paper_trade_only')}) — {sig.get('reason', '')}"
                        )
                        await risk_orchestrator.propose_trade(
                            ai_name, symbol, sig, {"trend": "NEUTRAL"}, client, state
                        )
                        break  # one AI signal per symbol per loop
                except Exception as _ai_e:
                    logger.error(f"AI strategy eval error for {symbol}: {_ai_e}")

            # Execute all symbol-level strategies simultaneously. return_exceptions=True is required
            # here (03-08-26 fix): without it, ANY single strategy raising (e.g. a missing dependency
            # inside one strategy module, as happened with Strategy 7 / pandas) aborts the whole
            # gather() and silently skips EVERY other strategy for this symbol on this tick too —
            # not just the one that failed.
            import asyncio
            _strat_names = ["Strategy 4", "Strategy 6", "Strategy 7", "Strategy 8", "Strategy 9", "Strategy 10", "Strategy 11", "Strategy 1", "Crude strats", "AI strategies"]
            _results = await asyncio.gather(
                run_strat_4(), run_strat_6(), run_strat_7(), run_strat_8(),
                run_strat_9(), run_strat_10(), run_strat_11(), run_strat_1(),
                run_crude_strats(), run_ai_strategies(),
                return_exceptions=True
            )
            for _name, _res in zip(_strat_names, _results):
                if isinstance(_res, Exception):
                    logger.error(f"{_name} error for {symbol}: {_res}")
        except Exception as e:
            logger.error(f"Error in Symbol loop for {symbol}: {e}")

    while True:
        try:
            # Engine liveness heartbeat: update at the TOP of every iteration so the watchdog
            # knows the loop is alive, even during off-market hours or stuck API calls.
            try:
                import state as _state_hb
                _state_hb.last_automation_cycle_ts = time.time()
            except Exception:
                pass

            any_market_open = is_market_open()
            if not any_market_open:
                # Check if any user has active MCX/CDS symbols that are still open. MCX and CDS keep
                # DIFFERENT hours (MCX crude to 23:30; NSE currency to 17:00), so each must be tested
                # against its own asset-class session — not both against COMMODITY_OPTIONS.
                if is_market_open("COMMODITY_OPTIONS"):
                    any_market_open = True
                    for u_id in list(USER_CONTEXTS.keys()):
                        state = get_user_state(u_id)
                        if "MCX:CRUDEOIL" not in state.active_symbols:
                            state.add_symbol("MCX:CRUDEOIL", enable=True, by_agent=True)
                elif is_market_open("CURRENCY_OPTIONS"):
                    any_market_open = True

            if not any_market_open:
                from datetime import datetime
                from state import IST
                now = datetime.now(IST)
                for u_id in list(USER_CONTEXTS.keys()):
                    state = get_user_state(u_id)
                    state.check_daily_reset()
                    state.check_and_send_eod_report()
                    state.check_and_send_holiday_report()
                    state.check_and_run_nightly_learning()
                    if state.use_ai_oracle and not state.ai_daily_bias and now.hour == 8 and now.minute >= 30:
                        try:
                            from engine.trading_agents_oracle import get_daily_bias
                            bias = await get_daily_bias("^NSEI")
                            state.ai_daily_bias = bias
                            state.save()
                        except Exception: pass
                import asyncio
                await asyncio.sleep(30)
                continue

            for u_id in list(USER_CONTEXTS.keys()):
                client = USER_CONTEXTS.get(u_id)
                if not client: continue
                try:
                    import asyncio
                    # HARD TIMEOUT: is_authenticated must never block the loop. If the Fyers
                    # SDK's internal token check hangs, we skip this user for this cycle.
                    try:
                        _auth_ok = await asyncio.wait_for(
                            api_queue.enqueue(2, client.is_authenticated), timeout=15
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        logger.warning(f"⏱️ is_authenticated timed out for user {u_id} — skipping cycle")
                        continue
                    if not _auth_ok:
                        continue
                except Exception: continue

                state = get_user_state(u_id)
                state.check_daily_reset()
                
                if not state.automation_enabled:
                    continue
                
                # ═══════════════════════════════════════════
                # DAILY DRAWDOWN CIRCUIT BREAKER
                # Stop trading if daily realized loss exceeds the configured limit.
                # This protects capital by halting all new trades for the day.
                # ═══════════════════════════════════════════
                try:
                    daily_realized_pnl = getattr(state, 'daily_realized_pnl', 0.0)
                    # Get available funds (use cached value if available, otherwise estimate)
                    cache = get_user_cache(u_id)
                    available_funds = cache.get("funds", {}).get("availableBalance", 100000)  # Default 1L
                    if available_funds <= 0:
                        available_funds = 100000  # Fallback to prevent division by zero
                    
                    drawdown_limit = available_funds * (DAILY_DRAWDOWN_LIMIT_PCT / 100)
                    if daily_realized_pnl < 0 and abs(daily_realized_pnl) >= drawdown_limit:
                        logger.warning(
                            f"🛑 DAILY DRAWDOWN LIMIT HIT for user {u_id}: "
                            f"Realized PnL ₹{daily_realized_pnl:.2f} exceeds "
                            f"{DAILY_DRAWDOWN_LIMIT_PCT}% limit (₹{drawdown_limit:.2f}). "
                            f"Trading halted for today."
                        )
                        await broadcast_log(
                            f"🛑 DAILY DRAWDOWN LIMIT HIT: ₹{daily_realized_pnl:.2f} — trading halted for today",
                            level="error",
                            user_id=u_id,
                            telegram_alert=True
                        )
                        continue  # Skip all strategy evaluation for this user
                except Exception as e:
                    logger.error(f"Error checking daily drawdown for user {u_id}: {e}")
                    
                # 1. Gather all tasks for this tick simultaneously
                tasks = [
                    eval_strat_2(client, state, u_id),
                    eval_strat_3(client, state, u_id),
                    eval_strat_5(client, state, u_id),
                    check_shadow_trades(client, state, u_id),
                ]
                
                for symbol in state.active_symbols:
                    tasks.append(eval_symbol_strats(client, state, u_id, symbol))
                    
                # 2. Execute the entire Swarm simultaneously (Zero Delay)
                # HARD CYCLE TIMEOUT: A single hung API call must never block the loop forever.
                # If the cycle exceeds MAX_CYCLE_SECS, log and continue to the next tick.
                import asyncio
                MAX_CYCLE_SECS = 180  # 3 minutes max per cycle
                _cycle_t0 = time.time()
                try:
                    # return_exceptions=True (03-08-26 hardening): every task here already has its
                    # own top-level try/except, so this is defense-in-depth only — without it, a
                    # future task added to this list without its own guard could silently cancel
                    # every other strategy AND every symbol's entire evaluation for the whole cycle
                    # (exactly the class of bug found and fixed elsewhere today).
                    _results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=MAX_CYCLE_SECS)
                    for _r in _results:
                        if isinstance(_r, Exception):
                            logger.error(f"Automation cycle task error for user {u_id}: {_r}")
                except asyncio.TimeoutError:
                    logger.warning(
                        f"⏱️ Automation cycle TIMEOUT after {MAX_CYCLE_SECS}s for user {u_id} "
                        f"({len(tasks)} evaluations). A hung API call is blocking the loop."
                    )
                    await broadcast_log(
                        f"⏱️ Strategy cycle timed out after {MAX_CYCLE_SECS}s — a stuck API call is blocking.",
                        level="warning", user_id=u_id
                    )
                # FIX 2: cycle watchdog. The time-boxed strategies are only reachable if a cycle
                # completes well inside their window — Strategy 3 ORB has just 09:20-09:30 (10 min)
                # and Strategy 2 fires 09:26-09:40. A single hung API call previously pushed one
                # cycle to 15-20 MINUTES, which made those windows structurally unreachable and
                # produced zero trades for months. The api_queue per-call timeout fixes the cause;
                # this makes any regression LOUD instead of silent.
                _cycle_secs = time.time() - _cycle_t0
                # Engine liveness heartbeat (#2). A completed cycle is the ONLY reliable proof the
                # engine is actually evaluating strategies; engine_health_watchdog() alerts if this
                # goes stale during market hours.
                try:
                    import state as _state_hb
                    _state_hb.last_automation_cycle_ts = time.time()
                except Exception:
                    pass
                if _cycle_secs > 60:
                    logger.warning(
                        f"🐢 Automation cycle took {_cycle_secs:.0f}s for user {u_id} "
                        f"({len(tasks)} evaluations). Time-boxed strategies (ORB 09:20-09:30, "
                        f"09:26 entry) risk being MISSED — check API-queue timeouts / provider latency."
                    )
                
                # Diagnostic: log strategy activity summary every 2 minutes
                _now_min = int(time.time() / 120)
                if not hasattr(automation_loop, '_last_log_min') or automation_loop._last_log_min != _now_min:
                    automation_loop._last_log_min = _now_min
                    _active = getattr(state, 'active_strategies', [])
                    _auto = getattr(state, 'automation_enabled', False)
                    _trades = getattr(state, 'trades_today', 0)
                    print(f"📊 Cycle #{_now_min}: user={u_id} active={len(_active)} auto={_auto} trades={_trades} cycle={_cycle_secs:.1f}s symbols={state.active_symbols}", flush=True)
                
                # 3. Ask Orchestrator to resolve any simultaneous trade signals
                await risk_orchestrator.flush_signals(u_id)

        except Exception as e:
            logger.error(f"Automation loop error: {e}")

        import asyncio
        await asyncio.sleep(3)
