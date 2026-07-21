"""
Shared application state, constants, and helpers.

Centralizes the mutable globals and utility functions used across `app.py`
and the `workers/*` modules so background tasks can be split out of app.py
without introducing circular imports.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set
import orjson

import pytz
from fastapi import Request, WebSocket

from fyers_client import FyersClient
from engine.automation import TradingState
from models import Database

# ───────────────────────── Constants ─────────────────────────
IST = pytz.timezone("Asia/Kolkata")
VERSION = "6.0.0"
SERVER_START_TIME = datetime.now(IST)

# Risk Management Constants
DAILY_DRAWDOWN_LIMIT_PCT = 2.0  # Stop trading when daily loss exceeds this % of capital
RISK_PER_TRADE_PCT = 1.0  # Risk 1% of capital per trade

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ENV_PATH = PROJECT_ROOT / "fyers-mcp-server" / ".env"
LOG_DIR = BASE_DIR / "logs"

logger = logging.getLogger("DASHBOARD")

# ───────────────────────── Mutable globals ─────────────────────────
USER_CONTEXTS: Dict[int, FyersClient] = {}
USER_STATES: Dict[int, TradingState] = {}
USER_CACHES: Dict[str, dict] = {}
active_connections: Set[WebSocket] = set()
dashboard_cache: dict = {}
ai_trend_cache: dict = {}  # Cache for AI predictions to prevent rate-limits
_analysis_store: dict = {}
main_loop: Optional[asyncio.AbstractEventLoop] = None

# Global Market Regime state evaluated by the Regime Worker.
# market_regime/regime_reason = NSE/Indian equity regime (kept for backward compat). The Regime
# Worker also fills per-market regimes below using the SAME 5m-candle logic (currency uses the
# news-derived trend since its FUT feed is deferred).
# Engine liveness heartbeat — updated by the automation loop after EVERY completed cycle.
# engine_health_watchdog() alerts when this goes stale during market hours. This exists because
# the engine silently stopped placing trades for 133 of 159 days and nothing ever surfaced it:
# a hung API call stretched one cycle to 15-20 minutes, so the loop was "running" but never
# reached the time-boxed strategy windows. A heartbeat catches exactly that (age > 10 min).
last_automation_cycle_ts: float = 0.0

market_regime: str = "NEUTRAL"
regime_reason: str = "Awaiting first 5-minute candle."
mcx_regime: str = "NEUTRAL"
mcx_regime_reason: str = "Awaiting MCX session."
currency_regime: str = "NEUTRAL"
currency_regime_reason: str = "Awaiting currency session."

# Token readiness gate: blocks market-dependent operations until the first
# Fyers token refresh completes on startup.  Set by fyers_token_refresh_scheduler
# in app.py after the initial refresh finishes.
_token_ready: asyncio.Event = asyncio.Event()


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Setter used by the FastAPI lifespan to publish the running loop."""
    global main_loop
    main_loop = loop


# ───────────────────────── Helpers ─────────────────────────
def get_user_state(user_id) -> TradingState:
    """Get or create TradingState for a user. Always normalizes user_id to int."""
    u_id = int(user_id)
    if u_id not in USER_STATES:
        USER_STATES[u_id] = TradingState(user_id=u_id)
    return USER_STATES[u_id]


def get_user_cache(user_id) -> dict:
    """Get or create the per-user runtime cache (keyed by str(user_id))."""
    u_id = str(user_id)
    if u_id not in USER_CACHES:
        USER_CACHES[u_id] = {
            "spot": {}, "vix": None, "analysis": {}, "strikes": {},
            "positions": [], "active_positions": [], "orders": [], "funds": {},
            "last_update": 0, "total_pnl": 0, "is_auth": False,
        }
    return USER_CACHES[u_id]


def purge_user_runtime(user_id) -> None:
    """Remove all in-memory runtime state for a user (Phase 2 Item A3).

    Called synchronously when a user is deactivated or deleted so that every background
    loop iterating `for u_id, client in USER_CONTEXTS.items()` (trailing_monitor,
    automation_loop, token-refresh, hard-exit scheduler) naturally excludes them on the
    next tick — instead of continuing to trade a deactivated/deleted user's live broker
    session until the process restarts. First flips `automation_enabled=False` on their
    live TradingState (in case another loop tick already captured a reference), then drops
    the entries from all three per-user maps. Idempotent and never raises.
    """
    try:
        u_id_int = int(user_id)
    except (TypeError, ValueError):
        return

    st = USER_STATES.get(u_id_int)
    if st is not None:
        try:
            st.automation_enabled = False
            st.hard_exit_triggered = True
        except Exception:
            pass

    USER_CONTEXTS.pop(u_id_int, None)
    USER_STATES.pop(u_id_int, None)
    # USER_CACHES is keyed by str(user_id) (see get_user_cache).
    USER_CACHES.pop(str(u_id_int), None)


