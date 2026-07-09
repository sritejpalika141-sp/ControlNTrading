"""
Backtest: Strategy 7 — Intraday Swing-Pivot (HH/HL/LL/LH) Breakout Strategy
Uses NIFTY 5-min data from yfinance.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time as dtime
import pytz

# ─── Configuration ───
STALE_ORDER_CANDLES = 3          # Cancel unfilled entry after 3 candles
COST_PER_TRADE_PTS = 1.0        # Round-trip cost placeholder (points on underlying)
ATR_PERIOD = 14
ATR_PIVOT_MULT = 0.5            # Minimum pivot size = 0.5 × ATR(14)
MAX_TRADES_PER_DAY = 2           # Cap trades per day
VERBOSE = False                  # Set True to print every pivot and trade


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


def backtest_swing_pivot(symbol="^NSEI"):
    print(f"\n{'='*70}")
    print(f"  Backtesting Strategy 7: Swing-Pivot Breakout for {symbol}")
    print(f"{'='*70}")

    ticker = yf.Ticker(symbol)
    df = ticker.history(period="59d", interval="5m")

    if df.empty:
        print(f"No data for {symbol}")
        return

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")

    # Pre-compute ATR for each row
    df["ATR"] = calc_atr(df, ATR_PERIOD)

    dates = pd.Series(df.index.date).unique()

    all_trades = []

    for day in dates:
        day_df = df[df.index.date == day].copy()
        if len(day_df) < 5:
            continue

        day_df = day_df.reset_index()
        day_df.rename(columns={"index": "Datetime", "Datetime": "Datetime"}, inplace=True)
        if "Datetime" not in day_df.columns:
            day_df.rename(columns={day_df.columns[0]: "Datetime"}, inplace=True)

        n = len(day_df)

        # ── Pivot detection ──
        # A pivot is confirmed on candle i+1 (the candle AFTER the extremum)
        confirmed_swing_highs = []  # list of (candle_index, price)
        confirmed_swing_lows = []

        # Labels: list of (candle_index, price, label)  label ∈ {HH, LH, HL, LL, baseline}
        labeled_highs = []
        labeled_lows = []

        # Market state tracking
        market_state = "UNCLEAR"  # UPTREND, DOWNTREND, TRANSITION, UNCLEAR

        # Trade tracking for this day
        pending_entry = None   # dict with trigger_price, sl_price, direction, candles_alive, breakout_candle_idx
        active_trade = None    # dict with entry_price, sl_price, direction, entry_idx
        last_trade_was_stopout = False
        skip_next_signal = False  # cooldown flag
        day_trade_count = 0        # max 2 trades per day
        awaiting_confirmation = None  # Double-close: {direction, breakout_level, candle_idx}

        for i in range(1, n - 1):
            curr_time = day_df.loc[i, "Datetime"]
            if hasattr(curr_time, "time"):
                ct = curr_time.time()
            else:
                ct = curr_time

            curr_h = day_df.loc[i, "High"]
            curr_l = day_df.loc[i, "Low"]
            curr_c = day_df.loc[i, "Close"]
            curr_o = day_df.loc[i, "Open"]
            prev_h = day_df.loc[i - 1, "High"]
            prev_l = day_df.loc[i - 1, "Low"]
            next_h = day_df.loc[i + 1, "High"]
            next_l = day_df.loc[i + 1, "Low"]
            atr_val = day_df.loc[i, "ATR"]
            min_pivot_size = ATR_PIVOT_MULT * atr_val if atr_val > 0 else 0

            # ── 3:15 PM mandatory exit ──
            if ct >= dtime(15, 15) and active_trade:
                exit_price = curr_c
                pnl = (exit_price - active_trade["entry_price"]) if active_trade["direction"] == "CE" else (active_trade["entry_price"] - exit_price)
                pnl -= COST_PER_TRADE_PTS
                all_trades.append({
                    "date": day,
                    "direction": active_trade["direction"],
                    "entry": active_trade["entry_price"],
                    "exit": exit_price,
                    "pnl": pnl,
                    "exit_reason": "EOD_SQUAREOFF"
                })
                active_trade = None
                last_trade_was_stopout = False
                continue

            # ── Check pending entry fill ──
            if pending_entry and not active_trade:
                pending_entry["candles_alive"] += 1

                # Stale order check
                if pending_entry["candles_alive"] > STALE_ORDER_CANDLES:
                    if VERBOSE:
                        print(f"  [{day}] Stale pending order cancelled after {STALE_ORDER_CANDLES} candles")
                    pending_entry = None
                else:
                    filled = False
                    if pending_entry["direction"] == "CE":
                        if curr_h >= pending_entry["trigger_price"]:
                            # Same-candle ambiguity: if SL also hit, worst-case = loss
                            if curr_l <= pending_entry["sl_price"]:
                                # Both entry and SL hit — worst case: loss
                                pnl = pending_entry["sl_price"] - pending_entry["trigger_price"] - COST_PER_TRADE_PTS
                                all_trades.append({
                                    "date": day,
                                    "direction": "CE",
                                    "entry": pending_entry["trigger_price"],
                                    "exit": pending_entry["sl_price"],
                                    "pnl": pnl,
                                    "exit_reason": "SAME_CANDLE_SL"
                                })
                                pending_entry = None
                                last_trade_was_stopout = True
                                skip_next_signal = True
                                day_trade_count += 1
                            else:
                                active_trade = {
                                    "entry_price": pending_entry["trigger_price"],
                                    "sl_price": pending_entry["sl_price"],
                                    "direction": "CE",
                                    "entry_idx": i
                                }
                                pending_entry = None
                                filled = True
                    elif pending_entry["direction"] == "PE":
                        if curr_l <= pending_entry["trigger_price"]:
                            if curr_h >= pending_entry["sl_price"]:
                                pnl = pending_entry["trigger_price"] - pending_entry["sl_price"] - COST_PER_TRADE_PTS
                                all_trades.append({
                                    "date": day,
                                    "direction": "PE",
                                    "entry": pending_entry["trigger_price"],
                                    "exit": pending_entry["sl_price"],
                                    "pnl": pnl,
                                    "exit_reason": "SAME_CANDLE_SL"
                                })
                                pending_entry = None
                                last_trade_was_stopout = True
                                skip_next_signal = True
                                day_trade_count += 1
                            else:
                                active_trade = {
                                    "entry_price": pending_entry["trigger_price"],
                                    "sl_price": pending_entry["sl_price"],
                                    "direction": "PE",
                                    "entry_idx": i
                                }
                                pending_entry = None
                                filled = True

            # ── Trailing SL for active trade (Structural: HL for CE, LH for PE) ──
            if active_trade and i > active_trade["entry_idx"]:

                if active_trade["direction"] == "CE":
                    # Trail using the latest confirmed HL pivot
                    latest_hl = None
                    for lbl in reversed(labeled_lows):
                        if lbl[2] in ("HL", "baseline"):
                            latest_hl = lbl[1]
                            break
                    if latest_hl and latest_hl > active_trade["sl_price"]:
                        active_trade["sl_price"] = latest_hl  # tighten only

                    if curr_l <= active_trade["sl_price"]:
                        exit_price = active_trade["sl_price"]
                        pnl = exit_price - active_trade["entry_price"] - COST_PER_TRADE_PTS
                        all_trades.append({
                            "date": day,
                            "direction": "CE",
                            "entry": active_trade["entry_price"],
                            "exit": exit_price,
                            "pnl": pnl,
                            "exit_reason": "TRAILING_SL"
                        })
                        active_trade = None
                        last_trade_was_stopout = True
                        skip_next_signal = True
                        day_trade_count += 1

                elif active_trade["direction"] == "PE":
                    # Trail using the latest confirmed LH pivot
                    latest_lh = None
                    for lbl in reversed(labeled_highs):
                        if lbl[2] in ("LH", "baseline"):
                            latest_lh = lbl[1]
                            break
                    if latest_lh and latest_lh < active_trade["sl_price"]:
                        active_trade["sl_price"] = latest_lh  # tighten only

                    if curr_h >= active_trade["sl_price"]:
                        exit_price = active_trade["sl_price"]
                        pnl = active_trade["entry_price"] - exit_price - COST_PER_TRADE_PTS
                        all_trades.append({
                            "date": day,
                            "direction": "PE",
                            "entry": active_trade["entry_price"],
                            "exit": exit_price,
                            "pnl": pnl,
                            "exit_reason": "TRAILING_SL"
                        })
                        active_trade = None
                        last_trade_was_stopout = True
                        skip_next_signal = True
                        day_trade_count += 1

            # ── Detect pivots (3-candle fractal, confirmed at candle i+1) ──
            # We are evaluating candle i as a potential pivot, confirmed by candle i+1
            is_swing_high = (curr_h > prev_h) and (curr_h > next_h)
            is_swing_low = (curr_l < prev_l) and (curr_l < next_l)

            if is_swing_high:
                # ATR filter: must differ from last confirmed swing high by >= 0.5x ATR
                if confirmed_swing_highs:
                    last_sh_price = confirmed_swing_highs[-1][1]
                    if abs(curr_h - last_sh_price) < min_pivot_size:
                        is_swing_high = False  # Too small, ignore

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

            # ── Update market state ──
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
                    # Early day — treat baseline + HL as tentative uptrend, baseline + LL as tentative downtrend
                    if latest_low_label == "HL" or latest_high_label == "HH":
                        market_state = "UPTREND"
                    elif latest_low_label == "LL" or latest_high_label == "LH":
                        market_state = "DOWNTREND"
                    else:
                        market_state = "UNCLEAR"
                else:
                    market_state = "UNCLEAR"

            # ── Transition zone resolution ──
            if market_state == "TRANSITION" and labeled_highs and labeled_lows:
                lh_price = labeled_highs[-1][1]
                hl_price = labeled_lows[-1][1]
                # Price closes above LH → becomes new HH
                if curr_c > lh_price:
                    labeled_highs[-1] = (labeled_highs[-1][0], labeled_highs[-1][1], "HH")
                    market_state = "UPTREND"
                # Price closes below HL → becomes new LL
                elif curr_c < hl_price:
                    labeled_lows[-1] = (labeled_lows[-1][0], labeled_lows[-1][1], "LL")
                    market_state = "DOWNTREND"

            # ── Double-Close Confirmation: check if awaiting 2nd close ──
            if awaiting_confirmation and not active_trade and not pending_entry:
                if awaiting_confirmation["direction"] == "CE":
                    if curr_c > awaiting_confirmation["breakout_level"]:
                        # 2nd candle also closed above → CONFIRMED! Create pending entry
                        trigger_price = curr_h
                        sl_price = day_df.loc[i - 1, "Low"]
                        pending_entry = {
                            "trigger_price": trigger_price,
                            "sl_price": sl_price,
                            "direction": "CE",
                            "candles_alive": 0,
                            "breakout_candle_idx": i
                        }
                        if VERBOSE:
                            print(f"  [{day}] Double-close CONFIRMED bullish at candle {i}: trigger={trigger_price:.1f}")
                        awaiting_confirmation = None
                        continue
                    else:
                        # 2nd candle failed to confirm → discard
                        if VERBOSE:
                            print(f"  [{day}] Double-close FAILED for bullish at candle {i}")
                        awaiting_confirmation = None

                elif awaiting_confirmation["direction"] == "PE":
                    if curr_c < awaiting_confirmation["breakout_level"]:
                        trigger_price = curr_l
                        sl_price = day_df.loc[i - 1, "High"]
                        pending_entry = {
                            "trigger_price": trigger_price,
                            "sl_price": sl_price,
                            "direction": "PE",
                            "candles_alive": 0,
                            "breakout_candle_idx": i
                        }
                        if VERBOSE:
                            print(f"  [{day}] Double-close CONFIRMED bearish at candle {i}: trigger={trigger_price:.1f}")
                        awaiting_confirmation = None
                        continue
                    else:
                        if VERBOSE:
                            print(f"  [{day}] Double-close FAILED for bearish at candle {i}")
                        awaiting_confirmation = None

            # ── Signal generation (only if no active trade, no pending entry, no awaiting confirmation) ──
            if active_trade or pending_entry or awaiting_confirmation:
                continue

            # Daily trade cap
            if day_trade_count >= MAX_TRADES_PER_DAY:
                continue

            if is_in_no_trade_time(ct):
                continue

            if market_state == "TRANSITION" or market_state == "UNCLEAR":
                continue

            # Breakout candle quality filter: body must be >= 50% of range
            candle_range = curr_h - curr_l
            candle_body = abs(curr_c - curr_o)
            is_strong_candle = (candle_body >= 0.5 * candle_range) if candle_range > 0 else False

            # ── Bullish breakout check ──
            if market_state == "UPTREND" and labeled_highs:
                latest_hh_price = None
                for lh in reversed(labeled_highs):
                    if lh[2] == "HH":
                        latest_hh_price = lh[1]
                        break
                if latest_hh_price and curr_c > latest_hh_price and is_strong_candle:
                    if skip_next_signal:
                        skip_next_signal = False
                        if VERBOSE:
                            print(f"  [{day}] Skipped bullish signal (cooldown) at candle {i}")
                        continue

                    # First close above HH → await 2nd confirmation
                    awaiting_confirmation = {
                        "direction": "CE",
                        "breakout_level": latest_hh_price,
                        "candle_idx": i
                    }
                    if VERBOSE:
                        print(f"  [{day}] Bullish breakout 1st close at candle {i}, awaiting 2nd close")

            # ── Bearish breakdown check ──
            elif market_state == "DOWNTREND" and labeled_lows:
                latest_ll_price = None
                for ll in reversed(labeled_lows):
                    if ll[2] == "LL":
                        latest_ll_price = ll[1]
                        break
                if latest_ll_price and curr_c < latest_ll_price and is_strong_candle:
                    if skip_next_signal:
                        skip_next_signal = False
                        if VERBOSE:
                            print(f"  [{day}] Skipped bearish signal (cooldown) at candle {i}")
                        continue

                    awaiting_confirmation = {
                        "direction": "PE",
                        "breakout_level": latest_ll_price,
                        "candle_idx": i
                    }
                    if VERBOSE:
                        print(f"  [{day}] Bearish breakdown 1st close at candle {i}, awaiting 2nd close")

        # ── End of day: close any remaining active trade ──
        if active_trade:
            last_close = day_df.iloc[-1]["Close"]
            if active_trade["direction"] == "CE":
                pnl = last_close - active_trade["entry_price"] - COST_PER_TRADE_PTS
            else:
                pnl = active_trade["entry_price"] - last_close - COST_PER_TRADE_PTS
            all_trades.append({
                "date": day,
                "direction": active_trade["direction"],
                "entry": active_trade["entry_price"],
                "exit": last_close,
                "pnl": pnl,
                "exit_reason": "EOD_SQUAREOFF"
            })
            active_trade = None

    # ═══════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════
    if not all_trades:
        print("\nNo trades were generated.")
        return

    trades_df = pd.DataFrame(all_trades)
    total = len(trades_df)
    wins = len(trades_df[trades_df["pnl"] > 0])
    losses = len(trades_df[trades_df["pnl"] <= 0])
    win_rate = (wins / total * 100) if total > 0 else 0
    net_pnl = trades_df["pnl"].sum()
    avg_win = trades_df[trades_df["pnl"] > 0]["pnl"].mean() if wins > 0 else 0
    avg_loss = trades_df[trades_df["pnl"] <= 0]["pnl"].mean() if losses > 0 else 0
    max_win = trades_df["pnl"].max()
    max_loss = trades_df["pnl"].min()

    # Profit factor
    gross_profit = trades_df[trades_df["pnl"] > 0]["pnl"].sum()
    gross_loss = abs(trades_df[trades_df["pnl"] <= 0]["pnl"].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # Max drawdown
    cumulative = trades_df["pnl"].cumsum()
    peak = cumulative.cummax()
    drawdown = cumulative - peak
    max_dd = drawdown.min()

    # Exit reason breakdown
    exit_reasons = trades_df["exit_reason"].value_counts()

    # Direction breakdown
    ce_trades = trades_df[trades_df["direction"] == "CE"]
    pe_trades = trades_df[trades_df["direction"] == "PE"]

    ce_wins = len(ce_trades[ce_trades["pnl"] > 0])
    pe_wins = len(pe_trades[pe_trades["pnl"] > 0])
    ce_total = len(ce_trades)
    pe_total = len(pe_trades)

    print(f"\n{'─'*50}")
    print(f"  STRATEGY 7: SWING-PIVOT BREAKOUT — RESULTS")
    print(f"{'─'*50}")
    print(f"  Period         : ~60 trading days")
    print(f"  Total Trades   : {total}")
    print(f"  Wins           : {wins}")
    print(f"  Losses         : {losses}")
    print(f"  Win Rate       : {win_rate:.1f}%")
    print(f"{'─'*50}")
    print(f"  Net PnL (Pts)  : {net_pnl:+.1f}")
    print(f"  Avg Win (Pts)  : {avg_win:+.1f}")
    print(f"  Avg Loss (Pts) : {avg_loss:+.1f}")
    print(f"  Max Win (Pts)  : {max_win:+.1f}")
    print(f"  Max Loss (Pts) : {max_loss:+.1f}")
    print(f"  Profit Factor  : {profit_factor:.2f}")
    print(f"  Max Drawdown   : {max_dd:+.1f}")
    print(f"{'─'*50}")
    print(f"  CE Trades      : {ce_total}  (Wins: {ce_wins}, WR: {ce_wins/ce_total*100:.0f}%)" if ce_total > 0 else "  CE Trades      : 0")
    print(f"  PE Trades      : {pe_total}  (Wins: {pe_wins}, WR: {pe_wins/pe_total*100:.0f}%)" if pe_total > 0 else "  PE Trades      : 0")
    print(f"{'─'*50}")
    print(f"  Exit Breakdown :")
    for reason, count in exit_reasons.items():
        print(f"    {reason:20s} : {count}")
    print(f"{'─'*50}")

    # Print last 10 trades
    print(f"\n  Last 10 Trades:")
    for _, t in trades_df.tail(10).iterrows():
        emoji = "✅" if t["pnl"] > 0 else "❌"
        print(f"    {emoji} {t['date']} | {t['direction']} | Entry: {t['entry']:.1f} → Exit: {t['exit']:.1f} | PnL: {t['pnl']:+.1f} | {t['exit_reason']}")


if __name__ == "__main__":
    backtest_swing_pivot("^NSEI")
