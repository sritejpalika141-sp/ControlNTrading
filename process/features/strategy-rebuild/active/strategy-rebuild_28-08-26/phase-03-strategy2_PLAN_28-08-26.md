---
name: plan:strategy-rebuild-phase-03-strategy2
description: "Strategy Rebuild — Phase 03: Strategy 2 — Audit"
date: 28-08-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: phase-03
---

# Phase 03 — Strategy 2 — Audit

**Program:** strategy-rebuild
**Umbrella plan:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
**Phase status:** ⏳ PLANNED (RESEARCH + INNOVATE complete; PLAN-SUPPLEMENT complete — see below)
**Report destination:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-03-strategy2_REPORT_{dd-mm-yy}.md (flat in the program task folder)
**Date**: 31-08-26
**Status**: PLANNED
**Complexity**: SIMPLE (audit + regression-test-only phase; no behavior/signature change)

---

## Overview

This is one direct phase plan within the `strategy-rebuild` phase program (see umbrella plan
above for program-level context). Scope, decisions, and full checklist are below.

---

## Purpose

Audit-only pass on Strategy 2 ("9:26 - 180 Buy", active strategy, Tier 2) to confirm entry/exit/SL
logic is correct. **RESEARCH found no live bug.** This phase now adds regression test coverage
(currently zero) plus one trivial docstring correction — no behavior or signature change to the
live strategy function.

---

## RESEARCH Findings (integrated)

Fresh re-verification of `trading-app/engine/strategy_926.py` (276 lines) confirms:

1. **Duplicate-function shadowing bug — CONFIRMED FIXED.** The historical bug (an empty duplicate
   `async def _find_180_strikes(client):` later in the file silently shadowing the real
   implementation, per the in-file `NOTE` comment at lines 272-276) is gone. Only one definition of
   `_find_180_strikes` exists in the file today (line ~163).
2. **Phantom-expiry bug — CONFIRMED FIXED.** `_find_180_strikes` calls
   `client.find_nearest_expiry(spot)` and uses the real `expiry['code']` to build option symbols;
   no hardcoded or stale expiry path remains.
3. **Shared execution gate stack — CONFIRMED, no bypass.** Strategy 2 returns a plain signal dict
   from `evaluate_926_strategy()` like every other strategy; it goes through the same downstream
   `auto_trader.py` `execute_auto_trade()` gate stack (chase/fade checks, SL/TSL lock, order
   concurrency, directional-regime gate) as all other strategies. No strategy-specific bypass found.
