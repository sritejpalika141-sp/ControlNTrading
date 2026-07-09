#!/usr/bin/env python3
"""
One-time credential re-encryption migration (Phase 1 Item G1).

Rotates the Fernet ENCRYPTION_KEY: decrypts every stored Fyers credential with the OLD key
and re-encrypts it with the NEW key, so the exposed old key can be retired.

USAGE (run with the app stopped, or against a DB copy):

    export ENCRYPTION_KEY_OLD="<the current/old Fernet key>"
    export ENCRYPTION_KEY="<the newly generated Fernet key>"
    python scripts/migrate_reencrypt_credentials.py            # migrate the live DB
    python scripts/migrate_reencrypt_credentials.py --db /path/to/copy.db   # dry-run target

Safety:
  - Takes an automatic pre-migration backup (<db>.pre-migration-backup) before writing.
  - Writes all rows in a single transaction (all-or-nothing).
  - After running, verify one credential decrypts with the NEW key, then confirm
    `grep -c '^ENCRYPTION_KEY=' .env` == 1 BEFORE restarting the app (get_cipher() will
    silently generate + persist a fresh key if ENCRYPTION_KEY is missing at process start,
    which would orphan every credential you just migrated).

Backwards-compat: if a value fails to decrypt with the OLD key it is treated as plaintext
(mirrors models.decrypt_val), so already-plaintext values are simply encrypted with the NEW key.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

CRED_COLUMNS = [
    "fyers_client_id",
    "fyers_secret",
    "fyers_access_token",
    "fyers_refresh_token",
    "fyers_pin",
]

DEFAULT_DB = str(Path(__file__).resolve().parent.parent / "trading_app.db")


def _old_decrypt(fernet_old, value):
    """Decrypt with the OLD key; fall back to treating the value as plaintext."""
    if not value:
        return value
    try:
        return fernet_old.decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        return value  # already plaintext / not old-key ciphertext


def main():
    parser = argparse.ArgumentParser(description="Re-encrypt Fyers credentials with a rotated key.")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite DB (default: trading_app.db)")
    parser.add_argument("--no-backup", action="store_true", help="Skip the automatic pre-migration backup")
    args = parser.parse_args()

    old_key = os.getenv("ENCRYPTION_KEY_OLD")
    new_key = os.getenv("ENCRYPTION_KEY")
    if not old_key:
        print("❌ ENCRYPTION_KEY_OLD is not set. Set it to the current/old Fernet key and retry.")
        sys.exit(1)
    if not new_key:
        print("❌ ENCRYPTION_KEY (the new key) is not set. Set it and retry.")
        sys.exit(1)
    if old_key == new_key:
        print("❌ ENCRYPTION_KEY_OLD and ENCRYPTION_KEY are identical — nothing to rotate.")
        sys.exit(1)
    if not os.path.exists(args.db):
        print(f"❌ DB not found: {args.db}")
        sys.exit(1)

    try:
        fernet_old = Fernet(old_key.encode("utf-8"))
        fernet_new = Fernet(new_key.encode("utf-8"))
    except Exception as e:
        print(f"❌ Invalid Fernet key(s): {e}")
        sys.exit(1)

    if not args.no_backup:
        backup_path = f"{args.db}.pre-migration-backup"
        shutil.copy2(args.db, backup_path)
        print(f"🧾 Pre-migration backup written: {backup_path}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        where = " OR ".join(f"{col} IS NOT NULL AND {col} != ''" for col in CRED_COLUMNS)
        c.execute(f"SELECT id, {', '.join(CRED_COLUMNS)} FROM users WHERE {where}")
        rows = c.fetchall()
        print(f"🔍 {len(rows)} user row(s) with credentials to re-encrypt.")

        updated = 0
        for row in rows:
            updates = {}
            for col in CRED_COLUMNS:
                val = row[col]
                if not val:
                    continue
                plaintext = _old_decrypt(fernet_old, val)
                if plaintext:
                    updates[col] = fernet_new.encrypt(plaintext.encode("utf-8")).decode("utf-8")
            if updates:
                set_clause = ", ".join(f"{col} = ?" for col in updates)
                c.execute(
                    f"UPDATE users SET {set_clause} WHERE id = ?",
                    (*updates.values(), row["id"]),
                )
                updated += 1

        conn.commit()  # single transaction — all rows or none
        print(f"✅ Re-encrypted credentials for {updated} user(s) with the NEW key.")
        print("👉 Next: verify one user's fyers_access_token decrypts with the NEW key, then")
        print("   confirm `grep -c '^ENCRYPTION_KEY=' .env` == 1 BEFORE restarting the app.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed and was rolled back: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
