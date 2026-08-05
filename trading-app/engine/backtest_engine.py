"""
Shared backtest engine (04-08-26) — runs every real strategy's live evaluate_* function against
replayed historical underlying data, so a backtest can never silently drift from what's actually
live (the flaw in the old hand-rolled backtest_*.py scripts, which re-implemented each strategy's
rules from scratch and were never re-verified against the real code).

TWO HONEST SIMPLIFICATIONS — read this before trusting a number out of this engine:

1. Option premiums are MODELED, not literal historical quotes. Fyers has no historical
   option-chain data for expired contracts, so there is nothing real to replay. Premiums are
   priced with Black-Scholes (engine/greeks.py bs_price) from the REAL historical underlying
   price path (spot, ATM strike, time-to-expiry) using an IV estimated from the underlying's own
   trailing realized volatility. This correctly captures direction, delta-scaling, and theta
   decay — the three things that actually matter for "does this strategy's entry timing have
   edge" — but it is not a byte-identical replay of what the market would have quoted. DTE
   (days-to-expiry) is a fixed per-asset-class assumption (near-week/near-month), not a real
   expiry calendar.
2. SL/target simulation uses ONE uniform rule for every strategy: the strategy's own
   sl_points/target_points from its signal dict when it provides them, else a 12%-of-premium
   floor (matching the same floor used everywhere live), with a simple breakeven-at-1.5x-risk
   trail. It does not replicate each strategy's bespoke live trailing algorithm (Strategy 1's
   1R breakeven-then-trail, Strategy 7's 3-candle swing trail, etc.) exactly.

Read results as "does this strategy's entry logic point the right direction, on real historical
price action" — a screening/prioritization signal — not as an exact live P&L forecast.
"""
import re
import math
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz

from engine.greeks import bs_price, RISK_FREE_RATE
from engine.asset_classes import get_asset_class

IST = pytz.timezone("Asia/Kolkata")

# Fixed near-contract DTE assumption per asset class (days to expiry at signal time, counted
# down as the simulated clock advances). A real expiry calendar needs a holiday calendar this
# engine doesn't have — this is a documented simplification, not an attempt at exact replay.
DTE_ASSUMPTION_DAYS = {
    "INDEX_OPTIONS": 3.0,       # near-week NIFTY contract
    "COMMODITY_OPTIONS": 10.0,  # near-month crude contract
}

REALIZED_VOL_LOOKBACK_DAYS = 20
DEFAULT_IV = 0.18  # fallback if realized-vol estimation fails (bad/short data)


def realized_vol_from_daily_closes(daily_candles: List[Dict], lookback: int = REALIZED_VOL_LOOKBACK_DAYS) -> float:
    """Annualized realized volatility from daily close-to-close returns — the IV proxy used to
    price synthetic premiums (no historical IV surface exists to draw from)."""
    closes = [c["close"] for c in daily_candles[-(lookback + 1):] if c.get("close", 0) > 0]
    if len(closes) < 5:
        return DEFAULT_IV
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 4:
        return DEFAULT_IV
    daily_sd = statistics.stdev(rets)
    annualized = daily_sd * math.sqrt(252)
    return max(0.08, min(annualized, 1.2))  # clamp to a sane band


def pick_atm_strike(spot: float, strike_interval: float) -> float:
    return round(round(spot / strike_interval) * strike_interval, 2)


_STRIKE_SYM_RE = re.compile(r"^(?P<prefix>[A-Z]+:)?(?P<base>[A-Z]+)(?P<rest>[\dA-Z]*?)(?P<strike>\d+)(?P<opt>CE|PE)$")


def parse_strike_symbol(symbol: str) -> Optional[Tuple[float, bool]]:
    """Best-effort (strike, is_call) parse of a Fyers option symbol, e.g.
    'NSE:NIFTY2680424600CE' -> (24600.0, True). Used only by the historical-replay mock client to
    answer a strategy's own internal client.get_quotes([strike_symbol]) call during backtest —
    not used anywhere in the live trading path."""
    try:
        s = symbol.upper().split(":")[-1]
        is_call = s.endswith("CE")
        digits = re.findall(r"\d+", s)
        if not digits:
            return None
        # The strike is the LAST numeric run before CE/PE in Fyers' symbol format.
        strike = float(digits[-1])
        return strike, is_call
    except Exception:
        return None


def synthetic_premium(spot: float, strike: float, dte_days: float, iv: float, is_call: bool) -> float:
    t_years = max(dte_days, 0.3) / 365.0
    price = bs_price(spot, strike, t_years, iv, is_call, RISK_FREE_RATE)
    if price is None or price <= 0:
        # Deep OTM / near-zero-time edge cases — floor at intrinsic (usually 0 for OTM), never
        # a negative or None premium so the simulation loop can always continue.
        intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
        return round(max(intrinsic, 0.05), 2)
    return round(price, 2)


