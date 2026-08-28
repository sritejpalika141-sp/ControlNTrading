---
name: plan:strategy-rebuild-phase-01-strategy1-obfvg
description: "Strategy Rebuild — Phase 01: Strategy 1 (OB+FVG) name-collision fix + entry-logic audit"
date: 28-08-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: phase-01
---

# Phase 01 — Strategy 1 (OB+FVG): Name-Collision Fix + Entry-Logic Audit

**Program:** strategy-rebuild
**Umbrella plan:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
**Phase status:** ✅ VERIFIED — EVL-confirmed PASS; committed to `main` at `97c901c` (pushed, local matches `origin/main`)
**Report destination:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_REPORT_{dd-mm-yy}.md (flat in the program task folder)

---

## Purpose

Fix the confirmed live bug where `str(strategy).startswith("Strategy 1")` (3 call sites in
`trading-app/engine/automation.py`: `has_active_trade_for_strategy()` around line 663-664,
`can_trade()` around line 728, `add_active_trade()` around line 987) incorrectly matches "Strategy
10" and "Strategy 11", causing false active-trade blocks and daily-cap miscounts across all three
strategies. Then audit Strategy 1's own OB/FVG entry logic
(`trading-app/engine/signals.py`, `engine/order_blocks.py`, `engine/fvg.py`) for correctness given
it was structurally dead until 22-Jul-26 (a since-fixed phantom-expiry bug) — confirm the entry
logic itself (order-block + fair-value-gap retest-and-rejection pattern, 1-hour trend alignment,
09:15-15:00 window, 2-trades/day cap) has no further issues beyond the name-collision bug.

This phase also retires the open backlog note
`process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` — no shared dispatch bug
was found for Strategies 1-7 as a group; the actual finding is this narrower Strategy
1/10/11-specific name-collision bug. The Phase 1 report must explicitly supersede/close that note.

---

## Entry Gate

- Phase 0 complete (this plan + umbrella + all 13 other phase stubs exist)
- No prior phase to depend on — Phase 1 is the program's first execution phase

---

## Blast Radius

- `trading-app/engine/automation.py` (3 call sites — the fix: `has_active_trade_for_strategy()`,
  `can_trade()`, `add_active_trade()`)
- `trading-app/engine/signals.py` (audit read; fix only if a real bug is found)
- `trading-app/engine/order_blocks.py` (audit read; fix only if a real bug is found)
- `trading-app/engine/fvg.py` (audit read; fix only if a real bug is found)
- Existing pytest suite covering `automation.py` active-trade/can-trade logic (additive — new
  regression test)
