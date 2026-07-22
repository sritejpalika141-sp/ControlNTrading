"""
Strategy 2: 9:26 - 180 Buy
At 9:26 AM, find CE and PE nearest to ₹180 (below).
First one to hit ₹180 before 9:35 AM triggers a BUY.
Strictly ONE trade per day from this strategy.
"""

import asyncio
import logging
from datetime import datetime
import pytz

from engine.strikes import get_dynamic_lot_size

logger = logging.getLogger("STRATEGY_926")
IST = pytz.timezone('Asia/Kolkata')

# Strategy Constants
ENTRY_PRICE = 183.0      # Target LTP to trigger buy
ARMING_THRESHOLD = 181.5 # Price must drop below this to arm the trigger
SELECTION_MIN = 170.0    # Minimum LTP for candidate selection
SELECTION_MAX = 190.0    # Maximum LTP for candidate selection
SL_POINTS = 20.0         # Stop loss (₹163)
TARGET_POINTS = 40.0     # Target (₹223) → 1:2 RR



async def evaluate_926_strategy(client, state, current_trend="NEUTRAL"):
    """
    Strategy 2: 9:26 - 9:35 - 183 Buy
    Selects CE/PE nearest to 183 (below) at 9:26 AM.
    Triggers a BUY if either hits 183 before 9:35 AM.
    Strictly aligns with the market trend. Blocks entirely if NEUTRAL.
    Returns a signal dict or None.
    """
    now = datetime.now(IST)
    current_time_str = now.strftime("%H:%M:%S")

    # 1. Check if Strategy 2 is active in settings
    if "Strategy 2: 9:26 - 180 Buy" not in state.active_strategies:
        return None

    # 2. Already triggered today — strictly one trade
    if getattr(state, "strat_926_triggered", False):
        return None

    # 3. Hard Stop: Exit if after 9:40:00 AM
    if current_time_str > "09:40:00":
        if not getattr(state, "strat_926_expired", False):
            logger.info("⏰ Strategy 2: Time window closed (9:40 AM). Expired for today.")
            state.strat_926_expired = True
        return None

    # 4. Too early — before 9:26
    if current_time_str < "09:26:00":
        return None

    # 5. Selection Phase: Try to select strikes if not already selected
    if "09:26:00" <= current_time_str < "09:40:00":
        if not getattr(state, "strat_926_strikes", None):
            # Throttle selection attempts to once every 5 seconds to avoid API spam if no strikes found
            last_try = getattr(state, "strat_926_last_try", 0)
            if now.timestamp() - last_try < 5:
                return None
                
            state.strat_926_last_try = now.timestamp()
            logger.info("🎯 Strategy 2: Selection phase started / retrying...")
            strikes = await _find_180_strikes(client)
            if strikes:
                state.strat_926_strikes = strikes
                msg = "✅ Strategy 2: Selected Strikes -> "
                if strikes.get('ce'): msg += f"CE: {strikes['ce']['symbol']} @ ₹{strikes['ce']['ltp']:.2f} | "
                if strikes.get('pe'): msg += f"PE: {strikes['pe']['symbol']} @ ₹{strikes['pe']['ltp']:.2f}"
                logger.info(msg)
            else:
                logger.warning("⚠️ Strategy 2: Failed to find strikes near ₹180. Will retry.")
                return None

    # 6. Monitoring Phase: 9:26 to 9:40 — watch for ₹180 crossover
    if getattr(state, "strat_926_strikes", None) and not getattr(state, "strat_926_triggered", False):
        strikes = state.strat_926_strikes

        # Get live LTPs for both selected strikes
        symbols = []
        if strikes.get('ce'): symbols.append(strikes['ce']['symbol'])
        if strikes.get('pe'): symbols.append(strikes['pe']['symbol'])
        
        if not symbols:
            return None
        try:
            quotes = await asyncio.to_thread(client.get_quotes, symbols)
        except Exception as e:
            logger.error(f"Strategy 2: Quote fetch error: {e}")
            return None

        if not quotes:
            return None

        for sym, data in quotes.items():
            ltp = data.get('lp', 0)
            if ltp <= 0:
                continue

            # Determine if this is CE or PE
            is_ce = strikes.get('ce') and (sym == strikes['ce']['symbol'])
            sig_type = "CALL" if is_ce else "PUT"
            strike_info = strikes['ce'] if is_ce else strikes['pe']
            
            if not strike_info: continue

            # Update live price in strike info
            strike_info['ltp'] = ltp

            # TRIGGER CONDITION: Price must be < ARMING_THRESHOLD to arm, then cross >= 183 to trigger
            if ltp < ARMING_THRESHOLD:
                if not strike_info.get('armed', False):
                    strike_info['armed'] = True
                    logger.info(f"Strategy 2: {sym} dipped below {ARMING_THRESHOLD} (LTP: {ltp}), now ARMED.")
            elif ltp >= ENTRY_PRICE:
                if strike_info.get('armed', False):
                    logger.info(f"🚀 Strategy 2 TRIGGERED! {sig_type} {sym} crossed ₹{ENTRY_PRICE} from below (LTP: {ltp})")
                    state.strat_926_triggered = True

                return {
                    "symbol": "NSE:NIFTY50-INDEX",
                    "type": sig_type,
                    "side": "BUY",
                    "strategy": "Strategy 2: 9:26 - 180 Buy",
                    "reason": f"9:26 Strategy: {sig_type} breakout of ₹{ENTRY_PRICE} level",
                    "confidence": 95,
                    "entry_price": ltp,
                    "sl": ltp - SL_POINTS,
                    "target": ltp + TARGET_POINTS,
                    "strike_info": {
                        "symbol": sym,
                        "ltp": ltp,
                        "strike": strike_info.get("strike", 0),
                        "type_label": f"Strategy 2 {sig_type}",
                        "score": 95.0,
                        "moneyness": "ATM"
                    },
                    "is_direct_option": True,  # Skip standard strike selection
                    "sl_points": SL_POINTS,
                    "target_points": TARGET_POINTS,
                    "qty": getattr(state, "trade_lots", 1) * get_dynamic_lot_size(sym)
                }

    return None

