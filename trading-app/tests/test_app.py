"""Phase 2 tests for app.py — items A1 (guest-fallback 401) and B4 (regime/duplicate-position
guard fail-closed rejection).

Importing `app` triggers real module-level init (DB table verification, AI-engine provider
init) exactly as production does on process start — this is the same tradeoff already accepted
by the pre-existing Phase 1 harness (`test_order_concurrency.py` imports `engine.automation`,
which pulls in similar module-level state). Tests use distinctive, high/non-numeric-looking
fake identities and clean up any global dict entries they create so they don't leak state into
other tests in the same session.
"""
import pytest
from fastapi import HTTPException

import app as app_module
import state
from engine.automation import TradingState


class _FakeRequest:
    """Minimal stand-in for fastapi.Request — get_current_client only reads .cookies."""

    def __init__(self, cookies=None):
        self.cookies = cookies or {}


def _cleanup_fake_user_state(fake_uid):
    """Remove the global in-memory entries a fake TradingState/FyersClient registers, so
    these tests don't leak state into other tests in the same session."""
    app_module.USER_CONTEXTS.pop(fake_uid, None)
    state.USER_STATES.pop(fake_uid, None)


# ── A1: guest/user-0 fallback is CLOSED by default on trading-critical endpoints ──
@pytest.mark.asyncio
async def test_guest_fallback_401_without_allow_guest():
    req = _FakeRequest()  # no user_id cookie at all
    with pytest.raises(HTTPException) as exc_info:
        await app_module.get_current_client(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_explicit_allow_guest_route_still_succeeds():
    req = _FakeRequest()
    try:
        client = await app_module.get_current_client(req, allow_guest=True)
        assert client is not None
        assert client.user_id == 0
    finally:
        app_module.USER_CONTEXTS.pop(0, None)


# ── A3: deactivating/deleting a user purges their in-memory runtime synchronously ──
def test_purge_user_runtime_removes_user_and_flips_automation_off():
    FAKE_UID = 987654323

    class _FakeState:
        automation_enabled = True
        hard_exit_triggered = False

    fake_state = _FakeState()
    app_module.USER_CONTEXTS[FAKE_UID] = object()
    state.USER_STATES[FAKE_UID] = fake_state
    try:
        state.purge_user_runtime(FAKE_UID)
        assert FAKE_UID not in app_module.USER_CONTEXTS
        assert FAKE_UID not in state.USER_STATES
        # The live TradingState reference (in case another loop tick already captured it)
        # must be flipped off before the dict entry is dropped.
        assert fake_state.automation_enabled is False
        assert fake_state.hard_exit_triggered is True
    finally:
        app_module.USER_CONTEXTS.pop(FAKE_UID, None)
        state.USER_STATES.pop(FAKE_UID, None)


def test_purge_user_runtime_is_idempotent_and_never_raises():
    # No entry exists for this id at all — must be a safe no-op, not an exception.
    state.purge_user_runtime(555555555)
    state.purge_user_runtime("not-an-int")


# ── B4: regime/duplicate-position guard fails closed with an explicit rejection ────
@pytest.mark.asyncio
async def test_regime_guard_fail_closed_rejects_when_no_confirmed_trend(monkeypatch):
    FAKE_UID = 987654321  # distinctive fake id, unlikely to collide with real users

    class _FakeClient:
        user_id = FAKE_UID

    async def _fake_get_current_client(request, allow_guest=False):
        return _FakeClient()

    monkeypatch.setattr(app_module, "get_current_client", _fake_get_current_client, raising=True)
    # NEUTRAL (the module default, and what regime_worker sets on every failure/fallback path)
    # is not a confirmed tradeable trend -> must fail closed with a structured rejection.
    monkeypatch.setattr(state, "market_regime", "NEUTRAL", raising=True)
    # TradingState.save() schedules a fire-and-forget asyncio task that writes
    # logs/trading_state_<uid>.json — no-op it so this fake-uid test never touches disk.
    monkeypatch.setattr(TradingState, "save", lambda self: None, raising=True)

    order = app_module.OrderRequest(symbol="NSE:BANKNIFTY25JUL50000CE", qty=15, side="BUY")
    try:
        result = await app_module.place_order(_FakeRequest(), order)
    finally:
        _cleanup_fake_user_state(FAKE_UID)

    assert result["success"] is False
    assert "regime" in result["message"].lower()


@pytest.mark.asyncio
async def test_regime_guard_allows_aligned_trade_on_confirmed_trend(monkeypatch):
    FAKE_UID = 987654322

    class _FakeClient:
        user_id = FAKE_UID

        def get_positions(self):
            return []

        def place_order(self, *a, **k):
            return {"success": True, "message": "mock order placed"}

    async def _fake_get_current_client(request, allow_guest=False):
        return _FakeClient()

    monkeypatch.setattr(app_module, "get_current_client", _fake_get_current_client, raising=True)
    monkeypatch.setattr(state, "market_regime", "TRENDING_UP", raising=True)
    monkeypatch.setattr(TradingState, "save", lambda self: None, raising=True)

    # TRENDING_UP + a CE (call) symbol is the aligned case -> must NOT be blocked by the guard.
    order = app_module.OrderRequest(symbol="NSE:BANKNIFTY25JUL50000CE", qty=15, side="BUY")
    try:
        result = await app_module.place_order(_FakeRequest(), order)
    finally:
        _cleanup_fake_user_state(FAKE_UID)

    # Not the regime-lockout rejection — the guard let it through to order placement.
    assert "regime" not in (result.get("message") or "").lower()
