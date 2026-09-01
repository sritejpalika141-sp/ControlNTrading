"""Phase 15 tests for engine/risk_orchestrator.py — strategy-name mismatch fix.

Covers:
  * _get_agent_config() resolves the real DB row for every previously-mismatched strategy
    (1-9) now that auto_trader.py passes the FULL descriptive name.
  * the exact-match-on-split retry does NOT collide "Strategy 1" with "Strategy 10"/"Strategy 11"
    (the bug class automation.py's has_active_trade_for_strategy() was hardened against 28-08-26).
  * the fallback branch logs a warning and still returns the safe zeroed default.
  * flush_signals()'s daily-cap side effects (strat_orb_triggered / strat_4_trades /
    strat_6_trades_today) still fire after the Strategy 3/4/6 call sites switched to full names.
"""
import logging

import pytest

import engine.risk_orchestrator as ro
from engine.risk_orchestrator import RiskOrchestrator


# models.py `default_strats` seeding — kept byte-identical on purpose.
SEEDED = [
    "Strategy 1: OB + FVG",
    "Strategy 2: 9:26 - 180 Buy",
    "Strategy 3: 5-Minute ORB",
    "Strategy 4: Wisdom-Aligned Pullback",
    "Strategy 5: Optimized Aerospace Mean Reversion",
    "Strategy 6: Gap Fill Reversal",
    "Strategy 7: Swing-Pivot Breakout",
    "Strategy 8: Smart Money Concepts",
    "Strategy 9: 9-EMA Momentum Scalper",
]
# Strategy 10/11 have no bootstrap seed row; they are upserted by nightly learning.
EXTRA = ["Strategy 10: Adaptive ADX Engine", "Strategy 11: FRVP LVN Vacuum"]


def _fake_rows():
    """One swarm_agent_configs row per strategy, each with a distinct win_rate."""
    rows = []
    for idx, name in enumerate(SEEDED + EXTRA, start=1):
        rows.append(
            {
                "strategy_name": name,
                "win_rate": 50.0 + idx,          # distinct, non-zero, non-default
                "total_trades": 10 + idx,        # >= 5 so the grace period does not mask it
                "config_json": {},
            }
        )
    return rows


@pytest.fixture
def db(monkeypatch):
    """Stub Database so no real sqlite file is touched."""
    rows = _fake_rows()
    by_name = {r["strategy_name"]: r for r in rows}

    async def _get_agent_config(strategy_name):
        row = by_name.get(strategy_name)
        return dict(row) if row else None

    async def _get_all_agent_configs():
        return [dict(r) for r in rows]

    monkeypatch.setattr(ro.Database, "get_agent_config", staticmethod(_get_agent_config))
    monkeypatch.setattr(ro.Database, "get_all_agent_configs", staticmethod(_get_all_agent_configs))
    return by_name


# ── the actual mismatch fix: full names resolve to their real DB rows ──────────
@pytest.mark.parametrize("full_name", SEEDED)
async def test_full_name_resolves_real_db_row(db, full_name):
    cfg = await RiskOrchestrator()._get_agent_config(full_name)
    assert cfg["win_rate"] == db[full_name]["win_rate"]
    assert cfg["total_trades"] == db[full_name]["total_trades"]
    # NOT the zeroed default that the pre-fix mismatch always produced.
    assert cfg["win_rate"] != 0.0
    assert cfg["total_trades"] != 0


# ── defensive hardening: a short name still resolves, via exact-match-on-split ──
@pytest.mark.parametrize(
    "short_name,full_name",
    [(n.split(":")[0].strip(), n) for n in SEEDED],
)
async def test_short_name_resolves_via_split_retry(db, short_name, full_name):
    cfg = await RiskOrchestrator()._get_agent_config(short_name)
    assert cfg["strategy_name"] == full_name
    assert cfg["win_rate"] == db[full_name]["win_rate"]


# ── collision regression: "Strategy 1" must never resolve to 10 or 11 ─────────
async def test_strategy_1_does_not_collide_with_10_or_11(db):
    cfg = await RiskOrchestrator()._get_agent_config("Strategy 1")
    assert cfg["strategy_name"] == "Strategy 1: OB + FVG"


async def test_strategy_10_and_11_resolve_to_themselves(db):
    orch = RiskOrchestrator()
    cfg10 = await orch._get_agent_config("Strategy 10")
    assert cfg10["strategy_name"] == "Strategy 10: Adaptive ADX Engine"
    cfg11 = await orch._get_agent_config("Strategy 11")
    assert cfg11["strategy_name"] == "Strategy 11: FRVP LVN Vacuum"