def get_current_client(request: Request) -> FyersClient:
    """Resolve the FyersClient for the user_id cookie on the request."""
    user_id = request.cookies.get("user_id")
    if not user_id:
        user_id = 0  # Default to guest/unauthenticated user context
    u_id = int(user_id)
    if u_id not in USER_CONTEXTS:
        USER_CONTEXTS[u_id] = FyersClient(user_id=u_id)
    return USER_CONTEXTS[u_id]


import json
import os

_lot_sizes_dict = None

def get_lot_size(symbol: str) -> int:
    """Get the official NSE lot size from local data/lot_sizes.json.
    No hardcoded fallbacks — all values come from the JSON file."""
    global _lot_sizes_dict
    
    if _lot_sizes_dict is None:
        try:
            path = os.path.join(os.path.dirname(__file__), "data", "lot_sizes.json")
            with open(path, "r") as f:
                _lot_sizes_dict = json.load(f)
            logger.info(f"✅ Loaded {len(_lot_sizes_dict)} lot sizes from lot_sizes.json")
        except Exception as e:
            logger.error(f"❌ CRITICAL: Failed to load lot_sizes.json: {e}")
            _lot_sizes_dict = {}

    s = symbol.upper()
    
    # 1. Exact match (handles full Fyers symbols like NSE:NIFTY2670723950CE)
    if s in _lot_sizes_dict:
        return _lot_sizes_dict[s]
    
    # 2. Check by base name — order matters: check BANKNIFTY before NIFTY
    for idx in ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTY", "SENSEX", "BANKEX"]:
        if idx in s:
            val = _lot_sizes_dict.get(idx)
            if val:
                return val
            # Also try the INDEX format
            idx_key = f"NSE:{idx}-INDEX" if idx != "NIFTY" else "NSE:NIFTY50-INDEX"
            val = _lot_sizes_dict.get(idx_key)
            if val:
                return val

    # 3. Try extracting base symbol from option format (e.g., NSE:RELIANCE2670731300CE → RELIANCE,
    #    NSE:USDINR26717101CE → USDINR, MCX:CRUDEOIL26JUL7700CE → CRUDEOIL). Covers NSE equity/currency
    #    AND MCX commodity options.
    import re
    m = re.match(r"(?:NSE|MCX|CDS):([A-Z]+)\d", s)
    if m:
        base = m.group(1)
        val = _lot_sizes_dict.get(base)
        if val:
            return val
        # MCX commodity + currency options: Fyers takes the order qty in LOTS (qty=1 == 1 lot), so
        # the correct per-lot multiplier is 1 when the master has no explicit entry — NOT a noisy
        # "unknown" default. (NSE equity options are handled by the -EQ branch below.)
        if s.startswith("MCX:") or s.startswith("CDS:") or any(fx in s for fx in ("USDINR", "EURINR", "GBPINR", "JPYINR")):
            return 1

    # 4. Equity stocks have lot size 1
    if "-EQ" in s:
        return 1

    logger.warning(f"⚠️ No lot size found for {symbol} in lot_sizes.json, defaulting to 1")
    return 1  # Default for unknown equity/stocks


def calculate_position_size(user_id: int, entry_price: float, sl_points: float, symbol: str = "") -> int:
    """Calculate position size based on risk-per-trade percentage.
    
    Uses the RISK_PER_TRADE_PCT constant (default 1%) to determine how many
    lots/shares to trade based on available capital and stop-loss distance.
    
    Args:
        user_id: User ID to get capital info
        entry_price: Expected entry price per unit
        sl_points: Stop-loss distance in points
        symbol: Symbol to determine lot size
    
    Returns:
        Number of lots/shares to trade (minimum 1)
    """
    try:
        from models import Database
        user = Database.get_user_by_id_sync(user_id)
        if not user:
            return 1
        
        # Get available funds from user states or cache
        import sqlite3
        conn = sqlite3.connect(Database.DB_NAME)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT daily_profit, daily_loss FROM user_states WHERE user_id=?", (user_id,))
            row = cursor.fetchone()
            # Use a reasonable default capital estimate if not available
            # In production, this should come from the broker API or a config
            capital = 500000  # Default ₹5L capital
        finally:
            conn.close()
        
        # Calculate risk amount
        risk_amount = capital * (RISK_PER_TRADE_PCT / 100)
        
        # If SL is too tight or zero, return minimum lot size
        if sl_points <= 0:
            lot_size = get_lot_size(symbol)
            return max(1, lot_size)
        
        # Calculate position size: risk_amount / sl_points = number of units
        position_value = risk_amount / sl_points
        lot_size = get_lot_size(symbol)
        
        # Convert to lots (round down to whole lots)
        if lot_size > 0:
            lots = int(position_value / (entry_price * lot_size))
            return max(1, lots * lot_size)
        
        return max(1, int(position_value / entry_price))
        
    except Exception as e:
        logger.error(f"Error calculating position size: {e}")
        return 1  # Fallback to minimum


