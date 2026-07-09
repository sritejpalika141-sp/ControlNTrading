"""Phase 2 tests for workers/health_agent.py — item D6 (exact-token allowlist + user-scoped
execute_fix)."""
import pytest

import workers.health_agent as ha


# ── D6: exact-token match only — a sentence merely containing a token must NOT fire it ──
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("restart_ws", "restart_ws"),
        ("Restart_WS", "restart_ws"),
        ("  relogin.\n", "relogin"),
        ("`clear_cache`", "clear_cache"),
        ("wait", "wait"),
        ("You should definitely NOT restart_ws right now", "wait"),  # substring-only -> rejected
        ("please restart_ws asap", "wait"),
        ("", "wait"),
        (None, "wait"),
        ("delete_database", "wait"),
    ],
)
def test_match_fix_action_exact_token_only(raw, expected):
    assert ha._match_fix_action(raw) == expected


# ── D6: execute_fix hard-rejects anything outside the allow-list, even if it slips through ──
@pytest.mark.asyncio
async def test_execute_fix_rejects_non_allowlisted_action(monkeypatch):
    called = []
    monkeypatch.setattr(ha, "USER_CONTEXTS", {}, raising=True)
    # Should simply log-and-return; must not attempt to touch USER_CONTEXTS/ws_feed at all.
    monkeypatch.setattr(ha, "ws_feed", None, raising=True)
    await ha.execute_fix("drop_database", u_id=None)  # must not raise


# ── D6: restart_ws/relogin scope to the originating user when one is known ─────────
@pytest.mark.asyncio
async def test_execute_fix_scopes_restart_ws_to_originating_user(monkeypatch):
    touched = []

    class _FakeClient:
        def __init__(self, uid):
            self.user_id = uid

    fake_contexts = {1: _FakeClient(1), 2: _FakeClient(2)}
    fake_caches = {"1": {"is_auth": True}, "2": {"is_auth": True}}

    class _FakeWsFeed:
        def restart(self, client):
            touched.append(client.user_id)

    monkeypatch.setattr(ha, "USER_CONTEXTS", fake_contexts, raising=True)
    monkeypatch.setattr(ha, "USER_CACHES", fake_caches, raising=True)
    monkeypatch.setattr(ha, "ws_feed", _FakeWsFeed(), raising=True)

    await ha.execute_fix("restart_ws", u_id=1)

    assert touched == [1]  # only the originating user, not user 2


@pytest.mark.asyncio
async def test_execute_fix_falls_back_to_all_users_when_origin_unknown(monkeypatch):
    touched = []

    class _FakeClient:
        def __init__(self, uid):
            self.user_id = uid

    fake_contexts = {1: _FakeClient(1), 2: _FakeClient(2)}
    fake_caches = {"1": {"is_auth": True}, "2": {"is_auth": True}}

    class _FakeWsFeed:
        def restart(self, client):
            touched.append(client.user_id)

    monkeypatch.setattr(ha, "USER_CONTEXTS", fake_contexts, raising=True)
    monkeypatch.setattr(ha, "USER_CACHES", fake_caches, raising=True)
    monkeypatch.setattr(ha, "ws_feed", _FakeWsFeed(), raising=True)

    await ha.execute_fix("restart_ws", u_id=None)  # genuinely global error -> no origin

    assert set(touched) == {1, 2}
