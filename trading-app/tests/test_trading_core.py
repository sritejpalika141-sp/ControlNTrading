"""
Fast, deterministic regression tests for the MONEY-CRITICAL trading logic.

Every test here locks in a bug that actually reached production on this system, so a future
change (from either agent) that reintroduces it fails CI instead of silently trading wrong:

  * per-session hard-exit gate + Strategy-1 daily cap  (can_trade)
  * agent-scrip tags surviving the daily date-change reset  (TradingState.load)
  * orphaned auto-trade enables getting pruned  (TradingState.load)
  * session-aware, agent-only end-of-day purge  (purge_agent_symbols)
  * symbol -> session bucketing  (session_key_for_symbol)

No network, no broker, no DB: state is built via __new__ or a temp state file, so this runs
in well under a second on both the workstation and the VM.
"""
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from engine.automation import TradingState, session_key_for_symbol  # noqa: E402


# ───────────────────────── helpers ─────────────────────────
def make_state(**overrides):
    """A TradingState with permissive can_trade() defaults, no side effects."""
    st = TradingState.__new__(TradingState)
    defaults = dict(
        user_id=99990, use_ai_oracle=False, ai_daily_bias=None,
        automation_enabled=True, hard_exit_triggered=False,
        paper_trading=True, paper_trades_today=0, live_trades_today=0,
        paper_pnl_today=0.0, live_pnl_today=0.0,
        max_trades_per_day=100, max_loss_per_day=5000.0,
        loss_trades_today=0, max_loss_trades_per_day=3,
        last_trade_close_time=0.0, last_trade_time=0.0, last_trade_result="",
        active_auto_trades=[], closed_sessions_today=[],
        strat_1_trades_today=0, STRAT_1_MAX_TRADES_PER_DAY=2,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(st, k, v)
    st.check_daily_reset = lambda: None
    st._get_cooldown_minutes = lambda: 0
    st.has_active_trade_for_strategy = lambda *a, **k: False
    return st


# ───────────────────────── session bucketing ─────────────────────────
@pytest.mark.parametrize("symbol,expected", [
    ("NSE:NIFTY50-INDEX", "NSE"),
    ("NSE:SBIN-EQ", "NSE"),
    ("MCX:CRUDEOIL26JULFUT", "MCX"),
    ("MCX:CRUDEOIL26JUL7700CE", "MCX"),
    ("CDS:USDINR26JULFUT", "CDS"),
    ("NSE_CD:USDINR", "CDS"),
    ("", "NSE"),
])
def test_session_key(symbol, expected):
    assert session_key_for_symbol(symbol) == expected


# ───────────────────────── can_trade gates ─────────────────────────
def test_can_trade_allows_when_open():
    ok, _ = make_state().can_trade("Strategy 3", signal_type="CALL", symbol="NSE:NIFTY50-INDEX")
    assert ok is True

def test_can_trade_blocks_when_automation_off():
    ok, reason = make_state(automation_enabled=False).can_trade("S", symbol="NSE:NIFTY50-INDEX")
    assert ok is False and "utomation" in reason

def test_can_trade_blocks_on_loss_hard_exit():
    ok, reason = make_state(hard_exit_triggered=True).can_trade("S", symbol="NSE:NIFTY50-INDEX")
    assert ok is False

def test_per_session_gate_blocks_only_that_session():
    """NSE closed for the day must block NSE symbols but NOT MCX (crude trades till 23:20)."""
    st = make_state(closed_sessions_today=["NSE"])
    assert st.can_trade("S", signal_type="CALL", symbol="NSE:SBIN-EQ")[0] is False
    assert st.can_trade("S", signal_type="CALL", symbol="MCX:CRUDEOIL26JULFUT")[0] is True

def test_strategy1_daily_cap():
    """Strategy 1 is capped at 2/day; other strategies are unaffected by that counter.

    SCOPE (Phase 16, 02-09-26) — KEPT, not retired, but read this before trusting it:
    this is a unit test of can_trade()'s OWN cap logic. It hand-types the strategy name, so
    it proves nothing about what the production call site actually passes. It passed for
    months while workers/auto_trader.py's run_strat_1() passed a bare "Strategy 1" that
    never matched this gate — i.e. it masked a live daily-cap bypass. The real-call-site
    coverage now lives in test_auto_trader.py::test_strat1_passes_full_name_to_can_trade and
    ::test_strat1_daily_cap_blocks_at_real_call_site. Do NOT treat this test alone as proof
    that the cap enforces in production.
    """
    for n, expect in [(0, True), (1, True), (2, False), (3, False)]:
        st = make_state(strat_1_trades_today=n)
        assert st.can_trade("Strategy 1: OB + FVG", signal_type="CALL",
                            symbol="NSE:NIFTY50-INDEX")[0] is expect
    # a different strategy is not blocked by Strategy-1's counter
    st = make_state(strat_1_trades_today=5)
    assert st.can_trade("Strategy 3: 5-Minute ORB", signal_type="CALL",
                        symbol="NSE:NIFTY50-INDEX")[0] is True


# ───────────────────────── state persistence (the date-change bug) ─────────────────────────
@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    """Run TradingState against an isolated logs/ dir so tests never touch live state files."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("logs", exist_ok=True)
    created = {}

    def _write(uid, data):
        p = os.path.join("logs", f"trading_state_{uid}.json")
        json.dump(data, open(p, "w"))
        created[uid] = p
        return uid

    yield _write


def test_agent_tags_survive_date_change(temp_state):
    """The reported bug: on the first load of a NEW day, reset_day() ran and the watchlist +
    agent tags fell back to defaults, so purge_agent_symbols() had nothing to purge and
    agent scrips became permanent. Tags must survive the reset."""
    uid = temp_state(90001, {
        "last_reset_date": "2020-01-01",  # force a date-change reset on load
        "active_symbols": ["NSE:NIFTY50-INDEX", "NSE:AGENTSTK-EQ"],
        "enabled_symbols": ["NSE:NIFTY50-INDEX", "NSE:AGENTSTK-EQ"],
        "agent_added_symbols": ["NSE:AGENTSTK-EQ"],
        "automation_enabled": False,
    })
    st = TradingState(user_id=uid)
    assert "NSE:AGENTSTK-EQ" in st.active_symbols
    assert st.agent_added_symbols == ["NSE:AGENTSTK-EQ"], "agent tag was wiped by the reset"


def test_orphaned_enables_pruned_on_load(temp_state):
    """enabled_symbols that are not in the watchlist (e.g. an expired MCX contract) must be
    pruned on load, so a dead symbol is never armed for auto-trade."""
    uid = temp_state(90002, {
        "last_reset_date": "2020-01-01",
        "active_symbols": ["NSE:NIFTY50-INDEX"],
        "enabled_symbols": ["NSE:NIFTY50-INDEX", "MCX:CRUDEOIL24NOVFUT", "NSE:SBIN-EQ"],
        "agent_added_symbols": [],
    })
    st = TradingState(user_id=uid)
    assert st.enabled_symbols == ["NSE:NIFTY50-INDEX"]


# ───────────────────────── agent-scrip purge (session-aware, agent-only) ─────────────────────────
def test_purge_is_session_aware_and_agent_only(temp_state):
    uid = temp_state(90003, {
        "last_reset_date": __import__("datetime").date.today().isoformat(),  # same-day: no reset
        "active_symbols": ["NSE:NIFTY50-INDEX", "NSE:USERPICK-EQ",
                           "NSE:AGENTSTK-EQ", "MCX:AGENTCRUDE26JULFUT"],
        "enabled_symbols": ["NSE:NIFTY50-INDEX", "NSE:USERPICK-EQ",
                            "NSE:AGENTSTK-EQ", "MCX:AGENTCRUDE26JULFUT"],
        "agent_added_symbols": ["NSE:AGENTSTK-EQ", "MCX:AGENTCRUDE26JULFUT"],
    })
    st = TradingState(user_id=uid)
    st.save = lambda: None

    removed = st.purge_agent_symbols(only="equity")   # 15:30 equity cleanup
    assert removed == ["NSE:AGENTSTK-EQ"]
    assert "MCX:AGENTCRUDE26JULFUT" in st.active_symbols, "equity purge wrongly touched MCX"
    assert "NSE:USERPICK-EQ" in st.active_symbols, "purge wrongly removed a USER scrip"

    removed_mcx = st.purge_agent_symbols(only="mcx")   # 23:45 MCX cleanup
    assert removed_mcx == ["MCX:AGENTCRUDE26JULFUT"]
    assert st.active_symbols == ["NSE:NIFTY50-INDEX", "NSE:USERPICK-EQ"]


# ───────────────────────── hard-exit backward-compat invariant ─────────────────────────
def _would_disable_automation(active_symbols, already_closed, firing_session):
    """Pure replica of app.py daily_hard_exit_scheduler's 'other_open' rule, kept in lockstep:
    disable automation only when NO active symbol remains in a still-open session."""
    csd = list(already_closed)
    if firing_session not in csd:
        csd.append(firing_session)
    csd_set = set(csd)
    return not any(session_key_for_symbol(s) not in csd_set for s in active_symbols)

def test_hard_exit_nse_only_disables_like_legacy():
    # NSE-only account at 15:14 -> automation disabled (byte-for-byte legacy behaviour)
    assert _would_disable_automation(["NSE:NIFTY50-INDEX", "NSE:SBIN-EQ"], [], "NSE") is True

def test_hard_exit_mcx_account_keeps_trading_after_nse_close():
    # account holding crude at 15:14 -> NOT disabled, so crude trades into the evening
    assert _would_disable_automation(["NSE:SBIN-EQ", "MCX:CRUDEOIL26JULFUT"], [], "NSE") is False

def test_hard_exit_mcx_account_stops_at_mcx_close():
    # same account at 23:20 (NSE already closed earlier today) -> now disabled (end of day)
    assert _would_disable_automation(["NSE:SBIN-EQ", "MCX:CRUDEOIL26JULFUT"], ["NSE"], "MCX") is True


# ───────── Strategy 1 vs 10 vs 11 name-collision (28-08-26 fix) ─────────
# Bug locked in here: `str(strategy).startswith("Strategy 1")` also matched "Strategy 10"
# and "Strategy 11", so those three strategies silently cross-blocked each other at all
# THREE call sites in automation.py — has_active_trade_for_strategy(), can_trade()'s
# Strategy-1 daily cap, and add_active_trade()'s strat_1_trades_today counter.

S1 = "Strategy 1: OB + FVG"
S10 = "Strategy 10: Adaptive ADX Engine"
S11 = "Strategy 11: FRVP LVN Vacuum"


def _state_with_active(strategy_names):
    """Real (un-stubbed) has_active_trade_for_strategy over the given active trades."""
    st = make_state(active_auto_trades=[{"strategy": s} for s in strategy_names])
    del st.has_active_trade_for_strategy   # drop the make_state stub, use the real method
    return st


# --- call site 1: has_active_trade_for_strategy() ---
@pytest.mark.parametrize("active,asked", [
    ([S10], S1), ([S11], S1),          # S10/S11 running must not block S1
    ([S1], S10), ([S1], S11),          # S1 running must not block S10/S11
    ([S10], S11), ([S11], S10),        # S10 and S11 must not block each other
])
def test_active_trade_does_not_cross_block(active, asked):
    assert _state_with_active(active).has_active_trade_for_strategy(asked) is False


@pytest.mark.parametrize("strategy", [S1, S10, S11])
def test_active_trade_still_blocks_same_strategy(strategy):
    """The genuine guard must survive the exact-match change."""
    assert _state_with_active([strategy]).has_active_trade_for_strategy(strategy) is True


def test_active_trade_matches_bare_id_form():
    """A tracked "Strategy 1" (no suffix) must still match "Strategy 1: OB + FVG"."""
    assert _state_with_active(["Strategy 1"]).has_active_trade_for_strategy(S1) is True
    assert _state_with_active([S1]).has_active_trade_for_strategy("Strategy 1") is True


# --- call site 2: can_trade() Strategy-1 daily cap ---
@pytest.mark.parametrize("strategy", [S10, S11])
def test_can_trade_s1_cap_does_not_block_s10_s11(strategy):
    st = make_state(strat_1_trades_today=99)   # S1 cap maxed out
    ok, reason = st.can_trade(strategy, signal_type="CALL", symbol="NSE:NIFTY50-INDEX")
    assert ok is True, f"{strategy} wrongly blocked by Strategy-1 cap: {reason}"


def test_can_trade_s1_cap_still_blocks_s1():
    st = make_state(strat_1_trades_today=2)
    ok, reason = st.can_trade(S1, signal_type="CALL", symbol="NSE:NIFTY50-INDEX")
    assert ok is False and "Strategy 1 daily cap" in reason


# --- call site 3: add_active_trade() Strategy-1 counter increment ---
def _add_trade(monkeypatch, strategy):
    import engine.automation as _auto
    monkeypatch.setattr(_auto, "trigger_webhook_background", lambda *a, **k: None)
    st = make_state(webhook_url="", strat_1_trades_today=0)
    st.save = lambda: None
    st.add_active_trade("NSE:NIFTY50-INDEX", 100.0, 5.0, "BUY", "sl1", "tg1",
                        strategy=strategy)
    return st


@pytest.mark.parametrize("strategy", [S10, S11])
def test_add_active_trade_does_not_increment_s1_counter(monkeypatch, strategy):
    assert _add_trade(monkeypatch, strategy).strat_1_trades_today == 0


def test_add_active_trade_increments_s1_counter_for_s1(monkeypatch):
    assert _add_trade(monkeypatch, S1).strat_1_trades_today == 1
