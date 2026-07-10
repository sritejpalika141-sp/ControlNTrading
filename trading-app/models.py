import sqlite3
import aiosqlite
import os
import base64
import logging
import bcrypt
import pytz
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path

IST = pytz.timezone('Asia/Kolkata')

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """Raised (D1) when a value that IS an encrypted Fernet token fails to decrypt.

    Distinct from the legacy-plaintext backwards-compat path: a value that was never
    encrypted (plain string) is returned as-is, but a genuine ciphertext that cannot be
    decrypted (wrong key / corruption) must fail loudly rather than being handed back to
    callers as if it were a usable plaintext credential.
    """

# Load the trading-app/.env FIRST so ENCRYPTION_KEY persists across restarts
_MODELS_DIR = Path(__file__).resolve().parent
_MODELS_ENV_PATH = _MODELS_DIR / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(_MODELS_ENV_PATH)
except ImportError:
    pass  # dotenv not available, fall back to os.getenv

ENCRYPTION_KEY = None

def get_cipher():
    global ENCRYPTION_KEY
    if ENCRYPTION_KEY is None:
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            key = Fernet.generate_key().decode('utf-8')
            env_path = str(_MODELS_ENV_PATH)
            try:
                # Read existing content and update/add ENCRYPTION_KEY
                existing_lines = []
                if os.path.exists(env_path):
                    with open(env_path, 'r') as f:
                        existing_lines = f.readlines()
                
                # Replace existing ENCRYPTION_KEY line or append new one
                new_lines = []
                found = False
                for line in existing_lines:
                    if line.strip().startswith("ENCRYPTION_KEY="):
                        new_lines.append(f"ENCRYPTION_KEY={key}\n")
                        found = True
                    else:
                        new_lines.append(line)
                if not found:
                    new_lines.append(f"ENCRYPTION_KEY={key}\n")
                
                with open(env_path, 'w') as f:
                    f.writelines(new_lines)
                print(f"🔐 New ENCRYPTION_KEY generated and saved to {env_path}")
            except Exception as e:
                print(f"⚠️ Error writing ENCRYPTION_KEY to .env: {e}")
            os.environ["ENCRYPTION_KEY"] = key
        ENCRYPTION_KEY = key.encode('utf-8')
    return Fernet(ENCRYPTION_KEY)

def encrypt_val(val: str) -> str:
    if not val:
        return val
    try:
        cipher = get_cipher()
        return cipher.encrypt(val.encode('utf-8')).decode('utf-8')
    except Exception as e:
        print(f"⚠️ Encryption error: {e}")
        return val

def _looks_like_fernet_token(val: str) -> bool:
    """True if `val` structurally looks like a Fernet token (URL-safe base64 whose first
    decoded byte is the Fernet version marker 0x80). Used to tell an actually-encrypted value
    apart from legacy plaintext that was never encrypted."""
    try:
        raw = base64.urlsafe_b64decode(val.encode('utf-8'))
        return len(raw) >= 1 and raw[0] == 0x80
    except Exception:
        return False


