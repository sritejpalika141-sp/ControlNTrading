"""Strategy 2 (9:26 - 180 Buy) regression coverage — strategy-rebuild Phase 03.

Audit-only phase: these tests pin down the CURRENT behavior of engine/strategy_926.py
(entry window, one-trade-per-day cap, arm-then-recover crossover, ATM-based SL/target
sizing, zero-ATM fallback) and guard against recurrence of the historical
duplicate-`_find_180_strikes`-definition shadowing bug.

Mocking notes: `client.get_quotes` and `client.find_nearest_expiry` are both SYNC methods
invoked via `asyncio.to_thread(...)`, so they are mocked as plain `MagicMock` callables,
never `AsyncMock`.
"""
import os
import re
import sys
import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytz

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.strategy_926 import (  # noqa: E402
    evaluate_926_strategy,
    _find_180_strikes,
    ENTRY_PRICE,
    ARMING_THRESHOLD,
    SL_POINTS,
    TARGET_POINTS,
)

IST = pytz.timezone("Asia/Kolkata")
STRAT_NAME = "Strategy 2: 9:26 - 180 Buy"
EXPIRY_CODE = "26SEP"
SPOT_SYMBOL = "NSE:NIFTY50-INDEX"


class FakeState:
    """Minimal state stand-in. The strategy reads every strat_926_* attribute via
    getattr(state, attr, default), so only active_strategies/trade_lots are required."""

    def __init__(self):
        self.active_strategies = [STRAT_NAME]
        self.trade_lots = 1


def _at(hhmmss):
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return IST.localize(datetime(2026, 8, 31, h, m, s))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _atm_quote_client(spot, atm_ce_ltp, atm_pe_ltp, extra_quotes=None):
    """Build a client whose get_quotes serves BOTH calls _find_180_strikes makes:
    the single-symbol spot lookup and the CE/PE strike-chunk lookup."""
    atm = round(spot / 50) * 50
    chunk_quotes = {
        f"NSE:NIFTY{EXPIRY_CODE}{atm}CE": {"lp": atm_ce_ltp},
        f"NSE:NIFTY{EXPIRY_CODE}{atm}PE": {"lp": atm_pe_ltp},
    }
    if extra_quotes:
        chunk_quotes.update(extra_quotes)

    def _get_quotes(symbols):
        if list(symbols) == [SPOT_SYMBOL]:
            return {SPOT_SYMBOL: {"lp": spot}}
        return {s: chunk_quotes[s] for s in symbols if s in chunk_quotes}

    client = MagicMock()
    client.get_quotes = MagicMock(side_effect=_get_quotes)
    client.find_nearest_expiry = MagicMock(
        return_value={"code": EXPIRY_CODE, "date": "2026-09-30"}
    )
    return client


def _seeded_strikes(ltp=0, armed=None):
    ce = {"symbol": f"NSE:NIFTY{EXPIRY_CODE}24000CE", "ltp": ltp, "strike": 24000}
    if armed is not None:
        ce["armed"] = armed
    return {
        "ce": ce,
        "pe": None,
        "_entry_price": 180.0,
        "_arming_threshold": 178.2,
        "_sl_points": 27.0,
        "_target_points": 54.0,
    }


# --- Test 1 (B2) -----------------------------------------------------------------


def test_entry_window_enforcement():
    """Fires only inside 09:26:00-09:40:00; sets the expired flag after 09:40."""
    client = MagicMock()
    client.get_quotes = MagicMock(side_effect=AssertionError("must not fetch quotes"))

    early = FakeState()
    assert _run(evaluate_926_strategy(client, early, now=_at("09:20:00"))) is None
    assert getattr(early, "strat_926_expired", False) is False

    late = FakeState()
    assert _run(evaluate_926_strategy(client, late, now=_at("09:45:00"))) is None
    assert late.strat_926_expired is True


# --- Test 2 (B3) -----------------------------------------------------------------


def test_one_trade_per_day_cap():
    """strat_926_triggered short-circuits every later call the same day."""
    client = MagicMock()
    client.get_quotes = MagicMock(side_effect=AssertionError("must not fetch quotes"))

    state = FakeState()
    state.strat_926_triggered = True
    state.strat_926_strikes = _seeded_strikes(ltp=180.0, armed=True)

    assert _run(evaluate_926_strategy(client, state, now=_at("09:30:00"))) is None


# --- Test 3 (B4) -----------------------------------------------------------------


