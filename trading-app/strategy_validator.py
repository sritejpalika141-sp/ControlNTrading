"""
Evidence gate for auto-discovered strategies — "AI proposes, evidence disposes".

The strategy researcher can write a new engine/strategy_auto_*.py at any time. Nothing may
reach live money on the strength of an LLM's confidence. This module backtests a candidate
against REAL NIFTY history and returns a hard PASS/FAIL.

Why the bar is set where it is (learned the expensive way on this system):
  * Strategy 8 produced 1,973 signals and looked perfectly healthy — and lost 643 points at a
    44% win rate. "It reacts to the market and runs fine" is NOT evidence of profitability.
  * The live record is +Rs5,224 lifetime, but a single day contributed +Rs5,294 — remove it and
    the system is -Rs69. So a candidate carried by one outlier must FAIL.
  * An LLM shown price history will happily produce curve-fitted rules that explain the past and
    fail forward, so an implausibly high win rate is treated as a BUG signal, not a triumph.

Contract for a candidate file:
    async def evaluate_auto_<name>_strategy(client, state, symbol, candles_5m, candles_daily, vix)
    returns None, or a dict with at least a BUY/SELL-ish signal and ideally entry/stop.

Usage:
    python3 strategy_validator.py engine/strategy_auto_foo.py
    from strategy_validator import validate_strategy; validate_strategy(path)

SAFETY: validating a candidate EXECUTES LLM-written code in this process. It is never given a
real broker client (a stub is passed), so it cannot place orders — but it is not sandboxed.
Treat engine/strategy_auto_*.py as untrusted input.
"""
import asyncio
import bisect
import importlib.util
import inspect
import json
import os
import sys
from datetime import datetime

import pytz

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
IST = pytz.timezone("Asia/Kolkata")
DATA_FILE = os.path.join(BASE, "bt_data.json")

SESSION = ((9, 15), (15, 0))
SQUARE_OFF = (15, 14)

# ── the bar a candidate must clear ────────────────────────────────────────────────────
MIN_TRADES = 20          # below this, any win rate is noise
MIN_EXPECTANCY_PTS = 0.0  # must be net positive per trade
MIN_PROFIT_TO_DD = 1.0   # total profit must at least equal max drawdown
MAX_PLAUSIBLE_WIN = 90.0  # >90% win rate => almost certainly lookahead/bug, not edge
MAX_TRADES_PER_DAY = 3   # a candidate that fires constantly is overfitting noise


class _StubClient:
    """No real broker. A candidate can never place an order during validation."""
    def __init__(self):
        self.user_id = 1

    def __getattr__(self, _n):
        return lambda *a, **k: None


class _StubState:
    def __init__(self):
        self.active_strategies = []
        self.active_symbols = ["NSE:NIFTY50-INDEX"]
        self.trade_lots = 1
        self.paper_trading = True

    def can_trade(self, *a, **k):
        return True, "OK"

    def save(self):
        pass

    def __getattr__(self, _n):
        return None


def _ist(ts):
    return datetime.fromtimestamp(ts, IST)


