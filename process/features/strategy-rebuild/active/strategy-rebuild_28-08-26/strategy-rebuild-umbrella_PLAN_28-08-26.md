---
name: plan:strategy-rebuild-umbrella
description: "Strategy Rebuild — umbrella/orchestration plan for the 14-phase audit+fix program across all trading strategies"
date: 28-08-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: umbrella
---

# Strategy Rebuild — Umbrella Plan

**Date:** 28-08-26
**Complexity:** COMPLEX
**Status:** ⏳ PLANNED

- Program type: PHASE PROGRAM (14 phases, sequential with gated joins)
- Date: 28-08-26
- Feature folder: `process/features/strategy-rebuild/`

---

## Program Goal Charter

```
Strategy Rebuild — Program Goal Charter

North star:
- Every trading strategy in this live-money system fires when its entry conditions are genuinely
  met, exits/stops correctly, and is free of structural bugs that silently block or distort it —
  verified against real historical data and a live-monitoring window, not just code review.

Definition of done (an unattended agent must be able to do all of these):
1. Audit any one strategy's entry/exit/SL logic against its own source code and correctly
   classify each finding as bug / rare-by-design / intentionally-disabled.
2. Apply a targeted, scoped fix for any confirmed bug without altering the strategy's core
   intended behavior (behavior changes require explicit user sign-off, same as this session's
   INNOVATE-then-confirm pattern).
3. Prove the fix via the existing backtest runner (trading-app/engine/backtest_runner.py, covers
   all 13 rule-based strategies) clearing a reasonable threshold, plus a short live/paper
   monitoring window before calling the phase VERIFIED.

What "verified" means (program level):
- A phase reaches VERIFIED only when: (a) the specific bug/audit finding for that strategy has a
  code fix, OR an explicit "no fix needed, confirmed working as intended" finding is recorded;
  (b) the fix compiles (py_compile clean) and passes the existing + new test suite with no
  regressions; (c) a backtest run via backtest_runner.py shows the strategy still produces sensible
  signals (the bar is "fires correctly and the fix didn't break its own logic" — NOT "is
  profitable"; a correctly implemented strategy can still lose money in backtest); (d) a
  live-contract check that a follow-up live/paper monitoring window (default: 5 trading days OR 10
  real signals, whichever comes first) shows no new structural issue.
- validate-contract gates must be recorded alongside phase gates and regression evidence for a
  phase to reach VERIFIED. A phase without a validate-contract (or documented skip reason) cannot
  be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 (Confirmed live bugs) → Phases 1, 2 (Strategy 1 name-collision bug, Strategy 3 window bug)
- Tier 2 (Active strategies, audit-only or minor cleanup) → Phases 3-9 (Strategies 2, 4, 7, 8, 9,
  10, 11)
- Tier 3 (Intentionally disabled strategies — lower priority) → Phases 10-13 (Strategies 5, 6,
  Crude Evening, Crude EIA)
- Tier 4 (Shared infrastructure) → Phase 14 (the shared post-signal trend-gate stack — deliberately
  scheduled LAST per user decision, so individual strategy fixes are evaluated before touching the
  shared filter everyone depends on)
- This program retires the open backlog note
  `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` — no shared dispatch
  bug was found this session; Phase 1's report supersedes/closes that note with the real findings
  (the Strategy 1/10/11 name-collision bug in automation.py).

Explicitly out of scope (deferred tier):
- Full strategy rewrites from scratch (user explicitly chose "audit + targeted fix" over full
  rewrite this session).
- The AI-generated dynamic strategy pipeline (engine/ai_strategy_registry.py — paper-only, not
  covered by the backtest runner, separate concern).
- Nightly-learning tuning behavior (already fixed in the separate completed program
  nightly-tuning-safety_21-08-26).

Hard safety constraints (non-negotiable, per phase):
- Never change a strategy's core entry/exit intent without flagging it as a design decision
  requiring explicit user sign-off. Bug fixes are silent-ok within phase scope; behavior changes
  must surface (same INNOVATE-then-confirm pattern as this session).
- Never disable the global 3-candle trailing-SL mechanism or reintroduce a per-strategy trailing
  override (locked owner rule, 03-08-26) without explicit new instruction.
- Never touch trading-app/workers/sl_guardian.py or hindsight_optimizer_worker.py's own logic as
  part of a strategy-audit phase (out of blast radius).
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits (matches this repo's established pattern).
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: strategy-rebuild — Strategy Rebuild (14-phase audit+fix)
Ref: process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md

TARGET: Complete ALL 14 phases until:
- Every strategy's audit finding is classified (bug/rare-by-design/intentionally-disabled) and any
  confirmed bug has a scoped fix
- backtest_runner.py runs cleanly for each fixed strategy pre/post with no unintended signal drift
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe
  (record-judgment)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State -> loop step + validate-contract status
2. Phase plan ## Phase Loop Progress -> first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop R -> I -> P -> PVL -> E -> EVL -> UP, never skip, never reorder;
SKIPS SPEC -- SPEC runs once in the outer program loop):
  1. RESEARCH -> 2. INNOVATE -> 3. PLAN-SUPPLEMENT -> 4. PVL -> 5. EXECUTE -> 6. EVL -> 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into phase plan (or marks "n/a -- clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format; a partial
  contract (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked same
  as placeholder
- Every subagent FIRST ACTION: run vc-context-discovery (load context group files +
  process/context/tests/all-tests.md routing chain) AND vc-plan-discovery (same-feature full depth
  active/backlog/completed/reports/refs + other features active-only + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for next step strategy recommendation

Report via phase reports. No approval between phases unless hard stop hit.

HARD STOPS (pause, wait for user):
- Irreversible/outward-facing action without explicit validate-contract instruction
- Net gate = BLOCKED with no backlog resolution path
- Any strategy core entry/exit-intent change (not a bug fix) discovered mid-phase -- must surface
  for explicit sign-off before applying
- Validate-contract is placeholder and vc-validate-agent cannot run

SAFETY (never override):
- Never disable the global 3-candle trailing-SL mechanism or add a per-strategy trailing override
- Never touch sl_guardian.py or hindsight_optimizer_worker.py's own logic in a strategy-audit phase
- Commit each phase before advancing; process and execution commits kept separate

TEST GATES (every phase exit):
  python3 -m py_compile trading-app/engine/*.py trading-app/workers/*.py
  pytest trading-app/ -k "<phase-specific test selector>" (or full suite if none scoped)
  python3 trading-app/engine/backtest_runner.py --strategy "<Strategy Name>" (pre and post fix)
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs (only if harness files touched)

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before
EXECUTE.

START: Phase 1, loop step RESEARCH (pending). Spawn vc-research-agent for Phase 1
(phase-01-strategy1-obfvg).
```

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (pre-program) | this file | Confirm folder structure, baseline audit, create sub-phase plans | — |
| 1 — Strategy 1 (OB+FVG) name-collision + audit | `phase-01-strategy1-obfvg_PLAN_28-08-26.md` | Fix automation.py `startswith("Strategy 1")` collision with Strategy 10/11; audit OB/FVG entry logic | Phase 0 |
| 2 — Strategy 3 (ORB) window bug | `phase-02-strategy3-orb_PLAN_28-08-26.md` | Fix confirmed call-site window bug limiting Strategy 3 to ~5 of its intended 70 minutes/day | Phase 1 |
| 3 — Strategy 2 audit | `phase-03-strategy2_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 2 | Phase 2 |
| 4 — Strategy 4 audit | `phase-04-strategy4_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 4 | Phase 3 |
| 5 — Strategy 7 audit | `phase-05-strategy7_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 7 | Phase 4 |
| 6 — Strategy 8 audit | `phase-06-strategy8_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 8 | Phase 5 |
| 7 — Strategy 9 audit | `phase-07-strategy9_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 9 | Phase 6 |
| 8 — Strategy 10 audit | `phase-08-strategy10_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 10 | Phase 7 |
| 9 — Strategy 11 audit | `phase-09-strategy11_PLAN_28-08-26.md` | Audit-only / minor cleanup, Strategy 11 (FRVP) | Phase 8 |
| 10 — Strategy 5 audit | `phase-10-strategy5_PLAN_28-08-26.md` | Intentionally-disabled strategy audit, Strategy 5 | Phase 9 |
| 11 — Strategy 6 audit | `phase-11-strategy6_PLAN_28-08-26.md` | Intentionally-disabled strategy audit, Strategy 6 | Phase 10 |
| 12 — Crude Evening audit | `phase-12-crude-evening_PLAN_28-08-26.md` | Intentionally-disabled strategy audit, Crude Evening | Phase 11 |
| 13 — Crude EIA audit | `phase-13-crude-eia_PLAN_28-08-26.md` | Intentionally-disabled strategy audit, Crude EIA | Phase 12 |
| 14 — Shared gate stack | `phase-14-shared-gate-stack_PLAN_28-08-26.md` | Shared post-signal trend-gate stack (directional-regime-gate, MTF-alignment-gate, execution_gates.py) — deliberately LAST | Phases 1-13 |

