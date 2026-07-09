---
name: plan:trading-remediation-phase-01-critical-security
description: "Trading Platform Security Remediation — Phase 1: critical live-money auth, order-safety, and secret-rotation fixes"
date: 03-07-26
metadata:
  node_type: memory
  type: plan
  feature: security-remediation
  phase: phase-01
---

# Phase 01 — Critical Security & Live-Money Safety Fixes

**Program:** trading-remediation
**Umbrella plan:** process/features/security-remediation/active/trading-remediation_03-07-26/trading-remediation-umbrella_PLAN_03-07-26.md
**Phase status:** ✅ EXECUTED (all code changes applied; fully-automated gates green; live/deploy-day manual gates pending — see report)
**Report destination:** process/features/security-remediation/active/trading-remediation_03-07-26/phase-01-critical-security_REPORT_03-07-26.md (flat in the program task folder)

---

## Purpose

This is the highest-risk phase in the program: it touches session authentication, the Telegram
webhook, admin-account creation, order placement, the emergency stop-loss square-off race, and
encryption-key rotation on a **live real-money trading platform**. The platform currently has
live authenticated traders and live automated positions running against a real broker (Fyers).
Every checklist item below is written so it can be deployed without an unplanned mass-logout, an
unplanned automation outage during market hours, or a broken live position exit path.

Phase 1 owns: session-cookie/auth-token mechanism, Telegram webhook auth, admin
credentials/rate-limiting, and the order-lock/TOCTOU race in `/api/order`. Phase 2 (guest-fallback
/401 behavior, OAuth state-binding) touches different functions in the same `app.py` file and does
not overlap with these items — confirmed via SendMessage with phase2-writer.

---

## Audit-Line-Number Drift Found During Grounding Read

The original audit line numbers had drifted. Verified against current repo state on 03-07-26:

| Audit said | Actual | Note |
|---|---|---|
| Login/cookie-setting ~line 195 | `app.py:194` (`response.set_cookie(key="user_id", ...)`) | Matches closely — no material drift |
| `get_current_client` ~798-812 | `app.py:797-811` | Matches closely |
| Order placement + order_lock ~2040-2102 | `app.py:2039-2100`, function `place_order` | **Bug is worse than described**: `async with state.order_lock:` wraps ONLY the `trades_today >= max_trades_per_day` check (2 lines); the `place_order` call and `state.record_trade()` happen OUTSIDE the lock. This is a full TOCTOU race, not a partial one — see Checklist Item 6. |
| Telegram webhook ~2721-2920 | `app.py:2721-2917` | Matches closely |
| `trailing_monitor` ~125-176 | `workers/auto_trader.py:64-176` | Function starts earlier than stated (line 64), but the described behavior (max-loss square-off before disabling automation) is confirmed at lines 125-156 |
| `exit_position` calls ~248, 263 | `workers/auto_trader.py:248`, `:263` | Confirmed — `client.exit_position` does not exist anywhere in `fyers_client.py`. Both calls pass a dict `{"id": sl_order_id}` as if calling a cancel method. |
| `automation_loop` ~1197-1226 | `workers/auto_trader.py:1025` (function start) | Line drift is larger here; automation_loop is used only for the acceptance/rollback description below, not directly patched in this phase |
| Default admin creation ~220-240 | `models.py:229-236` | Matches closely |
| Encryption helpers ~22-91 | `models.py:22-92` | Matches closely |

No item in the checklist below changed as a result of this drift — line numbers in the checklist are the **verified current** ones.

---

## VALIDATE Grounding Notes (added at V1–V2, 03-07-26)

