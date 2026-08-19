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
            
        # Migration: add active_broker column to existing DBs
        try:
            c.execute("ALTER TABLE users ADD COLUMN active_broker TEXT DEFAULT 'fyers'")
            print("🆕 Migrated users table: added active_broker column", flush=True)
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
            asset_class TEXT DEFAULT 'EQUITY',
            stats_source TEXT DEFAULT 'live'
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

        # Migration: add stats_source provenance column (strategy-self-improvement, 11-08-26)
        try:
            c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN stats_source TEXT DEFAULT 'live'")
            # One-time backfill, guarded by the ALTER above (which can only succeed once, making
            # this idempotent by construction). Every pre-existing row was last written by
            # nightly_learning's backtest-sourced update_agent_config() calls — confirmed on the
            # live DB 13-08-26: the rows holding non-zero stats match backtest_results trade counts
            # exactly (Strategy 8: 159 vs backtest 158, Strategy 9: 79 vs 79, Crude EIA: 63 vs 63),
            # while only 24 real executed_trades exist in total. Marking them 'backtest' rather than
            # letting the column DEFAULT 'live' stand is what makes the Strategy 8 case (SPEC AC#5)
            # non-misleading.
            #
            # NOTE: this replaces the PLAN's `... WHERE stats_source='live' AND last_updated <
            # '2026-08-11'` date-gated form. That literal cutoff was written on 11-08-26 assuming
            # same-day EXECUTE; EXECUTE ran 13-08-26, by which point nightly_learning had rewritten
            # the backtest-derived rows at 2026-08-11 15:18 — i.e. NOT `< '2026-08-11'` — so the
            # date form tagged the exact rows SPEC AC#5 targets as 'live', the opposite of intent.
            # The ALTER-guarded form is date-free and cannot later mis-flip a genuinely live row.
            c.execute("UPDATE swarm_agent_configs SET stats_source='backtest'")
            print("🆕 Migrated swarm_agent_configs table: added stats_source column (existing rows backfilled as 'backtest')", flush=True)
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

        # Pending Strategy Tunings (Approval Queue for Self-Improvement)
        c.execute('''CREATE TABLE IF NOT EXISTS pending_strategy_tunings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            param_name TEXT NOT NULL,
            old_value TEXT NOT NULL,
            proposed_value TEXT NOT NULL,
            expectancy_delta REAL DEFAULT 0.0,
            status TEXT DEFAULT 'PENDING',
            reason TEXT
        )''')

        # Executed-trade ledger (added 30-07-26). The AUTHORITATIVE record of EVERY executed trade,
        # win or loss. A row is written at ENTRY (status OPEN) with full context (strategy, entry
        # price, SL, regime/trend) and UPDATED at EXIT (status CLOSED) with exit price, pnl and
        # WIN/LOSS outcome. Recording at entry is what makes this reliable — the old close-time-only
        # recorder dropped trades whose strategy context was already gone by close (0 rows / 0 pnl).
        # This is the table the self-improvement / nightly-learning reads real win-rates from.
        c.execute('''CREATE TABLE IF NOT EXISTS executed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            strategy_name TEXT,
            symbol TEXT NOT NULL,
            underlying TEXT,
            side TEXT,
            qty INTEGER,
            entry_price REAL,
            entry_time TEXT,
            sl_points REAL,
            sl_method TEXT,
            sl_price REAL,
            initial_sl_price REAL,
            final_sl_price REAL,
            sl_trail_count INTEGER DEFAULT 0,
            target_points REAL,
            product TEXT,
            regime TEXT,
            trend TEXT,
            entry_reason TEXT,
            entry_order_id TEXT,
            status TEXT DEFAULT 'OPEN',
            exit_price REAL,
            exit_time TEXT,
            pnl REAL,
            outcome TEXT,
            exit_reason TEXT,
            trade_date TEXT
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_exec_trades_date ON executed_trades(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_exec_trades_openkey ON executed_trades(symbol, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_exec_trades_strat ON executed_trades(strategy_name, trade_date)")
        # Migration for existing DBs (table already created without the SL/TSL/reason columns).
        for _col, _decl in (("sl_price", "REAL"), ("initial_sl_price", "REAL"), ("final_sl_price", "REAL"),
                            ("sl_trail_count", "INTEGER DEFAULT 0"), ("entry_reason", "TEXT")):
            try:
                c.execute(f"ALTER TABLE executed_trades ADD COLUMN {_col} {_decl}")
            except sqlite3.OperationalError:
                pass

        # backtest_results (04-08-26): output of engine/backtest_runner.py — deliberately a
        # SEPARATE table from executed_trades (real live/paper fills) and shadow_trades (isolated
        # paper simulation) so "real", "shadow-simulated", and "backtested" data can never be
        # silently conflated. One row per strategy per backtest run (run_date), so history of
        # past runs is kept, not overwritten — nightly_learning reads the LATEST row per strategy.
        c.execute('''CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            symbol TEXT,
            run_date TEXT NOT NULL,
            window_days INTEGER,
            trades INTEGER,
            wins INTEGER,
            losses INTEGER,
            win_rate REAL,
            total_pnl REAL,
            avg_pnl REAL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_backtest_strat_date ON backtest_results(strategy_name, run_date)")

        # backtest_refresh_status (strategy-self-improvement, 11-08-26): single-row status of the
        # nightly run_backtests_cron.py refresh, so a silent refresh failure is visible to a human.
        c.execute('''CREATE TABLE IF NOT EXISTS backtest_refresh_status (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_status TEXT,
            last_run_at TEXT,
            last_error TEXT
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

    async def update_active_broker(user_id: int, broker: str):
        import aiosqlite
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("UPDATE users SET active_broker=? WHERE id=?", (broker, user_id))
            await conn.commit()

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
        """Synchronous version for FyersClient initialization.

        Must decrypt DB values the same way as get_master_app_credentials(); credentials
        are stored encrypted via update_fyers_creds.
        """
        conn = sqlite3.connect(Database.DB_NAME)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT fyers_client_id, fyers_secret FROM users WHERE is_admin=1 AND is_active=1 LIMIT 1")
            row = cursor.fetchone()
            if row and row['fyers_client_id'] and row['fyers_secret']:
                client_id = decrypt_val(row['fyers_client_id']) or ""
                secret = decrypt_val(row['fyers_secret']) or ""
                if client_id and secret:
                    return (client_id, secret)
            return (os.getenv("FYERS_CLIENT_ID", ""), os.getenv("FYERS_SECRET_KEY", ""))
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
    async def update_agent_config(strategy_name: str, config_dict: dict, win_rate: float, total_trades: int, winning_trades: int, status: str = 'APPROVED', pending_config_json: str = None, is_paper_trading: int = 1, continuous_losses: int = 0, asset_class: str = 'EQUITY', stats_source: str = 'live'):
        import json
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        config_json = json.dumps(config_dict)
        # pending_config_json (bound as SQL parameter 8) is a JSON-TEXT column. Callers sometimes
        # pass an already-parsed dict/list (e.g. cfg.get('pending_config_json')); SQLite cannot bind
        # those ("Error binding parameter 8: type 'dict' is not supported"), which silently broke the
        # nightly AI-critique save. Serialize any dict/list to JSON text before binding.
        if isinstance(pending_config_json, (dict, list)):
            pending_config_json = json.dumps(pending_config_json)
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO swarm_agent_configs (strategy_name, config_json, last_updated, win_rate, total_trades, winning_trades, status, pending_config_json, is_paper_trading, continuous_losses, asset_class, stats_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    asset_class = excluded.asset_class,
                    stats_source = excluded.stats_source
            """, (strategy_name, config_json, timestamp, win_rate, total_trades, winning_trades, status, pending_config_json, is_paper_trading, continuous_losses, asset_class, stats_source))
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
        # STRICT: only real losses (pnl < 0) count toward continuous_losses.
        # Breakeven must NOT inflate the streak or auto-disable a strategy.
        if pnl > 0:
            winning_trades += 1
            continuous_losses = 0
        elif pnl < 0:
            continuous_losses += 1
            if continuous_losses >= 3:
                status = 'DISABLED'
                logger.warning(f"🚫 Strategy {strategy_name} auto-disabled due to 3 continuous losses.")
        # pnl == 0 (breakeven): leave continuous_losses unchanged

        win_rate = round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0.0

        await Database.update_agent_config(
            strategy_name=strategy_name, config_dict=config_dict, win_rate=win_rate,
            total_trades=total_trades, winning_trades=winning_trades, status=status,
            pending_config_json=pending_config_json, is_paper_trading=is_paper_trading,
            continuous_losses=continuous_losses, asset_class=asset_class, stats_source='live'
        )

    # ─────────────────────────────────────────────────────────────────────────────
    # Executed-trade ledger (authoritative, entry+exit). Reliable because a row is
    # written at ENTRY with full context, then completed at EXIT. Win-rates are
    # computed on-demand FROM this ledger (get_strategy_performance), so there is no
    # incremental counter to drift or double-count.
    # ─────────────────────────────────────────────────────────────────────────────
    @staticmethod
    async def record_trade_entry(user_id: int, strategy_name: str, symbol: str, underlying: str,
                                 side: str, qty: int, entry_price: float, entry_time: str,
                                 sl_points: float, sl_method: str, target_points: float,
                                 product: str, regime: str, trend: str, entry_order_id: str,
                                 trade_date: str, entry_reason: str = "") -> int:
        """Write an OPEN row the moment an order is placed. Captures WHICH strategy, the initial SL
        (points + absolute price) and the entry reason. final_sl_price starts at the initial stop and
        is bumped by record_trade_trail on every TSL move. Best-effort — callers must wrap so a DB
        failure never affects execution. Returns the new row id (0 on failure)."""
        try:
            ep = float(entry_price or 0)
            slp = float(sl_points or 0)
            # Absolute initial stop price. Long option (BUY) stops below entry; short above.
            sl_price = round(ep - slp, 2) if str(side).upper() == "BUY" else round(ep + slp, 2)
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                cur = await conn.execute("""
                    INSERT INTO executed_trades
                      (user_id, strategy_name, symbol, underlying, side, qty, entry_price, entry_time,
                       sl_points, sl_method, sl_price, initial_sl_price, final_sl_price, sl_trail_count,
                       target_points, product, regime, trend, entry_reason, entry_order_id,
                       status, trade_date)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?, 'OPEN', ?)
                """, (user_id, strategy_name, symbol, underlying, side, int(qty or 0),
                      ep, entry_time, slp, sl_method, sl_price, sl_price, sl_price,
                      float(target_points or 0), product, regime, trend, entry_reason,
                      entry_order_id, trade_date))
                await conn.commit()
                return cur.lastrowid or 0
        except Exception as e:
            logger.warning(f"record_trade_entry failed for {symbol}: {e}")
            return 0

    @staticmethod
    async def record_trade_trail(symbol: str, new_sl_price: float, user_id: int = None) -> bool:
        """Record a TSL move: update the OPEN row's final_sl_price and bump sl_trail_count. Called by
        the trailing monitor each time it trails the stop toward the winning side. Best-effort."""
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                where_user = "AND user_id = ?" if user_id is not None else ""
                params = [symbol] + ([user_id] if user_id is not None else [])
                async with conn.execute(
                    f"SELECT id FROM executed_trades WHERE symbol = ? AND status = 'OPEN' {where_user} "
                    f"ORDER BY id DESC LIMIT 1", params) as cur:
                    row = await cur.fetchone()
                if not row:
                    return False
                await conn.execute(
                    "UPDATE executed_trades SET final_sl_price=?, sl_trail_count=COALESCE(sl_trail_count,0)+1 "
                    "WHERE id=?", (round(float(new_sl_price or 0), 2), row[0]))
                await conn.commit()
                return True
        except Exception as e:
            logger.warning(f"record_trade_trail failed for {symbol}: {e}")
            return False

    @staticmethod
    async def record_trade_exit(symbol: str, exit_price: float, pnl: float, exit_reason: str = "",
                                user_id: int = None) -> bool:
        """Complete the most-recent OPEN row for `symbol` (win or loss). Matches by symbol (+user_id
        if given). Outcome = WIN if pnl>0, LOSS if pnl<0, else BREAKEVEN. Idempotent-ish: only OPEN
        rows are updated, so a duplicate exit call is a no-op. Best-effort."""
        try:
            outcome = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")
            exit_time = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                where_user = "AND user_id = ?" if user_id is not None else ""
                params = [symbol] + ([user_id] if user_id is not None else [])
                async with conn.execute(
                    f"SELECT id FROM executed_trades WHERE symbol = ? AND status = 'OPEN' {where_user} "
                    f"ORDER BY id DESC LIMIT 1", params) as cur:
                    row = await cur.fetchone()
                if not row:
                    return False
                await conn.execute("""
                    UPDATE executed_trades
                       SET status='CLOSED', exit_price=?, exit_time=?, pnl=?, outcome=?, exit_reason=?
                     WHERE id=?
                """, (float(exit_price or 0), exit_time, float(pnl or 0), outcome, exit_reason, row[0]))
                await conn.commit()
                return True
        except Exception as e:
            logger.warning(f"record_trade_exit failed for {symbol}: {e}")
            return False

    @staticmethod
    async def get_strategy_performance(days: int = 30):
        """Real per-strategy stats computed FROM the executed-trade ledger (CLOSED rows only).
        Returns {strategy_name: {trades, wins, losses, win_rate, total_pnl, avg_pnl}}."""
        import datetime as _dt
        cutoff = (datetime.now(IST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        out = {}
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                async with conn.execute("""
                    SELECT strategy_name,
                           COUNT(*) AS trades,
                           SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                           SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses,
                           COALESCE(SUM(pnl), 0) AS total_pnl
                      FROM executed_trades
                     WHERE status='CLOSED' AND trade_date >= ?
                     GROUP BY strategy_name
                """, (cutoff,)) as cur:
                    async for r in cur:
                        strat, trades, wins, losses, total_pnl = r
                        trades = int(trades or 0); wins = int(wins or 0)
                        out[strat] = {
                            "trades": trades, "wins": wins, "losses": int(losses or 0),
                            "win_rate": round(wins / trades * 100, 1) if trades else 0.0,
                            "total_pnl": round(float(total_pnl or 0), 2),
                            "avg_pnl": round(float(total_pnl or 0) / trades, 2) if trades else 0.0,
                        }
        except Exception as e:
            logger.warning(f"get_strategy_performance failed: {e}")
        return out

    @staticmethod
    async def save_backtest_result(strategy_name: str, symbol: str, run_date: str, window_days: int,
                                    trades: int, wins: int, losses: int, win_rate: float,
                                    total_pnl: float, avg_pnl: float, note: str = "") -> bool:
        """Persist one strategy's backtest_runner.py output. Appends a new row per run (does not
        overwrite prior runs) — get_backtest_performance() reads the latest per strategy."""
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                await conn.execute("""
                    INSERT INTO backtest_results
                        (strategy_name, symbol, run_date, window_days, trades, wins, losses,
                         win_rate, total_pnl, avg_pnl, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (strategy_name, symbol, run_date, window_days, trades, wins, losses,
                      win_rate, total_pnl, avg_pnl, note))
                await conn.commit()
            return True
        except Exception as e:
            logger.warning(f"save_backtest_result failed for {strategy_name}: {e}")
            return False

    @staticmethod
    async def set_backtest_refresh_status(status: str, error: str = "") -> bool:
        """Upsert the single-row backtest_refresh_status (id=1) — visible signal for the nightly
        run_backtests_cron.py refresh outcome (strategy-self-improvement, 11-08-26)."""
        try:
            last_run_at = datetime.now(IST).isoformat()
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                await conn.execute("""
                    INSERT INTO backtest_refresh_status (id, last_status, last_run_at, last_error)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        last_status = excluded.last_status,
                        last_run_at = excluded.last_run_at,
                        last_error = excluded.last_error
                """, (status, last_run_at, error))
                await conn.commit()
            return True
        except Exception as e:
            logger.warning(f"set_backtest_refresh_status failed: {e}")
            return False

    @staticmethod
    async def get_backtest_refresh_status() -> Optional[Dict]:
        """Read the single-row backtest_refresh_status, or None if never written."""
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute("SELECT * FROM backtest_refresh_status WHERE id=1") as c:
                    row = await c.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"get_backtest_refresh_status failed: {e}")
            return None

    @staticmethod
    async def get_backtest_performance() -> dict:
        """Latest backtest_results row per strategy, in the SAME {strategy: {trades, wins, losses,
        win_rate, total_pnl, avg_pnl}} shape as get_strategy_performance() — so nightly_learning.py
        can read from either source without changing its own logic."""
        out = {}
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute("""
                    SELECT b.strategy_name, b.trades, b.wins, b.losses, b.win_rate, b.total_pnl, b.avg_pnl, b.run_date
                      FROM backtest_results b
                      INNER JOIN (
                          SELECT strategy_name, MAX(run_date) AS max_date
                            FROM backtest_results GROUP BY strategy_name
                      ) latest ON b.strategy_name = latest.strategy_name AND b.run_date = latest.max_date
                """) as cur:
                    async for r in cur:
                        d = dict(r)
                        out[d["strategy_name"]] = {
                            "trades": int(d["trades"] or 0), "wins": int(d["wins"] or 0),
                            "losses": int(d["losses"] or 0), "win_rate": float(d["win_rate"] or 0.0),
                            "total_pnl": float(d["total_pnl"] or 0.0), "avg_pnl": float(d["avg_pnl"] or 0.0),
                            "run_date": d["run_date"],
                        }
        except Exception as e:
            logger.warning(f"get_backtest_performance failed: {e}")
        return out

    @staticmethod
    async def get_losing_trades(days: int = 30, strategy_name: str = None, limit: int = 50):
        """CLOSED losing trades (pnl < 0) from the executed-trades ledger — newest first.
        Used by nightly learning to STRICTLY learn from losses (not win-rate aggregates alone)."""
        import datetime as _dt
        cutoff = (datetime.now(IST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        rows = []
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                conn.row_factory = aiosqlite.Row
                q = ("SELECT * FROM executed_trades WHERE status='CLOSED' AND pnl < 0 "
                     "AND trade_date >= ?")
                params = [cutoff]
                if strategy_name:
                    q += " AND strategy_name = ?"
                    params.append(strategy_name)
                q += " ORDER BY id DESC LIMIT ?"
                params.append(int(limit))
                async with conn.execute(q, params) as cur:
                    rows = [dict(r) async for r in cur]
        except Exception as e:
            logger.warning(f"get_losing_trades failed: {e}")
        return rows

    @staticmethod
    async def compute_continuous_loss_streak(strategy_name: str, days: int = 90) -> int:
        """Count consecutive CLOSED losses from the most recent trade backward.
        Wins/breakeven break the streak. Authoritative source for continuous_losses sync."""
        import datetime as _dt
        cutoff = (datetime.now(IST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        streak = 0
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                async with conn.execute("""
                    SELECT pnl FROM executed_trades
                     WHERE status='CLOSED' AND strategy_name = ? AND trade_date >= ?
                     ORDER BY id DESC
                     LIMIT 50
                """, (strategy_name, cutoff)) as cur:
                    async for (pnl,) in cur:
                        if pnl is None:
                            break
                        if float(pnl) < 0:
                            streak += 1
                        else:
                            break
        except Exception as e:
            logger.warning(f"compute_continuous_loss_streak failed for {strategy_name}: {e}")
        return streak

    @staticmethod
    async def lookup_open_trade_strategy(symbol: str, user_id: int = None) -> str:
        """Best-effort: recover strategy_name for a still-OPEN ledger row (close-path fallback)."""
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                where_user = "AND user_id = ?" if user_id is not None else ""
                params = [symbol] + ([user_id] if user_id is not None else [])
                async with conn.execute(
                    f"SELECT strategy_name FROM executed_trades WHERE symbol = ? AND status = 'OPEN' "
                    f"{where_user} ORDER BY id DESC LIMIT 1", params
                ) as cur:
                    row = await cur.fetchone()
                return (row[0] if row and row[0] else "") or ""
        except Exception as e:
            logger.warning(f"lookup_open_trade_strategy failed for {symbol}: {e}")
            return ""

    @staticmethod
    async def get_executed_trades(days: int = 7, strategy_name: str = None, limit: int = 500):
        """Raw executed-trade rows (newest first) for analysis / dashboards."""
        import datetime as _dt
        cutoff = (datetime.now(IST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        rows = []
        try:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                conn.row_factory = aiosqlite.Row
                q = "SELECT * FROM executed_trades WHERE trade_date >= ?"
                params = [cutoff]
                if strategy_name:
                    q += " AND strategy_name = ?"; params.append(strategy_name)
                q += " ORDER BY id DESC LIMIT ?"; params.append(limit)
                async with conn.execute(q, params) as cur:
                    rows = [dict(r) async for r in cur]
        except Exception as e:
            logger.warning(f"get_executed_trades failed: {e}")
        return rows

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

    @staticmethod
    async def insert_pending_tuning(strategy_name: str, param_name: str, old_val: str, proposed_val: str, expectancy_delta: float = 0.0, reason: str = ""):
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                INSERT INTO pending_strategy_tunings (timestamp, strategy_name, param_name, old_value, proposed_value, expectancy_delta, status, reason)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (timestamp, strategy_name, param_name, str(old_val), str(proposed_val), expectancy_delta, reason))
            await conn.commit()

    @staticmethod
    async def get_pending_tunings(status: str = "PENDING"):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT * FROM pending_strategy_tunings
                WHERE status = ?
                ORDER BY id DESC
            """, (status,)) as c:
                rows = await c.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def update_tuning_status(tuning_id: int, new_status: str):
        async with aiosqlite.connect(Database.DB_NAME) as conn:
            await conn.execute("""
                UPDATE pending_strategy_tunings
                SET status = ?
                WHERE id = ?
            """, (new_status, tuning_id))
            await conn.commit()

# Initialize on import
Database.init_db()