def decrypt_val(val: str) -> str:
    if not val:
        return val
    try:
        cipher = get_cipher()
        return cipher.decrypt(val.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        # D1: distinguish two failure modes instead of silently returning the raw value:
        #  - the value LOOKS like a real Fernet token but won't decrypt (wrong key / corruption):
        #    fail LOUD — never hand ciphertext back as if it were a usable plaintext credential.
        #  - the value is legacy plaintext that was never encrypted: return it as-is (bounded
        #    backwards-compat), which is returning plaintext-as-plaintext, not ciphertext-as-plaintext.
        if _looks_like_fernet_token(val):
            logger.error("🔓 decrypt_val: value is an encrypted Fernet token but decryption FAILED "
                         "(wrong ENCRYPTION_KEY or corrupted ciphertext). Refusing to return ciphertext.")
            raise DecryptionError("Fernet token failed to decrypt")
        return val
    except Exception as e:
        # Unexpected error (not a decrypt-validity failure): log loudly, do not mask.
        logger.error(f"🔓 decrypt_val: unexpected error during decryption: {e}")
        raise DecryptionError(str(e))

def decrypt_user_dict(user: dict) -> dict:
    if not user:
        return user

    def _safe_decrypt_field(field: str) -> None:
        # D1 caller audit: on a genuine decryption failure, set the field to None (so downstream
        # sees "no credential" and re-auth is forced) instead of letting ciphertext be used as a
        # live credential. Legacy plaintext still round-trips normally.
        if field in user and user[field]:
            try:
                user[field] = decrypt_val(user[field])
            except DecryptionError:
                logger.error(f"🔓 decrypt_user_dict: '{field}' for user {user.get('id', '?')} "
                             f"failed to decrypt — blanking field (forces re-auth).")
                user[field] = None

    for _f in ("fyers_client_id", "fyers_secret", "fyers_access_token",
               "fyers_refresh_token", "fyers_pin"):
        _safe_decrypt_field(_f)
    return user


class Database:
    DB_NAME = "trading_app.db"

    @staticmethod
    def init_db():
        conn = sqlite3.connect(Database.DB_NAME)
        c = conn.cursor()
        
        # Users Table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            fyers_client_id TEXT,
            fyers_secret TEXT,
            fyers_access_token TEXT,
            fyers_refresh_token TEXT,
            fyers_pin TEXT,
            automation_enabled BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Global Kill Switch Table
        c.execute('''CREATE TABLE IF NOT EXISTS global_kill_switch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_active BOOLEAN DEFAULT 0,
            reason TEXT,
            engaged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Migration: add fyers_refresh_token column to existing DBs (SQLite ignores duplicate-column errors here)
        try:
            c.execute("ALTER TABLE users ADD COLUMN fyers_refresh_token TEXT")
            print("🆕 Migrated users table: added fyers_refresh_token column", flush=True)
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: add fyers_pin column to existing DBs
        try:
            c.execute("ALTER TABLE users ADD COLUMN fyers_pin TEXT")
            print("🆕 Migrated users table: added fyers_pin column", flush=True)
        except sqlite3.OperationalError:
            pass  # column already exists
        
        # Migration: add is_active column to existing DBs
        try:
            c.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1")
            print("🆕 Migrated users table: added is_active column", flush=True)
        except sqlite3.OperationalError:
            pass  # column already exists
        
        # User States (PnL, Limits, etc)
        c.execute('''CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            daily_profit REAL DEFAULT 0,
            daily_loss REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            is_conservative BOOLEAN DEFAULT 0,
            max_loss_per_day REAL DEFAULT -1000.0,
            max_trades_per_day INTEGER DEFAULT 5,
            webhook_url TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )''')

        # Migration: user_states created before these columns existed is missing them
        # (CREATE TABLE IF NOT EXISTS does NOT alter an existing table). Without this, nightly
        # learning crashes ("no such column: webhook_url") and the per-user risk limits fall back
        # to defaults. SQLite raises OperationalError on a duplicate column, which we ignore.
        for _col_sql in (
            "ALTER TABLE user_states ADD COLUMN max_loss_per_day REAL DEFAULT -1000.0",
            "ALTER TABLE user_states ADD COLUMN max_trades_per_day INTEGER DEFAULT 5",
            "ALTER TABLE user_states ADD COLUMN webhook_url TEXT DEFAULT ''",
        ):
            try:
                c.execute(_col_sql)
                print(f"🆕 Migrated user_states: {_col_sql.split('ADD COLUMN')[1].strip()}", flush=True)
            except sqlite3.OperationalError:
                pass  # column already exists

        # Daily PnL History Table (LIVE trades only)
        c.execute('''CREATE TABLE IF NOT EXISTS daily_pnl_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            pnl REAL NOT NULL,
            trades INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )''')

        # Paper PnL History Table (Paper trades only — separate from live)
        c.execute('''CREATE TABLE IF NOT EXISTS paper_pnl_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            pnl REAL NOT NULL,
            trades INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(user_id, date)
        )''')

        # System Logs Table
        c.execute('''CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )''')

        # Health Memory Table (Self-Healing)
        c.execute('''CREATE TABLE IF NOT EXISTS health_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            error_signature TEXT NOT NULL,
            diagnostics TEXT,
            applied_fix TEXT,
            success INTEGER DEFAULT 0
        )''')

        # Swarm Agent Trade Records (AgentDB Memory)
        c.execute('''CREATE TABLE IF NOT EXISTS swarm_trade_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            vix REAL,
            market_trend TEXT,
            chart_image_path TEXT
        )''')

        # Swarm Agent Configs (Dynamic Parameters & Win Rate)
        c.execute('''CREATE TABLE IF NOT EXISTS swarm_agent_configs (
            strategy_name TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            win_rate REAL DEFAULT 0.0,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            status TEXT DEFAULT 'APPROVED',
            pending_config_json TEXT,
            is_paper_trading BOOLEAN DEFAULT 1,
            continuous_losses INTEGER DEFAULT 0,
            asset_class TEXT DEFAULT 'EQUITY'
        )''')

        # Migration: add status and pending_config_json to existing swarm_agent_configs
        try:
            c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN status TEXT DEFAULT 'APPROVED'")
            c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN pending_config_json TEXT")
            print("🆕 Migrated swarm_agent_configs table: added status & pending_config_json columns", flush=True)
        except sqlite3.OperationalError:
            pass

        # Migration: add is_paper_trading, continuous_losses, asset_class
        try:
            c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN is_paper_trading BOOLEAN DEFAULT 1")
            c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN continuous_losses INTEGER DEFAULT 0")
            c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN asset_class TEXT DEFAULT 'EQUITY'")
            print("🆕 Migrated swarm_agent_configs table: added is_paper_trading, continuous_losses, asset_class columns", flush=True)
        except sqlite3.OperationalError:
            pass

        # Swarm Learning Logs (Post-Market LLM Analysis)
        c.execute('''CREATE TABLE IF NOT EXISTS swarm_learning_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            date TEXT NOT NULL,
            llm_analysis TEXT NOT NULL,
            old_config TEXT,
            new_config TEXT
        )''')

        # Cognitive Risk Orchestrator Memory
        c.execute('''CREATE TABLE IF NOT EXISTS orchestrator_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            winning_strategy TEXT NOT NULL,
            rejected_strategies TEXT NOT NULL,
            market_regime TEXT,
            pnl_winner REAL DEFAULT 0,
            pnl_losers TEXT
        )''')

        # First-run admin setup — NO hardcoded default credential (Phase 1 Item C1).
        # Only create the admin from an explicit INITIAL_ADMIN_PASSWORD env var; never fall
        # back to a guessable default. On the existing live DB this is a no-op (admin exists).
        c.execute("SELECT id FROM users WHERE username='admin'")
        if not c.fetchone():
            initial_admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
            if initial_admin_password:
                admin_pass = Database.hash_password(initial_admin_password)
                c.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                          ("admin", admin_pass, 1))
                print("✅ Initial admin user created from INITIAL_ADMIN_PASSWORD")
            else:
                print("⚠️ No admin user exists and INITIAL_ADMIN_PASSWORD is not set — set it in .env and restart")

        # Initialize Swarm Agents with 9 default strategies
        default_strats = [
            "Strategy 1: OB + FVG",
            "Strategy 2: 9:26 - 180 Buy",
            "Strategy 3: 5-Minute ORB",
            "Strategy 4: Wisdom-Aligned Pullback",
            "Strategy 5: Optimized Aerospace Mean Reversion",
            "Strategy 6: Gap Fill Reversal",
            "Strategy 7: Swing-Pivot Breakout",
            "Strategy 8: Smart Money Concepts",
            "Strategy 9: 9-EMA Momentum Scalper"
        ]
        import json, datetime
        for strat in default_strats:
            c.execute("SELECT strategy_name FROM swarm_agent_configs WHERE strategy_name=?", (strat,))
            if not c.fetchone():
                now_str = datetime.datetime.now().isoformat()
                c.execute("INSERT INTO swarm_agent_configs (strategy_name, config_json, last_updated) VALUES (?, ?, ?)",
                          (strat, json.dumps({}), now_str))

        conn.commit()
        conn.close()

    @staticmethod
    async def get_user_by_username(username):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE username=?", (username,)) as c:
                user = await c.fetchone()
        return decrypt_user_dict(dict(user)) if user else None

    @staticmethod
    def get_user_by_id_sync(user_id: int) -> Optional[Dict]:
        """Synchronous version for FyersClient initialization."""
        conn = sqlite3.connect(Database.DB_NAME)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return decrypt_user_dict(dict(row))
            return None
        finally:
            conn.close()

    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE id=?", (user_id,)) as c:
                user = await c.fetchone()
        return decrypt_user_dict(dict(user)) if user else None

    @staticmethod
    def verify_password(plain_password, hashed_password):
        try:
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception as e:
            print(f"⚠️ bcrypt.checkpw error: {e}")
            return False

    @staticmethod
    def hash_password(password):
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    @staticmethod
    async def create_user(username, password, is_admin=0):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            try:
                password_hash = Database.hash_password(password)
                cursor = await conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                          (username, password_hash, is_admin))
                user_id = cursor.lastrowid
                # Init state
                await conn.execute("INSERT INTO user_states (user_id) VALUES (?)", (user_id,))
                await conn.commit()
                return user_id
            except sqlite3.IntegrityError:
                return None

    @staticmethod
    async def get_all_automation_users():
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM users WHERE automation_enabled=1") as c:
                rows = await c.fetchall()
        return [decrypt_user_dict(dict(u)) for u in rows]

    @staticmethod
    async def update_fyers_creds(user_id, client_id, secret, pin=""):
        enc_client = encrypt_val(client_id)
        enc_secret = encrypt_val(secret)
        enc_pin = encrypt_val(pin)
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("UPDATE users SET fyers_client_id=?, fyers_secret=?, fyers_pin=? WHERE id=?",
                      (enc_client, enc_secret, enc_pin, user_id))
            await conn.commit()
        
    @staticmethod
    async def update_fyers_pin(user_id, pin):
        enc_pin = encrypt_val(pin) if pin else ""
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("UPDATE users SET fyers_pin=? WHERE id=?", (enc_pin, user_id))
            await conn.commit()
        
    @staticmethod
    def get_master_app_credentials_sync():
        """Synchronous version for FyersClient initialization."""
        conn = sqlite3.connect(Database.DB_NAME)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT fyers_client_id, fyers_secret FROM users WHERE is_admin=1 AND is_active=1 LIMIT 1")
            row = cursor.fetchone()
            if row and row['fyers_client_id'] and row['fyers_secret']:
                return (row['fyers_client_id'], row['fyers_secret'])
            return ("", "")
        finally:
            conn.close()

    @staticmethod
    async def get_master_app_credentials():
        """Fetch Admin (is_admin=1) Fyers App ID and Secret as Master credentials for SaaS model."""
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute("SELECT fyers_client_id, fyers_secret FROM users WHERE is_admin=1 LIMIT 1") as c:
                    row = await c.fetchone()
                if row:
                    result = dict(row)
                    client_id = result.get("fyers_client_id", "")
                    secret = result.get("fyers_secret", "")
                    if client_id: client_id = decrypt_val(client_id)
                    if secret: secret = decrypt_val(secret)
                    return (client_id or "", secret or "")
        except Exception:
            pass
        # Fallback to environment variables
        return (os.getenv("FYERS_CLIENT_ID", ""), os.getenv("FYERS_SECRET_KEY", ""))

    # D5: user-scoped tables confirmed by direct schema read (CREATE TABLE definitions) to
    # carry a user_id column. health_memory and the swarm_* tables are error-/strategy-scoped
    # (no user_id) and are intentionally excluded from the cascade.
    USER_SCOPED_TABLES = ("user_states", "daily_pnl_history", "paper_pnl_history", "system_logs")

    @staticmethod
    def delete_user_cascade(user_id):
        """Delete a user AND every dependent-table row referencing them, in ONE transaction
        (Phase 2 D5). Dependents are deleted before the users row so no dangling references
        are left mid-transaction. Returns None; raises on DB error (caller decides handling)."""
        conn = sqlite3.connect(Database.DB_NAME)
        c = conn.cursor()
        try:
            for table in Database.USER_SCOPED_TABLES:
                c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    async def update_password(user_id, new_password):
        password_hash = Database.hash_password(new_password)
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
            await conn.commit()

    @staticmethod
    async def set_user_active_status(user_id: int, is_active: bool):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if is_active else 0, user_id))
            await conn.commit()

    @staticmethod
    async def update_fyers_token(user_id, token):
        enc_token = encrypt_val(token)
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("UPDATE users SET fyers_access_token=? WHERE id=?",
                      (enc_token, user_id))
            await conn.commit()

    @staticmethod
    def update_fyers_token_sync(user_id: int, access_token: str):
        conn = sqlite3.connect(Database.DB_NAME)
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET fyers_access_token = ? WHERE id = ?", (encrypt_val(access_token), user_id))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    
    @classmethod
    def update_fyers_tokens_sync(cls, user_id, access_token, refresh_token=None):
        import sqlite3
        conn = sqlite3.connect(cls.DB_NAME)
        cursor = conn.cursor()
        enc_access = encrypt_val(access_token) if access_token else None
        if refresh_token:
            enc_refresh = encrypt_val(refresh_token)
            cursor.execute('UPDATE users SET fyers_access_token = ?, fyers_refresh_token = ? WHERE id = ?', (enc_access, enc_refresh, user_id))
        else:
            cursor.execute('UPDATE users SET fyers_access_token = ? WHERE id = ?', (enc_access, user_id))
        conn.commit()
        conn.close()

    @staticmethod
    async def update_fyers_tokens(user_id, access_token, refresh_token):
        """Update both access and refresh tokens atomically. Pass None to skip a field."""
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            if access_token is not None and refresh_token is not None:
                await conn.execute("UPDATE users SET fyers_access_token=?, fyers_refresh_token=? WHERE id=?",
                          (encrypt_val(access_token), encrypt_val(refresh_token), user_id))
            elif access_token is not None:
                await conn.execute("UPDATE users SET fyers_access_token=? WHERE id=?",
                          (encrypt_val(access_token), user_id))
            elif refresh_token is not None:
                await conn.execute("UPDATE users SET fyers_refresh_token=? WHERE id=?",
                          (encrypt_val(refresh_token), user_id))
            await conn.commit()

    @staticmethod
    async def upsert_daily_pnl(user_id, date, pnl, trades):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO daily_pnl_history (user_id, date, pnl, trades)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, date) DO UPDATE SET
                    pnl = excluded.pnl,
                    trades = excluded.trades
            """, (user_id, date, pnl, trades))
            await conn.commit()

    @staticmethod
    async def get_pnl_history(user_id, months_limit=6):
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now(IST) - timedelta(days=months_limit * 30)).date().isoformat()
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT date, pnl, trades FROM daily_pnl_history
                WHERE user_id = ? AND date >= ?
                ORDER BY date DESC
            """, (user_id, cutoff_date)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def prune_pnl_history(user_id, months_limit=6):
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now(IST) - timedelta(days=months_limit * 30)).date().isoformat()
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                DELETE FROM daily_pnl_history
                WHERE user_id = ? AND date < ?
            """, (user_id, cutoff_date))
            # Also prune paper history
            await conn.execute("""
                DELETE FROM paper_pnl_history
                WHERE user_id = ? AND date < ?
            """, (user_id, cutoff_date))
            await conn.commit()

    @staticmethod
    async def upsert_paper_pnl(user_id, date, pnl, trades):
        """Store paper trading PnL separately from live trades."""
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO paper_pnl_history (user_id, date, pnl, trades)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, date) DO UPDATE SET
                    pnl = excluded.pnl,
                    trades = excluded.trades
            """, (user_id, date, pnl, trades))
            await conn.commit()

    @staticmethod
    async def get_paper_pnl_history(user_id, months_limit=6):
        """Retrieve paper trading PnL history."""
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now(IST) - timedelta(days=months_limit * 30)).date().isoformat()
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT date, pnl, trades FROM paper_pnl_history
                WHERE user_id = ? AND date >= ?
                ORDER BY date DESC
            """, (user_id, cutoff_date)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def insert_log(level: str, message: str, timestamp: str, user_id=None):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO system_logs (user_id, timestamp, level, message)
                VALUES (?, ?, ?, ?)
            """, (user_id, timestamp, level, message))
            await conn.commit()

    @staticmethod
    async def prune_system_logs(months_limit=6):
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now(IST) - timedelta(days=months_limit * 30)).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                DELETE FROM system_logs
                WHERE timestamp < ?
            """, (cutoff_date,))
            await conn.commit()

    @staticmethod
    async def get_user_logs(user_id, limit=100):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT timestamp, level, message FROM system_logs
                WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
            """, (user_id, limit)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def insert_health_memory(error_signature: str, diagnostics: str, applied_fix: str, success: int = 0):
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO health_memory (timestamp, error_signature, diagnostics, applied_fix, success)
                VALUES (?, ?, ?, ?, ?)
            """, (timestamp, error_signature, diagnostics, applied_fix, success))
            await conn.commit()

    @staticmethod
    async def get_health_memory(error_signature: str):
        """Get the most recent successful fix for a specific error signature."""
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM health_memory
                WHERE error_signature = ? AND success = 1
                ORDER BY id DESC LIMIT 1
            """, (error_signature,)) as c:
                row = await c.fetchone()
        return dict(row) if row else None
    
    @staticmethod
    async def get_recent_health_memory(limit=50):
        """Get recent health agent actions for the UI."""
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM health_memory
                ORDER BY id DESC LIMIT ?
            """, (limit,)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

    # --- Swarm AgentDB Methods ---

    @staticmethod
    async def get_agent_config(strategy_name: str) -> Optional[Dict]:
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM swarm_agent_configs WHERE strategy_name=?", (strategy_name,)) as c:
                row = await c.fetchone()
        if row:
            import json
            data = dict(row)
            data['config_json'] = json.loads(data['config_json'])
            return data
        return None

    @staticmethod
    async def get_all_agent_configs() -> list:
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM swarm_agent_configs") as c:
                rows = await c.fetchall()
        
        results = []
        import json
        for row in rows:
            data = dict(row)
            if data.get('config_json'):
                try:
                    data['config_json'] = json.loads(data['config_json'])
                except:
                    pass
            if data.get('pending_config_json'):
                try:
                    data['pending_config_json'] = json.loads(data['pending_config_json'])
                except:
                    pass
            results.append(data)
        return results

    @staticmethod
    async def get_learning_logs(strategy_name: str, limit: int = 1) -> list:
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM swarm_learning_logs WHERE strategy_name=? ORDER BY id DESC LIMIT ?",
                (strategy_name, limit)
            ) as c:
                rows = await c.fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def update_agent_config(strategy_name: str, config_dict: dict, win_rate: float, total_trades: int, winning_trades: int, status: str = 'APPROVED', pending_config_json: str = None, is_paper_trading: int = 1, continuous_losses: int = 0, asset_class: str = 'EQUITY'):
        import json
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        config_json = json.dumps(config_dict)
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO swarm_agent_configs (strategy_name, config_json, last_updated, win_rate, total_trades, winning_trades, status, pending_config_json, is_paper_trading, continuous_losses, asset_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_name) DO UPDATE SET
                    config_json = excluded.config_json,
                    last_updated = excluded.last_updated,
                    win_rate = excluded.win_rate,
                    total_trades = excluded.total_trades,
                    winning_trades = excluded.winning_trades,
                    status = excluded.status,
                    pending_config_json = excluded.pending_config_json,
                    is_paper_trading = excluded.is_paper_trading,
                    continuous_losses = excluded.continuous_losses,
                    asset_class = excluded.asset_class
            """, (strategy_name, config_json, timestamp, win_rate, total_trades, winning_trades, status, pending_config_json, is_paper_trading, continuous_losses, asset_class))
            await conn.commit()

    @staticmethod
    async def approve_agent_config(strategy_name: str) -> bool:
        """Moves pending_config_json into config_json and sets status to APPROVED."""
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT pending_config_json FROM swarm_agent_configs WHERE strategy_name=? AND status='PENDING'", (strategy_name,)) as c:
                row = await c.fetchone()
                if not row or not row['pending_config_json']:
                    return False
                
                pending_cfg = row['pending_config_json']
            
            await conn.execute("""
                UPDATE swarm_agent_configs 
                SET config_json = ?, status = 'APPROVED', pending_config_json = NULL, last_updated = ?
                WHERE strategy_name = ?
            """, (pending_cfg, timestamp, strategy_name))
            await conn.commit()
            return True

    @staticmethod
    async def reject_agent_config(strategy_name: str) -> bool:
        """Clears pending_config_json and resets status to APPROVED."""
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT pending_config_json FROM swarm_agent_configs WHERE strategy_name=? AND status='PENDING'", (strategy_name,)) as c:
                row = await c.fetchone()
                if not row:
                    return False
            
            await conn.execute("""
                UPDATE swarm_agent_configs 
                SET status = 'APPROVED', pending_config_json = NULL, last_updated = ?
                WHERE strategy_name = ?
            """, (timestamp, strategy_name))
            await conn.commit()
            return True

    @staticmethod
    async def insert_trade_record(strategy_name: str, symbol: str, entry_time: str, exit_time: str, entry_price: float, exit_price: float, pnl: float, vix: float, market_trend: str, chart_image_path: str = ""):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO swarm_trade_records (strategy_name, symbol, entry_time, exit_time, entry_price, exit_price, pnl, vix, market_trend, chart_image_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (strategy_name, symbol, entry_time, exit_time, entry_price, exit_price, pnl, vix, market_trend, chart_image_path))
            await conn.commit()

    @staticmethod
    async def record_trade_outcome(strategy_name: str, symbol: str, entry_time: str, exit_time: str,
                                   entry_price: float, exit_price: float, pnl: float,
                                   vix: float = 0.0, market_trend: str = ""):
        """ADDITIVE trade-outcome recorder. Persists the closed trade AND updates the
        per-strategy win-rate stats in swarm_agent_configs.

        This is intentionally best-effort: callers MUST wrap invocation so a failure here
        can never break the live trade-close path. It:
          a. persists the trade row via insert_trade_record (regime/trend context in market_trend)
          b. increments total_trades, increments winning_trades when pnl > 0, recomputes
             win_rate = round(winning_trades/total_trades*100, 1), preserving the existing
             config_dict/status.
        """
        # a. Persist the raw trade record.
        await Database.insert_trade_record(
            strategy_name=strategy_name, symbol=symbol, entry_time=entry_time, exit_time=exit_time,
            entry_price=entry_price, exit_price=exit_price, pnl=pnl, vix=vix,
            market_trend=market_trend, chart_image_path=""
        )

        # b. Update per-strategy win-rate stats (preserve existing config_dict + status).
        cfg = await Database.get_agent_config(strategy_name)
        if cfg is None:
            # No config row yet for this strategy — start a fresh stats row with an empty config.
            config_dict = {}
            total_trades = 0
            winning_trades = 0
            status = 'APPROVED'
            pending_config_json = None
            is_paper_trading = 1
            continuous_losses = 0
            asset_class = 'EQUITY'
        else:
            config_dict = cfg.get('config_json') or {}
            total_trades = int(cfg.get('total_trades') or 0)
            winning_trades = int(cfg.get('winning_trades') or 0)
            status = cfg.get('status') or 'APPROVED'
            pending_config_json = cfg.get('pending_config_json')
            is_paper_trading = int(cfg.get('is_paper_trading') if cfg.get('is_paper_trading') is not None else 1)
            continuous_losses = int(cfg.get('continuous_losses') or 0)
            asset_class = cfg.get('asset_class') or 'EQUITY'

        total_trades += 1
        if pnl > 0:
            winning_trades += 1
            continuous_losses = 0
        else:
            continuous_losses += 1
            if continuous_losses >= 3:
                status = 'DISABLED'
                logger.warning(f"🚫 Strategy {strategy_name} auto-disabled due to 3 continuous losses.")

        win_rate = round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0.0

        await Database.update_agent_config(
            strategy_name=strategy_name, config_dict=config_dict, win_rate=win_rate,
            total_trades=total_trades, winning_trades=winning_trades, status=status,
            pending_config_json=pending_config_json, is_paper_trading=is_paper_trading,
            continuous_losses=continuous_losses, asset_class=asset_class
        )

    @staticmethod
    async def get_strategy_trade_records(strategy_name: str, limit: int = 100):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM swarm_trade_records
                WHERE strategy_name = ?
                ORDER BY id DESC LIMIT ?
            """, (strategy_name, limit)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def insert_learning_log(strategy_name: str, llm_analysis: str, old_config: str, new_config: str):
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO swarm_learning_logs (strategy_name, date, llm_analysis, old_config, new_config)
                VALUES (?, ?, ?, ?, ?)
            """, (strategy_name, date_str, llm_analysis, old_config, new_config))
            await conn.commit()

    @staticmethod
    def is_kill_switch_active() -> bool:
        """Returns True if the global kill switch is currently active."""
        try:
            conn = sqlite3.connect(Database.DB_NAME)
            c = conn.cursor()
            # If table doesn't exist yet, it will throw an exception and return False
            c.execute("SELECT is_active FROM global_kill_switch ORDER BY id DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            return bool(row[0]) if row else False
        except Exception as e:
            return False

    @staticmethod
    def engage_kill_switch(reason: str):
        """Engages the global kill switch to halt all trading."""
        try:
            conn = sqlite3.connect(Database.DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO global_kill_switch (is_active, reason) VALUES (1, ?)", (reason,))
            conn.commit()
            conn.close()
            print(f"🛑 GLOBAL KILL SWITCH ENGAGED: {reason}", flush=True)
        except Exception as e:
            print(f"Error engaging kill switch: {e}", flush=True)

    @staticmethod
    async def insert_orchestrator_memory(winning_strategy: str, rejected_strategies: list, market_regime: str):
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        rej_str = ",".join(rejected_strategies) if rejected_strategies else ""
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO orchestrator_memory (timestamp, winning_strategy, rejected_strategies, market_regime)
                VALUES (?, ?, ?, ?)
            """, (timestamp, winning_strategy, rej_str, market_regime))
            await conn.commit()

    @staticmethod
    async def get_daily_orchestrator_memory(date_str: str = None):
        if not date_str:
            date_str = datetime.now(IST).strftime("%Y-%m-%d")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM orchestrator_memory
                WHERE timestamp LIKE ?
                ORDER BY id ASC
            """, (f"{date_str}%",)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

# Initialize on import
Database.init_db()
