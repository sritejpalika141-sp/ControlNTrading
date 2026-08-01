# VM Orchestrator ↔ Cursor RIPER agents

Last updated: 2026-08-01

## Role split

| Component | Runs where | Job |
|-----------|------------|-----|
| `vm_orchestrator.py` | GCP VM (`sritej-orchestrator`) | Watch journals, local AI heal, restarts, health Telegram |
| `engine/cursor_agent_bridge.py` | Called from orchestrator / news_worker | Escalate hard issues to **Cursor Cloud Agents** (RIPER) |
| Cursor / RIPER agents | Cursor Cloud VM | Edit code, tests, PR → merge → `deploy.yml` |

RIPER agents **do not trade**. They only change code.

## Escalation triggers

1. **3-strike crash loop** — local heal failed 3× → escalate + rollback  
2. **Heal cannot find file / invalid patch / AI error / patch mismatch**  
3. **Global news brief quality** — empty `telegram_bullets` or `"Failed to parse news sentiment"` when sending Pre-Market / hourly brief  

## Required secret (for auto-launch)

On the production VM `.env` (or orchestrator env):

```
CURSOR_API_KEY=<from Cursor Dashboard → API Keys>
CURSOR_REPO_URL=https://github.com/sritejpalika141-sp/ControlNTrading
CURSOR_STARTING_REF=main
# optional:
# CURSOR_ESCALATE_COOLDOWN_SEC=3600
```

Without `CURSOR_API_KEY`, escalations still write tickets under `trading-app/logs/cursor_escalations/` and Telegram-notify so a human can paste the prompt into Cursor.

## API

`POST https://api.cursor.com/v1/agents` with Bearer token, `autoCreatePR: true`, repo `main`.

## News brief fix (related)

`get_global_macro_summary` now:
- parses JSON through markdown fences
- **returns `telegram_bullets`** (previously dropped — caused weak Telegram briefs)