### Join Conditions

- Each phase N MUST NOT start until phase N-1's exit gate passes (strictly sequential — one
  strategy at a time in a live-money system; parallel strategy fixes are not attempted).
- Phase 14 MUST NOT start until ALL of phases 1-13 pass, since it touches shared infrastructure
  every other strategy depends on.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | Phase plan files created; baseline audit note (zero-trade-strategies-1-7) reviewed |
| 1 | Phase 0 complete | Name-collision fix applied at 3 call sites; regression test added; backtest_runner.py pre/post comparable for Strategy 1; phase report supersedes zero-trade-strategies-1-7 backlog note |
| 2 | Phase 1 exit met | Window bug fixed in eval_strat_3(); backtest confirms full ~70min/day window now evaluated |
| 3-9 | Prior phase exit met | Fresh RESEARCH audit complete; confirmed bugs (if any) fixed and backtested; "no fix needed" findings documented if none found |
| 10-13 | Prior phase exit met | Fresh RESEARCH audit complete on intentionally-disabled strategy; confirm disablement is still intentional or flag for re-enable decision (requires sign-off, not silent) |
| 14 | Phases 1-13 all pass | Shared gate stack audited/fixed only after every dependent strategy's own logic is proven correct in isolation |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — SPEC runs once in the outer program loop, not per phase. The 7 steps map to:

