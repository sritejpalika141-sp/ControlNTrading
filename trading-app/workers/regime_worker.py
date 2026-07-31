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
        return "WARMING_UP", "Not enough 5m candles formed yet — regime warming up."

    recent_candles = [
        {
            "time": datetime.fromtimestamp(c.get("timestamp", c.get("time", 0)), IST).strftime("%H:%M"),
            "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
        }
        for c in candles_5m[-5:]
    ]
    user_prompt = (f"Symbol: {symbol}\nCurrent Spot: {spot}\nIndia VIX: {vix}\n"
                   f"Recent 5M Candles: {json.dumps(recent_candles)}\nWhat is the current market regime?")
    # Use the FULL provider fallback chain (groq → gemini → github → claude → …) with per-provider
    # key rotation, NOT groq-only. Previously this forced Groq alone, so a single Groq 429/timeout
    # made the regime silently return NEUTRAL even though Gemini/others were available. The regime
    # runs every 5 min (not in the hot trade path), so the extra fall-through latency is irrelevant.
    try:
        decision = await ai_engine.run_trading_agent(
            system_prompt=_SYSTEM_PROMPT, user_prompt=user_prompt
        )
        if decision and "regime" in decision:
            return decision.get("regime", "CHOPPY_SIDEWAYS"), decision.get("reason", "AI evaluated.")
    except Exception as e:
        logger.warning(f"Regime AI eval failed for {symbol}: {e}")
    # Mathematical Technical Price Action Fallback (prevents "AI down" warnings during AI key cooldowns)
    try:
        closes = [float(c["close"]) for c in candles_5m[-5:]]
        highs = [float(c["high"]) for c in candles_5m[-5:]]
        lows = [float(c["low"]) for c in candles_5m[-5:]]
        span = max(highs) - min(lows)
        
        if closes[-1] > closes[0] and span > (spot * 0.001):
            return "TRENDING_UP", "Technical Math: Bullish 5m price expansion"
        elif closes[-1] < closes[0] and span > (spot * 0.001):
            return "TRENDING_DOWN", "Technical Math: Bearish 5m price breakdown"
        else:
            return "CHOPPY_SIDEWAYS", "Technical Math: 5m range consolidation"
    except Exception:
        return "TRENDING_UP", "Technical Math fallback active"


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

        # ── 1. NSE / BSE Indian equity regimes (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) ──
        try:
            if state.is_market_open():
                spot, vix = 0, 0
                for _uid_key, _cache in state.USER_CACHES.items():
                    if not _cache.get("is_auth"):
                        continue
                    _spot_dict = _cache.get("spot") or {}
                    _s = _spot_dict.get("lp", 0)
                    if _s > 0:
                        spot = _s
                    _vix_dict = _cache.get("vix") or {}
                    _v = _vix_dict.get("lp", 0) if isinstance(_vix_dict, dict) else 0
                    if _v > 0:
                        vix = _v
                    if spot > 0 and vix > 0:
                        break

                # Primary NIFTY regime
                r, reason = await _compute_regime_for("NSE:NIFTY50-INDEX", ai_engine, vix=vix, spot=spot)
                state.market_regime, state.regime_reason = r, reason
                state.asset_regimes["NSE:NIFTY50-INDEX"] = r
                state.asset_regime_reasons["NSE:NIFTY50-INDEX"] = reason
                logger.info(f"🟢 NSE NIFTY Regime: {r} - {reason}")

                # Additional Indices: BANKNIFTY, FINNIFTY, SENSEX
                for idx_sym in ["NSE:NIFTYBANK-INDEX", "NSE:FINNIFTY-INDEX", "BSE:SENSEX-INDEX"]:
                    try:
                        idx_r, idx_reason = await _compute_regime_for(idx_sym, ai_engine, vix=vix)
                        state.asset_regimes[idx_sym] = idx_r
                        state.asset_regime_reasons[idx_sym] = idx_reason
                        logger.info(f"🟢 {idx_sym} Regime: {idx_r} - {idx_reason}")
                    except Exception as ex:
                        state.asset_regimes[idx_sym] = r
                        state.asset_regime_reasons[idx_sym] = f"Fallback to NIFTY: {ex}"
            else:
                state.market_regime = "CLOSED"
                state.regime_reason = "Indian equity market is closed."
                for idx_sym in ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX", "NSE:FINNIFTY-INDEX", "BSE:SENSEX-INDEX"]:
                    state.asset_regimes[idx_sym] = "CLOSED"
                    state.asset_regime_reasons[idx_sym] = "Equity market closed."
        except Exception as e:
            logger.error(f"❌ NSE regime error: {e}")
            state.market_regime, state.regime_reason = "NEUTRAL", f"Error: {str(e)[:40]}"

        # ── 2. MCX / Commodities regimes (CRUDEOIL & GOLD) ──
        try:
            if state.is_market_open("COMMODITY_OPTIONS"):
                from engine.strikes import resolve_current_commodity_expiry
                from fyers_client import FyersClient
                fc_stub = FyersClient(user_id=1)

                # Crudeoil
                try:
                    crude_fut = resolve_current_commodity_expiry("MCX:CRUDEOIL", client=fc_stub)
                    r_crude, reason_crude = await _compute_regime_for(crude_fut, ai_engine)
                    state.mcx_regime, state.mcx_regime_reason = r_crude, reason_crude
                    state.asset_regimes["MCX:CRUDEOIL"] = r_crude
                    state.asset_regimes[crude_fut] = r_crude
                    state.asset_regime_reasons["MCX:CRUDEOIL"] = reason_crude
                    logger.info(f"🟠 MCX Crude Regime ({crude_fut}): {r_crude} - {reason_crude}")
                except Exception as ex_c:
                    logger.warning(f"MCX Crude regime eval failed: {ex_c}")

                # Gold
                try:
                    gold_fut = resolve_current_commodity_expiry("MCX:GOLD", client=fc_stub)
                    r_gold, reason_gold = await _compute_regime_for(gold_fut, ai_engine)
                    state.asset_regimes["MCX:GOLD"] = r_gold
                    state.asset_regimes[gold_fut] = r_gold
                    state.asset_regime_reasons["MCX:GOLD"] = reason_gold
                    logger.info(f"🟠 MCX Gold Regime ({gold_fut}): {r_gold} - {reason_gold}")
                except Exception as ex_g:
                    logger.warning(f"MCX Gold regime eval failed: {ex_g}")
            else:
                state.mcx_regime = "CLOSED"
                state.mcx_regime_reason = "MCX commodities market is closed."
                state.asset_regimes["MCX:CRUDEOIL"] = "CLOSED"
                state.asset_regimes["MCX:GOLD"] = "CLOSED"
        except Exception as e:
            logger.error(f"❌ MCX regime error: {e}")
            state.mcx_regime, state.mcx_regime_reason = "NEUTRAL", f"Error: {str(e)[:40]}"

        # ── 3. Currency regime (news-derived trend) ──
        try:
            if state.is_market_open("CURRENCY_OPTIONS"):
                try:
                    from workers.news_worker import news_worker
                    fx_trend = (news_worker.last_summary or {}).get("currency_trend", "NEUTRAL")
                except Exception:
                    fx_trend = "NEUTRAL"
                fx_map = {"BULLISH": "TRENDING_UP", "BEARISH": "TRENDING_DOWN",
                          "NEUTRAL": "CHOPPY_SIDEWAYS", "VOLATILE": "EVENT_RISK_AVOID"}
                state.currency_regime = fx_map.get(str(fx_trend).upper(), "NEUTRAL")
                state.currency_regime_reason = f"News-derived USD/INR trend: {fx_trend}."
                state.asset_regimes["NSE:USDINR-FUT"] = state.currency_regime
            else:
                state.currency_regime = "CLOSED"
                state.currency_regime_reason = "Currency market is closed."
                state.asset_regimes["NSE:USDINR-FUT"] = "CLOSED"
        except Exception as e:
            logger.error(f"❌ Currency regime error: {e}")
            state.currency_regime, state.currency_regime_reason = "NEUTRAL", f"Error: {str(e)[:40]}"

