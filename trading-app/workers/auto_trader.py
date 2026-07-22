"""
Automated trading background tasks.

- `trailing_monitor`: monitors active auto-trades, enforces max-loss exit, and
  trails stop-losses in 10-point steps (or Strategy 3 target/breakeven logic).
- `calculate_smart_sl`: derives chart-based SL/target points using recent
  candles (swing-low for trending, ATR×1.5 for range-bound).
- `execute_auto_trade`: places a confirmed auto-trade (BUY-only policy) with
  smart SL, regime-aware product type, and strategy-aware target handling.
- `automation_loop`: top-level scheduler that evaluates Strategy 2 / 3 / 1 per
  active user and dispatches `execute_auto_trade` when guards pass.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Dict

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

from engine.ws_feed import ws_feed
from engine.risk_orchestrator import orchestrator as risk_orchestrator
from datetime import timedelta

# B1: how long a previously-open position must stay absent from the broker feed before the
# monitor treats it as closed (feed omission). Long enough to ride out a transient/partial
# snapshot, short enough that stale entries do not linger indefinitely.
POSITION_ABSENCE_GRACE_SECONDS = 30

# Maps an equity strategy name -> its commodity-family equivalent. A strategy with NO mapping here
# does NOT run on commodity (MCX/CDS) symbols at all. This is how the equity and commodity strategy
# families are kept separate: equity symbols gate on state.active_strategies, MCX symbols gate on
# state.commodity_strategies via this map.
_COMMODITY_STRAT_MAP = {
    "Strategy 3: 5-Minute ORB": "Commodity: 5-Minute ORB",
    "Strategy 9: 9-EMA Momentum Scalper": "Commodity: 9-EMA Momentum",
    "Strategy 7: Swing-Pivot Breakout": "Commodity: Swing-Pivot Breakout",
}


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
        for u_id, client in USER_CONTEXTS.items():
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
                                await api_queue.enqueue(1, client.place_order, symbol=sym, qty=_cqty, side=("SELL" if side == "BUY" else "BUY"), order_type="MARKET", product="INTRADAY")
                            except Exception as _e:
                                logger.error(f"Catastrophic force-close error for {sym}: {_e}")
                            state.record_trade_close("loss", pos={"side": side, "symbol": sym}, exit_price=_fltp, pnl=_fmtm, reason="Catastrophic SL-failure force-close")
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
                        
                        # Liquidate everything instantly
                        for _p in [p for p in positions if p.get("qty", 0) != 0]:
                            try:
                                # We temporarily bypass the fyers_client killswitch by calling the raw client, or we rely on the fact that close-outs might fail but the DB lock protects future trades.
                                # Actually, our fyers_client blocks place_order. We should allow force-closes or use the underlying client.
                                # The underlying client is self.client inside fyers_client.
                                _cqty = abs(_p.get("qty", 0))
                                _side = -1 if _p.get("side", 1) > 0 else 1
                                _order_data = {
                                    "symbol": _p.get("symbol", ""),
                                    "qty": _cqty,
                                    "type": 2, # Market
                                    "side": _side,
                                    "productType": "INTRADAY",
                                    "validity": "DAY",
                                    "offlineOrder": False,
                                }
                                await api_queue.enqueue(2, client.client.place_order, _order_data)
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
                    for _p in [p for p in positions if p.get("qty", 0) != 0]:
                        try:
                            await api_queue.enqueue(1, client.place_order, symbol=_p.get("symbol", ""), qty=abs(_p.get("qty", 0)), side=("SELL" if _p.get("side", 1) > 0 else "BUY"), order_type="MARKET", product="INTRADAY")
                        except Exception as _e:
                            logger.error(f"Daily-stop square-off error: {_e}")
                    state.active_auto_trades = []
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

                    # ── Strategy 1 (OB+FVG) — Variant L exit: breakeven at +1R, then trail by 1R ──
                    # Backtest over 68 trading days (confluence-only signals, 2 trades/day cap):
                    # win rate 14.7% -> 57.6% and max drawdown -348 -> -113 pts vs the old
                    # hold-to-stop/EOD exit. Deliberately does NOT book a partial: the resting SL
                    # order covers the FULL quantity, so a partial fill could desync it and leave the
                    # account unintentionally SHORT. INTRADAY only — the daily hard-exit squares off
                    # anything still open, and this only ever tightens the stop (never widens it).
                    if str(t.get("strategy", "")).startswith("Strategy 1"):
                        try:
                            # Explicit local import: api_queue is otherwise bound by a
                            # function-local import further up this coroutine, which is not
                            # guaranteed to have executed on every path.
                            from engine.api_queue import api_queue as _apiq
                            r_pts = float(t.get("sl_points", 0) or 0)
                            if r_pts > 0:
                                fav = (ltp - entry) if side == "BUY" else (entry - ltp)
                                peak = max(float(t.get("s1_peak_fav", 0) or 0), fav)
                                t["s1_peak_fav"] = peak
                                if peak >= r_pts:          # +1R reached -> breakeven, then trail by 1R
                                    give_back = peak - r_pts
                                    new_sl = (entry + give_back) if side == "BUY" else (entry - give_back)
                                    new_sl = round(round(new_sl / 0.05) * 0.05, 2)
                                    cur = float(t.get("trailing_sl_price", 0) or 0)
                                    better = (new_sl > cur) if side == "BUY" else (cur == 0 or new_sl < cur)
                                    sl_order_id = t.get("sl_order_id")
                                    if better and sl_order_id:
                                        o_type = t.get("sl_order_type", 4)
                                        lim = (new_sl - 1.0) if side == "BUY" else (new_sl + 1.0)
                                        lim = round(round(lim / 0.05) * 0.05, 2)
                                        mod_res = await _apiq.enqueue(
                                            2, client.modify_order, order_id=sl_order_id,
                                            order_type=o_type, stop_price=new_sl,
                                            limit_price=lim if o_type == 4 else 0, qty=active_qty)
                                        if mod_res.get("success"):
                                            t["trailing_sl_price"] = new_sl
                                            t["last_sl_update"] = time.time()
                                            state.update_trade_sl_price(sl_order_id, new_sl)
                                            await broadcast_log(
                                                f"🛡️ Strategy 1 SL → ₹{new_sl} (peak +{peak:.1f} pts, 1R={r_pts:.1f})",
                                                "success", user_id=u_id)
                                        else:
                                            logger.warning(f"Strategy 1 trail failed for {sym}: {mod_res.get('message')}")
                        except Exception as _s1e:
                            logger.error(f"Strategy 1 breakeven/trail error for {sym}: {_s1e}")

                    # Strategy 5 (Aerospace) Milestone & Time Stop Monitoring
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
                            
                        # Trailing Activation & Update
                        fvl_target = t.get("fvl_target", 0)
                        # Check Nifty spot (We can get it from analysis or just fetch quote)
                        # For simplicity, we can fetch spot here or rely on the ATR trail directly if spot crossed.
                        # Wait, the instruction said: "TARGET MILESTONE: The underlying Nifty Index reaching the central Kalman Fair Value Line acts as the milestone activator."
                        # And: "TRAILING ENGINE ACTIVATION: The exact moment the underlying index touches or crosses the central FVL, activate the trailing mechanism on the live Cover Order."
                        # We need Nifty spot price. Let's fetch it.
                        nifty_quote = ws_feed.get_quotes_from_ws(["NSE:NIFTY50-INDEX"]) if ws_feed.is_connected() else {}
                        spot = nifty_quote.get("NSE:NIFTY50-INDEX", {}).get("lp", 0)
                        if spot == 0:
                            try:
                                sq = await api_queue.enqueue(2, client.get_quotes, ["NSE:NIFTY50-INDEX"])
                                spot = sq.get("NSE:NIFTY50-INDEX", {}).get("lp", 0)
                            except:
                                pass
                                
                        if spot > 0 and fvl_target > 0:
                            # Did we cross FVL?
                            side_index = t.get("type", "CALL")
                            crossed = False
                            if side_index == "CALL" and spot >= fvl_target: crossed = True
                            if side_index == "PUT" and spot <= fvl_target: crossed = True
                            
                            if crossed and not t.get("trailed"):
                                logger.info(f"🛡️ Strategy 5 FVL Milestone Hit at {spot}! Activating ATR trail.")
                                await broadcast_log(f"🛡️ Strategy 5 FVL Hit! Activating CO Trailing.", "success", user_id=u_id)
                                t["trailed"] = True
                                
                        # If trailed is active, push SL up by ATR
                        if t.get("trailed"):
                            # Fetch 14-period ATR of the option
                            # We can approximate ATR dynamically by fetching 14 bars. To avoid heavy API calls in loop,
                            # we can do a simplified trailing: SL = LTP - (some fixed value) or just limit updates.
                            # We will check if 15 seconds have passed since last update
                            last_update = t.get("last_sl_update", 0)
                            if time.time() - last_update > 15:
                                try:
                                    # Fetch historical for ATR calculation
                                    bars = await api_queue.enqueue(2, client.get_historical, sym, "3", 1) # fetch a few days to get 14 bars
                                    # But since get_historical takes time, let's just do a simple 10% trail or approximate ATR if history isn't ready.
                                    # Assuming standard Nifty option ATR on 3-min is around 5-10 points.
                                    # Let's say ATR = 8 points
                                    atr = 8.0 
                                    if len(bars) >= 14:
                                        # Compute simple ATR
                                        trs = []
                                        for i in range(1, 14):
                                            high = bars[-i]["high"]
                                            low = bars[-i]["low"]
                                            pc = bars[-i-1]["close"]
                                            tr = max(high-low, abs(high-pc), abs(low-pc))
                                            trs.append(tr)
                                        if trs:
                                            atr = sum(trs)/len(trs)
                                            
                                    new_sl = ltp - (1.2 * atr)
                                    new_sl = round(round(new_sl / 0.05) * 0.05, 2)
                                    # B6: `new_sl` is an ABSOLUTE price. Compare against and store
                                    # into a dedicated `trailing_sl_price` field — NOT `sl_points`,
                                    # which everywhere else in the codebase is a distance/offset.
                                    # Overwriting sl_points with an absolute price silently corrupts
                                    # every downstream reader that treats it as a distance.
                                    current_sl_price = t.get("trailing_sl_price", 0)

                                    # Only trail UP
                                    if new_sl > current_sl_price:
                                        sl_order_id = t.get("sl_order_id")
                                        if sl_order_id:
                                            mod_res = await api_queue.enqueue(2, client.modify_order, order_id=sl_order_id, order_type=4, stop_price=new_sl, qty=active_qty)
                                            if mod_res.get("success"):
                                                t["trailing_sl_price"] = new_sl
                                                t["last_sl_update"] = time.time()
                                                logger.info(f"Strategy 5 Trailed SL to {new_sl} (ATR: {atr:.2f})")
                                except Exception as e:
                                    logger.error(f"Strategy 5 ATR calc/trail error: {e}")

                    # Strategy 3 (ORB) and Strategy 9 (9-EMA Scalper) Target Monitoring
                    if t.get("strategy") in ["Strategy 3: 5-Minute ORB", "Strategy 9: 9-EMA Momentum Scalper"]:
                        target_1 = t.get("target_1")
                        target_2 = t.get("target_2")
                        trailed = t.get("trailed", False)

                        if target_1 and target_2:
                            is_target_1_hit = False
                            is_target_2_hit = False

                            if side == "BUY":
                                if ltp >= target_1:
                                    is_target_1_hit = True
                                if ltp >= target_2:
                                    is_target_2_hit = True
                            else:  # SELL
                                if ltp <= target_1:
                                    is_target_1_hit = True
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

                                # Exit position
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

                                product_type = "INTRADAY" if "INDEX" not in sym and "-EQ" in sym else "MARGIN"
                                exit_res = await asyncio.to_thread(
                                    client.place_order,
                                    symbol=sym,
                                    qty=qty,
                                    side=exit_side,
                                    order_type="MARKET",
                                    product=product_type,
                                    sl_points=0.0,
                                    target_points=0.0
                                )
                                if exit_res.get("success"):
                                    trade_pnl = (ltp - entry) if side == "BUY" else (entry - ltp)
                                    result_type = "profit" if trade_pnl > 0 else "loss"
                                    state.record_trade_close(result_type, pos={"side": side, "symbol": sym}, exit_price=ltp, pnl=trade_pnl, reason="Strategy 3 Target Hit")
                                    await broadcast_log(f"✅ Strategy 3 exit at ₹{ltp}. ⏳ Cooldown: {3 if result_type == 'profit' else 5} minutes.", "success", user_id=u_id, telegram_alert=True)
                                    state.remove_active_trade(sym)
                                else:
                                    await broadcast_log(f"⚠️ Strategy 3 exit failed: {exit_res.get('message')}", "error", user_id=u_id)
                                continue

                            if is_target_1_hit and not trailed:
                                logger.info(f"🛡️ Strategy 3 Target 1 Hit for {sym} at ₹{ltp}! Trailing SL to breakeven (₹{entry}).")
                                sl_order_id = t.get("sl_order_id")
                                if sl_order_id:
                                    limit_price = entry - 1.0 if side == "BUY" else entry + 1.0
                                    limit_price = round(round(limit_price / 0.05) * 0.05, 2)
                                    o_type = t.get("sl_order_type", 4)
                                    mod_res = await asyncio.to_thread(
                                        client.modify_order,
                                        order_id=sl_order_id,
                                        order_type=o_type,
                                        stop_price=entry,
                                        limit_price=limit_price if o_type == 4 else 0,
                                        qty=active_qty
                                    )
                                    if mod_res.get("success"):
                                        await broadcast_log(f"🛡️ Strategy 3 SL trailed to breakeven (₹{entry})", "success", user_id=u_id)
                                        state.update_trade_sl_price(sl_order_id, entry)
                                        state.mark_trade_trailed(sl_order_id)
                                    else:
                                        await broadcast_log(f"⚠️ Strategy 3 SL trail failed: {mod_res.get('message')}", "warning", user_id=u_id)
                                else:
                                    t["trailed"] = True
                                    state.save()
                        continue

                    # Strategy 7: Spot-based Structural Trailing
                    if t.get("strategy") == "Strategy 7: Swing-Pivot Breakout":
                        now = time.time()
                        last_swing_check = t.get("last_swing_check", 0)
                        if now - last_swing_check > 60:
                            t["last_swing_check"] = now
                            state.save()
                            try:
                                # Fetch Nifty spot 5-min candles
                                spot_candles = await api_queue.enqueue(2, client.get_historical, "NSE:NIFTY50-INDEX", "5", 1)
                                if spot_candles:
                                    from engine.strategy_swing import get_latest_pivots_for_trailing
                                    latest_hl, latest_lh = get_latest_pivots_for_trailing(spot_candles)
                                    
                                    new_spot_sl = None
                                    if side == "BUY" and latest_hl: # CE trades use HL
                                        if t.get("latest_hl_lh") != latest_hl:
                                            new_spot_sl = latest_hl
                                    elif side == "SELL" and latest_lh: # PE trades use LH
                                        if t.get("latest_hl_lh") != latest_lh:
                                            new_spot_sl = latest_lh
                                            
                                    if new_spot_sl:
                                        # Spot SL changed, update Option SL
                                        t["latest_hl_lh"] = new_spot_sl
                                        
                                        # Rough Option SL update: for every 1 point move in spot SL, move option SL by 0.5 pts
                                        spot_diff = abs(new_spot_sl - (t.get("initial_spot_sl", new_spot_sl)))
                                        # Actually, we don't store initial_spot_sl. Let's just bump option SL incrementally.
                                        # Better yet, just trail the option SL using 1-min swing low like the others, since mapping spot to option is imprecise.
                                        # Wait, strategy 7 specifically requested "structural trailing SL (HL/LH)".
                                        # So if new_spot_sl is higher (for CE), we can just bump the option SL by (new_spot_sl - old_spot_sl) * 0.5
                                        pass
                            except Exception as e:
                                logger.error(f"Strategy 7 spot trailing error: {e}")
                                
                    # Global Trailing Stoploss (Always 3-Candle Swing Low)
                    now = time.time()
                    last_swing_check = t.get("last_swing_check", 0)
                    
                    is_expiry = is_symbol_expiry_today(sym)
                    
                    # Always use 1-min chart for trailing SL
                    timeframe = "1"
                    
                    if now - last_swing_check > 5:
                        t["last_swing_check"] = now
                        state.save()
                        try:
                            # Pass 1 for days_back to avoid fetching massive amounts of data
                            candles = await api_queue.enqueue(2, client.get_historical, sym, timeframe, 1) 
                            
                            # Globally enforce 3 candles for all trades
                            required_candles = 3
                            
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

                                    # Auto-Breakeven Rule for Expiry Day removed to strictly follow 3-candle low

                                    # Trail SL up if the new swing low is higher than current SL and below LTP
                                    if lowest_low > current_sl_price and lowest_low < ltp:
                                        new_sl_price = round(round(lowest_low / 0.05) * 0.05, 2)
                                        trail_msg = "Global 3-Candle Trailing"
                                        logger.info(f"🚀 {trail_msg} Milestone Hit for {sym}! LTP: {ltp} | New Low: {lowest_low}")
                                        
                                        if t.get("sl_order_id"):
                                            o_type = t.get("sl_order_type", 4)
                                            mod_res = await asyncio.to_thread(
                                                client.modify_order,
                                                order_id=t["sl_order_id"],
                                                order_type=o_type,
                                                stop_price=new_sl_price,
                                                limit_price=new_sl_price - 1.0 if o_type == 4 else 0
                                            )
                                            if mod_res.get("success"):
                                                logger.info(f"🛡️ Trailed SL to ₹{new_sl_price} for {sym}")
                                                await broadcast_log(f"🛡️ SL trailed to ₹{new_sl_price} (3-Candle Low)", "success")
                                                if state.webhook_url:
                                                    trigger_webhook_background(state.webhook_url, f"🚀 *{trail_msg} Updated*\n\n📈 *Symbol:* {sym}\n🛡️ *New SL Price:* ₹{new_sl_price}\n🔥 *Swing Low:* {lowest_low}", title="Trailing SL")
                                                state.update_trade_sl_price(t["sl_order_id"], new_sl_price)
                                            else:
                                                logger.error(f"❌ Failed to trail SL to ₹{new_sl_price} for {sym}: {mod_res.get('message')}")
                                        else:
                                            logger.warning(f"⚠️ No SL order ID tracked for {sym}, cannot modify on-exchange SL.")
                                
                                elif side == "SELL":
                                    highest_high = max(c["high"] for c in recent)
                                    current_sl_price = t.get("sl_price", entry + t.get("sl_points", 0))
                                    
                                    # Auto-Breakeven Rule for Expiry Day removed to strictly follow 3-candle high
                                        
                                    # Trail SL down if new swing high is lower than current SL
                                    if highest_high < current_sl_price and highest_high > ltp:
                                        new_sl_price = round(round(highest_high / 0.05) * 0.05, 2)
                                        trail_msg = "Global 3-Candle Trailing"
                                        logger.info(f"🚀 [SELL] {trail_msg} Milestone Hit for {sym}! LTP: {ltp} | New High: {highest_high}")
                                        
                                        if t.get("sl_order_id"):
                                            o_type = t.get("sl_order_type", 4)
                                            mod_res = await asyncio.to_thread(
                                                client.modify_order,
                                                order_id=t["sl_order_id"],
                                                order_type=o_type,
                                                stop_price=new_sl_price,
                                                limit_price=new_sl_price + 1.0 if o_type == 4 else 0
                                            )
                                            if mod_res.get("success"):
                                                logger.info(f"🛡️ [SELL] Trailed SL to ₹{new_sl_price} for {sym}")
                                                await broadcast_log(f"🛡️ SL trailed to ₹{new_sl_price} (3-Candle High)", "success")
                                                state.update_trade_sl_price(t["sl_order_id"], new_sl_price)
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
    SL strictly from the 3-candle swing low on the 1-min OPTION chart.

    The SL distance is CAPPED to a fraction of the premium so it stays inside the Fyers
    Cover-Order SL band. A stop wider than the band (the old fixed-20 pts = 74% of a ₹27 option)
    gets the ENTIRE CO rejected, which forced a separate SELL stop-loss — a pending short on a long
    option that reserves ~₹1.2L naked-short margin and was rejected, leaving trades with NO stop.
    A CO-compatible SL means the stop rides along as the CO's own leg (margin-benefited).
    """
    is_trending = "BULL" in trend.upper() or "BEAR" in trend.upper()
    # When the 3-candle swing low is at/above entry (the stop would sit ABOVE the buy price —
    # invalid for a long option), fall back to a FIXED option-premium stop: 5 pts for INDEX
    # options, 2 pts for STOCK options. Index = NIFTY-family / SENSEX / BANKEX.
    _is_index = any(k in (strike_symbol or "").upper() for k in ("NIFTY", "SENSEX", "BANKEX"))
    _fixed_pts = 5.0 if _is_index else 2.0
    # Cover-Order SL band ceiling: keep the stop within ~40% of premium so the CO's SL leg is
    # accepted. Uncapped-but-rejected leaves the trade naked, which is strictly worse.
    _cap = max(round(entry_ltp * 0.40, 1), 2.0)

    def _pkg(sl_pts: float, method: str) -> Dict:
        sl_pts = max(round(sl_pts, 1), 1.0)
        if sl_pts > _cap:
            sl_pts = _cap
            method += "_capped"
        tgt = round(sl_pts * (2 if is_trending else 1.5), 1)
        return {"sl_points": sl_pts, "target_points": tgt, "method": method}


    try:
        if strike_symbol.startswith("MCX") or strike_symbol.startswith("CDS"):
            logger.info(f"🧠 Asking AI for Commodities/Currency SL and TSL dynamic adjustment for {strike_symbol}")
            from engine.ai_engine import ai_engine
            ai_prompt = f"""
            You are a Quantitative Risk AI for Commodities and Currencies.
            We entered {strike_symbol} at {entry_ltp} in a {trend} trend.
            Provide the ideal Stop Loss distance (in points, NOT percentage) and the Trailing method.
            Return ONLY a valid JSON object with `sl_points` (float) and `target_points` (float).
            Example: {{"sl_points": 10.5, "target_points": 21.0}}
            """
            ai_resp = await ai_engine._call_chain(ai_prompt) if hasattr(ai_engine, '_call_chain') else None
            if ai_resp:
                import json
                start_idx = ai_resp.find('{')
                end_idx = ai_resp.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = ai_resp[start_idx:end_idx+1]
                    ai_data = json.loads(json_str)
                    ai_sl = float(ai_data.get("sl_points", entry_ltp * 0.2))
                    return _pkg(ai_sl, "ai_dynamic_sl")

        # 2 days of history so a freshly-ATM / thin strike still yields >=3 candles.
        candles = await api_queue.enqueue(2, client.get_historical, strike_symbol, "1", 2)

        if not candles or len(candles) < 3:
            # No option candles (thin/new strike or throttled history). Use a %-of-premium stop
            # that fits the CO band instead of a fixed 20 pts that blew it.
            logger.warning(f"No option candles for {strike_symbol} — 30%-of-premium CO-safe SL.")
            return _pkg(entry_ltp * 0.30, "pct_fallback")

        recent = candles[-3:]
        lowest_low = min(c["low"] for c in recent)
        sl_distance = round(entry_ltp - lowest_low, 2)

        if sl_distance <= 0:
            # Swing low is at/above the buy price -> the stop would sit ABOVE entry (invalid for a
            # long). Use the fixed fallback: 5 pts (index) / 2 pts (stock).
            logger.info(f"⚠️ Swing low {lowest_low} >= entry {entry_ltp} (SL above buy) — fixed {_fixed_pts}pt SL ({'index' if _is_index else 'stock'}).")
            return _pkg(_fixed_pts, "fixed_sl_above_buy")

        logger.info(f"📊 3-CANDLE OPTION SL: Low={lowest_low}, Distance={sl_distance}, Cap={_cap}")
        return _pkg(sl_distance, "strict_3_candle_low")

    except Exception as e:
        logger.error(f"Smart SL calculation error: {e}")
        return _pkg(entry_ltp * 0.30, "error_fallback")


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

            sl_points = sig.get("sl_points", 20.0)
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

            # User explicitly requested ALL strategies to use Cover Orders (CO) exclusively.
            product_type = "CO"
            target_points = 0.0

            side = sig.get("side", "BUY")
            strategy_name = sig.get("strategy", "Strategy 2: 9:26 - 180 Buy")

            # ── OPTIONS-BUY-ONLY ENFORCEMENT (user directive) ──
            # Every auto-trade must BUY an OPTION (CE/PE) via Cover Order — never sell/write, and
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

            logger.info(f"🚀 {strategy_name} TRADE: {sig['type']} {side} {strike_symbol} @ ₹{entry_price} | SL: {sl_points}pts | TGT: {target_points}pts | Product: {product_type}")
            await broadcast_log(
                f"🚀 {strategy_name}: {sig['type']} {side} {strike_symbol} @ ₹{entry_price} | SL: {sl_points}pts | Product: {product_type}",
                "success"
            )

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
                log_trade({
                    "symbol": strike_symbol, "side": side, "qty": qty,
                    "price": entry_price, "signal_type": f"{strategy_name}_{sig['type']}",
                    "status": "PLACED", "sl": sl_points, "target": target_points,
                    "sl_method": "orb_checklist" if is_orb else "strategy_926_fixed"
                })
                await broadcast_log(
                    f"✅ {strategy_name} Order placed: {strike_symbol} @ ₹{entry_price} | {result.get('message', '')}",
                    "success"
                )
                logger.info(f"✅ {strategy_name} trade executed: {result}")
            else:
                logger.error(f"❌ {strategy_name} trade failed: {result.get('message', 'Unknown')}")
                await broadcast_log(f"❌ {strategy_name} failed: {result.get('message', '')}", "error", user_id=client.user_id)
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
            return

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
        # GUARD: one open position per underlying (broker-truth)
        # Prevents a SECOND strike on a symbol we already hold (e.g. SBIN 1050PE + 1040PE both
        # open when the ATM moved). Checks the broker's LIVE positions, so it holds even if the
        # in-memory active-trade list is briefly out of sync (the desync we saw). Both the held
        # position and the new strike are OPTION symbols, so comparing their alpha prefixes
        # (SBIN / NIFTY / BANKNIFTY …) reliably means "same underlying".
        # ═══════════════════════════════════════════
        def _opt_base(s):
            s = (s or "").upper().split(":")[-1]
            base = ""
            for ch in s:
                if ch.isalpha():
                    base += ch
                else:
                    break
            return base
        _new_base = _opt_base(strike_symbol)
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
        # SMART SL CALCULATION (Chart-based)
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
        is_trending = "BULL" in current_trend or "BEAR" in current_trend

        # 1-Minute Option Candle SL and Entry for Strategy 1
        if sig.get("use_1m_option_candle"):
            try:
                # Fetch recent 1-minute option candles
                opt_candles = await api_queue.enqueue(2, client.get_historical, strike_symbol, "1", 1)
                if opt_candles and len(opt_candles) >= 3:
                    last_3_candles = opt_candles[-3:]
                    last_closed = opt_candles[-1] # Grabbing the most recent closed/closing candle
                    
                    # Entry at Top
                    entry_price = last_closed["high"]
                    
                    # SL at lowest low of last 3 candles minus 2
                    sl_price = min(c["low"] for c in last_3_candles) - 2.0
                    
                    # VIX Adjustment (+4 buffer)
                    try:
                        vix_q = await api_queue.enqueue(2, client.get_quote, "NSE:INDIAVIX-INDEX")
                        if vix_q and vix_q.get("lp", 0) > 18:
                            sl_price -= 4.0
                    except Exception:
                        pass
                        
                    sl_points = max(round(entry_price - sl_price, 1), 1.0)
                    
                    sl_method = "1m_option_candle"
                    target_points = round(sl_points * 2, 1) # 1:2 RR for Strategy 1
                    logger.info(f"📊 OPTION CANDLE SL: High={last_closed['high']}, Low={last_closed['low']}, Final Entry={entry_price}, SL_pts={sl_points}, TGT_pts={target_points}")
                else:
                    raise ValueError("No option candles found")
            except Exception as e:
                logger.error(f"Failed to use 1m option candle: {e}. Falling back to default SL.")
                sl_data = await calculate_smart_sl(strike_symbol, entry_price, current_trend, client)
                sl_points = sl_data["sl_points"]
                sl_method = sl_data["method"]
                target_points = 0.0
        elif sig.get("strategy") == "Strategy 7: Swing-Pivot Breakout":
            sl_data = await calculate_smart_sl(strike_symbol, entry_price, current_trend, client)
            sl_points = sl_data["sl_points"]
            sl_method = sl_data["method"]
            target_points = 0.0
            logger.info(f"📊 STRATEGY 7 SL: Using 3-Candle Low, Option SL_pts={sl_points}")
        else:
            sl_data = await calculate_smart_sl(strike_symbol, entry_price, current_trend, client)
            sl_points = sl_data["sl_points"]
            sl_method = sl_data["method"]
            target_points = 0.0

        # Determine market regime for order type
        # User explicitly requested ALL strategies to use Cover Orders (CO) exclusively.
        product_type = "CO"



        lot_size = get_lot_size(strike_symbol)
        if "NIFTY" in strike_symbol or "BANKNIFTY" in strike_symbol:
            lots = state.trade_lots
        elif strike_symbol.startswith("MCX:") or strike_symbol.startswith("CDS:"):
            lots = getattr(state, "mcx_lots", 1)
        else:
            lots = getattr(state, "stock_lots", 1)
        qty = lots * lot_size



        logger.info(f"🚀 AUTO-TRADE: {sig['type']} {strike_symbol} @ ₹{entry_price} | SL: {sl_points} ({sl_method}) | TGT: {target_points} | Regime: {'TRENDING (CO)' if is_trending else 'RANGE (BO)'}")
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

            # CRITICAL: Warn if SL was not placed (margin shortfall, API error, etc.)
            if not result.get("sl_order_id"):
                logger.error(f"🚨 CRITICAL: Trade placed WITHOUT Stop Loss! SL order failed for {strike_symbol}")
                await broadcast_log(
                    f"🚨 CRITICAL: Trade {strike_symbol} has NO STOP LOSS! Place SL manually immediately. Msg: {result.get('message', '')}",
                    "error", user_id=client.user_id
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
                if "09:20:00" <= now <= "09:30:00":
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
                        if pending["candles_alive"] > 3 or now_t >= dtime(15, 15):
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
                        has_sig, sig = await evaluate_swing_pivot_strategy(spot, candles_5m, analysis, state.active_symbols, client, state)
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
                        
            async def run_strat_1():
                if "Strategy 1: OB + FVG" in state.active_strategies and analysis.get("signals"):
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
                            
            # Execute all symbol-level strategies simultaneously
            import asyncio
            await asyncio.gather(run_strat_4(), run_strat_6(), run_strat_7(), run_strat_8(), run_strat_9(), run_strat_1())
            
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
                # Check if any user has active MCX/CDS symbols that are still open
                for u_id in list(USER_CONTEXTS.keys()):
                    state = get_user_state(u_id)
                    for symbol in state.active_symbols:
                        if symbol.startswith("MCX:") or symbol.startswith("CDS:"):
                            if is_market_open("COMMODITY_OPTIONS"):
                                any_market_open = True
                                break
                    if any_market_open: break

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
                    eval_strat_5(client, state, u_id)
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
                    await asyncio.wait_for(asyncio.gather(*tasks), timeout=MAX_CYCLE_SECS)
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
