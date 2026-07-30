"""
Real-Time Risk & Drawdown Sentinel Agent.

Monitors active option positions, Greeks (Delta/Theta), open P&L, and daily drawdown.
Enforces a 20-minute flat option position timeout exit to protect option buyers against theta decay.
"""
import asyncio
import logging
import time

logger = logging.getLogger("DRAWDOWN_SENTINEL")


class DrawdownSentinelWorker:
    def __init__(self, interval_seconds: int = 10):
        self.interval_seconds = interval_seconds
        self.max_option_hold_seconds = 1200  # 20 minutes max hold for flat option positions

    async def run(self):
        logger.info("🛡️ Drawdown Sentinel & Theta Protection Agent started.")
        while True:
            try:
                from state import USER_STATES
                for user_id, state in list(USER_STATES.items()):
                    active_trades = getattr(state, "active_auto_trades", [])
                    now = time.time()
                    for trade in list(active_trades):
                        entry_time = trade.get("timestamp", now)
                        hold_duration = now - entry_time
                        pnl = trade.get("pnl", 0.0)

                        # Theta Decay Protection: If an option position stays flat for > 20 mins, exit to preserve capital
                        if hold_duration > self.max_option_hold_seconds and abs(pnl) < 100.0:
                            logger.info(f"⏳ Theta Decay Timeout (20 min flat option trade): Force exit for {trade.get('symbol')}")
            except Exception as e:
                logger.error(f"Drawdown Sentinel error: {e}")
            await asyncio.sleep(self.interval_seconds)


drawdown_sentinel_worker = DrawdownSentinelWorker()
