"""
NIFTY Options Trading Dashboard — FastAPI Backend
"""
print("🏁 TOP OF APP.PY REACHED", flush=True)
print("📦 Importing os, json, logging...", flush=True)
import os
import json
import logging
print("📦 Importing asyncio...", flush=True)
import asyncio
try:
    import uvloop
    uvloop.install()
    print("⚡ uvloop installed for ultra-low latency event loop", flush=True)
except ImportError:
    pass
print("📦 Importing sqlite3...", flush=True)
import sqlite3
print("📦 Importing threading...", flush=True)
import threading
import signal
import hmac
import orjson
# import pandas as pd (REMOVED: hanging in venv)
print("📦 Importing pytz...", flush=True)
import pytz
IST = pytz.timezone('Asia/Kolkata')
print("📦 Importing datetime...", flush=True)
from datetime import datetime, timedelta
print("📦 Importing typing...", flush=True)
from typing import Optional, List, Set, Dict
print("📦 Importing fastapi...", flush=True)
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Query, BackgroundTasks, Depends
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import ORJSONResponse as JSONResponse
from pydantic import BaseModel
from pathlib import Path
from dotenv import load_dotenv

# Setup logging with rotation (prevents disk full on GCP)
from logging.handlers import RotatingFileHandler
os.makedirs("logs", exist_ok=True)
log_formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)