Every file in the Blast Radius was read directly during VALIDATE (not just grep'd) to confirm the
plan's technical claims before writing the contract. Key confirmations and one **critical
correction**:

- `FyersClient.cancel_order(self, order_id: str) -> Dict` confirmed at `fyers_client.py:1650` —
  takes a **plain string**, not a dict. The plan's Item 4 replacement call
  (`client.cancel_order, sl_order_id`) is exactly correct as written. No change needed to Item 4.
- `app.py:2054` (`place_order`) confirmed: `async with state.order_lock:` wraps only the 2-line
  `trades_today` check; `client.place_order` and `state.record_trade()` are ~40+ lines outside the
  lock. Item 6's widen-the-lock fix is correctly scoped.
- `workers/auto_trader.py:125-156` confirmed: the square-off `for pos in open_positions:` loop
  runs fully BEFORE `state.automation_enabled = False` is set, and `automation_loop`
  (`auto_trader.py:1208`) reads `state.automation_enabled` on every tick — the race window Item 5
  describes is real and the reorder fix closes it.
- `.env`, `trading.db`, `trading_app.db`, `trading_bot.db` are confirmed currently tracked by git
  (`git ls-files` from `trading-app/` returns all four) — Item 7/G3's premise is correct.
  `requirements.txt` does NOT list `itsdangerous` — Item 1's dependency-add is necessary, not
  optional.
- `models.py:24-57` (`get_cipher()`) has a behavior not mentioned in the plan: **if
  `ENCRYPTION_KEY` is unset at process start, it silently generates a brand-new key and persists it
  to `.env`, overwriting the file.** This is a real risk during Item 7/G1's key-rotation cutover —
  see the new execute-agent instruction in the Validate Contract below.
- **CRITICAL — Item 1 (A1) blast radius was incomplete as originally scoped.** See the correction
  inserted directly into Item A1 below. Summary: `app.py` has ~19 route handlers beyond
  `login_api`/`get_current_client` that read `request.cookies.get("user_id")` directly as a raw
  int, completely bypassing the new signed-cookie verification. Left unfixed, every route that does
  this (including the `/` root route every logged-in user lands on) would break for any user who
  authenticates after this deploy. This is a plan update (P1 below), not a design change — the
  chosen approach (signed cookie + grace period) is unaffected; only its blast radius grows.

---

## Entry Gate

- Program umbrella plan created (or being created in parallel by umbrella-writer)
- Access to `trading-app/` source and a paper-trading/test Fyers account for verification
- Confirmed via SendMessage with phase2-writer: no app.py function overlap between Phase 1 and Phase 2 scope

---

## Blast Radius

- `trading-app/app.py` (login/cookie, session dependency, telegram webhook, order placement,
  .env-adjacent config, **plus the ~19 additional route handlers that must migrate from reading
  `request.cookies.get("user_id")` directly to the new shared cookie-resolver helper — found during
  VALIDATE V2, see Item A1 correction below. Exact line numbers: 224 (`/` root route), 258
  (`/api/state`), 289 (`/admin`), 299 (`/api/admin/analytics`), 380, 417, 434, 453, 467, 481, 495
  (`/api/admin/*` family), 509 (`/api/fyers/login_url`), 542 (OAuth/auth-code callback), 574, 597
  (`/api/user/settings`), 622 (`/api/submit-auth-code`), 1008 (refresh-login), 1077
  (`/api/restart`), 2711 (`/api/logs`)**)
- `trading-app/models.py` (default-admin creation, encryption key helpers, add login-attempt tracking table)
- `trading-app/workers/auto_trader.py` (`trailing_monitor` max-loss square-off ordering, `exit_position` → `cancel_order` calls)
- `trading-app/fyers_client.py` (read-only reference for correct public method; no functional change expected, verify during Item 4)
- `trading-app/requirements.txt` (add `itsdangerous` only if not already available transitively — see Item 1)
- `trading-app/.gitignore`, `.env`, `trading_app.db`, `trading.db`, `trading_bot.db` (git tracking fix)
- One new one-time migration script: `trading-app/scripts/migrate_reencrypt_credentials.py` (new file)
- One new setup-time script/flow: initial admin creation (extends `models.py` init path)

---

## Public Contracts

- `/api/login` response shape (`{"success": bool, "message": str}`) is unchanged; only the cookie's internal format changes (signed vs raw).
- `/api/order` response shape and business rules (BUY-only, daily trade limit, regime lockout) are unchanged; only the concurrency correctness of the daily-limit check changes.
- `/api/telegram/webhook` external contract (Telegram's POST body format) is unchanged; only server-side verification is added, which requires a one-time Telegram-side `setWebhook` call with `secret_token`.
- No REST endpoint signatures, routes, or JSON field names change in this phase. **This includes
  the ~19 routes corrected in Item A1 below — the shared cookie-resolver changes only HOW a user id
  is resolved from the cookie, never each route's existing failure-mode contract (guest-fallback /
  401 / 403 per route, unchanged).**
- New login-attempt lockout will introduce a new failure message in `/api/login` (e.g. `423 Locked` / `{"success": false, "message": "Too many attempts..."}`) — this is an additive behavior change, not a breaking one, since callers already handle `{"success": false}`.

---

## Implementation Checklist

Ordered so that nothing breaks live traffic mid-deploy. Each item includes: current behavior →
target behavior → rollback note. Deploy order matters — items 4–6 (order safety / exit fix) should
land in the SAME deploy as item 1 only if item 1's grace-period design (below) is used; otherwise
they may ship independently.

### Step A — Session Auth Fix (Item 1)

- [x] **A1. `app.py:194-196` (`login_api`) — replace raw `user_id` cookie with a signed cookie.**
  - **Current:** `response.set_cookie(key="user_id", value=str(user["id"]), ...)` sets the raw
    integer user id as a cookie value with no signature — any client can forge `user_id=<any int>`
    and impersonate any account (including the admin, id=1).
  - **Target:** Sign the cookie value using `itsdangerous.URLSafeTimedSerializer` (check
    `trading-app/requirements.txt` first — `itsdangerous` is a transitive dependency of `fastapi`
    via `starlette`'s `SessionMiddleware` but is **not currently in `requirements.txt`** as a
    direct import; add `itsdangerous>=2.1.0` to `requirements.txt` explicitly since the code will
    import it directly rather than relying on the transitive pin). Introduce a `SECRET_KEY` env
    var (generate once, store in `.env`, same rotation discipline as `ENCRYPTION_KEY`). On login,
    set the cookie value to `serializer.dumps(user["id"])` instead of the raw id. Add a new
    `get_current_client`-side verification: `serializer.loads(raw_cookie, max_age=86400*30)`,
    catching `itsdangerous.BadSignature`/`SignatureExpired` and treating those as unauthenticated
    (fall through to guest/401 path — this is Phase 2's territory for the guest-fallback shape, so
    Phase 1 only needs to raise/return whatever `get_current_client` already does today on invalid
    input; confirmed with phase2-writer that Phase 1 should NOT redesign the 401/guest branching,
    only make the cookie itself unforgeable).
  - **Migration path (grace period, chosen over forced re-login):** On the day this ships, currently
    logged-in users hold a cookie value like `user_id=17` (raw). The new `get_current_client` must
    accept EITHER a valid signed token OR (if signature verification fails) a raw integer string
    that matches an existing active user id, for a **7-day grace window measured from deploy date**
    (hardcode a `SESSION_MIGRATION_CUTOFF` date constant, or check `if raw_cookie.isdigit(): honor
    as legacy for grace period`). During the grace period, do NOT re-sign the raw cookie on
    subsequent requests — force a real re-login to get the new signed cookie by NOT refreshing
    `max_age`; the old raw cookie will simply expire naturally on its existing 30-day `max_age` or
    the grace window, whichever is sooner.
    - **Tradeoff documented:** This means the raw-cookie forgery vulnerability is NOT closed for
      returning users until they log in again or 7 days pass — but it avoids an unplanned mass
      logout of every active session during market hours, which the user has said is worse than a
      short-lived residual risk. Alternative (force immediate re-login) was rejected because it
      would knock every currently-authenticated live trader off mid-session with no warning.
  - **Blast-radius correction (found during VALIDATE V2 fan-out — the scope above, as originally
    written, is INCOMPLETE and would break the live app if shipped as-is):** `app.py` has ~19 OTHER
    route handlers beyond `login_api`/`get_current_client` that read
    `request.cookies.get("user_id")` directly and pass the raw value straight into
    `Database.get_user_by_id(...)` or `int(...)` — confirmed via
    `grep -n 'cookies.get("user_id")' app.py`, which returns matches at lines: 224 (`/` **root
    route — the primary page every logged-in user lands on**), 258 (`/api/state`), 289 (`/admin`),
    299 (`/api/admin/analytics`), 380, 417, 434, 453, 467, 481, 495 (the `/api/admin/*` family),
    509 (`/api/fyers/login_url`), 542 (OAuth/auth-code callback route), 574, 597
    (`/api/user/settings`), 622 (`/api/submit-auth-code`), 1008 (refresh-login route), 1077
    (`/api/restart`), 2711 (`/api/logs`). **None of these 19 routes go through
    `get_current_client`.** If only `login_api` + `get_current_client` are patched as originally
    scoped, EVERY ONE of these routes breaks for any user who authenticates after this deploy —
    their cookie value is now a signed-token string, not a raw int, and
    `Database.get_user_by_id(<token string>)` / `int(<token string>)` will either return no user or
    raise a `ValueError`. This includes the `/` route, meaning a freshly-logged-in user would see
    the logged-out landing page instead of the app. This is a phase-breaking regression, not a
    minor residual gap, and must be fixed in the SAME deploy as the cookie-signing change.
  - **Required additional work (part of Item 1, same deploy):** extract one shared helper —
    `async def resolve_authenticated_user_id(request: Request) -> Optional[int]:` — implementing
    the exact same signed-token-or-grace-period-raw-digit verification logic being added to
    `get_current_client` above (valid signed token → return the id; else if `SESSION_MIGRATION_CUTOFF`
    grace period is still active and the raw cookie value `isdigit()` → return `int(raw_cookie)`;
    else → return `None`). Replace ALL ~20 raw `request.cookies.get("user_id")` reads (the 19 line
    numbers above, plus `get_current_client` itself) with a call to this helper. **Preserve each
    call site's existing failure-mode contract exactly** (guest-fallback / 401 / 403 per route, as
    today) — this correction only changes HOW the user id is resolved from the cookie, never what a
    route does when resolution returns `None`. The Blast Radius and Public Contracts sections above
    have been updated to include this.
  - **Rollback:** Revert this commit; the old raw-cookie format is a strict subset of what the
    grace-period-compatible `get_current_client`/`resolve_authenticated_user_id` accepts, so
    reverting is safe and no session data is lost either way.

### Step B — Telegram Webhook Auth (Item 2)

- [x] **B1. `app.py:2721-2723` (`telegram_webhook`) — verify `X-Telegram-Bot-Api-Secret-Token`.**
  - **Current:** Any POST to `/api/telegram/webhook` is processed with zero authentication — an
    attacker who discovers the URL can send fake Telegram updates that trigger `/stop`, `/start`,
    or `/authcode` handling as if they came from the real bot/chat.
  - **Target:** Read `request.headers.get("x-telegram-bot-api-secret-token")` at the top of the
    handler; compare (constant-time, `hmac.compare_digest`) against a new `TELEGRAM_WEBHOOK_SECRET`
    env var. On mismatch, return `{"status": "error", "message": "unauthorized"}` with HTTP 403
    immediately, before any `data = await request.json()` parsing. **Confirmed during VALIDATE:**
    `data = await request.json()` is the very first statement in the current handler body, so
    inserting the header check before it is a clean, low-risk single-point edit.
  - **Deployment step (not just code — required, or the fix is inert):** Telegram will not send
    this header unless the webhook was registered with `secret_token` set. After this code deploys,
    a one-time call must be made: `POST https://api.telegram.org/bot<TOKEN>/setWebhook` with
    `url=<existing webhook url>` and `secret_token=<TELEGRAM_WEBHOOK_SECRET>`. Document this as a
    manual post-deploy step in the phase report — it cannot be automated from inside this repo
    since it requires calling Telegram's live API with the bot token.
  - **Rollback:** If the secret_token check breaks real Telegram delivery (e.g. `setWebhook` step
    was missed or the secret doesn't match), the code fails closed (blocks all webhook traffic,
    including legitimate). Rollback = redeploy without this check OR re-run `setWebhook` with the
    correct `secret_token` matching the env var — the latter is the correct fix, not a full
    code revert, so document both options in the phase report.

### Step C — Admin Credentials & Login Rate-Limiting (Item 3)