4. **Stale docstring (non-functional).** The module docstring / function docstring implies
   `current_trend` blocks entry on NEUTRAL trend ("Strictly aligns with the market trend. Blocks
   entirely if NEUTRAL."), but `current_trend` is an accepted parameter that is **never read** in
   the function body (grep confirms no other reference to `current_trend` after the signature).
   This is **not a functional gap**: the SHARED downstream directional-regime gate in
   `auto_trader.py`'s `execute_auto_trade()` already enforces trend alignment for every strategy,
   Strategy 2 included. Fix: correct the docstring wording only. Do NOT remove the unused
   parameter (removing it would be a signature change, out of audit scope, and risks an unrelated
   call-site break with no functional benefit).
5. **Zero test coverage** exists for `trading-app/engine/strategy_926.py` today (confirmed:
   `trading-app/tests/` has no `test_strategy_926.py` or similar file referencing this module).

## INNOVATE Decision (integrated)

**Chosen approach: Approach 1 — regression tests only.** No behavior/signature change to the live
strategy function. Add `trading-app/tests/test_strategy_926.py` covering the 6 scenarios below,
plus the trivial docstring correction. Rejected alternatives: (a) removing the unused
`current_trend` parameter — rejected, would widen scope beyond audit and risks call-site breakage
for zero functional gain since the shared gate already covers trend enforcement; (b) doing nothing
(no test file) — rejected, zero test coverage on a live-money strategy function is an unacceptable
residual gap for a program whose exit bar requires regression protection.

---

## Entry Gate

- Phase 2 complete (validated, committed)

---

## Blast Radius

- `trading-app/engine/strategy_926.py` — docstring-only edit (function `evaluate_926_strategy`,
  lines ~30-38); **no functional/logic/signature change**
- `trading-app/tests/test_strategy_926.py` — new file (regression tests only)

Confirmed via fresh RESEARCH re-verification — no other files touched.

---

## Implementation Checklist

### Step A — Docstring correction (trivial, bundled fix)

- [x] A1. In `trading-app/engine/strategy_926.py`, edit the `evaluate_926_strategy` docstring
      (currently reads: `"Strictly aligns with the market trend. Blocks entirely if NEUTRAL."`).
      Replace with wording that states: this function's own `current_trend` parameter is accepted
      but not evaluated in the function body; trend/directional-regime alignment for this strategy
      (as for every strategy) is enforced downstream by the shared gate stack in
      `auto_trader.py`'s `execute_auto_trade()`. Do NOT remove or rename the `current_trend`
      parameter — signature must stay identical (`async def evaluate_926_strategy(client, state,
      current_trend="NEUTRAL", now=None):`).
- [x] A2. `python3 -m py_compile trading-app/engine/strategy_926.py` — confirm exit 0, no output.

### Step B — New regression test file

- [x] B1. Create `trading-app/tests/test_strategy_926.py`. Follow the exact mocking/import style of
      `trading-app/tests/test_anti_chase_fade.py` and `trading-app/tests/test_smart_sl_3candle.py`:
      - `os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")` at top
      - `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` at top
      - `from unittest.mock import AsyncMock, MagicMock, patch`
      - import target: `from engine.strategy_926 import evaluate_926_strategy, _find_180_strikes`
      - mock `client.get_quotes` (sync method called via `asyncio.to_thread`, so mock it as a plain
        `MagicMock` callable returning a dict, NOT `AsyncMock` — `asyncio.to_thread` wraps a sync
        callable) and `client.find_nearest_expiry` (also sync, called via `asyncio.to_thread`)
      - build a minimal fake `state` object (a simple object or `SimpleNamespace`/`MagicMock` with
        `active_strategies = ["Strategy 2: 9:26 - 180 Buy"]` and default falsy
        `strat_926_triggered` / `strat_926_strikes` / `strat_926_expired` attributes via
        `getattr(state, attr, default)` semantics already used by the strategy — a plain object
        with only `active_strategies` set, plus `trade_lots = 1`, is sufficient since the strategy
        code uses `getattr(state, ..., default)` throughout)
      - no live Fyers dependency; no network calls
- [x] B2. **Test 1 — entry-window enforcement.** Call `evaluate_926_strategy(client, state,
      now=<fixed IST datetime>)` with `now` before 09:26:00 → assert returns `None` (no selection
      attempted, no `client.get_quotes` call needed for spot). Call with `now` after 09:40:00 →
      assert returns `None` and `state.strat_926_expired` is set `True`. (Use the `now=` injectable
      param already supported by the function — no monkeypatching of `datetime.now` needed.)
- [x] B3. **Test 2 — one-trade-per-day cap.** Set `state.strat_926_triggered = True` before calling
      `evaluate_926_strategy` with `now` inside the 09:26-09:40 window → assert returns `None`
      immediately (confirms the early-return guard at step 2 of the function fires regardless of
      strike/quote state).
- [x] B4. **Test 3 — arm-then-recover crossover trigger logic.** Pre-seed
      `state.strat_926_strikes = {"ce": {"symbol": "NSE:NIFTYXXXXXCE", "ltp": 0, "strike": 24000},
      "pe": None, "_entry_price": 180.0, "_arming_threshold": 178.2, "_sl_points": 27.0,
      "_target_points": 54.0}` to skip the selection phase. Mock `client.get_quotes` to return, on
      first call, an LTP below `_arming_threshold` (e.g. 175.0) — call `evaluate_926_strategy` with
      `now` in-window, assert returns `None` and the strike's `armed` flag becomes `True` (arms but
      does not trigger). Then mock `client.get_quotes` to return an LTP at/above `_entry_price`
      (e.g. 180.5) on the strike info that is now armed (reuse the same `state.strat_926_strikes`
      dict across the two calls since the function mutates `strike_info['armed']` in place) — call
      again, assert a signal dict is returned with `side == "BUY"`, `type == "CALL"`,
      `entry_price == 180.5`, and `state.strat_926_triggered` becomes `True`. Also assert a direct
      jump (LTP never dips below arming, straight to/above entry on the very first tick with
      `armed` still `False`) does NOT trigger (returns `None` for that tick) — proves the
      arm-then-recover ordering is enforced, not a bare threshold check.
