import pandas as pd
import numpy as np
from datetime import datetime, time as dtime
import pytz
from state import logger


# ─── Configuration ───
STALE_ORDER_CANDLES = 3          # Cancel unfilled entry after 3 candles
ATR_PERIOD = 14
ATR_PIVOT_MULT = 0.5            # Minimum pivot size = 0.5 × ATR(14)
MAX_TRADES_PER_DAY = 2           # Cap trades per day

def calc_atr(candles_df, period=14):
    """Calculate ATR on a DataFrame with High, Low, Close columns."""
    h = candles_df["High"]
    l = candles_df["Low"]
    c = candles_df["Close"]
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()

def is_in_no_trade_time(t):
    """Block entries during 9:15-9:30 AM and 3:00-3:15 PM."""
    if dtime(9, 15) <= t < dtime(9, 30):
        return True
    if dtime(15, 0) <= t <= dtime(15, 15):
        return True
    return False

async def evaluate_swing_pivot_strategy(spot, candles_5m, analysis, active_symbols, client, state, is_commodity=False):
    """
    Evaluates Strategy 7: Intraday Swing-Pivot Breakout with optimizations:
    - Double Close Confirmation
    - Candle Quality Filter (body >= 50% range)
    - Structural Trailing SL (HL for CE, LH for PE)
    - Max 2 trades per day
    """
    if len(candles_5m) < 15:
        return False, None

    import state as global_state
    # CHOPPY_SIDEWAYS no longer hard-blocks here — the high-confidence override in
    # risk_orchestrator.propose_trade allows this validated Swing-Pivot signal through in choppy
    # markets; only sub-85 signals are skipped.

    # Enforce daily trade cap
    if getattr(state, "strat_7_trades_today", 0) >= MAX_TRADES_PER_DAY:
        return False, None

    # Load 5m candles into DataFrame for vectorized calculation of ATR and pivots
    df = pd.DataFrame(candles_5m)
    df['Datetime'] = pd.to_datetime(df['timestamp'])
    
    # Filter to today's candles only to build the intraday structure
    tz = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(tz)
    today_date = now_ist.date()
    df['date'] = df['Datetime'].dt.date
    day_df = df[df['date'] == today_date].copy()
    
    if len(day_df) < 5:
        return False, None

    day_df = day_df.reset_index(drop=True)
    day_df.rename(columns={'high': 'High', 'low': 'Low', 'close': 'Close', 'open': 'Open'}, inplace=True)
    
    # Calculate ATR (can use historical data appended for accurate rolling, but for simplicity we calculate on today if needed, or better, calculate on full df then slice)
    df.rename(columns={'high': 'High', 'low': 'Low', 'close': 'Close', 'open': 'Open'}, inplace=True)
    df["ATR"] = calc_atr(df, ATR_PERIOD)
    
    day_df = df[df['date'] == today_date].copy().reset_index(drop=True)
    n = len(day_df)

    confirmed_swing_highs = []  
    confirmed_swing_lows = []
    labeled_highs = []
    labeled_lows = []
    market_state = "UNCLEAR"

    # Replay today's candles up to the current one to build the state
    for i in range(1, n - 1):
        curr_h = day_df.loc[i, "High"]
        curr_l = day_df.loc[i, "Low"]
        curr_c = day_df.loc[i, "Close"]
        prev_h = day_df.loc[i - 1, "High"]
        prev_l = day_df.loc[i - 1, "Low"]
        next_h = day_df.loc[i + 1, "High"]
        next_l = day_df.loc[i + 1, "Low"]
        atr_val = day_df.loc[i, "ATR"]
        min_pivot_size = ATR_PIVOT_MULT * atr_val if atr_val > 0 else 0

        is_swing_high = (curr_h > prev_h) and (curr_h > next_h)
        is_swing_low = (curr_l < prev_l) and (curr_l < next_l)

        if is_swing_high:
            if confirmed_swing_highs:
                last_sh_price = confirmed_swing_highs[-1][1]
                if abs(curr_h - last_sh_price) < min_pivot_size:
                    is_swing_high = False 

        if is_swing_low:
            if confirmed_swing_lows:
                last_sl_price = confirmed_swing_lows[-1][1]
                if abs(curr_l - last_sl_price) < min_pivot_size:
                    is_swing_low = False

        if is_swing_high:
            if not confirmed_swing_highs:
                labeled_highs.append((i, curr_h, "baseline"))
            else:
                prev_sh = confirmed_swing_highs[-1][1]
                label = "HH" if curr_h > prev_sh else "LH"
                labeled_highs.append((i, curr_h, label))
            confirmed_swing_highs.append((i, curr_h))

        if is_swing_low:
            if not confirmed_swing_lows:
                labeled_lows.append((i, curr_l, "baseline"))
            else:
                prev_sl = confirmed_swing_lows[-1][1]
                label = "HL" if curr_l > prev_sl else "LL"
                labeled_lows.append((i, curr_l, label))
            confirmed_swing_lows.append((i, curr_l))

        if labeled_highs and labeled_lows:
            latest_high_label = labeled_highs[-1][2]
            latest_low_label = labeled_lows[-1][2]

            if latest_low_label == "HL" and latest_high_label == "HH":
                market_state = "UPTREND"
            elif latest_low_label == "LL" and latest_high_label == "LH":
                market_state = "DOWNTREND"
            elif latest_low_label == "HL" and latest_high_label == "LH":
                market_state = "TRANSITION"
            elif latest_low_label in ("baseline",) or latest_high_label in ("baseline",):
                if latest_low_label == "HL" or latest_high_label == "HH":
                    market_state = "UPTREND"
                elif latest_low_label == "LL" or latest_high_label == "LH":
                    market_state = "DOWNTREND"
                else:
                    market_state = "UNCLEAR"
            else:
                market_state = "UNCLEAR"

        if market_state == "TRANSITION" and labeled_highs and labeled_lows:
            lh_price = labeled_highs[-1][1]
            hl_price = labeled_lows[-1][1]
            if curr_c > lh_price:
                labeled_highs[-1] = (labeled_highs[-1][0], labeled_highs[-1][1], "HH")
                market_state = "UPTREND"
            elif curr_c < hl_price:
                labeled_lows[-1] = (labeled_lows[-1][0], labeled_lows[-1][1], "LL")
                market_state = "DOWNTREND"

    # Now evaluate the current fully formed candle (which is the last one in day_df if the latest tick hasn't closed it, but we look at n-1, which is the last closed candle)
    # The live system provides candles. The last candle might be incomplete, so we look at the last *closed* candle, which is index n-2 if n-1 is currently forming.
    # Actually, the automation loop ensures candles_5m are the closed ones. Let's assume day_df.iloc[-1] is the latest closed candle.
    latest_candle = day_df.iloc[-1]
    curr_c = latest_candle["Close"]
    curr_h = latest_candle["High"]
    curr_l = latest_candle["Low"]
    curr_o = latest_candle["Open"]
    
    ct = latest_candle["Datetime"].time()
    
    # The 9:15-9:30 / 15:00-15:15 no-trade windows are NSE-clock specific. For MCX/CDS commodity
    # symbols they are meaningless (MCX trades to ~23:30), so skip them and run the full session.
    if not is_commodity and is_in_no_trade_time(ct):
        return False, None

    if market_state == "TRANSITION" or market_state == "UNCLEAR":
        return False, None
        
    # Check if we are awaiting double close confirmation
    awaiting_conf = getattr(state, "strat_7_awaiting_confirmation", None)
    if awaiting_conf:
        # Check if the current closed candle confirms it
        if awaiting_conf["direction"] == "CE":
            if curr_c > awaiting_conf["breakout_level"]:
                logger.info(f"Strategy 7: Bullish Double-Close CONFIRMED at {curr_h}")
                state.strat_7_awaiting_confirmation = None
                return True, {
                    "strategy": "Strategy 7: Swing-Pivot Breakout",
                    "type": "PENDING_CE",
                    "trigger_price": curr_h,
                    "sl_price": day_df.iloc[-2]["Low"], # SL is low of previous candle
                    "candles_alive": 0,
                    "latest_hl": labeled_lows[-1][1] if labeled_lows else None # For trailing
                }
            else:
                logger.info("Strategy 7: Bullish Double-Close FAILED to confirm. Resetting.")
                state.strat_7_awaiting_confirmation = None
                return False, None
                
        elif awaiting_conf["direction"] == "PE":
            if curr_c < awaiting_conf["breakout_level"]:
                logger.info(f"Strategy 7: Bearish Double-Close CONFIRMED at {curr_l}")
                state.strat_7_awaiting_confirmation = None
                return True, {
                    "strategy": "Strategy 7: Swing-Pivot Breakout",
                    "type": "PENDING_PE",
                    "trigger_price": curr_l,
                    "sl_price": day_df.iloc[-2]["High"],
                    "candles_alive": 0,
                    "latest_lh": labeled_highs[-1][1] if labeled_highs else None
                }
            else:
                logger.info("Strategy 7: Bearish Double-Close FAILED to confirm. Resetting.")
                state.strat_7_awaiting_confirmation = None
                return False, None

    # Breakout candle quality filter: body must be >= 50% of range
    candle_range = curr_h - curr_l
    candle_body = abs(curr_c - curr_o)
    is_strong_candle = (candle_body >= 0.5 * candle_range) if candle_range > 0 else False

    if market_state == "UPTREND" and labeled_highs:
        latest_hh_price = None
        for lh in reversed(labeled_highs):
            if lh[2] == "HH":
                latest_hh_price = lh[1]
                break
        if latest_hh_price and curr_c > latest_hh_price and is_strong_candle:
            if getattr(state, "strat_7_was_stopout", False):
                logger.info("Strategy 7: Skipped bullish signal due to cooldown.")
                state.strat_7_was_stopout = False # Reset cooldown
                return False, None
            
            logger.info(f"Strategy 7: 1st Bullish Breakout above {latest_hh_price}, awaiting confirmation.")
            state.strat_7_awaiting_confirmation = {
                "direction": "CE",
                "breakout_level": latest_hh_price
            }
            return False, None

    elif market_state == "DOWNTREND" and labeled_lows:
        latest_ll_price = None
        for ll in reversed(labeled_lows):
            if ll[2] == "LL":
                latest_ll_price = ll[1]
                break
        if latest_ll_price and curr_c < latest_ll_price and is_strong_candle:
            if getattr(state, "strat_7_was_stopout", False):
                logger.info("Strategy 7: Skipped bearish signal due to cooldown.")
                state.strat_7_was_stopout = False
                return False, None
                
            logger.info(f"Strategy 7: 1st Bearish Breakdown below {latest_ll_price}, awaiting confirmation.")
            state.strat_7_awaiting_confirmation = {
                "direction": "PE",
                "breakout_level": latest_ll_price
            }
            return False, None

    return False, None