- [x] **C1. `models.py:229-236` — remove hardcoded `admin`/`admin123` auto-creation.**
  - **Current:** On every fresh DB init, a default admin account with password `admin123` is
    silently created and logged to stdout (`print("🚀 Default admin created (admin / admin123)")`).
    This is a guessable, publicly-known default credential on a live-money system. **Confirmed
    verbatim at `models.py:230-236` during VALIDATE.**
  - **Target:** Replace with an explicit first-run setup: read `INITIAL_ADMIN_PASSWORD` from env at
    startup. If the `users` table is empty AND `INITIAL_ADMIN_PASSWORD` is set, create the admin
    user with that password and log a one-line confirmation without echoing the password value. If
    the table is empty and the env var is NOT set, log a clear warning
    (`"⚠️ No admin user exists and INITIAL_ADMIN_PASSWORD is not set — set it in .env and restart"`)
    and do NOT create any account — do not silently fall back to a guessable default.
  - **Live-system note:** Since this repo's DB (`trading_app.db`) already has a live admin account
    in place, this code path only fires on fresh installs — it will NOT affect the current running
    admin login. Confirm this by checking `SELECT id FROM users WHERE username='admin'` returns a
    row already (it will, since the DB is live) — the `if not c.fetchone():` guard means this
    change is a no-op for the current deployment.
  - **Rollback:** Revert the commit; on a fresh DB this reintroduces the old behavior, but the live
    DB is unaffected either way.

- [x] **C2. `app.py:179-203` (`login_api`) — add login rate-limiting/lockout.**
  - **Current:** No limit on failed login attempts — brute-forceable.
  - **Target:** Add a simple in-memory (or new `login_attempts` DB table, preferred for
    multi-worker safety since this is a single-process Uvicorn deployment per the stack notes —
    **confirmed during VALIDATE: `uvicorn.run(app, host="0.0.0.0", port=port)` at `app.py:2929` has
    no `workers=` argument, so this is single-process; an in-memory dict is safe**) counter keyed by
    `username` (not IP, since IP may be shared/proxied): after 5 failed attempts within 15 minutes,
    return `{"success": false, "message": "Too many failed attempts. Try again in N minutes."}`
    without checking the password at all (to avoid a timing oracle). Reset the counter on
    successful login. Use exponential backoff optionally (5 attempts → 5 min lock, then 15 min,
    then 30 min) — for Phase 1 scope, a flat 15-minute lockout after 5 attempts is sufficient; note
    escalation as a documented simplification, not a gap.
  - **Rollback:** Revert; lockout state is additive and does not touch existing session/user data.

### Step D — Fix Broken Position-Exit Method (Item 4)

- [x] **D1. `workers/auto_trader.py:248` and `:263` — `client.exit_position(...)` does not exist;
      replace with the correct existing method.**
  - **Current:** Both call sites do
    `await asyncio.to_thread(client.exit_position, {"id": sl_order_id})`. `FyersClient` (verified
    via `grep -n "    def " fyers_client.py`) has NO `exit_position` method. This call raises
    `AttributeError` at runtime, which is caught by the surrounding bare `except Exception as e:`
    and only logged (`logger.error(f"Error cancelling Strategy 5 CO: {e}")`) — meaning **Strategy
    5's time-stop and Strategy 6's 1:30pm force-exit have never actually cancelled the standing
    stop-loss/cover order in production**; the code silently no-ops and the position is only
    removed from `state.active_auto_trades` bookkeeping via `state.remove_active_trade(sym)`
    while the real broker-side SL/CO order may remain live.
  - **Target:** The intent at both call sites is to cancel the standing broker-side stop-loss/CO
    order identified by `sl_order_id` (not to place an opposite-side exit order — the variable name
    and surrounding comments confirm this is a "cancel the CO" operation). `FyersClient.cancel_order
    (self, order_id: str)` (**confirmed at `fyers_client.py:1650` during VALIDATE — signature and
    return shape match exactly as described; internally calls `self.client.cancel_order({"id":
    order_id})` and normalizes the response**) is the correct existing method and takes a plain
    string id, not a dict. Replace both calls with:
    `await asyncio.to_thread(client.cancel_order, sl_order_id)`.
  - **Mark-closed ordering fix (also required at both sites):** Currently
    `state.remove_active_trade(sym)` is called unconditionally right after the (currently no-op)
    exit attempt, regardless of success. Change to: only call `state.remove_active_trade(sym)`
    after checking `result = await asyncio.to_thread(client.cancel_order, sl_order_id)` and
    `result.get("success")` is true, OR after independently confirming via
    `client.get_positions()` that the position is actually flat (qty 0) — because a cancel-order
    failure does not necessarily mean the position itself is still open (the position may have
    already been closed by the SL/target hitting). Log a warning and keep the trade in
    `active_auto_trades` for the next `trailing_monitor` tick to re-evaluate if neither condition
    holds, rather than silently dropping bookkeeping while a real position may still be open.
  - **Rollback:** If `cancel_order` calls start erroring in a way the old broken code didn't
    (e.g. rate limits), revert to the previous no-op behavior temporarily — but note this
    re-introduces the original bug; prefer fixing forward. Detect via logs
    (`grep "Error cancelling" logs/*.log`) and via manual position check against the Fyers app.

### Step E — Fix Emergency Stop-Loss Race (Item 5)

- [x] **E1. `workers/auto_trader.py:125-156` (`trailing_monitor`) — set `automation_enabled = False`
      and `hard_exit_triggered = True` BEFORE iterating positions to exit, not after.**
  - **Current:** Order is: (a) log the breach, (b) loop over `open_positions` and place exit orders
    for each (lines ~128-149), (c) only AFTER the loop completes, set
    `state.automation_enabled = False` (line 154) and `state.hard_exit_triggered = True` (line 156).
    Because `automation_loop` (a separate concurrent asyncio task, confirmed reading
    `state.automation_enabled` at `workers/auto_trader.py:1208`) reads `state.automation_enabled` on
    every tick to decide whether to open new positions, there is a live race window during the
    square-off loop where `automation_enabled` is still `True` and a concurrent `automation_loop`
    tick could open a brand-new position while the emergency square-off is still in progress.
  - **Target:** Move `state.automation_enabled = False` and `state.hard_exit_triggered = True` (and
    `state.save()` if needed for the flag alone, deferring the rest of `state.save()` until after
    cleanup as today) to immediately after the breach is detected and logged, BEFORE the
    `for pos in open_positions:` loop begins. This closes the race: any concurrent
    `automation_loop` tick checking `automation_enabled` after this point sees `False` immediately.
  - **Verify no other write to `automation_enabled` conflicts:** confirmed via
    `grep -n "automation_enabled" workers/auto_trader.py app.py` during EXECUTE that no other code
    path re-enables automation between this point and the end of the square-off loop (this is a
    read-only assumption check, not a code change — execute-agent must run this grep before
    finalizing the reorder). **VALIDATE note:** this grep found manual re-enable paths at
    `app.py:2343` (`/api/toggle-automation`-style endpoint) and `app.py:2900` (Telegram `/start`
    command) — these are USER-triggered actions, not background-loop conflicts, so they are outside
    this fix's scope, but a residual edge case exists: if a user manually re-enables automation via
    Telegram or the API WHILE the square-off loop is still running (mid-way through closing
    multiple positions), `automation_loop`'s next tick could still open a new position concurrently
    with the ongoing square-off. This is documented as an accepted residual risk in the Validate
    Contract below (Known Gaps), not fixed in this phase — it requires a broader "is a square-off in
    progress" guard that Phase 1 does not currently scope.
  - **Rollback:** Revert the statement-order change only; this is a pure reordering with no new
    state or schema, trivially revertable.

### Step F — Fix Daily-Trade-Limit TOCTOU Race (Item 6)

