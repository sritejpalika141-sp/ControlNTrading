"""
Unit tests for Phase 1 Item C (admin credentials + login rate-limiting).

- item-3-admin-hardcode: init_db() on an empty DB with no INITIAL_ADMIN_PASSWORD creates ZERO admin rows.
- item-3-rate-limit: 5 failed attempts within the window locks the 6th.

Run: cd trading-app && ./.venv/bin/python -m pytest tests/test_admin_and_ratelimit.py -q
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
import auth_utils  # noqa: E402


def _count_admins(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
        return cur.fetchone()[0]
    finally:
        conn.close()


def test_no_admin_created_without_env(monkeypatch, tmp_path):
    db_path = str(tmp_path / "empty1.db")
    monkeypatch.setattr(models.Database, "DB_NAME", db_path)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
    models.Database.init_db()
    assert _count_admins(db_path) == 0


def test_admin_created_with_env(monkeypatch, tmp_path):
    db_path = str(tmp_path / "empty2.db")
    monkeypatch.setattr(models.Database, "DB_NAME", db_path)
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "a-strong-password-123")
    models.Database.init_db()
    assert _count_admins(db_path) == 1


def test_no_hardcoded_admin123_anywhere():
    # Belt-and-suspenders: the literal weak credential must not appear in models.py.
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models.py")) as f:
        assert "admin123" not in f.read()


def test_rate_limit_locks_after_five_failures():
    username = "victim@example.com"
    auth_utils.reset_login_attempts(username)
    now = 1000.0
    for i in range(5):
        assert auth_utils.check_login_locked(username, now=now + i) is False
        auth_utils.register_failed_login(username, now=now + i)
    # 6th check: locked.
    assert auth_utils.check_login_locked(username, now=now + 5) is True


def test_rate_limit_window_expiry():
    username = "expiry@example.com"
    auth_utils.reset_login_attempts(username)
    now = 2000.0
    for i in range(5):
        auth_utils.register_failed_login(username, now=now + i)
    assert auth_utils.check_login_locked(username, now=now + 5) is True
    # After the window fully passes, the lock clears.
    later = now + auth_utils.LOGIN_LOCKOUT_WINDOW_SECONDS + 10
    assert auth_utils.check_login_locked(username, now=later) is False


def test_rate_limit_reset_on_success():
    username = "reset@example.com"
    auth_utils.reset_login_attempts(username)
    now = 3000.0
    for i in range(5):
        auth_utils.register_failed_login(username, now=now + i)
    assert auth_utils.check_login_locked(username, now=now + 5) is True
    auth_utils.reset_login_attempts(username)
    assert auth_utils.check_login_locked(username, now=now + 5) is False
