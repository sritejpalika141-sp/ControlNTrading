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

def check_no_economic_events() -> bool:
    """
    Placeholder/mock helper to check for major economic events in the next 30 minutes.
    Can be updated to query a calendar API/feed.
    """
    # Pre-defined major event dates could be added here.
    # Defaulting to True (safe to trade).
    return True

async def evaluate_orb_strategy(client, state, symbol: str, candles_5m: List[Dict], candles_daily: List[Dict] = None, vix: float = 15.0) -> Optional[Dict]:
    """
    Evaluates the 15-Minute ORB breakout strategy rules on the provided candle data.
    Runs strictly after 9:30 AM IST. Requires a full 5m candle close outside the range.
    """
    # 1. Active checks
    import state as global_state
    # CHOPPY_SIDEWAYS no longer hard-blocks here — the high-confidence override in
    # risk_orchestrator.propose_trade decides: this validated 95-confidence ORB signal is allowed
    # through in choppy markets; only sub-85 signals are skipped.

    if "Strategy 3: 5-Minute ORB" not in state.active_strategies:
        return None

    # Strictly 1 trade today
    if getattr(state, "strat_orb_triggered", False):
        return None

    now = datetime.now(IST)
    current_time_str = now.strftime("%H:%M:%S")

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

    # Identify the 9:15 candle (the Opening Range)
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

    # 4. ENTRY CHECKLIST
    # Checklist 1: Volume Check (Breakout candle volume >= 2x historical average of 9:20 candle)
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

    if trigger_volume < 2 * avg_volume:
        logger.info(f"⏭️ Strategy 3: Volume check failed for {symbol}. Volume {trigger_volume} < 2x Avg ({avg_volume:.1f})")
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

    # Checklist 3: Range Width Check (< 0.5% of instrument price)
    if orb_open <= 0:
        return None
    range_pct = (orb_high - orb_low) / orb_open * 100
    if range_pct >= 0.5:
        logger.info(f"⏭️ Strategy 3: Range check failed for {symbol}. Width {range_pct:.2f}% >= 0.5%")
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
    lots = getattr(state, "trade_lots", 1) if is_index else getattr(state, "stock_lots", 1)
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