- [x] **F1. `app.py:2039-2100` (`place_order`) — the `order_lock` currently wraps only the check,
      not the check+place+increment as one atomic unit; widen the lock scope.**
  - **Current (confirmed via direct read, worse than the original audit described):**
    ```
    async with state.order_lock:
        if state.trades_today >= state.max_trades_per_day:
            return {...}
    # <-- lock released here
    ... regime lockout checks ...
    result = await asyncio.to_thread(client.place_order, ...)
    if result.get("success"):
        state.record_trade()
    return result
    ```
    The lock is released immediately after the limit check. Two concurrent requests can both pass
    the check before either calls `record_trade()`, allowing more trades than
    `max_trades_per_day` to be placed. This also means the lock currently does not protect
    `place_order`+`record_trade` from any concurrent caller at all. **Confirmed during VALIDATE:
    `state.record_trade()` sits roughly 40+ lines after `async with state.order_lock:` in the
    current file — see the Execute-Agent Instructions in the Validate Contract for a note about the
    Exit Gate check #4 line-window below.**
  - **Target:** Widen the `async with state.order_lock:` block to wrap the ENTIRE critical section:
    the `trades_today >= max_trades_per_day` check, the regime-lockout checks that read/depend on
    `state`, the `client.place_order` call, and `state.record_trade()`. Regime-lockout checks that
    only read external caches (`ai_trend_cache`, `client.get_positions()`) can safely stay inside
    the widened lock since they don't hold competing locks themselves — verify no nested-lock
    deadlock risk during EXECUTE by grepping for any other `async with state.order_lock` usage
    inside `client.place_order` itself (there should be none — `FyersClient.place_order` does not
    touch `state.order_lock`).
  - **Behavior-preserving note:** Widening the lock will serialize all order placement per-user
    (already effectively true today since `order_lock` is per-`UserState` — **confirmed at
    `engine/automation.py:43`: `self.order_lock = asyncio.Lock()` is instantiated inside the
    per-user `TradingState.__init__`**), so this does not change single-user behavior — it only
    closes the multi-concurrent-request race. Cross-user order placement is unaffected since each
    user has their own `UserState`/`order_lock`.
  - **Rollback:** Revert to the narrow lock; this reintroduces the race but does not break existing
    functionality — safe fallback if the widened lock is found to cause an unexpected timeout under
    load (unlikely given single-user serialization is already the norm).

### Step G — Secret Rotation & Git History Hygiene (Item 7)

- [x] **G1. Generate a new `ENCRYPTION_KEY` and write a one-time migration script.**
  - **Current:** `ENCRYPTION_KEY` (used by `models.py:22-92` `get_cipher()`/`encrypt_val`/
    `decrypt_val`) is stored in a tracked `.env` file (`git ls-files` confirms
    `trading-app/.env` is currently tracked) — the key has been exposed in git history.
  - **Target:** Create `trading-app/scripts/migrate_reencrypt_credentials.py` (new file) that:
    1. Reads the OLD key from `ENCRYPTION_KEY_OLD` env var (temporarily set alongside the new key).
    2. Selects every row from `users` with any of `fyers_client_id`, `fyers_secret`,
       `fyers_access_token`, `fyers_refresh_token`, `fyers_pin` populated.
    3. Decrypts each with the OLD key (`Fernet(ENCRYPTION_KEY_OLD.encode()).decrypt(...)`) — falls
       back to treating the value as plaintext if decryption fails, mirroring the existing
       `decrypt_val` backwards-compatibility behavior at `models.py:69-77`.
    4. Re-encrypts with the NEW key (the one already active via `get_cipher()`).
    5. Writes back to the DB in a single transaction, with a pre-migration DB backup copy
       (`cp trading_app.db trading_app.db.pre-migration-backup`) taken automatically by the script
       before writing.
  - **VALIDATE finding — `get_cipher()` auto-regeneration risk (see Execute-Agent Instructions in
    the Validate Contract below):** `models.py:24-57` (`get_cipher()`) will SILENTLY generate a
    brand-new random key and persist it to `.env` if `ENCRYPTION_KEY` is not found in the
    environment at the moment it's first called. If the manual `.env` edit in the deployment steps
    below is mistyped, missed, or the app starts before the edit lands, this auto-regeneration will
    silently overwrite the just-migrated key, orphaning all re-encrypted credentials. This must be
    guarded explicitly — see the Validate Contract's execute-agent instruction.
  - **Deployment order (must run in this exact sequence to avoid locking out live Fyers sessions):**
    1. Generate new key, set `ENCRYPTION_KEY_OLD=<current key value>` and
       `ENCRYPTION_KEY=<newly generated key>` in `.env`.
    2. Stop the app (or run the script against a DB copy while app is briefly paused — script
       must not run concurrently with live app writes to the same rows).
    3. Run `python scripts/migrate_reencrypt_credentials.py`.
    4. Verify: spot-check one user's `fyers_access_token` decrypts correctly with the new key via
       `decrypt_val` before restarting the app.
    5. **Before restarting** (new step, added at VALIDATE): run
       `grep -c '^ENCRYPTION_KEY=' trading-app/.env` and confirm it equals `1` with a non-empty
       value matching the key used in step 3 — do NOT rely on the running shell's env var alone,
       since `get_cipher()` reads from `.env` via `load_dotenv` on next process start.
    6. Restart the app with the new `ENCRYPTION_KEY` active and `ENCRYPTION_KEY_OLD` removed.
  - **Rollback:** Restore `trading_app.db.pre-migration-backup` and revert `.env` to the old
    `ENCRYPTION_KEY` value if verification in step 4 fails. Do NOT restart the app with a
    mismatched key — this would make all encrypted Fyers credentials undecryptable (Fyers logins
    would silently fail).

- [x] **G2. Manual (non-code) action — rotate provider-side secrets.**
  - Rotate `GOOGLE_CLIENT_SECRET`, `OPENROUTER_API_KEY`, `HF_API_KEYS`, `GITHUB_API_KEYS` at their
    respective provider dashboards. This is a manual user action outside the codebase — document
    in the phase report as an open action item, not something EXECUTE can perform. After rotation,
    update the corresponding `.env` values and restart the app.

- [x] **G3. `.gitignore` fix and untrack committed secrets/DB files.**
  - **Current:** `.gitignore` (verified content: only covers `*.log`, `logs/`, `__pycache__/`,
    `.venv/`, `env/`, `venv/`, `*.zip`, `.DS_Store`) does not exclude `.env` or `*.db`. `git
    ls-files` confirms `trading-app/.env`, `trading-app/trading.db`, `trading-app/trading_app.db`,
    `trading-app/trading_bot.db` are all currently tracked. **VALIDATE re-confirmed this directly:
    `.env` has exactly 1 prior commit in its git log — the exposure window is real but shallow.**
  - **Target:** Add to `trading-app/.gitignore`:
    ```
    .env
    *.db
    *.db-journal
    ```
    Then run `git rm --cached trading-app/.env trading-app/trading.db trading-app/trading_app.db trading-app/trading_bot.db`
    to untrack them WITHOUT deleting the working-directory copies (`git rm --cached` only removes
    from the index, files remain on disk — confirm with `ls -la trading-app/*.db trading-app/.env`
    after running).
  - **VALIDATE infra note — this repo's git root spans the entire home directory
    (`/Users/sritejpalika`), not just this project folder** (confirmed via `git rev-parse
    --show-toplevel`). This matches the umbrella plan's own documented reason for rejecting a git
    history rewrite. It also means any validator script that resolves paths via `git rev-parse
    --show-toplevel` (e.g. `validate-phase-stub.mjs`) must be invoked with a path relative to the
    true home-directory root, not relative to this `v5/` project folder — see the Validate
    Contract's Infra Fit finding.
  - **Explicit user decision — do NOT rewrite git history.** The already-committed historical
    versions of `.env` and the `.db` files remain in git history; this phase only stops FUTURE
    commits from re-adding them. This was the user's explicit choice (history rewrite carries its
    own risk of breaking other clones/branches) and must not be silently "improved on" during
    EXECUTE.
  - **Rollback:** `git rm --cached` is trivially reversible via `git add -f trading-app/.env ...`
    if this causes an unexpected deploy issue (e.g. a deploy pipeline that expects `.env` to be
    tracked) — flag this as a live-system risk to check before running G3 in production.

---

## Exit Gate

```bash
# 1. Confirm no client.exit_position references remain
grep -rn "exit_position" trading-app/ && echo "FAIL: exit_position still referenced" || echo "PASS"

# 2. Confirm admin123 hardcode removed
grep -n "admin123" trading-app/models.py && echo "FAIL: admin123 still hardcoded" || echo "PASS"

# 3. Confirm .env / *.db are gitignored and untracked
cd trading-app && git ls-files .env trading.db trading_app.db trading_bot.db
# Expected: empty output (PASS)

# 4. Confirm order_lock now wraps place_order + record_trade
# NOTE (added at VALIDATE): the widened lock block may exceed a 40-line window once regime-lockout
# checks are included inside it — if this check reports FAIL despite record_trade genuinely being
# inside the lock, increase -A to 60 or verify by reading the indentation block directly before
# treating it as a real failure.
grep -A 60 "async with state.order_lock:" trading-app/app.py | grep -q "record_trade" && echo "PASS" || echo "FAIL: record_trade not inside lock"

# 5. Confirm telegram webhook checks secret token before parsing body
grep -B2 -A3 "x-telegram-bot-api-secret-token" trading-app/app.py

# 6. (Added at VALIDATE) Confirm no route still reads the raw cookie outside the shared resolver.
# Execute-agent must name the resolver function (e.g. resolve_authenticated_user_id) and confirm
# every one of the ~20 original call sites (see Item A1) now calls it instead of reading
# request.cookies.get("user_id") directly for the purpose of resolving a *trusted* user id.
grep -n 'cookies.get("user_id")' trading-app/app.py
# Expected: matches only inside the shared resolver's own implementation, nowhere else.
```

