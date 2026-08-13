"""
run_backtests_cron.py — nightly cron entry point (strategy-self-improvement, 11-08-26).

Invoked by cron ~15 min before nightly_learning.py's trigger (~15:35 IST), so backtest_results
is refreshed with a same-night run_date before nightly tuning reads it. Headless auth: reuses
the "any authenticated user's session works" pattern from workers/news_worker.py's
_get_validation_client(). On success: runs run_all_backtests() and saves via save_backtest_result().
On failure (no session, or any exception): logs, writes backtest_refresh_status, fires a
Telegram alert, and leaves prior backtest_results rows untouched — nightly_learning.py's existing
"read latest run_date per strategy" query is the fallback, unchanged.

Standalone sync-process shape (same as check_nightly_learning_report.py): own .env loader, plain
`requests` for Telegram (NOT engine.notifier, which is app-process/async-only).
"""
import asyncio
import logging
import os
import sqlite3
import sys
from datetime import datetime

import pytz
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_app.db")
IST = pytz.timezone("Asia/Kolkata")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("BACKTEST_CRON")


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def send_telegram(webhook_url: str, message: str, title: str = "Backtest Refresh"):
    # Identical pattern to check_nightly_learning_report.py's send_telegram().
    if not webhook_url:
        print("No webhook_url configured — cannot send alert.")
        return False
    url = webhook_url.split("&text=")[0].split("?text=")[0]
    payload = {"text": f"<b>{title}</b>\n{message}", "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=15.0)
        ok = resp.status_code in (200, 204)
        if not ok:
            print(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"Telegram send exception: {e}")
        return False


def _candidate_user_ids():
    """Active user ids, read from the DB.

    NOTE (deviation from PLAN Section 3.1, documented in the phase report): the plan's sketch
    looped `state.USER_STATES`, but that dict is populated lazily by the long-running app process
    and is ALWAYS EMPTY in a fresh standalone cron process (state.py:45) — the loop would find
    zero users and report "no authenticated session" every single night. Reading the ids from the
    `users` table preserves the exact same semantics ("try every user, take the first
    authenticated client") in a standalone process.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute("SELECT id FROM users WHERE is_active=1 ORDER BY id").fetchall()
        finally:
            conn.close()
        return [int(r[0]) for r in rows]
    except Exception as e:
        logger.warning(f"Could not read user ids from DB ({e}) — falling back to user_id=1.")
        return [1]


def _get_headless_client():
    """Return the first authenticated FyersClient (and its user id), or (None, None)."""
    from fyers_client import FyersClient
    for u_id in _candidate_user_ids():
        try:
            c = FyersClient(user_id=u_id)
            if c.is_authenticated():
                return c, u_id
        except Exception:
            continue
    return None, None


def _resolve_webhook_url() -> str:
    """webhook_url from the persisted per-user state file, preferring user 1, else env fallback.

    NOTE (deviation from PLAN Section 3.1): the plan's sketch used
    `state.get_user_state(1).webhook_url`. In a fresh standalone process that builds an EMPTY
    TradingState — get_user_state() constructs a blank object and does NOT hydrate it — so it
    would silently yield "". The value the plan meant is the one the app process hydrates from at
    engine/automation.py:231: `logs/trading_state_{user_id}.json`. Reading that file directly is
    the same value via the same source, minus the app-process dependency. (Verified on the live VM
    13-08-26: trading_state_1.json holds the real Telegram webhook; the `user_states.webhook_url`
    DB column is empty for every user, so the DB is NOT a usable source here.)
    """
    candidates = [os.path.join(BASE_DIR, "logs", "trading_state_1.json")]
    try:
        log_dir = os.path.join(BASE_DIR, "logs")
        candidates += sorted(
            os.path.join(log_dir, f) for f in os.listdir(log_dir)
            if f.startswith("trading_state") and f.endswith(".json")
        )
    except Exception:
        pass

    import json
    for path in candidates:
        try:
            with open(path) as fh:
                url = (json.load(fh).get("webhook_url") or "").strip()
            if url:
                return url
        except Exception:
            continue
    logger.warning("No webhook_url found in any trading_state_*.json — falling back to env.")
    return os.getenv("TELEGRAM_WEBHOOK", "")


def _alert_failure(msg: str):
    send_telegram(_resolve_webhook_url(), msg, title="⚠️ Nightly Backtest Refresh Failed")


async def _run():
    from models import Database
    from engine.backtest_runner import run_all_backtests

    client, u_id = _get_headless_client()
    if client is None:
        msg = "No authenticated Fyers session found at refresh time — backtest refresh skipped tonight."
        logger.error(msg)
        await Database.set_backtest_refresh_status("FAILED", msg)
        _alert_failure(msg)
        return

    logger.info(f"Authenticated Fyers session found (user_id={u_id}) — starting backtest refresh.")
    try:
        results = await run_all_backtests(client, days_back=60)
        run_date = datetime.now(IST).strftime("%Y-%m-%d")
        saved = 0
        for r in results:
            ok = await Database.save_backtest_result(
                strategy_name=r["strategy"], symbol=r.get("symbol", ""), run_date=run_date,
                window_days=60, trades=r["trades"], wins=r["wins"], losses=r["losses"],
                win_rate=r["win_rate"], total_pnl=r["total_pnl"], avg_pnl=r["avg_pnl"],
                note=r.get("error", ""),
            )
            saved += int(ok)
        logger.info(f"Backtest refresh complete: saved {saved}/{len(results)} (run_date={run_date}).")
        await Database.set_backtest_refresh_status("OK", "")
    except Exception as e:
        msg = f"Backtest refresh crashed: {e}"
        logger.exception(msg)
        await Database.set_backtest_refresh_status("FAILED", msg)
        _alert_failure(msg)


if __name__ == "__main__":
    load_env()
    asyncio.run(_run())