- [x] B5. **Test 4 — ATM-based SL/target sizing math.** Directly assert the arithmetic path inside
      `_find_180_strikes`'s ATM-branch (lines ~218-224): given a mocked `atm_premium` scenario
      (mock `client.get_quotes` to return `lp` values for the ATM CE+PE symbols such that
      `atm_premium = (atm_ce_ltp + atm_pe_ltp) / 2`), assert the returned dict's `_sl_points ==
      round(atm_premium * 0.15, 1)` (~15%) and `_target_points == round(atm_premium * 0.30, 1)`
      (~30%), and `_entry_price == round(atm_premium * 0.95, 1)` / `_arming_threshold ==
      round(_entry_price * 0.99, 1)`. Mock `client.find_nearest_expiry` to return a fixed
      `{"code": "26SEP", "date": "2026-09-30"}`-shaped dict (match whatever field names
      `find_nearest_expiry`'s real return contract uses — confirm via a quick grep of
      `fyers_client.py`'s `find_nearest_expiry` before writing the mock's return shape) and mock
      `client.get_quotes` to return valid `lp` values for the constructed ATM/CE/PE symbol strings
      so `_find_180_strikes` reaches the ATM branch instead of the fallback branch.
- [x] B6. **Test 5 — zero-ATM-premium fallback path.** Same `_find_180_strikes` call, but mock
      `client.get_quotes` so both `atm_ce_ltp` and `atm_pe_ltp` resolve to `0` (ATM branch's `if
      atm_premium > 0` is False) → assert the function falls back to the hardcoded module constants
      (`ENTRY_PRICE`, `SELECTION_MIN`, `SELECTION_MAX`, `ARMING_THRESHOLD`, `SL_POINTS`,
      `TARGET_POINTS` as defined at the top of `strategy_926.py`) by asserting the returned
      `_entry_price == ENTRY_PRICE`, `_sl_points == SL_POINTS`, `_target_points == TARGET_POINTS`
      when a CE or PE candidate happens to fall inside the fallback `SELECTION_MIN`-`SELECTION_MAX`
      range in the mocked quotes.
- [x] B7. **Test 6 — duplicate-definition regression guard.** Read the source file
      (`inspect.getsource` on the imported module, or a plain `open(...).read()` of
      `engine/strategy_926.py`) and assert the substring `"async def _find_180_strikes"` occurs
      exactly once (`.count(...) == 1`) — directly catches recurrence of the historical
      duplicate-function shadowing bug class. Also call `_find_180_strikes(client)` with a fully
      valid mocked `client` (mocked `get_quotes` + `find_nearest_expiry` returning a plausible
      strike) and assert the return value is not `None` — confirms the live (non-shadowed)
      implementation is actually reachable and returns a real result end-to-end.
- [x] B8. Run the full new test file in isolation first:
      `cd trading-app/tests && python3 -m pytest test_strategy_926.py -v` — confirm all 6 scenarios
      (B2-B7 across their sub-assertions) pass green before running the full scoped suite.

### Step C — Full scoped regression run

- [x] C1. Run the scoped pytest command per the umbrella's documented workaround (root cause: root-
      level diagnostic scripts break bare `pytest .` / `pytest trading-app/` collection — do NOT use
      either of those forms):
      `cd trading-app/tests && python3 -m pytest -q`
      Confirm no new failures introduced anywhere in the suite by the docstring edit or the new
      test file (docstring edit is comment-only so zero behavioral risk to other tests; new test
      file must not collide with any existing fixture/name).

---

## Acceptance Criteria

- `trading-app/engine/strategy_926.py` docstring corrected with zero functional/signature change
- `trading-app/tests/test_strategy_926.py` created, covering all 6 scenarios in the Implementation
  Checklist (Step B), and passing green in isolation and inside the full scoped suite
- No regression introduced in the existing `trading-app/tests/` scoped suite

## Phase Completion Rules

This phase is `CODE DONE` when Steps A-C of the Implementation Checklist are all checked and the
Exit Gate commands below pass. It is `VERIFIED` only after EVL (Phase Loop Progress Step 6)
independently re-confirms the same gate commands green and UPDATE PROCESS (Step 7) archives the
phase report and commits. Do not mark this phase `✅ VERIFIED` on EXECUTE's self-report alone.

## Exit Gate

```bash
# Compile check — scoped to the one touched file
python3 -m py_compile trading-app/engine/strategy_926.py
# Expected: exit 0, no output