**Manual verification (required — live-money system, cannot be fully scripted):**

- [ ] **Existing live session survives deploy:** Before deploying Item 1 (A1), capture one currently
  logged-in browser's cookie value. After deploy, confirm that browser can still make one
  authenticated request (e.g. load `/api/positions`) without being logged out, during the grace
  period. This proves the migration path does not surprise-logout active traders.
- [ ] **New-login route coverage (added at VALIDATE — regression test for the Item A1 blast-radius
  gap):** log in fresh (post-deploy) and confirm `/`, `/admin` (as an admin user), and
  `/api/user/settings` all load correctly with the new signed cookie — not just `/api/order`/
  `/api/positions`. This directly proves the ~19-route correction was actually applied everywhere.
- [ ] **Paper-trading account full order round-trip:** Using a paper-trading account
  (`PAPER_TRADING=true`), place one order via `/api/order`, confirm it appears in
  `/api/positions`, then trigger the corrected exit path (either via Strategy 5 time-stop
  simulation or a manual `cancel_order` call) and confirm the position is closed and
  `active_auto_trades` bookkeeping matches the broker-reported state — i.e. no bookkeeping
  drift between "trade marked closed" and "position actually closed."
- [ ] All 7 checklist items checked off
- [ ] Phase report written to report destination above, including the manual Telegram
  `setWebhook` step outcome and the G2 provider-secret-rotation status

---

## Blockers That Would Justify BLOCKED Status

- No paper-trading Fyers account/credentials available to verify Item 4/6 order round-trip safely
- `INITIAL_ADMIN_PASSWORD` env var cannot be set in the deploy environment before restart (Item 3
  would then log the "no admin" warning and require a follow-up manual step)
- Deploy pipeline requires `.env` to remain tracked in git (would block Item G3 as written — must
  be resolved with the user before untracking)
- No safe maintenance window to run the encryption-key migration script (Item G1) against the live
  DB without risking a concurrent write collision

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports read; test context loaded; plan drift checked
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: this plan authored directly with grounded file:line detail during initial phase-program plan creation (no prior phase plan existed to supplement)
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Status / Gate / Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog artifacts / Known gaps / Accepted by)
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [x] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written (14/14 tests, 6/6 exit-gates, 4 highest-risk claims re-verified against live code post-commit)
- [x] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done (`0e1b78c`)

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

- `trading-app/app.py` — login_api, get_current_client, place_order, telegram_webhook, plus the new
  shared `resolve_authenticated_user_id` helper and its ~19 call-site migrations (lines 224, 258,
  289, 299, 380, 417, 434, 453, 467, 481, 495, 509, 542, 574, 597, 622, 1008, 1077, 2711 — see Item A1)
- `trading-app/models.py` — get_cipher/encrypt_val/decrypt_val (unchanged, referenced by migration script), default-admin init block
- `trading-app/workers/auto_trader.py` — trailing_monitor (max-loss ordering, exit_position→cancel_order fix)
- `trading-app/fyers_client.py` — read-only reference (cancel_order signature confirmed, no change)
- `trading-app/requirements.txt` — add itsdangerous if not already present
- `trading-app/.gitignore`, `.env`, `trading_app.db`, `trading.db`, `trading_bot.db`
- `trading-app/scripts/migrate_reencrypt_credentials.py` (new file)

---

## High-Risk Class

This entire phase is a high-risk class: auth/identity, live billing-adjacent (real money order
placement), and secrets/trust-boundary logic all in one phase. Minimum test tier per
`vc-test-coverage-plan` waterfall is **Hybrid** for every item — no item in this phase may be
accepted as known-gap without an explicit documented rationale in the validate-contract.

| Area | High-risk class | Minimum tier | Gap rationale if known-gap accepted |
|---|---|---|---|
| Session cookie signing + shared-resolver rollout (A1, incl. VALIDATE correction) | auth/identity | Hybrid (manual live-session check + new-login route coverage check) | — |
| Telegram webhook auth (B1) | trust-boundary | Hybrid (requires live Telegram `setWebhook`, cannot be fully automated) | Live `setWebhook` verification is Agent-Probe/manual since it needs Telegram's live API — documented, not a silent gap |
| Admin creation + rate-limit (C1/C2) | auth/identity | Fully-automated (unit test) + Hybrid (manual lockout timing check) | — |
| exit_position fix (D1) | billing/live-money order | Hybrid (paper-trading round-trip required) | — |
| Max-loss race reorder (E1) | billing/live-money order | Hybrid (manual concurrent-tick simulation, hard to fully automate asyncio race timing) | Residual: manual-re-enable-during-square-off edge case accepted as known-gap (see Validate Contract) |
| order_lock TOCTOU fix (F1) | billing/live-money order | Fully-automated (concurrent request test) + Hybrid (paper-account live check) | — |
| Encryption key rotation (G1) | secrets/trust-boundary | Hybrid (migration script dry-run against DB copy + verification decrypt + pre-restart `.env` grep check) | — |
| Git secret untracking (G3) | secrets/trust-boundary | Fully-automated (`git ls-files` check) | — |

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `grep -rn "exit_position" trading-app/` returns empty | Fully-Automated | Broken exit-position calls fully removed (Item 4) |
| `grep -n "admin123" trading-app/models.py` returns empty | Fully-Automated | Hardcoded default admin credential removed (Item 3) |
| `git ls-files .env trading.db trading_app.db trading_bot.db` returns empty | Fully-Automated | Secrets/DB files untracked from git going forward (Item 7 / G3) |
| Concurrent `/api/order` requests test: fire N=`max_trades_per_day`+3 simultaneous requests, assert exactly `max_trades_per_day` succeed | Fully-Automated | Daily-trade-limit TOCTOU race closed (Item 6) |
| Unit test: forged raw `user_id` cookie is rejected post-grace-period; valid signed cookie is accepted | Fully-Automated | Session cookie unforgeable (Item 1) |
| Fully-Automated route-coverage check: `grep -n 'cookies.get("user_id")' app.py` shows no bare reads outside the shared resolver | Fully-Automated | Session-cookie fix blast radius is complete — no route bypasses the new verification (Item 1 correction found during VALIDATE) |
| Manual: existing live browser session (raw cookie) still makes 1 authenticated request immediately post-deploy | Agent-Probe / Manual | Grace-period migration does not surprise-logout live traders (Item 1) |
| Manual: freshly-logged-in session loads `/`, `/admin`, and `/api/user/settings` correctly | Agent-Probe / Manual | The ~19-route blast-radius correction was actually applied everywhere, not just at login/get_current_client (Item 1 correction) |
| Paper-trading account: place order → confirm position → trigger exit path → confirm broker-side + bookkeeping both closed | Hybrid | Full order lifecycle round-trips correctly with fixed exit logic (Item 4, Item 6) |
| Manual: `curl -X POST /api/telegram/webhook` without secret header returns 403; with correct header returns 200 | Hybrid | Telegram webhook authenticated (Item 2) — requires live `setWebhook` registration first |
| Manual: simulate max-loss breach with a concurrent automation_loop tick in flight; confirm no new position opens after breach detected | Hybrid | Emergency stop race closed (Item 5) |
| Migration script dry-run against a copy of `trading_app.db`; spot-check decrypt with new key succeeds; `.env` grep-verified before restart | Hybrid | Encryption key rotation is safe and reversible (Item 7 / G1) |

---

## Test Infra Improvement Notes

- Exit Gate check #4 (`order_lock` line-window grep) is fragile — a fixed `-A N` line-count window
  breaks silently if unrelated code is added/removed between the lock statement and
  `record_trade()`. Consider replacing with a semantic check (e.g. parse the indented block) in a
  future test-infra hardening pass. Not blocking for this phase — documented as a known fragility.
