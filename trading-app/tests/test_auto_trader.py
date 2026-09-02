"""Phase 2 tests for workers/auto_trader.py — items B2, B3, B5, B6."""
import asyncio
import os

import pytest

import workers.auto_trader as at


# ── B2: missing/malformed `pl` must not be silently treated as ₹0 ──────────────
def test_pl_missing_alerts():
    positions = [
        {"symbol": "A", "pl": -100.0},
        {"symbol": "B"},              # missing pl entirely
        {"symbol": "C", "pl": 50.0},
        {"symbol": "D", "pl": "oops"},  # non-numeric
    ]
    total, incomplete, bad = at.aggregate_position_pnl(positions)
    # Only the two valid numeric pls are summed; the bad ones are excluded, NOT zeroed-in.
    assert total == -50.0
    assert incomplete is True
    assert set(bad) == {"B", "D"}


def test_pl_all_valid_is_not_incomplete():
    total, incomplete, bad = at.aggregate_position_pnl(
        [{"symbol": "A", "pl": 10}, {"symbol": "B", "pl": -4}]
    )
    assert total == 6
    assert incomplete is False
    assert bad == []


def test_pl_bool_is_treated_as_invalid():
    # bool is a subclass of int in Python; a stray True/False must not count as P&L.
    total, incomplete, bad = at.aggregate_position_pnl([{"symbol": "A", "pl": True}])
    assert total == 0.0
    assert incomplete is True
    assert bad == ["A"]


# ── B3: one user's failure must not abort other users' loop tick ───────────────
@pytest.mark.asyncio
async def test_per_user_isolation(monkeypatch):
    calls = []

    class _FakeState:
        active_auto_trades = []
        max_loss_per_day = 1000.0

    def fake_get_user_state(u_id):
        calls.append(u_id)
        if u_id == 1:
            raise ValueError("boom — user 1 malformed state")
        return _FakeState()

    # Two users; user 1 raises inside its per-user body, user 2 must still be processed.
    monkeypatch.setattr(at, "USER_CONTEXTS", {1: object(), 2: object()}, raising=True)
    monkeypatch.setattr(at, "get_user_state", fake_get_user_state, raising=True)

    async def _stop_sleep(*_a, **_k):
        # End the infinite while-loop after the first full tick. CancelledError is a
        # BaseException, so the per-user `except Exception` does NOT swallow it.
        raise asyncio.CancelledError

    monkeypatch.setattr(at.asyncio, "sleep", _stop_sleep, raising=True)

    with pytest.raises(asyncio.CancelledError):
        await at.trailing_monitor()

    # Both users reached despite user 1 raising -> isolation holds.
    assert calls == [1, 2]


# ── B5: fabricated Try-4 estimated-price branch must be gone ───────────────────
def test_no_fabricated_price_order():
    src = _read_source("workers/auto_trader.py")
    # The removed fabrication computed entry_price from intrinsic + time_value.
    assert "intrinsic + time_value" not in src
    assert "ESTIMATED premium" not in src
    # The fail-safe skip must remain (no order on unavailable real price).
    assert "no fabricated-price order" in src


# ── B6: ATR trail must not overwrite sl_points (distance) with an absolute price ─
def test_atr_sl_field_separation():
    src = _read_source("workers/auto_trader.py")
    # The buggy overwrite is gone; the dedicated absolute-price field is used instead.
    assert 't["sl_points"] = new_sl' not in src
    assert 't["trailing_sl_price"] = new_sl' in src


def _read_source(rel):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, rel), "r") as f:
        return f.read()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 16 — Strategy 1 identity fixes.