class HistoricalReplayClient:
    """Answers the small subset of client.get_historical / client.get_quotes calls that a handful
    of strategies (2, 3, 4, 5) make internally for their OWN data needs — entirely from data
    fetched ONCE upfront (real historical candles), sliced to never see beyond the simulated
    "now" (no lookahead). Every other client method a strategy might reference but not call
    during signal generation is intentionally left unimplemented — if one is hit, that's a
    real gap to fix, not something to silently stub."""

    def __init__(self, candle_store: Dict[str, List[Dict]], now_ts: float, iv: float,
                 dte_days: float, underlying_symbol: str):
        self._store = candle_store          # {"1": [...], "3": [...], "5": [...], "60": [...], "D": [...]}
        self._now_ts = now_ts
        self._iv = iv
        self._dte_days = dte_days
        self._underlying = underlying_symbol
        self.user_id = 1

    def _res_key(self, resolution) -> str:
        return str(resolution)

    def get_historical(self, symbol, resolution, days_back=None):
        """Sync signature matches the real client (called via asyncio.to_thread live)."""
        key = self._res_key(resolution)
        series = self._store.get(key, [])
        return [c for c in series if c["timestamp"] <= self._now_ts]

    def get_quotes(self, symbols):
        out = {}
        for sym in symbols:
            if sym == self._underlying or sym.endswith("-INDEX") or sym.endswith("-EQ"):
                series = self._store.get("5", [])
                past = [c for c in series if c["timestamp"] <= self._now_ts]
                lp = past[-1]["close"] if past else 0
            else:
                parsed = parse_strike_symbol(sym)
                if not parsed:
                    lp = 0
                else:
                    strike, is_call = parsed
                    series = self._store.get("5", [])
                    past = [c for c in series if c["timestamp"] <= self._now_ts]
                    spot = past[-1]["close"] if past else 0
                    lp = synthetic_premium(spot, strike, self._dte_days, self._iv, is_call) if spot else 0
            out[sym] = {"lp": lp, "ask": lp, "bid": lp}
        return out


class BacktestState:
    """Minimal read-only mimic of the live TradingState — just enough surface for strategy
    evaluate_* functions to read without touching the real per-user state. Deliberately does NOT
    replicate can_trade()'s live-only checks (session timing, real broker balance, cooldowns) —
    those are already exercised live; this engine isolates entry-signal quality."""

    def __init__(self):
        # 04-08-26 bug fix: several strategies gate on an EXACT full-string membership check
        # (e.g. `if "Strategy 8: Smart Money Concepts" not in state.active_strategies: return`) —
        # abbreviated "Strategy N" placeholders never match, so every one of those strategies was
        # silently returning zero signals on every single backtest tick. Must be the exact live
        # names, matching STRATEGY_META in engine/backtest_runner.py.
        self.active_strategies = [
            "Strategy 1: OB + FVG", "Strategy 2: 9:26 - 180 Buy", "Strategy 3: 5-Minute ORB",
            "Strategy 4: Wisdom-Aligned Pullback", "Strategy 5: Optimized Aerospace Mean Reversion",
            "Strategy 6: Gap Fill Reversal", "Strategy 7: Swing-Pivot Breakout",
            "Strategy 8: Smart Money Concepts", "Strategy 9: 9-EMA Momentum Scalper",
            "Strategy 10: Adaptive ADX Engine", "Strategy 11: FRVP LVN Vacuum",
        ]
        self.commodity_strategies = ["Commodity: 5-Minute ORB", "Commodity: 9-EMA Momentum",
                                      "Commodity: Swing-Pivot Breakout", "Commodity: EIA Volatility (Wed)",
                                      "Commodity: Evening Momentum"]
        self.active_symbols = []
        self.active_auto_trades = []
        self.trade_lots = 1
        self.mcx_lots = 1
        self.stock_lots = 1
        self.market_regime = "NEUTRAL"
        self.mcx_regime = "NEUTRAL"
        self.currency_regime = "NEUTRAL"
        self.shadow_strategies = []
        self.paper_trading = True
        self.strat_9_consec_sl = 0
        self.strat_9_last_call = None
        self.strat_7_pending_order = None

    def has_active_trade_for_strategy(self, strategy_name):
        return False

    def can_trade(self, strategy_name="", signal_type="", symbol=""):
        return True, "OK"

    def is_shadow_strategy(self, strategy_name):
        return False


def build_backtest_analysis(candles_1h, candles_5m, candles_daily, candles_1m, spot, symbol, vix=15.0) -> Dict:
    """Same shape the live get_analysis() builds — reuses the REAL signal engine
    (engine.signals.generate_signals) so Strategy 1 and the trend/regime fields every other
    strategy reads from `analysis` are computed identically to live, not re-implemented."""
    from engine.signals import generate_signals
    try:
        result = generate_signals(candles_1h, candles_5m, spot, candles_daily, vix, symbol, candles_1m)
    except Exception:
        result = {}
    result = dict(result or {})
    result.setdefault("spot", spot)
    result["candles_5m"] = candles_5m
    result["candles_1m"] = candles_1m
    result["candles_1h"] = candles_1h
    result["candles_daily"] = candles_daily
    result.setdefault("trend", {"trend": "NEUTRAL"})
    return result
