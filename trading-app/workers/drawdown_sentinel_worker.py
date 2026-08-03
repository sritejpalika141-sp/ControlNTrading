"""
Real-Time Risk & Drawdown Sentinel Agent.

Monitors active option positions and enforces a 20-minute flat option position timeout exit
to protect option buyers against theta decay.
"""
import asyncio
import logging
import time

from engine.api_queue import api_queue
from engine.ws_feed import ws_feed
from state import USER_CONTEXTS, broadcast_log, get_user_state, get_lot_size

logger = logging.getLogger("DRAWDOWN_SENTINEL")

FLAT_PNL_THRESHOLD = 100.0  # ₹ — "flat" means MTM within ±this band


class DrawdownSentinelWorker:
    def __init__(self, interval_seconds: int = 10):
        self.interval_seconds = interval_seconds
        self.max_option_hold_seconds = 1200  # 20 minutes max hold for flat option positions

    async def _trade_mtm(self, trade: dict, ltp: float, qty: int) -> float:
        entry = float(trade.get("entry_price") or 0)
        side = trade.get("side", "BUY")
        if entry <= 0 or ltp <= 0 or qty <= 0:
            return 0.0
        if side == "BUY":
            return (ltp - entry) * qty
        return (entry - ltp) * qty

    async def _force_exit(self, user_id: int, state, trade: dict, ltp: float, mtm: float) -> None:
        client = USER_CONTEXTS.get(user_id)
        if not client:
            return

        sym = trade.get("symbol")
        side = trade.get("side", "BUY")
        qty = int(trade.get("qty") or 0)
        if qty <= 0:
            qty = state.trade_lots * get_lot_size(sym)

        sl_order_id = trade.get("sl_order_id")
        if sl_order_id:
            try:
                await api_queue.enqueue(2, client.cancel_order, sl_order_id)
            except Exception as e:
                logger.warning(f"Drawdown Sentinel: SL cancel failed for {sym}: {e}")

        exit_side = "SELL" if side == "BUY" else "BUY"
        if getattr(client, "_is_option_symbol", lambda _s: False)(sym):
            if exit_side != "SELL":
                logger.error(f"Drawdown Sentinel blocked {sym}: options buy-only")
                return
            product_type = client.resolve_exit_product(sym, "MARGIN")
        else:
            product_type = "INTRADAY" if "-EQ" in sym else "MARGIN"
        try:
            res = await api_queue.enqueue(
                1,
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
            if isinstance(res, dict) and res.get("success"):
                result_type = "profit" if mtm > 0 else "loss" if mtm < 0 else "breakeven"
                state.record_trade_close(
                    result_type,
                    pos={**trade, "strategy": trade.get("strategy")},
                    exit_price=ltp,
                    pnl=mtm,
                    reason="Theta decay timeout (20 min flat)",
                )
                state.remove_active_trade(sym)
                state.save()
                await broadcast_log(
                    f"⏳ Theta timeout: exited {sym} after 20m flat (MTM ₹{mtm:.0f})",
                    "warning",
                    user_id=user_id,
                    telegram_alert=True,
                )
            else:
                logger.error(f"Drawdown Sentinel exit failed for {sym}: {res}")
        except Exception as e:
            logger.error(f"Drawdown Sentinel force-exit error for {sym}: {e}")

    async def run(self):
        logger.info("🛡️ Drawdown Sentinel & Theta Protection Agent started.")
        while True:
            try:
                now = time.time()
                for user_id, client in list(USER_CONTEXTS.items()):
                    if int(user_id) <= 0:
                        continue
                    state = get_user_state(user_id)
                    active_trades = list(getattr(state, "active_auto_trades", []))
                    if not active_trades:
                        continue

                    quotes = {}
                    if ws_feed.is_connected():
                        quotes = ws_feed.get_quotes_from_ws([t["symbol"] for t in active_trades])

                    for trade in active_trades:
                        opened_at = trade.get("opened_at") or trade.get("entry_time") or now
                        hold_duration = now - float(opened_at)
                        if hold_duration <= self.max_option_hold_seconds:
                            continue

                        sym = trade.get("symbol")
                        ltp = float((quotes.get(sym) or {}).get("lp") or 0)
                        if ltp <= 0:
                            try:
                                fresh = await api_queue.enqueue(2, client.get_quote, sym)
                                ltp = float((fresh or {}).get("lp") or 0)
                            except Exception:
                                ltp = 0.0
                        if ltp <= 0:
                            continue

                        qty = int(trade.get("qty") or 0) or state.trade_lots * get_lot_size(sym)
                        mtm = await self._trade_mtm(trade, ltp, qty)
                        if abs(mtm) >= FLAT_PNL_THRESHOLD:
                            continue

                        logger.info(
                            f"⏳ Theta Decay Timeout: force exit {sym} "
                            f"(held {hold_duration/60:.1f}m, MTM ₹{mtm:.0f})"
                        )
                        await self._force_exit(user_id, state, trade, ltp, mtm)
            except Exception as e:
                logger.error(f"Drawdown Sentinel error: {e}")
            await asyncio.sleep(self.interval_seconds)


drawdown_sentinel_worker = DrawdownSentinelWorker()