def _load_candidate(path):
    """Import a candidate file and return its evaluate_auto_* coroutine."""
    spec = importlib.util.spec_from_file_location(f"cand_{os.path.basename(path)[:-3]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, fn in inspect.getmembers(mod, inspect.iscoroutinefunction):
        if name.startswith("evaluate_"):
            return fn, name
    raise ValueError("no evaluate_* coroutine found in candidate")


def _levels(sig, spot):
    """Normalise a candidate's signal dict into direction/entry/stop."""
    if not isinstance(sig, dict):
        return None
    raw = str(sig.get("signal") or sig.get("type") or sig.get("direction") or "").upper()
    if any(k in raw for k in ("BUY", "CALL", "LONG", "CE", "BULL")):
        is_bull = True
    elif any(k in raw for k in ("SELL", "PUT", "SHORT", "PE", "BEAR")):
        is_bull = False
    else:
        return None
    entry = sig.get("entry_price") or sig.get("entry") or spot
    stop = sig.get("stop_loss") or sig.get("sl_price") or sig.get("sl")
    if not stop:
        stop = entry - 30 if is_bull else entry + 30
    risk = abs(entry - stop)
    if risk < 1 or risk > entry * 0.1:      # implausible stop => unusable signal
        return None
    return {"bull": is_bull, "entry": entry, "stop": stop, "risk": risk}


async def _replay(fn, c5, c1):
    five_ts = [c["timestamp"] for c in c5]
    client, state = _StubClient(), _StubState()
    sigs, errors = [], 0
    per_day = {}

    for i in range(60, len(c1), 5):
        bar = c1[i]
        dt = _ist(bar["timestamp"])
        if not (SESSION[0] <= (dt.hour, dt.minute) <= SESSION[1]):
            continue
        day = dt.strftime("%Y-%m-%d")
        if per_day.get(day, 0) >= MAX_TRADES_PER_DAY:
            continue
        spot = bar["close"]
        hi = bisect.bisect_right(five_ts, bar["timestamp"] - 300)
        w5 = c5[max(0, hi - 300):hi]
        if len(w5) < 30:
            continue
        try:
            res = await fn(client, state, "NSE:NIFTY50-INDEX", w5, None, 13.0)
        except TypeError:
            try:
                res = await fn(client, state, "NSE:NIFTY50-INDEX", w5)
            except Exception:
                errors += 1
                continue
        except Exception:
            errors += 1
            continue
        lv = _levels(res, spot) if res else None
        if lv:
            lv.update({"i": i, "day": day})
            sigs.append(lv)
            per_day[day] = per_day.get(day, 0) + 1
    return sigs, errors


def _simulate(sigs, c1):
    out, busy = [], -1
    for s in sigs:
        if s["i"] <= busy:
            continue
        entry, stop, risk, bull = s["entry"], s["stop"], s["risk"], s["bull"]
        pnl = None
        for j in range(s["i"] + 1, len(c1)):
            b = c1[j]
            d = _ist(b["timestamp"])
            busy = j
            if d.strftime("%Y-%m-%d") != s["day"] or (d.hour, d.minute) >= SQUARE_OFF:
                pnl = (b["close"] - entry) if bull else (entry - b["close"])
                break
            fav = (b["high"] - entry) if bull else (entry - b["low"])
            if fav >= risk:                       # 1R target
                pnl = risk
                break
            if (bull and b["low"] <= stop) or (not bull and b["high"] >= stop):
                pnl = -risk
                break
        if pnl is not None:
            out.append(pnl)
    return out


def validate_strategy(path):
    """Backtest a candidate and return {verdict, metrics, reasons}."""
    result = {"file": os.path.basename(path), "verdict": "FAIL", "reasons": [], "metrics": {}}
    if not os.path.exists(DATA_FILE):
        result["reasons"].append("no bt_data.json history available")
        return result
    try:
        fn, fname = _load_candidate(path)
    except Exception as e:
        result["reasons"].append(f"could not load candidate: {e}")
        return result

    d = json.load(open(DATA_FILE))
    c5 = sorted(d["c5"], key=lambda x: x["timestamp"])
    c1 = sorted(d["c1"], key=lambda x: x["timestamp"])

    sigs, errors = asyncio.run(_replay(fn, c5, c1))
    pnls = _simulate(sigs, c1)
    n = len(pnls)
    days = len({_ist(b["timestamp"]).strftime("%Y-%m-%d") for b in c1})
    wins = sum(1 for p in pnls if p > 0)
    total = sum(pnls)
    exp = (total / n) if n else 0.0
    win_rate = (wins / n * 100) if n else 0.0
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    biggest = max(pnls) if pnls else 0.0

    result["metrics"] = {
        "function": fname, "days": days, "signals": len(sigs), "trades": n,
        "win_rate": round(win_rate, 1), "total_pts": round(total, 1),
        "expectancy_pts": round(exp, 2), "max_drawdown_pts": round(dd, 1),
        "errors": errors, "largest_single_win": round(biggest, 1),
    }

    r = result["reasons"]
    if n < MIN_TRADES:
        r.append(f"only {n} trades (need >= {MIN_TRADES}); any win rate is noise")
    if exp <= MIN_EXPECTANCY_PTS:
        r.append(f"expectancy {exp:+.2f} pts/trade is not positive")
    if dd < 0 and total < abs(dd) * MIN_PROFIT_TO_DD:
        r.append(f"profit {total:+.1f} does not exceed max drawdown {dd:.1f}")
    if win_rate > MAX_PLAUSIBLE_WIN:
        r.append(f"win rate {win_rate:.1f}% is implausible — treat as lookahead/bug, not edge")
    if n and biggest >= total > 0:
        r.append("entire profit rests on a single trade (outlier-carried, not an edge)")
    if errors > len(sigs):
        r.append(f"{errors} evaluation errors — candidate is unstable")

    result["verdict"] = "PASS" if not r else "FAIL"
    return result


def format_report(res):
    m = res["metrics"]
    icon = "✅" if res["verdict"] == "PASS" else "❌"
    lines = [f"{icon} <b>{res['file']}</b> — {res['verdict']}"]
    if m:
        lines.append(f"  trades {m['trades']} over {m['days']}d | win {m['win_rate']}% | "
                     f"exp {m['expectancy_pts']:+} pts | total {m['total_pts']:+} | "
                     f"maxDD {m['max_drawdown_pts']}")
    for reason in res["reasons"]:
        lines.append(f"  • {reason}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    res = validate_strategy(sys.argv[1])
    print(format_report(res))
    print(json.dumps(res["metrics"], indent=2))
    sys.exit(0 if res["verdict"] == "PASS" else 1)