#
# Bug 1: run_strat_1() passed a bare "Strategy 1" to can_trade(), which never matched
#        automation.py's `.startswith("Strategy 1:")` cap gate -> the 2-trades/day cap was
#        dead code. Fixed by hoisting a single `strat_name` local used for BOTH the
#        can_trade() gate and the propose_trade() call, inside the newly extracted
#        module-level _strat1_attempt_trade().
# Bug 2: execute_auto_trade()'s directional-consistency guard used substring containment
#        (`"Strategy 1" in strategy_name`), which also matched "Strategy 10: ..." and
#        "Strategy 11: ...". Fixed with exact-match-on-split.
#
# These tests deliberately exercise the REAL production code (the extracted function and
# execute_auto_trade itself) and assert on the ACTUAL string reaching can_trade — NOT a
# hand-typed "string I think gets passed". That test design already failed once here
# (test_trading_core.py::test_strategy1_daily_cap passed while the real call site was broken).
# ═══════════════════════════════════════════════════════════════════════════════

from engine.automation import TradingState  # noqa: E402

STRAT1_FULL_NAME = "Strategy 1: OB + FVG"


def _make_strat1_state(**overrides):
    """A real TradingState (real can_trade(), NOT mocked) with permissive defaults, no I/O."""
    st = TradingState.__new__(TradingState)
    defaults = dict(
        user_id=99991, use_ai_oracle=False, ai_daily_bias=None,
        automation_enabled=True, hard_exit_triggered=False,
        paper_trading=True, paper_trades_today=0, live_trades_today=0,
        paper_pnl_today=0.0, live_pnl_today=0.0,
        max_trades_per_day=100, max_loss_per_day=5000.0,
        loss_trades_today=0, max_loss_trades_per_day=3,
        last_trade_close_time=0.0, last_trade_time=0.0, last_trade_result="",
        active_auto_trades=[], closed_sessions_today=[],
        strat_1_trades_today=0, STRAT_1_MAX_TRADES_PER_DAY=2,
        active_strategies=[STRAT1_FULL_NAME], profit_target_met=False,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(st, k, v)
    st.check_daily_reset = lambda: None
    st._get_cooldown_minutes = lambda: 0
    st.has_active_trade_for_strategy = lambda *a, **k: False
    return st


def _strat1_analysis():
    """Analysis dict shaped like a real Strategy-1-eligible payload (CALL in a bull trend)."""
    return {
        "trend": {"trend": "BULLISH"},
        "signals": [{"type": "CALL", "confidence": 80, "ai_confidence": 70, "ai_status": "ok"}],
    }


def _record_can_trade(state):
    """Wrap the REAL can_trade() so we capture the exact strategy_name argument the
    production call site passes, without replacing the gate's real logic."""
    seen = []
    real = state.can_trade

    def _rec(strategy_name="", signal_type="", symbol=""):
        seen.append(strategy_name)
        return real(strategy_name, signal_type=signal_type, symbol=symbol)

    state.can_trade = _rec
    return seen


def _patch_propose_trade(monkeypatch):
    proposed = []

    async def _fake_propose(*args, **kwargs):
        proposed.append(args)
        return True

    monkeypatch.setattr(at.risk_orchestrator, "propose_trade", _fake_propose, raising=True)
    return proposed


# ── Bug 1: the real call site must pass the FULL name to can_trade ─────────────
@pytest.mark.asyncio
async def test_strat1_passes_full_name_to_can_trade(monkeypatch):
    state = _make_strat1_state(strat_1_trades_today=0)
    seen = _record_can_trade(state)
    proposed = _patch_propose_trade(monkeypatch)

    await at._strat1_attempt_trade(state, object(), "NSE:NIFTY50-INDEX", _strat1_analysis())

    # The ACTUAL argument the production code passes — a bare "Strategy 1" here would
    # silently bypass automation.py's `.startswith("Strategy 1:")` cap gate.
    assert seen == [STRAT1_FULL_NAME]
    # Under the cap -> the trade is proposed, with the same single name.
    assert len(proposed) == 1
    assert proposed[0][0] == STRAT1_FULL_NAME


# ── Bug 1: the daily cap must now actually block (it never did before) ─────────
@pytest.mark.asyncio
async def test_strat1_daily_cap_blocks_at_real_call_site(monkeypatch):
    state = _make_strat1_state(strat_1_trades_today=2)  # == STRAT_1_MAX_TRADES_PER_DAY
    seen = _record_can_trade(state)
    proposed = _patch_propose_trade(monkeypatch)

    await at._strat1_attempt_trade(state, object(), "NSE:NIFTY50-INDEX", _strat1_analysis())

    assert seen == [STRAT1_FULL_NAME]
    # BEHAVIOR CHANGE (intended): with the bare-string bug, can_trade() returned True here
    # and the trade went through. The cap now enforces.
    assert proposed == []


@pytest.mark.asyncio
async def test_strat1_skips_mcx_and_cds(monkeypatch):
    """Extraction integrity: the MCX/CDS guard moved with the body and still short-circuits."""
    proposed = _patch_propose_trade(monkeypatch)
    for sym in ("MCX:CRUDEOIL26AUG7500CE", "CDS:USDINR26AUGFUT"):
        state = _make_strat1_state()
        await at._strat1_attempt_trade(state, object(), sym, _strat1_analysis())
    assert proposed == []


@pytest.mark.asyncio
async def test_strat1_skips_when_strategy_disabled(monkeypatch):
    """Extraction integrity: the active_strategies gate uses the same full name."""
    state = _make_strat1_state(active_strategies=[])
    proposed = _patch_propose_trade(monkeypatch)
    await at._strat1_attempt_trade(state, object(), "NSE:NIFTY50-INDEX", _strat1_analysis())
    assert proposed == []


# ── Bug 2: execute_auto_trade()'s directional guard must not misidentify S10/S11 ──
class _FakeClient:
    user_id = 99991

    async def get_historical(self, *a, **k):
        return []


def _setup_execute_auto_trade(monkeypatch):
    """Drive the REAL execute_auto_trade() as far as the directional-consistency guard.

    Sentinel: api_queue.enqueue is the FIRST thing called after the guard. If the
    Strategy-1 branch fires (early `return`), enqueue is never reached.
    """
    state = _make_strat1_state()
    state._last_trade_fail_time = 0
    state.enabled_symbols = ["NSE:NIFTY50-INDEX"]
    state.max_concurrent_index_options = 2
    monkeypatch.setattr(at, "get_user_state", lambda u_id: state, raising=True)

    reached = []

    class _FakeQueue:
        async def enqueue(self, *a, **k):
            reached.append(True)
            return []  # empty history -> the directional gate then returns; nothing is traded

    monkeypatch.setattr(at, "api_queue", _FakeQueue(), raising=True)
    return reached


def _sig(strategy_name, sig_type="PUT"):
    return {"strategy": strategy_name, "type": sig_type, "side": "BUY", "confidence": 80}


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy_name", [
    "Strategy 10: Adaptive ADX Engine",
    "Strategy 11: FRVP LVN Vacuum",
])
async def test_directional_guard_does_not_fire_for_strategy_10_and_11(monkeypatch, strategy_name):
    reached = _setup_execute_auto_trade(monkeypatch)
    # PUT signal in a BULLISH trend: Strategy 1's guard would `return` here.
    await at.execute_auto_trade(
        "NSE:NIFTY50-INDEX", _sig(strategy_name, "PUT"),
        {"trend": {"trend": "BULLISH"}}, _FakeClient())
    # Substring containment ("Strategy 1" in "Strategy 10: ...") would have blocked this.
    assert reached == [True], f"{strategy_name} was misidentified as Strategy 1"


@pytest.mark.asyncio
async def test_directional_guard_still_fires_for_real_strategy_1(monkeypatch):
    reached = _setup_execute_auto_trade(monkeypatch)
    await at.execute_auto_trade(
        "NSE:NIFTY50-INDEX", _sig(STRAT1_FULL_NAME, "PUT"),
        {"trend": {"trend": "BULLISH"}}, _FakeClient())
    # No false-negative introduced by the fix: genuine Strategy 1 is still guarded.
    assert reached == []


@pytest.mark.asyncio
async def test_directional_guard_allows_aligned_strategy_1(monkeypatch):
    reached = _setup_execute_auto_trade(monkeypatch)
    await at.execute_auto_trade(
        "NSE:NIFTY50-INDEX", _sig(STRAT1_FULL_NAME, "CALL"),
        {"trend": {"trend": "BULLISH"}}, _FakeClient())
    assert reached == [True]