# New regression test file, isolated
cd trading-app/tests && python3 -m pytest test_strategy_926.py -v
# Expected: all tests pass (exit 0)

# Full scoped suite (per umbrella's documented pytest-collection workaround —
# NOT bare `pytest .` or `pytest trading-app/`)
cd trading-app/tests && python3 -m pytest -q
# Expected: exit 0, no new failures vs pre-phase baseline
```

- All checklist items (A1-A2, B1-B8, C1) checked
- py_compile clean on the touched file
- `test_strategy_926.py` passes in isolation and as part of the full scoped suite
- No pre-existing test in the scoped suite regresses
- Docstring correction reviewed to confirm zero functional/signature change
- Phase report written to report destination above, including the RESEARCH "no bug found" verdict
  and the specific fixed-bug confirmations (duplicate shadowing, phantom expiry)

---

## Blockers That Would Justify BLOCKED Status

- Phase 02 exit gate not yet passed (strictly sequential program — this phase cannot start early)
- `find_nearest_expiry`'s actual return-value contract (field names) cannot be confirmed from
  `fyers_client.py` without ambiguity — would block writing an accurate mock in Test 4 (B5); resolve
  by reading `fyers_client.py`'s `find_nearest_expiry` implementation during EXECUTE before writing
  that specific mock
- The full scoped suite (`cd trading-app/tests && python3 -m pytest -q`) reveals a pre-existing
  regression unrelated to this phase's changes — do not silently absorb; document as a
  known-gap/backlog note and confirm it predates this phase's edits via `git stash` + re-run

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase report read; test context loaded; fresh audit of
      this strategy's current code completed (Blast Radius re-verified — confirmed correct, both
      historical bugs confirmed fixed, stale docstring found, zero test coverage found)
- [x] 2. INNOVATE — innovate-agent: approach decided (Approach 1 — regression tests + docstring
      fix only, no behavior/signature change); Decision Summary written
- [x] 3. PLAN-SUPPLEMENT — plan-agent: this stub fleshed out into a full checklist with concrete
      file paths, test scenarios, and mocking guidance
- [x] 4. PVL — vc-validate-agent: full V1-V7 complete; validate-contract written, Gate: PASS
      (31-08-26)
- [x] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- `trading-app/engine/strategy_926.py` (docstring-only edit)
- `trading-app/tests/test_strategy_926.py` (new file)

---

## Public Contracts

- No external API surface change. `evaluate_926_strategy`'s signature is unchanged
  (`client, state, current_trend="NEUTRAL", now=None`); only its docstring text changes.
- No behavior change to signal generation, entry/exit/SL/target math, or the one-trade-per-day cap.
- Shared downstream gate stack (`auto_trader.py` `execute_auto_trade()`) is untouched by this phase.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `python3 -m py_compile trading-app/engine/strategy_926.py` | Fully-Automated | Docstring edit introduces no syntax/compile error |
| `test_strategy_926.py::test_entry_window_enforcement` (Test 1, B2) | Fully-Automated | Strategy only fires within 09:26-09:40 window; correctly sets expired flag after 09:40 |
| `test_strategy_926.py::test_one_trade_per_day_cap` (Test 2, B3) | Fully-Automated | `strat_926_triggered` guard blocks all further signals same-day |
| `test_strategy_926.py::test_arm_then_recover_crossover` (Test 3, B4) | Fully-Automated | Crossover requires arm (dip below threshold) THEN recover (cross back above entry) — not a bare threshold check |
| `test_strategy_926.py::test_atm_based_sl_target_sizing` (Test 4, B5) | Fully-Automated | SL ≈15% / target ≈30% of ATM premium, entry ≈95%, arming ≈99% of entry — matches documented dynamic-sizing formula |
| `test_strategy_926.py::test_zero_atm_premium_fallback` (Test 5, B6) | Fully-Automated | When ATM premium unavailable, strategy correctly falls back to hardcoded module constants |
| `test_strategy_926.py::test_no_duplicate_find_180_strikes_definition` (Test 6, B7) | Fully-Automated | Regression guard against recurrence of the historical duplicate-function-shadowing bug class; confirms live implementation is reachable and functional |
| `cd trading-app/tests && python3 -m pytest -q` (full scoped suite) | Fully-Automated | Docstring edit + new test file introduce zero regressions elsewhere in the suite |
| Fresh RESEARCH-phase audit read of entry/exit/SL logic (already completed) | Agent-Probe | Confirms no further structural issues beyond the docstring finding — completed this session |

```bash
# Verification command — run after phase complete
git log --oneline -1 -- trading-app/engine/strategy_926.py trading-app/tests/test_strategy_926.py
# Expected: shows this phase's commit
```

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-03-strategy2_PLAN_28-08-26.md`
- Last completed step: PLAN-SUPPLEMENT (Step 3) — RESEARCH and INNOVATE findings fully integrated
  into the checklist above
