import asyncio
import os
import time
from datetime import datetime
import httpx
import re
import hashlib

from models import Database, IST
from state import logger, broadcast_log, get_user_state, USER_CONTEXTS, USER_CACHES
from engine.ai_engine import ai_engine
from engine.ws_feed import ws_feed

# D6: the ONLY actions the health agent is permitted to auto-execute. An LLM suggestion must
# match one of these exactly (after trim/lowercase) — no substring matching — otherwise it is
# rejected and falls back to "wait".
ALLOWED_FIX_ACTIONS = {"restart_ws", "relogin", "clear_cache", "wait"}

# Secret-leak monitor: detect-and-alert-only patterns scanned in the tail of app log files.
# NOTE: these patterns are strictly for DETECTION + admin alerting. A leak finding must NEVER
# be routed through execute_fix() or added to ALLOWED_FIX_ACTIONS (Phase-2 hardening).
SECRET_PATTERNS = {
    "Google/Gemini API key": re.compile(r"AIzaSy[A-Za-z0-9_-]{20,}"),
    "OpenRouter API key": re.compile(r"sk-or-v1-[A-Za-z0-9]{40,}"),
    "HuggingFace token": re.compile(r"hf_[A-Za-z0-9]{30,}"),
    "GitHub PAT (fine-grained)": re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    "GitHub PAT (classic)": re.compile(r"ghp_[A-Za-z0-9]{36}"),
    "Telegram bot token": re.compile(r"\d{8,}:[A-Za-z0-9_-]{30,}"),
}
SECRET_SCAN_INTERVAL_SECONDS = 3600  # throttle: at most once per hour
SECRET_SCAN_TAIL_BYTES = 64 * 1024   # read only the last 64KB of each log file per cycle
# Resolved relative to this file (workers/) so the scan works regardless of the server's CWD.
_HEALTH_AGENT_DIR = os.path.dirname(__file__)
SECRET_SCAN_LOG_FILES = [
    os.path.join(_HEALTH_AGENT_DIR, "..", "logs", "dashboard.log"),
    os.path.join(_HEALTH_AGENT_DIR, "..", "logs", "fyersApi.log"),
    os.path.join(_HEALTH_AGENT_DIR, "..", "logs", "fyersRequests.log"),
    os.path.join(_HEALTH_AGENT_DIR, "..", "app.log"),
]


def _match_fix_action(raw: str) -> str:
    """D6: exact-token match of an LLM fix suggestion against the allow-list.

    Trims whitespace and surrounding quotes/backticks/periods, lowercases, then requires EXACT
    equality with an allow-listed token. A sentence that merely CONTAINS a token (e.g.
    'do NOT restart_ws') does NOT fire the action — it falls through to 'wait'.
    """
    if not raw:
        return "wait"
    cleaned = raw.strip().strip('`"\'. \n\t').lower()
    return cleaned if cleaned in ALLOWED_FIX_ACTIONS else "wait"

HEALTH_AGENT_STATUS = {
    "status": "idle",
    "last_check": None,
    "last_error": None,
    "last_fix": None,
    "is_paused": False
}

# Secret-leak monitor throttle/dedup state (module-level, process-lifetime only).
_last_secret_scan_ts = 0.0
_alerted_secret_fingerprints = set()


def _secret_fingerprint(pattern_name: str, matched_text: str) -> str:
    """One-way fingerprint of a finding used for dedup.

    Only a short 12-char prefix of the matched text is fed into the hash, and ONLY the
    truncated digest is ever stored/compared — the raw secret value is never retained,
    logged, or surfaced. This keeps dedup working without re-leaking the secret.
    """
    return hashlib.sha256(
        (pattern_name + ":" + matched_text[:12]).encode()
    ).hexdigest()[:16]


def _check_env_world_readable() -> dict | None:
    """Bonus MVP signal: flag a world-readable .env. Read-only os.stat, no value ever surfaced."""
    env_path = os.path.join(_HEALTH_AGENT_DIR, "..", ".env")
    try:
        mode = os.stat(env_path).st_mode
        if mode & 0o004:  # world-readable bit
            return {"pattern_name": ".env world-readable", "file": env_path,
                    "fingerprint": "env-world-readable", "preview": "n/a"}
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"🩺 Secret-scan .env permission check failed: {e}")
    return None


def _read_tail(path: str, tail_bytes: int) -> str:
    """Blocking helper: read only the last `tail_bytes` of a file. Offloaded via to_thread."""
    with open(path, "rb") as fh:
        filesize = os.fstat(fh.fileno()).st_size
        fh.seek(max(0, filesize - tail_bytes))
        return fh.read().decode(errors="ignore")


