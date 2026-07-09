---
phase: phase-01-critical-security
date: 2026-07-04
status: COMPLETE_WITH_GAPS
feature: security-remediation
plan: process/features/security-remediation/active/trading-remediation_03-07-26/phase-01-critical-security_PLAN_03-07-26.md
---

# Phase 1 — Critical Security & Live-Money Safety — EXECUTE Report

**TL;DR:** All 7 checklist items (A–G) implemented on a clean baseline. 14 new unit/concurrency
tests pass; all fully-automated Exit-Gate greps + the migration dry-run pass; the high-risk
5-artifact evidence pack validates clean. Live-money / live-provider checks (paper round-trip,
live session survival, Telegram setWebhook, provider-secret rotation, the actual encryption-key
cutover) are deploy-day manual actions and are documented, not run here. No hard-stop deviations.

## ⚠️ CRITICAL DEPLOY-DAY GATES (do not skip)

Two items in the Deploy-Day Runbook below WILL break production if forgotten:

1. **`TELEGRAM_WEBHOOK_SECRET` must be set AND registered with Telegram via `setWebhook`
   BEFORE go-live.** The webhook now fails closed (403) without a matching secret token — if
   this step is skipped, all Telegram bot traffic silently stops working. See Runbook step 2.
2. **Encryption-key rotation is order-dependent and must not be reordered.** Set
   `ENCRYPTION_KEY_OLD` + new `ENCRYPTION_KEY` → stop app → run
   `scripts/migrate_reencrypt_credentials.py` → verify a decrypt with the new key → **grep-verify
   exactly one `ENCRYPTION_KEY=` line in `.env` BEFORE restart (Item E2)** → only then remove
   `ENCRYPTION_KEY_OLD` and restart. Restarting with a stale/duplicate key line, or before the
   migration script runs, can lock the app out of the live Fyers credential store. See Runbook
   step 3.

## What Was Done

Files changed (file:line = where the fix lands after edits):

- **A1 — Signed session cookie + shared resolver (auth/identity).**
  - `trading-app/auth_utils.py` (NEW): `sign_user_id()`, `resolve_user_id_from_cookie()` using
    `itsdangerous.URLSafeTimedSerializer` with a 7-day legacy-raw-cookie grace window
    (`SESSION_MIGRATION_CUTOFF = 2026-07-11`); plus the login rate-limit helpers (C2).
  - `trading-app/app.py:~66` import; `~805` new `resolve_authenticated_user_id(request)` helper;
    `get_current_client` rewired through it; **all 19 other cookie-read routes migrated** (root `/`,
    `/api/state`, `/admin`, `/api/admin/*`, `/api/fyers/login_url`, OAuth callback, `/api/user/settings`,
    `/api/submit-auth-code`, force-refresh, restart, `/api/logs`).
  - Cookie **signed at every write site**: `login_api` set_cookie + both OAuth-callback set_cookie sites.
  - `trading-app/requirements.txt`: added `itsdangerous>=2.1.0`.
- **B1 — Telegram webhook auth (trust-boundary).** `app.py` `telegram_webhook`: `hmac.compare_digest`
  of `x-telegram-bot-api-secret-token` vs `TELEGRAM_WEBHOOK_SECRET` **before** `request.json()`;
  fail-closed 403 when the secret is unset or mismatched. Added `import hmac`.
- **C1 — Remove hardcoded admin (auth/identity).** `models.py:~230`: `admin/admin123` auto-create
  replaced with `INITIAL_ADMIN_PASSWORD`-gated first-run creation (else warn, create nothing).
- **C2 — Login rate-limit (auth/identity).** `auth_utils.check_login_locked/register_failed_login/
  reset_login_attempts` (in-memory, username-keyed, 5 attempts / 15 min); wired into `login_api`
  (lock before password check → no timing oracle; reset on success). In-memory is plan-sanctioned
  (single-process Uvicorn).
- **D1 — Fix broken position exit (live-money).** `workers/auto_trader.py:~248` and `~263`:
  `client.exit_position({"id": ...})` → `client.cancel_order(sl_order_id)`; bookkeeping
  (`remove_active_trade`) now cleared **only** after a successful cancel OR a broker-confirmed-flat
  position; otherwise a warning is logged and the trade is kept for the next tick.