- Validate-contract status: pending — Step 4 (PVL) not yet run
- Supporting context files loaded this session: `trading-app/engine/strategy_926.py` (full file),
  `trading-app/tests/test_smart_sl_3candle.py` and `trading-app/tests/test_anti_chase_fade.py`
  (mocking-style references)
- Next step: Spawn vc-validate-agent for PVL (Step 4). Note for EXECUTE: before writing Test 4
  (B5)'s mock for `find_nearest_expiry`, confirm the real return-shape by reading
  `fyers_client.py`'s `find_nearest_expiry` implementation — do not assume field names from this
  plan alone.

---

## Test Infra Improvement Notes

- Zero test coverage existed for `trading-app/engine/strategy_926.py` prior to this phase — this
  phase closes that specific gap. No broader test-infra tooling gap identified (existing
  `unittest.mock` + `pytest` patterns in `test_anti_chase_fade.py` / `test_smart_sl_3candle.py`
  were sufficient to write full coverage without new fixtures or infra).

---

## Inner Loop Refresh Note: 2026-08-31 — changed sections: Purpose, Blast Radius, Implementation Checklist, Exit Gate, Blockers, Touchpoints, Public Contracts, Verification Evidence, Resume and Execution Handoff, Test Infra Improvement Notes. Invalidates prior validate-contract.

---

## Validate Contract

Status: PASS
Date: 31-08-26
date: 2026-08-31
generated-by: inner-pvl: phase-3

Parallel strategy: sequential
Rationale: Score 1/7 (S4 phase-program classification only — this is a single already-scoped
inner-PVL phase, not cross-phase creation/validate fan-out, so the Phase Program Rule's
agent-team requirement does not apply). No multi-package scope, no schema/API/auth surface, one
decided approach (no 3+ directions), no high-risk class, only 2 files in blast radius. Auto-skip
rule applies: single small-scope change → sequential, no fan-out mentioned. All 4 Layer-1
dimension checks (infra fit, test coverage, breaking changes, security surface) were performed
directly in this V2 pass against the real source files rather than via parallel dimension
subagents — appropriate given the LOW score and because this tool context has no Agent-spawn
access (Read/Grep/Glob/Bash/Write only). EXECUTE-phase recommendation: also sequential — one
vc-execute-agent (opus), single pass through Steps A→B→C (docstring edit, new test file, 3 gate
commands); no independent workstreams to parallelize.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| A2 | Docstring edit introduces no syntax/compile error | Fully-Automated | `python3 -m py_compile trading-app/engine/strategy_926.py` | A |
| B2 | Strategy fires only within 09:26–09:40 window; sets expired flag after 09:40 | Fully-Automated | `test_strategy_926.py::test_entry_window_enforcement` | B |
| B3 | `strat_926_triggered` guard blocks all further signals same-day | Fully-Automated | `test_strategy_926.py::test_one_trade_per_day_cap` | B |
| B4 | Crossover requires arm (dip below threshold) THEN recover (cross back above entry) — not a bare threshold check | Fully-Automated | `test_strategy_926.py::test_arm_then_recover_crossover` | B |
| B5 | SL ≈15% / target ≈30% of ATM premium, entry ≈95%, arming ≈99% of entry | Fully-Automated | `test_strategy_926.py::test_atm_based_sl_target_sizing` | B |
| B6 | When ATM premium unavailable, strategy falls back to hardcoded module constants | Fully-Automated | `test_strategy_926.py::test_zero_atm_premium_fallback` | B |
| B7 | Regression guard against recurrence of the historical duplicate-function-shadowing bug; live implementation reachable | Fully-Automated | `test_strategy_926.py::test_no_duplicate_find_180_strikes_definition` | B |
| C1 | Docstring edit + new test file introduce zero regressions elsewhere in the scoped suite | Fully-Automated | `cd trading-app/tests && python3 -m pytest -q` | A |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: all rows above use only the 3 proving strategies (Fully-Automated). No
Known-Gap row — every developed behavior in this phase's blast radius has a Fully-Automated gate
(net-gate vacuous-green check: PASS, no behavior rests on Known-Gap alone).

