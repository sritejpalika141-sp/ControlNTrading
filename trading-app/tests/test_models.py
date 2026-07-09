"""Phase 2 tests for models.py — items D1 (decrypt_val) and D5 (cascade delete)."""
import os
import sqlite3

import pytest

import models
from models import decrypt_val, encrypt_val, DecryptionError, Database


# ── D1: decrypt_val must fail loud on genuine ciphertext failure ───────────────
def test_decrypt_val_failure_signal():
    token = encrypt_val("super-secret-token")
    assert token != "super-secret-token"  # was actually encrypted

    # Corrupt the payload while keeping a valid-looking Fernet token prefix.
    corrupted = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(DecryptionError):
        decrypt_val(corrupted)


def test_decrypt_val_legacy_plaintext_passthrough():
    # A value that was never encrypted (legacy plaintext) is returned as-is, not raised on.
    assert decrypt_val("plainapikey123") == "plainapikey123"


def test_decrypt_val_roundtrip_ok():
    assert decrypt_val(encrypt_val("hello")) == "hello"


# ── D5: deleting a user removes every dependent-table row ──────────────────────
def test_user_delete_cascade(tmp_path, monkeypatch):
    db_file = str(tmp_path / "cascade_test.db")
    monkeypatch.setattr(Database, "DB_NAME", db_file, raising=True)

    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    c.execute("CREATE TABLE user_states (user_id INTEGER)")
    c.execute("CREATE TABLE daily_pnl_history (user_id INTEGER)")
    c.execute("CREATE TABLE paper_pnl_history (user_id INTEGER)")
    c.execute("CREATE TABLE system_logs (user_id INTEGER)")
    uid = 42
    c.execute("INSERT INTO users (id, username) VALUES (?, ?)", (uid, "victim"))
    c.execute("INSERT INTO users (id, username) VALUES (?, ?)", (99, "bystander"))
    for table in Database.USER_SCOPED_TABLES:
        c.execute(f"INSERT INTO {table} (user_id) VALUES (?)", (uid,))
        c.execute(f"INSERT INTO {table} (user_id) VALUES (?)", (99,))  # unrelated user
    conn.commit()
    conn.close()

    Database.delete_user_cascade(uid)

    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    # No rows for the deleted user anywhere.
    c.execute("SELECT COUNT(*) FROM users WHERE id=?", (uid,))
    assert c.fetchone()[0] == 0
    for table in Database.USER_SCOPED_TABLES:
        c.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (uid,))
        assert c.fetchone()[0] == 0, f"orphaned rows left in {table}"
    # The unrelated user's rows are untouched.
    c.execute("SELECT COUNT(*) FROM users WHERE id=99")
    assert c.fetchone()[0] == 1
    for table in Database.USER_SCOPED_TABLES:
        c.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=99")
        assert c.fetchone()[0] == 1, f"wrongly deleted bystander rows in {table}"
    conn.close()
