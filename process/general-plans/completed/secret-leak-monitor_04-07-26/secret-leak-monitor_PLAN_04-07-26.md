---
name: plan:secret-leak-monitor
description: "Throttled secret-leak-detection check inside the self-healing health agent, alerting admin via Telegram on exposed secrets"
date: 04-07-26
feature: general
---

# Secret Leak Monitor — Implementation Plan (SIMPLE)

Date: 04-07-26
Status: VALIDATE PASS — ready for EXECUTE
Complexity: SIMPLE

## Overview

Add a throttled, read-only secret-leak scanner to the existing `health_monitor_worker()` loop in
`trading-app/workers/health_agent.py`. It tails the app's log files once per hour, regexes for
known secret patterns, and fires exactly one Telegram alert per distinct leak via the existing
`notify_admin()` helper. Detect-and-alert only — no auto-remediation.

## Goals

1. Detect exposed secrets (Gemini/OpenRouter/HuggingFace/GitHub/Telegram-token patterns) in the
   tail of the app's log files, cheaply and without blocking the event loop.
2. Alert the admin via the existing `notify_admin()` path, once per distinct finding (dedup).
3. Add a lightweight `.env` world-readable permission check as a bonus MVP signal.
4. Never run more than once per hour; never scan whole files; never auto-fix.

## Non-Goals / Deferred

- Scanning for `.env`/`*.db` becoming git-tracked (deferred — home-directory git root is heavy to
  scan; documented as an optional future extension, not built now).
- Any auto-remediation of a leak (explicitly forbidden — leaks are not, and must never be, in
  `ALLOWED_FIX_ACTIONS`).

## Touchpoints

- `trading-app/workers/health_agent.py` — ONLY file changed. New module-level constants, new
  `scan_for_leaked_secrets()` async function, new dedup/throttle state, and a ~6-line wire-in
  inside `health_monitor_worker()`'s existing `while True` loop.