- **E1 — Max-loss square-off race (live-money).** `workers/auto_trader.py:~133`:
  `automation_enabled = False` + `hard_exit_triggered = True` moved to **before** the
  `for pos in open_positions:` loop.
- **F1 — Daily-limit TOCTOU race (live-money).** `app.py` `place_order`: `order_lock` widened to wrap
  the limit check + regime checks + `client.place_order` + `state.record_trade()` as one atomic block.
- **G1 — Encryption-key rotation (secrets).** `trading-app/scripts/migrate_reencrypt_credentials.py`
  (NEW): decrypt-with-OLD → re-encrypt-with-NEW, auto pre-migration backup, single transaction,
  plaintext-fallback. Dry-run verified against a synthetic DB copy.
- **G3 — Git hygiene (secrets).** `trading-app/.gitignore`: added `.env`, `*.db`, `*.db-journal`;
  `git rm --cached .env trading.db trading_app.db trading_bot.db` (index-only; working copies intact).
  Also `git rm workers/auto_trader.py.new` — a stray tracked backup holding the OLD vulnerable
  `exit_position` code.
- **High-risk evidence pack**: `.../harness/{risk-gate,context-snippets,verification,review-decision,
  adversarial-validation}.json` — validates clean (0 failures / 0 warnings).
- **Tests (NEW)**: `trading-app/tests/{test_auth_cookie,test_admin_and_ratelimit,test_order_concurrency}.py`.

## What Was Skipped or Deferred

- **G2 (provider-secret rotation)** — manual dashboard action; documented as an open item. No code.
- **Deploy-day manual gates** (per plan Hybrid/Agent-Probe tiering): item-1-live-session,
  item-1-new-login-coverage, item-2 live curl + Telegram `setWebhook`, item-4-order-roundtrip (paper),
  item-5-race-live, the live encryption-key cutover. Cannot run in this env (need live session /
  paper account / live Telegram API / maintenance window).

## Test Gate Outcomes

| Gate | Tier | Result |
|---|---|---|
| item-1-cookie-signing (`pytest test_auth_cookie.py`) | Fully-Automated | PASS (6) |
| item-1-route-coverage (`grep cookies.get("user_id")`) | Fully-Automated | PASS (only resolver-internal) |
| item-3-admin-hardcode + item-3-rate-limit (`pytest test_admin_and_ratelimit.py`) | Fully-Automated | PASS (6) |
| item-2-webhook-auth (code: `grep` header check) | Hybrid (code portion) | PASS; live curl+setWebhook deferred |
| item-4-exit-fix (`grep exit_position`) | Fully-Automated | PASS (empty) |
| item-5-race-reorder (`grep` flag before loop) | Fully-Automated | PASS |
| item-6-toctou-fix (`grep record_trade` in lock) | Fully-Automated | PASS |
| item-6-toctou-concurrency (`pytest test_order_concurrency.py`) | Fully-Automated | PASS (2) — widened lock = exactly 5/8; narrow-lock overcounts |
| item-7-encryption-migration (dry-run vs DB copy) | Hybrid | PASS |
| item-7-git-untrack (`git ls-files`) | Fully-Automated | PASS (empty) |
| py_compile all touched modules | Fully-Automated | PASS |

Full suite: `cd trading-app && ./.venv/bin/python -m pytest tests/ -q` → **14 passed**.

## Plan Deviations

All within-blast-radius (documented); none hard-stop-class:

1. **New module `auth_utils.py`** (not explicitly in Blast Radius) — created to hold the pure
   signing / grace-period / rate-limit logic so the plan's required unit tests actually run without
   importing the heavy `app.py`. The auth mechanism itself stays in `app.py`'s blast radius; the
   plan-named helper `resolve_authenticated_user_id` lives in `app.py` and delegates to `auth_utils`.
2. **Cookie signed at OAuth-callback write sites too** (not only `login_api`) — prevents the OAuth
   callback from re-issuing a forgeable raw cookie. This is signing consistency, not the Phase-2
   OAuth state-binding redesign.
3. **Removed stray `workers/auto_trader.py.new`** — a git-tracked dead-scratch backup containing the
   OLD vulnerable `exit_position` code; unreferenced/unimportable. Removal unblocks Exit-Gate #1 and
   eliminates a lingering copy of the exact vulnerability this phase fixes.
