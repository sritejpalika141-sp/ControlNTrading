"""
Walk-forward backtest + A/B harness for Strategy 1 (OB + FVG), using the REAL engine.

Imports the SAME functions live uses (engine/order_blocks.py, engine/fvg.py,
engine/signals.py:detect_retest_and_rejection) so zones, the liquidity-sweep trigger
and the rejection rule are byte-identical to production. Nothing is reimplemented.

Replay model (mirrors live):
  * zones rebuilt from a rolling 4-DAY window of COMPLETED 5m candles (live: days_back=4)
  * sweep/rejection evaluated on 1m candles every minute (live: days_back=1)
  * 09:15-15:00 IST only; square-off at 15:14

NO LOOKAHEAD: signals are collected in one chronological pass. Variant rules
(quality filter, per-day cap) are applied FORWARD-ONLY in post-processing, so every
variant is implementable live. "Best signal of the day" is deliberately NOT tested —
it would require knowing the future.

MEASURES spot directional edge in points. Option premium P&L (delta/theta/IV) is NOT
simulated — historical option chains aren't available.

Usage:  .venv/bin/python3 backtest_ob_fvg.py [--cached]
"""
import os
import sys
import json
import bisect
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
IST = pytz.timezone("Asia/Kolkata")
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "bt_data.json")

SYMBOL = "NSE:NIFTY50-INDEX"
WINDOW_5M_DAYS = 4
SESSION_START, SESSION_END = (9, 15), (15, 0)
SQUARE_OFF = (15, 14)


def fetch_data():
    for line in open(os.path.join(BASE, ".env")):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        from fyers_client import FyersClient
        c = FyersClient(user_id=1)
        c5 = c.get_historical(SYMBOL, "5", days_back=100)
        c1 = c.get_historical(SYMBOL, "1", days_back=100)
    if not c5 or not c1:
        raise SystemExit("No historical data (auth/rate-limit?).")
    json.dump({"c5": c5, "c1": c1}, open(DATA_FILE, "w"))
    return c5, c1


def load_data(cached):
    if cached and os.path.exists(DATA_FILE):
        d = json.load(open(DATA_FILE))
        return d["c5"], d["c1"]
    return fetch_data()


def ist(ts):
    return datetime.fromtimestamp(ts, IST)


# ───────────── one expensive chronological pass: collect ALL signals ─────────────
def collect_signals(c5, c1):
    from engine.order_blocks import get_active_order_blocks
    from engine.fvg import get_active_fvg, find_ob_fvg_confluence
    from engine.signals import detect_retest_and_rejection

    c5 = sorted(c5, key=lambda x: x["timestamp"])
    c1 = sorted(c1, key=lambda x: x["timestamp"])
    five_ts = [c["timestamp"] for c in c5]
    window = WINDOW_5M_DAYS * 24 * 3600

    out, last_bucket, setups = [], None, []
    for i in range(3, len(c1)):
        bar = c1[i]
        ts = bar["timestamp"]
        dt = ist(ts)
        if not (SESSION_START <= (dt.hour, dt.minute) <= SESSION_END):
            continue
        spot = bar["close"]

        bucket = ts - (ts % 300)
        if bucket != last_bucket:
            last_bucket = bucket
            hi = bisect.bisect_right(five_ts, bucket - 300)   # completed candles only
            lo = bisect.bisect_left(five_ts, bucket - window)
            w5 = c5[lo:hi]
            if len(w5) < 20:
                setups = []
                continue
            obs = get_active_order_blocks(w5, spot)
            fvgs = get_active_fvg(w5, spot)
            confs = find_ob_fvg_confluence(obs, fvgs)
            setups = (
                [{"dir": c["direction"], "top": c["zone_top"], "bottom": c["zone_bottom"],
                  "type": "confluence", "score": c.get("confluence_score", 0)} for c in confs]
                + [{"dir": o["direction"], "top": o["top"], "bottom": o["bottom"],
                    "type": "ob", "score": o.get("impulse_strength", 0) * 20} for o in obs]
                + [{"dir": f["direction"], "top": f["top"], "bottom": f["bottom"],
                    "type": "fvg", "score": f.get("gap_pct", 0) * 500} for f in fvgs]
            )
        if not setups:
            continue

        recent = c1[max(0, i - 400):i + 1]
        for s in setups:
            st = detect_retest_and_rejection(recent, s, s["dir"])
            if not (st["retested"] and st["rejected"]):
                continue
            is_bull = s["dir"] == "BULLISH"
            sl = (s["bottom"] - 2.0) if is_bull else (s["top"] + 2.0)
            risk = abs(spot - sl)
            if risk < 1:
                continue
            out.append({"i": i, "ts": ts, "day": dt.strftime("%Y-%m-%d"), "dir": s["dir"],
                        "type": s["type"], "score": s["score"], "entry": spot,
                        "sl": sl, "risk": risk})
            break   # at most one signal per minute (live takes the first match)
    return out


