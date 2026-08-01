"""
Escalate production issues from vm_orchestrator to Cursor Cloud Agents (RIPER).

Flow:
  1. Local AI heal tries first (vm_orchestrator.heal_application).
  2. On repeated failure / quality gates (news brief), call escalate_to_cursor_agent().
  3. If CURSOR_API_KEY is set → POST https://api.cursor.com/v1/agents (Cloud Agents API).
  4. Always write a local escalation ticket under logs/cursor_escalations/ and Telegram-notify.

RIPER agents do NOT trade — they edit code on a Cursor VM and open a PR; deploy.yml
picks up the merge.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, request

DEFAULT_REPO_URL = os.getenv(
    "CURSOR_REPO_URL",
    "https://github.com/sritejpalika141-sp/ControlNTrading",
)
ESCALATION_DIR_NAME = "cursor_escalations"
# Avoid spam: one escalate per issue key per cooldown window
_LAST_ESCALATE: Dict[str, float] = {}
COOLDOWN_SECONDS = int(os.getenv("CURSOR_ESCALATE_COOLDOWN_SEC", "3600"))


def _app_dir() -> Path:
    here = Path(__file__).resolve().parent.parent  # trading-app/
    return here


def _escalation_dir() -> Path:
    d = _app_dir() / "logs" / ESCALATION_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_riper_prompt(
    *,
    issue_type: str,
    summary: str,
    evidence: str,
    suggested_files: Optional[list[str]] = None,
) -> str:
    files = suggested_files or []
    file_block = "\n".join(f"- `{f}`" for f in files) if files else "- (infer from evidence)"
    return (
        "[MODE: ORCHESTRATOR] Production escalation from vm_orchestrator.\n\n"
        f"## Issue type\n{issue_type}\n\n"
        f"## Summary\n{summary}\n\n"
        f"## Evidence\n```\n{evidence[:6000]}\n```\n\n"
        f"## Likely files\n{file_block}\n\n"
        "## Required workflow\n"
        "1. RESEARCH: locate root cause in the evidence and files above.\n"
        "2. If non-trivial: PLAN briefly then ENTER EXECUTE MODE.\n"
        "3. Fix the code; add/adjust a focused unit test when possible.\n"
        "4. Commit on a `cursor/<name>-9e4a` branch, push, open/update PR to `main`.\n"
        "5. Do NOT place live trades. Do NOT weaken risk/shadow gates.\n\n"
        "Deploy is automatic on merge to main."
    )


def _cooldown_ok(issue_key: str) -> bool:
    now = time.time()
    last = _LAST_ESCALATE.get(issue_key, 0)
    if now - last < COOLDOWN_SECONDS:
        return False
    _LAST_ESCALATE[issue_key] = now
    return True


def _write_ticket(payload: Dict[str, Any]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _escalation_dir() / f"{ts}_{payload.get('issue_type', 'issue')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def _post_cursor_agent(prompt_text: str, name: str) -> Dict[str, Any]:
    api_key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "skipped": True, "reason": "CURSOR_API_KEY not set"}

    body = {
        "prompt": {"text": prompt_text},
        "name": name[:100],
        "repos": [
            {
                "url": DEFAULT_REPO_URL,
                "startingRef": os.getenv("CURSOR_STARTING_REF", "main"),
            }
        ],
        "autoCreatePR": True,
    }
    env_name = (os.getenv("CURSOR_ENV_NAME") or "").strip()
    if env_name:
        # Named cloud environment (mutually exclusive with repos in some configs —
        # keep repos; API may ignore env if conflict). Prefer repos for reliability.
        body["env"] = {"type": "cloud", "name": env_name}

    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        "https://api.cursor.com/v1/agents",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return {"ok": True, "response": parsed, "status": getattr(resp, "status", 200)}
    except error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:2000]
        return {"ok": False, "status": e.code, "error": err_body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def escalate_to_cursor_agent(
    *,
    issue_type: str,
    summary: str,
    evidence: str,
    suggested_files: Optional[list[str]] = None,
    issue_key: Optional[str] = None,
    notify_telegram: bool = True,
) -> Dict[str, Any]:
    """
    Escalate to Cursor Cloud Agents when local heal cannot fix the issue.

    Returns dict with ticket_path, cursor API result, and whether escalate was skipped (cooldown).
    """
    key = issue_key or f"{issue_type}:{hash(summary) % 10_000_000}"
    if not _cooldown_ok(key):
        return {"ok": False, "skipped": True, "reason": "cooldown", "issue_key": key}

    prompt = build_riper_prompt(
        issue_type=issue_type,
        summary=summary,
        evidence=evidence,
        suggested_files=suggested_files,
    )
    name = f"vm-orch: {issue_type}"[:100]
    ticket = {
        "issue_type": issue_type,
        "summary": summary,
        "evidence": evidence[:8000],
        "suggested_files": suggested_files or [],
        "prompt": prompt,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "issue_key": key,
    }
    path = _write_ticket(ticket)
    api_result = _post_cursor_agent(prompt, name)
    ticket["cursor_api"] = {k: v for k, v in api_result.items() if k != "response"}
    if api_result.get("response"):
        ticket["cursor_api"]["agent_id"] = (
            (api_result["response"].get("agent") or {}).get("id")
            or api_result["response"].get("id")
        )
        ticket["cursor_api"]["url"] = (
            (api_result["response"].get("agent") or {}).get("url")
            or api_result["response"].get("url")
        )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ticket, f, indent=2)

    if notify_telegram:
        try:
            from engine.notifier import trigger_webhook_background

            wh = (
                os.getenv("TELEGRAM_WEBHOOK")
                or os.getenv("WEBHOOK_URL")
                or ""
            )
            if not wh:
                try:
                    from engine.encryption import get_secret

                    wh = get_secret("TELEGRAM_WEBHOOK", fallback_env=True) or ""
                except Exception:
                    pass
            if wh:
                status = (
                    "✅ Cursor agent launched"
                    if api_result.get("ok")
                    else (
                        "📝 Ticket saved (set CURSOR_API_KEY to auto-launch)"
                        if api_result.get("skipped")
                        else "⚠️ Cursor API failed — ticket saved"
                    )
                )
                url = (ticket.get("cursor_api") or {}).get("url") or ""
                msg = (
                    f"🧠 <b>RIPER escalation</b>\n"
                    f"<b>Type:</b> {issue_type}\n"
                    f"<b>Summary:</b> {summary[:400]}\n"
                    f"<b>Status:</b> {status}\n"
                    f"<b>Ticket:</b> <code>{path.name}</code>\n"
                )
                if url:
                    msg += f"<b>Agent:</b> {url}\n"
                trigger_webhook_background(wh, msg, title="Cursor RIPER Escalation")
        except Exception:
            pass

    return {
        "ok": bool(api_result.get("ok") or path.exists()),
        "ticket_path": str(path),
        "cursor": api_result,
        "issue_key": key,
    }