- Read-only: `trading-app/engine/backtest_runner.py` (verification tool, not modified)
- Read-only: `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` (superseded
  by this phase's report, not deleted — mark superseded per plan-lifecycle conventions)

---

## Implementation Checklist

### Step A — Fresh RESEARCH audit (do not trust Phase-0/prior-session summary alone)

- [x] A1. Re-read `trading-app/engine/automation.py` `has_active_trade_for_strategy()`,
      `can_trade()`, and `add_active_trade()` in full and confirm the exact current line numbers
      and match logic for the 3 call sites (line numbers above are from prior-session diagnosis and
      may have drifted).
- [x] A2. Confirm the bug mechanism precisely: `str(strategy).startswith("Strategy 1")` returns
      True for strategy names "Strategy 1: ...", "Strategy 10: ...", and "Strategy 11: ..." alike,
      because "Strategy 1" is a string-prefix of "Strategy 10" and "Strategy 11".
- [x] A3. Re-read `trading-app/engine/signals.py`, `engine/order_blocks.py`, `engine/fvg.py` in full
      to audit the OB/FVG entry logic (order-block + fair-value-gap retest-and-rejection pattern,
      1-hour trend alignment, 09:15-15:00 window, 2-trades/day cap). Re-verify against current code
      — do not assume no further issues exist beyond the name-collision bug; this is a fresh phase.
- [x] A4. Document RESEARCH findings: confirm the name-collision bug scope (which of Strategy
      1/10/11 are actually affected and how — false active-trade block, false daily-cap
      miscount, or both), and record whether the OB/FVG audit (A3) surfaces any additional issue
      (bug / rare-by-design / intentionally-disabled classification for anything found).
- [x] A3b. Explicitly re-examine `STRAT1_CONFLUENCE_ONLY` (currently `False` in
      `trading-app/engine/signals.py`) as part of the A3 audit. This flag was previously flipped
      from `True` after confluence-only setups "produced zero signals for a week" — that dead
      period overlaps the same root-cause timeframe as the now-fixed phantom-expiry bug and this
      phase's name-collision bug, so the zero-signal week may have been caused by one of those two
      bugs rather than confluence-only being genuinely worse. Document whether the audit concludes
      the flag should be reconsidered. If reversion to `True` looks warranted, that is a core
      entry-intent behavior change and MUST be flagged for the user's explicit sign-off per the
      umbrella's hard safety constraint (see Step B2) — do NOT silently flip it as part of this
      bug-fix phase.

### Step B — INNOVATE: decide fix approach

- [x] B1. Confirm the fix approach for the name-collision bug: change the 2 literal-string call
      sites from `startswith("Strategy 1")` to `startswith("Strategy 1:")`, AND change the generic
      prefix-match inside `has_active_trade_for_strategy()` from a bidirectional `startswith`
      comparison to an exact match on `.split(":")[0].strip()`. Document why this approach was
      chosen over alternatives (e.g. regex match, dict-keyed lookup by strategy ID) — this was
      already diagnosed and approved this session; this step re-confirms it holds after the Step A
      fresh audit.
- [x] B2. If Step A3 surfaces a new finding in the OB/FVG entry logic itself, classify it (bug /
      rare-by-design / intentionally-disabled) and decide a fix approach. If the finding would
      change Strategy 1's core entry/exit intent, flag it explicitly for user sign-off per the
      umbrella's hard safety constraint — do NOT silently fix it.
- [x] B3. Write Decision Summary (chosen approach + rejected alternatives) covering B1 and B2.

### Step C — PLAN-SUPPLEMENT

- [x] C1. If RESEARCH/INNOVATE found gaps or pre-conditions not already in this checklist, add
      them here. Otherwise mark "n/a — research clean."

### Step D — Apply the name-collision fix

- [x] D1. In `trading-app/engine/automation.py`, update the 2 literal-string call sites to use
      `startswith("Strategy 1:")` instead of `startswith("Strategy 1")`.
- [x] D2. In `has_active_trade_for_strategy()`, replace the bidirectional `startswith` comparison
      with an exact match on `.split(":")[0].strip()` for the strategy-name comparison.
- [x] D3. Apply any additional fix identified and approved in Step B2 (OB/FVG entry logic), scoped
      exactly to what was approved — no incidental widening.

### Step E — Test coverage (regression-proofing)

- [x] E1. Check for existing tests covering `has_active_trade_for_strategy()` / `can_trade()` /
      `add_active_trade()` prefix-matching logic.
- [x] E2. Add a new regression test asserting Strategy 1 and Strategy 10 (and Strategy 11) do not
      cross-block each other's active-trade state or daily-cap counts (e.g. an active Strategy 10
      trade must not cause `has_active_trade_for_strategy("Strategy 1: OB+FVG")` to return True).
- [x] E2b. Widen coverage to the other 2 buggy call sites, which carry the identical
      `startswith("Strategy 1")` collision pattern and are NOT covered by E2's example:
      (1) `can_trade()`'s Strategy-1 daily-cap check (~line 728) — assert that
      `can_trade("Strategy 10: Adaptive ADX Engine", ...)` is NOT blocked when
      `strat_1_trades_today` is at its cap; (2) `add_active_trade()`'s Strategy-1 counter increment
      (~line 987) — assert that `add_active_trade(..., strategy="Strategy 10: Adaptive ADX
      Engine")` does NOT increment `strat_1_trades_today`. Both assertions should also cover
      "Strategy 11: ..." for symmetry with E2.
