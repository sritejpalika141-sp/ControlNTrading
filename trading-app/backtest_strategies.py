"""
Multi-strategy walk-forward backtest (gap #2) using the REAL strategy engines.

Calls the SAME evaluate_* coroutines the live auto-trader calls, replaying NIFTY history
minute by minute. Nothing is reimplemented.

SCOPE — read this before trusting any number here
  Backtested (no broker dependency in the signal path):
      Strategy 6  Gap Fill Reversal      engine/strategy_gap.py     (0 client calls)
      Strategy 7  Swing-Pivot Breakout   engine/strategy_swing.py   (0 client calls)
      Strategy 8  Smart Money Concepts   engine/strategy_8.py       (0 client calls)
      Strategy 9  9-EMA Momentum         engine/strategy_9.py       (1 client call, stubbed)
  NOT backtested — these query the broker mid-signal (option chain / strike selection), so
  replaying them would require mocking broker responses; fabricated fills would produce
  misleading numbers, which is worse than no number:
      Strategy 2 (9:26), Strategy 3 (ORB), Strategy 4 (Wisdom)  — 3-5 client calls each
      Strategy 5 (Aerospace) — fetches all its own data internally
  Strategy 1 (OB+FVG) has its own dedicated harness: backtest_ob_fvg.py

MEASURES spot directional edge in points, exactly like backtest_ob_fvg.py. Option premium
P&L (delta/theta/IV) is NOT simulated. No lookahead: signals are produced from data up to
the current bar only.

Usage:  .venv/bin/python3 backtest_strategies.py [--cached]
"""
import asyncio
import bisect
import json
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
IST = pytz.timezone("Asia/Kolkata")
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "bt_data.json")
SYMBOL = "NSE:NIFTY50-INDEX"
SESSION = ((9, 15), (15, 0))
SQUARE_OFF = (15, 14)
R_TARGET = 1.0


# ───────────────────────── stubs ─────────────────────────
class StubClient:
    """Minimal stand-in. Strategies in scope don't need real broker data for the SIGNAL;
    anything they do ask for returns benign values so the code path runs unchanged."""
    def __init__(self):
        self.user_id = 1

    def get_historical(self, symbol, resolution, days_back=10):
        return []

    def get_quote(self, symbol):
        return {"lp": 0}

    def get_quotes(self, symbols, force_rest=False):
        return {}

    def is_authenticated(self):
        return True

    def find_nearest_expiry(self, spot, symbol=None):
        return {"code": "0", "date": "2026-07-30"}

    def get_option_chain_strikes(self, *a, **k):
        return {}


class StubState:
    """TradingState-shaped stub: permissive gates so we measure the STRATEGY, not the
    risk rails (those are tested separately and would just zero out the sample)."""
    def __init__(self):
        self.user_id = 1
        self.active_strategies = [
            "Strategy 6: Gap Fill Reversal", "Strategy 7: Swing-Pivot Breakout",
            "Strategy 8: Smart Money Concepts", "Strategy 9: 9-EMA Momentum Scalper",
        ]
        self.commodity_strategies = []
        self.active_symbols = [SYMBOL]
        self.enabled_symbols = [SYMBOL]
        self.trade_lots = 1
        self.stock_lots = 1
        self.mcx_lots = 1
        self.paper_trading = True
        self.automation_enabled = True
        self.active_auto_trades = []
        self.closed_trades_today = []
        self.traded_strikes_today = []
        self.skipped_signals = []
        self.strat_6_trades_today = 0
        self.strat_6_confirmed = False
        self.strat_6_gap_data = None
        self.strat_6_confirmation_data = None
        self.strat_7_trades_today = 0
        self.strat_7_pending_order = None
        self.strat_7_was_stopout = False
        self.strat_7_awaiting_confirmation = None
        self.max_sl_trending = 15.0
        self.max_sl_range = 10.0
        self.use_ai_oracle = False
        self.ai_daily_bias = ""
        self.commodity_params = {"sl_multiplier": 1.75, "target_multiplier": 1.75,
                                 "breakout_buffer_mult": 1.5}

    def can_trade(self, *a, **k):
        return True, "OK"

    def has_active_trade_for_strategy(self, *a, **k):
        return False

    def save(self):
        pass

    def __getattr__(self, name):        # tolerate any attribute a strategy reaches for
        return None


