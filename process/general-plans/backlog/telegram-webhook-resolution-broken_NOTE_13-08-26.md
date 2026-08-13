---
name: note:telegram-webhook-resolution-broken
description: "Sibling standalone scripts resolve webhook_url from empty sources — their Telegram alerts have likely been failing silently"
date: 13-08-26
feature: general
---

# BACKLOG NOTE — Telegram Alert Resolution Is Broken in Standalone Scripts (G2)

Opened: 13-08-26. Found during EXECUTE of `strategy-self-improvement_11-08-26`.
**Not fixed — out of scope for that plan.**

## What was found

On the live VM, the webhook lookup that several standalone scripts rely on resolves to an empty
string:

- `user_states.webhook_url` is `''` for **every** user (verified: users 3 and 4, both empty).
- `TELEGRAM_WEBHOOK` is **not set** in `.env` (no `TELEGRAM*` keys present at all).

The webhook that actually works is persisted in `logs/trading_state_1.json`, which is the file the
running app hydrates from at `engine/automation.py:231`. That is why the live app successfully logs
`Webhook sent: Fyers Auto-Login` while the standalone scripts cannot send anything.

## Affected code

| Location | Pattern | Consequence |
|---|---|---|
| `check_nightly_learning_report.py:165` | `getattr(state, "webhook_url", "") or os.getenv("TELEGRAM_WEBHOOK", "")` | Fresh `TradingState` is never hydrated → `""` → nightly report never sends |
| `engine/nightly_learning.py:316` | `SELECT webhook_url FROM user_states WHERE user_id=?` | Column is empty for all users → shadow-out alerts never send |
| `engine/nightly_learning.py:392` | same | same |
| `app.py:3236`, `app.py:3266` | same DB query + env fallback | same |

`run_backtests_cron.py` (added 13-08-26) deliberately sidesteps this by reading
`logs/trading_state_*.json` directly — see its `_resolve_webhook_url()` docstring. The sibling
scripts were **not** modified.

## Impact

Silent. Nothing errors; the send functions simply return early on an empty URL. Any alerting these
scripts were supposed to provide has been dark for an unknown period.

## Recommended next step

Open a RESEARCH task to pick one canonical webhook-resolution source and route every caller through
it. Candidate: a small shared helper that reads `logs/trading_state_{uid}.json` (the source of
truth the app already uses), falling back to `user_states.webhook_url`, then env. Then backfill
`user_states.webhook_url` (or retire that column) so the two sources cannot drift again.
