---
name: plan:trading-remediation-phase-02-remaining-findings
description: "Trading Remediation — Phase 2: guest-fallback/OAuth-state auth gaps, trading-engine correctness fixes, XSS, and secrets/TLS/data-integrity cleanup"
date: 03-07-26
metadata:
  node_type: memory
  type: plan
  feature: security-remediation
  phase: phase-02
---

# Phase 02 — Remaining Findings: Auth Edge Cases, Trading-Engine Correctness, XSS, Secrets/TLS/Data-Integrity

**Program:** trading-remediation
**Umbrella plan:** process/features/security-remediation/active/trading-remediation_03-07-26/trading-remediation-umbrella_PLAN_03-07-26.md
**Phase status:** ✅ VERIFIED (code-complete, deploy-day/scripted-browser manual gates pending — see umbrella `## Current Execution State`)
**Report destination:** process/features/security-remediation/active/trading-remediation_03-07-26/phase-02-remaining-findings_REPORT_03-07-26.md (flat in the program task folder)

---

## Purpose

Phase 1 lands the core auth mechanism (session tokens replacing raw `user_id` cookies), Telegram webhook auth, admin credential/rate-limit hardening, and the order-lock/TOCTOU race fix. Phase 2 assumes that mechanism is live and closes the remaining findings from the security audit that are either a *different code path in the same function* (the guest-fallback branch of `get_current_client`, and OAuth `state` binding — both auth-adjacent but not the token mechanism itself) or an *entirely different risk category*: live-money trading-engine correctness bugs (fabricated prices being sent to the broker, a stop-loss field being silently corrupted, a duplicate-position guard that fails open, a single bad quote aborting monitoring for every user), reflected XSS in two admin/public HTML surfaces, and a cluster of secrets/TLS/data-integrity cleanup items (silent decrypt failure, disabled TLS verification, sensitive API caching, lost nightly-learning state, orphaned DB rows, and an LLM-driven auto-remediation agent that can take global action from unvalidated text).

This phase does not touch the session-token mechanism, Telegram webhook auth, admin login/rate-limiting, or the manual-order-path TOCTOU lock — those are Phase 1's exclusive scope. If any checklist item below is found to require modifying Phase 1's token mechanism itself, STOP and message phase1-writer/orchestrator rather than redeciding it here.

---

## Entry Gate

