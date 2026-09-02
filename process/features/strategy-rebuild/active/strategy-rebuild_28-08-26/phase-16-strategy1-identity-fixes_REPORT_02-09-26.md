---
name: report:strategy-rebuild-phase-16-strategy1-identity-fixes
description: "strategy-rebuild Phase 16 EXECUTE report — extracted _strat1_attempt_trade(), fixed Strategy 1's bare-string daily-cap bypass and the execute_auto_trade() substring collision with Strategy 10/11; 8 new tests green"
date: 02-09-26
phase: phase-16
status: COMPLETE
feature: strategy-rebuild
plan: process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-16-strategy1-identity-fixes_PLAN_02-09-26.md
metadata:
  node_type: memory
  type: report
  feature: strategy-rebuild
  phase: phase-16
---

# Phase 16 — EXECUTE Report (Strategy 1 Identity Fixes)

**TL;DR** — Both bugs fixed exactly as planned, plus the planned behavior-preserving extraction.
8 new tests, all green. One pre-existing unrelated test failure (`test_atr_sl_field_separation`)
was already failing at HEAD and is out of this phase's scope. Not committed — awaiting EVL.

---

## What Was Done

### Step A — Pre-EXECUTE re-verification (all confirmed from live source, no drift)
- **A1** — `state.can_trade("Strategy 1", ...)` confirmed at `auto_trader.py:2153`;
  `propose_trade("Strategy 1: OB + FVG", ...)` at `:2165`. Exactly as the plan stated.
- **A2** — `if "Strategy 1" in strategy_name:` confirmed at `auto_trader.py:1190`.
- **A3** — Coverage baseline confirmed: `run_strat_1` appears at exactly two places
  (`async def` at 2124, one `asyncio.gather` call site at 2323) — no other reference, so the
  delegator refactor is safe. `test_strategy1_daily_cap` (`test_trading_core.py:86`) is the only
  related existing test, and it calls `can_trade()` **directly** with a hand-typed
  `"Strategy 1: OB + FVG"` — confirming RESEARCH finding 3. No existing test exercised
  `run_strat_1()` or `execute_auto_trade()`'s directional guard.

### Step B — Fixes
- **B1 — extraction + Bug 1 fix.** New module-level `async def _strat1_attempt_trade(state,
  client, symbol, analysis)` at `auto_trader.py:207`, placed directly after
  `_strat3_orb_window_ok()` alongside the file's other `_strat*` helpers. Body is a verbatim
  relocation of `run_strat_1()`'s former 2124-2166 block — every guard, the signals loop, the
  trend/confidence/AI-veto checks, the `can_trade()` call and the `propose_trade()` call, in the
  same order with the same variable names. `risk_orchestrator` is referenced directly (already a
  module-level import at `:39`), not threaded as a parameter, per the plan.
  Bug 1's fix applied inside it: a single hoisted local `strat_name = "Strategy 1: OB + FVG"` now
  feeds **all three** places the name is used — the `active_strategies` membership check, the
  `can_trade()` gate (was a bare `"Strategy 1"`), and the `propose_trade()` call. The
  two-independent-literals structure is gone.
  `run_strat_1()` is now a one-line delegator: `await _strat1_attempt_trade(state, client, symbol,
  analysis)`. The `asyncio.gather(...)` call site was not touched (same zero-arg call, same
  position in the gather list).
- **B2 — Bug 2 fix.** `auto_trader.py:1246` (was 1190): `if "Strategy 1" in strategy_name:` →
  `if strategy_name.split(":")[0].strip() == "Strategy 1":`, with an explanatory comment. No other
  logic inside the guard block was touched.
- **B3 — pattern-elimination greps.** Both `can_trade("Strategy 1"` and `"Strategy 1" in
  strategy_name` return **zero matches**. `_strat1_attempt_trade` and `run_strat_1` both exist; no
  duplicated trade-attempt logic anywhere.