async def test_split_retry_is_not_a_prefix_match(db):
    """Regression guard: the retry must be exact-equality on the split ID, never startswith.

    Remove the Strategy 1 row entirely — a startswith/substring implementation would then
    happily hand back Strategy 10 or 11. The correct implementation must fall through to
    the zeroed default instead.
    """
    async def _none(strategy_name):
        return None

    async def _only_10_11():
        return [
            {"strategy_name": "Strategy 10: Adaptive ADX Engine", "win_rate": 77.0, "total_trades": 20},
            {"strategy_name": "Strategy 11: FRVP LVN Vacuum", "win_rate": 88.0, "total_trades": 20},
        ]

    ro.Database.get_agent_config = staticmethod(_none)
    ro.Database.get_all_agent_configs = staticmethod(_only_10_11)

    cfg = await RiskOrchestrator()._get_agent_config("Strategy 1")
    assert cfg["win_rate"] == 0.0
    assert cfg["total_trades"] == 0
    assert "strategy_name" not in cfg


# ── fallback branch: warns, and still returns the safe zeroed default ─────────
async def test_unknown_strategy_warns_and_returns_zeroed_default(db, caplog):
    with caplog.at_level(logging.WARNING, logger="DASHBOARD"):
        cfg = await RiskOrchestrator()._get_agent_config("Strategy 99")
    assert cfg["win_rate"] == 0.0
    assert cfg["total_trades"] == 0
    assert any(
        "No agent config found for strategy" in rec.message and "Strategy 99" in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )


async def test_known_strategy_does_not_warn(db, caplog):
    with caplog.at_level(logging.WARNING, logger="DASHBOARD"):
        await RiskOrchestrator()._get_agent_config("Strategy 4: Wisdom-Aligned Pullback")
    assert not [r for r in caplog.records if "No agent config found" in r.message]


# ── flush_signals daily-cap regression (the Phase-15 PVL cycle-1 blocking gap) ──
class _FakeState:
    def __init__(self):
        self.saves = 0

    def save(self):
        self.saves += 1


class _FakeClient:
    def __init__(self, user_id=1):
        self.user_id = user_id


@pytest.fixture
def no_exec(monkeypatch):
    """Stub out real order execution; record what flush_signals tried to execute."""
    import workers.auto_trader as at

    executed = []

    async def _fake_execute(symbol, sig, analysis, client):
        executed.append(sig["strategy_name"])

    monkeypatch.setattr(at, "execute_auto_trade", _fake_execute)

    # Neutral regime so propose_trade's CHOPPY_SIDEWAYS confidence override never trips.
    import state as _state_mod
    monkeypatch.setattr(_state_mod, "market_regime", "TRENDING", raising=False)
    return executed


async def _run_one(orch, name, state, client):
    await orch.propose_trade(name, "NSE:NIFTY50-INDEX", {"confidence": 99}, {"trend": "NEUTRAL"}, client, state)
    await orch.flush_signals(client.user_id)


async def test_flush_signals_sets_strat_orb_triggered_for_strategy_3(db, no_exec):
    orch, state, client = RiskOrchestrator(), _FakeState(), _FakeClient()
    await _run_one(orch, "Strategy 3: 5-Minute ORB", state, client)
    assert no_exec == ["Strategy 3: 5-Minute ORB"]
    assert state.strat_orb_triggered is True
    assert state.saves == 1


async def test_flush_signals_increments_strat_4_trades_to_two(db, no_exec):
    orch, state, client = RiskOrchestrator(), _FakeState(), _FakeClient()
    for _ in range(2):
        await _run_one(orch, "Strategy 4: Wisdom-Aligned Pullback", state, client)
    assert state.strat_4_trades == 2
    assert state.saves == 2


async def test_flush_signals_increments_strat_6_trades_today_to_two(db, no_exec):
    orch, state, client = RiskOrchestrator(), _FakeState(), _FakeClient()
    for _ in range(2):
        await _run_one(orch, "Strategy 6: Gap Fill Reversal", state, client)
    assert state.strat_6_trades_today == 2
    assert state.saves == 2


async def test_flush_signals_short_names_no_longer_drive_caps(db, no_exec):
    """The pre-fix SHORT strings must not be what the cap checks key on any more.

    This asserts the literals were actually migrated (not left compare-both-ways), so the
    checks stay pinned to exactly what auto_trader.py passes today.
    """
    orch, state, client = RiskOrchestrator(), _FakeState(), _FakeClient()
    await _run_one(orch, "Strategy 3", state, client)
    assert not getattr(state, "strat_orb_triggered", False)
    assert state.saves == 0
