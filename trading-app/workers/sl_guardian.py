"""SL Guardian — dedicated risk-management agent (owner directive 31-07-26).

Guarantees that EVERY open position always has a stop-loss at the broker. Cover Orders occasionally
fill the entry but have their SL leg REJECTED by Fyers (e.g. 'LimitPrice not a valid tick multiple'),
leaving a naked position that can lose the whole premium. This loop is the safety net: every few
seconds it scans open positions, and for any position WITHOUT an active broker stop it immediately
places a protective SL-Market and hands the SL order id to the trailing monitor so it gets trailed.

Why this is safe and non-duplicating:
  - It only acts on positions that have NO pending stop order (type 3/4, status 6) in the orderbook,
    so it never double-protects a healthy CO/BO position.
  - It uses SL-Market (no limit price) which sidesteps the exact tick-limit rejection that breaks the
    CO SL leg.
  - Placing the stop and setting sl_order_id on the tracked trade lets the existing trailing_monitor
    trail it — so "keep the SL" (this agent) + "trail the SL" (trailing_monitor) together form the
    full stop lifecycle.
"""
import asyncio
import logging
from datetime import datetime
import pytz

from engine.api_queue import api_queue
from state import USER_CONTEXTS, get_user_state

logger = logging.getLogger("SL_GUARDIAN")
IST = pytz.timezone("Asia/Kolkata")

GUARDIAN_INTERVAL = 10          # seconds between scans
_PLACED_COOLDOWN_OK = 45        # after a successful protective place
_PLACED_COOLDOWN_FAIL = 8       # retry faster when placement failed (naked risk)
_recent_attempts = {}           # symbol -> last attempt epoch
_recent_attempt_ok = {}         # symbol -> bool last attempt succeeded


def _has_active_stop(orders, symbol) -> bool:
    """True if the orderbook already has a PENDING protective stop (SL-M/SL-L, type 3 or 4,
    status 6 = pending) for this symbol — i.e. the position is protected."""
    for o in (orders or []):
        if o.get("symbol") != symbol:
            continue
        if o.get("type") in (3, 4) and o.get("status") == 6:
            return True
    return False


async def _compute_stop(client, symbol, entry, ltp, side_long):
    """Protective stop using LOCKED canonical calculate_smart_sl (last-3×1m option low).
    Fallback is a tight 3% premium distance — never the old 12% widen."""
    sl_pts = None
    try:
        from workers.auto_trader import calculate_smart_sl
        sl_data = await calculate_smart_sl(symbol, entry, "NEUTRAL", client)
        sl_pts = float(sl_data.get("sl_points") or 0)
    except Exception as e:
        logger.warning(f"Guardian SL calc failed for {symbol}: {e}")
    if not sl_pts or sl_pts <= 0:
        sl_pts = max(round(entry * 0.03, 1), 1.0) if entry > 0 else 5.0
    stop = round(entry - sl_pts, 1) if side_long else round(entry + sl_pts, 1)
    # Ensure the trigger is on the correct side of the current price (below LTP for a long).
    ref = ltp or entry
    if side_long and stop >= ref:
        stop = round(ref - max(2.0, entry * 0.03), 1)
    elif (not side_long) and stop <= ref:
        stop = round(ref + max(2.0, entry * 0.03), 1)
    return round(stop, 1), sl_pts


