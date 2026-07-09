---
phase: phase-02-remaining-findings
date: 2026-07-04
status: COMPLETE_WITH_GAPS
feature: security-remediation
plan: process/features/security-remediation/active/trading-remediation_03-07-26/phase-02-remaining-findings_PLAN_03-07-26.md
---

# Phase 2 — Remaining Findings: Auth Edge Cases, Trading-Engine Correctness, XSS, Secrets/TLS/Data-Integrity — EXECUTE Report

**TL;DR:** All 18 checklist items (A1-A3, B0-B6, C1-C2, D1-D6) implemented and verified against
live code. B0's pytest+pytest-asyncio harness (8 new/updated test files, 45 tests) is green,
including the live TLS re-verification (D2) against the real Fyers endpoint. One regression-guard
test (B5) initially failed on a stray comment string, fixed inline. Phase 2's own high-risk
5-artifact evidence pack has NOT been created yet (the existing `harness/*.json` files in this
task folder are Phase 1's) — flagged as an open pre-finalize item, not fabricated here.

## What Was Done

Files changed (file:line = where the fix lands):

- **A1 — Guest-fallback 401 (auth/identity).** `app.py:848-873` (`get_current_client`): raises
  `HTTPException(401)` when no session identity is present, unless the caller explicitly passes
  `allow_guest=True`; the only allowlisted route is `GET /api/version`. `app.py:866-868`: also
  rejects a deactivated user's still-valid cookie (`401 — Account deactivated`).
- **A2 — OAuth `state` bound to a signed nonce (auth/identity).** `app.py:560,572` +
  `auth_utils.py` (`generate_oauth_state`/nonce validation): `/fyers/callback` no longer trusts a
  raw `state=user_id`; nonce is single-use, short-TTL, and rejected on replay/expiry/tamper.
- **A3 — Deactivated/deleted users purged from live runtime (live-money).** `state.py:82-107`
  (new `purge_user_runtime()`): flips `automation_enabled=False` + `hard_exit_triggered=True` on
  any live `TradingState` reference, then drops `USER_CONTEXTS`/`USER_STATES` entries. Wired into
  `app.py:468` (`toggle_user_status`, on deactivate) and `app.py:493` (`admin_delete_user`, before
  the D5 cascade delete) so every background loop (`trailing_monitor`, `automation_loop`,
  token-refresh) naturally excludes the user on its next tick.
- **B0 — Minimal pytest harness (test infra).** `trading-app/pytest.ini` (`testpaths = tests`,
  `norecursedirs` belt-and-suspenders, `asyncio_mode = auto`), `trading-app/requirements-dev.txt`
  (`pytest>=8.0`, `pytest-asyncio>=0.24`, dev-only — confirmed absent from `requirements.txt`),
  `trading-app/tests/conftest.py` (sys.path fixup only). Verified per Execute-Agent Instruction E9:
  both `pytest tests/ --collect-only` and a bare `pytest` (no path arg, run from `trading-app/`)
  collect exactly the intended 45 tests and never touch the 20 legacy ad-hoc `test_*.py` root
  scripts (one of which, `test_login.py`, has a genuine top-level-`await` `SyntaxError`).
- **B1 — Closed-position cleanup on feed omission (live-money).** `workers/auto_trader.py:225-261`:
  `pos is None` (broker feed omitted the position, not just zeroed it) is now also treated as a
  completion candidate, with the existing `pos is not None and qty==0` path unchanged.
- **B2 — Missing/malformed `pl` no longer silently zeroed (live-money).**
  `workers/auto_trader.py` (`aggregate_position_pnl`): missing/non-numeric/`bool` `pl` values are
  excluded from the aggregate and flagged `incomplete=True` with the offending symbols returned,
  instead of defaulting to `0`.
- **B3 — Per-user isolation in `trailing_monitor` (live-money).**
  `workers/auto_trader.py:63-180+`: each user's per-tick body is wrapped in its own
  `try/except Exception: continue`, so one user's malformed state no longer aborts the whole tick.
- **B4 — Regime/duplicate-position guard fails closed (live-money).** RESEARCH sub-step
  re-confirmed `ai_trend_cache` is dead code (zero write sites); `app.py:2127-2154` (`place_order`)
  now routes the guard off `state.market_regime` (the live signal `regime_worker.py` writes) and
  returns an explicit structured rejection (`success: False`, message naming the regime) when the
  regime is not a confirmed `TRENDING_UP`/`TRENDING_DOWN`, or when the CE/PE alignment doesn't
  match the regime — replacing the old silent no-op.
- **B5 — Fabricated estimated-price fallback removed (live-money).**
  `workers/auto_trader.py:965-974`: the former "Try 4" Black-Scholes-flavored guess is gone; when
  no real quote/candle is available, `entry_price` stays `<= 0` and the trade is skipped this
  cycle (no live order at a synthetic price). Comment on line 966 reworded during this session
  (see Test Failures Hit and Fixed below) — logic was already correct.
- **B6 — ATR trailing stop field separation (live-money).**
  `workers/auto_trader.py`: the Strategy 5 ATR trail now writes the absolute trailed price to a
  new `t["trailing_sl_price"]` field; `t["sl_points"]` (a distance elsewhere in the codebase) is
  no longer overwritten with an absolute price.
- **C1 — Reflected XSS in `landing.html` news feed.** `static/landing.html:1505-1560`
  (`_safeHttpUrl()` + `renderNews()`): every feed-controlled string (`title`/`source`/`pubDate`) is
  written via `createElement`+`textContent`, never `innerHTML`; `n.link` is validated against an
  `http:`/`https:`-only allowlist (rejects `javascript:`/`data:`) before being wired via
  `addEventListener('click', ...)` instead of an inlined `onclick` attribute string.
- **C2 — Reflected XSS in `admin.html` log terminals.** `static/admin.html:560-573` (crash-log) and
  `~656-660` (user-activity log): `log.message` now renders via `textContent` on a dedicated
  `span`, with timestamp/styling kept on separate `createElement`d spans — no `innerHTML` of
  attacker-influenceable log text in either terminal.
- **D1 — `decrypt_val` fails loudly (secrets).** `models.py` (`decrypt_val`, `DecryptionError`):
  a genuine decryption failure now raises `DecryptionError` (logged) instead of silently returning
  ciphertext as plaintext; legacy never-encrypted plaintext values still pass through unchanged.
- **D2 — TLS verification restored (secrets/network).** `fetch_lot_sizes.py:4,11`: explicit
  `verify=certifi.where()` replaces `verify=False`. `app.py:2575-2581` (`_RSS_SSL_CTX`): built via
  `ssl.create_default_context(cafile=certifi.where())`, replacing `CERT_NONE`.
  `requirements.txt`: added `requests>=2.31.0`, `certifi>=2024.2.2`. **Live-verified this session**:
  `requests.get('https://public.fyers.in/sym_details/NSE_FO.csv', timeout=10)` → `200`, no
  `verify=False`/`CERT_NONE` anywhere in the codebase (grep-confirmed).
- **D3 — Sensitive API paths excluded from service-worker cache.**
  `static/service-worker.js:55-56`: `/api/funds`, `/api/positions`, `/api/orders`, `/api/admin/`,
  `/api/user/settings` are checked before `cache.put` and bypass caching entirely; non-sensitive
  `/api/*` paths keep the existing Network-First caching.
- **D4 — `nightly_learning_date` persists across restart (live-money/data-integrity).**
  `engine/automation.py:155` (`load()`) and `:214` (`save()`): the field now round-trips through
  `TradingState.save()`/`load()`, so the nightly-learning "already ran today" guard survives a
  process restart.
- **D5 — Orphaned dependent-table rows removed on user deletion (data-integrity).**
  `models.py:428-446` (`USER_SCOPED_TABLES`, `delete_user_cascade`): schema re-grepped per
  Execute-Agent Instruction E5 — of the 7 candidate tables VALIDATE flagged, only 4
  (`user_states`, `daily_pnl_history`, `paper_pnl_history`, `system_logs`) actually carry a
  `user_id` column; `health_memory` and the three `swarm_*` tables are error-/strategy-scoped with
  no `user_id` column and are correctly excluded (documented inline at `models.py:428-430`).
  Cascade delete runs in one transaction, dependents-then-`users`-row.
- **D6 — Exact-token allow-list + user-scoped `execute_fix` (secrets/trust-boundary).**
  `workers/health_agent.py:14-25` (`ALLOWED_FIX_ACTIONS`, `_match_fix_action`): an LLM suggestion
  must exactly equal (after trim/lowercase) one of `{restart_ws, relogin, clear_cache, wait}` —
  substring-only matches fall through to `wait`. `workers/health_agent.py:111-118` (`execute_fix`):
  `restart_ws`/`relogin` scope to the originating `u_id` when the triggering error was
  user-scoped, falling back to all users only when the error is genuinely global.

## Test Harness (B0) — Final State

`trading-app/tests/`: `conftest.py`, `test_admin_and_ratelimit.py`, `test_auth_cookie.py`,
`test_order_concurrency.py` (Phase 1, pre-existing), plus **this phase's additions**:
`test_auto_trader.py` (B2/B3/B5/B6), `test_models.py` (D1/D5), `test_app.py` (A1/A3/B4 — new this
session), `test_automation.py` (D4 — new this session), `test_health_agent.py` (D6 — new this
session).

```
pytest tests/ -v            -> 45 passed
pytest tests/ --collect-only -> 45 collected (no legacy-script collection errors)
pytest (bare, from trading-app/) -> 45 passed (testpaths scoping confirmed)
```

## Test Failures Hit and Fixed (this session)

1. **`test_auto_trader.py::test_no_fabricated_price_order`** — FAILED on first run. The B5 fix
   itself was already correct (fabrication branch removed, fail-safe skip in place); the failure
   was a stray explanatory comment at `workers/auto_trader.py:966` that literally contained the
   banned phrase `"intrinsic + time_value"` describing what had been *removed*. Fixed by
   rewording the comment (`workers/auto_trader.py:965-967`) without touching any logic. Re-ran:
   PASSED.
2. No other gate failures. All other 44 tests passed on first run against the already-landed code.

## Exit Gate — Verification

| Gate (from plan) | Result |
|---|---|
| `pytest trading-app/tests/ -v` | **PASS** — 45/45 (0 failures after the B5 comment fix above) |
| Static/manual XSS verification (C1/C2) | **PASS (static)** — direct code read confirms `textContent`/`createElement` only, `_safeHttpUrl()` protocol allowlist on `n.link`; no `innerHTML` of feed-/log-controlled text remains in either file. Scripted browser probe (`vc-agent-browser`, E7) not run this session — static verification only. |
| TLS re-verification (D2) | **PASS (live)** — `requests.get(...NSE_FO.csv..., timeout=10)` → HTTP 200 against the real Fyers endpoint from this dev environment, with `verify=False`/`CERT_NONE` fully removed (grep-confirmed repo-wide). |
| All Step A-D checklist items checked off | **DONE** — all 18 items implemented and grounded against live code this session (see "What Was Done" above). |
| No `verify=False`/`CERT_NONE` remaining | **CONFIRMED** — grep-clean except historical mentions in comments. |
| No feed-/log-controlled `innerHTML` remains | **CONFIRMED** by direct read of `landing.html`/`admin.html`. |
| Phase report written | **DONE** — this file. |

## What Was Skipped or Deferred

- **Phase 2's own high-risk 5-artifact evidence pack** (`risk-gate.json`, `context-snippets.json`,
  `verification.json`, `review-decision.json`, `adversarial-validation.json`) — Section VI of the
  validate-contract flags this as required before finalize. The `harness/` folder in this task
  folder currently holds **Phase 1's** pack only. Not fabricated this session — recommend a
  follow-up EXECUTE/UPDATE-PROCESS action to produce Phase 2's own pack before treating this phase
  as finalize-ready.