### Step C — Tests (`trading-app/tests/test_auto_trader.py`, +8 tests)
All call the **real production code**, not synthetic strings:
| Test | Proves |
|---|---|
| `test_strat1_passes_full_name_to_can_trade` | The **actual** argument reaching `can_trade()` is `"Strategy 1: OB + FVG"` — captured by wrapping the **real** `can_trade()` (not mocked), so a regression to a bare string fails the test |
| `test_strat1_daily_cap_blocks_at_real_call_site` | With `strat_1_trades_today == STRAT_1_MAX_TRADES_PER_DAY`, the real `can_trade()` gate blocks and `propose_trade` is NOT called (before the fix it was) |
| `test_strat1_skips_mcx_and_cds` | Extraction integrity — the MCX/CDS guard moved with the body |
| `test_strat1_skips_when_strategy_disabled` | Extraction integrity — the `active_strategies` gate |
| `test_directional_guard_does_not_fire_for_strategy_10_and_11` (parametrized ×2) | Strategy 10/11-shaped `sig` dicts (PUT in a BULLISH trend) are no longer misidentified as Strategy 1 |
| `test_directional_guard_still_fires_for_real_strategy_1` | No false-negative — a genuine Strategy 1 PUT-in-BULL is still blocked |
| `test_directional_guard_allows_aligned_strategy_1` | A genuine Strategy 1 CALL-in-BULL still passes the guard |

**Bug 2 test mechanics:** `execute_auto_trade()`'s Strategy 1 branch has no observable effect other
than a bare `return`, so the tests use `api_queue.enqueue` — the first call made *after* the guard —
as the sentinel. Guard fired ⇒ never reached; guard skipped ⇒ reached. `get_user_state` and
`api_queue` are monkeypatched on the `workers.auto_trader` module object, matching the existing
`test_per_user_isolation` pattern.

**C3 — `test_strategy1_daily_cap` disposition: KEPT, with an explicit scope docstring added.**
Rationale: it is still a legitimate unit test of `can_trade()`'s *own* cap logic (including the
"Strategy 3 is not blocked by Strategy 1's counter" assertion), which nothing else covers. It was
never wrong — it was *insufficient*, because it hand-types the name and therefore proves nothing
about the production call site. Deleting it would lose real gate coverage; leaving it silent would
let it keep looking like proof the cap enforces. The added docstring states exactly what it does and
does not prove and names the two new real-call-site tests that now carry that burden.

---

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| compile-clean | `python3 -m py_compile trading-app/workers/auto_trader.py` | **PASS** (exit 0) |
| pattern-elimination | `grep -n 'can_trade("Strategy 1"' …` / `grep -n '"Strategy 1" in strategy_name' …` | **PASS** — zero matches for both |
| extraction-integrity | `grep -n 'async def _strat1_attempt_trade\|async def run_strat_1'` + diff-region review | **PASS** — both exist; diff confirms verbatim 1:1 relocation, only the two literal→variable substitutions |
| bug1-cap-fix | `pytest -q test_trading_core.py test_auto_trader.py` | **PASS** — both Bug 1 tests green |
| bug2-collision-fix | same run | **PASS** — all 4 Bug 2 tests green |
| scope-confined | `git diff --stat` | **PASS** — code changes limited to `auto_trader.py` + `test_auto_trader.py` + `test_trading_core.py` (all declared Blast Radius) |
| legacy-test-disposition (Agent-Probe) | this report | **PASS** — disposition recorded above (KEPT + scope docstring) |

**Suite result: 47 passed, 1 failed.** All 8 new tests pass.

---

## ⚠️ BEHAVIOR CHANGE CALLOUT (record verbatim — do not drop)

**Bug 1's fix is a live BEHAVIOR CHANGE, not a silent bug fix.** Strategy 1's daily 2-trade cap
will actually enforce **for the first time in production** once this ships. Until now the bare
`"Strategy 1"` string never matched `automation.py:733`'s `.startswith("Strategy 1:")` gate, so the
cap was dead code on this path and Strategy 1 traded uncapped.

**Strategy 1's trade volume may visibly drop after deploy. That is EXPECTED and INTENDED, not a new
bug.** It matches the strategy's own documented design — `automation.py`'s own comment: *"Backtest
showed 2/day + confluence-only + breakeven-trail was the best risk-adjusted configuration; more
trades/day degraded drawdown sharply"* (Variant L). Do not let a future session mistake the volume
drop for a regression and "fix" it by removing the cap.

---

## Plan Deviations

None. Both fixes and the extraction were implemented exactly as the plan's Steps A/B/C and the
Testability Extraction section specify. The FALLBACK option (driving `automation_loop()` with
`app.get_analysis` patched) was not needed — Step A3 confirmed `run_strat_1` has no other reference,
so the extraction was safe as predicted.

One implementation detail worth naming (within blast radius, no behavior change): the hoisted
`strat_name` is also used for the `active_strategies` membership check, which previously used its own
third copy of the same literal. Same value, same outcome — it simply removes one more drift surface
than the plan's minimum.

