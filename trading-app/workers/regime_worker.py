import asyncio
import logging
import json
from datetime import datetime
import pytz

import state
from engine.candle_builder import candle_builder
from engine.ai_engine import AIEngine

logger = logging.getLogger("REGIME_WORKER")
IST = pytz.timezone("Asia/Kolkata")

async def regime_evaluator():
    """
    Background worker that runs every 5 minutes to evaluate the market regime.
    Updates state.market_regime instantly for strategies to read with 0 delay.
    """
    logger.info("🟢 Starting 5-Minute Groq Regime Gatekeeper...")
    ai_engine = AIEngine()
    
    # Wait until the first 5-minute candle closes (e.g. 09:20:00)
    # We will sync to run at exactly 5 seconds past the 5-minute mark.
    while True:
        now = datetime.now(IST)
        
        # Calculate seconds until the next 5-minute boundary + 5 seconds
        minutes_to_next = 5 - (now.minute % 5)
        if minutes_to_next == 5 and now.second < 5:
            # We are exactly at the 5-min mark, just need to wait until :05
            seconds_to_wait = 5 - now.second
        elif minutes_to_next == 5 and now.second >= 5:
            # We just passed the trigger mark, wait for the next 5-min cycle
            seconds_to_wait = (5 * 60) - now.second + 5
        else:
            # Wait until the next 5-minute block
            seconds_to_wait = (minutes_to_next * 60) - now.second + 5
            
        await asyncio.sleep(seconds_to_wait)
        
        if not state.is_market_open():
            state.market_regime = "CLOSED"
            state.regime_reason = "Market is closed."
            continue

        try:
            symbol = "NSE:NIFTY50-INDEX"
            
            # 1. Fetch live ticks and candles locally
            spot_data = state.get_user_cache("0").get("spot", {}).get(symbol, {})
            spot_price = spot_data.get("lp", 0)
            vix = state.get_user_cache("0").get("vix", 0)
            
            candles_5m = candle_builder.get_candles(symbol, "5m")

            # CandleBuilder only fills from live WS ticks and is NEVER auto-seeded, so after every
            # restart the regime sat on "Not enough 5m candles" for ~15 min. Seed it once from REST
            # (5m/15m/1h) so the regime works right away. Guarded by is_bootstrapped -> one fetch.
            if len(candles_5m) < 3 and not candle_builder.is_bootstrapped(symbol):
                try:
                    from fyers_client import FyersClient
                    _bc = FyersClient(user_id=1)
                    for _tf, _res in (("5m", "5"), ("15m", "15"), ("1h", "60")):
                        _h = await asyncio.to_thread(_bc.get_historical, symbol, _res, 2)
                        if _h:
                            candle_builder.bootstrap_from_historical(symbol, _tf, _h)
                    candles_5m = candle_builder.get_candles(symbol, "5m")
                    logger.info(f"📊 Regime: seeded CandleBuilder from REST ({len(candles_5m)} 5m candles)")
                except Exception as e:
                    logger.warning(f"Regime CandleBuilder bootstrap failed: {e}")

            if len(candles_5m) < 3:
                state.market_regime = "NEUTRAL"
                state.regime_reason = "Not enough 5m candles formed yet."
                continue

            # 2. Extract quick context for the AI
            # Using the "Micro-Snapshot" pattern so Groq is even faster.
            recent_candles = [
                {
                    "time": datetime.fromtimestamp(c.get("timestamp", c.get("time", 0)), IST).strftime("%H:%M"),
                    "open": c["open"], "high": c["high"],
                    "low": c["low"], "close": c["close"]
                }
                for c in candles_5m[-5:]  # Last 5 candles
            ]
            
            system_prompt = """You are the Global Market Regime Gatekeeper.
Your job is to analyze the 5-minute candle structure and VIX.
Decide if the market is trending strongly enough to allow Breakout strategies, or if it is choppy/sideways (which means breakout trades should be blocked).
Respond ONLY with a JSON object. No markdown, no conversational text.
{
  "regime": "TRENDING_UP" | "TRENDING_DOWN" | "CHOPPY_SIDEWAYS" | "EVENT_RISK_AVOID",
  "reason": "1 sentence explaining why."
}
"""
            user_prompt = f"Current Spot: {spot_price}\nIndia VIX: {vix}\nRecent 5M Candles: {json.dumps(recent_candles)}\nWhat is the current market regime?"

            # 3. Offload strictly to Groq (Zero risk to Gemini/OpenAI rate limits)
            logger.info("🧠 Requesting Groq Regime Evaluation...")
            decision = await ai_engine.run_trading_agent(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                force_provider="groq"
            )
            
            if decision and "regime" in decision:
                state.market_regime = decision.get("regime", "CHOPPY_SIDEWAYS")
                state.regime_reason = decision.get("reason", "Groq evaluated.")
                logger.info(f"🟢 Groq Regime Update: {state.market_regime} - {state.regime_reason}")
            else:
                # Graceful API Fallback
                logger.warning(f"🔴 Groq Regime Evaluation failed. Fallback to NEUTRAL. Output: {decision}")
                state.market_regime = "NEUTRAL"
                state.regime_reason = "Groq API Fallback"
                
        except Exception as e:
            logger.error(f"❌ Regime Worker Error: {e}")
            state.market_regime = "NEUTRAL"
            state.regime_reason = f"Worker Error: {str(e)[:50]}"