def get_latest_pivots_for_trailing(candles_5m):
    """
    Helper function to recalculate the latest HL or LH for trailing stops.
    Called periodically by auto_trader.
    """
    df = pd.DataFrame(candles_5m)
    df['Datetime'] = pd.to_datetime(df['timestamp'])
    tz = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(tz)
    df['date'] = df['Datetime'].dt.date
    day_df = df[df['date'] == now_ist.date()].copy()
    if len(day_df) < 5:
        return None, None
        
    df.rename(columns={'high': 'High', 'low': 'Low', 'close': 'Close', 'open': 'Open'}, inplace=True)
    df["ATR"] = calc_atr(df, ATR_PERIOD)
    day_df = df[df['date'] == now_ist.date()].copy().reset_index(drop=True)
    n = len(day_df)

    confirmed_swing_highs = []  
    confirmed_swing_lows = []
    labeled_highs = []
    labeled_lows = []

    for i in range(1, n - 1):
        curr_h = day_df.loc[i, "High"]
        curr_l = day_df.loc[i, "Low"]
        prev_h = day_df.loc[i - 1, "High"]
        prev_l = day_df.loc[i - 1, "Low"]
        next_h = day_df.loc[i + 1, "High"]
        next_l = day_df.loc[i + 1, "Low"]
        atr_val = day_df.loc[i, "ATR"]
        min_pivot_size = ATR_PIVOT_MULT * atr_val if atr_val > 0 else 0

        is_swing_high = (curr_h > prev_h) and (curr_h > next_h)
        is_swing_low = (curr_l < prev_l) and (curr_l < next_l)

        if is_swing_high:
            if confirmed_swing_highs:
                if abs(curr_h - confirmed_swing_highs[-1][1]) < min_pivot_size:
                    is_swing_high = False 
        if is_swing_low:
            if confirmed_swing_lows:
                if abs(curr_l - confirmed_swing_lows[-1][1]) < min_pivot_size:
                    is_swing_low = False

        if is_swing_high:
            if not confirmed_swing_highs:
                labeled_highs.append((i, curr_h, "baseline"))
            else:
                label = "HH" if curr_h > confirmed_swing_highs[-1][1] else "LH"
                labeled_highs.append((i, curr_h, label))
            confirmed_swing_highs.append((i, curr_h))

        if is_swing_low:
            if not confirmed_swing_lows:
                labeled_lows.append((i, curr_l, "baseline"))
            else:
                label = "HL" if curr_l > confirmed_swing_lows[-1][1] else "LL"
                labeled_lows.append((i, curr_l, label))
            confirmed_swing_lows.append((i, curr_l))

    latest_hl = None
    if labeled_lows:
        for lbl in reversed(labeled_lows):
            if lbl[2] in ("HL", "baseline"):
                latest_hl = lbl[1]
                break

    latest_lh = None
    if labeled_highs:
        for lbl in reversed(labeled_highs):
            if lbl[2] in ("LH", "baseline"):
                latest_lh = lbl[1]
                break
                
    return latest_hl, latest_lh