4. **item-6-toctou-concurrency** validates the real `TradingState.order_lock` + `record_trade`
   invariant directly (importing `TradingState` is cheap; importing the `/api/order` route is not).
   The live-route concurrency behavior is deferred to the deploy-day paper round-trip.

## Test Infra Gaps Found

- No pre-existing test suite for `trading-app/` — created `trading-app/tests/` with 3 new files.
  `itsdangerous` + `pytest` installed into `trading-app/.venv` (itsdangerous also added to requirements.txt).
- Exit-Gate #4 fixed-line-window grep remains a heuristic (backlog note filed).

## Closeout Packet

- **Selected plan:** `.../phase-01-critical-security_PLAN_03-07-26.md`
- **Finished:** all 7 checklist items (A–G) coded; 14 tests + all automated gates green; evidence pack valid.
- **Verified vs unverified:** verified = all fully-automated gates + migration dry-run + compile.
  Unverified (deploy-day) = live session survival, fresh-login route coverage, live Telegram
  setWebhook 403/200, paper order round-trip, live concurrent-tick race, the real key cutover, G2 rotation.
- **Cleanup/next:** commit (user-gated); then deploy-day runbook (env vars → setWebhook → key rotation
  per Item G1 order incl. E2 pre-restart `.env` grep → G2 provider rotation → post-deploy manual checks).
- **Best next state:** `Keep in active/testing` — code-complete, but the plan must stay active until
  the deploy-day live-money manual gates are executed and recorded.

## Follow-up stubs created

- `process/features/security-remediation/backlog/phase1-square-off-reentry-guard_NOTE_03-07-26.md`
- `process/features/security-remediation/backlog/exit-gate-line-window-fragility_NOTE_03-07-26.md`

## CONTEXT_PARTIAL notes

- `CONTEXT_PARTIAL: live-money runtime` — could not run the app or live-provider gates in this
  environment; those gates are deferred to deploy-day manual verification (documented above).

## Forward Preview

- **Test Infra Found:** new `trading-app/tests/` (pytest); run `cd trading-app && ./.venv/bin/python -m pytest tests/ -q`.
- **Blast Radius Changes:** `app.py`, `models.py`, `workers/auto_trader.py`, `requirements.txt`,
  `.gitignore` modified; NEW `auth_utils.py`, `scripts/migrate_reencrypt_credentials.py`, `tests/*`;
  `.env`/`*.db`/`auto_trader.py.new` untracked from git.
- **Commands to Stay Green:** `./.venv/bin/python -m pytest tests/ -q`; `grep -n 'cookies.get("user_id")' app.py`
  (only resolver); `grep -rn exit_position workers/ app.py` (empty); `git ls-files .env *.db` (empty).
- **Dependency Changes:** `itsdangerous>=2.1.0` added (requirements.txt + venv). New required env vars
  before prod: `SECRET_KEY`, `TELEGRAM_WEBHOOK_SECRET`, `INITIAL_ADMIN_PASSWORD` (fresh installs),
  `ENCRYPTION_KEY_OLD` (rotation only).

## Deploy-Day Runbook (must run before/at prod cutover)

1. Set `SECRET_KEY` (else auto-generated+persisted on first start), `TELEGRAM_WEBHOOK_SECRET`,
   and `INITIAL_ADMIN_PASSWORD` (fresh installs only) in `trading-app/.env`.
2. Telegram: `POST https://api.telegram.org/bot<TOKEN>/setWebhook` with existing `url` +
   `secret_token=<TELEGRAM_WEBHOOK_SECRET>` — REQUIRED or all webhook traffic fails closed (403).
3. Encryption rotation (Item G1 order): set `ENCRYPTION_KEY_OLD`+new `ENCRYPTION_KEY`; stop app;
   `python scripts/migrate_reencrypt_credentials.py`; verify one token decrypts with new key;
   **run `grep -c '^ENCRYPTION_KEY=' .env` == 1 (E2) BEFORE restart**; remove `ENCRYPTION_KEY_OLD`; restart.
4. G2: rotate `GOOGLE_CLIENT_SECRET`, `OPENROUTER_API_KEY`, `HF_API_KEYS`, `GITHUB_API_KEYS`; update `.env`; restart.
5. Post-deploy: confirm one existing live session still authenticates (grace window), and a fresh
   login loads `/`, `/admin`, `/api/user/settings`.
