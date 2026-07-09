"""
Unit tests for session cookie signing + grace-period verification (Phase 1, Item 1).

Proves: forged raw `user_id` cookie is rejected post-grace-period; valid signed cookie is
accepted; legacy raw digit is honored during the grace window and rejected after it.

Run: cd trading-app && ./.venv/bin/python -m pytest tests/test_auth_cookie.py -q
"""
import os
import sys
from datetime import datetime, timedelta

# Deterministic secret so signatures are reproducible in the test process.
os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_utils  # noqa: E402
from auth_utils import sign_user_id, resolve_user_id_from_cookie  # noqa: E402

BEFORE_CUTOFF = auth_utils.SESSION_MIGRATION_CUTOFF - timedelta(days=1)
AFTER_CUTOFF = auth_utils.SESSION_MIGRATION_CUTOFF + timedelta(days=1)


def test_valid_signed_cookie_accepted():
    token = sign_user_id(17)
    assert resolve_user_id_from_cookie(token, now=AFTER_CUTOFF) == 17


def test_forged_raw_cookie_rejected_after_grace():
    # Raw integer forgery must be rejected once the grace window closes.
    assert resolve_user_id_from_cookie("1", now=AFTER_CUTOFF) is None
    assert resolve_user_id_from_cookie("9999", now=AFTER_CUTOFF) is None


def test_legacy_raw_cookie_accepted_within_grace():
    # During the grace window, a legacy raw-int cookie is still honored.
    assert resolve_user_id_from_cookie("17", now=BEFORE_CUTOFF) == 17


def test_tampered_signed_cookie_rejected():
    token = sign_user_id(17)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert resolve_user_id_from_cookie(tampered, now=BEFORE_CUTOFF) is None
    assert resolve_user_id_from_cookie(tampered, now=AFTER_CUTOFF) is None


def test_garbage_cookie_rejected():
    assert resolve_user_id_from_cookie("not-a-token", now=BEFORE_CUTOFF) is None
    assert resolve_user_id_from_cookie("", now=BEFORE_CUTOFF) is None
    assert resolve_user_id_from_cookie(None, now=BEFORE_CUTOFF) is None


def test_signed_cookie_survives_grace_boundary_both_sides():
    # A properly signed cookie is valid regardless of the migration cutoff.
    token = sign_user_id(42)
    assert resolve_user_id_from_cookie(token, now=BEFORE_CUTOFF) == 42
    assert resolve_user_id_from_cookie(token, now=AFTER_CUTOFF) == 42
