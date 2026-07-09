---
name: context:all-tests
description: "Testing quick-start router: runner selection, commands, debugging procedures for ControlN"
keywords: test, testing, pytest, runner, verification, debug, debugging, tests, gate, exit-gate
date: 04-07-26
---

# ControlN Trading Platform - All Tests

Last updated: (auto-generated)

Attach this file first when the task involves testing, verification, or test debugging.

This is the fast operator guide for the testing surface:

- which runner to use
- what command to start with
- how to quickly debug common failures
- which deeper file to read next

Do not load the whole `process/context/tests/` folder by default. Start here, then drill down.

---

## How This File Works

This is the `all-tests.md` entrypoint for the `tests/` context group. It follows the `all-*.md` routing convention:

1. Agents read `all-context.md` first and get routed here for testing tasks
2. This file gives quick decision rules and commands
3. For deeper details, agents follow the routing table below to specific docs

As the project grows, add deeper docs to this group (e.g., `e2e-tests.md`, `debugging-and-pitfalls.md`) and add routing entries below. This file stays the fast-start entrypoint.

---

## What This Covers

- test runner selection
- quick commands by package
- fast debugging procedures
- current testing gaps worth remembering

## Read This When

Use this file when you need to:

- run tests after implementation
- decide between test runners
- debug failing tests

## Quick Routing

<!-- STUDY: Replace with routing entries to deeper test docs as they are created. -->
<!-- Start with an empty table. Add rows as deeper docs are created during the project lifecycle. -->

<!-- Example of what a filled-in routing table looks like (from a mature project): -->

<!--
| If you need... | Read next |
|---|---|
| commands and scripts by package | `scripts-and-commands.md` |
| architecture, mocks, auth model, and runner split | `architecture-and-patterns.md` |
| Playwright setup, auth flow, and current specs | `e2e-tests.md` |
| failing-test triage and runtime debugging | `debugging-and-pitfalls.md` |
| known gaps and future test-system fixes | `known-issues.md` |
-->

(No deeper test docs yet. Add routing entries here as they are created.)

## Quick Decision Guide

### Automated Test Runner: pytest (added security-remediation Phase 1, expanded Phase 2)
`trading-app/tests/` exists with pytest coverage for the auth/session/rate-limit/concurrency
surfaces (Phase 1, commit `0e1b78c`) plus the auth-edge-case/trading-engine-correctness/XSS/
secrets-TLS surfaces (Phase 2, commit `c31e950`):

- `test_auth_cookie.py` — signed-cookie signing/verification, forged raw-cookie rejection, grace window
- `test_admin_and_ratelimit.py` — hardcoded-admin removal, login rate-limiting/lockout
- `test_order_concurrency.py` — `order_lock` TOCTOU race closure (concurrent `/api/order` requests)
- `test_app.py` (Phase 2, NEW) — guest-fallback 401 (A1), deactivated-user runtime purge (A3),
  regime/duplicate-position fail-closed guard (B4)
- `test_auto_trader.py` (Phase 2, NEW) — closed-position cleanup on feed omission (B1), `pl`-missing
  alerting (B2), per-user `trailing_monitor` isolation (B3), no-fabricated-price-order (B5), ATR
  `sl_points`/`trailing_sl_price` field separation (B6)
- `test_models.py` (Phase 2, NEW) — `decrypt_val` loud-failure signal (D1), user-deletion cascade
  across `USER_SCOPED_TABLES` (D5)
- `test_automation.py` (Phase 2, NEW) — `nightly_learning_date` round-trip through `state.save()`/`load()` (D4)
- `test_health_agent.py` (Phase 2, NEW) — exact-token allow-list rejects substring matches,
  `execute_fix` user-scoping (D6)

Run with: `cd trading-app && ./.venv/bin/python -m pytest tests/ -q` (**45 tests as of Phase 2**,
up from 14 after Phase 1). `pytest.ini` sets `testpaths = tests` (+ `norecursedirs`,
`asyncio_mode = auto`) so a bare `pytest` invocation from `trading-app/` never attempts to collect
the 20 pre-existing ad-hoc `test_*.py` scripts in the repo root — several are not valid pytest
modules (`test_login.py` has a genuine top-level-`await` `SyntaxError`). `pytest`/`pytest-asyncio`
are dev-only (`trading-app/requirements-dev.txt`) — confirmed absent from production
`requirements.txt`; `itsdangerous`/`certifi`/`requests` are the only test-relevant additions to
production `requirements.txt`.