# ───────────── forward-only variant selection (no lookahead) ─────────────
def select(signals, types=None, max_per_day=1, stop_mult=1.0, exits=None):
    """Chronological: take the first N signals per day matching the quality filter.
    Skips signals that overlap an open trade (uses the exit index from `exits`)."""
    chosen, per_day, busy_until = [], {}, -1
    for s in signals:
        if types and s["type"] not in types:
            continue
        if s["i"] <= busy_until:
            continue
        if per_day.get(s["day"], 0) >= max_per_day:
            continue
        t = dict(s)
        if stop_mult != 1.0:
            is_bull = t["dir"] == "BULLISH"
            t["risk"] = t["risk"] * stop_mult
            t["sl"] = t["entry"] - t["risk"] if is_bull else t["entry"] + t["risk"]
        chosen.append(t)
        per_day[t["day"]] = per_day.get(t["day"], 0) + 1
        if exits is not None:
            busy_until = exits.get(t["i"], t["i"])
    return chosen


# ───────────── exit policies ─────────────
def simulate(signals, c1, policy="stop_eod"):
    """policy: stop_eod | fixed_1r | fixed_2r | partial_trail
    partial_trail: book 50% at +1R, move stop to breakeven, trail remainder by 1R."""
    results, exit_idx = [], {}
    for sg in signals:
        is_bull = sg["dir"] == "BULLISH"
        entry, risk = sg["entry"], sg["risk"]
        sl = sg["sl"]
        booked, half_done, stop = 0.0, False, sl
        peak = 0.0
        pnl_r, j_exit = None, sg["i"]

        for j in range(sg["i"] + 1, len(c1)):
            b = c1[j]
            d = ist(b["timestamp"])
            j_exit = j
            if d.strftime("%Y-%m-%d") != sg["day"] or (d.hour, d.minute) >= SQUARE_OFF:
                close_r = ((b["close"] - entry) if is_bull else (entry - b["close"])) / risk
                pnl_r = booked + (0.5 if half_done else 1.0) * close_r
                break
            fav = ((b["high"] - entry) if is_bull else (entry - b["low"])) / risk
            peak = max(peak, fav)

            if policy in ("fixed_1r", "fixed_2r"):
                tgt = 1.0 if policy == "fixed_1r" else 2.0
                if fav >= tgt:
                    pnl_r = tgt
                    break
                if (is_bull and b["low"] <= sl) or (not is_bull and b["high"] >= sl):
                    pnl_r = -1.0
                    break
            elif policy == "trail_be":
                # No partial booking: at +1R move stop to breakeven, then trail by 1R. Exits 100%
                # at the trailing stop. Avoids the live risk of a partial fill desyncing SL qty.
                if fav >= 1.0:
                    stop = entry if not half_done else stop
                    half_done = True
                    trail = (entry + (peak - 1.0) * risk) if is_bull else (entry - (peak - 1.0) * risk)
                    stop = max(stop, trail) if is_bull else min(stop, trail)
                hit = (is_bull and b["low"] <= stop) or (not is_bull and b["high"] >= stop)
                if hit:
                    pnl_r = ((stop - entry) if is_bull else (entry - stop)) / risk
                    break
            elif policy == "partial_trail":
                if not half_done and fav >= 1.0:
                    booked, half_done, stop = 0.5, True, entry     # book half, BE stop
                if half_done:
                    trail = (entry + (peak - 1.0) * risk) if is_bull else (entry - (peak - 1.0) * risk)
                    stop = max(stop, trail) if is_bull else min(stop, trail)
                hit = (is_bull and b["low"] <= stop) or (not is_bull and b["high"] >= stop)
                if hit:
                    rem_r = ((stop - entry) if is_bull else (entry - stop)) / risk
                    pnl_r = booked + (0.5 if half_done else 1.0) * rem_r
                    break
            else:  # stop_eod
                if (is_bull and b["low"] <= sl) or (not is_bull and b["high"] >= sl):
                    pnl_r = -1.0
                    break
        if pnl_r is None:
            pnl_r = 0.0
        exit_idx[sg["i"]] = j_exit
        results.append({"r": pnl_r, "pts": pnl_r * risk, "risk": risk})
    return results, exit_idx