Legacy line form (retained so existing validate-contract consumers still parse):
- strategy_926.py docstring: Fully-automated: `python3 -m py_compile trading-app/engine/strategy_926.py`
- strategy_926.py regression coverage: Fully-automated: `cd trading-app/tests && python3 -m pytest test_strategy_926.py -v`
- full scoped suite: Fully-automated: `cd trading-app/tests && python3 -m pytest -q`

Dimension findings:
- Infra fit: PASS — no new dependencies, agents, or runtime surfaces. Follows the exact
  `unittest.mock`/pytest pattern already used by `test_anti_chase_fade.py` and
  `test_smart_sl_3candle.py`; `os.environ.setdefault("SECRET_KEY", ...)` and `sys.path.insert(...)`
  boilerplate match sibling test files exactly.
- Test coverage: PASS — mocking approach independently verified viable against the REAL function
  signatures (see "Verified during V2" below); one implementation-detail note surfaced for EXECUTE
  (not a blocking concern — see Open gaps).
- Breaking changes: PASS — confirmed via grep that `current_trend` (the parameter whose docstring
  wording changes) appears ONLY in the `evaluate_926_strategy` signature (line 31) and is never
  read anywhere else in the function body — the docstring edit is proven zero-functional-impact,
  not just claimed. Confirmed 3 real call sites of `evaluate_926_strategy`
  (`trading-app/app.py:112` import, `trading-app/workers/auto_trader.py:1995`,
  `trading-app/engine/backtest_runner.py:105`) — none are affected since the signature string is
  unchanged (docstring-only edit). No other file references `_find_180_strikes`.
- Security surface: PASS — no auth, secrets, schema, billing, or API-contract surface touched;
  test file uses only the existing placeholder-secret pattern already established in sibling
  tests, no live credentials or network calls.