async def sl_guardian():
    # Use logger (writes to logs/dashboard.log with the rest of the app) for all events.
    logger.info("🛡️ SL Guardian started — guarantees every open position always has a stop-loss.")
    _tick = 0
    while True:
        try:
            _tick += 1
            now = datetime.now(IST).timestamp()
            _scanned = _naked = 0
            for u_id, client in list(USER_CONTEXTS.items()):
                try:
                    st = get_user_state(u_id)
                    positions = await api_queue.enqueue(1, client.get_positions) or []
                    open_pos = [p for p in positions if abs(int(p.get("qty", 0) or 0)) > 0]
                    # RECONCILE tracked trades vs the broker's real open positions FIRST — this must
                    # run even when there are zero open positions (that's exactly when every tracked
                    # entry is a stale phantom blocking its strategy from re-entering). Grace period
                    # guards against transient feed blips.
                    _dropped = st.reconcile_active_trades({p.get("symbol") for p in open_pos})
                    if _dropped:
                        logger.warning(f"🧹 Guardian reconciled stale trades (position closed): {_dropped}")
                    if not open_pos:
                        continue
                    _scanned += len(open_pos)
                    orders = await api_queue.enqueue(2, client.get_orders) or []
                    for p in open_pos:
                        sym = p.get("symbol")
                        if not sym:
                            continue
                        if _has_active_stop(orders, sym):
                            continue  # already protected — nothing to do
                        # Cooldown: shorter after failure so a naked MCX position is retried quickly.
                        _cd = _PLACED_COOLDOWN_OK if _recent_attempt_ok.get(sym) else _PLACED_COOLDOWN_FAIL
                        if now - _recent_attempts.get(sym, 0) < _cd:
                            continue

                        qty = abs(int(p.get("qty", 0) or 0))
                        side_long = int(p.get("qty", 0) or 0) > 0
                        entry = float(p.get("buyAvg") or p.get("netAvg") or p.get("avgPrice") or 0)
                        ltp = float(p.get("ltp") or 0)
                        if entry <= 0:
                            entry = ltp
                        if entry <= 0:
                            logger.error(f"🛡️ Guardian: cannot price {sym} (no entry/ltp) — skipping this tick.")
                            continue

                        _naked += 1
                        stop, sl_pts = await _compute_stop(client, sym, entry, ltp, side_long)
                        _recent_attempts[sym] = now
                        exit_side = -1 if side_long else 1
                        logger.warning(f"🛡️ Guardian: NAKED position {sym} (entry {entry}, ltp {ltp}) — "
                                       f"placing protective SL-M @ {stop} ({sl_pts}pts).")
                        res = await asyncio.to_thread(client.place_stop_loss, sym, qty, stop, exit_side,
                                                       client._position_product(p) or client.resolve_exit_product(sym, "INTRADAY"))
                        ok = isinstance(res, dict) and (res.get("s") == "ok" or res.get("id"))
                        oid = (res or {}).get("id", "")
                        _recent_attempt_ok[sym] = bool(ok)
                        if ok:
                            logger.warning(f"🛡️ Guardian placed protective SL for {sym} @ {stop} (id {oid}).")
                            # Register the SL id on the tracked trade so trailing_monitor trails it.
                            try:
                                t = next((x for x in getattr(st, "active_auto_trades", [])
                                          if x.get("symbol") == sym), None)
                                if t is not None:
                                    t["sl_order_id"] = oid
                                    t["sl_order_type"] = 3
                                    t["sl_price"] = stop
                                    t["sl_points"] = sl_pts
                                    st.save()
                            except Exception as _re:
                                logger.warning(f"Guardian could not register SL for trailing ({sym}): {_re}")
                            await _alert(st, f"🛡️ SL Guardian placed a protective stop for {sym} at ₹{stop} "
                                             f"(entry ₹{entry}) — the CO stop had failed, position was naked.")
                        else:
                            logger.error(f"🛡️ Guardian FAILED to place SL for {sym}: {res}")
                            await _alert(st, f"🚨 SL Guardian could NOT place a stop for naked {sym} "
                                             f"(entry ₹{entry}). SQUARE OFF MANUALLY NOW. Broker said: "
                                             f"{(res or {}).get('message', res)}")
                except Exception as ue:
                    logger.error(f"🛡️ SL Guardian user {u_id} error: {ue}")
            # Heartbeat every ~6 ticks (~60s) so the loop is visibly alive even when nothing is naked.
            if _tick % 6 == 1:
                logger.info(f"🛡️ Guardian scan: {_scanned} open position(s), {_naked} naked this tick.")
        except Exception as e:
            logger.error(f"🛡️ SL Guardian loop error: {e}")
        await asyncio.sleep(GUARDIAN_INTERVAL)


async def _alert(state, msg: str):
    """Best-effort Telegram/webhook alert; never raises."""
    try:
        wh = getattr(state, "webhook_url", "")
        if wh:
            from engine.notifier import trigger_webhook_background
            trigger_webhook_background(wh, msg, title="🛡️ SL Guardian")
    except Exception:
        pass
