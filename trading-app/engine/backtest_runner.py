"""
Backtest runner (04-08-26) — orchestrates engine/backtest_engine.py: fetches real historical
underlying candles once per symbol, then replays them candle-by-candle through each strategy's
REAL evaluate_* function, simulating entries/exits with Black-Scholes-modeled option premiums.

See engine/backtest_engine.py's module docstring for the two honest simplifications (modeled
premiums, uniform SL/target model) before trusting a number out of this file.

Known per-strategy limitations (beyond the two general ones above):
  - Strategy 5: its internal 3-min candle fetch has a 15s real-time cache TTL that isn't
    backtest-clock-aware — results are best-effort.
  - Strategy 9: its session gate (is_market_open/get_market_phase) checks the REAL wall clock,
    not the simulated one — a backtest run outside real market hours under-reports its signals.
  - Strategy 7: returns a pending-trigger shape (trigger_price/sl_price) rather than an immediate
    signal; approximated here as an immediate entry at the trigger price.
  - Crude strategies: backtested only over whatever historical window the CURRENT active
    futures contract has (no contract-roll stitching), so the window may be shorter than equity.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

import pytz

from engine.backtest_engine import (
    HistoricalReplayClient, BacktestState, build_backtest_analysis,
    realized_vol_from_daily_closes, pick_atm_strike, synthetic_premium,
    DTE_ASSUMPTION_DAYS,
)
from engine.asset_classes import get_asset_class
from engine.strategy_926 import evaluate_926_strategy
from engine.strategy_orb import evaluate_orb_strategy
from engine.strategy_wisdom import evaluate_wisdom_strategy
from engine.strategy_5 import evaluate_strat5_strategy
from engine.strategy_gap import evaluate_gap_fill_strategy
from engine.strategy_swing import evaluate_swing_pivot_strategy
from engine.strategy_8 import evaluate_strategy_8
from engine.strategy_9 import evaluate_strategy_9
from engine.strategy_10 import evaluate_strategy_10
from engine.strategy_11_frvp import evaluate_frvp_strategy
from engine.strategy_crude_evening import generate_signal as crude_evening_signal
from engine.strategy_crude_eia import generate_signal as crude_eia_signal

IST = pytz.timezone("Asia/Kolkata")

# Which underlying + candle resolutions + asset class each strategy needs. "COMMODITY_OPTIONS" is
# the REAL registry key (see engine/asset_classes.py) — the crude strategy files themselves pass
# the WRONG name ("CRUDE_OIL_OPTIONS", not registered) to get_asset_class internally, a separate
# live bug this backtest build surfaced; noted for a follow-up fix, worked around here by using
# the correct key directly.
STRATEGY_META = {
    "Strategy 1: OB + FVG":                         {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5", "60", "D", "1"}},
    "Strategy 2: 9:26 - 180 Buy":                    {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5"}},
    "Strategy 3: 5-Minute ORB":                      {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5", "D"}},
    "Strategy 4: Wisdom-Aligned Pullback":           {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5", "60", "D"}},
    "Strategy 5: Optimized Aerospace Mean Reversion":{"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5", "3"}},
    "Strategy 6: Gap Fill Reversal":                 {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5"}},
    "Strategy 7: Swing-Pivot Breakout":              {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5"}},
    "Strategy 8: Smart Money Concepts":              {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5", "1"}},
    "Strategy 9: 9-EMA Momentum Scalper":            {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5"}},
    "Strategy 10: Adaptive ADX Engine":              {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5"}},
    "Strategy 11: FRVP LVN Vacuum":                  {"asset_class": "INDEX_OPTIONS", "symbol": "NSE:NIFTY50-INDEX", "needs": {"5", "1", "D"}},
    "Crude Evening Momentum":                        {"asset_class": "COMMODITY_OPTIONS", "symbol": None, "needs": {"5"}},  # symbol resolved at run time (current contract)
    "Crude EIA Volatility":                          {"asset_class": "COMMODITY_OPTIONS", "symbol": None, "needs": {"5"}},
}

SL_FLOOR_PCT = 0.12          # matches the live quality-gate floor (12% of premium)
TRAIL_TRIGGER_R = 1.5        # once favorable move >= 1.5x initial risk, trail SL to breakeven
EOD_BUFFER_MIN = 10          # square off this many minutes before the asset class's hard_exit_time


async def _call_adapter(strategy_name: str, ctx: Dict) -> Optional[Dict]:
    """Calls the REAL evaluate_* function for `strategy_name` and normalizes its return to
    {"type": "CALL"|"PUT", "sl_points": float|None, "target_points": float|None} or None."""
    client, state, now = ctx["client"], ctx["state"], ctx["now"]
    symbol, spot = ctx["symbol"], ctx["spot"]
    c5, c1, c1h, cd = ctx["candles_5m"], ctx["candles_1m"], ctx["candles_1h"], ctx["candles_daily"]
    analysis = ctx["analysis"]

    def _norm(sig_type, sig):
        if not sig_type or sig_type not in ("CALL", "PUT"):
            return None
        return {"type": sig_type, "sl_points": (sig or {}).get("sl_points"),
                "target_points": (sig or {}).get("target_points")}

    if strategy_name == "Strategy 1: OB + FVG":
        signals = analysis.get("signals") or []
        trend_info = analysis.get("trend", {})
        current_trend = (trend_info.get("trend", "") if isinstance(trend_info, dict) else str(trend_info)).upper()
        for sig in signals:
            if sig.get("type") not in ("CALL", "PUT"):
                continue
            if sig.get("confidence", 0) < 70:  # simplified: no AI confidence score in backtest
                continue
            if "BULL" in current_trend and sig["type"] != "CALL":
                continue
            if "BEAR" in current_trend and sig["type"] != "PUT":
                continue
            return _norm(sig["type"], sig)
        return None

    if strategy_name == "Strategy 2: 9:26 - 180 Buy":
        trend_info = analysis.get("trend", {})
        current_trend = (trend_info.get("trend", "") if isinstance(trend_info, dict) else str(trend_info)).upper()
        sig = await evaluate_926_strategy(client, state, current_trend=current_trend, now=now)
        return _norm((sig or {}).get("type"), sig)

    if strategy_name == "Strategy 3: 5-Minute ORB":
        sig = await evaluate_orb_strategy(client, state, symbol, c5, cd, vix=15.0, now=now)
        return _norm((sig or {}).get("type"), sig)

    if strategy_name == "Strategy 4: Wisdom-Aligned Pullback":
        sig = await evaluate_wisdom_strategy(client, state, symbol, c5, c1h, cd, vix=15.0, now=now)
        return _norm((sig or {}).get("type"), sig)

    if strategy_name == "Strategy 5: Optimized Aerospace Mean Reversion":
        sig = await evaluate_strat5_strategy(client, state, now=now)
        return _norm((sig or {}).get("type"), sig)

    if strategy_name == "Strategy 6: Gap Fill Reversal":
        has_sig, sig = await evaluate_gap_fill_strategy(spot, c5, analysis, [symbol], client, state, now=now)
        return _norm((sig or {}).get("type") if has_sig else None, sig)

    if strategy_name == "Strategy 7: Swing-Pivot Breakout":
        has_sig, sig = await evaluate_swing_pivot_strategy(spot, c5, analysis, [symbol], client, state, is_commodity=False, now=now)
        if not has_sig or not sig:
            return None
        raw_type = sig.get("type", "")
        t = "CALL" if "CE" in raw_type else "PUT" if "PE" in raw_type else None
        return _norm(t, sig)

    if strategy_name == "Strategy 8: Smart Money Concepts":
        has_sig, sig = await evaluate_strategy_8(symbol, spot, c1, c5, analysis, client, state, now=now)
        return _norm((sig or {}).get("type") if has_sig else None, sig)

    if strategy_name == "Strategy 9: 9-EMA Momentum Scalper":
        has_sig, sig = await evaluate_strategy_9(symbol, spot, c5, analysis, client, state, now=now)
        return _norm((sig or {}).get("type") if has_sig else None, sig)

    if strategy_name == "Strategy 10: Adaptive ADX Engine":
        has_sig, sig = await evaluate_strategy_10(symbol, spot, c5, analysis, client, state, now=now)
        return _norm((sig or {}).get("type") if has_sig else None, sig)

    if strategy_name == "Strategy 11: FRVP LVN Vacuum":
        sig = await evaluate_frvp_strategy(client, state, symbol, c5, candles_1m=c1, candles_daily=cd, vix=15.0)
        return _norm((sig or {}).get("type"), sig)

    if strategy_name == "Crude Evening Momentum":
        sig = crude_evening_signal(candles=c5, now=now)
        return _norm((sig or {}).get("type"), sig)

    if strategy_name == "Crude EIA Volatility":
        sig = crude_eia_signal(candles=c5, now=now)
        return _norm((sig or {}).get("type"), sig)

    return None


def _reset_daily_state(state: BacktestState):
    """Generic daily reset — clears any '*_triggered' bool and any '*_today'/'*_consec_sl'
    counter, mirroring what the live daily reset does, without hand-enumerating every strategy's
    specific flag name."""
    for k in list(vars(state).keys()):
        if k.endswith("_triggered"):
            setattr(state, k, False)
        elif k.endswith("_today") or k.endswith("_consec_sl"):
            setattr(state, k, 0)
    state.strat_7_pending_order = None
    state.active_auto_trades = []


async def backtest_strategy(strategy_name: str, real_client, days_back: int = 60) -> Dict:
    """Runs one strategy's full backtest and returns a summary dict + trade list."""
    meta = STRATEGY_META[strategy_name]
    asset_class_name = meta["asset_class"]
    ac = get_asset_class(asset_class_name)
    symbol = meta["symbol"]
    if symbol is None:
        # Crude: resolve the current active MCX futures contract (fetched once, live).
        # resolve_current_commodity_expiry returns the FULL tradable symbol already
        # (e.g. "MCX:CRUDEOIL26AUGFUT") — do not re-wrap its return value.
        from engine.strikes import resolve_current_commodity_expiry
        try:
            symbol = resolve_current_commodity_expiry("MCX:CRUDEOIL", client=real_client)
        except Exception:
            symbol = "MCX:CRUDEOIL26AUGFUT"

    # 1. Fetch real historical candles ONCE per needed resolution (read-only, same as any
    #    diagnostic historical pull — not a live trading action).
    store: Dict[str, List[Dict]] = {}
    for res in meta["needs"] | {"5"}:
        db = 90 if res in ("D",) else days_back
        try:
            candles = await asyncio.to_thread(real_client.get_historical, symbol, res, days_back=db)
        except Exception:
            candles = []
        store[res] = sorted(candles or [], key=lambda c: c["timestamp"])

    candles_5m = store.get("5", [])
    if len(candles_5m) < 30:
        return {"strategy": strategy_name, "symbol": symbol, "trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0, "error": "insufficient historical data"}

    iv = realized_vol_from_daily_closes(store.get("D") or candles_5m)
    dte_days = DTE_ASSUMPTION_DAYS.get(asset_class_name, 5.0)
    strike_interval = ac.strike_interval
    eod_h, eod_m = ac.hard_exit_time
    eod_cutoff = (eod_h * 60 + eod_m) - EOD_BUFFER_MIN

    state = BacktestState()
    trades: List[Dict] = []
    active = None  # {"type","strike","entry_prem","sl_price","target_price","entry_time","risk"}
    current_date = None

    for i, candle in enumerate(candles_5m):
        now = datetime.fromtimestamp(candle["timestamp"], IST)
        if current_date is not None and now.date() != current_date:
            if active is not None:
                # Carried a position past a day boundary the live EOD square-off would have
                # closed — force-close at the last known premium rather than let it leak across days.
                exit_prem = active["last_prem"]
                pnl = round((exit_prem - active["entry_prem"]) if active["type"] == "CALL" else (active["entry_prem"] - exit_prem), 2)
                trades.append({**active, "exit_prem": exit_prem, "pnl": pnl, "exit_reason": "day-boundary square-off"})
                active = None
            _reset_daily_state(state)
        current_date = now.date()

        spot = candle["close"]
        minute_of_day = now.hour * 60 + now.minute
        mock_client = HistoricalReplayClient(store, candle["timestamp"], iv, dte_days, symbol)

        if active is not None:
            strike, is_call = active["strike"], active["type"] == "CALL"
            dte_now = max(dte_days - (i - active["entry_idx"]) * (5.0 / (60 * 24)), 0.3)
            prem = synthetic_premium(spot, strike, dte_now, iv, is_call)
            active["last_prem"] = prem
            fav = (prem - active["entry_prem"])
            if fav >= TRAIL_TRIGGER_R * active["risk"]:
                active["sl_price"] = max(active["sl_price"], active["entry_prem"])  # trail to breakeven
            exit_reason = None
            if prem <= active["sl_price"]:
                exit_reason = "SL"
            elif active["target_price"] and prem >= active["target_price"]:
                exit_reason = "TARGET"
            elif minute_of_day >= eod_cutoff:
                exit_reason = "EOD"
            if exit_reason:
                pnl = round(prem - active["entry_prem"], 2)
                trades.append({**active, "exit_prem": prem, "pnl": pnl, "exit_reason": exit_reason})
                active = None
            continue

        if minute_of_day >= eod_cutoff or minute_of_day < ac.session_open[0] * 60 + ac.session_open[1]:
            continue

        c1m = [c for c in store.get("1", []) if c["timestamp"] <= candle["timestamp"]][-100:]
        c1h = [c for c in store.get("60", []) if c["timestamp"] <= candle["timestamp"]][-100:]
        cd_ = [c for c in store.get("D", []) if c["timestamp"] <= candle["timestamp"]][-30:]
        window_5m = candles_5m[:i + 1][-100:]
        analysis = build_backtest_analysis(c1h, window_5m, cd_, c1m, spot, symbol)

        ctx = {"client": mock_client, "state": state, "now": now, "symbol": symbol, "spot": spot,
               "candles_5m": window_5m, "candles_1m": c1m, "candles_1h": c1h, "candles_daily": cd_,
               "analysis": analysis}
        try:
            sig = await _call_adapter(strategy_name, ctx)
        except Exception:
            sig = None
        if not sig:
            continue

        strike = pick_atm_strike(spot, strike_interval)
        is_call = sig["type"] == "CALL"
        entry_prem = synthetic_premium(spot, strike, dte_days, iv, is_call)
        if entry_prem < 0.5:
            continue
        sl_pts = sig.get("sl_points") or max(round(entry_prem * SL_FLOOR_PCT, 2), 0.5)
        tgt_pts = sig.get("target_points") or 0
        active = {
            "strategy": strategy_name, "type": sig["type"], "strike": strike,
            "entry_prem": entry_prem, "last_prem": entry_prem,
            "sl_price": round(entry_prem - sl_pts, 2), "risk": sl_pts,
            "target_price": round(entry_prem + tgt_pts, 2) if tgt_pts else None,
            "entry_time": now.isoformat(), "entry_idx": i,
        }

    if active is not None:
        pnl = round(active["last_prem"] - active["entry_prem"], 2)
        trades.append({**active, "exit_prem": active["last_prem"], "pnl": pnl, "exit_reason": "backtest-end square-off"})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    total_pnl = round(sum(t["pnl"] for t in trades), 2)
    win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0.0
    return {
        "strategy": strategy_name, "symbol": symbol, "trades": len(trades),
        "wins": len(wins), "losses": len(losses), "win_rate": win_rate,
        "total_pnl": total_pnl, "avg_pnl": round(total_pnl / len(trades), 2) if trades else 0.0,
        "trade_log": trades,
    }


async def run_all_backtests(real_client, days_back: int = 60) -> List[Dict]:
    results = []
    for name in STRATEGY_META:
        try:
            r = await backtest_strategy(name, real_client, days_back=days_back)
        except Exception as e:
            r = {"strategy": name, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                 "total_pnl": 0.0, "avg_pnl": 0.0, "error": str(e)}
        results.append(r)
    return results
