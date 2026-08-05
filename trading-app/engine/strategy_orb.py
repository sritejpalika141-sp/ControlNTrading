"""
Strategy 3: 5-Minute ORB (Opening Range Breakout)
The Opening Range is defined by the HIGH and LOW of the very first 5-minute candle (9:15 AM – 9:20 AM IST).
A LONG trade is triggered when the live price CROSSES above the ORB High during the 9:20 AM candle.
A SHORT trade is triggered when the live price CROSSES below the ORB Low during the 9:20 AM candle.
Entry is taken at market price immediately upon cross.
"""

import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Optional
from engine.strikes import get_strike_recommendations, get_dynamic_lot_size
from engine.economic_calendar import check_no_economic_events
from engine.orb_filters import (
    MIN_ORB_RANGE_PCT,
    MAX_ORB_RANGE_PCT,
    orb_range_ok,
    trend_15m_confirms,
    volume_multiplier,
    passes_volume_check,
)

logger = logging.getLogger("STRATEGY_ORB")
IST = pytz.timezone('Asia/Kolkata')

# Lot size lookup for indices (effective Jan 2026)
LOT_SIZES = {
    "NSE:NIFTY50-INDEX": 65,
    "NSE:BANKNIFTY-INDEX": 30,
    "NSE:FINNIFTY-INDEX": 60,
    "NSE:MIDCPNIFTY-INDEX": 120,
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120
}