async def scan_for_leaked_secrets() -> list[dict]:
    """Scan the tail of each configured log file for known secret patterns.

    Returns a list of finding dicts: {pattern_name, file, fingerprint, preview}. The `preview`
    field is for potential future debugging ONLY — it must never be passed to notify_admin()
    or any logger call. Dedup is the CALLER's responsibility (see health_monitor_worker); this
    function reports every match it finds. Never raises — per-file errors are logged and skipped.
    """
    findings: list[dict] = []
    for path in SECRET_SCAN_LOG_FILES:
        try:
            if not os.path.exists(path):
                continue
            tail_text = await asyncio.to_thread(_read_tail, path, SECRET_SCAN_TAIL_BYTES)
            for pattern_name, regex in SECRET_PATTERNS.items():
                for match in regex.finditer(tail_text):
                    matched_text = match.group(0)
                    fp = _secret_fingerprint(pattern_name, matched_text)
                    findings.append({
                        "pattern_name": pattern_name,
                        "file": path,
                        "fingerprint": fp,
                        "preview": matched_text[:8] + "…",
                    })
        except Exception as e:
            # Never let one bad file abort the whole scan. Log the path, not any secret value.
            logger.error(f"🩺 Secret-scan failed for {os.path.basename(path)}: {e}")

    env_finding = _check_env_world_readable()
    if env_finding:
        findings.append(env_finding)

    return findings


async def notify_admin(msg: str):
    await broadcast_log(f"🩺 Health Agent: {msg}", level="warning", user_id=1, telegram_alert=True)

async def check_strategies():
    # Simple heuristic to check if strategies are acting weird.
    # For instance, if there are many recent errors in system_logs.
    logs = await Database.get_user_logs(1, limit=20)
    error_logs = [log for log in logs if log['level'] == 'ERROR' and 'strategy' in log['message'].lower()]
    if len(error_logs) > 3:
        return "Multiple strategy errors detected recently."
    return None

async def generate_diagnostic_report(error_msg: str, context: str = ""):
    raw_gemini = os.getenv("GOOGLE_API_KEYS") or os.getenv("GOOGLE_API_KEY", "")
    gemini_keys = [k.strip() for k in raw_gemini.split(",") if k.strip()]
    if not gemini_keys:
        return f"Error: {error_msg}\n(No AI key available for detailed report)"
    
    key = gemini_keys[0]
    prompt = f"""
    The trading application encountered a serious issue that requires human approval.
    Context: {context}
    Error: {error_msg}
    
    Please provide a short, detailed diagnostic report with summarized pointers:
    1. Possible Cause
    2. Impact on Application
    3. Recommended Actions (Wait/Restart/Clear)
    Keep it concise and formatted for Telegram.
    """
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
    
    return f"Error: {error_msg}\n(AI report generation failed)"

async def query_google_ai_for_fix(error_msg: str):
    raw_gemini = os.getenv("GOOGLE_API_KEYS") or os.getenv("GOOGLE_API_KEY", "")
    gemini_keys = [k.strip() for k in raw_gemini.split(",") if k.strip()]
    if not gemini_keys:
        return "No Google AI key available to diagnose."
    
    key = gemini_keys[0]
    prompt = f"The following error occurred in a Python trading application: '{error_msg}'. Suggest a one-line action to take, like 'restart_ws', 'relogin', 'clear_cache', or 'wait'."
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                raw = data["candidates"][0]["content"]["parts"][0]["text"]
                # D6: exact-token match only (see _match_fix_action) — no substring matching.
                return _match_fix_action(raw)
    except Exception as e:
        logger.error(f"AI diagnosis failed: {e}")
    return "wait"

async def execute_fix(fix_action: str, u_id=None):
    # D6: hard allow-list guard — never execute anything outside the approved set.
    if fix_action not in ALLOWED_FIX_ACTIONS:
        logger.warning(f"🩺 Health Agent: rejected non-allowlisted action '{fix_action}' — treating as wait.")
        return

    # D6: scope restart_ws/relogin to the originating user when the triggering error was
    # user-scoped; fall back to all users only for genuinely global errors (u_id is None).
    if u_id is not None and int(u_id) in USER_CONTEXTS:
        targets = [(int(u_id), USER_CONTEXTS[int(u_id)])]
    else:
        targets = list(USER_CONTEXTS.items())

    if fix_action == "restart_ws":
        logger.info(f"🩺 Health Agent executing: restart_ws (scope: {'user ' + str(u_id) if u_id is not None else 'all users'})")
        for u_id, client in targets:
            try:
                if USER_CACHES.get(str(u_id), {}).get("is_auth"):
                    asyncio.create_task(broadcast_log(f"🩺 Auto-healing: Restarting WebSocket for user {u_id}...", "warning"))
                    ws_feed.restart(client)
            except Exception as e:
                logger.error(f"Failed to restart WS for {u_id}: {e}")

    elif fix_action == "relogin":
        logger.info(f"🩺 Health Agent executing: relogin (scope: {'user ' + str(u_id) if u_id is not None else 'all users'})")
        for u_id, client in targets:
            try:
                asyncio.create_task(broadcast_log(f"🩺 Auto-healing: Forcing token refresh for user {u_id}...", "warning"))
                success = await asyncio.to_thread(client.refresh_via_refresh_token)
                if success:
                    client.reinit_with_fresh_token()
                    USER_CACHES[str(u_id)]["is_auth"] = True
                    ws_feed.restart(client)
                    asyncio.create_task(broadcast_log(f"✅ Auto-heal token refresh successful for user {u_id}", "success"))
            except Exception as e:
                logger.error(f"Failed to relogin {u_id}: {e}")
                
    elif fix_action == "clear_cache":
        logger.info("🩺 Health Agent executing: clear_cache")
        for u_id_key, cache in USER_CACHES.items():
            cache["quotes"] = {}
            cache["all_spots"] = {}
            cache["_initial_quotes_fetched"] = False
        asyncio.create_task(broadcast_log("🩺 Auto-healing: Cleared market data caches.", "info"))
        
    else:
        logger.info(f"Health Agent executing: {fix_action} (No-op)")