No other file is touched. `state.py` (`notify_admin`'s underlying `broadcast_log`) is read-only
context — its signature is already `broadcast_log(msg, level="info", user_id=None,
telegram_alert=False)` and is not modified.

## Public Contracts

None. This is an internal background-loop addition — no new API route, no schema change, no new
public/callable surface. `HEALTH_AGENT_STATUS` dict gains two new keys (`last_secret_scan`,
`last_secret_alert_count`) which are additive/backward-compatible (existing consumers of this dict
only read known keys such as `status`/`last_check`/`is_paused`; grep confirms no consumer enumerates
all keys or fails on unknown keys — `trading-app/app.py:2601` returns the whole dict verbatim).

## Blast Radius

- **Files changed:** 1 (`trading-app/workers/health_agent.py`)
- **Risk class:** none of auth/billing/schema/public-API/deploy — this is a monitoring/alerting
  addition. Read-only file I/O (log tails) + read-only `os.stat` on `.env`. No writes to disk, no
  DB writes, no new env vars required (though `.env` path is inferred from `BASE_DIR`-style
  conventions already used in the codebase — see checklist item 2).
- **Size:** small, ~90-120 new lines in one file.

## Implementation Checklist

1. **Add secret-pattern constants** (top of `trading-app/workers/health_agent.py`, near existing
   `ALLOWED_FIX_ACTIONS`):
   ```python
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
   SECRET_SCAN_LOG_FILES = [
       "trading-app/logs/dashboard.log",
       "trading-app/logs/fyersApi.log",
       "trading-app/logs/fyersRequests.log",
       "trading-app/app.log",
   ]
   ```
   Note: paths are relative to repo root as observed on disk (`trading-app/logs/*.log`,
   `trading-app/app.log`, confirmed via `ls`). Resolve them relative to `os.path.dirname(__file__)`
   (i.e. `../logs/*.log` and `../app.log` from `workers/health_agent.py`) so the scan works
   regardless of CWD the server was launched from — mirror the existing `BASE_DIR`-style pattern
   used elsewhere in the codebase (see `process/context/all-context.md` Env var groups: `BASE_DIR`).

   **[VALIDATE fix]** Also add `import hashlib` next to the existing `import re` line at the top
   of the file. `hashlib` is NOT currently imported in `health_agent.py` (confirmed by grep) and
   is required by the fingerprint computation in step 2 below — without this the code will
   `NameError` on the first match.

2. **Add module-level throttle/dedup state** (near `HEALTH_AGENT_STATUS`):
   ```python
   _last_secret_scan_ts = 0.0
   _alerted_secret_fingerprints = set()
   ```
   Fingerprint = `hashlib.sha256((pattern_name + ":" + matched_text[:12]).encode()).hexdigest()[:16]`
   (do NOT log/alert the full matched secret — only a short prefix goes into the hash input, and
   only the hash digest is stored/compared — to avoid re-leaking the secret itself in the
   Telegram alert or in logs). Store fingerprints in-memory only (process-lifetime dedup is
   sufficient for this MVP — restart naturally resets and is documented as an accepted known-gap,
   not silently hidden).

3. **Implement `async def scan_for_leaked_secrets() -> list[dict]`**:
   - For each path in `SECRET_SCAN_LOG_FILES`: skip silently if the file doesn't exist (`os.path.exists`).
   - Read only the tail: open in binary mode, `seek` to `max(0, filesize - SECRET_SCAN_TAIL_BYTES)`,
     read to EOF, decode with `errors="ignore"`. Wrap the blocking file I/O in
     `asyncio.to_thread(...)` so the event loop is never blocked (mirrors the existing
     `asyncio.to_thread(client.refresh_via_refresh_token)` pattern already used in `execute_fix`).
   - Run each compiled regex from `SECRET_PATTERNS` against the tail text.
   - For each match: build a fingerprint (see step 2); if fingerprint already in
     `_alerted_secret_fingerprints`, skip (already alerted, no repeat); otherwise add to a
     `findings` list as `{"pattern_name": ..., "file": path, "fingerprint": fp, "preview": matched_text[:8] + "…"}`.
     (`preview` is carried in the return value for potential future debugging only — it must
     NEVER be passed to `notify_admin()` or any `logger` call; see step 5's wire-in, which uses
     only `pattern_name` and `file`.)
   - Also run the `.env` world-readable check (see step 4) and append any finding to the same list.
   - Return `findings` (empty list if nothing new).
   - Catch and log (not raise) any exception per-file so one bad file never aborts the whole scan.

4. **Implement `.env` permission check** (small helper, called from step 3, or inlined):
   ```python
   def _check_env_world_readable() -> dict | None:
       env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
       try:
           mode = os.stat(env_path).st_mode
           if mode & 0o004:  # world-readable bit
               return {"pattern_name": ".env world-readable", "file": env_path,
                        "fingerprint": "env-world-readable", "preview": "n/a"}
       except FileNotFoundError:
           pass
       return None
   ```
   This finding's fingerprint is static (`"env-world-readable"`), so it also naturally dedups via
   the same `_alerted_secret_fingerprints` set — but it should be RE-ALERTED if the condition
   clears and then reoccurs. Simplification for MVP: treat it exactly like any other fingerprinted
   finding (alert once, no repeat) — document this as an accepted limitation in Known Gaps rather
   than adding extra state-machine complexity for a secondary/optional check.

5. **Wire into `health_monitor_worker()`** — insert as a new throttled step inside the existing
   `while True:` loop, after the existing "1. Check Strategies" block and before "2. Check System
   Logs" (or after — ordering does not matter functionally; placing it as a new numbered step
   keeps the loop readable):
   ```python
   # 1b. Throttled secret-leak scan (at most once per hour)
   now_ts = time.time()
   if now_ts - _last_secret_scan_ts >= SECRET_SCAN_INTERVAL_SECONDS:
       _last_secret_scan_ts = now_ts
       HEALTH_AGENT_STATUS["last_secret_scan"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
       findings = await scan_for_leaked_secrets()
       if findings:
           HEALTH_AGENT_STATUS["last_secret_alert_count"] = len(findings)
           # [VALIDATE fix] Batch ALL findings from this scan cycle into ONE Telegram
           # message — never one notify_admin() call per finding. A burst of several
           # distinct leaks in a single cycle must not spam multiple messages.
           lines = []
           for f in findings:
               _alerted_secret_fingerprints.add(f["fingerprint"])
               lines.append(f"- {f['pattern_name']} in {os.path.basename(f['file'])}")
           await notify_admin(
               "⚠️ Possible secret exposure(s) detected — rotate the credential(s) and "
               "check logging:\n" + "\n".join(lines)
           )
   ```
   Use `global _last_secret_scan_ts` at the top of `health_monitor_worker()` since it reassigns a
   module-level variable (Python scoping requirement — `_alerted_secret_fingerprints` is mutated
   via `.add()` so it does NOT need `global`).
   Do NOT call `execute_fix()` or add `"leak"` to `ALLOWED_FIX_ACTIONS` — this step must remain
   strictly detect-and-alert per Phase-2 hardening (do not weaken the exact-token allowlist).

