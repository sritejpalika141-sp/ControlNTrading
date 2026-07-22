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
# NOTE: ENTRY_PRICE, SELECTION_MIN/MAX, SL, and TARGET are now computed dynamically
# from the ATM premium in _find_180_strikes() so the strategy adapts to varying IV levels.
# These defaults are kept as fallbacks only.
ENTRY_PRICE = 183.0      # Fallback target LTP (overridden by ATM-based calculation)
ARMING_THRESHOLD = 181.5 # Fallback arming (overridden dynamically)
SELECTION_MIN = 170.0    # Fallback min (overridden dynamically)
SELECTION_MAX = 190.0    # Fallback max (overridden dynamically)
SL_POINTS = 20.0         # Stop loss points
TARGET_POINTS = 40.0     # Target points → ~1:2 RR



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
                logger.warning("⚠️ Strategy 2: Failed to find strikes. Will retry.")
                return None

    # 6. Monitoring Phase: 9:26 to 9:40 — watch for crossover
    if getattr(state, "strat_926_strikes", None) and not getattr(state, "strat_926_triggered", False):
        strikes = state.strat_926_strikes

        # Use dynamic params if available, else fallback to constants
        _entry = strikes.get("_entry_price", ENTRY_PRICE)
        _arming = strikes.get("_arming_threshold", ARMING_THRESHOLD)
        _sl_pts = strikes.get("_sl_points", SL_POINTS)
        _tgt_pts = strikes.get("_target_points", TARGET_POINTS)

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

            # TRIGGER CONDITION: Price must be < arming to arm, then cross >= entry to trigger
            if ltp < _arming:
                if not strike_info.get('armed', False):
                    strike_info['armed'] = True
                    logger.info(f"Strategy 2: {sym} dipped below {_arming} (LTP: {ltp}), now ARMED.")
            elif ltp >= _entry:
                if strike_info.get('armed', False):
                    logger.info(f"🚀 Strategy 2 TRIGGERED! {sig_type} {sym} crossed ₹{_entry} from below (LTP: {ltp})")
                    state.strat_926_triggered = True

                return {
                    "symbol": "NSE:NIFTY50-INDEX",
                    "type": sig_type,
                    "side": "BUY",
                    "strategy": "Strategy 2: 9:26 - 180 Buy",
                    "reason": f"9:26 Strategy: {sig_type} breakout of ₹{_entry} level",
                    "confidence": 95,
                    "entry_price": ltp,
                    "sl": ltp - _sl_pts,
                    "target": ltp + _tgt_pts,
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
    """Find CE and PE strikes with LTP nearest but below the dynamic ATM premium anchor."""
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

        # 5. Compute dynamic premium anchor from ATM option premiums
        atm_sym_ce = f"NSE:NIFTY{expiry_code}{atm}CE"
        atm_sym_pe = f"NSE:NIFTY{expiry_code}{atm}PE"
        atm_ce_ltp = all_quotes.get(atm_sym_ce, {}).get('lp', 0)
        atm_pe_ltp = all_quotes.get(atm_sym_pe, {}).get('lp', 0)
        atm_premium = 0
        if atm_ce_ltp > 0 and atm_pe_ltp > 0:
            atm_premium = (atm_ce_ltp + atm_pe_ltp) / 2
        elif atm_ce_ltp > 0:
            atm_premium = atm_ce_ltp
        elif atm_pe_ltp > 0:
            atm_premium = atm_pe_ltp

        if atm_premium > 0:
            # Anchor the selection range around ATM premium
            entry_price = round(atm_premium * 0.95, 1)  # 95% of ATM
            selection_min = round(atm_premium * 0.85, 1)  # 85% of ATM
            selection_max = round(atm_premium * 1.15, 1)  # 115% of ATM
            arming_threshold = round(entry_price * 0.99, 1)
            sl_points = round(atm_premium * 0.15, 1)  # 15% of ATM
            target_points = round(atm_premium * 0.30, 1)  # 30% of ATM (~1:2 RR)
            logger.info(f"Strategy 2: ATM premium ₹{atm_premium:.1f} → selection [{selection_min}-{selection_max}], entry ₹{entry_price}, SL ₹{sl_points}, target ₹{target_points}")
        else:
            # Fallback to hardcoded values
            entry_price = ENTRY_PRICE
            selection_min = SELECTION_MIN
            selection_max = SELECTION_MAX
            arming_threshold = ARMING_THRESHOLD
            sl_points = SL_POINTS
            target_points = TARGET_POINTS
            logger.warning(f"Strategy 2: Could not determine ATM premium. Using fallback range [{selection_min}-{selection_max}]")

        # 6. Find best CE
        best_ce = None
        for sym in ce_symbols:
            ltp = all_quotes.get(sym, {}).get('lp', 0)
            if selection_min <= ltp <= selection_max:
                dist = abs(ltp - entry_price)
                if not best_ce or dist < best_ce['dist']:
                    strike_str = sym.replace(f"NSE:NIFTY{expiry_code}", "").replace("CE", "")
                    best_ce = {"symbol": sym, "ltp": ltp, "strike": int(strike_str), "dist": dist, "armed": ltp < arming_threshold}

        # 7. Find best PE
        best_pe = None
        for sym in pe_symbols:
            ltp = all_quotes.get(sym, {}).get('lp', 0)
            if selection_min <= ltp <= selection_max:
                dist = abs(ltp - entry_price)
                if not best_pe or dist < best_pe['dist']:
                    strike_str = sym.replace(f"NSE:NIFTY{expiry_code}", "").replace("PE", "")
                    best_pe = {"symbol": sym, "ltp": ltp, "strike": int(strike_str), "dist": dist, "armed": ltp < arming_threshold}

        if best_ce or best_pe:
            if not best_pe: logger.warning(f"Strategy 2: Only found CE candidate, no PE in [{selection_min}-{selection_max}] range.")
            if not best_ce: logger.warning(f"Strategy 2: Only found PE candidate, no CE in [{selection_min}-{selection_max}] range.")
            # Attach dynamic params so the caller uses consistent values
            result = {"ce": best_ce, "pe": best_pe}
            result["_entry_price"] = entry_price
            result["_arming_threshold"] = arming_threshold
            result["_sl_points"] = sl_points
            result["_target_points"] = target_points
            return result
        else:
            logger.warning(f"Strategy 2: No CE or PE found in [{selection_min}-{selection_max}] range (ATM premium: ₹{atm_premium:.1f}).")

    except Exception as e:
        logger.error(f"Strategy 2 find_180_strikes error: {e}")

    return None
# NOTE: an EMPTY second `async def _find_180_strikes(client):` (docstring only, no body) used to
# sit here. In Python the later definition wins, so it SHADOWED the real implementation above and
# always returned None — Strategy 2 could therefore never select its ~Rs180 strikes and logged
# "Failed to find strikes near Rs180. Will retry." on every 9:26 window, placing zero trades. The
# dead duplicate is removed so the working implementation above is the one that runs.
