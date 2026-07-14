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

_SYSTEM_PROMPT = """You are the Global Market Regime Gatekeeper.
Your job is to analyze the 5-minute candle structure and volatility.
Decide if the market is trending strongly enough to allow Breakout strategies, or if it is choppy/sideways (which means breakout trades should be blocked).
Respond ONLY with a JSON object. No markdown, no conversational text.
{
  "regime": "TRENDING_UP" | "TRENDING_DOWN" | "CHOPPY_SIDEWAYS" | "EVENT_RISK_AVOID",
  "reason": "1 sentence explaining why."
}
"""


async def _compute_regime_for(symbol: str, ai_engine: AIEngine, vix: float = 0, spot: float = 0):
    """Same 5m-candle → Groq regime logic, for ANY market's underlying symbol.
    Returns (regime, reason). Bootstraps candles from REST once if the live builder is empty."""
    candles_5m = candle_builder.get_candles(symbol, "5m")

    # Seed the CandleBuilder from REST once (it only fills from live WS ticks otherwise), so the
    # regime works right away even for a symbol that isn't tick-subscribed (e.g. crude FUT).
    if len(candles_5m) < 3 and not candle_builder.is_bootstrapped(symbol):
        try:
            from fyers_client import FyersClient
            _bc = FyersClient(user_id=1)
            for _tf, _res in (("5m", "5"), ("15m", "15"), ("1h", "60")):
                _h = await asyncio.to_thread(_bc.get_historical, symbol, _res, 2)
                if _h:
                    candle_builder.bootstrap_from_historical(symbol, _tf, _h)
            candles_5m = candle_builder.get_candles(symbol, "5m")
            logger.info(f"📊 Regime: seeded CandleBuilder for {symbol} ({len(candles_5m)} 5m candles)")
        except Exception as e:
            logger.warning(f"Regime CandleBuilder bootstrap failed for {symbol}: {e}")

    if len(candles_5m) < 3:
        return "NEUTRAL", "Not enough 5m candles formed yet."

    recent_candles = [
        {
            "time": datetime.fromtimestamp(c.get("timestamp", c.get("time", 0)), IST).strftime("%H:%M"),
            "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
        }
        for c in candles_5m[-5:]
    ]
    user_prompt = (f"Symbol: {symbol}\nCurrent Spot: {spot}\nIndia VIX: {vix}\n"
                   f"Recent 5M Candles: {json.dumps(recent_candles)}\nWhat is the current market regime?")
    try:
        decision = await ai_engine.run_trading_agent(
            system_prompt=_SYSTEM_PROMPT, user_prompt=user_prompt, force_provider="groq"
        )
        if decision and "regime" in decision:
            return decision.get("regime", "CHOPPY_SIDEWAYS"), decision.get("reason", "Groq evaluated.")
    except Exception as e:
        logger.warning(f"Regime Groq eval failed for {symbol}: {e}")
    return "NEUTRAL", "Groq API Fallback"


async def regime_evaluator():
    """5-minute regime gatekeeper for THREE markets (same logic each):
    - NSE (Indian equity): NIFTY 5m candles + VIX  -> state.market_regime
    - MCX (commodities):   current crude FUT 5m candles -> state.mcx_regime
    - Currency:            news-derived currency trend  -> state.currency_regime
    Each market is only evaluated while it is open; otherwise it reads CLOSED.
    """
    logger.info("🟢 Starting 5-Minute Groq Regime Gatekeeper (NSE / MCX / Currency)...")
    ai_engine = AIEngine()

    while True:
        now = datetime.now(IST)
        minutes_to_next = 5 - (now.minute % 5)
        if minutes_to_next == 5 and now.second < 5:
            seconds_to_wait = 5 - now.second
        elif minutes_to_next == 5 and now.second >= 5:
            seconds_to_wait = (5 * 60) - now.second + 5
        else:
            seconds_to_wait = (minutes_to_next * 60) - now.second + 5
        await asyncio.sleep(seconds_to_wait)

        # ── 1. NSE / Indian equity regime (NIFTY) ──
        try:
            if state.is_market_open():
                cache0 = state.get_user_cache("0")
                spot = (cache0.get("spot", {}) or {}).get("NSE:NIFTY50-INDEX", {}).get("lp", 0)
                vix = cache0.get("vix", 0)
                r, reason = await _compute_regime_for("NSE:NIFTY50-INDEX", ai_engine, vix=vix, spot=spot)
                state.market_regime, state.regime_reason = r, reason
                logger.info(f"🟢 NSE Regime: {r} - {reason}")
            else:
                state.market_regime = "CLOSED"
                state.regime_reason = "Indian equity market is closed."
        except Exception as e:
            logger.error(f"❌ NSE regime error: {e}")
            state.market_regime, state.regime_reason = "NEUTRAL", f"Error: {str(e)[:40]}"

        # ── 2. MCX / commodities regime (current crude FUT as the proxy) ──
        try:
            if state.is_market_open("COMMODITY_OPTIONS"):
                from engine.strikes import resolve_current_commodity_expiry
                crude_fut = resolve_current_commodity_expiry("MCX:CRUDEOIL")
                r, reason = await _compute_regime_for(crude_fut, ai_engine)
                state.mcx_regime, state.mcx_regime_reason = r, reason
                logger.info(f"🟠 MCX Regime ({crude_fut}): {r} - {reason}")
            else:
                state.mcx_regime = "CLOSED"
                state.mcx_regime_reason = "MCX commodities market is closed."
        except Exception as e:
            logger.error(f"❌ MCX regime error: {e}")
            state.mcx_regime, state.mcx_regime_reason = "NEUTRAL", f"Error: {str(e)[:40]}"

        # ── 3. Currency regime (news-derived trend; USDINR FUT candle feed is deferred) ──
        try:
            if state.is_market_open("CURRENCY_OPTIONS"):
                try:
                    from workers.news_worker import news_worker
                    fx_trend = (news_worker.last_summary or {}).get("currency_trend", "NEUTRAL")
                except Exception:
                    fx_trend = "NEUTRAL"
                # Map the news trend to the regime vocabulary for a consistent display.
                fx_map = {"BULLISH": "TRENDING_UP", "BEARISH": "TRENDING_DOWN",
                          "NEUTRAL": "CHOPPY_SIDEWAYS", "VOLATILE": "EVENT_RISK_AVOID"}
                state.currency_regime = fx_map.get(str(fx_trend).upper(), "NEUTRAL")
                state.currency_regime_reason = f"News-derived USD/INR trend: {fx_trend}."
            else:
                state.currency_regime = "CLOSED"
                state.currency_regime_reason = "Currency market is closed."
        except Exception as e:
            logger.error(f"❌ Currency regime error: {e}")
            state.currency_regime, state.currency_regime_reason = "NEUTRAL", f"Error: {str(e)[:40]}"
