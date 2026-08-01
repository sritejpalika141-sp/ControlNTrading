"""Tests for Cursor RIPER escalation bridge used by vm_orchestrator."""
import json
from pathlib import Path

from engine.cursor_agent_bridge import build_riper_prompt, escalate_to_cursor_agent
from engine import cursor_agent_bridge as bridge
from engine.ai_engine import _parse_ai_json


def test_build_riper_prompt_contains_workflow():
    p = build_riper_prompt(
        issue_type="news_brief_parse_quality",
        summary="bullets empty",
        evidence="summary failed",
        suggested_files=["trading-app/workers/news_worker.py"],
    )
    assert "EXECUTE" in p
    assert "news_brief_parse_quality" in p
    assert "news_worker.py" in p


def test_escalate_writes_ticket_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_app_dir", lambda: tmp_path)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    bridge._LAST_ESCALATE.clear()

    result = escalate_to_cursor_agent(
        issue_type="test_issue",
        summary="unit test",
        evidence="traceback here",
        suggested_files=["a.py"],
        issue_key="unit:test:1",
        notify_telegram=False,
    )
    assert result["ok"] is True
    path = Path(result["ticket_path"])
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["issue_type"] == "test_issue"
    assert data["cursor_api"]["skipped"] is True


def test_escalate_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_app_dir", lambda: tmp_path)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    bridge._LAST_ESCALATE.clear()
    monkeypatch.setattr(bridge, "COOLDOWN_SECONDS", 3600)

    r1 = escalate_to_cursor_agent(
        issue_type="cd",
        summary="a",
        evidence="e",
        issue_key="cooldown:x",
        notify_telegram=False,
    )
    r2 = escalate_to_cursor_agent(
        issue_type="cd",
        summary="a",
        evidence="e",
        issue_key="cooldown:x",
        notify_telegram=False,
    )
    assert r1["ok"] is True
    assert r2.get("skipped") is True


def test_parse_ai_json_with_fence():
    raw = '```json\n{"equities_trend": "BULLISH", "telegram_bullets": ["a"]}\n```'
    data = _parse_ai_json(raw)
    assert data["equities_trend"] == "BULLISH"
    assert data["telegram_bullets"] == ["a"]