# Rotating file handler (5MB per file, keep last 3)
file_handler = RotatingFileHandler('logs/dashboard.log', maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("DASHBOARD")

# Dynamic path resolution for portability (must happen BEFORE imports that need env vars)
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ENV_PATH = PROJECT_ROOT / "fyers-mcp-server" / ".env"
LOG_DIR = BASE_DIR / "logs"

# Ensure logs directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Load .env files FIRST — before any module that needs ENCRYPTION_KEY or FYERS_* vars
print("🔍 Debug: Loading environment...", flush=True)
load_dotenv(BASE_DIR / ".env")  # trading-app/.env (ENCRYPTION_KEY)
load_dotenv(ENV_PATH)           # fyers-mcp-server/.env (FYERS_CLIENT_ID, etc.)
print("🔍 Debug: Environment loaded.", flush=True)

print("📦 Importing auth_utils...", flush=True)
from auth_utils import (
    sign_user_id,
    resolve_user_id_from_cookie,
    check_login_locked,
    register_failed_login,
    reset_login_attempts,
    generate_oauth_state,
    consume_oauth_state,
)
print("📦 Importing fyers_client...", flush=True)
from fyers_client import FyersClient
print("📦 Importing engine.signals...", flush=True)
from engine.signals import generate_signals
# Try to import the real AI engine; fall back to a mock if google-generativeai is missing
try:
    print("📦 Importing engine.ai_engine...", flush=True)
    from engine.ai_engine import ai_engine
except ImportError:
    print("⚠️ google-generativeai not installed. Using MockAIEngine.", flush=True)
    class MockAIEngine:
        enabled = False
        async def confirm_signal(self, symbol, signal, context):
            return {"ai_confidence": signal.get("confidence", 70), "ai_status": "mocked"}
        async def get_ai_trend(self, symbol, context):
            return {"trend": "NEUTRAL", "strength": 50, "rationale": "Mock AI: Defaulting to Neutral."}
    ai_engine = MockAIEngine()

print("📦 Importing engine.strikes...", flush=True)
from engine.strikes import select_strike, get_strike_recommendations
print("📦 Importing engine.logger...", flush=True)
from engine.logger import log_signal, log_trade, get_signal_history
print("📦 Importing engine.automation...", flush=True)
from engine.automation import TradingState
print("📦 Importing engine.strategy_926...", flush=True)
from engine.strategy_orb import evaluate_orb_strategy
from engine.strategy_926 import evaluate_926_strategy
from engine.strategy_5 import evaluate_strat5_strategy
from engine.ws_feed import ws_feed
print("📦 Importing engine.api_queue...", flush=True)
from engine.api_queue import api_queue
print("📦 Importing models...", flush=True)
from models import Database
print("📦 Importing workers...", flush=True)
from workers.market_worker import market_data_worker
from workers.auto_trader import trailing_monitor, automation_loop, calculate_smart_sl, execute_auto_trade
from workers.news_worker import news_worker
from workers.health_agent import health_monitor_worker, HEALTH_AGENT_STATUS
print("📦 Imports complete.", flush=True)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """Application lifespan: start background tasks on startup."""
    global main_loop
    running_loop = asyncio.get_running_loop()
    main_loop = running_loop
    state.set_main_loop(running_loop)

    # Start background tasks
    asyncio.create_task(api_queue.start())
    from workers.regime_worker import regime_evaluator
    asyncio.create_task(regime_evaluator())
    asyncio.create_task(market_data_worker())
    asyncio.create_task(trailing_monitor())
    asyncio.create_task(automation_loop())
    asyncio.create_task(news_worker.run())
    asyncio.create_task(health_monitor_worker())
    asyncio.create_task(fyers_token_refresh_scheduler())
    # daily_restart_scheduler REMOVED — it relied on broken Vagator V2 TOTP auto-login
    asyncio.create_task(daily_hard_exit_scheduler())
    asyncio.create_task(hourly_status_scheduler())
    asyncio.create_task(ai_oracle_scheduler())
    asyncio.create_task(ws_connection_monitor())

    # Prune old logs on startup
    try:
        await Database.prune_system_logs(months_limit=6)
        print("✅ System logs pruned (6 months retention).", flush=True)
    except Exception as e:
        print(f"⚠️ Failed to prune system logs: {e}", flush=True)

    print("✅ All background tasks started.", flush=True)

    yield  # Application is running

app = FastAPI(title="ControlN Trading Dashboard", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
VERSION = "6.0.1"
SERVER_START_TIME = datetime.now(pytz.timezone('Asia/Kolkata'))

# Ensure Database is initialized
Database.init_db()
print("🗄️ Database Initialized & Tables Verified.")

# Multi-User Session Cache & State Map
import state
USER_CONTEXTS = state.USER_CONTEXTS
USER_STATES = state.USER_STATES

def get_user_state(user_id) -> TradingState:
    return state.get_user_state(user_id)

def get_lot_size(symbol: str) -> int:
    """Get the official NSE lot size (effective Jan 2026)."""
    symbol_upper = symbol.upper()
    if "BANKNIFTY" in symbol_upper:
        return 30
    if "FINNIFTY" in symbol_upper:
        return 60
    if "MIDCPNIFTY" in symbol_upper:
        return 120
    if "NIFTY" in symbol_upper:
        return 65
    return 65  # Default fallback

# --- AUTHENTICATION ROUTES (v4.2.0) ---
@app.get("/login")
async def login_page(request: Request):
    response = FileResponse(BASE_DIR / "static" / "login.html")
    # Clear browser cache and storage when session expires
    if request.query_params.get("reason") in ["session_expired", "idle"]:
        response.headers["Clear-Site-Data"] = '"cache", "storage"'
    return response

@app.post("/api/login")
async def login_api(request: Request):
    try:
        data = await request.json()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        print(f"🔐 Login attempt for: '{username}' with password length: {len(password)}")

        # Brute-force lockout: after too many failed attempts, refuse without checking the
        # password at all (avoids a timing oracle). See Phase 1 Item C2.
        if check_login_locked(username):
            print(f"⛔ Login locked for '{username}' (too many failed attempts)")
            return JSONResponse({"success": False, "message": "Too many failed attempts. Try again in 15 minutes."})

        user = await Database.get_user_by_username(username)
        if user:
            print(f"✅ User found in DB. Verifying password...")
            if Database.verify_password(password, user["password_hash"]):
                if not user.get("is_active", True):
                    return JSONResponse({"success": False, "message": "Your account has been deactivated by the administrator."})
                print("✅ Password matches!")
                reset_login_attempts(username)
                response = JSONResponse({"success": True})
                response.set_cookie(key="user_id", value=sign_user_id(user["id"]), max_age=86400 * 30, path="/", httponly=True, samesite="lax")
                response.set_cookie(key="username", value=user["username"], max_age=86400 * 30, path="/", samesite="lax")
                return response
            else:
                print("❌ Password did not match!")
        else:
            print("❌ User not found!")

        register_failed_login(username)
        return JSONResponse({"success": False, "message": "Invalid credentials"})
    except Exception as e:
        print(f"💥 Login API Exception: {e}")
        return JSONResponse({"success": False, "message": str(e)})

@app.get("/logout")
async def logout(request: Request):
    reason = request.query_params.get("reason")
    url = "/login"
    if reason:
        url += f"?reason={reason}"
    response = RedirectResponse(url=url)
    response.delete_cookie("user_id", path="/")
    response.delete_cookie("username", path="/")
    # Tell the browser to wipe local storage but NOT cache (which causes extreme slowness)
    response.headers["Clear-Site-Data"] = '"storage"'
    return response

# Protected main route
@app.get("/")
async def root(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    auth_code = request.query_params.get("auth_code")

    # Backward compat: if Fyers still redirects here with ?auth_code (legacy FYERS_REDIRECT_URI),
    # forward to the dedicated callback so there's one code path.
    if auth_code:
        print(f"↪️ Forwarding legacy ?auth_code on / to /fyers/callback", flush=True)
        return RedirectResponse(url=f"/fyers/callback?auth_code={auth_code}")

    print(f"🏠 Root route: user_id cookie = '{user_id}'", flush=True)

    if not user_id:
        print("🏠 → Serving landing.html (no user_id cookie)", flush=True)
        response = FileResponse(BASE_DIR / "static" / "landing.html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response
    
    user = await Database.get_user_by_id(user_id)
    if not user or not user.get("is_active", True):
        print(f"🏠 → Serving landing.html (user_id={user_id} not found or deactivated)", flush=True)
        response = FileResponse(BASE_DIR / "static" / "landing.html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.delete_cookie("user_id", path="/")
        response.delete_cookie("username", path="/")
        return response
    
    print(f"🏠 → Serving index.html for user '{user.get('username', '?')}' (id={user_id})", flush=True)
    response = FileResponse(BASE_DIR / "static" / "index.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

@app.get("/api/state")
async def get_state(request: Request):
    """Full application state including config, market data, and active positions."""
    u_id = await resolve_authenticated_user_id(request)
    if not u_id: return JSONResponse({"error": "Unauthorized"}, 401)
    
    u_id_int = int(u_id)
    client = USER_CONTEXTS.get(u_id_int)
    
    user_state = state.get_user_state(u_id_int)
    
    return {
        "status": "connected" if client and client.client else "disconnected",
        "market_phase": "OPEN" if state.is_market_open() else "CLOSED",
        "market_regime": state.market_regime,
        "regime_reason": state.regime_reason,
        "config": user_state.get_trading_config(),
        "market": {},
        "signals": [],
        "user_state": {
            "daily_pnl": user_state.pnl_today,
            "trades_count": user_state.trades_today,
            "is_auto": user_state.automation_enabled
        }
    }

@app.get("/api/market-summary")
async def get_market_summary():
    """Returns the daily news-based AI market summary."""
    return news_worker.last_summary

# --- ADMIN ROUTES (v4.2.0) ---
@app.get("/admin")
async def admin_page(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    if not user_id: return RedirectResponse(url="/login")
    
    user = await Database.get_user_by_id(user_id)
    if not user or not user["is_admin"]:
        return "Unauthorized: Admins only"
    return FileResponse(BASE_DIR / "static" / "admin.html")

@app.get("/api/admin/analytics")
async def admin_analytics(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    if not user_id: return JSONResponse({"error": "Unauthorized"}, 401)
    
    admin_user = await Database.get_user_by_id(user_id)
    if not admin_user or not admin_user["is_admin"]:
        return JSONResponse({"error": "Unauthorized"}, 403)
        
    from state import USER_STATES, active_connections, USER_CACHES
    import subprocess
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
    
    # 1. App Analytics
    conn = sqlite3.connect(Database.DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT id, username, is_active FROM users")
    db_users = [dict(r) for r in c.fetchall()]
    total_users = len(db_users)
    active_users = sum(1 for u in db_users if u["is_active"])
    
    logged_in_users = []
    for u in db_users:
        uid_str = str(u["id"])
        if uid_str in USER_CACHES and USER_CACHES[uid_str].get("is_auth", False):
            logged_in_users.append({
                "id": u["id"],
                "username": u["username"]
            })
            
    strategies_count = {}
    for state in USER_STATES.values():
        if state.automation_enabled:
            for s in state.active_strategies:
                strategies_count[s] = strategies_count.get(s, 0) + 1
                
    active_ws = len(active_connections)
    users_with_automation = sum(1 for s in USER_STATES.values() if s.automation_enabled)
    
    # 2. Crash Analytics
    c.execute("SELECT timestamp, message FROM system_logs WHERE level='error' ORDER BY id DESC LIMIT 50")
    error_logs = [{"timestamp": r["timestamp"], "message": r["message"]} for r in c.fetchall()]
    conn.close()
    
    # 3. Update Pipelines
    try:
        import os
        git_info_path = os.path.join(os.path.dirname(__file__), "git_info.txt")
        with open(git_info_path, "r") as f:
            git_log = f.read()
    except Exception:
        git_log = "Git log not available."
        
    try:
        uptime = (datetime.now(IST) - SERVER_START_TIME).total_seconds()
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{int(hours)}h {int(minutes)}m"
    except Exception:
        uptime_str = "Unknown"
        
    return JSONResponse({
        "app": {
            "total_users": total_users,
            "active_users": active_users,
            "logged_in_users": logged_in_users,
            "active_connections": active_ws,
            "users_with_automation": users_with_automation,
            "strategies_working": strategies_count
        },
        "crashes": error_logs,
        "pipeline": {
            "version": VERSION,
            "uptime": uptime_str,
            "git_log": git_log
        }
    })

@app.get("/api/admin/users/{uid}/activity")
async def admin_user_activity(uid: int, request: Request):
    user_id = await resolve_authenticated_user_id(request)
    if not user_id: return JSONResponse({"error": "Unauthorized"}, 401)
    
    admin_user = await Database.get_user_by_id(user_id)
    if not admin_user or not admin_user["is_admin"]:
        return JSONResponse({"error": "Unauthorized"}, 403)
        
    from state import USER_CACHES, USER_STATES
    cache = USER_CACHES.get(str(uid), {})
    state = USER_STATES.get(uid)
    
    logs = await Database.get_user_logs(uid, 50)
    
    state_data = {}
    if state:
        state_data = {
            "automation_enabled": state.automation_enabled,
            "active_strategies": state.active_strategies,
            "live_pnl_today": state.live_pnl_today,
            "paper_pnl_today": state.paper_pnl_today,
            "live_trades_today": state.live_trades_today,
            "paper_trades_today": state.paper_trades_today
        }
        
    return JSONResponse({
        "cache": {
            "is_auth": cache.get("is_auth", False),
            "funds": cache.get("funds", {}),
            "positions": cache.get("positions", []),
            "orders": cache.get("orders", [])
        },
        "state": state_data,
        "logs": logs
    })

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    if not user_id: return JSONResponse({"error": "Unauthorized"}, 401)
    
    admin_user = await Database.get_user_by_id(user_id)
    if not admin_user or not admin_user["is_admin"]:
        return JSONResponse({"error": "Unauthorized"}, 403)

    conn = sqlite3.connect(Database.DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, username, is_admin, automation_enabled, is_active, created_at FROM users")
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    return JSONResponse(users)

@app.post("/api/admin/users/{uid}/toggle-status")
async def toggle_user_status(uid: int, request: Request):
    user_id = await resolve_authenticated_user_id(request)
    admin_user = await Database.get_user_by_id(user_id)
    if not admin_user or not admin_user["is_admin"]:
        return JSONResponse({"error": "Unauthorized"}, 403)
        
    # Prevent admin from deactivating themselves
    if int(user_id) == uid:
        return JSONResponse({"success": False, "message": "Cannot deactivate your own admin account"})
        
    data = await request.json()
    is_active = data.get("is_active", True)
    
    await Database.set_user_active_status(uid, is_active)

    # A3: on deactivation, synchronously purge the user's in-memory runtime so every
    # background loop excludes them on its next tick (no more live orders / trailing /
    # token-refresh against a deactivated user's broker session).
    if not is_active:
        state.purge_user_runtime(uid)

    return JSONResponse({"success": True})

@app.post("/api/admin/users")
async def admin_add_user(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    user = await Database.get_user_by_id(user_id)
    if not user or not user["is_admin"]: return JSONResponse({"error": "Unauthorized"}, 403)
    
    data = await request.json()
    new_id = await Database.create_user(data.get("username"), 
        data.get("password"), 
        is_admin=data.get("is_admin", 0)
    )
    if new_id: return {"success": True, "id": new_id}
    return {"success": False, "message": "User already exists"}

@app.delete("/api/admin/users/{id}")
async def admin_delete_user(id: int, request: Request):
    user_id = await resolve_authenticated_user_id(request)
    user = await Database.get_user_by_id(user_id)
    if not user or not user["is_admin"]: return JSONResponse({"error": "Unauthorized"}, 403)
    
    # A3: drop the user's in-memory runtime first so background loops stop touching them.
    state.purge_user_runtime(id)

    # D5: delete the user AND every dependent-table row referencing them in one transaction
    # (see Database.delete_user_cascade) — not just users/user_states — so no trade/pnl/log
    # history rows are left orphaned referencing a deleted user id.
    Database.delete_user_cascade(id)
    return {"success": True}

@app.post("/api/admin/users/{id}/password")
async def admin_change_password(id: int, request: Request):
    user_id = await resolve_authenticated_user_id(request)
    user = await Database.get_user_by_id(user_id)
    if not user or not user["is_admin"]: return JSONResponse({"error": "Unauthorized"}, 403)
    
    data = await request.json()
    new_password = data.get("new_password")
    if not new_password or len(new_password) < 6:
        return {"success": False, "message": "Password must be at least 6 characters"}
        
    await Database.update_password(id, new_password)
    return {"success": True, "message": "Password updated successfully"}

@app.post("/api/admin/users/{id}/pin")
async def admin_change_pin(id: int, request: Request):
    user_id = await resolve_authenticated_user_id(request)
    user = await Database.get_user_by_id(user_id)
    if not user or not user["is_admin"]: return JSONResponse({"error": "Unauthorized"}, 403)
    
    data = await request.json()
    new_pin = data.get("pin")
    if not new_pin or len(str(new_pin)) != 4:
        return {"success": False, "message": "PIN must be exactly 4 digits"}
        
    await Database.update_fyers_pin(id, str(new_pin))
    return {"success": True, "message": "PIN updated successfully"}

@app.get("/api/fyers/login_url")
async def get_fyers_login_url(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    user = await Database.get_user_by_id(user_id)
    if not user: return JSONResponse({"error": "Unauthorized"}, 401)

    # SaaS: Use user's own keys if available, otherwise fall back to Admin's Master App ID
    master_creds = await Database.get_master_app_credentials()
    client_id = user.get("fyers_client_id") or master_creds[0]
    secret = user.get("fyers_secret") or master_creds[1]
    if not client_id or not secret:
        return JSONResponse({"error": "No Master App ID configured. Admin must set up Fyers API keys first."}, 400)

    from fyers_apiv3 import fyersModel
    redirect_url = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret,
        redirect_uri=redirect_url,
        response_type='code',
        grant_type='authorization_code'
    )
    url = session.generate_authcode()
    # A2: bind the OAuth `state` to a signed, single-use, short-TTL nonce keyed to the
    # initiating user instead of the raw user_id (which any party could observe/guess and
    # replay to hijack another user's callback + session cookie).
    from urllib.parse import quote as _urlquote
    oauth_state = generate_oauth_state(user_id)
    url = url.replace("state=None", f"state={_urlquote(oauth_state)}")
    return {"url": url}

@app.get("/fyers/callback")
async def fyers_oauth_callback(request: Request):
    """
    Fyers OAuth redirect target. To use the auto-redirect flow:
      1. Set FYERS_REDIRECT_URI=https://<your-host>/fyers/callback in fyers-mcp-server/.env
      2. Register the same URL on https://myapi.fyers.in/ for your app
    The legacy manual paste flow (POST /api/submit-auth-code) continues to work.
    """
    # A2: when a `state` value is present it MUST be a valid, unexpired, single-use signed
    # nonce (see generate_oauth_state). We no longer trust a raw `state=user_id` at face value.
    state = request.query_params.get("state")
    state_present = bool(state and state != "None")
    if state_present:
        bound_uid = consume_oauth_state(state)
        if bound_uid is None:
            print("⚠️ /fyers/callback rejected: invalid/expired/replayed OAuth state", flush=True)
            return RedirectResponse(url="/login?reason=invalid_state")
        user_id = bound_uid
    else:
        # No state (e.g. cookies survived the redirect): fall back to the authenticated cookie.
        user_id = await resolve_authenticated_user_id(request)
    auth_code = request.query_params.get("auth_code")

    if not user_id:
        print("⚠️ /fyers/callback hit without user_id cookie or state", flush=True)
        return RedirectResponse(url="/login?reason=session_expired")

    if not auth_code:
        err = request.query_params.get("error") or "no_auth_code"
        print(f"❌ /fyers/callback missing auth_code (error={err})", flush=True)
        return RedirectResponse(url=f"/?msg=Fyers+login+failed:+{err}")

    print(f"📥 /fyers/callback user={user_id} code={auth_code[:10]}...", flush=True)
    res = await _exchange_fyers_auth_code(user_id, auth_code)

    if res.get("success"):
        response = RedirectResponse(url="/?msg=Connected")
        if state_present:
            response.set_cookie(key="user_id", value=sign_user_id(user_id), max_age=86400 * 30, path="/", httponly=True, samesite="lax")
        return response

    safe_msg = (res.get("message") or "exchange_failed")[:80].replace(" ", "+")
    response = RedirectResponse(url=f"/?msg=Fyers+login+failed:+{safe_msg}")
    if state_present:
        response.set_cookie(key="user_id", value=sign_user_id(user_id), max_age=86400 * 30, path="/", httponly=True, samesite="lax")
    return response

@app.post("/api/user/settings")
async def save_settings(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    if not user_id:
        return JSONResponse({"success": False, "message": "Unauthorized"}, 401)
    
    data = await request.json()
    client_id = data.get("client_id")
    secret_id = data.get("secret_id")
    fyers_pin = data.get("fyers_pin", "")
    
    await Database.update_fyers_creds(user_id, client_id, secret_id, fyers_pin)
    
    # Refresh context
    try:
        u_id_int = int(user_id)
        if u_id_int in USER_CONTEXTS:
            del USER_CONTEXTS[u_id_int]
    except Exception as e:
        print(f"Error clearing user context: {e}")
        
    return {"success": True}

@app.get("/api/user/settings")
async def get_settings(request: Request):
    user_id = await resolve_authenticated_user_id(request)
    user = await Database.get_user_by_id(user_id)
    if not user: return JSONResponse({"error": "Unauthorized"}, 401)
    master_creds = await Database.get_master_app_credentials()
    has_master = bool(master_creds[0] and master_creds[1])
    return {
        "client_id": user.get("fyers_client_id", ""),
        "secret_id": user.get("fyers_secret", ""),
        "fyers_pin": user.get("fyers_pin", ""),
        "has_master_app": has_master
    }

class AuthSubmission(BaseModel):
    code: str

@app.get("/api/login")
async def get_fyers_login_url_legacy(request: Request):
    """Handle the legacy GET /api/login call from app.js (v4.4.2 fix)."""
    client = await get_current_client(request)
    url = await api_queue.enqueue(2, client.get_login_url)
    return {"success": bool(url), "url": url}

@app.post("/api/submit-auth-code")
async def submit_auth_code(request: Request, data: AuthSubmission):
    """Receive auth code (or full redirect URL) and exchange for token (manual paste fallback)."""
    user_id = await resolve_authenticated_user_id(request)
    if not user_id:
        return JSONResponse({"success": False, "message": "Unauthorized"}, 401)
    print(f"📥 Received Auth Submission for User {user_id}", flush=True)
    try:
        code = data.code.strip()
        print(f"🔍 Auth code received (length={len(code)})", flush=True)

        # If the user pasted the full URL, extract the code
        if "auth_code=" in code:
            import urllib.parse as urlparse
            parsed = urlparse.urlparse(code)
            params = urlparse.parse_qs(parsed.query)
            if 'auth_code' in params:
                code = params['auth_code'][0]
                print(f"✂️ Extracted Code: {code[:10]}...", flush=True)

        res = await _exchange_fyers_auth_code(user_id, code)
        print(f"🏁 Exchange result: {res}", flush=True)
        return res
    except Exception as e:
        import traceback
        err_msg = f"Auth Submission Error: {e}\n{traceback.format_exc()}"
        print(f"❌ {err_msg}", flush=True)
        logger.error(err_msg)
        return {"success": False, "message": str(e)}

@app.post("/api/scripts/add")
async def add_script(request: Request, data: Dict):
    symbol = data.get("symbol", "").strip().upper()
    if not symbol: return {"success": False, "message": "Symbol required"}
    
    # Auto-format for common shorthand
    # 1. If no prefix, add NSE:
    if ":" not in symbol:
        symbol = f"NSE:{symbol}"
    
    # 2. If no suffix, check if it's a known index or option
    if "-" not in symbol:
        indices = ["NIFTY50", "NIFTYBANK", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIAVIX", "SENSEX", "NIFTYNXT50"]
        is_index = any(idx in symbol for idx in indices)
        # Options usually have long numeric strings like NIFTY26505...
        is_option = len(symbol) > 12 and any(char.isdigit() for char in symbol)
        
        if is_index:
            symbol = f"{symbol}-INDEX"
        elif not is_option:
            symbol = f"{symbol}-EQ"
    
    # Special case: SBI -> SBIN
    if "NSE:SBI-EQ" in symbol: symbol = "NSE:SBIN-EQ"
    if "NSE:BANKNIFTY-INDEX" in symbol: symbol = "NSE:NIFTYBANK-INDEX"
    if "NSE:BANKNIFTY-EQ" in symbol: symbol = "NSE:NIFTYBANK-INDEX"

    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    state.add_symbol(symbol)
    return {"success": True, "scripts": state.active_symbols, "formatted": symbol}

@app.get("/api/scripts")
async def get_scripts(request: Request):
    """Get currently tracked scripts/symbols."""
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    return {"success": True, "scripts": state.active_symbols, "enabled": getattr(state, "enabled_symbols", ["NSE:NIFTY50-INDEX"])}

@app.post("/api/scripts/toggle-auto-trade")
async def toggle_script_auto_trade(request: Request):
    data = await request.json()
    symbol = data.get("symbol", "")
    enabled = data.get("enabled", False)
    if not symbol: return {"success": False, "message": "Symbol required"}
    
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    
    enabled_list = getattr(state, "enabled_symbols", ["NSE:NIFTY50-INDEX"])
    if enabled and symbol not in enabled_list:
        enabled_list.append(symbol)
    elif not enabled and symbol in enabled_list:
        enabled_list.remove(symbol)
        
    state.enabled_symbols = enabled_list
    state.save()
    return {"success": True, "enabled": state.enabled_symbols}

@app.post("/api/scripts/remove")
async def remove_script(request: Request):
    data = await request.json()
    symbol = data.get("symbol", "")
    if not symbol: return {"success": False, "message": "Symbol required"}
    
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    state.remove_symbol(symbol)
    return {"success": True, "scripts": state.active_symbols}



# User-Specific Market Caches
USER_CACHES = state.USER_CACHES

def get_user_cache(user_id):
    return state.get_user_cache(user_id)

# Global Caches for specific workers
dashboard_cache = state.dashboard_cache
ai_trend_cache = state.ai_trend_cache # Cache for AI predictions to prevent rate-limits

# Global dependencies
_analysis_store = state._analysis_store

# Event loop reference for background tasks
main_loop = state.main_loop

# ── Static file serving with per-type cache control ─────────────────────────
# Replaces app.mount(StaticFiles) so we have full header control.
# Allow caching for JS, CSS, and other static assets to improve load times
_STATIC_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=86400",
}

@app.get("/static/{file_path:path}", include_in_schema=False)
async def serve_static(file_path: str):
    """Serve static files with aggressive caching."""
    full_path = os.path.join("static", file_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(file_path)[1].lower()
    headers = _STATIC_CACHE_HEADERS if ext in (".js", ".css", ".png", ".jpg", ".svg", ".json") else {}
    return FileResponse(full_path, headers=headers)


# Track active WebSocket connections
active_connections = state.active_connections

async def broadcast_log(msg: str, level: str = "info", user_id: int = None):
    """Send a log message to connected clients and store in DB."""
    import pytz
    import sys
    import traceback
    from datetime import datetime
    
    # Auto-heal hook: Print full tracebacks to stdout so the external VM orchestrator can catch them
    if level == "error":
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type is not None:
            tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            print(f"🏥 [VM-ORCHESTRATOR-HOOK] Traceback caught:\n{tb_str}", flush=True)

    ist = pytz.timezone('Asia/Kolkata')
    timestamp_ws = datetime.now(ist).strftime("%H:%M:%S")
    timestamp_db = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Asynchronously write to DB
    try:
        asyncio.create_task(Database.insert_log(level, msg, timestamp_db, user_id))
    except Exception as e:
        print(f"⚠️ DB log insert error: {e}")

    if not active_connections:
        return
    
    payload = {
        "type": "log",
        "msg": msg,
        "level": level,
        "time": timestamp_ws
    }
    
    disconnected = set()
    for ws in active_connections:
        # Route to specific user if user_id is provided, else broadcast to all
        if user_id is None or getattr(ws, "user_id", None) == user_id:
            try:
                await ws.send_text(orjson.dumps(payload).decode("utf-8"))
            except:
                disconnected.add(ws)
    
    for ws in disconnected:
        active_connections.discard(ws)





async def resolve_authenticated_user_id(request: Request) -> Optional[int]:
    """
    Resolve a trusted integer user id from the request's signed session cookie.

    Returns the verified user id, or None when the cookie is missing, forged, expired,
    or a legacy raw cookie past the migration grace period. This is the single point of
    truth for turning a `user_id` cookie into a trusted id — every route MUST use this
    instead of reading `request.cookies.get("user_id")` directly (see Phase 1 Item A1).
    """
    return resolve_user_id_from_cookie(request.cookies.get("user_id"))


async def get_current_client(request: Request, allow_guest: bool = False):
    """Resolve the FyersClient for the authenticated caller.

    Phase 2 Item A1: the guest/user-0 fallback is CLOSED by default. Any trading-critical
    endpoint (order placement, positions, funds, settings, automation toggles, quotes, etc.)
    that reaches this without a valid session identity now receives a 401 instead of a
    silently-scoped guest/user-0 context. The ONLY routes permitted to opt into the guest
    path pass ``allow_guest=True`` explicitly — currently the single genuinely-public,
    non-trading info endpoint ``GET /api/version`` (UI shell health/version poll that may
    fire before login). Do not add to this allowlist without a documented, non-trading reason.
    """
    user_id = await resolve_authenticated_user_id(request)
    if not user_id:
        if not allow_guest:
            raise HTTPException(status_code=401, detail="Unauthorized")
        user_id = 0 # Explicitly-allowlisted public/guest context only

    if user_id != 0:
        user = await Database.get_user_by_id(user_id)
        if not user or not user.get("is_active", True):
            raise HTTPException(status_code=401, detail="Unauthorized - Account deactivated")

    u_id = int(user_id)
    if u_id not in USER_CONTEXTS:
        USER_CONTEXTS[u_id] = FyersClient(user_id=u_id)

    return USER_CONTEXTS[u_id]


async def _exchange_fyers_auth_code(user_id, auth_code: str) -> Dict:
    """
    Shared helper to exchange a Fyers auth_code for an access token.
    Used by GET /fyers/callback (auto-redirect flow) and POST /api/submit-auth-code (manual paste).
    On success: persists token (FyersClient.set_auth_code -> Database.update_fyers_token),
    refreshes USER_CONTEXTS, marks user cache as authed, and restarts ws_feed.
    """
    if not user_id:
        return {"success": False, "message": "Unauthorized: no user_id"}

    try:
        u_id_int = int(user_id)
    except (TypeError, ValueError):
        return {"success": False, "message": "Invalid user_id"}

    # Drop cached client so it re-inits with the new token on next access
    USER_CONTEXTS.pop(u_id_int, None)

    client = FyersClient(user_id=u_id_int)
    res = await api_queue.enqueue(2, client.set_auth_code, auth_code)

    if res.get("success"):
        USER_CONTEXTS[u_id_int] = client
        try:
            cache = get_user_cache(user_id)
            cache["is_auth"] = True
            cache["login_attempts"] = 0  # Reset so market worker doesn't skip this user
        except Exception as e:
            print(f"⚠️ Failed to update user cache: {e}", flush=True)
            
        try:
            from state import USER_STATES
            from engine.notifier import trigger_webhook_background
            state_obj = USER_STATES.get(u_id_int)
            if state_obj and getattr(state_obj, 'webhook_url', None):
                trigger_webhook_background(state_obj.webhook_url, "Fyers connected manually.", title="Fyers Manual Login")
        except Exception as e:
            pass

        try:
            print(f"🔄 Restarting WS Feed for user {u_id_int} with new auth token...", flush=True)
            ws_feed.restart(client)
        except Exception as ws_err:
            print(f"❌ Error restarting WS Feed: {ws_err}", flush=True)

    return res


def _fyers_totp_creds_configured() -> bool:
    return bool(os.getenv("FYERS_USER_ID") and os.getenv("FYERS_PIN") and os.getenv("FYERS_TOTP_SECRET"))


async def _refresh_all_fyers_tokens(reason: str = "scheduled"):
    """
    Refresh Fyers tokens for all users via refresh_token (official API).
    The old Vagator V2 TOTP auto-login has been deprecated by Fyers.
    Safe to call repeatedly.
    """

    try:
        conn = sqlite3.connect(Database.DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE (fyers_client_id IS NOT NULL AND fyers_client_id != '') OR (fyers_access_token IS NOT NULL AND fyers_access_token != '')")
        user_ids = [row["id"] for row in c.fetchall()]
        # Fallback: env-only mode. If no per-user creds in DB but env has both client_id + secret_key,
        # auto_login can still run (uses env values); refresh all users so each gets a fresh token row.
        if not user_ids and os.getenv("FYERS_CLIENT_ID") and os.getenv("FYERS_SECRET_KEY"):
            c.execute("SELECT id FROM users")
            user_ids = [row["id"] for row in c.fetchall()]
            print(f"ℹ️ Fyers token refresh ({reason}): env-only mode, refreshing {len(user_ids)} user(s)", flush=True)
        conn.close()
    except Exception as e:
        print(f"❌ Fyers token refresh: DB query failed: {e}", flush=True)
        return

    if not user_ids:
        print(f"⏭️ Fyers token refresh ({reason}): no eligible users (no DB creds and no FYERS_CLIENT_ID/FYERS_SECRET_KEY in env)", flush=True)
        return

    print(f"🔄 Fyers token refresh ({reason}) for users: {user_ids}", flush=True)
    for uid in user_ids:
        try:
            if uid in USER_CONTEXTS:
                client = USER_CONTEXTS[uid]
            else:
                client = FyersClient(user_id=uid)
                USER_CONTEXTS[uid] = client

            # Check if existing token is still valid before forcing a refresh
            if reason in ["startup", "daily_0830_IST", "scheduled"]:
                is_valid = await api_queue.enqueue(2, client.is_authenticated)
                if is_valid:
                    print(f"✅ Existing token is still valid for user {uid}. Skipping refresh.", flush=True)
                    try:
                        from state import USER_STATES
                        from engine.notifier import trigger_webhook_background
                        state_obj = USER_STATES.get(uid)
                        if state_obj and getattr(state_obj, 'webhook_url', None):
                            trigger_webhook_background(state_obj.webhook_url, "Fyer's Connected automatically.", title="Fyers Auto-Login")
                    except Exception as e:
                        pass
                    
                    try:
                        ws_feed.restart(client)
                    except Exception as ws_err:
                        print(f"⚠️ WS restart failed for user {uid}: {ws_err}", flush=True)
                    continue

            # Strategy: try official refresh_token first (robust, ~14-day lifetime).
            # Fall back to vagator auto_login (TOTP) only if no refresh_token stored or it failed.
            success = await api_queue.enqueue(2, client.refresh_via_refresh_token)
            via = "refresh_token"
            if not success:
                print(f"↪️ refresh_token path failed for user {uid}; falling back to vagator auto_login", flush=True)
                success = await api_queue.enqueue(2, client.auto_login)
                via = "vagator/TOTP"

            if success:
                # Re-initialize the existing client in-place to load the new token and recreate model
                client.reinit_with_fresh_token()
                print(f"✅ Auto-refreshed Fyers token for user {uid} via {via}", flush=True)
                try:
                    from state import USER_STATES
                    from engine.notifier import trigger_webhook_background
                    state_obj = USER_STATES.get(uid)
                    if state_obj and getattr(state_obj, 'webhook_url', None):
                        trigger_webhook_background(state_obj.webhook_url, "Fyer's Connected automatically.", title="Fyers Auto-Login")
                except Exception as e:
                    pass
                try:
                    ws_feed.restart(client)
                except Exception as ws_err:
                    print(f"⚠️ WS restart after refresh failed for user {uid}: {ws_err}", flush=True)
            else:
                print(f"⚠️ All auto-refresh paths failed for user {uid} — manual login required", flush=True)
                try:
                    from state import USER_STATES
                    from engine.notifier import trigger_webhook_background
                    state_obj = USER_STATES.get(uid)
                    if state_obj and getattr(state_obj, 'webhook_url', None):
                        trigger_webhook_background(state_obj.webhook_url, "Fyers not connected automatically.", title="Fyers Auto-Login Failed")
                except Exception as e:
                    pass
        except Exception as e:
            print(f"❌ Auto-refresh error for user {uid}: {e}", flush=True)


async def fyers_token_refresh_scheduler():
    """
    Permanent fix for the 'every morning Fyers re-login' problem.

    Fyers daily tokens expire at midnight IST. This scheduler:
      1. Refreshes tokens once on app startup
      2. Sleeps until next 08:30 IST and refreshes again (well before 09:15 market open)
      3. Loops daily

    Requires FYERS_USER_ID, FYERS_PIN, FYERS_TOTP_SECRET in fyers-mcp-server/.env.
    Without those env vars, the scheduler logs a skip and exits the loop body cleanly.
    """
    # Small delay so app finishes booting before the first call
    await asyncio.sleep(5)
    try:
        await _refresh_all_fyers_tokens(reason="startup")
    finally:
        state._token_ready.set()
        print("🔓 Fyers startup token gate opened.", flush=True)

    while True:
        try:
            now = datetime.now(IST)
            target = now.replace(hour=8, minute=30, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            print(f"⏰ Next Fyers token refresh at {target.isoformat()} (in {int(wait_seconds)}s)", flush=True)
            await asyncio.sleep(wait_seconds)
            await _refresh_all_fyers_tokens(reason="daily_0830_IST")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ fyers_token_refresh_scheduler error: {e}. Sleeping 5min then retrying.", flush=True)
            await asyncio.sleep(300)



@app.post("/api/fyers/force-refresh")
async def force_fyers_refresh(request: Request):
    """
    Manually trigger a Fyers token refresh for the current user (or all users if admin).
    Tries refresh_token path first, falls back to TOTP auto-login.
    Useful when the scheduled 08:30 IST refresh fails or to recover a stale session.
    """
    user_id = await resolve_authenticated_user_id(request)
    if not user_id:
        return JSONResponse({"success": False, "message": "Unauthorized"}, 401)

    try:
        u_id_int = int(user_id)
    except (TypeError, ValueError):
        return JSONResponse({"success": False, "message": "Invalid user_id"}, 400)

    print(f"🔄 Manual force-refresh triggered by user {u_id_int}", flush=True)

    if u_id_int in USER_CONTEXTS:
        client = USER_CONTEXTS[u_id_int]
    else:
        client = FyersClient(user_id=u_id_int)
        USER_CONTEXTS[u_id_int] = client

    # Try refresh_token first, fallback to TOTP auto_login
    success = await api_queue.enqueue(2, client.refresh_via_refresh_token)
    via = "refresh_token"
    if not success:
        print(f"↪️ force-refresh: refresh_token failed for user {u_id_int}, trying TOTP auto_login", flush=True)
        success = await api_queue.enqueue(2, client.auto_login)
        via = "vagator/TOTP"

    if success:
        client.reinit_with_fresh_token()
        try:
            ws_feed.restart(client)
        except Exception as ws_err:
            print(f"⚠️ WS restart after force-refresh failed: {ws_err}", flush=True)
        print(f"✅ force-refresh succeeded for user {u_id_int} via {via}", flush=True)
        return {"success": True, "message": f"Token refreshed via {via}"}
    else:
        msg = "All refresh paths failed. Check FYERS_USER_ID/FYERS_PIN/FYERS_TOTP_SECRET in .env, or log in manually via the Fyers login button."
        print(f"❌ force-refresh failed for user {u_id_int}: {msg}", flush=True)
        return {"success": False, "message": msg}


@app.get("/api/admin/swarm-status")
async def get_swarm_status(request: Request):
    try:
        from models import Database
        agents = await Database.get_all_agent_configs()
        
        # Hydrate with latest learning logs
        for agent in agents:
            s_name = agent["strategy_name"]
            agent["active"] = True  # Always active for now
            logs = await Database.get_learning_logs(s_name, limit=1)
            if logs:
                agent["latest_insight"] = logs[0]["llm_analysis"]
                agent["last_learning_time"] = logs[0]["date"]
            else:
                agent["latest_insight"] = "No insights yet."
                agent["last_learning_time"] = None
                
        return JSONResponse({"success": True, "agents": agents})
    except Exception as e:
        logger.error(f"Error fetching swarm status: {e}")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/admin/restart-server")
async def admin_restart_server(request: Request):
    """
    Admin-only endpoint to gracefully restart the server process.
    Relies on systemd (Restart=always) to bring the app back up immediately.
    """
    user_id = await resolve_authenticated_user_id(request)
    if not user_id:
        return JSONResponse({"success": False, "message": "Unauthorized"}, 401)

    user = await Database.get_user_by_id(user_id)
    if not user or not user["is_admin"]:
        return JSONResponse({"success": False, "message": "Admin access required"}, 403)

    print(f"🔄 Admin {user.get('username', user_id)} triggered server restart", flush=True)
    await broadcast_log("🔄 Admin triggered server restart. Reconnecting in ~10 seconds...", "warning")

    # Schedule the kill after a short delay so the HTTP response can be sent first
    async def _delayed_kill():
        await asyncio.sleep(2)
        print("🔄 Executing server restart (SIGTERM)...", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_delayed_kill())
    return {"success": True, "message": "Server restarting in 2 seconds..."}


async def daily_restart_scheduler():
    """
    DEPRECATED: This scheduler has been disabled.
    The 8:55 AM daily restart relied on the Fyers Vagator V2 TOTP auto-login API
    which Fyers has permanently blocked (-1025 error). Token refresh is now handled
    by fyers_token_refresh_scheduler using the official refresh_token API.
    """
    print("⏭️ daily_restart_scheduler is DISABLED (Vagator V2 API deprecated)", flush=True)
    return  # Exit immediately, do not restart the server


async def hourly_status_scheduler():
    """
    Sends an hourly status report to Telegram for all users with configured webhooks.
    Only runs during market hours (9 AM to 4 PM IST).
    """
    await asyncio.sleep(15)  # Let the app fully boot first
    while True:
        try:
            now = datetime.now(IST)
            # Calculate time until the next hour (e.g., if 10:15, next is 11:00)
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            wait_seconds = (next_hour - now).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            
            # Guarantee we don't evaluate too early due to asyncio.sleep precision
            while datetime.now(IST) < next_hour:
                await asyncio.sleep(0.1)
                
            now_trigger = datetime.now(IST)
            # Only trigger during market hours: 9 AM (which covers 9:00 to 9:59) up to 15 (which covers 15:00 to 15:59)
            if 9 <= now_trigger.hour <= 15:
                from engine.notifier import trigger_webhook_background
                
                # Fetch memory usage safely
                import psutil
                process = psutil.Process()
                mem_mb = process.memory_info().rss / (1024 * 1024)
                
                for u_id, state_obj in USER_STATES.items():
                    if state_obj.webhook_url:
                        cache = get_user_cache(u_id)
                        is_auth = cache.get("is_auth", False)
                        auth_status = "✅ Connected" if is_auth else "❌ Disconnected"
                        active_trades = len(state_obj.active_auto_trades)
                        trades_today = state_obj.trades_today
                        pnl = state_obj.pnl_today
                        
                        strategies = ", ".join(state_obj.active_strategies) if state_obj.active_strategies else "None"
                        msg = (
                            f"⏱️ *Hourly System Status*\n\n"
                            f"🟢 *System:* Online ({mem_mb:.1f} MB RAM)\n"
                            f"🔐 *Fyers Auth:* {auth_status}\n"
                            f"💰 *PnL Today:* ₹{pnl:.2f}\n"
                            f"📈 *Active Trades:* {active_trades}\n"
                            f"📊 *Trades Taken:* {trades_today}/{state_obj.max_trades_per_day}\n"
                            f"🎯 *Active Strategies:* {strategies}"
                        )
                        trigger_webhook_background(state_obj.webhook_url, msg, title="Hourly Status Report")
                        
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ hourly_status_scheduler error: {e}", flush=True)
            await asyncio.sleep(60)


async def ai_oracle_scheduler():
    """
    Sends the Pre-Market AI Oracle bias to Telegram at 8:30 AM and hourly during market hours.
    """
    await asyncio.sleep(20)  # Let the app fully boot first
    while True:
        try:
            now = datetime.now(IST)
            if now.minute < 30:
                next_trigger = now.replace(minute=30, second=0, microsecond=0)
            else:
                next_trigger = (now + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
                
            wait_seconds = (next_trigger - now).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            
            # Guarantee we don't evaluate too early due to asyncio.sleep precision
            while datetime.now(IST) < next_trigger:
                await asyncio.sleep(0.1)
                
            now_trigger = datetime.now(IST)
            
            # Skip if weekend or holiday
            from state import get_holiday_reason
            if get_holiday_reason() is not None:
                continue
                
            h = now_trigger.hour
            m = now_trigger.minute
            
            should_trigger = False
            # Trigger at exactly 8:30 AM or between 9:30 AM and 3:30 PM (15:30)
            if h == 8 and m == 30:
                should_trigger = True
            elif 9 <= h <= 15 and m == 30:
                should_trigger = True
                
            if should_trigger:
                from workers.news_worker import news_worker
                from state import USER_STATES
                from engine.notifier import trigger_webhook_background
                
                summary = news_worker.last_summary
                if "Waiting" in summary.get("summary", ""):
                    await news_worker.update_summary()
                    summary = news_worker.last_summary
                    
                trend = summary.get("trend", "NEUTRAL")
                bias_msg = summary.get("summary", "No summary available.")
                
                msg = (
                    f"🔮 *Pre-Market AI Oracle*\n\n"
                    f"🧠 *Overall Bias:* {trend}\n\n"
                    f"📰 *Analysis:*\n{bias_msg}"
                )
                
                for u_id, state_obj in USER_STATES.items():
                    if getattr(state_obj, 'use_ai_oracle', False) and state_obj.webhook_url:
                        trigger_webhook_background(state_obj.webhook_url, msg, title="AI Oracle Report")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ ai_oracle_scheduler error: {e}", flush=True)
            await asyncio.sleep(60)


# Throttle for the "Data Feed Disconnected" alert so a persistent disconnect does not
# spam the user every 30s. Holds the epoch seconds of the last alert sent (0 = never).
_last_feed_disconnect_alert = 0.0


async def ws_connection_monitor():
    """
    Constantly monitors the Fyers WebSocket connection during market hours.
    If it dies silently without triggering on_close (is_connected() == False but _started == True),
    it automatically restarts the connection and sends an alert.

    Guards against false alarms: only runs when the market SHOULD be open
    (is_market_open() excludes weekends + NSE holidays + out-of-hours), only alerts when a
    user is genuinely Fyers-authenticated (is_auth), and throttles repeat alerts.
    """
    await asyncio.sleep(60)  # Wait for full initialization
    from engine.ws_feed import ws_feed
    from engine.notifier import trigger_webhook_background
    
    while True:
        try:
            await asyncio.sleep(30)

            # Only monitor when the market SHOULD be open. is_market_open() excludes weekends,
            # NSE holidays, AND out-of-market-hours — so no "feed disconnected" alert fires when
            # no live feed is even expected (fixes spurious weekend/holiday alerts).
            if state.is_market_open():
                # We check the raw state inside ws_feed
                if getattr(ws_feed, '_started', False) and not ws_feed.is_connected():
                    # Only act if at least one user is GENUINELY Fyers-authenticated right now.
                    # A stale/expired cached token can still satisfy get_access_token_for_ws(),
                    # which caused "disconnected" alerts when nobody was actually connected.
                    active_client = None
                    for u_id, client in USER_CONTEXTS.items():
                        if (client and USER_CACHES.get(str(u_id), {}).get("is_auth")
                                and hasattr(client, 'get_access_token_for_ws')
                                and client.get_access_token_for_ws()):
                            active_client = client
                            break

                    if active_client:
                        print("⚠️ WebSocket silent disconnect detected! Forcing restart...", flush=True)
                        ws_feed.restart(active_client)

                        # Throttle: send the alert at most once per 10 minutes so a persistent
                        # disconnect does not spam the user every 30s.
                        global _last_feed_disconnect_alert
                        now_ts = datetime.now(IST).timestamp()
                        if now_ts - _last_feed_disconnect_alert > 600:
                            _last_feed_disconnect_alert = now_ts
                            state_obj = get_user_state(active_client.user_id)
                            if state_obj and state_obj.webhook_url:
                                msg = "⚠️ <b>Fyers Data Feed Silently Disconnected</b>\n\nNo market updates received for over 20 seconds. Auto-restarting WebSocket feed."
                                trigger_webhook_background(state_obj.webhook_url, msg, title="Data Feed Alert")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ ws_connection_monitor error: {e}", flush=True)
            await asyncio.sleep(10)


async def daily_hard_exit_scheduler():
    """
    At 15:14 (3:14 PM) IST every day, forcibly exit ALL open positions across all users.
    This is a safety net to ensure no positions are carried overnight.
    """
    await asyncio.sleep(10)  # Let the app fully boot first
    while True:
        try:
            now = datetime.now(IST)
            target = now.replace(hour=15, minute=14, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            print(f"⏰ 3:14 PM hard exit scheduled at {target.isoformat()} (in {int(wait_seconds)}s)", flush=True)
            await asyncio.sleep(wait_seconds)

            print("🛑 3:14 PM HARD EXIT triggered — closing all positions for all users", flush=True)
            await broadcast_log("🛑 3:14 PM Hard Exit — Closing ALL open positions!", "error")

            for u_id, client in USER_CONTEXTS.items():
                try:
                    if not await api_queue.enqueue(2, client.is_authenticated):
                        continue

                    user_state = get_user_state(u_id)
                    cache = get_user_cache(u_id)
                    positions = cache.get("active_positions", [])

                    # If cache is empty, try fetching directly
                    if not positions:
                        try:
                            positions = await api_queue.enqueue(1, client.get_positions)
                            if isinstance(positions, dict):
                                positions = positions.get("netPositions", positions.get("overall", []))
                        except Exception as pos_err:
                            print(f"⚠️ Hard exit: Failed to fetch positions for user {u_id}: {pos_err}", flush=True)
                            continue

                    open_positions = [p for p in positions if abs(p.get("qty", p.get("netQty", 0))) > 0]

                    for pos in open_positions:
                        try:
                            qty = abs(pos.get("qty", pos.get("netQty", 0)))
                            symbol = pos.get("symbol", "")
                            side_val = pos.get("side", 1)
                            exit_side = "SELL" if side_val > 0 else "BUY"

                            print(f"🔴 Hard exit: {exit_side} {qty} x {symbol} for user {u_id}", flush=True)
                            await broadcast_log(f"🔴 Hard Exit: {exit_side} {qty} x {symbol}", "error", user_id=u_id)

                            result = await api_queue.enqueue(
                                1, client.place_order,
                                symbol=symbol,
                                qty=qty,
                                side=exit_side,
                                order_type="MARKET",
                                product="INTRADAY"
                            )
                            print(f"Hard exit result for {symbol}: {result}", flush=True)
                        except Exception as exit_err:
                            print(f"❌ Hard exit error for {pos.get('symbol', '?')}: {exit_err}", flush=True)

                    # Disable automation and mark hard exit
                    user_state.automation_enabled = False
                    user_state.hard_exit_triggered = True
                    user_state.active_auto_trades = []
                    user_state.save()

                except Exception as user_err:
                    print(f"❌ Hard exit error for user {u_id}: {user_err}", flush=True)

            await broadcast_log("🛑 3:14 PM Hard Exit complete. Automation disabled for all users.", "error")
            print("✅ 3:14 PM hard exit completed for all users", flush=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ daily_hard_exit_scheduler error: {e}. Retrying in 5 min.", flush=True)
            await asyncio.sleep(300)


@app.get("/api/status")
async def get_status(request: Request):
    """Get connection and auth status."""
    client = await get_current_client(request)
    authenticated = await api_queue.enqueue(2, client.is_authenticated)
    from engine.ws_feed import ws_feed
    return {
        "authenticated": authenticated,
        "feed_connected": ws_feed.is_connected(),
        "timestamp": datetime.now(IST).isoformat(),
        "market_open": True,
    }

async def get_nse_public_quotes() -> Dict[str, Dict]:
    """Helper that queries the NSE India indices API and maps Nifty 50 and India VIX."""
    try:
        cookies = await asyncio.get_event_loop().run_in_executor(None, _get_nse_cookies)
        raw = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _nse_get("https://www.nseindia.com/api/allIndices", cookies)
        )
        quotes = {}
        for d in raw.get("data", []):
            name = d.get("index", d.get("indexSymbol", ""))
            if name == "NIFTY 50":
                quotes["NSE:NIFTY50-INDEX"] = {
                    "lp": float(d.get("last", 0)),
                    "ch": float(d.get("variation", 0)),
                    "chp": float(d.get("percentChange", 0)),
                    "open": float(d.get("open", 0)),
                    "high": float(d.get("high", 0)),
                    "low": float(d.get("low", 0)),
                    "prev_close": float(d.get("previousClose", 0))
                }
            elif name == "INDIA VIX":
                quotes["NSE:INDIAVIX-INDEX"] = {
                    "lp": float(d.get("last", 0)),
                    "ch": float(d.get("variation", 0)),
                    "chp": float(d.get("percentChange", 0)),
                    "open": float(d.get("open", 0)),
                    "high": float(d.get("high", 0)),
                    "low": float(d.get("low", 0)),
                    "prev_close": float(d.get("previousClose", 0))
                }
        return quotes
    except Exception as e:
        print(f"[NSE Public Quotes] Scrape failed: {e}", flush=True)
        return {}

async def get_quotes_with_fallback(client, symbols: List[str], priority: int = 2) -> Dict[str, Dict]:
    """Get quotes from WS feed if available, otherwise fallback to REST API using Priority Queue."""
    if not symbols: return {}
    
    quotes = {}
    if ws_feed.is_connected():
        quotes = ws_feed.get_quotes_from_ws(symbols)
        
    missing = [s for s in symbols if s not in quotes or quotes[s].get("prev_close_price", 0) == 0]
    if missing:
        try:
            # We explicitly pass force_rest=True to bypass FyersClient internal websocket cache check
            rest_quotes = await api_queue.enqueue(priority, client.get_quotes, missing, force_rest=True)
            quotes.update(rest_quotes)
            
            # Inject fetched static data into WS feed so we don't keep fetching
            for sym, q_data in rest_quotes.items():
                ws_feed.inject_quote(sym, q_data)
                
            # If we had to fall back, ensure WS is subscribed
            if ws_feed.is_connected():
                ws_feed.subscribe(missing)
        except Exception as e:
            logger.error(f"Fallback quotes fetch failed: {e}")
            
    return quotes
@app.get("/api/fyers/status")
async def get_fyers_status(request: Request):
    """Get the current connection status of Fyers (REST and WS)."""
    client = await get_current_client(request)
    from engine.ws_feed import ws_feed
    ws_connected = ws_feed.is_connected()
    rest_authenticated = client.is_authenticated()
    return {
        "connected": rest_authenticated,
        "ws_connected": ws_connected,
        "reason": "OK" if rest_authenticated else "Token Expired or Invalid"
    }

@app.get("/api/quotes")
async def get_quotes_endpoint(request: Request, symbols: str):
    """Endpoint for retrieving quotes for a comma-separated list of symbols."""
    client = await get_current_client(request)
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not client.is_authenticated():
        # Fallback to cached/public quotes
        cache = get_user_cache(client.user_id)
        res = {}
        for sym in symbol_list:
            res[sym] = (cache.get("all_spots") or {}).get(sym, {})
        return res
    return await get_quotes_with_fallback(client, symbol_list)

@app.get("/api/spot")
async def get_spot(request: Request):
    """Get live NIFTY spot price and VIX."""
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    cache = get_user_cache(client.user_id)
    
    # Try Fyers client first if authenticated
    res = {}
    if client.is_authenticated():
        try:
            quotes = await get_quotes_with_fallback(client, state.active_symbols + ["NSE:INDIAVIX-INDEX"])
            if quotes:
                res = {symbol: quotes.get(symbol, {}) for symbol in state.active_symbols}
                res["vix"] = quotes.get("NSE:INDIAVIX-INDEX", {})
                return res
        except Exception as e:
            print(f"Error in Fyers spot fetch: {e}")
            
    # Fallback to cached public quotes
    for symbol in state.active_symbols:
        res[symbol] = (cache.get("all_spots") or {}).get(symbol, {})
        if not res[symbol] and symbol == "NSE:NIFTY50-INDEX":
            res[symbol] = cache.get("spot") or {}
    res["vix"] = cache.get("vix") or {}
    
    # Hard fallback: scrape directly if cache is empty
    if not res.get("NSE:NIFTY50-INDEX") or not res["NSE:NIFTY50-INDEX"].get("lp"):
        try:
            public_quotes = await get_nse_public_quotes()
            if public_quotes:
                for symbol in state.active_symbols:
                    res[symbol] = public_quotes.get(symbol, {})
                res["vix"] = public_quotes.get("NSE:INDIAVIX-INDEX", {})
        except:
            pass
    return res

@app.get("/api/auth-status")
async def auth_status(request: Request):
    """Check if we are authenticated."""
    try:
        client = await get_current_client(request)
        status = await api_queue.enqueue(2, client.is_authenticated)
        # Check if Fyers WebSocket feed is actively connected AND giving live prices
        from engine.ws_feed import ws_feed
        from workers.market_worker import get_user_cache
        cache = get_user_cache(client.user_id)
        last_up = cache.get("last_update", 0)
        from datetime import datetime
        now_ts = datetime.now(IST).timestamp()
        
        feed_connected = status and ws_feed.is_connected() and (now_ts - last_up < 15)
        
        # Check if user is admin and get username
        is_admin = False
        username = "Guest"
        if str(client.user_id).isdigit():
            user = await Database.get_user_by_id(int(client.user_id))
            if user:
                if user.get("is_admin"):
                    is_admin = True
                username = user.get("username", "Guest")
                
        # Holiday check
        holiday_reason = state.get_holiday_reason()
        return {
            "authenticated": status,
            "feed_connected": feed_connected,
            "is_admin": is_admin,
            "username": username,
            "market_holiday": holiday_reason is not None,
            "holiday_reason": holiday_reason
        }
    except Exception as e:
        return {"authenticated": False, "is_admin": False, "username": "Guest", "market_holiday": False, "holiday_reason": None}

def synthesize_15m_candles(candles_5m: List[Dict]) -> List[Dict]:
    """Group 5-minute REST API candles into 15-minute candles."""
    if not candles_5m:
        return []
    
    candles_15m = []
    current_15m = None
    
    for c in candles_5m:
        ts = c.get("timestamp", 0)
        if not ts: continue
        dt = datetime.fromtimestamp(ts, tz=IST)
        bucket_min = (dt.minute // 15) * 15
        bucket_dt = dt.replace(minute=bucket_min, second=0, microsecond=0)
        bucket_ts = int(bucket_dt.timestamp())
        
        h = c.get("high", c.get("h", 0))
        l = c.get("low", c.get("l", 0))
        o = c.get("open", c.get("o", 0))
        cl = c.get("close", c.get("c", 0))
        v = c.get("volume", c.get("v", 0))
        
        if not current_15m or current_15m["timestamp"] != bucket_ts:
            if current_15m:
                candles_15m.append(current_15m)
            current_15m = {"timestamp": bucket_ts, "open": o, "high": h, "low": l, "close": cl, "volume": v}
        else:
            current_15m["high"] = max(current_15m["high"], h)
            current_15m["low"] = min(current_15m["low"], l)
            current_15m["close"] = cl
            current_15m["volume"] += v
            
    if current_15m:
        candles_15m.append(current_15m)
        
    return candles_15m

async def get_analysis(symbol="NSE:NIFTY50-INDEX", client=None):
    """
    Core analysis logic for a specific symbol.
    Fetches historical data, detects levels, and generates signals.
    """
    if not client:
        # Fallback to a default client if needed (e.g. for background shared tasks)
        from fyers_client import FyersClient
        client = FyersClient()
    state = get_user_state(client.user_id)
    now = datetime.now(IST)
    now_ts = now.timestamp()
    
    # 60-second cache to respect Fyers API limits
    if symbol in _analysis_store:
        acache = _analysis_store[symbol]
        if acache:
            cache_time = datetime.fromtimestamp(acache.get("timestamp", 0), tz=IST)
            if cache_time.date() == now.date() and (now_ts - acache.get("timestamp", 0) < 60):
                # Inject live prices from WS into the cached data to ensure sub-ms latency
                try:
                    quotes = await get_quotes_with_fallback(client, [symbol, "NSE:INDIAVIX-INDEX", "NSE:NIFTYBANK-INDEX", "NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"])
                    if quotes:
                        spot_data = quotes.get(symbol)
                        vix_data = quotes.get("NSE:INDIAVIX-INDEX")
                        bnf_data = quotes.get("NSE:NIFTYBANK-INDEX")
                        if spot_data and spot_data.get("lp", 0) > 0:
                            acache["data"]["spot"] = spot_data.get("lp", 0)
                            acache["data"]["chp"] = spot_data.get("chp", 0.0)
                            acache["data"]["ch"] = spot_data.get("ch", 0.0)
                            acache["data"]["day_high"] = spot_data.get("high_price", 0)
                            acache["data"]["day_low"] = spot_data.get("low_price", 0)
                        if vix_data and vix_data.get("lp", 0) > 0:
                            acache["data"]["vix"] = vix_data.get("lp", 0)
                        if bnf_data and bnf_data.get("lp", 0) > 0:
                            acache["data"]["bnf_spot"] = bnf_data.get("lp", 0)
                        if "heavyweights" in acache["data"]:
                            for hw in acache["data"]["heavyweights"]:
                                hw_data = quotes.get(hw["symbol"])
                                if hw_data and hw_data.get("lp", 0) > 0:
                                    hw["lp"] = hw_data.get("lp", 0)
                except Exception as e:
                    print(f"⚠️ Error injecting live prices into cache: {e}")
                
                return acache["data"]

    try:
        # Fetch spot and VIX using WS with fallback
        quotes = await get_quotes_with_fallback(client, [symbol, "NSE:INDIAVIX-INDEX"])
        spot_data = quotes.get(symbol)
        vix_data = quotes.get("NSE:INDIAVIX-INDEX")

        # Parallelize historical candle fetches
        # Use get_historical instead of get_candles
        tasks = [
            api_queue.enqueue(2, client.get_historical, symbol, "60", days_back=3),  # 1H candles
            api_queue.enqueue(2, client.get_historical, symbol, "5", days_back=4),   # 5M candles
            api_queue.enqueue(2, client.get_historical, symbol, "D", days_back=10),  # Daily candles
            api_queue.enqueue(2, client.get_historical, symbol, "1", days_back=1),   # 1M candles
        ]
        
        candles_1h, candles_5m, candles_daily, candles_1m = await asyncio.gather(*tasks)

        if not candles_1h or not candles_5m:
            # Historical fetch failed (usually a Fyers rate-limit cooldown at market open).
            # Serve the LAST cached analysis (even if stale) so the dashboard keeps showing the
            # trend/regime instead of hanging on "loading".
            _stale = _analysis_store.get(symbol, {}).get("data")
            return _stale if _stale else None

        # Derive spot from quotes or fallback to latest candle close
        if spot_data and spot_data.get("lp", 0) > 0:
            spot = spot_data.get("lp", 0)
        elif candles_5m:
            spot = candles_5m[-1].get("close", 0)
        else:
            return None
        
        vix = (vix_data or {}).get("lp", 15.0)

        # Run signal engine
        result = generate_signals(candles_1h, candles_5m, spot, candles_daily, vix, symbol, candles_1m)

        # Find nearest expiry
        expiry = None
        if not expiry:
            try:
                expiry = await api_queue.enqueue(2, client.find_nearest_expiry, spot, symbol)
            except:
                expiry = None
        result["expiry"] = expiry
        
        # Option Chain Analysis for AI
        if expiry:
            try:
                # Fetch 5 strikes on each side of ATM for OI analysis (base_symbol MUST be the
                # symbol under analysis — omitting it defaulted every call to the NIFTY50 chain,
                # feeding wrong OI to the AI for stocks and adding a redundant NIFTY50 fetch).
                oc_data = await api_queue.enqueue(2, client.get_option_chain_strikes, spot, expiry["code"], 5, base_symbol=symbol)
                result["option_chain"] = oc_data
            except Exception as e:
                logger.error(f"Option Chain Fetch Error: {e}")
                result["option_chain"] = None
        else:
            result["option_chain"] = None

        # Add daily change data and intraday high/low for AI trend analysis
        result["chp"] = spot_data.get("chp", 0.0) if spot_data else 0.0
        result["ch"] = spot_data.get("ch", 0.0) if spot_data else 0.0
        result["day_high"] = spot_data.get("high_price", 0) if spot_data else 0
        result["day_low"] = spot_data.get("low_price", 0) if spot_data else 0
        result["open_price"] = spot_data.get("open_price", 0) if spot_data else 0
        result["prev_close"] = spot_data.get("prev_close_price", 0) if spot_data else 0

        # Add 3-day summary for AI
        try:
            last_3_days = candles_daily[-3:] if len(candles_daily) >= 3 else candles_daily
            summary = []
            for i, c in enumerate(last_3_days):
                summary.append(f"Day {i+1} (High: {c.get('high', c.get('h', 0))}, Low: {c.get('low', c.get('l', 0))})")
            result["three_day_summary"] = " | ".join(summary)
        except Exception as e:
            result["three_day_summary"] = "Not Available"

        # ═══ MULTI-TIMEFRAME INTRADAY TREND REGIME ═══
        # Uses CandleBuilder (WebSocket-based, zero API calls) + AI confirmation.
        try:
            from engine.candle_builder import candle_builder
            from engine.key_levels import detect_intraday_trend

            # Pull candles from in-memory CandleBuilder (instant, no API call)
            cb_5m = candle_builder.get_candles(symbol, "5m")
            cb_15m = candle_builder.get_candles(symbol, "15m")
            cb_1h = candle_builder.get_candles(symbol, "1h")

            # Merge REST candles with Live candles to eliminate "warm-up" period
            merged_5m = candles_5m.copy() if candles_5m else []
            merged_1h = candles_1h.copy() if candles_1h else []
            
            # Synthesize 15m from REST 5m, then merge
            rest_15m = synthesize_15m_candles(candles_5m)
            merged_15m = rest_15m.copy()
            
            # Simple merge: append live candles that are newer than the last REST candle
            if cb_5m and merged_5m:
                last_rest_ts = merged_5m[-1].get("timestamp", 0)
                merged_5m.extend([c for c in cb_5m if c.get("timestamp", 0) > last_rest_ts])
            elif cb_5m: merged_5m = cb_5m
                
            if cb_15m and merged_15m:
                last_rest_ts = merged_15m[-1].get("timestamp", 0)
                merged_15m.extend([c for c in cb_15m if c.get("timestamp", 0) > last_rest_ts])
            elif cb_15m: merged_15m = cb_15m
                
            if cb_1h and merged_1h:
                last_rest_ts = merged_1h[-1].get("timestamp", 0)
                merged_1h.extend([c for c in cb_1h if c.get("timestamp", 0) > last_rest_ts])
            elif cb_1h: merged_1h = cb_1h

            # ALWAYS compute multi_tf since we have REST data
            multi_tf = detect_intraday_trend(merged_5m, merged_15m, merged_1h)
            # Fetch AI Confirmation unconditionally
            ai_simple = {"trend": "NEUTRAL", "strength": 50, "rationale": "Pending...", "ai_status": "skipped", "cached": False}
            try:
                ai_simple = await ai_engine.get_simple_trend(
                    scrip_name="NIFTY 50",
                    spot=spot,
                    vix=vix,
                    chp=result.get("chp", 0),
                )
                print(f"🤖 AI Simple Trend (LIVE): {ai_simple.get('trend')} ({ai_simple.get('strength')}%) - {ai_simple.get('rationale')}", flush=True)
            except Exception as ai_err:
                print(f"⚠️ AI Simple Trend Error: {ai_err}. Defaulting to NEUTRAL.", flush=True)
                ai_simple = {"trend": "NEUTRAL", "strength": 50, "rationale": f"AI Error: {str(ai_err)[:60]}", "ai_status": "error", "cached": False}

            # Final regime decision: MATH IS PRIMARY. AI can only CONFIRM or trigger NEUTRAL.
            # SAFETY: AI must NEVER override math to the opposite direction.
            # This prevents the critical bug where AI hallucinated BULLISH while market was BEARISH.
            math_trend = multi_tf["trend"]
            ai_trend = ai_simple.get("trend", "NEUTRAL")
            
            if math_trend in ("BULLISH", "BEARISH"):
                if ai_trend == math_trend:
                    # BEST CASE: Math and AI agree → Strong conviction
                    final_trend = math_trend
                    final_strength = min(100, max(multi_tf["strength"], ai_simple.get("strength", 70)))
                    final_rationale = f"[CONFIRMED] Math + AI agree: {math_trend}. {multi_tf['rationale']}"
                elif ai_trend == "NEUTRAL":
                    # AI is uncertain but math has a direction → Use math with reduced confidence
                    final_trend = math_trend
                    final_strength = max(50, multi_tf["strength"] - 15)
                    final_rationale = f"[MATH] {multi_tf['rationale']} (AI uncertain)"
                else:
                    # CONFLICT: Math says one thing, AI says opposite → DEFAULT TO NEUTRAL (Capital Protection)
                    # This is the critical safety fix — NEVER trust AI over math blindly
                    final_trend = "NEUTRAL"
                    final_strength = 40
                    final_rationale = f"[CONFLICT] Math={math_trend} vs AI={ai_trend}. Defaulting to NEUTRAL for capital protection."
                    print(f"⚠️ SAFETY: Math({math_trend}) ≠ AI({ai_trend}). Blocking trades (Capital Protection).", flush=True)
            elif ai_trend in ("BULLISH", "BEARISH") and math_trend == "NEUTRAL":
                # Math is neutral but AI has opinion → Use AI with LOW confidence only
                final_trend = ai_trend
                final_strength = min(55, ai_simple.get("strength", 50))
                final_rationale = f"[AI WEAK] Math neutral, AI leans {ai_trend} (low confidence). {ai_simple.get('rationale', '')}"
            else:
                # Both neutral → Stay neutral
                final_trend = "NEUTRAL"
                final_strength = multi_tf["strength"]
                final_rationale = f"[MATH] {multi_tf['rationale']}"

            result["trend"] = {
                "trend": final_trend,
                "strength": final_strength,
                "rationale": final_rationale,
                "tf_1h": multi_tf.get("tf_1h", {}),
                "tf_15m": multi_tf.get("tf_15m", {}),
                "tf_5m": multi_tf.get("tf_5m", {}),
                "ai_trend": ai_simple.get("trend", "NEUTRAL"),
                "ai_status": ai_simple.get("ai_status", "skipped"),
                "ai_rationale": ai_simple.get("rationale", ""),
            }
            print(f"📊 REGIME: {final_trend} ({final_strength}%) | 1H:{multi_tf.get('tf_1h',{}).get('bias','?')} | 15m:{multi_tf.get('tf_15m',{}).get('bias','?')} | 5m:{multi_tf.get('tf_5m',{}).get('bias','?')} | AI:{ai_simple.get('trend','?')}", flush=True)

        except Exception as e:
            print(f"⚠️ Multi-TF Trend Error: {e}. Falling back to old AI trend.", flush=True)
            # Graceful fallback: use old AI trend method
            try:
                ai_trend = await ai_engine.get_ai_trend(symbol, result)
                result["trend"] = ai_trend
            except Exception as e2:
                print(f"⚠️ Fallback AI trend also failed: {e2}", flush=True)

        # Filter OBs and FVGs strictly near Key Levels
        filtered_obs = []
        for ob in result.get("order_blocks", []):
            is_near = False
            for kl in result.get("key_levels", []):
                if abs(ob["top"] - kl["price"]) / kl["price"] < 0.004 or \
                   abs(ob["bottom"] - kl["price"]) / kl["price"] < 0.004:
                    is_near = True
                    break
            if is_near: filtered_obs.append(ob)
        
        filtered_fvgs = []
        for fvg in result.get("fvgs", []):
            is_near = False
            for kl in result.get("key_levels", []):
                if abs(fvg["top"] - kl["price"]) / kl["price"] < 0.004 or \
                   abs(fvg["bottom"] - kl["price"]) / kl["price"] < 0.004:
                    is_near = True
                    break
            if is_near: filtered_fvgs.append(fvg)
        
        result["order_blocks"] = filtered_obs
        result["fvgs"] = filtered_fvgs
        result["active_order_blocks"] = [ob for ob in filtered_obs if ob.get("active")]
        result["candles_5m"] = candles_5m
        result["candles_1m"] = candles_1m
        
        # BANKNIFTY Correlation Data (v3.2.0)
        try:
            bnf_symbol = "NSE:NIFTYBANK-INDEX"
            bnf_quotes = await get_quotes_with_fallback(client, [bnf_symbol])
            bnf_data = bnf_quotes.get(bnf_symbol, {})
            result["bnf_spot"] = bnf_data.get("lp", 0)
            
            # Fetch 1H candles for BNF trend
            bnf_candles_1h = await api_queue.enqueue(2, client.get_historical, bnf_symbol, "60", days_back=2)
            from engine.key_levels import detect_trend
            bnf_trend_res = detect_trend(bnf_candles_1h) if bnf_candles_1h else {"trend": "NEUTRAL"}
            result["bnf_trend"] = bnf_trend_res.get("trend", "NEUTRAL")
        except Exception as e:
            logger.error(f"BNF Correlation Fetch Error: {e}")
            result["bnf_spot"] = 0
            result["bnf_trend"] = "UNKNOWN"
        
        # Heavyweight Monitoring (v3.3.0)
        try:
            heavy_symbols = ["NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"]
            h_quotes = await get_quotes_with_fallback(client, heavy_symbols)
            h_data_list = []
            for hs in heavy_symbols:
                q = h_quotes.get(hs, {})
                # Fetch trend for each heavyweight
                h_candles_1h = await api_queue.enqueue(2, client.get_historical, hs, "60", days_back=2)
                from engine.key_levels import detect_trend
                h_tr = detect_trend(h_candles_1h) if h_candles_1h else {"trend": "NEUTRAL"}
                h_data_list.append({
                    "symbol": hs,
                    "lp": q.get("lp", 0),
                    "trend": h_tr.get("trend", "NEUTRAL")
                })
            result["heavyweights"] = h_data_list
        except Exception as e:
            logger.error(f"Heavyweight Fetch Error: {e}")
            result["heavyweights"] = []

        # Pass PnL context for AI
        result["pnl_today"] = state.pnl_today
        result["profit_target_met"] = state.profit_target_met

        # Filter out skipped signals
        if result["signals"]:
            filtered_signals = []
            for sig in result["signals"]:
                sig["symbol"] = symbol
                bottom = round(sig.get('entry_zone_bottom', 0), 2)
                sig_id = f"{sig.get('type')}_{sig.get('reason')}_{bottom}"
                if sig_id not in state.skipped_signals:
                    filtered_signals.append(sig)
            
            # AI Confirmation for filtered signals
            confirmed_signals = []
            for sig in filtered_signals:
                if sig.get("type") in ("CALL", "PUT"):
                    sig["tech_confidence"] = sig.get("confidence")
                    ai_result = await ai_engine.confirm_signal(symbol, sig, result)
                    sig.update(ai_result)
                confirmed_signals.append(sig)
                
            result["signals"] = confirmed_signals

            # Multi-Strategy UI Integration: Show all active strategies on the dashboard
            if client:
                state = get_user_state(client.user_id)
                for strat in getattr(state, "active_strategies", []):
                    if "Strategy 1" not in strat:
                        result["signals"].append({
                            "type": "WAITING",
                            "direction": "NEUTRAL",
                            "strategy": strat,
                            "reason": f"Scanning live ticks for {strat}...",
                            "confidence": 0,
                            "advisory_only": True
                        })
            # Generate strike recommendations for the top signal
            if confirmed_signals and result.get("expiry") and result.get("option_chain"):
                top_sig = confirmed_signals[0]
                dte = result["expiry"].get("dte", 5)
                from engine.strikes import get_strike_recommendations
                try:
                    recs = get_strike_recommendations(result["option_chain"], top_sig["type"], spot, dte)
                    result["strike_recommendations"] = recs
                except Exception as e:
                    logger.error(f"Failed to generate strike recommendations: {e}")
                    result["strike_recommendations"] = []
            else:
                result["strike_recommendations"] = []
        else:
            result["strike_recommendations"] = []
        
        # Store in per-symbol cache
        _analysis_store[symbol] = {
            "data": result,
            "timestamp": now_ts
        }
        return result
        
    except Exception as e:
        print(f"⚠️ Analysis failed for {symbol}: {e}")
        return None

@app.get("/api/analysis")
async def get_analysis_api(request: Request, symbol: str = "NSE:NIFTY50-INDEX"):
    """Fetch analysis for a specific symbol."""
    client = await get_current_client(request)
    res = await get_analysis(symbol, client=client)
    if res: return res
    raise HTTPException(429, f"Rate limited or no data for {symbol}")

@app.get("/api/candles")
async def get_candles_api(request: Request, symbol: str = "NSE:NIFTY50-INDEX", resolution: str = "5", days: int = 3):
    """Fetch candles for a specific symbol."""
    client = await get_current_client(request)
    candles = await api_queue.enqueue(2, client.get_historical, symbol, resolution, days_back=days)
    return {"candles": candles}


@app.get("/api/test-signal")
async def test_signal():
    """Manually trigger a test signal to verify UI and History logic."""
    try:
        # Simulate a high-confidence signal
        test_sig = {
            "type": "CALL",
            "reason": "BREAKOUT ABOVE RESISTANCE (TEST)",
            "confidence": 98,
            "entry_zone_bottom": 24350.0,
            "entry_zone_top": 24380.0,
            "ai_confidence": 92,
            "ai_rationale": "High confluence of OB + FVG near Support. Trend is strongly bullish.",
            "ai_status": "confirmed",
            "advisory_only": False,
            "timestamp": datetime.now(IST).timestamp()
        }
        
        # Get current spot from cache
        spot = 24400.0
        
        # Mock Strike Selection
        trade_details = {
            "strike": "24400 CE (TEST)",
            "entry": 150.0,
            "sl": 138.0,
            "target": 174.0,
            "score": 95.5,
            "moneyness": "ATM",
            "type_label": "ATM CALL (OI Optimized)",
            "ltp": 150.0,
            "symbol": "NSE:NIFTY24APR24400CE"
        }
            
        # 1. Log to history
        from engine.logger import log_signal
        log_signal([test_sig], spot, "⚪ TEST SIMULATED", trade_details)
        
        # 2. Forcibly Inject into Global Analysis Store so UI picks it up
        _analysis_store["test"] = {
            "timestamp": datetime.now(IST).timestamp(),
            "data": {
                "signals": [test_sig],
                "strike_recommendations": [trade_details],
                "trend": {"trend": "BULLISH", "strength": 95},
                "key_levels": [],
                "order_blocks": [],
                "active_order_blocks": [],
                "fvgs": [],
                "bos_events": [],
                "spot": spot,
                "timestamp": datetime.now(IST).timestamp()
            }
        }
        
        return {"success": True, "message": "Test signal injected and logged."}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/api/option-chain")
async def get_option_chain(request: Request):
    """Get option chain around ATM."""
    client = await get_current_client(request)
    spot_data = client.get_quote("NSE:NIFTY50-INDEX")
    if not spot_data:
        raise HTTPException(500, "Could not fetch spot")
    spot = spot_data["lp"]

    expiry = client.find_nearest_expiry(spot, base_symbol)
    if not expiry:
        raise HTTPException(500, "No expiry found")

    chain = client.get_option_chain_strikes(spot, expiry["code"], 8)
    chain["expiry"] = expiry
    chain["spot"] = spot
    return chain

@app.get("/api/signal-history")
async def get_signal_history_api():
    """Get signal history from logger."""
    history = get_signal_history()
    return {"success": True, "history": history}


@app.post("/api/skip-signal")
async def skip_signal(request: Request, req: Dict):
    try:
        client = await get_current_client(request)
        state = get_user_state(client.user_id)
        idx = req.get("index")
        if idx is not None:
            # We record this in the automation state so it's not picked up again
            state.add_skipped_signal(f"manual_skip_{idx}_{datetime.now(IST).strftime('%H%M')}")
            
            # Log to history so it shows up in the UI
            try:
                from engine.logger import log_signal
                log_signal([{"type": "MANUAL", "reason": "User skipped signal", "confidence": 0}], 0, "⚪ SKIPPED (Manual)")
            except: pass
            
            return {"success": True}
        return {"success": False, "message": "Index missing"}
    except Exception as e:
        return {"success": False, "message": str(e)}


class OrderRequest(BaseModel):
    symbol: str
    qty: int
    side: str  # BUY or SELL
    order_type: str = "MARKET"
    product: str = "INTRADAY"
    limit_price: float = 0
    stop_price: float = 0
    sl_points: float = 12.0
    target_points: float = 0.0


@app.post("/api/order")
async def place_order(request: Request, order: OrderRequest):
    """Place a manual trade order with safety checks."""
    client = await get_current_client(request)
    
    # Policy check: BUY ONLY
    if order.side.upper() != "BUY":
        return {"success": False, "message": "⛔ SELL trades are blocked. Only BUY trades are allowed."}

    # Query user state for daily limits
    state = get_user_state(client.user_id)
    if state.order_lock.locked():
        return {"success": False, "message": "Order is currently being placed. Please wait."}

    # Phase 1 Item F1: the order_lock must wrap the ENTIRE critical section — the daily-limit
    # check, the regime-lockout checks, the broker place_order call, AND record_trade — as one
    # atomic unit. Previously the lock released right after the limit check, so two concurrent
    # requests could both pass the check and place more than max_trades_per_day trades (TOCTOU).
    async with state.order_lock:
        if state.trades_today >= state.max_trades_per_day:
            return {"success": False, "message": f"⛔ Daily trade limit reached ({state.max_trades_per_day} trades today). Manual order blocked."}

        # ═══════════════════════════════════════════
        # REGIME LOCKOUT: Block manual trades in flat/choppy markets & enforce alignment
        # ═══════════════════════════════════════════
        # B4: the former guard read `ai_trend_cache`, which is DEAD — grep confirms it has zero
        # write sites (only a `{}` declaration in state.py, an alias in app.py, and this single
        # read). `if trend_cache:` was therefore always falsy, so client.place_order /
        # state.record_trade / return were NEVER reached — manual orders silently no-op'd
        # (implicit None return). We route the guard off `state.market_regime`, the LIVE signal
        # actually written by regime_worker.py (values: TRENDING_UP/TRENDING_DOWN/CHOPPY_SIDEWAYS/
        # EVENT_RISK_AVOID/NEUTRAL/CLOSED). We FAIL CLOSED with an explicit structured rejection
        # when the regime is not a confirmed tradeable trend — regime_worker sets NEUTRAL on every
        # failure/fallback/insufficient-data path, so treating anything other than TRENDING_UP/DOWN
        # as a block also covers the empty/stale-signal case. The order-placement path is DEDENTED
        # out of the guard so a real result (rejection OR order outcome) is always returned, never
        # an unlabeled None.
        # [Phase 2 B4 escalation decision, recorded per Execute-Agent Instruction E2: option (a) —
        #  wire the guard to state.market_regime — chosen over option (b) permanent block, because
        #  it both restores manual trading (currently broken via the dead cache) and hardens it.]
        import state as _state_mod
        regime = (_state_mod.market_regime or "").upper()
        sym_u = order.symbol.upper()

        if regime not in ("TRENDING_UP", "TRENDING_DOWN"):
            return {"success": False, "message": f"⛔ Manual trade blocked: market regime is '{regime or 'UNKNOWN'}' — no confirmed tradeable trend (Zero-Trading lockout active)."}

        if regime == "TRENDING_UP" and "PE" in sym_u:
            return {"success": False, "message": "⛔ Manual trade blocked: regime is TRENDING_UP (only CALL/CE trades allowed)."}
        if regime == "TRENDING_DOWN" and "CE" in sym_u:
            return {"success": False, "message": "⛔ Manual trade blocked: regime is TRENDING_DOWN (only PUT/PE trades allowed)."}

        # Strict Position Check for NIFTY
        if order.symbol.startswith("NSE:NIFTY"):
            live_pos = await api_queue.enqueue(1, client.get_positions)
            if any((p.get("symbol") or "").startswith("NSE:NIFTY") and p.get("netQty", 0) != 0 for p in live_pos):
                return {"success": False, "message": "Active trade in progress. Close it before firing another."}

        result = await api_queue.enqueue(1, client.place_order,
            symbol=order.symbol,
            qty=order.qty,
            side=order.side,
            order_type=order.order_type,
            product=order.product,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            sl_points=order.sl_points,
            target_points=order.target_points
        )
        if result.get("success"):
            state.record_trade()
        return result

@app.get("/api/positions")
async def get_positions(request: Request):
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    state.check_daily_reset()
    positions = await api_queue.enqueue(1, client.get_positions)
    
    from datetime import datetime
    from engine.automation import IST
    now = datetime.now(IST)
    is_premarket = now.hour < 9 or (now.hour == 9 and now.minute < 15)
    has_open = any(p.get("netQty", 0) != 0 or p.get("qty", 0) != 0 for p in positions)
    
    # Internal Ghost PnL Guard: Ignore Fyers positions before 9:15 AM unless there are active holdings.
    # This prevents yesterday's PnL from flashing before Fyers clears it for the new day.
    if is_premarket and not has_open:
        positions = []
        overall_pnl = 0.0
    else:
        overall_pnl = sum(float(p.get("pl", 0) or 0) for p in positions)
    return {
        "netPositions": positions,
        "overallPnl": overall_pnl
    }


@app.get("/api/funds")
async def get_funds(request: Request):
    client = await get_current_client(request)
    return await api_queue.enqueue(1, client.get_funds)

@app.get("/api/orders")
async def get_orders(request: Request):
    client = await get_current_client(request)
    return await api_queue.enqueue(1, client.get_orders)


# ===== GLOBAL DATA WORKER =====
# _get_market_phase, POLL_CONFIG, and market_data_worker live in workers/market_worker.py


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    print(f"📡 Incoming WebSocket connection from {ws.client}", flush=True)
    await ws.accept()
    print(f"📡 WebSocket handshake accepted for {ws.client}", flush=True)
    
    # Identify user from cookies
    cookie_str = ws.headers.get("cookie", "")
    user_id_raw = None
    if "user_id=" in cookie_str:
        user_id_raw = cookie_str.split("user_id=")[1].split(";")[0].strip()
            
    if not user_id_raw:
        print("❌ WebSocket rejected: Missing user_id cookie")
        await ws.close(code=4001)
        return

    u_id_int = resolve_user_id_from_cookie(user_id_raw)
    if not u_id_int:
        print("❌ WebSocket rejected: Invalid user_id cookie signature")
        await ws.close(code=4001)
        return

    # Normalize to string for consistent key usage in USER_CACHES
    user_id = str(u_id_int)

    # Immediate initialization for this user if needed
    cache = get_user_cache(user_id)
    is_admin = False
    username = "Guest"
    try:
        user = await Database.get_user_by_id(u_id_int)
        if user:
            is_admin = bool(user.get("is_admin"))
            username = user.get("username", "Guest")
    except Exception as db_e:
        print(f"Error fetching user details in WS: {db_e}")

    if u_id_int in USER_CONTEXTS:
        client = USER_CONTEXTS[u_id_int]
        try:
            cache["is_auth"] = await api_queue.enqueue(2, client.is_authenticated)
        except Exception:
            cache["is_auth"] = False
    else:
        try:
            client = FyersClient(user_id=u_id_int)
            if client.is_authenticated():
                USER_CONTEXTS[u_id_int] = client
                cache["is_auth"] = True
                await broadcast_log(f"✅ Fyers connected for User {user_id}", "success")
            else:
                cache["is_auth"] = False
                await broadcast_log(f"⚠️ Fyers login required for User {user_id}", "warning")
        except Exception as e:
            print(f"Error during WS init for {user_id}: {e}")
            cache["is_auth"] = False

    ws.user_id = u_id_int
    active_connections.add(ws)
    last_spot_update = 0
    print(f"📡 WebSocket linked for User {user_id}. Total: {len(active_connections)}")
    
    try:
        while True:
            # Refresh local cache reference each loop
            cache = get_user_cache(user_id)
            is_auth = cache.get("is_auth", False)
            
            # Send Auth Status (Heartbeat) - Always send this
            from engine.ws_feed import ws_feed
            holiday_reason = state.get_holiday_reason()
            
            # Deem the feed "LIVE" only if we've received quotes recently
            last_up = cache.get("last_update", 0)
            now_ts = datetime.now(IST).timestamp()
            is_live_prices = is_auth and ws_feed.is_connected() and (now_ts - last_up < 15)

            payload_auth = {
                "type": "auth_status",
                "authenticated": is_auth,
                "feed_connected": is_live_prices,
                "is_admin": is_admin,
                "username": username,
                "message": "Connected" if is_auth else "Fyers Not Linked",
                "market_holiday": holiday_reason is not None,
                "holiday_reason": holiday_reason
            }
            await ws.send_text(orjson.dumps(payload_auth).decode("utf-8"))

            # Force initial data push even if no updates yet
            if not hasattr(ws, "_initial_push_done"):
                ws._initial_push_done = True
                user_state = get_user_state(user_id)
                payload_pos = {
                    "type": "positions", 
                    "positions": cache.get("active_positions", []), 
                    "total_pnl": cache.get("total_pnl", 0),
                    "active_trades": user_state.active_auto_trades,
                    "automation_stats": {
                        "trades_today": user_state.trades_today,
                        "pnl_today": user_state.pnl_today,
                        "max_trades": user_state.max_trades_per_day
                    }
                }
                await ws.send_text(orjson.dumps(payload_pos).decode("utf-8"))
                
                payload_orders = {"type": "orders", "orders": cache.get("orders", [])}
                await ws.send_text(orjson.dumps(payload_orders).decode("utf-8"))

            # Check if cache has new data
            if cache["last_update"] > last_spot_update:
                last_spot_update = cache["last_update"]
                
                # Prepare spots for all active symbols
                spot_data = cache.get("spot", {})
                if not spot_data:
                    spot_data = {"lp": 0, "ch": 0, "chp": 0}

                all_spots = {
                    "NSE:NIFTY50-INDEX": {
                        "lp": spot_data.get("lp", spot_data.get("ltp", 0)),
                        "change": spot_data.get("ch", 0),
                        "change_pct": spot_data.get("chp", 0)
                    }
                }
                
                # Add others if available in all_spots
                if "all_spots" in cache:
                    for sym, q in cache["all_spots"].items():
                        if sym not in all_spots:
                            all_spots[sym] = {
                                "lp": q.get("lp", q.get("ltp", 0)),
                                "change": q.get("ch", 0),
                                "change_pct": q.get("chp", 0)
                            }

                # Send Market Update
                payload_market = {
                    "type": "market_update",
                    "spots": all_spots,
                    "vix": {
                        "lp": cache["vix"].get("lp", cache["vix"].get("ltp", 0)) if cache["vix"] else 0,
                        "change": cache["vix"].get("chp", 0) if cache["vix"] else 0
                    }
                }
                await ws.send_text(orjson.dumps(payload_market).decode("utf-8"))
                
                # Send Account Data
                user_state = get_user_state(user_id)
                payload_acc = {
                    "type": "positions",
                    "positions": cache["active_positions"],
                    "active_positions": cache["active_positions"],
                    "total_pnl": cache.get("total_pnl", 0),
                    "active_trades": user_state.active_auto_trades,
                    "automation_stats": {
                        "trades_today": user_state.trades_today,
                        "pnl_today": user_state.pnl_today,
                        "max_trades": user_state.max_trades_per_day
                    }
                }
                await ws.send_text(orjson.dumps(payload_acc).decode("utf-8"))
                
                if cache["funds"]:
                    payload_funds = {
                        "type": "funds",
                        "funds": cache["funds"]
                    }
                    await ws.send_text(orjson.dumps(payload_funds).decode("utf-8"))

            await asyncio.sleep(0.8) # Sub-second push for real-time feel
    except Exception as e:
        print(f"📡 WebSocket error for User {user_id}: {e}")
    finally:
        active_connections.discard(ws)
        print(f"📡 WebSocket disconnected for User {user_id}. Remaining: {len(active_connections)}")

def _is_market_open() -> bool:
    return state.is_market_open()


@app.get("/api/automation")
async def get_automation(request: Request):
    client = await get_current_client(request)
    user_state = get_user_state(client.user_id)
    # Ensure daily counters are reset when a new day starts
    user_state.check_daily_reset()
    return {
        "enabled": user_state.automation_enabled,
        "trades_today": user_state.trades_today,
        "pnl_today": user_state.pnl_today,
        "max_trades": user_state.max_trades_per_day,
        "max_loss": user_state.max_loss_per_day,
        "market_regime": state.market_regime,
        "regime_reason": state.regime_reason
    }

@app.post("/api/automation/toggle")
async def toggle_automation(request: Request):
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    body = await request.json()
    enabled = body.get("enabled", False)
    
    if enabled:
        is_auth = await api_queue.enqueue(2, client.is_authenticated)
        if not is_auth:
            return {"success": False, "message": "Fyers account is not active. Please authenticate your Fyers account first."}
            
    state.automation_enabled = enabled
    state.save()
    return {"success": True, "enabled": state.automation_enabled}

@app.post("/api/automation/reset")
async def reset_automation(request: Request):
    """Manually reset daily trade counters (trades, PnL, skipped signals)."""
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    state.reset_day()
    await broadcast_log("🔄 Manual reset: Trade counters cleared (0/2)", "success")
    return {
        "success": True,
        "trades_today": state.trades_today,
        "pnl_today": state.pnl_today,
        "message": "Daily counters reset to 0"
    }

@app.get("/api/trading-config")
async def get_trading_config(request: Request):
    """Get current configurable trading parameters."""
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    return state.get_trading_config()

@app.get("/api/all-strategies")
async def get_all_strategies(request: Request):
    """Fetch all strategies dynamically for UI selection."""
    from models import Database
    configs = await Database.get_all_agent_configs()
    # If empty, return defaults
    if not configs:
        return [
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
    return [c['strategy_name'] for c in configs]

@app.post("/api/trading-config")
async def update_trading_config(request: Request):
    """Update configurable trading parameters from Settings UI."""
    client = await get_current_client(request)
    state = get_user_state(client.user_id)
    try:
        config = await request.json()
        state.update_trading_config(config)
        await broadcast_log(
            f"⚙️ Risk settings updated: {state.max_trades_per_day} trades, ₹{state.max_loss_per_day} max loss, ₹{state.daily_profit_target} target, SL trend={state.max_sl_trending}pts, SL range={state.max_sl_range}pts",
            "success"
        )
        return {"success": True, "config": state.get_trading_config()}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/learning/approve/{strategy_name}")
async def approve_learning(strategy_name: str, request: Request):
    """Approve a major strategy configuration change."""
    client = await get_current_client(request)
    if not client or not client.user_id:
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
        
    try:
        from models import Database
        from engine.notifier import send_webhook_alert
        import aiosqlite
        import os
        
        success = await Database.approve_agent_config(strategy_name)
        if success:
            async with aiosqlite.connect(Database.DB_NAME) as conn:
                cursor = await conn.execute("SELECT webhook_url FROM user_states WHERE user_id=?", (client.user_id,))
                row = await cursor.fetchone()
                webhook_url = row[0] if row else os.getenv("TELEGRAM_WEBHOOK", "")
                
            msg = f"<b>Approval Confirmed ✅</b>\nThe major parameter shift for <i>{strategy_name}</i> is now active."
            await send_webhook_alert(webhook_url, msg, title="🤖 AI Strategy Approved")
            
            await broadcast_log(f"✅ User approved major strategy update for {strategy_name}", "success")
            return {"success": True, "message": "Strategy updated successfully"}
        else:
            return {"success": False, "message": "No pending configuration found for this strategy"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/user-config")
async def get_user_config():
    """Missing endpoint called by frontend."""
    return {"success": True, "config": {"theme": "dark", "notifications": True}}

@app.get("/api/pnl-history")
async def get_pnl_history(request: Request):
    try:
        client = await get_current_client(request)
        if not client or not client.user_id:
            return {"success": False, "message": "Not authenticated"}
        
        # Query LIVE trade history from Database (never includes paper trades)
        from models import Database
        history = await Database.get_pnl_history(int(client.user_id), 6)
        
        # Also fetch paper history separately
        paper_history = await Database.get_paper_pnl_history(int(client.user_id), 6)
        
        # Get active live state for today's running PnL
        state = get_user_state(client.user_id)
        state.check_daily_reset()
        
        today_str = state.last_reset_date
        
        # Inject today's running PnL into the correct history based on paper mode
        history_dates = {item["date"] for item in history}
        if today_str not in history_dates:
            history.insert(0, {
                "date": today_str,
                "pnl": state.live_pnl_today,
                "trades": state.live_trades_today,
                "active": True
            })
        else:
            for item in history:
                if item["date"] == today_str:
                    item["active"] = True
                    item["pnl"] = state.live_pnl_today
                    item["trades"] = state.live_trades_today
                    break
                    
        paper_history_dates = {item["date"] for item in paper_history}
        if today_str not in paper_history_dates:
            paper_history.insert(0, {
                "date": today_str,
                "pnl": state.paper_pnl_today,
                "trades": state.paper_trades_today,
                "active": True
            })
        else:
            for item in paper_history:
                if item["date"] == today_str:
                    item["active"] = True
                    item["pnl"] = state.paper_pnl_today
                    item["trades"] = state.paper_trades_today
                    break
                    
        return {
            "success": True, 
            "history": history,
            "paper_history": paper_history,
            "is_paper_mode": state.paper_trading
        }
    except Exception as e:
        logger.error(f"❌ Error getting PnL history: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


@app.get("/api/health-agent-status")
async def health_agent_status():
    return HEALTH_AGENT_STATUS

@app.get("/api/health")
async def health_check():
    """Production health check — returns uptime, active users, memory, task status."""
    import resource
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    uptime_delta = now - SERVER_START_TIME
    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Memory usage (RSS in MB)
    mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    
    # Active user count
    active_users = len(USER_CONTEXTS)
    ws_connections = len(active_connections)
    
    # Auth status per user
    user_auth = {}
    for u_id in USER_CONTEXTS:
        cache = get_user_cache(u_id)
        user_auth[str(u_id)] = cache.get("is_auth", False)
    
    return {
        "status": "healthy",
        "version": VERSION,
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "started_at": SERVER_START_TIME.strftime("%Y-%m-%d %H:%M:%S IST"),
        "memory_mb": round(mem_mb, 1),
        "active_users": active_users,
        "ws_connections": ws_connections,
        "user_auth": user_auth,
        "market_open": _is_market_open(),
        "timestamp": now.isoformat()
    }

# ══════════════════════════════════════════════════════
# NSE INDIA MARKET DATA PROXY — Server-side fetch
# (avoids CORS issues from browser-direct calls)
# ══════════════════════════════════════════════════════
import urllib.request
import xml.etree.ElementTree as ET
try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET
import ssl
import certifi

# D2: TLS certificate verification for RSS/NSE fetches is ON. Build the context against
# certifi's CA bundle explicitly so a missing system CA on GCP Debian is fixed by shipping a
# trusted bundle rather than disabling verification wholesale (the previous CERT_NONE +
# check_hostname=False exposed these fetches to MITM tampering).
_RSS_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

_NSE_CACHE = {"indices": None, "news": None, "last_indices": None, "last_news": None}
_NSE_CACHE_TTL = 60  # seconds

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

def _nse_get(url: str, cookies: str = "") -> dict:
    req = urllib.request.Request(url)
    for k, v in _NSE_HEADERS.items():
        req.add_header(k, v)
    if cookies:
        req.add_header("Cookie", cookies)
    with urllib.request.urlopen(req, timeout=12, context=_RSS_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _rss_get(url: str) -> list:
    """Fetch and parse an RSS feed, using unverified SSL context to handle GCP CA issues."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=12, context=_RSS_SSL_CTX) as resp:
        raw = resp.read()
    root = dET.fromstring(raw)
    items = []
    for item in root.findall(".//item")[:8]:
        title = item.findtext("title", "").strip()
        pub   = item.findtext("pubDate", "").strip()
        link  = item.findtext("link", "").strip()
        # Also check <atom:link> or <guid> for link
        if not link:
            guid = item.findtext("guid", "").strip()
            if guid.startswith("http"):
                link = guid
        if title:
            items.append({"title": title, "pubDate": pub, "link": link})
    return items

def _get_nse_cookies() -> str:
    """Hit NSE home to get session cookies."""
    try:
        req = urllib.request.Request("https://www.nseindia.com/")
        for k, v in _NSE_HEADERS.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=12, context=_RSS_SSL_CTX) as resp:
            raw_cookies = resp.getheader("Set-Cookie") or ""
            # Extract key=value pairs
            parts = [p.strip().split(";")[0] for p in raw_cookies.split(",") if "=" in p.split(";")[0]]
            return "; ".join(parts)
    except Exception:
        return ""

@app.get("/api/market-data")
async def get_market_data():
    """Proxy endpoint: fetches live index prices from Yahoo Finance."""
    now = datetime.now(IST)
    last = _NSE_CACHE.get("last_indices")
    if _NSE_CACHE["indices"] and last and (now - last).total_seconds() < _NSE_CACHE_TTL:
        return JSONResponse(content=_NSE_CACHE["indices"])

    try:
        symbols_map = {
            "^NSEI": "NIFTY 50",
            "^NSEBANK": "NIFTY BANK",
            "^NSEMDCP50": "NIFTY MIDCAP 50",
            "^CNXIT": "NIFTY IT",
            "^CNXAUTO": "NIFTY AUTO",
            "^CNXFMCG": "NIFTY FMCG",
            "^CNXPHARMA": "NIFTY PHARMA",
            "^INDIAVIX": "INDIA VIX",
            "^CNXFIN": "NIFTY FINANCIAL SERVICES"
        }
        symbols_str = ",".join(symbols_map.keys())
        url = f"https://query1.finance.yahoo.com/v7/finance/spark?symbols={symbols_str}"
        
        def fetch_yahoo():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=12, context=_RSS_SSL_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
                
        raw = await asyncio.get_event_loop().run_in_executor(None, fetch_yahoo)
        
        filtered = []
        for item in raw.get("spark", {}).get("result", []):
            try:
                meta = item["response"][0]["meta"]
                sym = meta["symbol"]
                if sym not in symbols_map: continue
                price = meta.get("regularMarketPrice", 0)
                prev = meta.get("previousClose", price)
                change = price - prev
                pct = (change / prev * 100) if prev else 0
                filtered.append({
                    "name": symbols_map[sym],
                    "last": round(price, 2),
                    "change": round(change, 2),
                    "pct": round(pct, 2),
                    "open": prev,
                    "high": price,
                    "low": price,
                    "prev": prev
                })
            except Exception:
                continue

        # Mock market status since Yahoo doesn't return exactly the same string
        market_status = {"status": "Open" if 9 <= now.hour < 16 else "Closed"}
        result = {"indices": filtered, "market": market_status, "source": "Yahoo Finance", "fetched_at": now.strftime("%H:%M:%S IST")}
        _NSE_CACHE["indices"] = result
        _NSE_CACHE["last_indices"] = now
        return JSONResponse(content=result)
    except Exception as e:
        print(f"[YAHOO] Market data fetch failed: {e}")
        if _NSE_CACHE["indices"]:
            cached = dict(_NSE_CACHE["indices"])
            cached["cached"] = True
            return JSONResponse(content=cached)
        return JSONResponse(content={"error": str(e), "indices": []}, status_code=503)


@app.get("/api/market-news")
async def get_market_news():
    """Proxy endpoint: fetches latest Indian market news from Economic Times RSS."""
    now = datetime.now(IST)
    last = _NSE_CACHE.get("last_news")
    if _NSE_CACHE["news"] and last and (now - last).total_seconds() < 300:  # 5-min cache
        return JSONResponse(content=_NSE_CACHE["news"])

    feeds = [
        {"url": "https://feeds.feedburner.com/ndtvprofit-latest",          "source": "NDTV Profit"},
        {"url": "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms", "source": "Times of India"},
        {"url": "https://www.livemint.com/rss/markets",                     "source": "Livemint"},
    ]
    all_news = []
    for feed in feeds:
        try:
            items = await asyncio.get_event_loop().run_in_executor(None, lambda u=feed["url"]: _rss_get(u))
            for item in items[:5]:
                item["source"] = feed["source"]
                all_news.append(item)
        except Exception as ex:
            print(f"[NEWS] RSS fetch failed for {feed['source']}: {ex}")

    result = {"news": all_news[:12], "fetched_at": now.strftime("%H:%M:%S IST")}
    if all_news:
        _NSE_CACHE["news"] = result
        _NSE_CACHE["last_news"] = now
    return JSONResponse(content=result)


@app.get("/api/version")
async def get_version(request: Request):
    """Return dashboard version and system info."""
    # A1 allowlist: non-trading UI health/version poll may fire before login → guest OK.
    client = await get_current_client(request, allow_guest=True)
    state = get_user_state(client.user_id)
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    uptime_delta = now - SERVER_START_TIME
    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return {
        "version": VERSION,
        "name": "ControlN Trading Dashboard",
        "active_symbols": len(state.active_symbols),
        "automation": state.automation_enabled,
        "ai_active": ai_engine.enabled or ai_engine.openai_enabled,
        "ai_provider": "Both" if (ai_engine.enabled and ai_engine.openai_enabled) else "Gemini" if ai_engine.enabled else "ChatGPT" if ai_engine.openai_enabled else "None",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "started_at": SERVER_START_TIME.strftime("%H:%M:%S IST")
    }

# trailing_monitor, calculate_smart_sl, execute_auto_trade, and automation_loop
# live in workers/auto_trader.py


@app.get("/api/updates")
async def get_updates():
    """Read and return dailyupdates.md content as plain text."""
    updates_path = BASE_DIR / "dailyupdates.md"
    if not updates_path.exists():
        updates_path = PROJECT_ROOT / "dailyupdates.md"
        
    if updates_path.exists():
        try:
            with open(updates_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"status": "ok", "content": content}
        except Exception as e:
            return {"status": "error", "message": f"Failed to read file: {e}"}
    return {"status": "error", "message": "Updates file not found"}


@app.get("/api/logs")
async def get_logs(request: Request, limit: int = 100):
    """Fetch the latest system logs for the authenticated user (and global logs)."""
    try:
        user_id = await resolve_authenticated_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        logs = await Database.get_user_logs(int(user_id), limit)
        return {"status": "success", "logs": logs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching logs: {str(e)}")

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Handles incoming messages from Telegram Bot.
    """
    # Authenticate the webhook BEFORE parsing the body. Telegram sends the configured
    # secret in this header only if the webhook was registered via setWebhook with a
    # secret_token (see Phase 1 Item B1 — one-time manual setWebhook step required).
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not webhook_secret:
        # Fail closed: refuse to process unauthenticated webhook traffic when no secret is configured.
        logger.error("Telegram webhook rejected: TELEGRAM_WEBHOOK_SECRET is not set")
        return JSONResponse({"status": "error", "message": "unauthorized"}, status_code=403)
    provided = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(provided, webhook_secret):
        return JSONResponse({"status": "error", "message": "unauthorized"}, status_code=403)

    try:
        data = await request.json()
        message = data.get("message", {})
        text = message.get("text", "").strip().lower()
        if "@" in text and text.startswith("/"):
            text = text.split("@")[0]
        chat_id = message.get("chat", {}).get("id")

        if text and chat_id:
            for u_id, state_obj in USER_STATES.items():
                if state_obj.webhook_url and str(chat_id) in state_obj.webhook_url:
                    from engine.notifier import trigger_webhook_background
                    
                    if text in ["status", "/status"]:
                        import psutil
                        process = psutil.Process()
                        mem_mb = process.memory_info().rss / (1024 * 1024)
                        
                        cache = get_user_cache(u_id)
                        is_auth = cache.get("is_auth", False)
                        auth_status = "✅ Connected" if is_auth else "❌ Disconnected"
                        active_trades = len(state_obj.active_auto_trades)
                        trades_today = state_obj.trades_today
                        pnl = state_obj.pnl_today
                        strategies = ", ".join(state_obj.active_strategies) if state_obj.active_strategies else "None"
                        auto_state = "🟢 RUNNING" if state_obj.automation_enabled else "🔴 PAUSED"
                        
                        msg = (
                            f"⏱️ <b>System Status</b>\n\n"
                            f"🤖 <b>Automation:</b> {auto_state}\n"
                            f"🟢 <b>System:</b> Online ({mem_mb:.1f} MB RAM)\n"
                            f"🔐 <b>Fyers Auth:</b> {auth_status}\n"
                            f"💰 <b>PnL Today:</b> ₹{pnl:.2f}\n"
                            f"📈 <b>Active Trades:</b> {active_trades}\n"
                            f"📊 <b>Trades Taken:</b> {trades_today}/{state_obj.max_trades_per_day}\n"
                            f"🎯 <b>Active Strategies:</b> {strategies}"
                        )
                        trigger_webhook_background(state_obj.webhook_url, msg, title="Status Report")
                        
                    elif text == "/positions":
                        active = state_obj.active_auto_trades
                        if not active:
                            trigger_webhook_background(state_obj.webhook_url, "No active trades at the moment.", title="Open Positions")
                        else:
                            msg = ""
                            for t in active:
                                side_icon = "📈" if t['side'] == 'BUY' else "📉"
                                msg += f"{side_icon} <b>{t['symbol']}</b>\n"
                                msg += f"Entry: ₹{t['entry_price']:.2f}\n"
                                msg += f"Trailing SL: ₹{t['sl_price']:.2f}\n\n"
                            trigger_webhook_background(state_obj.webhook_url, msg.strip(), title="Open Positions")
                            
                    elif text in ["/strategies", "strategies"]:
                        strats = state_obj.active_strategies
                        if not strats:
                            trigger_webhook_background(state_obj.webhook_url, "No strategies currently enabled.", title="Strategies Status")
                        else:
                            msg = ""
                            for s in strats:
                                # Find if there is an active trade for this strategy
                                active_trades_for_strat = [t for t in state_obj.active_auto_trades if t.get('strategy') == s]
                                if active_trades_for_strat:
                                    msg += f"🎯 *{s}*\n└ 🟢 {len(active_trades_for_strat)} Open Trade(s)\n\n"
                                else:
                                    from datetime import datetime, time
                                    from engine.automation import IST
                                    now_time = datetime.now(IST).time()
                                    
                                    status = "⚪ Waiting for signals/conditions"
                                    
                                    # Check time windows for morning strategies
                                    if "9:26" in s and now_time > time(9, 35):
                                        status = "🛑 Time window closed for today"
                                    elif ("ORB" in s or "Gap Fill" in s) and now_time > time(10, 30):
                                        status = "🛑 Time window closed for today"
                                        
                                    msg += f"🎯 *{s}*\n└ {status}\n\n"
                            trigger_webhook_background(state_obj.webhook_url, msg.strip(), title="Strategies Status")
                            
                    elif text == "/login":
                        try:
                            from fyers_client import FyersClient
                            fc = FyersClient(user_id=u_id)
                            login_url = fc.get_login_url()
                            msg = (
                                f"🔐 *Manual Fyers Login*\n\n"
                                f"Fyers auto-login is currently blocked by the broker. Please log in manually once a day.\n\n"
                                f"1. Click this link: [Fyers Login]({login_url})\n"
                                f"2. Log in using your mobile or Client ID.\n"
                                f"3. You will be redirected to a blank page.\n"
                                f"4. Look at the URL in your browser's address bar. Copy the `auth_code` parameter.\n"
                                f"5. Send it back to me like this:\n\n"
                                f"`/authcode YOUR_AUTH_CODE`"
                            )
                            trigger_webhook_background(state_obj.webhook_url, msg, title="Fyers Login Required")
                        except Exception as e:
                            trigger_webhook_background(state_obj.webhook_url, f"❌ Error generating login URL: {str(e)}", title="Login Error")
                            
                    elif text.startswith("/authcode "):
                        auth_code = text.split("/authcode ", 1)[1].strip()
                        try:
                            client_data = await Database.get_user_by_id(u_id)
                            if not client_data:
                                trigger_webhook_background(state_obj.webhook_url, "❌ User not found.", title="Login Error")
                                continue

                            client_id = client_data.get("fyers_client_id") or os.getenv("FYERS_CLIENT_ID")
                            secret_key = client_data.get("fyers_secret") or os.getenv("FYERS_SECRET_KEY")
                            redirect_uri = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")
                            
                            from fyers_apiv3 import fyersModel
                            import traceback
                            
                            session = fyersModel.SessionModel(
                                client_id=client_id,
                                secret_key=secret_key,
                                redirect_uri=redirect_uri,
                                response_type="code",
                                grant_type="authorization_code"
                            )
                            session.set_token(auth_code)
                            response = session.generate_token()
                            
                            if response.get("s") == "ok":
                                access_token = response.get("access_token")
                                refresh_token = response.get("refresh_token")
                                
                                from fyers_client import FyersClient
                                fc = FyersClient(user_id=u_id)
                                fc._save_cache(access_token, refresh_token, True)
                                
                                trigger_webhook_background(state_obj.webhook_url, "✅ <b>Login Successful!</b>\n\nFyers API is now connected and ready for automated trading today.", title="Auth Success")
                                
                                # Auto-refresh cache
                                fc.client = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")
                                fc.get_profile()
                            else:
                                error_msg = response.get("message", str(response))
                                trigger_webhook_background(state_obj.webhook_url, f"❌ <b>Login Failed</b>\n\nBroker returned: {error_msg}\n\nPlease try /login again.", title="Auth Error")
                        except Exception as e:
                            print(f"Auth error: {traceback.format_exc()}")
                            trigger_webhook_background(state_obj.webhook_url, f"❌ <b>System Error</b>\n\n{str(e)}", title="Auth Error")
                            
                    elif text in ["/pnl", "pnl"]:
                        pnl = state_obj.pnl_today
                        closed_trades = getattr(state_obj, 'closed_trades_today', [])
                        
                        now_str = datetime.now(IST).date().isoformat()
                        msg = (
                            f"📊 <b>PnL Report</b>\n\n"
                            f"🗓️ Date: {now_str}\n"
                            f"💰 Total PnL Today: ₹{pnl:.2f}\n"
                            f"📈 Total Executed Trades: {len(closed_trades)}\n"
                            f"🔄 Current Limit Counter: {state_obj.trades_today}/{state_obj.max_trades_per_day}"
                        )
                        
                        msg += "\n\n<b>Trade Breakdown:</b>\n"
                        if closed_trades:
                            for i, t in enumerate(closed_trades, 1):
                                p_icon = "🟢" if t['pnl'] > 0 else "🔴" if t['pnl'] < 0 else "⚪"
                                msg += f"{i}. {t['symbol']}: {p_icon} ₹{t['pnl']:.2f}\n"
                        else:
                            msg += "No trades completed today."

                        trigger_webhook_background(state_obj.webhook_url, msg.strip(), title="PnL Report")
                        
                    elif text == "/stop":
                        state_obj.automation_enabled = False
                        state_obj.save()
                        trigger_webhook_background(state_obj.webhook_url, "🔴 <b>EMERGENCY STOP</b>\n\nAll automated trading has been paused. No new trades will be taken.", title="System Halted")
                        
                    elif text == "/start":
                        state_obj.automation_enabled = True
                        state_obj.save()
                        trigger_webhook_background(state_obj.webhook_url, "🟢 <b>AUTOMATION RESUMED</b>\n\nAutomated trading is now active.", title="System Resumed")
                        
                    elif text == "/settings":
                        msg = (
                            f"⚙️ <b>Current Settings</b>\n\n"
                            f"🔹 <b>Max Trades/Day:</b> {state_obj.max_trades_per_day}\n"
                            f"🔹 <b>Max Loss/Day:</b> ₹{state_obj.max_loss_per_day}\n"
                            f"🔹 <b>Trailing SL Step:</b> {getattr(state_obj, 'trail_sl_step', 5.0)} pts\n"
                            f"🔹 <b>Daily Profit Target:</b> ₹{state_obj.daily_profit_target}\n"
                            f"🔹 <b>Lots to Trade:</b> {state_obj.trade_lots}\n"
                            f"🔹 <b>Trading Mode:</b> {'Paper' if state_obj.paper_trading else 'Live'}"
                        )
                        trigger_webhook_background(state_obj.webhook_url, msg, title="Risk Settings")
                    
                    break
        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing telegram webhook: {e}")
        return {"status": "error"}

# Startup logic moved to lifespan() context manager at top of file

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting NIFTY Trading Dashboard on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