- No existing automated test suite was found for `trading-app/` (no `tests/`, `pytest.ini`, or
  `*.test.py` files discovered during VALIDATE's context-discovery pass). All "Fully-Automated"
  gates in this contract are new tests that do not yet exist and must be authored during EXECUTE —
  they are not being run against a pre-existing suite.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/security-remediation/active/trading-remediation_03-07-26/phase-01-critical-security_PLAN_03-07-26.md`
- Last completed step: VALIDATE (Step 4, PVL) — full V1-V7 run, validate-contract written, plan
  updated in place with the Item A1 blast-radius correction (P1) and several execute-agent
  instructions (see Validate Contract below)
- Validate-contract status: written — Gate: CONDITIONAL (see below)
- Supporting context files loaded: `trading-app/app.py`, `trading-app/models.py`, `trading-app/workers/auto_trader.py`, `trading-app/fyers_client.py`, `trading-app/.gitignore`, `trading-app/requirements.txt`, `trading-app/engine/automation.py`, `trading-app/requirements.txt` (all read directly during plan drafting AND during VALIDATE to confirm exact current line numbers and behavior; drift from original audit documented above)
- Next step: Orchestrator should have a human review the Item A1 blast-radius correction (the
  ~19-route fix) before spawning vc-execute-agent, given this is a live-money auth surface — see
  the Validate Contract's High-Risk Pack section. Once reviewed/accepted, spawn vc-execute-agent
  per the approved plan and validate-contract.

---

## Validate Contract

Status: CONDITIONAL
Date: 03-07-26
date: 2026-07-03
generated-by: outer-pvl

Parallel strategy: parallel-subagents
Rationale: 7/7 signals present (multi-package-adjacent single-file-but-multi-route scope, auth/schema-adjacent surface touched, phase-program classification, high-risk class present, 5+ files in blast radius) — Layer 1 (4 dimension agents) + Layer 2 (7 section agents, one per Step A–G) ran as independent read-only fan-out, no cross-agent coordination needed since each section maps to disjoint file regions; synthesis performed in this single VALIDATE pass.

### Net Gate Derivation

| Layer 1 dimensions | Status |
|---|---|
| Infra fit | CONCERN |
| Test coverage | CONCERN |
| Breaking changes | FAIL → resolved via Plan Update P1 (applied) |
| Security surface | CONCERN |

| Layer 2 sections | Status |
|---|---|
| Step A — Session Auth Fix | FAIL → resolved via Plan Update P1 (applied); residual CONCERN on manual verification depth |
| Step B — Telegram Webhook Auth | PASS |
| Step C — Admin Credentials & Rate Limiting | PASS |
| Step D — Fix Broken Position-Exit Method | PASS |
| Step E — Fix Emergency Stop-Loss Race | CONCERN (residual known-gap, accepted) |
| Step F — Fix Daily-Trade-Limit TOCTOU Race | CONCERN (Exit Gate check #4 line-window fragility) |
| Step G — Secret Rotation & Git History Hygiene | CONCERN (get_cipher() auto-regen risk; documented and mitigated with new instruction) |

**Totals (after P1 applied): 0 unresolved FAILs / 6 CONCERNs / 1 PASS-with-note / 3 PASS**

**→ Net Gate: CONDITIONAL**

### Test gates (C3 5-column table)

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| item-1-cookie-signing | Forged raw `user_id` cookie is rejected post-grace-period; valid signed cookie accepted | Fully-Automated | New unit test in `trading-app/tests/test_auth_cookie.py` (new file) — asserts `resolve_authenticated_user_id`/`get_current_client` behavior for: valid signed token, expired/bad signature, legacy raw digit within grace period, legacy raw digit after grace period | B |
| item-1-route-coverage | No route bypasses the shared cookie resolver | Fully-Automated | `grep -n 'cookies.get("user_id")' trading-app/app.py` shows matches only inside the resolver's own implementation | B |
| item-1-live-session | Existing live browser session (raw cookie) still authenticated immediately post-deploy | Agent-Probe | Manual: capture live cookie pre-deploy, confirm `/api/positions` succeeds post-deploy during grace period | A (planned for deploy day) |
| item-1-new-login-coverage | Freshly-logged-in session loads `/`, `/admin`, `/api/user/settings` correctly | Agent-Probe | Manual: fresh login post-deploy, load all three routes, confirm correct page/response (not landing-page fallback) | A (planned for deploy day) |
| item-2-webhook-auth | `/api/telegram/webhook` requires valid secret token | Hybrid | `curl -X POST /api/telegram/webhook` without header returns 403; with correct header (post-`setWebhook`) returns 200 — precondition: `TELEGRAM_WEBHOOK_SECRET` set and Telegram `setWebhook` call completed | A (planned for deploy day) |
| item-3-admin-hardcode | No hardcoded `admin123` credential created | Fully-Automated | New unit test asserting `Database.init_db()` on an empty DB with no `INITIAL_ADMIN_PASSWORD` set creates zero admin rows | B |
| item-3-rate-limit | 5 failed logins within 15 min locks the account | Fully-Automated | New unit test simulating 6 failed `login_api` calls, asserting the 6th returns the lockout message without checking password | B |
| item-4-exit-fix | `cancel_order` called with correct signature; no `exit_position` references remain | Fully-Automated | `grep -rn "exit_position" trading-app/` returns empty | A |
| item-4-order-roundtrip | Paper-trading order round-trips: place → confirm position → exit → confirm closed on both sides | Hybrid | Manual paper-trading round trip via `/api/order` + `/api/positions` — precondition: `PAPER_TRADING=true` and a paper account configured | A (planned for deploy day) |
| item-5-race-reorder | `automation_enabled=False` set before square-off loop begins | Fully-Automated | `grep -B5 "for pos in open_positions" trading-app/workers/auto_trader.py` shows `automation_enabled = False` appears before the loop | B |
| item-5-race-live | Concurrent automation_loop tick cannot open a position after breach detected | Hybrid | Manual: simulate max-loss breach with a concurrent automation_loop tick in flight — precondition: paper-trading account with an open position | A (planned for deploy day) |
| item-6-toctou-fix | order_lock wraps place_order + record_trade | Fully-Automated | `grep -A 60 "async with state.order_lock:" trading-app/app.py \| grep -q "record_trade"` exits 0 | A |
| item-6-toctou-concurrency | N=max_trades_per_day+3 concurrent requests yield exactly max_trades_per_day successes | Fully-Automated | New concurrency test firing N simultaneous `/api/order` requests against a test client, asserting exact success count | B |
| item-7-encryption-migration | Migration script re-encrypts correctly and is verifiable before cutover | Hybrid | Dry-run `python scripts/migrate_reencrypt_credentials.py` against a copy of `trading_app.db`; spot-check `decrypt_val` with new key — precondition: DB copy + both `ENCRYPTION_KEY`/`ENCRYPTION_KEY_OLD` set | A (planned for deploy day) |
| item-7-git-untrack | `.env`/`*.db` untracked from git | Fully-Automated | `cd trading-app && git ls-files .env trading.db trading_app.db trading_bot.db` returns empty | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle) / planned for deploy day where a live precondition is required
- B — fixed in this plan (gate added by this plan's checklist; execute-agent must write the test file as part of the section)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: no `Known-Gap` value used in the `strategy` column above — the one accepted
residual (Step E manual-re-enable-during-square-off race) is carried as a named residual row below
under Known Gaps, not as a proving strategy.

Legacy line form:
- Session cookie (Item 1): Fully-automated: new unit test for signed/legacy cookie verification + route-coverage grep | Agent-Probe: live-session survival + new-login route check (deploy day)
- Telegram webhook (Item 2): Hybrid: curl test against secret-token header, precondition `setWebhook` registered
- Admin/rate-limit (Item 3): Fully-automated: unit tests for no-hardcode and lockout behavior
- Exit fix (Item 4): Fully-automated: `exit_position` grep | Hybrid: paper-trading round trip
- Max-loss race (Item 5): Fully-automated: statement-order grep | Hybrid: concurrent-tick simulation
- TOCTOU fix (Item 6): Fully-automated: lock-scope grep + concurrency test
- Secret rotation (Item 7): Hybrid: migration dry-run + decrypt spot-check | Fully-automated: git ls-files check

### Dimension findings

- Infra fit: CONCERN — this repo's git root spans the entire home directory (`/Users/sritejpalika`), confirmed via `git rev-parse --show-toplevel`; scripts that resolve paths via that command (e.g. `validate-phase-stub.mjs`) must be invoked with the path relative to the true home-directory root, not relative to `v5/`, or they will falsely report "does not exist on disk." Not a plan defect — documented so execute-agent/orchestrator doesn't mistake it for a real gate failure. Single-process Uvicorn confirmed (no `workers=` arg), validating the C2 in-memory rate-limit design. `.env` loading path confirmed correct for all new env vars (`SECRET_KEY`, `TELEGRAM_WEBHOOK_SECRET`, `INITIAL_ADMIN_PASSWORD`, `ENCRYPTION_KEY_OLD`). Separately, V1's mandatory `validate-plan-artifact.mjs` structural check reports 4 residual FAIL lines against this file (missing overview/context heading, Complexity metadata, Phase Completion Rules, Acceptance Criteria) — these are expected for this phase-program per-phase-stub shape, which intentionally uses `## Purpose` instead of `## Overview` and omits the SIMPLE/COMPLEX single-plan fields. The dedicated validator for this shape, `validate-phase-stub.mjs`, reports 0 failures / 0 warnings when invoked with a path relative to the true git root. This is a known generic-validator/template-shape mismatch (the generic validator has not been updated to recognize the phase-program stub shape), not a plan defect — reported here per V1 Step 3b's mandatory reporting requirement, not treated as a blocking FAIL.
- Test coverage: CONCERN — no existing automated test suite found for `trading-app/` (no `tests/`, `pytest.ini`, or `*.test.py` discovered); every Fully-Automated gate above is a new test to be authored during EXECUTE, not a pre-existing suite being re-run. Several gates are inherently Hybrid/Agent-Probe (live paper-trading round trip, live Telegram webhook, live session survival) because this is a live-money system — this is expected for this domain, not a coverage failure, and matches the plan's own High-Risk Class table.
- Breaking changes: FAIL → resolved via Plan Update P1 — the plan as originally scoped only patched `login_api`/`get_current_client` for the signed-cookie migration, but ~19 other route handlers in `app.py` (including the `/` root route) read the raw cookie directly and bypass `get_current_client` entirely; shipping as originally scoped would break the primary page and most admin/settings/API routes for any user who authenticates after deploy. Fixed by extracting a shared `resolve_authenticated_user_id` helper and migrating all ~20 call sites — this is a blast-radius completion of the already-chosen design, not a new architecture, so it is applied directly to the plan (see Item A1 above) rather than requiring a return to INNOVATE.
- Security surface: CONCERN — `models.py`'s `get_cipher()` will silently generate and persist a brand-new `ENCRYPTION_KEY` to `.env` if the env var is unset at process start; during the Item G1 key-rotation cutover, a missed or mistyped `.env` edit would silently orphan all just-migrated credentials with no error. Mitigated with a new pre-restart verification step (Item G1, deployment step 5) and an execute-agent instruction below. Login rate-limiting keyed by username (not IP) is a deliberate, documented tradeoff, not a gap.

### Layer 2 — Per-Section Feasibility (detail)

**Step A — Session Auth Fix**
- Mechanical feasibility: CONCERN → resolved. Edit targets (`app.py:194-196`, `:797-811`) are correct and uniquely matchable, but the section as originally scoped omitted ~19 other call sites that must change in the same deploy. Resolved via Plan Update P1.
- Plan gaps: Found and fixed (see P1).
- Conflicts: None — Phase 2's guest-fallback/401 redesign is confirmed (via the plan's own note) to be a separate, later change to the same functions; Phase 1's fix does not preempt or conflict with it.
- Highest-risk edit: The `resolve_authenticated_user_id` extraction and its ~20 call-site migration. Execute-agent should do ALL ~20 call sites in one atomic commit (not partial), since a partial migration would leave some routes broken relative to others depending on cookie type. Sequence: write the helper + tests first (red), migrate `get_current_client`, then migrate the remaining 19 call sites in one pass, run the full route-coverage grep as a final check before moving to Step B.