- **A2 (OAuth state replay/tamper), A3 (background-loop exclusion under a live running loop), B1
  (feed-omission), D2 (target-deployment-env CA bundle), C1/C2 (scripted browser probe), D3
  (scripted cache-inspection probe)** — Hybrid/Agent-Probe tier per the plan's own Test Coverage
  Plan; these require a live/mocked OAuth provider, a running background loop, the real deploy
  target, or a browser/DOM environment, none of which substitute for or are proven by the
  Fully-Automated pytest gates above. This is the plan's own accepted tiering, not a new gap.
  Static/logic-level evidence for A3, C1, C2, and D2 was gathered directly this session (see Exit
  Gate table and "What Was Done" above) even though the full Hybrid/Agent-Probe proof was not run.
- **D6 residual LLM prompt-injection risk** — accepted known-gap per the plan (exact-token
  allow-list narrows but does not eliminate the risk of a crafted `error_msg` steering the LLM to
  emit an allow-listed token). No action required this phase.
- **20 legacy ad-hoc `test_*.py` root scripts** — out of this phase's blast radius; B0's
  `testpaths` scoping (E9) prevents them from interfering with the new harness; they remain
  unconverted, as the plan explicitly scopes.
- **EVL (independent gate re-confirmation) and UPDATE PROCESS** — not run in this EXECUTE pass;
  per protocol these are separate orchestrator-driven steps after this report.

## Files Changed (this session, code)

- `trading-app/workers/auto_trader.py` (comment fix at line 965-967 — the only source edit made
  during this resumed session; all other Step A-D logic was already landed and verified correct
  by direct code inspection)
- `trading-app/tests/test_app.py` (NEW)
- `trading-app/tests/test_automation.py` (NEW)
- `trading-app/tests/test_health_agent.py` (NEW)
- `process/features/security-remediation/active/trading-remediation_03-07-26/phase-02-remaining-findings_REPORT_03-07-26.md` (this file, NEW)

## Unrelated / Out of Scope

- `trading-app/static/ai_trading_chip.jpg` (untracked) — not part of this phase's blast radius;
  left untouched per explicit instruction.