6. **Add a test/on-demand trigger seam for verification without waiting an hour** — expose
   `scan_for_leaked_secrets()` as a standalone importable async function (already true from step 3
   — no extra wiring needed) so it can be called directly and manually in a Python REPL/test
   script without going through the 3600s throttle gate. Document this in the Verification section
   below rather than adding a new admin API route (out of scope / avoids new public surface).

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Plant a fake Gemini-shaped key (`AIzaSy` + 25 chars) in a temp log file; call `scan_for_leaked_secrets()` directly (monkeypatch `SECRET_SCAN_LOG_FILES` to point at the temp file) in an isolated script/REPL; assert returned findings list is non-empty and names the right pattern | Fully-Automated | Detection: scanner correctly identifies each of the 6 required secret patterns |
| Call `scan_for_leaked_secrets()` twice in a row with the same planted secret; assert 2nd call still returns the finding (scan itself is not what dedups) but the fingerprint is now present in `_alerted_secret_fingerprints` after the caller records it — assert the wiring code path in `health_monitor_worker()` would skip re-alerting (inspect fingerprint set membership) | Fully-Automated | Dedup: admin gets one alert per distinct leak, not a repeat every hour |
| Create a temp file sized > `SECRET_SCAN_TAIL_BYTES`, place the fake secret only in the last 1KB, and separately place a decoy secret-shaped string beyond the tail-read boundary (first bytes of the file); assert only the near-end secret is found | Fully-Automated | Performance/safety constraint: only the tail of each log file is read, not the whole file |
| Run `scan_for_leaked_secrets()` against the real files in `SECRET_SCAN_LOG_FILES` (no planted secrets) on a dev machine; assert it completes without exception and returns `[]` or only the `.env`-permission finding if applicable | Hybrid — precondition: real log files must exist on disk at the expected relative paths | Safety: scan runs cleanly against real, large (MB-sized) log files without error or excessive latency |
| `chmod 644 .env` (world-readable) vs `chmod 600 .env`; call `_check_env_world_readable()` directly; assert it returns a finding only in the 644 case | Fully-Automated | `.env` world-readable check works as the documented MVP secondary signal |
| Manually confirm (by temporarily lowering `SECRET_SCAN_INTERVAL_SECONDS` to e.g. `5` in a local run, or by directly calling the wired-in block logic in isolation) that `notify_admin()` is invoked with a message containing pattern name + filename for each finding, and — plant 2+ distinct fake secrets in one cycle — assert exactly ONE `notify_admin()` call fires listing all of them (not one call per finding) | Agent-Probe | End-to-end alert path: on a finding (or a burst of findings), `notify_admin()` fires exactly once per scan cycle with a clear, actionable, batched message naming what leaked and where |
| Grep `trading-app/workers/health_agent.py` post-change to confirm `ALLOWED_FIX_ACTIONS` is unchanged (still exactly `{"restart_ws", "relogin", "clear_cache", "wait"}`) and that no new code path calls `execute_fix()` for a secret finding | Fully-Automated | Non-regression: Phase-2 hardening (exact-token allowlist, no auto-remediation of leaks) is preserved |
| Grep the wired-in `notify_admin(...)` call site(s) added by this plan to confirm the message text is built only from `pattern_name` / `os.path.basename(file)` and never from `preview` or the raw matched text | Fully-Automated | Non-self-leak: the detector never echoes the matched secret value into logs or the Telegram message |