def ist(ts):
    return datetime.fromtimestamp(ts, IST)


def load_data():
    if not os.path.exists(DATA_FILE):
        raise SystemExit("bt_data.json missing — run backtest_ob_fvg.py first to fetch history.")
    d = json.load(open(DATA_FILE))
    return sorted(d["c5"], key=lambda x: x["timestamp"]), sorted(d["c1"], key=lambda x: x["timestamp"])


def _sig_levels(sig, spot):
    """Pull entry/SL out of a signal dict — shapes differ per strategy."""
    if not isinstance(sig, dict):
        return None
    typ = (sig.get("type") or sig.get("direction") or "").upper()
    if "CALL" in typ or "CE" in typ or "BUY" in typ:
        direction = "BULLISH"
    elif "PUT" in typ or "PE" in typ or "SELL" in typ:
        direction = "BEARISH"
    else:
        return None
    entry = sig.get("entry_price") or spot
    sl = sig.get("sl_price") or sig.get("stop_loss")
    if not sl:
        sl = entry - 20 if direction == "BULLISH" else entry + 20
    risk = abs(entry - sl)
    if risk < 1:
        return None
    return {"dir": direction, "entry": entry, "sl": sl, "risk": risk}


class _FrozenDateTime(datetime):
    """datetime subclass whose now()/today() return the REPLAY bar's time.

    These strategies call datetime.now(IST) internally instead of taking the bar timestamp,
    and Strategy 9 additionally calls get_market_phase() (also wall-clock). Without freezing
    time every strategy exits immediately when the backtest is run outside market hours —
    which is exactly why the first run reported 0 signals and 0 errors. Freezing time is the
    only way to replay them faithfully.
    """
    _now = None

    @classmethod
    def set(cls, dt):
        cls._now = dt

    @classmethod
    def now(cls, tz=None):
        return cls._now.astimezone(tz) if tz else cls._now

    @classmethod
    def today(cls):
        return cls._now


def _freeze_time_in_strategy_modules():
    """Patch `datetime` inside each strategy module + the market-phase helper."""
    import engine.strategy_gap as m_gap
    import engine.strategy_swing as m_swing
    import engine.strategy_8 as m8
    import engine.strategy_9 as m9
    import workers.market_worker as mw

    for m in (m_gap, m_swing, m8, m9):
        m.datetime = _FrozenDateTime
    mw.datetime = _FrozenDateTime
    # Strategy 9 gates on get_market_phase(); force the open-market phase so the strategy's
    # OWN time rules decide, not the wall clock.
    m9.get_market_phase = lambda *a, **k: "market"
    return m9


async def collect(c5, c1):
    from engine.strategy_gap import evaluate_gap_fill_strategy
    from engine.strategy_swing import evaluate_swing_pivot_strategy
    from engine.strategy_8 import evaluate_strategy_8
    from engine.strategy_9 import evaluate_strategy_9
    m9 = _freeze_time_in_strategy_modules()
    # Strategy 9 checks phase in ["OPEN","CLOSING"]; our patch returns "market", so also
    # accept whatever it compares against by normalising here.
    m9.get_market_phase = lambda *a, **k: "OPEN"

    five_ts = [c["timestamp"] for c in c5]
    client, state = StubClient(), StubState()
    out = {k: [] for k in ("Strategy 6", "Strategy 7", "Strategy 8", "Strategy 9")}
    errors = {k: 0 for k in out}
    last_day = None

    for i in range(60, len(c1), 5):          # evaluate every 5 minutes of replay
        bar = c1[i]
        dt = ist(bar["timestamp"])
        if not (SESSION[0] <= (dt.hour, dt.minute) <= SESSION[1]):
            continue
        day = dt.strftime("%Y-%m-%d")
        if day != last_day:                  # reset per-day strategy state like live does
            last_day = day
            state.strat_6_trades_today = 0
            state.strat_6_confirmed = False
            state.strat_6_gap_data = None
            state.strat_7_trades_today = 0
            state.strat_7_pending_order = None

        # Freeze wall-clock to THIS bar so the strategies' internal datetime.now() checks
        # (session windows, minute%5 gates) evaluate against replay time, not real time.
        _FrozenDateTime.set(dt)

        spot = bar["close"]
        hi = bisect.bisect_right(five_ts, bar["timestamp"] - 300)
        w5 = c5[max(0, hi - 300):hi]
        w1 = c1[max(0, i - 400):i + 1]
        if len(w5) < 30:
            continue
        analysis = {"spot": spot, "candles_5m": w5, "candles_1m": w1,
                    "trend": {"trend": "NEUTRAL", "strength": 50}, "signals": [],
                    "vix": 13.0, "order_blocks": [], "fvg": [], "key_levels": []}

        async def run(name, coro):
            try:
                res = await coro
            except Exception:
                errors[name] += 1
                return
            sig = None
            if isinstance(res, tuple):
                ok, s = (res + (None,))[:2]
                sig = s if ok else None
            elif isinstance(res, dict):
                sig = res
            lv = _sig_levels(sig, spot) if sig else None
            if lv:
                lv.update({"i": i, "day": day})
                out[name].append(lv)

        await run("Strategy 6", evaluate_gap_fill_strategy(spot, w5, analysis, [SYMBOL], client, state))
        await run("Strategy 7", evaluate_swing_pivot_strategy(spot, w5, analysis, [SYMBOL], client, state))
        await run("Strategy 8", evaluate_strategy_8(SYMBOL, spot, w1, w5, analysis, client, state))
        await run("Strategy 9", evaluate_strategy_9(SYMBOL, spot, w5, analysis, client, state))

    return out, errors