# ───────────────────────── NSE 2026 Holidays ─────────────────────────
NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Gurunanak Jayanti",
    "2026-12-25": "Christmas"
}

def get_holiday_reason() -> Optional[str]:
    """
    Check if today is a weekend or an official NSE trading holiday.
    Returns the reason string if it is a holiday, otherwise returns None.
    """
    now = datetime.now(IST)
    date_str = now.date().isoformat()
    
    # 1. Check official NSE holidays list
    if date_str in NSE_HOLIDAYS_2026:
        return f"NSE Holiday ({NSE_HOLIDAYS_2026[date_str]})"
        
    # 2. Check weekends (Sat/Sun)
    if now.weekday() == 5:
        return "Weekend (Saturday)"
    if now.weekday() == 6:
        # Exclude Muhurat Trading day (Nov 8, 2026)
        if date_str == "2026-11-08":
            return None
        return "Weekend (Sunday)"
        
    return None

def is_market_open(asset_class: str = None) -> bool:
    """Check if the market is currently open for the given asset class (default: INDEX_OPTIONS =
    NIFTY's 9:15-15:30 IST, weekdays, excluding holidays). Registry-driven (multi-asset Phase 1):
    the NO-ARG call is byte-for-byte identical to the previous hard-coded 9:15-15:30 behavior,
    because INDEX_OPTIONS carries exactly those hours."""
    now = datetime.now(IST)
    if get_holiday_reason() is not None:
        return False
    # Lazy import to avoid any circular-import at module load.
    from engine.asset_classes import get_asset_class
    ac = get_asset_class(asset_class)
    oh, om = ac.session_open
    ch, cm = ac.session_close
    market_start = now.replace(hour=oh, minute=om, second=0, microsecond=0)
    market_end = now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    return market_start <= now <= market_end


# Legacy underscore alias preserved for callers that imported it.
_is_market_open = is_market_open


async def broadcast_log(msg: str, level: str = "info", user_id: Optional[int] = None, telegram_alert: bool = False) -> None:
    """Send a log message to connected clients, store in DB, and forward to Webhook if requested."""
    timestamp_ws = datetime.now(IST).strftime("%H:%M:%S")
    timestamp_db = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    try:
        asyncio.create_task(Database.insert_log(level, msg, timestamp_db, user_id))
    except Exception as e:
        print(f"⚠️ DB log insert error: {e}")

    # --- NEW: Forward requested alerts to Telegram/Webhook ---
    if telegram_alert and user_id is not None:
        try:
            state = get_user_state(user_id)
            if state.webhook_url:
                from engine.notifier import trigger_webhook_background
                
                # Assign a sensible title based on the message content
                if "🚀" in msg or "Auto-executing" in msg:
                    title = "🚀 Trade Entry"
                elif "🎉" in msg or "📉" in msg or "🔴" in msg or "🛑" in msg or "🚨" in msg or "🎯" in msg or "✅" in msg:
                    title = "🔔 Trade Exit / Update"
                elif "❌" in msg or "⚠️" in msg:
                    title = "⚠️ System Error / Warning"
                else:
                    title = "Sritej Trading Alert"

                trigger_webhook_background(state.webhook_url, msg, title=title)
        except Exception as e:
            print(f"⚠️ Failed to forward log to webhook: {e}")

    if not active_connections:
        return

    payload = {"type": "log", "msg": msg, "level": level, "time": timestamp_ws}
    disconnected = set()
    for ws in active_connections:
        if user_id is None or getattr(ws, "user_id", None) == user_id:
            try:
                await ws.send_text(orjson.dumps(payload).decode("utf-8"))
            except Exception:
                disconnected.add(ws)
    for ws in disconnected:
        active_connections.discard(ws)