---

## Test Infra Gaps Found

1. **PRE-EXISTING FAILURE, out of scope: `test_auto_trader.py::test_atr_sl_field_separation`.**
   It asserts `'t["trailing_sl_price"] = new_sl' in src`. That string is absent from
   `auto_trader.py` **at HEAD as well as after this phase's edits** (verified:
   `git show HEAD:trading-app/workers/auto_trader.py | grep -c 'trailing_sl_price"] = new_sl'` → 0).
   This phase touched nothing in the trailing-SL path. The test is stale relative to some earlier
   refactor of the ATR-trail code — either the field was renamed or the assertion was never updated.
   **Not fixed here** (outside this phase's Blast Radius; fixing it requires deciding whether the
   test or the production code is wrong, which is a separate investigation). Recommend a backlog
   note at UPDATE PROCESS.
2. `execute_auto_trade()`'s directional-consistency guard is only observable via side-effect
   (bare `return`, no logging on mismatch — unlike every other gate in that function, which logs).
   The new tests work around this with an `api_queue.enqueue` sentinel. Adding a `logger.info` on
   the Strategy-1 guard's mismatch returns would make it directly observable and match the
   surrounding code's conventions — deliberately **not** done here (the plan forbids touching other
   logic inside the guard block). Candidate backlog item.

---

## Open Questions Carried Forward (unchanged — require user sign-off)

1. **Should Strategy 1 have a directional-consistency guard at all?** Not decided by this phase;
   this phase only makes the existing guard identify Strategy 1 correctly.
2. **Shared cross-file helper for the exact-match-on-split pattern** — now hand-written independently
   in three places (`automation.py`, `risk_orchestrator.py`, `auto_trader.py`). Deferred as scope
   creep; candidate backlog item.

---

## Files Touched

| File | Change |
|---|---|
| `trading-app/workers/auto_trader.py` | New module-level `_strat1_attempt_trade()` (+56 lines, verbatim relocation + `strat_name` hoist); `run_strat_1()` collapsed to a 1-line delegator (−43 lines); Bug 2 exact-match-on-split at the directional guard |
| `trading-app/tests/test_auto_trader.py` | +8 tests + fixtures/helpers for Phase 16 (+200 lines) |
| `trading-app/tests/test_trading_core.py` | `test_strategy1_daily_cap` — scope docstring added (C3 disposition); no assertion changed |

Not committed. No push.

---

## Closeout Packet

- **Selected plan:** `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-16-strategy1-identity-fixes_PLAN_02-09-26.md`
- **Finished:** Steps A1–A3, B1–B3, C1–C4 — all checklist items complete.
- **Verified:** py_compile, both pattern-elimination greps, extraction-integrity grep + diff review,
  8 new real-call-path tests, `git diff --stat` scope check.
- **Still unverified:** live production behavior (post-deploy Strategy 1 volume drop) — a live
  observation for UPDATE PROCESS closeout, not a pre-merge gate, per the validate-contract's own
  "What this coverage does NOT prove" section.
- **Remaining:** independent EVL confirmation run; commit; UPDATE PROCESS (archive, umbrella
  `## Current Execution State` update, backlog notes for the two Test Infra Gaps above).
- **Classification:** `Keep in active/testing` — implementation is complete and internally green,
  but EVL confirmation and commit have not run.

---

## Forward Preview

- **Test Infra Found:** `test_atr_sl_field_separation` is stale and red at HEAD — any future phase
  running the full `test_auto_trader.py` will see 1 pre-existing failure and should not attribute it
  to its own changes. `pytest.ini` has `asyncio_mode = auto`; the redirected-to-file poll-and-kill
  pytest pattern works reliably (~3s runtime for these two files).
- **Blast Radius Changes:** `auto_trader.py` gained one new module-level symbol,
  `_strat1_attempt_trade(state, client, symbol, analysis)` — internal, underscore-prefixed, not
  imported by any other module. Line numbers below ~207 in `auto_trader.py` have shifted by ~+56;
  **do not trust cached line numbers from Phases 1-15 for this file.**
- **Commands to Stay Green:**
  `python3 -m py_compile trading-app/workers/auto_trader.py` and
  `cd trading-app/tests && (python3 -m pytest -q test_trading_core.py test_auto_trader.py > /tmp/p16.log 2>&1 &) ; sleep 20 && cat /tmp/p16.log`
- **Dependency Changes:** none. No new imports, no new packages, no schema change.