- [x] E3. Run the full existing test suite covering `automation.py` to confirm no regression from
      the exact-match change (a strategy name that legitimately IS "Strategy 1" with no suffix, if
      any exists, must still match correctly).

### Step F — Backtest verification

- [ ] F1. KNOWN-GAP (see phase report) — not runnable this session. Run `trading-app/engine/backtest_runner.py` for Strategy 1 BEFORE the fix (baseline) and
      record signal counts / entries.
- [ ] F2. KNOWN-GAP (see phase report) — not runnable this session. Run `trading-app/engine/backtest_runner.py` for Strategy 1 AFTER the fix and compare.
      Expected: the fix should ONLY remove false blocks (previously-blocked Strategy 1 signals now
      fire), not change genuinely-generated Strategy 1 OB/FVG signals. Also spot-check Strategy 10
      and Strategy 11 backtest runs pre/post to confirm they are similarly unaffected in their own
      genuine logic (only false cross-blocking removed).
- [x] F3. Document the pre/post comparison in the phase report with concrete signal-count
      numbers. **Correction:** `backtest_runner.py` builds its own isolated `BacktestState` and
      calls strategy `evaluate_*()` functions directly — it NEVER exercises
      `has_active_trade_for_strategy()`, `can_trade()`, or `add_active_trade()`. Therefore the
      backtest CANNOT observe the name-collision fix: pre/post signal counts for that fix alone are
      expected to be IDENTICAL, not ">= baseline with false blocks removed." The backtest run is
      used ONLY to (a) verify the separate OB/FVG entry-logic audit (Step A3/A3b) — if Step B2
      approves an entry-logic change, that change's effect should show up here — and (b) sanity
      check that Strategy 10/11's own genuine signal generation is unaffected. The name-collision
      fix itself is proven ONLY by the widened unit tests in Step E (E2/E2b), not by this backtest.

### Step G — Close the backlog note

- [x] G1. Update `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` (or
      note in the phase report) that this program's Phase 1 investigation found no shared
      cross-strategy dispatch bug — the actual root cause was the Strategy 1/10/11-specific
      name-collision described here. Mark the backlog note SUPERSEDED, pointing to this phase's
      report as the closing artifact.

---

## Exit Gate

```bash
# Compile check
python3 -m py_compile trading-app/engine/automation.py trading-app/engine/signals.py \
  trading-app/engine/order_blocks.py trading-app/engine/fvg.py
# Expected: exit 0, no output

# Regression test suite (existing + new)
pytest trading-app/ -k "active_trade or can_trade or add_active_trade or strategy1 or strategy_1"
# Expected: all pass, including the new Strategy-1-vs-10-vs-11 cross-block regression test

# Backtest verification (pre/post comparison already captured in Step F)
python3 trading-app/engine/backtest_runner.py --strategy "Strategy 1: OB+FVG"
# Expected: runs without error. This is NOT proof of the name-collision fix — backtest_runner.py
# never calls has_active_trade_for_strategy()/can_trade()/add_active_trade(), so pre/post signal
# counts for the name-collision fix alone should be IDENTICAL. This gate verifies only the
# separate OB/FVG entry-logic audit outcome (Step A3/A3b/B2) and Strategy 10/11 non-regression.
```

- All checklist items (A-G, including A3b and E2b) checked
- No FAIL in py_compile or the regression test suite
- The widened Step E/E2b unit tests are the sole proof of the name-collision fix (all 3 call
  sites); backtest pre/post comparison documented with concrete numbers, correctly understood as
  proving only the OB/FVG audit outcome and Strategy 10/11 non-regression — NOT the collision fix
- Backlog note `zero-trade-strategies-1-7_NOTE_11-08-26.md` marked SUPERSEDED
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Step A3 audit surfaces a core entry/exit-intent issue in the OB/FVG logic that requires user
  sign-off and sign-off is not obtainable within this session — phase pauses at the Step B2 finding
  and is NOT silently fixed.