async def evaluate_orb_strategy(client, state, symbol: str, candles_5m: List[Dict], candles_daily: List[Dict] = None, vix: float = 15.0, now: Optional[datetime] = None) -> Optional[Dict]:
    """
    Evaluates the 15-Minute ORB breakout strategy rules on the provided candle data.
    Runs strictly after 9:30 AM IST. Requires a full 5m candle close outside the range.

    `now`: optional injectable IST datetime (04-08-26, for engine/backtest_engine.py replay —
    live callers never pass this, so live behavior is unchanged).
    """
    # 1. Active checks
    import state as global_state
    # CHOPPY_SIDEWAYS no longer hard-blocks here — the high-confidence override in
    # risk_orchestrator.propose_trade decides: this validated 95-confidence ORB signal is allowed
    # through in choppy markets; only sub-85 signals are skipped.

    # Asset-aware enablement: equity ORB uses active_strategies; commodity ORB uses commodity_strategies.
    is_commodity = symbol.startswith(("MCX:", "CDS:"))
    if is_commodity:
        if "Commodity: 5-Minute ORB" not in getattr(state, "commodity_strategies", []):
            return None
    elif "Strategy 3: 5-Minute ORB" not in state.active_strategies:
        return None

    # Strictly 1 trade today
    if getattr(state, "strat_orb_triggered", False):
        return None

    now = now or datetime.now(IST)
    current_time_str = now.strftime("%H:%M:%S")

    # Session window: NSE ORB is morning-only; commodity ORB follows MCX open+first-hour style window.
    if is_commodity:
        # MCX open ~09:00 IST; allow ORB-style breakout until 11:00 (commodity morning range).
        if current_time_str > "11:00:00":
            if not getattr(state, "strat_orb_expired", False):
                logger.info(f"⏰ Commodity ORB: Time window closed for {symbol} (11:00). Expired for today.")
                state.strat_orb_expired = True
                state.save()
            return None
        if current_time_str < "09:05:00":
            return None
    else:
        # Time expiration check: if past 10:30 AM IST, mark expired for today
        if current_time_str > "10:30:00":
            if not getattr(state, "strat_orb_expired", False):
                logger.info(f"⏰ Strategy 3: Time window closed for {symbol} (10:30 AM). Expired for today.")
                state.strat_orb_expired = True
                state.save()
            return None

        # Too early: Must be after 9:20:00 AM IST to have the first 5-min candle (9:15) closed
        if current_time_str < "09:20:00":
            return None

    # 2. Extract today's 5m candles
    today = now.date()
    today_candles = []
    for c in candles_5m:
        c_dt = datetime.fromtimestamp(c["timestamp"], tz=pytz.utc).astimezone(IST)
        if c_dt.date() == today:
            today_candles.append((c_dt, c))

    today_candles.sort(key=lambda x: x[0])

    if not today_candles:
        return None

    # Identify the Opening Range (C++ accelerated when available)
    from engine.native_bridge import NativeCore
    if NativeCore.is_available() and len(today_candles) >= 1:
        raw_candles = [c for _, c in today_candles]
        high, low, is_valid = NativeCore.calculate_orb(raw_candles, 1)
        if is_valid:
            orb_high = high
            orb_low = low
            orb_open = raw_candles[0]["open"]
        else:
            first_candle = today_candles[0][1]
            orb_high = first_candle["high"]
            orb_low = first_candle["low"]
            orb_open = first_candle["open"]
    else:
        first_candle = today_candles[0][1]
        orb_high = first_candle["high"]
        orb_low = first_candle["low"]
        orb_open = first_candle["open"]

    # 3. Check for breakout
    long_breakout = False
    short_breakout = False
    trigger_volume = 0
    trigger_close = 0
    
    # We need the current live spot price for live breakout
    try:
        quote = await asyncio.to_thread(client.get_quotes, [symbol])
        spot_price = quote.get(symbol, {}).get("lp", 0)
    except Exception as e:
        logger.error(f"Strategy 3: Failed to fetch live spot price: {e}")
        spot_price = 0

    if spot_price <= 0:
        return None

    # VIX Filter Logic
    if vix > 15.0:
        # Aggressive: Enter immediately upon crossing (Live Spot Check)
        if spot_price > orb_high:
            long_breakout = True
            trigger_close = spot_price
            trigger_volume = first_candle["volume"] # Fallback volume
        elif spot_price < orb_low:
            short_breakout = True
            trigger_close = spot_price
            trigger_volume = first_candle["volume"]
    else:
        # Cautious: Wait for a 5-minute candle to CLOSE outside the range
        # Only evaluate after 9:25:00 so the 9:20 candle is closed
        if current_time_str >= "09:25:00":
            closed_candles = []
            for dt, c in today_candles:
                candle_end_time = dt + timedelta(minutes=5)
                if now >= candle_end_time and dt.hour == 9 and dt.minute > 15:
                    closed_candles.append(c)
            
            if closed_candles:
                latest_closed = closed_candles[-1]
                if latest_closed["close"] > orb_high:
                    long_breakout = True
                    trigger_close = latest_closed["close"]
                    trigger_volume = latest_closed["volume"]
                elif latest_closed["close"] < orb_low:
                    short_breakout = True
                    trigger_close = latest_closed["close"]
                    trigger_volume = latest_closed["volume"]

    if not (long_breakout or short_breakout):
        return None

    # Breakout candle volume (VIX>15 path used to incorrectly use ORB candle volume)
    breakout_candle = None
    if vix > 15.0:
        breakout_candle = today_candles[-1][1] if today_candles else first_candle
        trigger_volume = breakout_candle.get("volume", 0) or first_candle.get("volume", 0)
    # trigger_volume already set for vix<=15 path above

    # 4. ENTRY CHECKLIST
    prev_920_volumes = []
    for c in candles_5m:
        c_dt = datetime.fromtimestamp(c["timestamp"], tz=pytz.utc).astimezone(IST)
        if c_dt.date() < today and c_dt.hour == 9 and c_dt.minute == 20:
            prev_920_volumes.append(c["volume"])

    if prev_920_volumes:
        avg_volume = sum(prev_920_volumes) / len(prev_920_volumes)
    else:
        # Fallback to all historical 5m candles average
        all_vols = [c["volume"] for c in candles_5m if c["volume"] > 0]
        avg_volume = sum(all_vols) / len(all_vols) if all_vols else 1.0

    if not passes_volume_check(
        trigger_volume, avg_volume, vix, symbol=symbol, candles_5m=candles_5m
    ):
        logger.info(
            f"⏭️ Strategy 3: Volume check failed for {symbol}. "
            f"Volume {trigger_volume} < {volume_multiplier(vix)}x Avg ({avg_volume:.1f})"
        )
        return None

    # Checklist 1b: 15m trend alignment (backtest-tuned filter)
    today_5m_only = [c for _, c in today_candles]
    if not trend_15m_confirms(today_5m_only, bullish=bool(long_breakout)):
        logger.info(f"⏭️ Strategy 3: 15m trend filter failed for {symbol}")
        return None

    # Checklist 2: Pre-market Gap Check (< 1%)
    # Use cached spot prices to avoid daily historical API spam
    try:
        import state as global_state
        u_cache = global_state.USER_CACHES.get(str(state.user_id), {})
        spot_data = u_cache.get("all_spots", {}).get(symbol, {})
        prev_close = spot_data.get("prev_close_price", 0)
        today_open = spot_data.get("open_price", 0)
        
        # Fallback to ORB candle open if open_price is missing
        if today_open <= 0:
            today_open = orb_open
            
        if prev_close > 0:
            gap_pct = abs(today_open - prev_close) / prev_close * 100
            if gap_pct >= 1.0:
                logger.info(f"⏭️ Strategy 3: Gap check failed for {symbol}. Gap {gap_pct:.2f}% >= 1.0%")
                return None
        else:
            logger.warning(f"Strategy 3: Missing prev_close_price in cache for {symbol} - skipping gap check.")
    except Exception as e:
        logger.error(f"Strategy 3: Gap check error: {e}")

    # Checklist 3: Range width (0.08% min, 0.5% max)
    ok_range, range_pct = orb_range_ok(orb_high, orb_low, orb_open)
    if not ok_range:
        if range_pct < MIN_ORB_RANGE_PCT:
            logger.info(f"⏭️ Strategy 3: ORB too narrow for {symbol}. Width {range_pct:.3f}% < {MIN_ORB_RANGE_PCT}%")
        else:
            logger.info(f"⏭️ Strategy 3: Range check failed for {symbol}. Width {range_pct:.2f}% >= {MAX_ORB_RANGE_PCT}%")
        return None

    # Checklist 4: Economic event check
    if not check_no_economic_events():
        logger.info(f"⏭️ Strategy 3: Economic event check failed for {symbol}")
        return None

    # 5. Position Sizing (Risk 1% of Capital)
    try:
        funds_resp = await asyncio.to_thread(client.get_funds)
        if isinstance(funds_resp, dict) and "equityAmount" in funds_resp:
            capital = float(funds_resp.get("equityAmount", 100000.0))
        elif isinstance(funds_resp, dict) and "availableBalance" in funds_resp:
            capital = float(funds_resp.get("availableBalance", 100000.0))
        else:
            capital = 100000.0
    except Exception as e:
        logger.warning(f"Strategy 3: Failed to fetch funds: {e}. Defaulting to ₹100,000")
        capital = 100000.0

    if capital <= 0:
        capital = 100000.0

    max_risk = capital * 0.01
    direction = "CALL" if long_breakout else "PUT"
    is_index = "INDEX" in symbol or "NIFTY" in symbol or "BANKNIFTY" in symbol or "FINNIFTY" in symbol

    # 6. Strike/Option Routing (Both Index & Stock)
    expiry = await asyncio.to_thread(client.find_nearest_expiry, trigger_close, symbol)
    if not expiry:
        logger.error(f"Strategy 3: Could not find expiry for {symbol}")
        return None

    option_chain = await asyncio.to_thread(client.get_option_chain_strikes, trigger_close, expiry["code"] if expiry else None, 5, base_symbol=symbol)
    if not option_chain:
        logger.error(f"Strategy 3: Option chain empty for {symbol}")
        return None

    # Pass dte=0 to force ITM/ATM preference as requested by user
    recs = get_strike_recommendations(option_chain, direction, trigger_close, dte=0, exclude_symbols=state.traded_strikes_today)
    if not recs:
        logger.error(f"Strategy 3: No option recommendations for {symbol}")
        return None

    best_strike = recs[0]
    strike_symbol = best_strike["symbol"]

    # Fetch option live quote
    quote_res = await asyncio.to_thread(client.get_quotes, [strike_symbol])
    option_ltp = quote_res.get(strike_symbol, {}).get("lp", best_strike.get("ltp", 0))

    if option_ltp <= 0:
        logger.error(f"Strategy 3: Could not fetch LTP for {strike_symbol}")
        return None

    # Convert underlying points risk to option points risk using 0.55 delta
    index_risk_pts = orb_high - orb_low
    option_risk_pts = index_risk_pts * 0.55
    
    # Cap maximum risk to 50 points to prevent huge losses on massive gap-up ORBs
    if option_risk_pts > 50.0:
        logger.info(f"🛡️ Strategy 3: Capping ORB option risk from {option_risk_pts:.2f} to 50.0 points.")
        option_risk_pts = 50.0

    lot_size = get_dynamic_lot_size(strike_symbol)
    if is_index:
        lots = getattr(state, "trade_lots", 1)
    elif symbol.startswith("MCX:") or symbol.startswith("CDS:"):
        lots = getattr(state, "mcx_lots", 1)
    else:
        lots = getattr(state, "stock_lots", 1)
    qty = lots * lot_size

    target_1 = option_ltp + option_risk_pts
    target_2 = option_ltp + 2 * option_risk_pts

    instrument_type = "Index" if is_index else "Stock"
    logger.info(f"🚀 Strategy 3 {instrument_type} Option Signal: CE/PE={strike_symbol} LTP={option_ltp} Qty={qty} SL_pts={option_risk_pts:.2f} T1={target_1:.2f} T2={target_2:.2f}")

    return {
        "symbol": symbol,
        "type": direction,
        "side": "BUY",
        "strategy": "Strategy 3: 5-Minute ORB",
        "reason": f"5M ORB {instrument_type} {direction} Breakout",
        "confidence": 95,
        "entry_price": option_ltp,
        "sl_points": round(option_risk_pts, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "is_direct_option": True,
        "strike_info": {
            "symbol": strike_symbol,
            "ltp": option_ltp,
            "strike": best_strike.get("strike", 0),
            "type_label": f"Strategy 3 {direction}",
            "score": 95.0,
            "moneyness": best_strike.get("moneyness", "ATM")
        },
        "qty": qty
    }