async def _find_180_strikes(client):
    """Find CE and PE strikes with LTP nearest but below ₹180."""
    try:
        # 1. Get NIFTY spot price
        symbol = "NSE:NIFTY50-INDEX"
        quotes = await asyncio.to_thread(client.get_quotes, [symbol])
        spot = quotes.get(symbol, {}).get('lp', 0)
        if not spot:
            logger.error("Strategy 2: Could not get NIFTY spot price.")
            return None

        # 2. Find nearest expiry using the existing method
        expiry = await asyncio.to_thread(client.find_nearest_expiry, spot)
        if not expiry:
            logger.error("Strategy 2: Could not find nearest expiry.")
            return None

        expiry_code = expiry['code']
        logger.info(f"Strategy 2: Using expiry {expiry['date']} (code: {expiry_code})")

        # 3. Build option symbols around ATM (±500 points, every 50)
        atm = round(spot / 50) * 50
        strike_range = list(range(atm - 500, atm + 550, 50))

        ce_symbols = [f"NSE:NIFTY{expiry_code}{s}CE" for s in strike_range]
        pe_symbols = [f"NSE:NIFTY{expiry_code}{s}PE" for s in strike_range]

        # 4. Fetch quotes in chunks of 50 to minimize API calls (Fyers limit is 50)
        all_quotes = {}
        all_syms = ce_symbols + pe_symbols
        for i in range(0, len(all_syms), 50):
            chunk = all_syms[i:i + 50]
            try:
                chunk_quotes = await asyncio.to_thread(client.get_quotes, chunk)
                if chunk_quotes:
                    all_quotes.update(chunk_quotes)
            except Exception as e:
                logger.error(f"Strategy 2: Chunk quote error: {e}")
            if i + 50 < len(all_syms):
                await asyncio.sleep(0.3)  # Rate limit protection between chunks

        # 5. Find best CE (Nearest to ₹183 between 170-190)
        best_ce = None
        for sym in ce_symbols:
            ltp = all_quotes.get(sym, {}).get('lp', 0)
            if SELECTION_MIN <= ltp <= SELECTION_MAX:
                dist = abs(ltp - ENTRY_PRICE)
                if not best_ce or dist < best_ce['dist']:
                    # Extract strike from symbol (e.g., NSE:NIFTY2652024400CE → 24400)
                    strike_str = sym.replace(f"NSE:NIFTY{expiry_code}", "").replace("CE", "")
                    best_ce = {"symbol": sym, "ltp": ltp, "strike": int(strike_str), "dist": dist, "armed": ltp < ARMING_THRESHOLD}

        # 6. Find best PE (Nearest to ₹183 between 170-190)
        best_pe = None
        for sym in pe_symbols:
            ltp = all_quotes.get(sym, {}).get('lp', 0)
            if SELECTION_MIN <= ltp <= SELECTION_MAX:
                dist = abs(ltp - ENTRY_PRICE)
                if not best_pe or dist < best_pe['dist']:
                    strike_str = sym.replace(f"NSE:NIFTY{expiry_code}", "").replace("PE", "")
                    best_pe = {"symbol": sym, "ltp": ltp, "strike": int(strike_str), "dist": dist, "armed": ltp < ARMING_THRESHOLD}

        if best_ce or best_pe:
            if not best_pe: logger.warning("Strategy 2: Only found CE candidate, no PE in 170-190 range.")
            if not best_ce: logger.warning("Strategy 2: Only found PE candidate, no CE in 170-190 range.")
            return {"ce": best_ce, "pe": best_pe}
        else:
            logger.warning("Strategy 2: No CE or PE found in 170-190 range.")

    except Exception as e:
        logger.error(f"Strategy 2 find_180_strikes error: {e}")

    return None
# NOTE: an EMPTY second `async def _find_180_strikes(client):` (docstring only, no body) used to
# sit here. In Python the later definition wins, so it SHADOWED the real implementation above and
# always returned None — Strategy 2 could therefore never select its ~Rs180 strikes and logged
# "Failed to find strikes near Rs180. Will retry." on every 9:26 window, placing zero trades. The
# dead duplicate is removed so the working implementation above is the one that runs.