**How to test without waiting an hour:** call `scan_for_leaked_secrets()` directly from a throwaway
Python script (`python3 -c "..."` or a scratch `.py` file) with `health_agent.SECRET_SCAN_LOG_FILES`
monkeypatched to point at a temp file containing a planted fake secret — this bypasses both the
3600s throttle (throttle lives in the caller, `health_monitor_worker()`, not in the scan function
itself) and the need to run the full worker loop. This isolates the scan logic from the alert
delivery, so tests never actually spam the real Telegram bot.

## Acceptance Criteria

- `scan_for_leaked_secrets()` detects all 6 secret patterns when planted in the tail of a log file.
- No log file is ever read in full — only the last `SECRET_SCAN_TAIL_BYTES` bytes per cycle.
- The scan runs at most once per hour inside `health_monitor_worker()` (throttle verified via
  `_last_secret_scan_ts` gating).
- Each distinct leak triggers exactly one `notify_admin()` mention (dedup verified via
  `_alerted_secret_fingerprints`); multiple distinct new findings discovered in the SAME scan
  cycle are batched into a single `notify_admin()` Telegram message, never one message per finding.
- The Telegram alert text and any log output contain only the pattern name and filename — never
  the matched secret value or its `preview` field.
- No new code path calls `execute_fix()` for a secret finding; `ALLOWED_FIX_ACTIONS` is unchanged.
- File I/O for log tailing is offloaded via `asyncio.to_thread` so the event loop is never blocked.

## Phase Completion Rules

This is a SIMPLE, single-phase plan — no multi-phase status tracking applies. The plan is
considered CODE DONE when all 6 Implementation Checklist items are applied to
`trading-app/workers/health_agent.py` and the Fully-Automated rows in Verification Evidence pass.
It is considered VERIFIED only after the Hybrid and Agent-Probe rows are also exercised against the
real on-disk log files and a user has confirmed the Telegram alert text is acceptable.

## Post-Phase Testing / Test Procedure

See `## Verification Evidence` above for the full per-scenario test matrix (Fully-Automated /
Hybrid / Agent-Probe strategies) and the "How to test without waiting an hour" note for the
isolated-scan test procedure. Context routing: `process/context/tests/all-tests.md` was consulted
during context discovery for this repo's test conventions (Python/pytest-style stdlib testing;
no dedicated test framework config was found for `trading-app/`, so verification uses ad-hoc
scratch scripts calling `scan_for_leaked_secrets()` directly, per the isolated-scan procedure
above). See also `process/context/all-context.md` for the wider repo context.

## Known Gaps (accepted for this SIMPLE plan)

- Dedup fingerprint set is in-memory/process-lifetime only — a service restart re-alerts previously
  seen leaks once. Acceptable: leaks are rare, low-volume events; a stronger persistent-dedup store
  is not warranted for this MVP.
- `.env` world-readable check does not re-alert on a clear-then-reoccur cycle (static fingerprint
  dedups it after the first alert regardless of intermediate state changes). Acceptable for MVP;
  documented, not silently dropped.
- Git-tracked `.env`/`*.db` re-leak check is explicitly deferred (see Non-Goals).
- If `health_monitor_worker()` takes the early `continue` inside the existing "1. Check Strategies"
  block (a strategy issue was just detected and already triggers its own `notify_admin()` alert),
  the new secret-scan step (placed after that block) is skipped for that single loop iteration.
  This is time-based and self-correcting — the throttle re-evaluates on the next ~60s tick — so no
  scan cycle is durably lost, only delayed by one iteration in the rare case both conditions
  coincide. Not fixed here to avoid restructuring the existing loop's control flow.

## Test Infra Improvement Notes

(none identified yet)

## Resume and Execution Handoff

1. **Selected plan file path:** `process/general-plans/active/secret-leak-monitor_04-07-26/secret-leak-monitor_PLAN_04-07-26.md`
2. **Last completed phase or step:** VALIDATE (this document) — validate-contract below.
3. **Validate-contract status:** written — see below.
4. **Supporting context files loaded:** `trading-app/workers/health_agent.py` (full read),
   `trading-app/state.py` (`broadcast_log` signature grep), `trading-app/app.py` (`HEALTH_AGENT_STATUS`
   consumer grep), on-disk log file listing under `trading-app/logs/` and `trading-app/app.log`,
   `process/context/all-context.md`.