- Phase 1 complete and exit gate passed: session-token auth mechanism, Telegram webhook auth, `exit_position` fix, max-loss race fix, TOCTOU fix (manual order path), and secret rotation all landed and verified (validate-contract PASS + regression evidence recorded in Phase 1's report).
- `get_current_client` in `trading-app/app.py` reads from the new session-token mechanism for the authenticated branch (Phase 1 output) — this phase modifies only the unauthenticated/guest-fallback branch of that same function.

---

## Blast Radius

- `trading-app/app.py` — `get_current_client` guest-fallback branch; `/fyers/callback` and the auth-code URL builder (OAuth `state` binding); background-loop / admin deactivation-deletion interaction points (~429-478); duplicate-position/regime guard (~2055-2090)
- `trading-app/workers/auto_trader.py` — `trailing_monitor` per-user isolation (~63-180+); closed-position cleanup (~166-176); `pl` field defaulting (~120, ~179); fabricated estimated-price fallback (~830-860); ATR trailing `sl_points` overwrite (~324-336)
- `trading-app/workers/regime_worker.py`, `trading-app/workers/market_worker.py` — trend-cache population feeding the regime/duplicate-position guard **[VALIDATE FINDING: `ai_trend_cache` has no write-site anywhere in the codebase during V2 grounding — these files populate `state.market_regime` instead; B4's RESEARCH sub-step re-confirms this and routes the fix accordingly, see B4 item text]**
- `trading-app/tests/` (NEW — added by B0) — minimal pytest + pytest-asyncio harness (`conftest.py`, `pytest.ini`, `requirements-dev.txt`) scoped to unit-testing B2, B3, B5, B6, D1, D4, D5, D6 in isolation
- `trading-app/workers/health_agent.py` — `query_google_ai_for_fix` / `execute_fix` (~63-124) action allow-list and per-user scoping
- `trading-app/models.py` — `decrypt_val` (~69-77)
- `trading-app/fetch_lot_sizes.py` — TLS verification (line 9)
- `trading-app/app.py` — RSS/NSE fetch TLS context (`_RSS_SSL_CTX`, ~2508)
- `trading-app/static/landing.html` — `renderNews()` (~1504-1519)
- `trading-app/static/admin.html` — crash-log terminal (~560-569) and user-activity terminal (~647-660)
- `trading-app/static/service-worker.js` — fetch handler `/api/*` caching (~40-66)
- `trading-app/engine/automation.py` — `order_lock` definition (~43) unused in automated path; `nightly_learning_date` persistence (~743-770)
- `trading-app/models.py` — user-deletion query (orphaned dependent-table rows)

---

## Implementation Checklist

### Step A — Auth/session edge-case hardening (guest fallback, OAuth state, deactivated-user background loops)

- [ ] A1. `trading-app/app.py:798-810` (`get_current_client`) — **current:** when the `user_id` cookie is absent, the function silently sets `user_id = 0` and returns a `FyersClient` for guest/user-0 context instead of rejecting the request; **target:** raise `HTTPException(status_code=401, detail="Unauthorized")` when no session/user identity is present on any trading-critical endpoint (order placement, positions, funds, settings, automation toggles). Keep a narrow, explicitly-named allowlist for genuinely public routes (e.g. landing page data) if any currently rely on the guest path — enumerate them explicitly in the diff, don't infer. Depends on Phase 1's session-token read already being wired into this function for the authenticated branch. **Test:** integration test — request with no session cookie against `/api/order`, `/api/positions`, `/api/user/settings` returns 401; a call against an explicitly-allowlisted public route (if any) still succeeds.
- [ ] A2. `trading-app/app.py:529-531` and `/fyers/callback` (~534-570) — **current:** OAuth `state` is set to the raw `user_id` (`url.replace("state=None", f"state={user_id}")`) and the callback trusts `state` at face value to re-identify and re-cookie the user, with no binding to the session that actually initiated the flow — any party who observes/guesses a `user_id` can complete another user's OAuth callback and receive their session cookie; **target:** generate a signed, single-use, short-TTL nonce server-side when `/fyers/auth-url` (or equivalent initiator) is called, store it keyed to the initiating session (e.g. in a server-side table/cache mapping `nonce -> user_id, expiry, used`), pass the nonce as `state`, and on `/fyers/callback` validate the nonce (exists, unexpired, unused) before trusting the `user_id` it maps to; mark it used-once. Reject the callback with a redirect to `/login?reason=invalid_state` if validation fails. **Test:** hybrid — replay a captured/expired/tampered `state` value against `/fyers/callback` and confirm it is rejected; a valid single-use flow still succeeds once and fails on replay.
- [ ] A3. `trading-app/app.py:432-449` (`toggle_user_status`) and `~465-477` (`admin_delete_user`) plus background loops (`automation_loop`, hard-exit scheduler, token-refresh loop, `trailing_monitor` in `auto_trader.py`) — **current:** deactivating or deleting a user updates the DB row (and for delete, the `users`/`user_states` tables) but does not touch the in-memory `USER_CONTEXTS` dict or any background loop's per-user iteration, so a deactivated/deleted user's automation, trailing monitor, and token refresh keep running against live broker sessions until the process restarts or their next API call 401s; **target:** on deactivate/delete, synchronously remove the user's entry from `USER_CONTEXTS` (and any per-user cache maps such as `ai_trend_cache`/`USER_CONTEXTS`-scoped state) and set `automation_enabled = False` on their `UserState` before deleting DB rows, so every background loop's `for u_id, client in USER_CONTEXTS.items()` naturally excludes them on its next tick. **Test:** integration — deactivate a user with an active automated trade running in a background loop; assert the next loop tick no longer processes that `u_id` and no further orders are placed for them.

### Step B — Trading-engine correctness (live-money-impacting)

**Cross-phase overlap note (apply before starting B1):** B1, B2, B3, B6 all edit `trailing_monitor()` in `trading-app/workers/auto_trader.py` — the SAME function Phase 1's items D1 (`exit_position`→`cancel_order` fix, ~lines 247/262) and E1 (max-loss race reorder, ~lines 125-156) also edit. The umbrella's cross-phase no-overlap confirmation only checked `app.py`, not `auto_trader.py`, where the real overlap is. Because Phase 2's Entry Gate requires Phase 1 to land first, there is no live merge conflict, but execute-agent MUST re-read the actual POST-Phase-1 state of `trailing_monitor()` fresh (using content-anchored search, not this plan's pre-Phase-1 line numbers) before implementing B1/B2/B3/B6. Apply B3's try/except wrap with explicit awareness that it re-indents the entire per-user body that B1/B2/B6 also touch — verify B1/B2/B6's target content by content, not cached whitespace/line offsets, after B3 lands. Similarly, B4 and Phase 1's item F1 both edit `place_order()` in `app.py` (B4's target range is nested inside F1's range) — implement B4 against Phase 1's landed lock-widened structure, not this plan's pre-Phase-1 code snapshot.

- [ ] B0. Stand up a minimal `pytest` + `pytest-asyncio` test harness scoped to this phase's pure-unit-testable items. **Current:** no `pytest`/`unittest`/CI test runner exists in `trading-app/` (confirmed by direct inspection — no `pytest` in `requirements.txt`, no `pytest.ini`/`setup.cfg`/`pyproject.toml`/`conftest.py`; existing `test_*.py` files are ad-hoc non-pytest debug scripts). **Target:** create a new `trading-app/tests/` directory with a `conftest.py` providing fixtures that mock `FyersClient`/DB calls sufficient to unit-test the 8 pure-unit-testable items in isolation: B2, B3, B5, B6, D1, D4, D5, D6. Add a `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]` section) and a `requirements-dev.txt` listing `pytest>=8.0` and `pytest-asyncio>=0.24` — do NOT add these to the production `requirements.txt`. **The `pytest.ini`/`pyproject.toml` MUST set `testpaths = trading-app/tests` (or equivalent `[tool.pytest.ini_options] testpaths = ["tests"]` scoped relative to `trading-app/`) so that a bare `pytest` invocation never attempts to collect the 20 pre-existing ad-hoc `test_*.py` scripts in `trading-app/` root (e.g. `test_login.py`, `test_db.py`, `test_webhook.py`, etc.) — several of these contain bare top-level `await` statements outside any `async def`, which is a Python `SyntaxError` at collection time, not a test failure. [VALIDATE FINDING, cycle 2: confirmed 20 such files exist (more than the 2 named in the original Test Infra note), and confirmed `test_login.py:5` has a bare top-level `await Database.get_user_by_username(...)` outside any function — this is a real SyntaxError, not a hypothetical.]** Scope is a minimal harness for these 8 items only, not a full test-infrastructure buildout. **Test:** `pytest trading-app/tests/ --collect-only` exits 0 and discovers at least one placeholder test per targeted item; additionally, bare `pytest` run from `trading-app/` (no path argument) must also exit 0 / collect only `trading-app/tests/` content, proving the `testpaths` scoping actually excludes the legacy ad-hoc scripts.
- [ ] B1. `trading-app/workers/auto_trader.py:166-176` (closed-position cleanup) — **current:** a trade is only classified "completed" when `pos is not None and abs(pos.get("qty", 0)) == 0` — if the broker's positions feed simply omits a fully-closed position (common once a position nets to zero and rolls off some brokers' snapshot), `pos` is `None` and the trade is never cleaned up, leaving a stale entry in `state.active_auto_trades` indefinitely; **target:** also treat `pos is None` (position absent from the feed) as a completion candidate — cross-check against order-status/trade-book API (or a configurable grace period + explicit no-position-found log) before clearing, so cleanup doesn't misfire on a transient empty feed but does eventually clear on sustained absence. **Test:** hybrid — simulate a positions feed that omits an entry that was previously present and confirm cleanup still fires (after any grace-period logic) without needing `qty == 0` explicitly.
- [ ] B2. `trading-app/workers/auto_trader.py:120,179` (`pl` field default) — **current:** `p.get("pl", 0)` / `pos.get("pl", 0)` silently treats a missing/malformed `pl` field as `₹0` P&L, which feeds directly into the max-loss emergency-exit check (`total_pnl <= MAX_LOSS_LIMIT`) — a broker response missing `pl` masks real losses and can suppress the emergency exit; **target:** when `pl` is missing or not numeric, log an error/alert (broadcast to admin/Telegram) and exclude that position from the aggregate sum with a flagged-incomplete state rather than silently substituting 0 — do not let a malformed response make the loss check look better than reality. **Test:** unit — feed a positions list with one entry missing `pl`; assert an alert fires and the aggregate calculation does not silently zero it out.
- [ ] B3. `trading-app/workers/auto_trader.py:63-180+` (`trailing_monitor` main loop) — **current:** the entire `for u_id, client in USER_CONTEXTS.items():` body for ALL users runs inside a single `try/except` at the loop-tick level (line ~66), so a single user's malformed data or an unexpected exception raised anywhere inside their iteration propagates and can abort processing for every other user in that tick; **target:** wrap the per-user body of the loop (everything from `state = get_user_state(u_id)` through the end of that user's processing) in its own `try/except Exception as e: logger.error(...); continue`, so one user's failure is isolated and every other user's monitoring continues uninterrupted. **Test:** unit/integration — inject a malformed state for one user (e.g. `active_positions` containing a non-dict entry) and confirm other users' max-loss checks and trailing-SL updates still execute in the same tick.
- [ ] B4. `trading-app/app.py:2055-2090` (regime/duplicate-position guard, manual order path) and the underlying `ai_trend_cache` population in `regime_worker.py`/`market_worker.py` — **RESEARCH SUB-STEP (required before any fix work, per Concern V1):** before touching this item, run `grep -rn "ai_trend_cache" trading-app/ --include=*.py` (excluding `.venv`) and confirm by direct code reading whether `ai_trend_cache` is genuinely ever populated anywhere in the current live codebase. Also confirm, by reading `place_order` in `app.py` end-to-end, whether `client.place_order(...)`, `state.record_trade()`, and the function's `return result` are structurally nested inside the `if trend_cache:` block. Document the finding in the phase report before proceeding. **[VALIDATE FINDING, cycle 2 — RE-CONFIRMED via fresh independent grounding (not just trusted from cycle 1): `grep -rn "ai_trend_cache" trading-app --include="*.py"` (excluding `.venv`) returns exactly 3 hits — declaration (`state.py:41`, `= {}`), alias (`app.py:729`), and the single read site (`app.py:2071`) — no write site anywhere. Direct read of `app.py:2039-2103` confirms `result = await asyncio.to_thread(client.place_order, ...)`, `state.record_trade()`, and `return result` are all nested inside `if trend_cache:` (lines 2072-2102); there is no code after that block, so when `trend_cache` is falsy (always, since the cache is never written) the function currently falls through to an implicit `None` return — manual order placement silently no-ops today, it does not "fail open." `regime_worker.py` confirmed to populate `state.market_regime` (not `ai_trend_cache`) as the live, actively-written alternative signal. This confirms the plan's "current"/"target" text below is accurate, not merely hypothesized.]**
  - **If `ai_trend_cache` is confirmed genuinely dead/unpopulated:** escalate to product/orchestrator whether to (a) wire the duplicate-position/regime check off `state.market_regime` (the actual signal `regime_worker.py`/`market_worker.py` populate today) or a real per-underlying trend source as part of this fix, or (b) accept that manual order placement becomes permanently blocked by a fail-closed fix and get explicit sign-off before implementing — document the choice in the phase report. Do not silently pick (a) or (b) without recording the decision.
  - **current (pending the research sub-step above; treat as unconfirmed until re-verified):** `trend_cache = ai_trend_cache.get(underlying)` — when the cache is empty, the `if trend_cache:` guard is falsy and the regime-lockout/duplicate-position check is skipped; the plan originally assumed this means the check **fails open** (trade proceeds unchecked). However, direct code inspection during VALIDATE found `client.place_order`/`state.record_trade()`/the function's only `return result` are nested INSIDE the `if trend_cache:` block — meaning if the cache is genuinely always empty, actual current behavior may already be "manual orders silently no-op" (implicit `None` return), not "fails open." The research sub-step above must resolve which is true before the fix below is written.
  - **target (once the research sub-step and any required escalation are resolved):** if the check is routed off `state.market_regime` (or another live signal per the escalation outcome), fail closed when that signal is empty/stale (older than an explicit freshness threshold) — block the trade with an explicit, structured rejection body (not just a silent no-op) rather than allowing it through or leaving it as an unlabeled `None` return. Dedent the order-placement path (`client.place_order`, `state.record_trade()`, `return result`) out of the guard conditional so a real fail-closed rejection is returned explicitly, distinguishable from a generic no-op. Apply the same fail-closed fix to the automated path if it consults the same/replacement signal.
  - **Test:** unit — call the order path with the regime/duplicate-position signal empty/stale for the underlying and assert a structured rejection is returned (not a silent no-op and not an unchecked trade); this must assert the specific rejection body, not merely "no order placed" (which may already be true today and would not catch a regression).
  - **[VALIDATE FINDING — incorporated above, see Concern V1 in the Validate Contract]**