1. **RESEARCH** — spawn research-agent: load context, read prior phase reports, re-verify the
   target strategy's current code (do not trust Phase-0 summary-level findings alone), document
   findings
2. **INNOVATE** — spawn innovate-agent: decide fix approach; write Decision Summary (chosen
   approach + rejected alternatives); any core-behavior change must be flagged for sign-off here
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps/pre-conditions not in
   checklist, add them; otherwise mark "n/a — research clean" and tick step 3
4. **PVL** — spawn vc-validate-agent: full V1-V7; validate-contract written per
   `.claude/skills/vc-validate-findings/references/example-validate-output.md` format
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract
6. **EVL** — spawn vc-tester: run phase test gates (py_compile, pytest, backtest_runner.py) to
   green; register follow-up stubs; write EVL HANDOFF SUMMARY
7. **UPDATE-PROCESS** — write phase report to durable report path, rewrite umbrella
   `## Current Execution State` section (overwrite, not append)

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn
execute-agent while the Validate Contract section reads "(placeholder — vc-validate-agent writes
this section before EXECUTE)".

---

## Autonomous Execution Rules (During /goal)

During /goal execution of this phase program:
- Agent self-decides at all V5 gates — no user approval needed between phases
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record
- BLOCKED net gate: document items in backlog, continue with remaining phase plans; backlog is
  always a valid resolution — always find a path forward
- Hard stops (must pause for user approval):
  - Irreversible/outward-facing action without explicit contract instruction (push to remote,
    deploy, live schema/data mutation)
  - Any strategy core entry/exit-intent change discovered mid-phase (not a pure bug fix)
  - Plan file explicitly marks "pause required" at a step
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all
  autonomously
- The phase report is the communication channel for conflicts, errors, and learnings — not inline
  questions

---

## Global Constraints

- Never disable the global 3-candle trailing-SL mechanism or reintroduce a per-strategy trailing
  override (locked owner rule, 03-08-26) without explicit new instruction.