5. **Next step for a fresh agent picking up mid-execution:** run `ENTER EXECUTE MODE` naming this
   exact plan file path, implementing checklist items 1–6 (including the two VALIDATE fixes —
   `import hashlib` and the batched Telegram alert) in `health_agent.py` only.

## Validate Contract

Status: PASS
Date: 04-07-26
date: 2026-07-04
generated-by: standalone

Parallel strategy: sequential
Rationale: Score 0/7 — single-file, read-only, no schema/auth/API/billing surface, no new
dependencies/agents/runtime surfaces, single clear direction. Auto-skip rule applies (trivial-scale
fan-out not warranted); ran as one sequential validate pass with a light two-layer check rather
than a heavy Layer-2 probe fan-out, per the task's explicit "keep the fan-out minimal" instruction.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| detect-6-patterns | Detects all 6 secret patterns in log tail | Fully-Automated | Plant fake key per pattern in temp file, monkeypatch `SECRET_SCAN_LOG_FILES`, call `scan_for_leaked_secrets()`, assert match | A |
| dedup-fingerprint | Same leak not re-alerted every cycle | Fully-Automated | Call scan twice with same planted secret; assert fingerprint present in `_alerted_secret_fingerprints` after first record | A |
| tail-only-read | Only last 64KB of file is scanned, not whole file | Fully-Automated | Oversized temp file, secret only in last 1KB, decoy secret beyond tail boundary; assert only near-end secret found | A |
| real-log-safety | Scan completes cleanly against real MB-sized log files | Hybrid — precondition: real log files exist on disk | Run `scan_for_leaked_secrets()` against real `SECRET_SCAN_LOG_FILES` paths, assert no exception | A |
| env-world-readable | `.env` world-readable check fires only when world-readable | Fully-Automated | `chmod 644` vs `chmod 600` on a test `.env`; call `_check_env_world_readable()`, assert finding only in 644 case | A |
| batched-alert | Burst of N distinct findings in one cycle sends exactly ONE Telegram message | Agent-Probe | Lower `SECRET_SCAN_INTERVAL_SECONDS` locally, plant 2+ distinct fake secrets, run wired-in block, assert one `notify_admin()` call listing all findings | A |
| no-auto-remediation | `ALLOWED_FIX_ACTIONS` unchanged; no `execute_fix()` call for a leak | Fully-Automated | `grep ALLOWED_FIX_ACTIONS` post-change == `{"restart_ws", "relogin", "clear_cache", "wait"}`; grep confirms no `execute_fix()` call near the leak wire-in | A |
| no-self-leak | Alert/log text never contains the matched secret or its preview | Fully-Automated | Grep the wired-in `notify_admin(...)` call to confirm it references only `pattern_name`/`os.path.basename(file)`, never `preview` or matched text | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

Legacy line form (retained so existing validate-contract consumers still parse):
- health_agent.py secret scan: [Fully-automated: isolated-script calls to `scan_for_leaked_secrets()` per Verification Evidence table] | [hybrid: run against real on-disk log files in `trading-app/logs/` + `trading-app/app.log` — precondition: files must exist, confirmed present] | [agent-probe: manual confirmation of batched Telegram alert text] | [known-gap: process-lifetime-only dedup persistence, documented above]

Dimension findings:
- Infra fit: PASS — target log files (`trading-app/logs/dashboard.log`, `fyersApi.log`,
  `fyersRequests.log`, `trading-app/app.log`) all exist on disk (confirmed via `ls`); `asyncio.to_thread`
  wrapping mirrors the existing pattern already used in `execute_fix`; `re`/`os`/`time`/`asyncio`/
  `datetime`/`IST` are already imported — only `hashlib` was missing (fixed in checklist item 1).
- Test coverage: PASS — full Fully-Automated/Hybrid/Agent-Probe tier table covers every claimed
  behavior; no developed behavior rests on Known-Gap alone (the only Known-Gap items are explicitly
  accepted design limitations — restart-reset dedup and env-flap re-alerting — not unproven claimed
  behaviors).