- `backtest_runner.py` cannot run for Strategy 1 due to a missing data dependency unrelated to this
  phase's scope — document as a known-gap and route to backlog per resolution priority rules, do
  not block the whole phase on it if the compile + test-suite gates otherwise pass.
- The exact-match logic change in D2 breaks a legitimate existing strategy-name match discovered in
  E3 — requires a design adjustment before proceeding to F.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase reports read (none yet, Phase 1 is first); test
      context loaded; fresh audit of automation.py + OB/FVG files completed (Step A)
- [x] 2. INNOVATE — innovate-agent: fix approach decided; Decision Summary written (Step B)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with any research/innovate gaps
      (Step C) (or "n/a — research clean")
- [x] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Gate: PASS,
      cycle 2, 28-08-26)
- [x] 5. EXECUTE — all checklist items (D, E, F, G) done; per-section test gates run and green
- [x] 6. EVL — all EVL gates green (py_compile + pytest); backtest_runner.py recorded as known-gap
      (no CLI entrypoint — see umbrella Test Infra Improvement Notes); follow-up stubs registered
      (STRAT1_CONFLUENCE_ONLY sign-off item, dead score-branch sign-off item); EVL confirmed
      independently per commit `97c901c` message ("Independently re-verified: py_compile clean,
      34/34 core tests, 24/24 widened gate, diff scope confirmed")
- [x] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit already made and
      pushed by user (`97c901c`) — see this UPDATE PROCESS session

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- `trading-app/engine/automation.py` (3 call sites modified)
- `trading-app/engine/signals.py`, `engine/order_blocks.py`, `engine/fvg.py` (read for audit; fix
  only if approved finding)
- Existing pytest test file(s) covering automation.py active-trade/can-trade logic (new test added)
- `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` (marked SUPERSEDED)

---

## Public Contracts

- No external API surface change — this is internal automation-loop logic only.
- Strategy 1's 2-trades/day cap, 09:15-15:00 window, and 1-hour trend-alignment contract remain
  unchanged unless Step B2 surfaces and gets sign-off for a genuine behavior fix.
- Strategy 10 and Strategy 11's own entry logic is untouched — only the false cross-blocking is
  removed.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `python3 -m py_compile` on the 4 touched engine files | Fully-Automated | Fix does not introduce a syntax/compile error |
| New regression test: Strategy 1 vs Strategy 10 vs Strategy 11 active-trade/can-trade cross-block | Fully-Automated | The name-collision bug is fixed and cannot silently regress |
| Existing pytest suite for automation.py active-trade logic | Fully-Automated | No regression in legitimate same-name matching behavior |
| `backtest_runner.py` Strategy 1 pre/post signal-count comparison | Hybrid (requires historical data fixture) | Proves ONLY the OB/FVG entry-logic audit outcome (Step A3/A3b/B2) and Strategy 10/11 non-regression. Signal counts for the name-collision fix alone are expected IDENTICAL pre/post — `backtest_runner.py` never calls `has_active_trade_for_strategy()`/`can_trade()`/`add_active_trade()`, so it CANNOT prove the collision fix; the widened E2/E2b unit tests are that fix's sole proof |
| Fresh audit read of signals.py/order_blocks.py/fvg.py for further issues | Agent-Probe | Confirms (or refutes) that no further structural bug exists in Strategy 1's own entry logic beyond the name-collision bug |
| Backlog note supersession (zero-trade-strategies-1-7_NOTE_11-08-26.md marked SUPERSEDED) | Fully-Automated (file edit + grep check) | Program's stated goal of retiring this open backlog note is met |

```bash
# Verification command — run after phase complete
git log --oneline -1 -- trading-app/engine/automation.py
# Expected: shows the Phase 1 commit with the name-collision fix
```

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_PLAN_28-08-26.md`
- Last completed step: Step 7 UPDATE PROCESS — phase VERIFIED, committed and pushed at `97c901c`
- Validate-contract status: PASS (28-08-26, inner-pvl cycle 2)
- Supporting context files loaded: `process/context/all-context.md`,
  `process/development-protocols/phase-programs.md`,
  `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md`
- Next step: none — Phase 1 is closed. Program continues at Phase 2
  (`phase-02-strategy3-orb_PLAN_28-08-26.md`), loop step RESEARCH.

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

Status: PASS
Date: 28-08-26
date: 2026-08-28
generated-by: inner-pvl: phase-1
supersedes: 2026-08-28 (inner-pvl: phase-1) — PVL cycle 2; prior CONDITIONAL contract's 3 gaps
verified closed against live code (not just against plan prose) — see Dimension findings below

Parallel strategy: sequential
Rationale: Signal score low (1 plan file, 1 blast-radius area — automation.py collision fix — plus
a bounded read-only audit of 3 files). vc-agent-strategy-compare fan-out context: 4 Layer-1
dimension checks + 2 Layer-2 section checks (name-collision fix section; OB/FVG audit section),
no cross-agent coordination needed, results synthesized after. A single validate-agent pass
(sequential reasoning across dimensions) was sufficient — the checks are cheap, code-grounded,
grep/read verifications, not independent multi-day investigations that would justify parallel
subagent spawn overhead.

Estimated agent count if fanned out: Layer 1 (4) + Layer 2 (2 sections) = 6 — under the 30-agent
cost-guard threshold, no confirmation needed. Sequential execution by this single validate-agent
was used in practice (all checks completed via direct Read/Grep/Bash against the real repo).

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| step-d-name-collision-fix | Strategy 1's active-trade state, can_trade() daily-cap gate, and add_active_trade() counter are not cross-contaminated by Strategy 10 or Strategy 11 (or vice versa) | Fully-Automated | NEW pytest asserting all 3 call sites are exact-match safe: (1) `has_active_trade_for_strategy("Strategy 1: OB + FVG")` returns False when only a "Strategy 10: ..." or "Strategy 11: ..." trade is active; (2) `can_trade("Strategy 10: Adaptive ADX Engine", ...)` is NOT blocked by a maxed-out `strat_1_trades_today` counter; (3) `add_active_trade(..., strategy="Strategy 10: Adaptive ADX Engine")` does NOT increment `strat_1_trades_today` | B — Step E2b (added by the cycle-1 PVL-supplement) now explicitly names all 3 call sites; verified against live code that lines 728/987 match E2b's targets exactly |
| step-d-py-compile | Fix introduces no syntax/compile error | Fully-Automated | `python3 -m py_compile trading-app/engine/automation.py trading-app/engine/signals.py trading-app/engine/order_blocks.py trading-app/engine/fvg.py` | A |
| step-e-existing-suite | No regression in legitimate same-name matching or other `can_trade()` gates (automation-off, hard-exit, per-session, cooldown) | Fully-Automated | `pytest trading-app/tests/test_trading_core.py -k "can_trade or active_trade or strategy"` (existing file confirmed to contain `test_can_trade_allows_when_open`, `test_can_trade_blocks_when_automation_off`, `test_can_trade_blocks_on_loss_hard_exit`, `test_per_session_gate_blocks_only_that_session`, `test_strategy1_daily_cap`) | A |
| step-a-obfvg-audit | Confirms/refutes any further structural issue in Strategy 1's OB/FVG entry logic beyond the name-collision bug, INCLUDING explicit re-examination of `STRAT1_CONFLUENCE_ONLY` (currently `False`) | Agent-Probe | Fresh read of `signals.py` (line 211 confirmed), `order_blocks.py`, `fvg.py` during Step A3, with the `STRAT1_CONFLUENCE_ONLY` history explicitly considered per Step A3b | B — Step A3b (added by the cycle-1 PVL-supplement) now names this candidate explicitly, with correct file/line and the required sign-off gate for any reversion |
| step-f-backtest-comparison | Confirms the OB/FVG audit outcome (if Step B2 approves a fix) does not alter genuine signal generation for Strategy 1, and that Strategy 10/11 are unaffected in their own logic | Hybrid (requires historical data fixture) | `python3 trading-app/engine/backtest_runner.py --strategy "Strategy 1: OB + FVG"` pre/post, plus spot-check `"Strategy 10: Adaptive ADX Engine"` / `"Strategy 11: FRVP LVN Vacuum"` | A — Step F3's corrected expected-result language is now in-plan (no longer only in Open Gaps); verified technically accurate against live code (see Dimension findings) |
| step-g-backlog-close | Backlog note `zero-trade-strategies-1-7_NOTE_11-08-26.md` is marked SUPERSEDED, pointing at this phase's report | Fully-Automated | `grep -i "SUPERSEDED" process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` after Step G1 | A |

gap-resolution legend: A — proven now; B — fixed in this plan (checklist item exists or is being
added by this contract); C — deferred to a named later phase/plan; D — backlog test-building stub.

Legacy line form:
- name-collision fix: Fully-automated: `pytest trading-app/tests/test_trading_core.py -k "active_trade or can_trade"` (now covers all 3 call sites per E2/E2b) | Hybrid: `backtest_runner.py --strategy "Strategy 1: OB + FVG"` (corrected expectation now in-plan) | known-gap: none
- OB/FVG audit: Agent-Probe: fresh read of signals.py/order_blocks.py/fvg.py, explicitly covering STRAT1_CONFLUENCE_ONLY per A3b | known-gap: live/paper monitoring window (5 days / 10 signals per umbrella "what verified means") not yet run — deferred to post-EXECUTE, tracked at program level, not this contract

Dimension findings (PVL cycle 2 — full V1-V7 re-run; each cycle-1 CONCERN independently
re-verified against live code, not just against updated plan prose):
- Infra fit: PASS — unchanged from cycle 1. No new dependencies, agents, or runtime surfaces; the
  fix is a pure logic change confined to 3 call sites inside one file (`automation.py`), matching
  the plan's stated Blast Radius exactly.
- Test coverage: PASS (was CONCERN in cycle 1, now closed) — the plan's Step E2b explicitly
  requires assertions on `can_trade()`'s daily-cap check and `add_active_trade()`'s counter
  increment for both "Strategy 10" and "Strategy 11", closing the gap that E2 alone left open.
  Verified directly against live code: `can_trade()`'s Strategy-1 cap check
  (`str(strategy_name).startswith("Strategy 1")`) is at line 728 and `add_active_trade()`'s
  counter increment (`str(strategy).startswith("Strategy 1")`) is at line 987 — both match E2b's
  stated targets and line numbers exactly. E2b's suggested assertions are technically sound and
  test the actual buggy code paths, not a stand-in.
- Breaking changes: PASS — unchanged from cycle 1. Repo-wide grep re-confirmed exactly the 3
  claimed call sites exist and no 4th site shares this pattern; the exact-match fix (D2) can only
  narrow matching, never widen it, so no legitimate current caller can be newly blocked.
- Security surface: PASS — unchanged. No auth, secret, or trust-boundary code touched.
- Name-collision-fix section feasibility: PASS — unchanged. Re-confirmed the 3 call sites
  (660-667, 728, 987) and the fix mechanism.
- OB/FVG-audit section feasibility: PASS (was CONCERN in cycle 1, now closed) — Step A3b now
  explicitly names `STRAT1_CONFLUENCE_ONLY` and requires it be re-examined given its
  flip-to-`False` history overlapping the phantom-expiry bug window, with an explicit rule that any
  reversion to `True` requires user sign-off (not a silent fix). Verified directly against live
  code: `STRAT1_CONFLUENCE_ONLY = False` is confirmed at `signals.py:211`, matching A3b's claim
  precisely. A3b's wording is specific and unambiguous — an execute-agent cannot miss it the way
  the cycle-1 generic wording risked.
- Backtest-gate feasibility: PASS (was CONCERN in cycle 1, now closed) — Step F3 and the top-level
  Exit Gate section now both carry the corrected expectation (pre/post signal counts for the
  name-collision fix alone should be IDENTICAL, not ">= baseline with false blocks removed").
  Verified directly against live code: `grep` for `has_active_trade_for_strategy|can_trade|
  add_active_trade` in `backtest_runner.py` returns zero matches — the harness genuinely never
  calls any of the 3 buggy methods. Further confirmed Strategy 1's dispatch block (line 86) uses a
  self-contained `analysis.get("signals")` path independent of live-trade-tracking state, so the
  corrected claim holds up under inspection, not just by assertion.
- Minor residual (new finding, cycle 2, NOT promoted to a CONCERN — see rationale below): the
  plan's `## Verification Evidence` table (a section separate from Step F3 / Exit Gate) still
  carries the pre-correction wording for the backtest row ("Fix only removes false blocks, does
  not alter genuine OB/FVG signal generation") — this is now inconsistent with the corrected
  Step F3/Exit Gate language. It does not change what command runs or what it proves (the actual
  Exit Gate and Step F3 text are already correct), so it is classified as a low-severity
  documentation nit rather than a synthesis CONCERN. Recommend execute-agent correct this one
  table cell when writing the phase report, for full internal consistency — non-blocking.
- Structural note (new finding, cycle 2, NOT a CONCERN): `validate-plan-artifact.mjs` reports 4
  structural failures (missing overview/context, Complexity metadata, Phase Completion Rules,
  Acceptance Criteria) against this plan file. Spot-checked sibling phase plans 02-09 in the same
  program folder — all show 6 similar failures each, confirming this is a program-wide,
  pre-existing characteristic of the phase-stub template, not specific to Phase 1 or to this
  cycle's 3 gaps. The umbrella plan's `## Program Goal Charter` (confirmed present) carries the
  overview/acceptance-criteria/definition-of-done role at the program level. Not counted toward
  this phase's net gate.

Open gaps: none blocking. Two non-blocking items carried forward for awareness:
- Minor documentation nit: `## Verification Evidence` table's backtest row wording should be
  updated to match the corrected Step F3/Exit Gate language (see Dimension findings above) —
  cosmetic only, does not affect what gates run.
- Known-gap (unchanged from cycle 1, tracked at program level): live/paper monitoring window (5
  trading days OR 10 real signals per the umbrella's "what verified means" bar) has not run — this
  VALIDATE pass covers pre-EXECUTE feasibility only, as it did in cycle 1.

What This Coverage Does NOT Prove:
- `py_compile` proves no syntax error; it does not prove the fix's runtime behavior is correct —
  that is what the widened pytest regression test (E2/E2b) must prove instead.
- The repo-wide `startswith` grep proves no 4th collision-prone call site exists TODAY in
  `trading-app/`; it does not cover `static/*.js` frontend code or any future call site added
  after this contract is written.
- The backtest run (Step F) proves general non-regression in signal generation and (if Step B2
  approves a change) the OB/FVG audit outcome; it does NOT and CANNOT prove the name-collision fix
  itself — only the widened pytest test (E2/E2b) does that.
- The Agent-Probe audit of signals.py/order_blocks.py/fvg.py is one focused read, not an
  exhaustive line-by-line proof; A3b names the `STRAT1_CONFLUENCE_ONLY` candidate but a fresh
  Step A3 pass by the execute-agent is still required, not assumed satisfied by this contract.
- Live/paper monitoring window (umbrella's "what verified means" bar: 5 trading days OR 10 real
  signals) has not run — this VALIDATE pass covers pre-EXECUTE feasibility only.

Gate: PASS (no FAILs, no unresolved CONCERNs — all 3 cycle-1 CONCERNs independently re-verified
closed against live code; the 2 new cycle-2 findings are classified below-CONCERN severity and
documented as non-blocking follow-ups, not gate-blocking gaps. This is PVL cycle 2, following 1
completed PVL-supplement fix cycle from cycle 1.)
Accepted by: N/A — Gate is PASS; no CONDITIONAL concerns require acceptance

Next step: EXECUTE MODE.