- Never touch `trading-app/workers/sl_guardian.py` or `hindsight_optimizer_worker.py`'s own logic
  as part of a strategy-audit phase.
- Never widen a strategy's entry/exit conditions beyond what "fixing a confirmed bug" requires
  without surfacing the change for sign-off.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.

---

## Durable Report Destinations

| Phase | Report path (inside task folder) |
|---|---|
| 0 (pre-program) | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-00-kickoff_REPORT_28-08-26.md` |
| 1 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_REPORT_{dd-mm-yy}.md` |
| 2 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-02-strategy3-orb_REPORT_{dd-mm-yy}.md` |
| 3 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-03-strategy2_REPORT_{dd-mm-yy}.md` |
| 4 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-04-strategy4_REPORT_{dd-mm-yy}.md` |
| 5 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-05-strategy7_REPORT_{dd-mm-yy}.md` |
| 6 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-06-strategy8_REPORT_{dd-mm-yy}.md` |
| 7 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-07-strategy9_REPORT_{dd-mm-yy}.md` |
| 8 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-08-strategy10_REPORT_{dd-mm-yy}.md` |
| 9 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-09-strategy11_REPORT_{dd-mm-yy}.md` |
| 10 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-10-strategy5_REPORT_{dd-mm-yy}.md` |
| 11 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-11-strategy6_REPORT_{dd-mm-yy}.md` |
| 12 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-12-crude-evening_REPORT_{dd-mm-yy}.md` |
| 13 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-13-crude-eia_REPORT_{dd-mm-yy}.md` |
| 14 | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-14-shared-gate-stack_REPORT_{dd-mm-yy}.md` |

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Pre-program (plan creation) | 🔨 CODE DONE (this artifact set) |
| 01 — Strategy 1 (OB+FVG) | ⏳ PLANNED |
| 02 — Strategy 3 (ORB) | ⏳ PLANNED |
| 03 — Strategy 2 | ⏳ PLANNED |
| 04 — Strategy 4 | ⏳ PLANNED |
| 05 — Strategy 7 | ⏳ PLANNED |
| 06 — Strategy 8 | ⏳ PLANNED |
| 07 — Strategy 9 | ⏳ PLANNED |
| 08 — Strategy 10 | ⏳ PLANNED |
| 09 — Strategy 11 | ⏳ PLANNED |
| 10 — Strategy 5 | ⏳ PLANNED |
| 11 — Strategy 6 | ⏳ PLANNED |
| 12 — Crude Evening | ⏳ PLANNED |
| 13 — Crude EIA | ⏳ PLANNED |
| 14 — Shared gate stack | ⏳ PLANNED |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Touchpoints

- `trading-app/engine/automation.py` (Phase 1 — name-collision fix, 3 call sites)
- `trading-app/engine/signals.py`, `engine/order_blocks.py`, `engine/fvg.py` (Phase 1 — audit)
- `trading-app/workers/auto_trader.py` (`eval_strat_3()` — Phase 2; directional-regime-gate /
  MTF-alignment-gate sections — Phase 14)
- `trading-app/engine/strategy_926.py` (Phase 3), `engine/strategy_wisdom.py` (Phase 4),
  `engine/strategy_swing.py` (Phase 10), `engine/strategy_8.py` (Phase 6),
  `engine/strategy_9.py` + `strategy9_filters.py` (Phase 7), `engine/strategy_10.py` (Phase 8),
  `engine/strategy_11_frvp.py` (Phase 9), `engine/strategy_5.py` (Phase 5 note: mapped per Tier —
  see individual phase stub for exact file), `engine/strategy_gap.py` (Phase 11),
  `engine/strategy_crude_evening.py` (Phase 12), `engine/strategy_crude_eia.py` (Phase 13)
- `trading-app/engine/execution_gates.py` (Phase 14)
- `trading-app/engine/backtest_runner.py` (read-only — verification tool for all phases)

---

## Public Contracts

- No external API surface change expected in any phase — all strategies are internal
  automation-loop consumers, not exposed endpoints.
- The 2-trades/day cap, session windows, and trailing-SL mechanism contracts must remain
  unchanged unless a phase explicitly documents and gets sign-off for a behavior change.

---

## Blast Radius

Files directly modified or created (see per-phase Blast Radius sections for exact scope):

- `trading-app/engine/automation.py` (Phase 1)
- `trading-app/workers/auto_trader.py` (Phase 2, Phase 14)
- 11 strategy engine files under `trading-app/engine/strategy_*.py` (Phases 3-13, one per phase)
- `trading-app/engine/execution_gates.py` (Phase 14)
- Associated test files under the existing pytest suite (each phase, additive only)
- 14 phase plan files + 1 umbrella plan file (this program's own artifacts)

Risk class: live-money trading logic (financial/execution surface) — not auth/billing/schema, but
treated with equivalent rigor per the hard safety constraints above (backtest + monitoring window
required before VERIFIED).

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| py_compile on touched engine/worker files (every phase) | Fully-Automated | Fix does not introduce a syntax/compile error |
| backtest_runner.py pre/post signal-count comparison (every phase) | Hybrid (requires historical data fixture) | Each phase's fix only addresses its confirmed finding, does not regress other signal generation |
| Existing + new regression pytest suite (every phase) | Fully-Automated | Confirmed bugs are fixed and cannot silently regress |
| Fresh RESEARCH audit read of each strategy's entry/exit/SL logic | Agent-Probe | Confirms/refutes bug vs rare-by-design vs intentionally-disabled classification per program's Definition of Done |
| Live/paper monitoring window (5 trading days OR 10 signals) per VERIFIED phase | Agent-Probe | Confirms no new structural issue surfaces once a fix is live, per program's "what verified means" bar |

```bash
# Compile check (every phase)
python3 -m py_compile trading-app/engine/*.py trading-app/workers/*.py
# Expected: exit 0, no output

# Backtest verification (per-phase, strategy-scoped)
python3 trading-app/engine/backtest_runner.py --strategy "<Strategy Name>"
# Expected: run completes without error; signal counts pre/post fix are comparable except for the
# specific bug being fixed (false blocks removed / missed window recovered)

# Regression test suite (if pytest suite exists for engine/automation)
pytest trading-app/ -k "<phase-specific selector>"
# Expected: all pass, including new regression test added per phase
```

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md`
- Last completed phase: Phase 0 (this umbrella plan file + 14 phase plans = Phase 0 artifact set)
- Validate-contract status: pending (vc-validate-agent writes per-phase, starting with Phase 1)
- Next step for a fresh agent: Read this umbrella plan, read the Phase 1 plan
  (`phase-01-strategy1-obfvg_PLAN_28-08-26.md`), then run Phase 1 RESEARCH subagent before any
  EXECUTE work. Do NOT jump ahead to later phases — strictly sequential.
- Current phase: Phase 1 — Strategy 1 (OB+FVG)
- Next action: Spawn vc-research-agent for Phase 1, scoped to a fresh audit of
  `trading-app/engine/automation.py`, `engine/signals.py`, `engine/order_blocks.py`, `engine/fvg.py`
- Execute-agent start instruction: Read this file. Read Phase 1 plan. Run research subagent first
  — VALIDATE (PVL) must complete before EXECUTE, even though the name-collision fix is already
  diagnosed.

---

## Current Execution State

Last updated: 28-08-26
Completed phases: Phase 0 (Planning — umbrella + 14 phase plans created)
Current phase: Phase 1 — Strategy 1 (OB+FVG) name-collision + audit
Current loop step: RESEARCH (pending)
Validate-contract status: pending (no phase validated yet)
Program Net Gate: PENDING
Latest validator run: 28-08-26 — plan-artifact structural validators run at kickoff (see chat output)

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append — git history is
the audit log).

---

## Pre-PVL Conflict Resolution

(Orchestrator fills this in before outer PVL begins.) This program is strictly sequential — one
phase executes at a time, no two phases run concurrently — so package-level conflicts between
in-flight phases are not expected. No package conflicts — all phases are parallel-safe for the
purpose of this section, since only one phase plan is active for EXECUTE at any given time; outer
PVL (validating all 14 phase plans as artifacts before any EXECUTE begins) may run in parallel
across phase plans since it is read-only validation of already-written plan text, not concurrent
code execution.

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
