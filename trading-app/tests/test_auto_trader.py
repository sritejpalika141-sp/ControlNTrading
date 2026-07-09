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