**Known fragility:** Exit Gate check #4 (a `grep -A 60` line-window heuristic checking that
`record_trade()` is inside the `order_lock` block) is not a semantic check — see backlog note
`process/features/security-remediation/backlog/exit-gate-line-window-fragility_NOTE_03-07-26.md`.

**Live TLS re-verification (Phase 2, D2):** `python -c "import requests; requests.get('https://public.fyers.in/sym_details/NSE_FO.csv', timeout=10)"`
must succeed with no `verify=False`/`CERT_NONE` anywhere in the codebase (grep-confirmed) — this is
a Hybrid-tier live-network check, not part of the pytest suite.

**Agent-Probe items not yet scripted:** C1/C2 (XSS payload neutralization in `landing.html`/
`admin.html`) and D3 (service-worker `/api/funds` cache-exclusion) were verified by direct static
code read in Phase 2, not by a scripted browser probe. The repo's `vc-agent-browser` skill is the
recommended next step to convert these to a repeatable Agent-Probe gate (see Phase 2 report,
Execute-Agent Instructions E7/E8) — treat as an open test-infra improvement, not a blocker.

**Working headless-browser viewport probe pattern (established Phase 3, mobile-responsive):**
`npx --yes agent-browser` against a plain `python3 -m http.server 8899` rooted at `trading-app/`
(NOT `file://`, and NOT booting the live `app.py` trading server) is the confirmed way to load
`index.html`/`admin.html`/`landing.html` with their `/static/*` absolute-path assets resolving
correctly, then measure `document.documentElement.scrollWidth` / `body.scrollWidth` vs
`window.innerWidth` at target widths (375/390/768/1440px) and drive click/interaction checks
(e.g. hamburger-menu open/close, tab-nav scrollability). This is the same tooling the Agent-Probe
items above (C1/C2/D3) should reuse once someone scripts them — booting `app.py` is unnecessary
and risky (it connects to Fyers and starts live background trading loops) for any pure
frontend/layout/DOM verification.

This pytest suite covers the security-remediation blast radius (Phases 1-2) so far — most of
`trading-app/` (market_data_worker, SL/TSL logic outside the audited strategies, the web UI) still
has no automated coverage; manual/live verification remains the default for everything outside
`tests/`.

### Use Live Testing / Direct Deployment when
- Modifying FastAPI endpoints
- Tweaking Fyers API interactions
- Updating the frontend dashboard UI

## Default Verification Order

Unless the task clearly needs a different path:

1. Check for syntax and logic errors locally.
2. Ensure the FastAPI server can boot locally using `python app.py` (if environment permits).
3. Deploy to the GCP server (via SSH or direct file transfer) and monitor logs.
4. Manually verify through the web dashboard or Telegram logs.

## Commands

| Package | Runner | Command |
|---|---|---|
| Backend (auth/session/concurrency subset) | pytest | `cd trading-app && ./.venv/bin/python -m pytest tests/ -q` |
| Backend (everything else) | Manual/Python | `python app.py` (for local run if env configured) |
| Server Deploy | gcloud SSH | Scripts or commands to copy files to `35.234.213.226` and restart systemd service |

## Debugging Quick Reference

- **Log Monitoring:** Always check `/home/sritejpalika/trading-app/app.log` on the GCP server after deploying changes.
- **Fyers API Rate Limits:** Fyers throws HTTP 429 errors if hit too fast. Ensure caching and timeouts are respected when testing background workers.
- **Auth Expiry:** Token expiration results in Error -8. Re-authenticate via the dashboard if this happens.

## Known Gaps

- No unit tests for most core logic components (e.g. `market_data_worker`, SL/TSL logic) —
  pytest coverage exists only for the auth/session/rate-limit/order-concurrency surfaces added
  in security-remediation Phase 1 (see above).
- No end-to-end tests for the web interface.
- Deployments are manual, which can lead to downtime if errors are deployed.
- Live-money / live-provider paths (paper order round-trip, live Telegram webhook registration,
  live encryption-key rotation cutover) are not automatable in this environment — these remain
  deploy-day manual verification steps (see security-remediation Phase 1 report's Deploy-Day
  Runbook).
- XSS (C1/C2) and service-worker cache-scoping (D3) fixes from Phase 2 are verified by static code
  read only — no scripted browser probe (`vc-agent-browser`) has been run yet against these three
  gates; see "Agent-Probe items not yet scripted" above.
- 20 legacy ad-hoc `test_*.py` scripts in `trading-app/` root remain unconverted/non-pytest (one
  has a confirmed collection-time `SyntaxError`); `pytest.ini`'s `testpaths` scoping prevents them
  from interfering with the real suite but does not fix or remove them.