def stats(name, res):
    if not res:
        return f"{name:<34} no trades"
    n = len(res)
    w = [x for x in res if x["r"] > 0]
    l = [x for x in res if x["r"] <= 0]
    tot_r = sum(x["r"] for x in res)
    tot_p = sum(x["pts"] for x in res)
    eq = peak = dd = 0.0
    for x in res:
        eq += x["pts"]
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return (f"{name:<34} {n:>4}  {len(w)/n*100:>5.1f}%  {tot_r/n:>+6.2f}R  "
            f"{tot_p:>+8.1f}  {dd:>+8.1f}")


if __name__ == "__main__":
    c5, c1 = load_data("--cached" in sys.argv)
    print(f"Loaded {len(c5)} 5m / {len(c1)} 1m candles.")
    raw = collect_signals(c5, c1)
    days = len({ist(b['timestamp']).strftime('%Y-%m-%d') for b in c1})
    bytype = {}
    for s in raw:
        bytype[s["type"]] = bytype.get(s["type"], 0) + 1
    print(f"\nRaw signals (uncapped, unfiltered): {len(raw)} over {days} trading days  {bytype}")

    print("\n" + "=" * 78)
    print(f"{'VARIANT':<34} {'N':>4}  {'WIN%':>6}  {'EXP/R':>7}  {'TOT pts':>8}  {'MaxDD':>8}")
    print("=" * 78)

    variants = [
        ("A baseline (1/day, stop->EOD)",      dict(types=None, max_per_day=1, stop_mult=1.0), "stop_eod"),
        ("B baseline + fixed 1R",              dict(types=None, max_per_day=1, stop_mult=1.0), "fixed_1r"),
        ("C EXIT: partial@1R + trail",         dict(types=None, max_per_day=1, stop_mult=1.0), "partial_trail"),
        ("D STOP x1.5 (stop->EOD)",            dict(types=None, max_per_day=1, stop_mult=1.5), "stop_eod"),
        ("E STOP x2.0 (stop->EOD)",            dict(types=None, max_per_day=1, stop_mult=2.0), "stop_eod"),
        ("F QUALITY: confluence only",         dict(types={"confluence"}, max_per_day=1, stop_mult=1.0), "stop_eod"),
        ("G CAP: 3/day (stop->EOD)",           dict(types=None, max_per_day=3, stop_mult=1.0), "stop_eod"),
        ("H C+D: partial/trail + stop x1.5",   dict(types=None, max_per_day=1, stop_mult=1.5), "partial_trail"),
        ("I C+F: partial/trail + confluence",  dict(types={"confluence"}, max_per_day=1, stop_mult=1.0), "partial_trail"),
        ("J C+G: partial/trail + 3/day",       dict(types=None, max_per_day=3, stop_mult=1.0), "partial_trail"),
        ("K confluence + BE-trail (NO partial)", dict(types={"confluence"}, max_per_day=1, stop_mult=1.0), "trail_be"),
        ("L confluence + BE-trail, 2/day",     dict(types={"confluence"}, max_per_day=2, stop_mult=1.0), "trail_be"),
    ]
    for name, sel, pol in variants:
        picked = select(raw, **sel)
        res, ex = simulate(picked, c1, pol)
        picked = select(raw, exits=ex, **sel)     # re-select honouring non-overlap
        res, _ = simulate(picked, c1, pol)
        print(stats(name, res))
    print("=" * 78)
    print("EXP/R = expectancy in R per trade (R = initial stop distance).")
    print("Spot-direction only — option premium P&L NOT simulated. No lookahead used.")
