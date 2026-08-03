"""Regression: /fyers/auth must not 500 (Internal Error) when Connect Fyers is clicked.

Root cause fixed: endpoint called non-existent Database.get_master_fyers_creds().
Also covers HTTPS-aware oauth_verifier Secure cookie (HTTP :8000 must still set cookie).
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_utils  # noqa: E402
from auth_utils import generate_oauth_state, consume_oauth_state  # noqa: E402


class _FakeUrl:
    def __init__(self, scheme="http"):
        self.scheme = scheme


class _FakeRequest:
    def __init__(self, scheme="http", cookies=None, headers=None):
        self.url = _FakeUrl(scheme)
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_oauth_verifier_cookie_not_secure_on_http():
    resp = Response()
    state = generate_oauth_state(1, response=resp, request=_FakeRequest(scheme="http"))
    assert state
    set_cookie = resp.headers.get("set-cookie", "")
    assert "oauth_verifier=" in set_cookie
    # Starlette omits Secure attribute when secure=False
    assert "Secure" not in set_cookie


def test_oauth_verifier_cookie_secure_on_https():
    resp = Response()
    state = generate_oauth_state(1, response=resp, request=_FakeRequest(scheme="https"))
    assert state
    set_cookie = resp.headers.get("set-cookie", "")
    assert "oauth_verifier=" in set_cookie
    assert "Secure" in set_cookie


def test_oauth_verifier_cookie_secure_via_forwarded_proto():
    resp = Response()
    req = _FakeRequest(scheme="http", headers={"x-forwarded-proto": "https"})
    generate_oauth_state(1, response=resp, request=req)
    assert "Secure" in resp.headers.get("set-cookie", "")


def test_consume_oauth_state_requires_matching_verifier_cookie():
    resp = Response()
    state = generate_oauth_state(42, response=resp, request=_FakeRequest(scheme="http"))
    raw = resp.headers.get("set-cookie", "")
    cookie_val = raw.split("oauth_verifier=", 1)[1].split(";", 1)[0]
    req = _FakeRequest(scheme="http", cookies={"oauth_verifier": cookie_val})
    assert consume_oauth_state(state, request=req) == 42

    # Fresh state + missing cookie → reject (not a replay of the previous nonce)
    resp2 = Response()
    state2 = generate_oauth_state(42, response=resp2, request=_FakeRequest(scheme="http"))
    assert consume_oauth_state(state2, request=_FakeRequest(scheme="http")) is None


def test_get_master_fyers_creds_does_not_exist():
    """Guardrail: the broken method name must never reappear on Database."""
    from models import Database
    assert not hasattr(Database, "get_master_fyers_creds")
    assert hasattr(Database, "get_master_app_credentials")
    assert hasattr(Database, "get_master_app_credentials_sync")


@pytest.mark.asyncio
async def test_fyers_auth_redirect_uses_master_app_credentials():
    """/fyers/auth must resolve creds via get_master_app_credentials, not a missing method."""
    import types
    import app as app_module

    fake_user = {"id": 1, "fyers_client_id": "", "fyers_secret": ""}

    class _Session:
        def __init__(self, **kwargs):
            pass

        def generate_authcode(self):
            return "https://api.fyers.in/api/v2/generate-authcode?client_id=ABC&state=None"

    fyers_model = types.ModuleType("fyers_apiv3.fyersModel")
    fyers_model.SessionModel = _Session
    fyers_pkg = types.ModuleType("fyers_apiv3")
    fyers_pkg.fyersModel = fyers_model

    with patch.object(app_module, "resolve_authenticated_user_id", AsyncMock(return_value=1)), \
         patch.object(app_module.Database, "get_user_by_id", AsyncMock(return_value=fake_user)), \
         patch.object(app_module.Database, "get_master_app_credentials", AsyncMock(return_value=("ABC-100", "secret"))), \
         patch.dict(sys.modules, {"fyers_apiv3": fyers_pkg, "fyers_apiv3.fyersModel": fyers_model}):
        req = MagicMock()
        req.url.scheme = "http"
        req.headers = {}
        req.cookies = {}
        result = await app_module.fyers_auth_redirect(req)

    assert result.status_code in (302, 307)
    loc = result.headers.get("location", "")
    assert "generate-authcode" in loc
    assert "state=None" not in loc
    set_cookie = result.headers.get("set-cookie", "")
    assert "oauth_verifier=" in set_cookie
    assert "Secure" not in set_cookie


@pytest.mark.asyncio
async def test_fyers_auth_redirect_never_500_on_cred_failure():
    import app as app_module

    with patch.object(app_module, "resolve_authenticated_user_id", AsyncMock(return_value=1)), \
         patch.object(app_module.Database, "get_user_by_id", AsyncMock(side_effect=RuntimeError("db down"))):
        req = MagicMock()
        req.url.scheme = "http"
        req.headers = {}
        result = await app_module.fyers_auth_redirect(req)

    assert result.status_code in (302, 307)
    assert "Fyers+connect+failed" in result.headers.get("location", "")