**Step B — Telegram Webhook Auth**
- Mechanical feasibility: PASS — `data = await request.json()` confirmed as the first statement; header check insertion point is unambiguous.
- Plan gaps: none found.
- Conflicts: none found.
- Highest-risk edit: the one-time `setWebhook` call itself (external, live, cannot be scripted from this repo) — execute-agent must document success/failure explicitly in the phase report since a failed `setWebhook` call would silently break all real Telegram delivery.

**Step C — Admin Credentials & Rate Limiting**
- Mechanical feasibility: PASS — `models.py:230-236` and `app.py:179-203` confirmed exactly as described.
- Plan gaps: none found.
- Conflicts: none found (existing live admin account is unaffected, confirmed via the `if not c.fetchone():` guard already in place).
- Highest-risk edit: none — this is the lowest-risk section in the phase.

**Step D — Fix Broken Position-Exit Method**
- Mechanical feasibility: PASS — `FyersClient.cancel_order(self, order_id: str) -> Dict` confirmed at `fyers_client.py:1650`; the plan's replacement call (`client.cancel_order, sl_order_id`, plain string) matches the real signature exactly. This was the item the user most wanted grounded, and it is correct as written.
- Plan gaps: none found.
- Conflicts: none found.
- Highest-risk edit: the mark-closed ordering fix (only clearing bookkeeping after confirmed cancel or confirmed-flat position) — execute-agent should write this as its own small testable unit, not inline, given it directly affects whether a live position could be silently forgotten.

**Step E — Fix Emergency Stop-Loss Race**
- Mechanical feasibility: PASS — confirmed the exact current ordering (loop before flag-set) and confirmed `automation_loop` reads the same flag concurrently at `auto_trader.py:1208`.
- Plan gaps: CONCERN — manual re-enable via Telegram/API mid-square-off is a residual race not covered by this fix. Accepted as a Known Gap below (documented, not silent).
- Conflicts: none found.
- Highest-risk edit: the flag-set relocation itself — trivial diff, but execute-agent must re-run the `grep -n "automation_enabled"` check specified in the plan immediately before finalizing, since state.py/app.py could have drifted further by EXECUTE time.

**Step F — Fix Daily-Trade-Limit TOCTOU Race**
- Mechanical feasibility: PASS — confirmed the exact current narrow-lock code shape.
- Plan gaps: CONCERN — the plan's own Exit Gate check #4 (`grep -A 40`) is likely too narrow a window once the lock is correctly widened; increased to `-A 60` in this contract's Exit Gate section, with a fallback instruction to verify manually if it still misses.
- Conflicts: none — confirmed `FyersClient.place_order` does not itself touch `state.order_lock`, so no nested-lock deadlock risk.
- Highest-risk edit: widening the lock scope around the live `client.place_order` broker call — execute-agent must confirm no unexpectedly-long broker round-trip inflates lock hold time enough to cause new-request timeouts under the "Order is currently being placed" pre-check at `app.py:2051`.

**Step G — Secret Rotation & Git History Hygiene**
- Mechanical feasibility: PASS — confirmed `.env`/`*.db` tracking status and `.gitignore` current content exactly as described.
- Plan gaps: CONCERN → mitigated. `get_cipher()`'s auto-regeneration-on-missing-key behavior was not mentioned in the original plan; added as an explicit pre-restart verification step (G1, deployment step 5) and an execute-agent instruction below.
- Conflicts: none found.
- Highest-risk edit: the migration script's re-encryption pass against the live DB — execute-agent must run the dry-run against a DB copy first (already specified) and must not skip the pre-restart `.env` grep check added in this contract.

### Plan updates applied

- [x] P1 — Item A1 (Step A) expanded to cover ~19 additional `app.py` route handlers that read the raw session cookie directly and bypass `get_current_client`; added a shared `resolve_authenticated_user_id` helper requirement, updated Blast Radius, Public Contracts, and Touchpoints sections accordingly. (Applied directly to the plan body above.)
- [x] P2 — Item G1 deployment steps: added a pre-restart `.env` verification step (step 5) guarding against `get_cipher()`'s silent auto-key-regeneration behavior.
- [x] P3 — Exit Gate check #4: widened the `grep -A` window from 40 to 60 lines and added a fallback-verification note, to avoid a false FAIL after the lock-widening fix.
- [x] P4 — Added a new manual verification bullet ("New-login route coverage") and a corresponding Verification Evidence row, directly testing that P1's fix was applied everywhere.
- [x] P5 — Added a `## Test Infra Improvement Notes` entry documenting that no pre-existing automated test suite exists for `trading-app/`, so all Fully-Automated gates in this contract are net-new tests execute-agent must author.