- [ ] B5. `trading-app/workers/auto_trader.py:830-855` (fabricated estimated-price fallback) — **current:** when live quotes and candle data are both unavailable, the code falls through to a hand-rolled Black-Scholes-flavored guess (`intrinsic + time_value`) and then **places a live market order at that guessed price** with only a log line noting it's an estimate — a stale/guessed premium can be significantly off from the real fill price on a live order; **target:** when entry price cannot be sourced from an actual quote or recent candle (Try 1-2 fail), skip the trade for this cycle (matching the existing `if entry_price <= 0: ... return` behavior already used elsewhere in this function) instead of falling through to the fabricated Try-3 estimate; remove the fabricated-estimate branch entirely, or gate it behind an explicit opt-in flag defaulted OFF with a loud warning if product decides some fallback is wanted later (default behavior for this phase is: no fabricated-price live orders). **Test:** unit — force both quote and candle fetch paths to fail and assert no order is placed (trade skipped, log/alert emitted) rather than an order placed at a synthetic price.
- [ ] B6. `trading-app/workers/auto_trader.py:300-336` (Strategy 5 ATR trailing) — **current:** `new_sl = ltp - (1.2 * atr)` computes an **absolute price**, and `if new_sl > current_sl: ... t["sl_points"] = new_sl` overwrites the `sl_points` field — which is used elsewhere in the codebase as a **distance/offset**, not an absolute price — with that absolute price value; any downstream code reading `sl_points` as a distance (e.g. target calculations, other strategies, reporting) will silently misinterpret the stored value; **target:** introduce a separate field (e.g. `t["trailing_sl_price"]`) to hold the absolute trailed stop price for this strategy, leave `sl_points` untouched/consistent with its distance semantics elsewhere, and update the `modify_order` call and any other reader of this trade's SL to use the correct field for its context. **Test:** unit — run the Strategy 5 trailing branch and assert `sl_points` is not mutated to an absolute-price value; assert the new field holds the trailed absolute price and is what's passed to `modify_order`. **[VALIDATE NOTE: this line range and B3's line range both fall inside `trailing_monitor`'s per-user body — see Concern V2/V3 below on cross-item and cross-phase ordering.]**

### Step C — Reflected XSS (admin + public HTML)

- [ ] C1. `trading-app/static/landing.html:1504-1519` (`renderNews()`) — **current:** `n.title`, `n.source`, `n.pubDate` are interpolated directly into an `innerHTML` template string, and `n.link` is interpolated unescaped directly into an `onclick="window.open('${n.link}',...)"` attribute — both a classic innerHTML-injection XSS vector (via `title`) and an attribute-breakout vector (via `link` containing a `'` or `"`) fed by a third-party RSS feed; **target:** build each news-item node with `document.createElement` + `textContent` assignment for `title`/`source`/`pubDate` (no `innerHTML` for feed-controlled text), and instead of inlining `link` into an `onclick` attribute string, attach a real `addEventListener('click', () => window.open(safeUrl, '_blank'))` where `safeUrl` is validated against an `http:`/`https:` protocol allowlist (reject `javascript:`, `data:`, etc.) before use. **Test:** unit/manual — feed a news item with `title` containing `<img src=x onerror=alert(1)>` and a `link` of `javascript:alert(1)`; assert no script executes and the malicious link is not opened.
- [ ] C2. `trading-app/static/admin.html:560-569` (crash-log terminal) and `~647-660` (user-activity terminal) — **current:** `div.innerHTML = \`...${log.message}...\`` in both viewers interpolates `log.message` (attacker-influenceable — it's application/error log text, potentially reflecting user input or crafted error strings) directly into `innerHTML`; **target:** replace with `textContent` for the message portion (keep timestamp/color styling via separate `span` elements built with `createElement`, not string-interpolated `innerHTML`) in both the crash-log and user-activity log renderers. **Test:** unit/manual — seed a log entry with `message = "<img src=x onerror=alert(1)>"` and confirm it renders as literal text in both terminals, not as executed markup.

### Step D — Secrets/TLS/data-integrity cleanup

- [ ] D1. `trading-app/models.py:69-77` (`decrypt_val`) — **current:** on any decryption exception, the function silently falls back to returning the raw (still-encrypted) value as if it were plaintext, with only a swallowed exception variable (`except Exception as e:` — `e` unused) and no logging; downstream code then uses ciphertext as a live credential/secret without any signal that decryption failed; **target:** log the exception (including which field/user context if available, without logging the secret value itself) at ERROR level and either raise a dedicated `DecryptionError` for the caller to handle explicitly, or return a clearly-sentinel value the caller must check — do not silently return ciphertext as if it were plaintext. Audit callers (`decrypt_user_dict` and any direct callers) to confirm they handle the new failure signal instead of blindly using the return value. **Test:** unit — corrupt an encrypted value and call `decrypt_val`; assert an error is logged/raised rather than a silently-wrong plaintext value returned.
- [ ] D2. `trading-app/fetch_lot_sizes.py:9` (`requests.get(..., verify=False, ...)`) and `trading-app/app.py:2508` (`_RSS_SSL_CTX.verify_mode = ssl.CERT_NONE`) — **current:** both disable TLS certificate verification entirely, exposing these fetches (lot-size CSV from Fyers, RSS/NSE market data) to MITM tampering; **target:** fix the underlying CA bundle issue instead of disabling verification — install/point at a proper CA bundle (e.g. `certifi.where()` passed explicitly, or fix the system trust store in the deployment image), removing `verify=False` and `CERT_NONE`. If a specific intermediate cert is the blocker, document and pin it rather than disabling verification wholesale. **Test:** hybrid — run both fetches in the target deployment environment with verification re-enabled and confirm they succeed without `CERT_NONE`/`verify=False`; if a target environment genuinely cannot get valid certs (e.g. corporate proxy MITM), document as a known-gap with rationale, do not silently re-disable.
- [ ] D3. `trading-app/static/service-worker.js:40-66` (fetch handler) — **current:** the Network-First `/api/*` branch caches ANY 200 response including `/api/funds`, `/api/positions`, `/api/orders`, `/api/admin/*`, `/api/user/settings` — sensitive financial/account data ends up in the Cache Storage API, persisted on-disk on the client and readable by anything with local device/devtools access, and stale cached data could also be served offline for these paths; **target:** add an explicit exclusion list (`funds`, `positions`, `orders`, `admin/`, `user/settings`, and any other sensitive `/api/*` prefix) checked before the `cache.put` call — these paths bypass caching entirely (network-only, no cache read/write). Non-sensitive `/api/*` paths (e.g. static market-news, public index/badge data) keep the existing Network-First caching behavior. **Test:** unit/manual — trigger a fetch to `/api/funds` through the service worker and confirm no cache entry is created for it; confirm a non-sensitive `/api/*` path still gets cached as before.
- [ ] D4. `trading-app/engine/automation.py:743-770` (nightly learning date) — **current:** `self.nightly_learning_date = current_date_str` is set on the in-memory object but never included in the payload written by `state.save()`, so on process restart the nightly-learning "already ran today" guard is lost and nightly learning can double-run after any restart; **target:** add `nightly_learning_date` to the fields persisted/restored by `state.save()`/`state.load()` (or the equivalent `UserState` serialization) so it survives a restart. **Test:** unit — set `nightly_learning_date`, call `state.save()`, reload state fresh, assert the field round-trips.
- [ ] D5. `trading-app/models.py` (`admin_delete_user` DB cleanup, `app.py:465-477`) — **current:** deletion only removes rows from `users` and `user_states`; any other dependent tables (e.g. trade history, health-agent memory keyed by user, session/token tables introduced by Phase 1) are left orphaned, referencing a deleted `user_id`; **target:** enumerate every table with a `user_id`/`uid` foreign-key-shaped column (grep schema for the column name) and delete/cascade those rows in the same transaction as the `users`/`user_states` delete, or add proper `ON DELETE CASCADE` constraints if the schema migration path supports it within this phase's scope. **Test:** integration — create a user with rows in every dependent table, delete the user, assert no dependent-table rows referencing that `user_id` remain. **[VALIDATE NOTE: confirmed 7 additional tables exist with likely user-scoped columns beyond `users`/`user_states` — `daily_pnl_history`, `paper_pnl_history`, `system_logs`, `health_memory`, `swarm_trade_records`, `swarm_agent_configs`, `swarm_learning_logs`. Enumeration scope is larger than "session/token tables introduced by Phase 1" alone — the plan's own instruction to grep-enumerate already covers this correctly.]**
- [ ] D6. `trading-app/workers/health_agent.py:63-124` (`query_google_ai_for_fix` / `execute_fix`) — **current:** the LLM's free-text suggestion is matched via substring (`if "restart_ws" in text`, `if "relogin" in text`) rather than an exact allow-list, so any LLM output merely containing those substrings anywhere in a longer sentence triggers the action; and `execute_fix` for `restart_ws`/`relogin` loops over **all** `USER_CONTEXTS` regardless of which user's error triggered the diagnosis; **target:** (a) require the LLM response to match one exact action token from a hardcoded allow-list (`{"restart_ws", "relogin", "clear_cache", "wait"}`) via exact string equality after trim/lowercase — reject anything else and fall back to `"wait"`; (b) thread the originating user context (the user whose error triggered `query_google_ai_for_fix`) through to `execute_fix` and scope `restart_ws`/`relogin` to that specific `u_id` when the triggering error was user-scoped, falling back to the existing all-users behavior only for genuinely global errors (no identifiable user). **Test:** unit — feed `query_google_ai_for_fix` a response like `"You should definitely NOT restart_ws right now"` and assert the substring match no longer fires the action (exact-token check fails and it falls back to `wait`); feed a user-scoped error and assert `execute_fix` only acts on that user's `USER_CONTEXTS` entry.