def test_arm_then_recover_crossover():
    """A dip below the arming threshold ARMS the strike; a later cross back above the
    entry price then TRIGGERS the one-per-day flag and returns a BUY/CALL signal."""
    state = FakeState()
    state.strat_926_strikes = _seeded_strikes()
    ce_sym = state.strat_926_strikes["ce"]["symbol"]

    client = MagicMock()

    # Tick 1: 175.0 < arming 178.2 → arms, no signal.
    client.get_quotes = MagicMock(return_value={ce_sym: {"lp": 175.0}})
    assert _run(evaluate_926_strategy(client, state, now=_at("09:30:00"))) is None
    assert state.strat_926_strikes["ce"]["armed"] is True
    assert getattr(state, "strat_926_triggered", False) is False

    # Tick 2: 180.5 >= entry 180.0 on the now-armed strike → triggers.
    client.get_quotes = MagicMock(return_value={ce_sym: {"lp": 180.5}})
    sig = _run(evaluate_926_strategy(client, state, now=_at("09:31:00")))
    assert sig is not None
    assert sig["side"] == "BUY"
    assert sig["type"] == "CALL"
    assert sig["entry_price"] == 180.5
    assert state.strat_926_triggered is True


def test_direct_jump_without_arming_still_sets_triggered_flag():
    """Confirmed bug FIXED in Phase 3 of strategy-rebuild: a strike jumping straight to/above
    the entry price WITHOUT first dipping below the arming threshold still returns a signal
    dict (the `return` sits outside the `armed` check), so the one-trade-per-day
    `strat_926_triggered` flag must now be consumed unconditionally. Previously it was gated
    on `armed`, which allowed more than 1 trade/day."""
    state = FakeState()
    state.strat_926_strikes = _seeded_strikes()
    ce_sym = state.strat_926_strikes["ce"]["symbol"]

    client = MagicMock()
    client.get_quotes = MagicMock(return_value={ce_sym: {"lp": 180.5}})

    sig = _run(evaluate_926_strategy(client, state, now=_at("09:30:00")))

    # armed was never set, but a signal IS emitted → the one-per-day flag must be consumed.
    assert state.strat_926_strikes["ce"].get("armed", False) is False
    assert getattr(state, "strat_926_triggered", False) is True
    assert sig is not None and sig["entry_price"] == 180.5


# --- Test 4 (B5) -----------------------------------------------------------------


def test_atm_based_sl_target_sizing():
    """SL ~15% / target ~30% of ATM premium; entry 95%; arming 99% of entry."""
    spot = 24000.0
    atm_ce_ltp, atm_pe_ltp = 200.0, 180.0
    atm_premium = (atm_ce_ltp + atm_pe_ltp) / 2  # 190.0

    client = _atm_quote_client(spot, atm_ce_ltp, atm_pe_ltp)
    result = _run(_find_180_strikes(client))

    assert result is not None
    assert result["_entry_price"] == round(atm_premium * 0.95, 1)
    assert result["_arming_threshold"] == round(round(atm_premium * 0.95, 1) * 0.99, 1)
    assert result["_sl_points"] == round(atm_premium * 0.15, 1)
    assert result["_target_points"] == round(atm_premium * 0.30, 1)


# --- Test 5 (B6) -----------------------------------------------------------------


def test_zero_atm_premium_fallback():
    """No usable ATM premium → hardcoded module constants are used instead."""
    spot = 24000.0
    # A non-ATM CE inside the fallback [SELECTION_MIN, SELECTION_MAX] band so the
    # function still returns a candidate.
    extra = {f"NSE:NIFTY{EXPIRY_CODE}24100CE": {"lp": 180.0}}
    client = _atm_quote_client(spot, 0, 0, extra_quotes=extra)

    result = _run(_find_180_strikes(client))

    assert result is not None
    assert result["_entry_price"] == ENTRY_PRICE
    assert result["_arming_threshold"] == ARMING_THRESHOLD
    assert result["_sl_points"] == SL_POINTS
    assert result["_target_points"] == TARGET_POINTS


# --- Test 6 (B7) -----------------------------------------------------------------


def test_no_duplicate_find_180_strikes_definition():
    """Regression guard for the historical duplicate-definition shadowing bug, plus a
    reachability check that the live implementation actually returns a result."""
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "engine",
        "strategy_926.py",
    )
    with open(src_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    # Count real top-level definitions only. A plain substring count would also match the
    # in-file historical NOTE comment that quotes `async def _find_180_strikes(client):`
    # while describing the removed duplicate, so anchor to line-start.
    definitions = re.findall(r"^async def _find_180_strikes\b", src, re.MULTILINE)
    assert len(definitions) == 1, f"expected 1 definition, found {len(definitions)}"

    client = _atm_quote_client(24000.0, 200.0, 180.0)
    assert _run(_find_180_strikes(client)) is not None