def simulate(sigs, c1):
    """One trade per day per strategy, exit at 1R / stop / 15:14 — same rules as the OB+FVG harness."""
    res, per_day, busy = [], {}, -1
    for s in sigs:
        if s["i"] <= busy or per_day.get(s["day"], 0) >= 1:
            continue
        per_day[s["day"]] = 1
        is_bull = s["dir"] == "BULLISH"
        entry, sl, risk = s["entry"], s["sl"], s["risk"]
        r = None
        for j in range(s["i"] + 1, len(c1)):
            b = c1[j]
            d = ist(b["timestamp"])
            busy = j
            if d.strftime("%Y-%m-%d") != s["day"] or (d.hour, d.minute) >= SQUARE_OFF:
                r = ((b["close"] - entry) if is_bull else (entry - b["close"])) / risk
                break
            fav = ((b["high"] - entry) if is_bull else (entry - b["low"])) / risk
            if fav >= R_TARGET:
                r = R_TARGET
                break
            if (is_bull and b["low"] <= sl) or (not is_bull and b["high"] >= sl):
                r = -1.0
                break
        if r is not None:
            res.append({"r": r, "pts": r * risk})
    return res


async def main():
    c5, c1 = load_data()
    days = len({ist(b["timestamp"]).strftime("%Y-%m-%d") for b in c1})
    print(f"Replaying {days} trading days ({len(c1)} 1m bars)...\n")
    sigs, errors = await collect(c5, c1)

    print("=" * 74)
    print(f"{'STRATEGY':<34}{'SIGNALS':>8}{'TRADES':>8}{'WIN%':>7}{'TOT pts':>9}{'ERR':>6}")
    print("=" * 74)
    for name in ("Strategy 6", "Strategy 7", "Strategy 8", "Strategy 9"):
        s = sigs[name]
        res = simulate(s, c1)
        if not res:
            print(f"{name:<34}{len(s):>8}{0:>8}{'n/a':>7}{'n/a':>9}{errors[name]:>6}")
            continue
        w = sum(1 for x in res if x["r"] > 0)
        print(f"{name:<34}{len(s):>8}{len(res):>8}{w/len(res)*100:>6.1f}%"
              f"{sum(x['pts'] for x in res):>9.1f}{errors[name]:>6}")
    print("=" * 74)
    print("Exit rule: 1R target / stop / 15:14 square-off. Spot-direction only —")
    print("option premium P&L NOT simulated. ERR = evaluations that raised (stub limits).")
    print("\nNOT covered here: Strategy 2/3/4 (3-5 broker calls mid-signal) and Strategy 5")
    print("(fetches its own data). Backtesting those needs mocked broker responses, which")
    print("would produce misleading fills. Strategy 1 -> backtest_ob_fvg.py")


if __name__ == "__main__":
    asyncio.run(main())