---

## Exit Gate

```bash
# Automated test suite covering all Step A-D changes (exact command sourced from repo test runner during EXECUTE/VALIDATE — see Test Infra Improvement Notes)
pytest trading-app/tests/ -v
# Expected: exit 0, all new/updated tests green

# Static/manual XSS verification (Step C)
{manual probe: inject <img src=x onerror=alert(1)> via mocked RSS feed and via a seeded log entry}
# Expected: no script execution in landing.html news list or admin.html log terminals

# TLS re-verification (Step D2)
python -c "import requests; requests.get('https://public.fyers.in/sym_details/NSE_FO.csv', timeout=10)"
# Expected: succeeds without verify=False; raises SSLError only if CA bundle is genuinely broken (escalate, do not silently re-disable)
```

- All Step A-D checklist items checked off with code changes landed
- No `verify=False` / `CERT_NONE` remaining in `fetch_lot_sizes.py` or the RSS/NSE fetch path (or documented known-gap with rationale)
- No `innerHTML` assignment of feed-/log-controlled text remains in `landing.html` or `admin.html` for the touched viewers
- `get_current_client` guest-fallback branch returns 401 on trading-critical endpoints; OAuth `state` is bound to a signed server-side nonce
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 1's session-token mechanism has not actually landed/is not readable from `get_current_client`'s authenticated branch yet (A1 depends on it existing, not on modifying it)
- No test runner/framework currently exists in `trading-app/` (repo has no visible `pytest`/`unittest` config discovered during this planning pass) — if EXECUTE finds this true, the Fully-Automated tier for several items becomes Hybrid/manual-probe until a minimal test harness is stood up; this is a known infra gap, not a reason to skip the fix itself
- A genuinely broken CA bundle in the deployment environment that cannot be fixed within this phase's scope (D2) — document as known-gap with explicit rationale rather than silently blocking the whole phase
- Ambiguity discovered at EXECUTE time about which app.py line ranges the `state` cookie interacts with Phase 1's new token mechanism (A1/A2 boundary) — message phase1-writer before proceeding

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked (line-number drift noted below — re-verify against Phase 1's actual landed diff before EXECUTE)
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated (B0 harness sub-step with `testpaths` scoping fix, B4 RESEARCH sub-step + escalation branch, Step B/B4 cross-phase overlap notes — P1-P4 applied and independently re-confirmed against live code during cycle-2 VALIDATE). Note: no explicit `## Inner Loop Refresh Note` section was added by the supplement pass; the content changes are directly evidenced in the Blast Radius/Implementation Checklist text above — flagged as a minor audit-trail gap in the Validate Contract below, not a blocking issue.
- [x] 4. PVL — vc-validate-agent: full V1-V7, cycle 2; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md`. **Gate: PASS. Cleared for EXECUTE.**
- [x] 5. EXECUTE — all checklist items (A1-A3, B0-B6, C1-C2, D1-D6) done; 45/45 pytest gates green; D2 TLS live-verified; C1/C2 XSS statically verified; report written (`phase-02-remaining-findings_REPORT_03-07-26.md`). Open item: Phase 2's own high-risk evidence pack not yet created (see report).
- [x] 6. EVL — independently re-confirmed: 45/45 pytest tests green, `py_compile` clean across all
  touched modules, live TLS re-verification (D2) against the real Fyers endpoint, 7 highest-risk
  claims re-verified against live code post-commit. High-risk evidence pack
  (`harness-phase2/*.json`) validator: 0 failures. Follow-up stub registered:
  `oauth-state-binding-hardening_NOTE_04-07-26.md` (adversarial-validation residual, user-accepted
  as backlog, not a blocker). EVL HANDOFF SUMMARY: gates_green — context_partial: scripted-browser
  probe for C1/C2/D3 not run (static-only verification accepted).
- [x] 7. UPDATE PROCESS — phase report written (`phase-02-remaining-findings_REPORT_03-07-26.md`),
  umbrella `## Current Execution State` + Program Status Table rewritten, `process/context/`
  updated (`all-context.md`, `tests/all-tests.md`), committed as `c31e950` on `main`.

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

- `trading-app/app.py` (get_current_client, /fyers/callback, auth-url builder, admin toggle/delete handlers, duplicate-position guard, RSS SSL context)
- `trading-app/workers/auto_trader.py` (trailing_monitor, closed-position cleanup, pl aggregation, ATR trailing, fabricated-price fallback)
- `trading-app/workers/regime_worker.py`, `trading-app/workers/market_worker.py` (trend-cache freshness)
- `trading-app/workers/health_agent.py` (query_google_ai_for_fix, execute_fix)
- `trading-app/models.py` (decrypt_val, user-deletion cascade)
- `trading-app/fetch_lot_sizes.py`
- `trading-app/static/landing.html`, `trading-app/static/admin.html`, `trading-app/static/service-worker.js`
- `trading-app/engine/automation.py` (nightly_learning_date persistence)

---

## Public Contracts

- `/fyers/auth-url` and `/fyers/callback` — external contract with Fyers OAuth changes only in that `state` becomes an opaque signed nonce instead of a raw `user_id`; the redirect/cookie behavior on success is unchanged from the caller's perspective
- Trading-critical API endpoints (`/api/order`, `/api/positions`, `/api/funds`, `/api/user/settings`, automation toggles) — behavior change: unauthenticated requests now receive 401 instead of a silently-scoped guest/user-0 response. This is an intentional breaking change for any caller relying on the guest fallback; no legitimate caller should have been relying on it.
- `/api/market-news` response shape — unchanged; only client-side rendering changes (Step C1)
- Service worker caching contract — unchanged for non-sensitive `/api/*` paths; sensitive paths (funds/positions/orders/admin/user-settings) no longer cached, which is a behavior change only in offline/stale-serving scenarios for those paths (acceptable — they should never be served stale)
- `/api/order` (manual order placement) — B4's RESEARCH sub-step (now independently re-confirmed, see Validate Contract Concern V1) will very likely find `ai_trend_cache` is genuinely dead, meaning today's actual behavior is "manual orders silently no-op" (not "fails open"), and the fail-closed fix will change that to an explicit structured rejection — a smaller, better-understood behavior change than the plan originally feared (see Plan Updates P2/P3 applied in cycle 1's supplement).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| A1: unauthenticated request to `/api/order`/`/api/positions`/`/api/user/settings` returns 401 | Fully-Automated | Guest fallback closed on trading-critical endpoints |
| A2: replayed/expired/tampered OAuth `state` rejected at `/fyers/callback` | Hybrid (requires mocked Fyers OAuth flow) | OAuth state bound to originating session |
| A3: deactivating a user with a live automated trade stops their background-loop processing on next tick | Hybrid (requires running background loop in test harness) | Deactivated/deleted users excluded from live background loops |
| B0: pytest harness collects only `trading-app/tests/`, never the 20 legacy ad-hoc `test_*.py` scripts | Fully-Automated | `pytest.ini`/`pyproject.toml` `testpaths` scoping prevents collection-time SyntaxErrors |
| B1: positions feed omitting a closed position still triggers cleanup | Hybrid | Closed-position cleanup handles broker feed omission |
| B2: positions list with missing `pl` triggers alert, not silent-zero | Fully-Automated | Malformed `pl` never silently treated as zero loss |
| B3: malformed single-user state doesn't abort other users' loop tick | Fully-Automated | Per-user isolation in trailing_monitor |
| B4: empty trend_cache/market_regime blocks trade with explicit rejection (fail closed) | Fully-Automated, gated by RESEARCH sub-step (E2) | Regime/duplicate-position guard fails closed with a structured rejection, not a silent no-op |
| B5: unavailable quote/candle data skips trade, no fabricated-price order placed | Fully-Automated | No live order placed on a guessed price |
| B6: Strategy 5 ATR trail does not overwrite `sl_points` with absolute price | Fully-Automated | Distance vs absolute-price field separation preserved |
| C1: malicious RSS title/link neutralized in landing.html | Agent-Probe (manual or scripted browser check — see execute-agent instruction E7) | XSS via RSS feed content closed |
| C2: malicious log message neutralized in admin.html terminals | Agent-Probe (manual or scripted browser check — see execute-agent instruction E7) | XSS via log message content closed |
| D1: corrupted encrypted value triggers loud failure, not silent plaintext-as-ciphertext | Fully-Automated | decrypt_val fails loudly |
| D2: lot-size and RSS/NSE fetches succeed without verify=False/CERT_NONE | Hybrid (requires target deployment env with fixed CA bundle) | TLS verification restored |
| D3: `/api/funds` not present in Cache Storage after service-worker fetch | Agent-Probe (manual or scripted browser check — see execute-agent instruction E8) | Sensitive API paths excluded from SW caching |
| D4: nightly_learning_date round-trips through state.save/load | Fully-Automated | Nightly-learning guard survives restart |
| D5: no orphaned dependent-table rows after user deletion | Fully-Automated | Cascading delete cleans all dependent tables (7 tables confirmed beyond users/user_states — see D5 note above) |
| D6: LLM fix-action exact-match allow-list rejects substring-only matches; execute_fix scopes to originating user when known | Fully-Automated | Health-agent auto-remediation constrained to allow-listed actions and scoped user |

---

## Test Infra Improvement Notes

**[VALIDATE CONFIRMED — cycle 1 and re-confirmed cycle 2]** No `pytest`/`unittest`/CI test runner exists in `trading-app/`. Verified during VALIDATE: `requirements.txt` has no `pytest`; no `pytest.ini`/`setup.cfg`/`pyproject.toml`/`conftest.py` under `trading-app/`; the existing `test_*.py` files present (20 confirmed by direct `find`: `test_msg2.py`, `test_expiry.py`, `test_webhook.py`, `test_db.py`, `test_login.py`, `test_quotes.py`, `test_ai.py`, `test_auto_login.py`, `test_login2.py`, `test_lots.py`, `test_msg.py`, `test_fyers.py`, `test_ws.py`, `test_lots_stock.py`, `test_pnl.py`, `test_chain.py`, `test_oc.py`, `test_lots_stock3.py`, `test_gemini.py`, `test_lots_stock2.py`) are ad-hoc debug scripts, not pytest suites — confirmed directly by reading `test_login.py`, which has a bare top-level `await Database.get_user_by_username(...)` at line 5, outside any `async def`/`asyncio.run()` wrapper (a genuine Python `SyntaxError`, re-confirmed by direct read in cycle 2, not merely cited from cycle 1). `process/context/tests/all-tests.md` independently confirms: "this project does not use automated test runners... testing is done by manual verification and direct deployment." The B0 checklist item now explicitly requires `testpaths` scoping in `pytest.ini` so a bare `pytest` invocation cannot accidentally attempt to collect these 20 files and fail with SyntaxErrors unrelated to this phase's changes.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/security-remediation/active/trading-remediation_03-07-26/phase-02-remaining-findings_PLAN_03-07-26.md`
- Last completed step: PVL (Step 4) — **PASS, cycle 2.** Plan-supplement cycle 1 (P1-P4) verified applied and adequate; one new bounded finding (pytest collection-scope risk) resolved via Execute-Agent Instruction E9, no further supplement cycle required.
- Validate-contract status: **PASS — written 03-07-26, generated-by: outer-pvl, supersedes 2026-07-03 (outer-pvl, CONDITIONAL)**
- Supporting context files loaded: `process/context/all-context.md`, `process/context/tests/all-tests.md`, `trading-app/app.py`, `trading-app/workers/auto_trader.py`, `trading-app/workers/regime_worker.py`, `trading-app/workers/market_worker.py`, `trading-app/workers/health_agent.py`, `trading-app/models.py`, `trading-app/state.py`, `trading-app/fetch_lot_sizes.py`, `trading-app/static/landing.html`, `trading-app/static/admin.html`, `trading-app/static/service-worker.js`, `trading-app/engine/automation.py`, `trading-app/requirements.txt`, Phase 1 plan, umbrella plan
- Next step: orchestrator may route to `ENTER EXECUTE MODE` for this plan (umbrella's `## Stable Program Goal` governs autonomy/hard-stop rules — no per-phase `## Autonomous Goal Block` is written here per BRANCH B).

---

## Validate Contract

Status: PASS
Date: 03-07-26
date: 2026-07-03
generated-by: outer-pvl
supersedes: 2026-07-03 (outer-pvl) — outer PVL re-run after plan-supplement cycle 1 (3 CONCERN-level gaps addressed); this cycle re-grounds every supplement edit against live code rather than trusting the supplement was applied correctly.

Parallel strategy: sequential (direct grounded re-verification)
Rationale: 7-signal score = 4/7 (S2 auth/schema surface, S4 phase-program, S6 high-risk class, S7 8+ blast-radius files) → HIGH tier would normally recommend parallel-subagents or workflow. This cycle's actual task shape was a *targeted* re-verification of three specific supplement edits (B0 harness scope, B4 RESEARCH sub-step, Step B cross-phase overlap note) plus spot re-grounding of the Section A/C/D findings that were not touched by the supplement — every check required cross-referencing the SAME small set of already-open files (`app.py`, `auto_trader.py`, `state.py`, `regime_worker.py`, `requirements.txt`), so a parallel fan-out would have re-read those files redundantly without adding coverage. Recommend parallel-subagents (one per Layer 1 dimension + one per Section A-D) for the NEXT re-validation pass, if EXECUTE-time findings trigger one — the remaining checks are now more independent since the 3 original cross-cutting concerns are resolved.

### 0. Supplement Verification (Cycle 2 — direct re-read, not trust-the-supplement)

Per the task's explicit instruction, each of the 3 cycle-1 CONCERN-level gaps was independently re-verified against live plan text and live source code (not assumed resolved because the plan file mentions them):

1. **B4 premise / `ai_trend_cache` (cycle-1 Concern V1):** RESOLVED and RE-CONFIRMED. Plan text now contains a RESEARCH sub-step (grep + code-read) and an explicit escalation branch (route to `state.market_regime` or accept fail-closed, with sign-off required) before any fix code is written. Fresh grounding in this cycle (`grep -rn "ai_trend_cache" trading-app --include="*.py"`, direct read of `app.py:2039-2103`) confirms the underlying facts the supplement's escalation branch depends on: `ai_trend_cache` has zero write sites (only a `{}` declaration, an alias, and one read); `place_order`/`record_trade`/`return result` are nested inside `if trend_cache:`; `state.market_regime` is the live, actively-written alternative (confirmed in `regime_worker.py`). The supplement's fix is grounded in fact, not assumption.
2. **Cross-phase overlap, `auto_trader.py` + `app.py` (cycle-1 Concerns V2/V3):** RESOLVED. A combined cross-phase overlap note was added at the top of Step B (before B1) covering both the `trailing_monitor()` overlap (Phase 1 D1/E1 vs Phase 2 B1/B2/B3/B6) and the `place_order()` nesting (Phase 1 F1 vs Phase 2 B4), instructing execute-agent to re-read POST-Phase-1 code by content, not line number. Fresh grounding in this cycle confirms `trailing_monitor()` spans `auto_trader.py:64-561` — a single ~500-line function — and all cited line ranges for B1 (166-176), B2 (120,179), B3 (63-180+), B6 (300-336), and Phase 1's D1 (~247/262)/E1 (~125-156) genuinely fall inside it; the note is accurate and sufficient.
3. **No test runner (cycle-1 Concern V4):** RESOLVED with one new bounded finding. B0 was added to Step B with the correct scope (8 pure-unit-testable items: B2/B3/B5/B6/D1/D4/D5/D6), a dev-only dependency split (`requirements-dev.txt`, confirmed NOT added to production `requirements.txt` — verified by reading `requirements.txt` directly, no `pytest`/`pytest-asyncio` present), and a `--collect-only` exit gate. **New finding this cycle:** `trading-app/` root contains 20 pre-existing ad-hoc `test_*.py` scripts (more than the "e.g." pair named in the Test Infra note), and direct read of `test_login.py` confirms a genuine top-level `await` SyntaxError. If B0's `pytest.ini` does not explicitly scope `testpaths` to `trading-app/tests/`, a bare `pytest` invocation (not the exact `pytest trading-app/tests/` command the plan's exit gate specifies) would fail at collection on these legacy files for reasons unrelated to this phase's changes. This is now addressed by adding an explicit `testpaths` requirement to B0's checklist text and a matching test in the plan's Verification Evidence table (B0 row) plus Execute-Agent Instruction E9 below — this does not require another supplement cycle since it is a one-line, non-design-changing implementation detail.

### I. Findings by Dimension

**Layer 1 — Infra/setup fit: PASS**
No new dependencies, containers, or runtime surfaces required. All fixes use symbols already available (`itsdangerous` is Phase 1's concern, not Phase 2's; `textContent`/`createElement` are native JS; `cancel_order`/`decrypt_val`/`USER_CONTEXTS` all already exist). `pytest`/`pytest-asyncio` are dev-only (`requirements-dev.txt`), confirmed absent from production `requirements.txt` by direct read. Deployment model is a single GCP VM + systemd (per `all-tests.md`) — no container/proxy/gateway surface is touched by this phase. Unchanged from cycle 1.

**Layer 1 — Test coverage: PASS (with one execute-agent instruction added)**
Cycle-1's CONCERN is resolved: B0 now stands up a scoped, dev-only `pytest`+`pytest-asyncio` harness for all 8 pure-unit-testable items, converting them from "cannot execute" to "gap-resolution B — fixed in this plan." One new bounded implementation-detail finding (pytest collection-scope collision with 20 legacy ad-hoc scripts, one confirmed genuine SyntaxError) is resolved via Execute-Agent Instruction E9 and an explicit `testpaths` requirement added to B0 — does not block PASS, does not require a further plan-supplement cycle.

**Layer 1 — Breaking changes: PASS**
Cycle-1's flagged risk (B4 fail-closed making manual orders permanently blocked, undocumented) is resolved: the Public Contracts section now correctly describes the smaller, better-understood behavior change (silent no-op → explicit structured rejection) that fresh grounding confirms is the likely actual delta, contingent on the RESEARCH sub-step/escalation outcome recorded in the phase report. The A1 401-on-guest-fallback breaking change remains correctly documented (unchanged from cycle 1).

**Layer 1 — Security surface: PASS (with one accepted residual, unchanged from cycle 1)**
A1/A2/A3 close real auth gaps (guest-fallback bypass, OAuth state-fixation/CSRF-adjacent, deactivated-user session persistence). C1/C2 close real reflected-XSS vectors with a sound fix approach (`textContent`/`createElement`, protocol allowlist for `window.open`). D6's exact-token allow-list meaningfully narrows but does not fully eliminate LLM prompt-injection risk on `execute_fix` — accepted as a documented residual (see Known Gaps), consistent with cycle 1.

**Layer 2 — Section A (Auth edge cases): PASS (unchanged from cycle 1; not subject to this supplement)**
Not touched by the plan-supplement. File existence for `trading-app/app.py` spot-checked in this cycle and confirmed present; line-level content re-check deferred to cycle 1's grounding (already direct-read, not re-duplicated here since nothing in this section changed).

**Layer 2 — Section B (Trading-engine correctness): PASS**
All three cycle-1 concerns in this section (V1, V2, V3) independently re-confirmed resolved — see Section 0 above. Mechanical feasibility for B1, B2, B3, B5, B6 unchanged from cycle 1 (all target lines exist, content matches). B0 (new) mechanically sound: `trading-app/tests/` does not yet exist (correct pre-EXECUTE state), `requirements-dev.txt` does not yet exist, no collision with anything currently on disk. Highest-risk edit: B4 — correctly gated behind the RESEARCH sub-step (do not implement until resolved, per E2); second-highest: B0's harness must land with `testpaths` scoping (E9) before B2/B3/B5/B6/D1/D4/D5/D6 attempt their Fully-Automated gates, to avoid an unrelated SyntaxError support cost during EXECUTE.

**Layer 2 — Section C (XSS): PASS (unchanged from cycle 1; not subject to this supplement)**
File existence for `landing.html`/`admin.html` spot-checked in this cycle and confirmed present. Fix approach and test-tier recommendation (E7 — `vc-agent-browser` scripted check, optional) unchanged.

**Layer 2 — Section D (Secrets/TLS/data-integrity): PASS (unchanged from cycle 1; not subject to this supplement)**
File existence for `models.py`, `fetch_lot_sizes.py`, `service-worker.js`, `automation.py` spot-checked in this cycle and confirmed present. D5's 7-table enumeration finding stands unchanged.

### II. Concerns Requiring Resolution

**All 3 cycle-1 substantive CONCERNs (V1, V2, V3, V4) are resolved** — see Section 0 (Supplement Verification) above for the direct re-grounding evidence for each. No open substantive CONCERN remains.

**New Concern V6 (LOW — informational, resolved via Execute-Agent Instruction, no plan-supplement needed):** `trading-app/` root contains 20 pre-existing ad-hoc `test_*.py` scripts (not just the 2 named as "e.g." in the original Test Infra note) — several are not valid pytest-collectable modules (`test_login.py` confirmed to have a bare top-level `await`, a genuine `SyntaxError`). B0's checklist text has been updated in this cycle to require explicit `testpaths` scoping in `pytest.ini` and an additional Verification Evidence row (B0) asserting a bare `pytest` invocation from `trading-app/` does not attempt to collect these files. See Execute-Agent Instruction E9.

**Concern V5 (LOW — informational, carried unchanged from cycle 1, no plan change needed):** generic `validate-plan-artifact.mjs` reports 2 FAIL lines against this plan in cycle 2 (missing overview/context section, missing Complexity metadata — down from cycle 1's reported 6, likely due to unrelated validator/content drift, not a regression introduced by the supplement). These are false positives for this artifact type: `validate-phase-stub.mjs` (the correct validator for phase-program stubs per `process/development-protocols/phase-programs.md`) passes with **0 failures, 0 warnings** when run with an absolute path (a relative-path CWD quirk in the script itself caused a false "does not exist" result on first attempt — confirmed spurious by re-running with an absolute path). No plan-text change required.

### III. Test Coverage Plan (C-4 reconciled: 3 proving strategies + Known-Gap as named residual only)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| B0 | pytest harness collects only `trading-app/tests/`, never the 20 legacy ad-hoc scripts | Fully-Automated | `pytest.ini` `testpaths` set to `trading-app/tests`; `pytest trading-app/tests/ --collect-only` and bare `pytest` (from `trading-app/`) both exit 0 | B |
| A1 | Guest-fallback branch returns 401 on trading-critical endpoints | Fully-Automated | `pytest tests/test_auth.py::test_guest_fallback_401` (new — requires B0 harness) | B |
| A2 | OAuth `state` bound to signed nonce; replay/expiry/tamper rejected | Hybrid — precondition: mocked Fyers OAuth flow | Integration test against `/fyers/callback` with fixture nonces | A |
| A3 | Deactivated/deleted user excluded from next background-loop tick | Hybrid — precondition: running `trailing_monitor`/`automation_loop` in test harness | Integration test asserting `USER_CONTEXTS` entry removed and no order placed post-deactivation | A |
| B1 | Closed-position cleanup fires when broker feed omits (not just zeroes) a position | Hybrid — precondition: mocked positions feed | Simulated feed-omission test | A |
| B2 | Missing/malformed `pl` triggers alert, excluded from aggregate (not silently zeroed) | Fully-Automated | `pytest tests/test_auto_trader.py::test_pl_missing_alerts` (new — requires B0 harness) | B |
| B3 | One user's malformed state doesn't abort other users' tick | Fully-Automated | `pytest tests/test_auto_trader.py::test_per_user_isolation` (new — requires B0 harness) | B |
| B4 | Regime/duplicate guard fails closed with explicit rejection when trend data unavailable | Fully-Automated, gated | `pytest tests/test_app.py::test_regime_guard_fail_closed` (new — write only after RESEARCH sub-step/escalation resolves, per E2) | B |
| B5 | No fabricated-price live order placed when quote/candle both unavailable | Fully-Automated | `pytest tests/test_auto_trader.py::test_no_fabricated_price_order` (new — requires B0 harness) | B |
| B6 | `sl_points` never overwritten with an absolute price; new field holds trailed price | Fully-Automated | `pytest tests/test_auto_trader.py::test_atr_sl_field_separation` (new — requires B0 harness) | B |
| C1 | Malicious RSS `title`/`link` neutralized in `renderNews()` | Agent-Probe (manual, or scripted via `vc-agent-browser` — E7) | Load landing.html with mocked payload; assert no script execution, no `javascript:` navigation | A |
| C2 | Malicious log `message` neutralized in admin.html terminals | Agent-Probe (manual, or scripted via `vc-agent-browser` — E7) | Seed log entry with payload; assert rendered as literal text | A |
| D1 | `decrypt_val` fails loudly (logs/raises) instead of returning ciphertext-as-plaintext | Fully-Automated | `pytest tests/test_models.py::test_decrypt_val_failure_signal` (new — requires B0 harness) | B |
| D2 | Lot-size + RSS/NSE fetches succeed without `verify=False`/`CERT_NONE` | Hybrid — precondition: target deployment env with fixed CA bundle | `python -c "import requests; requests.get(...)"` against real deployment target | A |
| D3 | `/api/funds` (and other sensitive prefixes) never cached by service worker | Agent-Probe (manual, or scripted via `vc-agent-browser` — E8) | Trigger fetch through SW; assert `caches.match('/api/funds')` is empty | A |
| D4 | `nightly_learning_date` round-trips through `state.save()`/`state.load()` | Fully-Automated | `pytest tests/test_automation.py::test_nightly_learning_date_persists` (new — requires B0 harness) | B |
| D5 | No orphaned dependent-table rows after user deletion (7 tables confirmed beyond users/user_states) | Fully-Automated | `pytest tests/test_models.py::test_user_delete_cascade` (new — requires B0 harness) | B |
| D6 | Exact-token allow-list rejects substring-only LLM matches; `execute_fix` scopes to originating user | Fully-Automated | `pytest tests/test_health_agent.py::test_exact_token_allowlist` (new — requires B0 harness) | B |

gap-resolution legend: A — proven now (gate passes in this cycle, no plan change needed) · B — fixed in this plan (gate added once B0's harness sub-step lands) · C — deferred to a named later phase/plan · D — backlog test-building stub (named residual; keep-active; continue)

**Failing stubs (Fully-Automated rows, tier B — to be created once B0's harness lands):**

```
test("should collect only trading-app/tests/ content, never the 20 legacy ad-hoc test_*.py scripts", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: B0 pytest testpaths scoping")
})
test("should alert and exclude position from aggregate when pl field is missing or non-numeric", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: B2 pl-missing alert")
})
test("should continue processing other users when one user's state is malformed mid-tick", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: B3 per-user isolation")
})
test("should never place a live order using the fabricated Try-4 estimated premium", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: B5 no fabricated-price order")
})
test("should store the ATR-trailed absolute stop in a new field, never overwrite sl_points", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: B6 sl_points field separation")
})
test("should log/raise on decrypt_val failure instead of returning ciphertext as plaintext", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: D1 decrypt_val loud failure")
})
test("should round-trip nightly_learning_date through state.save/state.load", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: D4 nightly_learning_date persistence")
})
test("should cascade-delete all 7+ dependent-table rows when a user is deleted", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: D5 orphaned-row cascade delete")
})
test("should reject substring-only LLM action matches and scope execute_fix to the originating user", () => {
  throw new Error("NOT IMPLEMENTED — TDD stub for: D6 exact-token allowlist + user scoping")
})
```

**Legacy line form (retained so existing validate-contract consumers still parse):**
- Step A: [fully-automated: pending B0 harness — A1 guest-fallback 401] | [hybrid: mocked-OAuth — A2 state-nonce replay/tamper] | [hybrid: test-harness background loop — A3 deactivation exclusion]
- Step B: [fully-automated: pending B0 harness with testpaths scoping — B0/B2/B3/B5/B6] | [hybrid: mocked feed — B1 closed-position omission] | [fully-automated, gated by RESEARCH sub-step — B4]
- Step C: [agent-probe: manual or vc-agent-browser scripted — C1/C2 XSS neutralization]
- Step D: [fully-automated: pending B0 harness — D1/D4/D5/D6] | [hybrid: target deploy env — D2 TLS] | [agent-probe: manual or vc-agent-browser scripted — D3 cache exclusion]

**What this coverage does NOT prove:**
- None of the Hybrid rows prove behavior under real Fyers production load/rate-limits — they prove correctness against mocked/paper-trading fixtures only.
- The Fully-Automated (pending-harness) rows prove pure-logic correctness in isolation; they do NOT prove the fixes behave correctly when wired into the live `trailing_monitor`/`automation_loop` runtime under real broker timing.
- C1/C2/D3 Agent-Probe rows (whether manual or `vc-agent-browser`-scripted) prove the specific payloads tested are neutralized; they do not prove exhaustive XSS-vector coverage (e.g. every possible HTML-injection vector) or a full CSP-equivalent hardening.
- B4's test cannot be written until the RESEARCH sub-step/escalation resolves which target signal (`state.market_regime` or otherwise) the fix should route through — the row above is gated, not yet proven.
- The B0 `testpaths` test proves collection-time isolation only; it does not prove every one of the 20 legacy scripts is harmless to leave in place (several may still error if executed directly outside pytest — out of scope for this phase).
- No row here proves absence of regressions in Phase 1's landed auth/session/rate-limit surface — that is EVL's job at Phase 2's own EXECUTE→EVL boundary, cross-checked against Phase 1's report.

### IV. Plan Updates Applied (from cycle-1 supplement, verified in this cycle)

| # | What changed | Where in plan | Verified how |
|---|---|---|---|
| P1 | Added B0 checklist sub-step (harness stand-up, 8-item scope, dev-only deps) | Step B, before B1 | Read live plan text; cross-checked `requirements.txt` has no pytest/pytest-asyncio (confirmed dev-only split respected) |
| P2 | Added RESEARCH sub-step to B4 (grep + code-read + escalation branch) | Step B, B4 item text | Read live plan text; independently re-ran the grep and code-read myself and got matching results |
| P3 | Updated B4's current/target/test text to reflect the `if trend_cache:` nesting finding | Step B, B4 item text + Verification Evidence | Read live plan text; independently re-read `app.py:2039-2103` and confirmed the nesting claim is accurate |
| P4 | Added cross-phase overlap note to Step B intro + inline B4 note | Step B intro, B4 item text | Read live plan text; independently confirmed `trailing_monitor()` spans `auto_trader.py:64-561` and all cited sub-ranges fall inside it |

### New Plan Update Applied This Cycle

| # | What changes | Where in plan | Why |
|---|---|---|---|
| P5 | Added explicit `testpaths` scoping requirement to B0, a new B0 Verification Evidence row, and a new B0 Test Coverage Plan row/stub | Step B (B0 item text), Verification Evidence table, Section III | Fresh grounding found 20 (not 2) legacy ad-hoc `test_*.py` scripts in `trading-app/` root, one (`test_login.py`) confirmed to have a genuine top-level-`await` SyntaxError — an unscoped `pytest.ini` would let a bare `pytest` invocation collide with these during EXECUTE for reasons unrelated to this phase |

### V. Execute-Agent Instructions (bind regardless of plan-text update timing)

| # | Instruction | Trigger condition |
|---|---|---|
| E1 | Before implementing A1, confirm Phase 1's landed `get_current_client` rejects on invalid/expired signature (not just absent cookie) — A1 only needs to add the absent-cookie/401 path; do not duplicate or short-circuit Phase 1's signature-validation branch. | A1 item |
| E2 | Do not implement B4 until the RESEARCH sub-step (grep + code-read + any required escalation) is complete and documented in the phase report. Cycle-2 VALIDATE independently re-confirmed the expected outcome (`ai_trend_cache` dead, `state.market_regime` is the live signal) but the escalation sign-off itself must still happen at EXECUTE time — do not skip it just because VALIDATE already found the same facts. | B4 item |
| E3 | Before starting any of B0/B1/B2/B3/B6, re-read the full current `trailing_monitor()` body in `auto_trader.py` fresh (post-Phase-1-landing) rather than relying on this plan's line numbers. Apply B3's try/except wrap with explicit awareness that it re-indents the entire per-user body — verify B1/B2/B6's target content (not line numbers) after B3 lands, using content-anchored search, not cached whitespace/line offsets. | Step B, before B1 |
| E4 | Before implementing B4, re-read Phase 1's landed `place_order()` structure (post order_lock widening from F1) — implement B4's fail-closed logic inside whatever lock boundary F1 produced, not against this plan's pre-Phase-1 code snapshot. | B4 item |
| E5 | For D5, run the schema grep (`grep -n "user_id\|uid" trading-app/models.py` schema definitions) to confirm the full table list before writing the cascade-delete transaction — this validate pass found 7 candidate tables (`daily_pnl_history`, `paper_pnl_history`, `system_logs`, `health_memory`, `swarm_trade_records`, `swarm_agent_configs`, `swarm_learning_logs`) beyond `users`/`user_states`; confirm each actually has a user-scoped column before including it. | D5 item |
| E6 | Stand up the minimal pytest harness (B0) BEFORE attempting B2/B3/B5/B6/D1/D4/D5/D6's Fully-Automated gates — do not silently downgrade to Hybrid/Agent-Probe without first attempting the harness, since it is confirmed in-scope and low-cost. | Step B/D, before first Fully-Automated-tagged item |
| E7 | For C1/C2, consider using the repo's existing `vc-agent-browser` (Puppeteer) skill to load the static HTML with a mocked payload and assert DOM state / absence of script execution programmatically, rather than a purely manual visual check — recommended, not required; document which approach was used in the phase report. | C1/C2 items |
| E8 | For D3, consider using `vc-agent-browser` to execute `caches.keys()`/`caches.match('/api/funds')` in a headless context and assert no entry exists, rather than a purely manual devtools check — recommended, not required. | D3 item |
| E9 (NEW, cycle 2) | When creating B0's `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`), explicitly set `testpaths = ["tests"]` (relative to `trading-app/`) or an equivalent scoping mechanism (`norecursedirs`, `--rootdir` + `-p no:cacheprovider` invocation convention documented in the phase report). Confirm with a bare `pytest` run from `trading-app/` (no path argument) that it does NOT attempt to collect any of the 20 legacy `test_*.py` scripts in `trading-app/` root — several are not valid pytest modules (`test_login.py` has a confirmed top-level `await` SyntaxError) and would otherwise cause spurious collection failures unrelated to this phase's own changes. | B0 item, before first Fully-Automated-tagged item |

### VI. High-Risk Pack

Per `process/development-protocols/implementation-standards.md` §Risky Work Evidence Contract and `orchestration.md` §High-Risk Execution Handoff: this phase touches **auth/identity** (A1, A2, A3), **billing/live-money-adjacent order logic** (B0-B6, all trading-engine correctness on a live real-money platform), and **secrets/trust-boundary logic** (D1, D2, D6). A manual-first evidence pack (`risk-gate.json`, `context-snippets.json`, `verification.json`, `review-decision.json`, `adversarial-validation.json`) is REQUIRED before this phase is treated as ready for finalize, per the umbrella's own High-Risk Class declaration for the whole program. Recommended location: `process/features/security-remediation/active/trading-remediation_03-07-26/harness/` (colocated in the task folder). This pack has NOT been created yet — creating it is an EXECUTE-phase (or pre-finalize) action item, not a VALIDATE deliverable; flagging its requirement here per protocol. Unchanged from cycle 1.

### VII. Backlog Artifacts

No new backlog artifacts required from this validate pass — all findings are resolvable within this phase's own scope (plan supplement, already applied and verified + execute-agent instructions). If the RESEARCH sub-step for B4 resolves to "ai_trend_cache is dead code and product decides NOT to wire it up in this phase," a backlog note (`ai-trend-cache-wiring_NOTE_[date].md`) documenting the deferred wiring work should be created at that time — not now, since the decision hasn't been made yet. Unchanged from cycle 1.

### VIII. Known Gaps

- **D6 residual LLM prompt-injection risk:** the exact-token allow-list narrows but does not fully eliminate the risk of a crafted `error_msg` manipulating the LLM into emitting an allow-listed token. Accepted as consistent with the audit's original scope (which asked for allow-listing, not full LLM-output sandboxing). No further action required this phase.
- **Hybrid/Agent-Probe items requiring live broker or browser environments** (A2, A3, B1, D2, C1, C2, D3): these cannot be reduced to Fully-Automated within this phase's scope regardless of harness stand-up, since they require a running background loop, a live/mocked OAuth provider, a real deployment CA bundle, or a DOM/browser environment. This is an accepted, correctly-triaged split already present in the plan — not a new gap introduced by this validate pass.
- **20 legacy ad-hoc `test_*.py` scripts in `trading-app/` root remain unconverted:** out of scope for this phase (they predate this plan and are not part of its Blast Radius); B0's `testpaths` scoping (E9) prevents them from interfering with this phase's new harness, but does not fix or remove them. No action required this phase.

### IX. Dimension Findings (summary table)

- Infra fit: PASS — no new dependencies/runtime surfaces; dev-only pytest deps confirmed absent from production requirements.txt
- Test coverage: PASS — B0 harness resolves cycle-1's CONCERN; new pytest-collision finding resolved via E9, no plan-supplement needed
- Breaking changes: PASS — B4 rescope now correctly documents the smaller, better-understood behavior change
- Security surface: PASS (one accepted residual) — D6 LLM prompt-injection narrowed, not eliminated (unchanged from cycle 1)
- Section A feasibility: PASS — unchanged from cycle 1, not subject to this supplement
- Section B feasibility: PASS — all 3 cycle-1 concerns (V1/V2/V3) independently re-confirmed resolved; B0 mechanically sound
- Section C feasibility: PASS — unchanged from cycle 1, not subject to this supplement
- Section D feasibility: PASS — unchanged from cycle 1, not subject to this supplement

Open gaps: none blocking. Informational only — Concern V5 (validator false-positive, informational), Concern V6/new (pytest collection-scope, resolved via E9), Known Gaps (D6 residual, live-env Hybrid/Agent-Probe items, legacy ad-hoc scripts) — none require a further plan-supplement cycle.

Gate: PASS (0 FAILs; 0 unresolved substantive CONCERNs — all 3 cycle-1 concerns independently re-verified resolved against live code; 1 new bounded finding resolved via Execute-Agent Instruction E9 without a plan-supplement cycle; 2 informational/no-action findings carried or newly noted). Cleared for EXECUTE.
Accepted by: session (cycle-2 outer-PVL re-validate) — Gate is PASS, not CONDITIONAL, so no user acceptance of open concerns is required; all findings are either resolved-and-verified or informational/execute-agent-instruction-bound.