Verified during V2 (per orchestrator's explicit request):
1. **Mocking approach viability — CONFIRMED VIABLE.** Read `trading-app/engine/strategy_926.py`
   directly: `client.get_quotes` (line 103, 167, 195) and `client.find_nearest_expiry` (line 174)
   are both called via `await asyncio.to_thread(client.<method>, ...)` — confirming the plan's
   instruction to mock them as plain sync `MagicMock` callables (not `AsyncMock`) is correct.
   Read `trading-app/fyers_client.py`'s real `find_nearest_expiry` (line 1331) and
   `_nearest_real_expiry` (line 1274): confirmed the real return shape is a dict with `code` and
   `date` keys (docstring at line 1282 states "Code format matches Fyers' own option symbols") —
   this exactly matches the plan's assumed mock shape `{"code": "26SEP", "date": "2026-09-30"}`.
   The plan's own flagged open item ("confirm find_nearest_expiry's real return-shape before
   writing the Test 4 mock") is now RESOLVED — no ambiguity remains.
   Also confirmed all `state.strat_926_*` attributes are read via `getattr(state, attr, default)`
   throughout the function (lines 50, 55, 66, 72, 86), so the plan's minimal fake-state approach
   (plain object/SimpleNamespace with only `active_strategies` + `trade_lots` set) is sufficient
   and viable — no hidden required attributes exist beyond what the checklist already lists.
2. **Docstring fix is genuinely zero-behavior-impact — CONFIRMED.** Grepped
   `engine/strategy_926.py` for `current_trend`: the only occurrence in the entire file is the
   function signature at line 31. It is accepted but never evaluated in the function body. The
   docstring's incorrect claim ("Blocks entirely if NEUTRAL") is purely textual — changing the
   wording cannot alter runtime behavior since nothing reads the docstring string at runtime and
   the parameter it describes is already unused.
3. **Blast Radius confirmed scoped — CONFIRMED, no scope creep.** `grep -rn` across
   `trading-app/` for `evaluate_926_strategy`, `_find_180_strikes`, and `strategy_926` found
   exactly: the definitions in `engine/strategy_926.py` itself, and 3 import/call sites
   (`app.py`, `auto_trader.py`, `backtest_runner.py`) — none require edits since the signature is
   unchanged. No shared execution-pipeline file (`auto_trader.py`'s gate stack, `models.py`,
   `state.py`, etc.) needs modification. The plan's Blast Radius section
   (`strategy_926.py` docstring-only + new `test_strategy_926.py`) is accurate and complete.

Open gaps: none blocking. One informational implementation note for EXECUTE (not a CONCERN —
resolvable within the existing test approach, does not change scope or checklist items):
- **Test 4 (B5) / Test 5 (B6) mock construction detail:** `_find_180_strikes` calls
  `client.get_quotes` MULTIPLE times with DIFFERENT symbol-list arguments within one invocation —
  once for the NIFTY spot price (`[symbol]`, line 167) and once for the CE/PE strike chunk (line
  195). A single static `return_value` will not serve both calls. EXECUTE should use a
  `side_effect` callable that inspects the requested `symbols` argument and returns the
  spot-price dict for the single-symbol spot call, and the constructed ATM/CE/PE quote dict for
  the chunk call — keeping the mocked spot price and the ATM strike symbols
  (`atm = round(spot / 50) * 50`) mutually consistent so the ATM branch's symbol lookups actually
  hit. This is a standard multi-call-mock pattern, not a design gap; flagging it here so EXECUTE
  does not have to re-derive it from scratch.

What this coverage does NOT prove:
- `test_entry_window_enforcement` / `test_one_trade_per_day_cap` / `test_arm_then_recover_crossover`
  / `test_atm_based_sl_target_sizing` / `test_zero_atm_premium_fallback` /
  `test_no_duplicate_find_180_strikes_definition`: these prove the named unit-level behaviors in
  isolation with mocked `client` calls — they do NOT prove live Fyers API integration behavior
  (real quote latency, real expiry-list shape drift, real rate-limiting) or interaction with the
  shared `auto_trader.py` gate stack (chase/fade, SL/TSL lock, order concurrency, directional-regime
  gate) downstream of this function's return value — that shared-gate coverage is out of this
  phase's scope (see `## Blockers That Would Justify BLOCKED Status` — full scoped suite run at C1
  is the only cross-check, and it is Fully-Automated but still mock/unit-level, not live-market).
- `cd trading-app/tests && python3 -m pytest -q` (full scoped suite): proves no regression is
  introduced in the existing suite; does NOT prove behavior of code paths the existing suite
  itself doesn't already cover (pre-existing gap, not introduced by this phase).
(Required until C3 is implemented — temporary C3 mitigation)

Gate: PASS (no FAILs, no unresolved CONCERNs — the one implementation-detail note above is
informational guidance for EXECUTE, not a residual risk requiring acceptance)
Accepted by: N/A (Gate: PASS — no CONDITIONAL concerns require acceptance)

---

## Autonomous Goal Block

Reference for latest state: `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md`
(umbrella plan carries `## Stable Program Goal` — BRANCH B: this phase plan does not carry its
own Autonomous Goal Block; the umbrella's /goal governs the full 14-phase strategy-rebuild
program, including this phase.)