### Execute-agent instructions

- E1 — Item A1 / Step A: migrate ALL ~20 cookie-read call sites (the 19 lines listed in the Blast Radius section plus `get_current_client`) to the new `resolve_authenticated_user_id` helper IN THE SAME COMMIT as the cookie-signing change. Do not ship the signed-cookie change with only a partial subset migrated — a partial migration is worse than the current state because it silently breaks a random subset of routes depending on which have been updated.
- E2 — Item G1: before restarting the app post-migration, run `grep -c '^ENCRYPTION_KEY=' trading-app/.env` and confirm it is exactly `1` with a value matching the key used to re-encrypt in step 3. If this check fails or is skipped, do NOT restart the app — `get_cipher()` will silently generate a new key and permanently orphan the just-migrated credentials.
- E3 — Item F1 / Exit Gate check #4: if `grep -A 60 "async with state.order_lock:" trading-app/app.py | grep -q "record_trade"` still reports FAIL after the fix is correctly applied, verify manually by reading the indented block directly before treating it as a real regression — the line-count window is a known fragility, not a semantic check.
- E4 — Item G3: confirm before running `git rm --cached` that no deploy pipeline in this environment expects `.env` to remain tracked (the Blockers section already lists this; execute-agent must actively check, not assume).
- E5 — All items: this phase is a High-Risk Pack requirement (auth/identity + billing/live-money-adjacent + secrets/trust-boundary, per `vc-risk-evidence-pack`). Produce the 5-artifact evidence pack (`risk-gate.json`, `context-snippets.json`, `verification.json`, `review-decision.json`, `adversarial-validation.json`) inside this task folder's `harness/` subdirectory before treating any item in this phase as ready to finalize. Do not report DONE on this phase without it.
- E6 — Item A1: write the new unit test file (`trading-app/tests/test_auth_cookie.py`) BEFORE editing `login_api`/`get_current_client`/the new helper (red-first), per this repo's TDD-first test coverage convention.

### High-risk pack

Required: yes

This phase touches all three of: auth/identity (session cookie signing + ~20-route resolver
migration), billing/live-money-adjacent (order placement, exit-position fix, max-loss race,
TOCTOU fix), and secrets/trust-boundary (encryption key rotation, Telegram webhook secret,
provider API key rotation). Per `vc-risk-evidence-pack`, the 5-artifact evidence pack
(`risk-gate.json`, `context-snippets.json`, `verification.json`, `review-decision.json`,
`adversarial-validation.json`) must be produced inside this task folder's `harness/`
subdirectory before this phase is treated as ready to finalize or hand off. Given the item A1
correction found in this VALIDATE pass, `review-decision.json` should explicitly record a human
(not just an agent) reviewing the ~20-route resolver migration before it ships, given the blast
radius includes the platform's primary landing page.

### Backlog artifacts to create during durable capture

- `phase1-square-off-reentry-guard_NOTE_03-07-26.md` — `process/features/security-remediation/backlog/` — tracks the Step E residual: a manual automation re-enable (Telegram `/start` or the toggle-automation API) arriving mid-square-off could still race with `trailing_monitor`'s exit loop; needs a broader "square-off in progress" guard, scoped as a follow-up (likely Phase 2 or a dedicated fast-follow), not required for Phase 1 to close.
- `exit-gate-line-window-fragility_NOTE_03-07-26.md` — `process/features/security-remediation/backlog/` — tracks replacing the Exit Gate #4 fixed-line-window grep with a semantic block check; low priority, cosmetic robustness only.

### Known gaps on record

- Manual automation re-enable (Telegram `/start` / toggle-automation API) during an in-progress emergency square-off is not guarded against in this phase — accepted because it requires precise user-timed action during an active emergency exit (narrow window, user-triggered not background-triggered), and because Phase 1's scope is the background-loop race specifically, not all possible re-enable timing interactions. Tracked via the backlog note above. Rationale accepted given the live-money urgency of shipping the primary race fix now.
- No pre-existing automated test suite exists for `trading-app/` — all Fully-Automated gates in this contract are new tests to be authored during EXECUTE. Accepted because building a full test harness from scratch is out of this phase's scope (fixing the 7 audit findings); the new tests required by this contract are the minimum necessary to prove each fix, not a general test-suite backfill.
- Exit Gate check #4's line-window grep is a known fragility (widened from 40 to 60 lines in this contract but still not semantic). Accepted as low-risk since execute-agent has an explicit fallback instruction (E3) to verify manually if it misfires.

### What This Coverage Does NOT Prove

- item-1-cookie-signing (Fully-Automated unit test) does NOT prove the resolver is actually wired into all ~20 call sites in production code — that is proven separately by item-1-route-coverage's grep check, and by the item-1-new-login-coverage manual check.
- item-1-route-coverage (grep check) does NOT prove the resolver's internal logic is correct — only that no call site bypasses it. Correctness of the signed/grace-period logic itself is proven by item-1-cookie-signing.
- item-1-live-session and item-1-new-login-coverage (Agent-Probe, deploy day) do NOT prove behavior under concurrent load or across all ~19 routes individually — they spot-check a representative subset (`/`, `/admin`, `/api/user/settings`, `/api/positions`). A route not explicitly spot-checked could still have an undiscovered migration mistake.
- item-2-webhook-auth (Hybrid) does NOT prove Telegram's `setWebhook` registration itself succeeded beyond the one manual curl check — if `setWebhook` silently fails days later (e.g. Telegram-side config drift), this gate will not re-detect it since it is not a recurring automated check.
- item-3-admin-hardcode / item-3-rate-limit (Fully-Automated) do NOT prove the lockout duration or backoff behavior under real concurrent multi-IP attack traffic — only the unit-level logic path.
- item-4-exit-fix (grep) does NOT prove the corrected `cancel_order` call actually succeeds against the live Fyers broker — only that the dead `exit_position` reference is gone. Live broker-side success is proven separately by item-4-order-roundtrip.
- item-4-order-roundtrip (Hybrid, paper-trading) does NOT prove identical behavior against the live (non-paper) broker endpoint — Fyers paper vs live order handling can differ in edge cases (e.g. slippage, partial fills) not exercised by paper mode.
- item-5-race-reorder (grep) does NOT prove the race is closed under real concurrent asyncio scheduling — only that the statement order is correct. Real concurrency behavior is proven separately by item-5-race-live.
- item-5-race-live (Hybrid, manual simulation) does NOT prove the manual-re-enable-during-square-off residual case is closed — that is an explicitly accepted Known Gap, not covered by any gate in this contract.
- item-6-toctou-fix (grep) does NOT prove the lock actually prevents over-limit trades under load — only that the lock's scope is structurally correct. Real concurrency behavior is proven separately by item-6-toctou-concurrency.
- item-6-toctou-concurrency (Fully-Automated, new test) does NOT prove behavior against the live broker under real network latency — the test exercises the lock/state logic with a mocked or paper `place_order`, not a live broker round-trip under production latency.
- item-7-encryption-migration (Hybrid, dry-run against a DB copy) does NOT prove the live cutover itself will succeed — it proves the script's logic is correct against a snapshot. The live cutover still depends on the manual `.env` verification step (execute-agent instruction E2) being followed correctly in real time.
- item-7-git-untrack (Fully-Automated) does NOT prove historical commits containing the secrets were removed from git history — by explicit user decision, history rewrite is out of scope for this phase (and this program); the secret's prior exposure in history is mitigated by rotation (Item G2), not erasure.

### Accepted by

Accepted by: session (autonomous VALIDATE pass, single-session run — no live user present to interactively accept/reject). Accepted concerns by name: (1) Infra fit — git-root-spans-home-directory validator-path quirk; (2) Test coverage — no pre-existing automated suite for trading-app/; (3) Security surface — get_cipher() auto-regen risk, mitigated with execute-agent instruction E2; (4) Step E residual — manual re-enable during square-off race, tracked via backlog note; (5) Step F — Exit Gate #4 line-window fragility, mitigated with widened window + fallback instruction E3. All CONCERNs and the one applied FAIL-resolution (P1) are surfaced explicitly in this contract and in the chat response for human review before EXECUTE begins, given this phase's live-money auth/billing/secrets risk profile. The High-Risk Pack (above) explicitly requires a human `review-decision.json` entry before this phase can be treated as ready to finalize — this is the checkpoint where a human must actually sign off, not this VALIDATE pass alone.