async def health_monitor_worker():
    global _last_secret_scan_ts
    logger.info("🩺 Health Monitor Agent started.")

    while True:
        try:
            HEALTH_AGENT_STATUS["last_check"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            HEALTH_AGENT_STATUS["status"] = "checking"

            if HEALTH_AGENT_STATUS["is_paused"]:
                await asyncio.sleep(60)
                continue

            # 1. Check Strategies
            strategy_issue = await check_strategies()
            if strategy_issue:
                HEALTH_AGENT_STATUS["is_paused"] = True
                report = await generate_diagnostic_report(strategy_issue, "Strategy Monitor")
                await notify_admin(f"🚨 Strategy Issue Detected. Pausing agent.\n\n{report}\n\nPlease review and approve.")
                continue

            # 1b. Throttled secret-leak scan (at most once per hour). Detect-and-alert ONLY —
            # never routed through execute_fix(). Only pattern name + filename are ever surfaced;
            # the matched secret value / preview never reaches a log or the Telegram message.
            now_ts = time.time()
            if now_ts - _last_secret_scan_ts >= SECRET_SCAN_INTERVAL_SECONDS:
                _last_secret_scan_ts = now_ts
                HEALTH_AGENT_STATUS["last_secret_scan"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                findings = await scan_for_leaked_secrets()
                # Dedup: only alert findings whose fingerprint has not been alerted before.
                new_findings = [f for f in findings if f["fingerprint"] not in _alerted_secret_fingerprints]
                if new_findings:
                    HEALTH_AGENT_STATUS["last_secret_alert_count"] = len(new_findings)
                    # Batch ALL new findings from this scan cycle into ONE Telegram message —
                    # never one notify_admin() call per finding.
                    lines = []
                    for f in new_findings:
                        _alerted_secret_fingerprints.add(f["fingerprint"])
                        lines.append(f"- {f['pattern_name']} in {os.path.basename(f['file'])}")
                    await notify_admin(
                        "⚠️ Possible secret exposure(s) detected — rotate the credential(s) and "
                        "check logging:\n" + "\n".join(lines)
                    )

            # 2. Check System Logs for recent errors
            logs = await Database.get_user_logs(1, limit=10)
            recent_errors = [log for log in logs if log['level'] == 'ERROR']
            
            if recent_errors:
                latest_error = recent_errors[0]['message']
                # D6: carry the originating user so restart_ws/relogin can be scoped to that
                # user instead of acting on every user. None -> genuinely global error.
                origin_uid = recent_errors[0].get('user_id')
                HEALTH_AGENT_STATUS["last_error"] = latest_error

                # Check memory
                known_fix = await Database.get_health_memory(latest_error)
                if known_fix:
                    action = known_fix['applied_fix']
                    logger.info(f"🩺 Known error detected. Applying fix: {action}")
                    await execute_fix(action, u_id=origin_uid)
                    HEALTH_AGENT_STATUS["last_fix"] = action
                else:
                    # Diagnose
                    logger.info(f"🩺 New error detected: {latest_error}. Diagnosing via AI...")
                    action = await query_google_ai_for_fix(latest_error)

                    if action != "wait":
                        await execute_fix(action, u_id=origin_uid)
                        await Database.insert_health_memory(latest_error, "AI Diagnosed", action, success=1)
                        HEALTH_AGENT_STATUS["last_fix"] = f"{action} (AI)"
                    else:
                        HEALTH_AGENT_STATUS["is_paused"] = True
                        report = await generate_diagnostic_report(latest_error, "System Log Error")
                        await notify_admin(f"🚨 Serious error requiring approval.\n\n{report}\n\nPlease review and approve.")

            HEALTH_AGENT_STATUS["status"] = "idle"
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Health Agent error: {e}")
            await asyncio.sleep(60)