- Breaking changes: PASS — no public API/schema/auth changes; `HEALTH_AGENT_STATUS` dict gains two
  additive keys; confirmed via grep that its one external consumer (`trading-app/app.py:2601`)
  returns the dict verbatim and does not enumerate/validate specific keys.
- Security surface: PASS (after fix) — scanner is read-only (log tail + `os.stat` on `.env`), never
  writes to disk, computes a one-way hash fingerprint (truncated match text as hash input only,
  never as output), and the wired-in `notify_admin()` call now references only `pattern_name` +
  filename — the unused `preview` field is explicitly called out in checklist item 3 as never to be
  logged/alerted. `ALLOWED_FIX_ACTIONS` is confirmed unchanged and no new call reaches `execute_fix()`.

Open gaps: none blocking. Two mechanical gaps found during VALIDATE were fixed directly in the plan
checklist (see "[VALIDATE fix]" markers in Implementation Checklist items 1 and 5):
1. Missing `import hashlib` — added to checklist item 1.
2. Alert-batching gap (burst of findings would have fired one Telegram message per finding instead
   of one batched message per scan cycle) — fixed in checklist item 5's wire-in code.

What this coverage does NOT prove:
- Fully-automated rows (isolated scan calls) prove detection/dedup/tail-boundary/env-check logic in
  isolation — they do NOT prove the real `health_monitor_worker()` loop wiring behaves identically
  end-to-end (that requires the Hybrid + Agent-Probe rows against the live loop).
- The Hybrid row (real log files, no planted secrets) proves the scan does not crash or hang against
  real MB-sized files — it does NOT prove correct behavior when a real secret is actually present in
  production logs (that scenario is only tested with planted fakes).
- The Agent-Probe row (batched alert) is a manual/one-time confirmation, not a repeatable CI gate —
  a regression here would not be caught automatically on a future refactor.
- None of the gates prove Telegram delivery itself succeeds (network failure of the underlying
  `broadcast_log`/Telegram call is out of scope — pre-existing `notify_admin()` behavior, unchanged
  by this plan).

Gate: PASS (no FAILs, plan updated — 2 mechanical gaps found and fixed in this VALIDATE pass)
Accepted by: session (autonomous VALIDATE pass) — no CONCERN accepted as-is; both findings were
fixed in the plan text rather than accepted as gaps, so no unresolved item requires user acceptance.

## Autonomous Goal Block

SESSION GOAL: Add a throttled, read-only secret-leak scanner to the live-trading health agent's
self-healing loop, alerting the admin via existing Telegram path (`notify_admin()`); detect-only,
never auto-remediate.
Charter + umbrella plan: N/A — single plan (no phase program, no umbrella)
Autonomy: Standard RIPER-5 explicit-approval gate for EXECUTE. No standing /goal is active for this
session; EXECUTE still requires the user to say "ENTER EXECUTE MODE" for this plan.
Hard stop conditions / safety constraints:
- Never call `execute_fix()` or add `"leak"`/any new value to `ALLOWED_FIX_ACTIONS` — this feature
  is detect-and-alert only, never auto-remediation (Phase-2 hardening must not be weakened).
- Never read more than `SECRET_SCAN_TAIL_BYTES` (64KB) of any log file per cycle, and never run the
  scan more than once per `SECRET_SCAN_INTERVAL_SECONDS` (3600s) — this is a live real-money trading
  server; the health loop must never be blocked (`asyncio.to_thread` is mandatory for file I/O).
- Never let a matched secret value, or its `preview` field, reach a `logger` call or the Telegram
  message text — only `pattern_name` and filename may be surfaced.
- Only `trading-app/workers/health_agent.py` may be modified; no other file is in scope.
Next phase: EXECUTE — plan path:
`process/general-plans/active/secret-leak-monitor_04-07-26/secret-leak-monitor_PLAN_04-07-26.md`
Validate contract: inline in plan (see `## Validate Contract` above)
Execute start: Fully-automated gates listed above (isolated-script calls to
`scan_for_leaked_secrets()`) | Hybrid: run against real files in `trading-app/logs/` +
`trading-app/app.log` | Agent-probe: manual batched-alert confirmation | high-risk pack: no
(risk class is none of the 6 high-risk classes — monitoring/alerting addition, read-only I/O)
