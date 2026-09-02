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

## Open Questions — Requires User Sign-Off (do NOT silently act on these)

Two findings from Phase 1's OB/FVG audit (`trading-app/engine/signals.py`) are core-entry-intent
candidates per the umbrella's hard safety constraint ("never change a strategy's core entry/exit
intent without flagging it... requiring explicit user sign-off"). Neither was fixed in Phase 1.
Recorded here so a later phase (candidate: Phase 14, shared gate stack, or a dedicated follow-up)
does not have to re-discover them, and so no agent treats silence as approval:

1. **`STRAT1_CONFLUENCE_ONLY = False` (`signals.py:211`).** History: flipped from `True` after
   confluence-only setups "produced zero signals for a week" — but that dead week overlaps the
   since-fixed phantom-expiry bug and Phase 1's name-collision bug, so the zero-signal period may
   have been caused by those bugs, not by confluence-only being genuinely worse. The comment's
   stated compensating safeguard (admit standalone setups only above ">70 confidence") does **not
   exist in code** — confidence is computed as `min(95, 60 + trend_strength/5)` (+15 at a key
   level) and is never gated. The same comment block cites backtest evidence favoring
   confluence-only (win rate 14.7% → 54.8%, max drawdown −348 → −68 pts). Reverting to `True` is a
   plausible fix but is a core entry-intent change — requires explicit sign-off before any agent
   applies it.
2. **Dead counter-trend escape hatch (`signals.py:223`).** `if setup.get("score", 0) < 80: continue`
   is dead code — no setup dict in `all_setups` ever carries a `"score"` key (order-blocks carry
   `impulse_strength`, confluences carry `confluence_score`), so the condition is always true and
   the intended "skip counter-trend setups unless it's a very strong OB" escape hatch never fires.
   Fix options (either changes behavior): populate a real `score` key so the escape hatch works as
   documented, or delete the dead branch and its comment. Requires sign-off on which behavior is
   actually wanted before either change is applied.

**Status:** open, unresolved, not actioned. Do not close either item without an explicit user
decision recorded in a phase report or this section.

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
| 15 (inserted mid-program, ahead of Phase 4 resume) | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-15-risk-orchestrator-name-mismatch_REPORT_01-09-26.md` |
| 16 (inserted mid-program, running alongside Phase 4 resume) | `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-16-strategy1-identity-fixes_REPORT_{dd-mm-yy}.md` |

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Pre-program (plan creation) | 🔨 CODE DONE (this artifact set) |
| 01 — Strategy 1 (OB+FVG) | ✅ VERIFIED |
| 02 — Strategy 3 (ORB) | ✅ VERIFIED |
| 03 — Strategy 2 | ✅ VERIFIED |
| 15 — Risk orchestrator strategy-name mismatch (inserted mid-program 31-08-26) | ✅ VERIFIED (committed + pushed `e9c6d63`, 01-09-26) |
| 16 — Strategy 1 identity fixes: daily-cap bypass + substring collision (inserted mid-program 02-09-26) | 🚧 IN PROGRESS (RESEARCH + INNOVATE done, PLAN written 02-09-26; PVL next) |
| 04 — Strategy 4 | 🚧 RESUMING (Step 1 RESEARCH done, no bug in strategy_wisdom.py itself; Step 2 INNOVATE next; may run in parallel with Phase 16) |
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

Last updated: 02-09-26

Completed phases: Phase 0 (Planning — umbrella + 14 phase plans created); Phase 1 — Strategy 1
(OB+FVG) name-collision fix + entry-logic audit — ✅ VERIFIED (committed `97c901c`); Phase 2 —
Strategy 3 (ORB) 5-minute time-window bug — ✅ VERIFIED (committed `ede705e`); Phase 3 — Strategy 2
(9:26-180 Buy) audit — ✅ VERIFIED (committed `a38fdef`; see prior-session detail below); Phase 15
— Risk orchestrator strategy-name mismatch (inserted mid-program) — ✅ VERIFIED, closed out
01-09-26.

**Phase 16 — Strategy 1 identity fixes (inserted mid-program, this session, 02-09-26) — 🚧 IN
PROGRESS.** Directly resolves the umbrella's own `## HIGH-PRIORITY Open Item` (below) found during
Phase 15's PVL sweep. RESEARCH (dedicated debugger investigation) and INNOVATE (fix approach) are
both complete and folded into the phase plan at creation time. PLAN written and PVL is the required
next step — plan file:
`phase-16-strategy1-identity-fixes_PLAN_02-09-26.md`. This phase runs in parallel with Phase 4's
resume (disjoint files: `auto_trader.py` here vs `strategy_wisdom.py` for Phase 4), per the
umbrella's own prior recommendation.

**Phase 15 closeout summary:** `auto_trader.py`'s `risk_orchestrator.propose_trade()` call sites
passed SHORT strategy-name strings ("Strategy 4") for Strategies 1-9 while `swarm_agent_configs` is
seeded with FULL descriptive names ("Strategy 4: Wisdom-Aligned Pullback"), silently pinning
`effective_win_rate` at 100.0 and the Kelly multiplier at 1.0 for all nine of them. Fixed by
renaming all 9 mismatched call sites to full names, hardening `_get_agent_config()` with an
exact-match-on-split retry (never startswith/substring — same pattern as Phase 1's fix), and adding
a fallback warning log. A cycle-1 PVL FAIL caught a real collateral regression this rename would
have caused (silently freezing the Strategy 3/4/6 daily-trade-cap counters inside
`flush_signals()`) — fixed in the same change (B1b) and pinned by a non-vacuous regression test
(C1's flush-signals-caps case). New `trading-app/tests/test_risk_orchestrator.py`: 27/27 green.
Independent EVL (separate session) re-ran every validate-contract gate command fresh and confirmed
green with no discrepancy from EXECUTE's self-report. Committed and pushed to `origin/main` at
`e9c6d63` ("fix(trading): strategy names didn't match database, breaking fair trade-slot
selection") — verified local HEAD == `origin/main` at this UPDATE PROCESS session. Full detail:
`phase-15-risk-orchestrator-name-mismatch_PLAN_31-08-26.md` (Validate Contract + Phase Loop
Progress) and `phase-15-risk-orchestrator-name-mismatch_REPORT_01-09-26.md`.

**Phase 15's PVL/EVL sweep surfaced 2 new pre-existing bugs, deliberately NOT fixed (out of Phase
15's declared Blast Radius) — see `## HIGH-PRIORITY Open Item` immediately below. Do not miss this
section.**

Prior-session detail (Phase 3, retained for context): Full 7-step inner loop closed
(R→I→P→PVL→E→EVL→UP). Validate-contract: Gate PASS (31-08-26, `generated-by: inner-pvl: phase-3`,
single V1-V7 pass, no CONCERNs). RESEARCH found the two historically-known bugs (duplicate-function
shadowing, phantom-expiry) already fixed; confirmed zero test coverage existed. EXECUTE added a
docstring correction plus a new 7-test regression file (`test_strategy_926.py`); one deviation was
material — the arm-then-recover test discovered a real live-money bug (an unarmed direct-jump
signal bypassed the 1-trade-per-day cap), escalated, user-approved, fixed with a one-line
supplement, EVL-reconfirmed twice. Phase report: `phase-03-strategy2_REPORT_31-08-26.md`. Backlog
note `strategy2-unarmed-direct-jump-signal_NOTE_31-08-26.md` is RESOLVED.

**PHASE 4 STATUS: 🚧 RESUMING now that Phase 15 has closed.** Phase 4 — Strategy 4
(Wisdom-Aligned Pullback), audit-only, no known bug from Phase 0. Phase 4's own RESEARCH (Step 1)
completed 31-08-26 and found no bug in `strategy_wisdom.py` itself for its original scope (the
Phase 15 finding was a side-discovery during that same RESEARCH pass, not part of Phase 4's own
scope — see Phase 15 above). **Documentation-reconciliation note:** Phase 4's own plan file
(`phase-04-strategy4_PLAN_28-08-26.md`) had NOT had its Step 1 checkbox ticked despite this section
previously asserting RESEARCH was done — the two artifacts had drifted out of sync. Reconciled this
session: Phase 4's plan file Step 1 is now ticked with the same finding recorded in both places.
Phase 4's Phase Loop Progress: Step 1 RESEARCH ✅ done; Steps 2-7 (INNOVATE onward) NOT started —
next action is Step 2 INNOVATE.

Current phase: TWO phases active in parallel — Phase 4 (Strategy 4, Wisdom-Aligned
Pullback, resuming) and Phase 16 (Strategy 1 identity fixes, newly inserted).
Current loop step: Phase 4 → INNOVATE (Step 1 RESEARCH already done for Phase 4's own scope). Phase
16 → PVL (Steps 1-2 RESEARCH/INNOVATE already done, folded into the plan at creation time).
Validate-contract status: pending for Phase 4 (placeholder in phase-04 plan file). Pending for Phase
16 (placeholder in phase-16 plan file — inner PVL required before EXECUTE, per
`MID_PROGRAM_PLAN_CREATED`). Phase 15's contract remains closed/PASS and does not apply to either.
Phase 3's contract remains closed/PASS, not reused.
Program Net Gate: PENDING (4 of 14 numbered phases verified — Phases 1, 2, 3 plus the inserted
Phase 15, which is not counted toward the 14-phase baseline total; Phase 16 is also inserted and not
counted toward the 14-phase baseline; 10 numbered phases remain: 4-14 minus the 3 already verified)
Latest validator run: 28-08-26 — plan-artifact structural validators run at kickoff. No harness-file
changes in Phase 3 or Phase 15 (application code + tests + process/context/backlog only in both) —
full regression validator suite (`vc-audit-vc` etc.) intentionally not re-run; not applicable per
§Regression Gate Validators (harness-artifact trigger only). Phase 15's own plan-artifact validator
run reported 4 advisory FAILs/4 warnings against the generic SIMPLE/COMPLEX template — treated as
non-blocking per established precedent for this program's phase-plan shape (see Phase 15's Validate
Contract "Structural note").

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.
**Next action — both paths are now active in parallel (the HIGH-PRIORITY item below has been
converted into Phase 16's plan; no further orchestrator choice needed on whether to investigate —
only on execution order if agent capacity is constrained):**
1. Spawn vc-validate-agent for Phase 16 (inner PVL, V1-V7) — `phase-16-strategy1-identity-fixes_PLAN_02-09-26.md`.
   RESEARCH and INNOVATE are already done; PVL is the next required step per
   `MID_PROGRAM_PLAN_CREATED`.
2. Spawn vc-innovate-agent for Phase 4 Step 2 (resume the paused phase per its own Phase Loop
   Progress in `phase-04-strategy4_PLAN_28-08-26.md`).
Both may run in parallel — they touch disjoint files (Phase 4 touches `strategy_wisdom.py` only;
Phase 16 touches `auto_trader.py` only). If only one can run at a time, prioritize Phase 16's PVL
first, since it concerns whether Phase 1's already-shipped, already-VERIFIED fix (`97c901c`) is
actually correct end-to-end on the real live call path — see the HIGH-PRIORITY section below for
why this matters more than routine backlog priority.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append — git history is
the audit log).

---

## HIGH-PRIORITY Open Item — Phase 1 Fix May Not Cover the Real Live Call Path

**Flagged 01-09-26, during Phase 15's UPDATE PROCESS closeout. This is NOT a routine backlog note —
read this before resuming Phase 4 or treating Phase 1 as fully closed.**

Phase 15's PVL cycle-2 independent re-verification ran a broadened hardcoded-name sweep (beyond
what its own checklist required) and found **two pre-existing, live, unfixed bugs directly adjacent
to Phase 1's already-shipped, already-✅-VERIFIED fix** (`97c901c`, 28-08-26):

1. **`automation.py:733`'s `can_trade()` Strategy-1 daily-cap check requires the caller to pass a
   colon-suffixed string** (`str(strategy_name).startswith("Strategy 1:")`), **but its only call
   site — `auto_trader.py:2153` — passes the bare short string `"Strategy 1"`** (no colon).
   `"Strategy 1".startswith("Strategy 1:")` is `False`. Result: **Strategy 1's daily 2-trade cap
   (`STRAT_1_MAX_TRADES_PER_DAY`) has never actually fired on the real live call path.**
   `automation.py:994` (`add_active_trade()`) carries the identical `.startswith("Strategy 1:")`
   shape and needs the same scrutiny.
2. **`auto_trader.py:1190`, inside the shared `execute_auto_trade()`:**
   `if "Strategy 1" in strategy_name:` — naive substring containment. Since `"Strategy 1"` is a
   literal prefix of `"Strategy 10: Adaptive ADX Engine"` and `"Strategy 11: FRVP LVN Vacuum"`
   (both already full-form), **this check also fires for every Strategy 10 and Strategy 11 trade** —
   reintroducing, via a second, different code path, the exact "Strategy 1 vs 10/11 collision" bug
   class that Phase 1's `has_active_trade_for_strategy()` fix was specifically built to prevent.

**Why this is high-priority, not routine backlog:** Phase 1's report and this program's Program
Status Table both mark Phase 1 ✅ VERIFIED with 34 passing tests as proof. But Phase 15's sweep
found that the *actual live call site* (`auto_trader.py:2153`, `:1190`) uses a code path these two
bugs live on — a path that may be **different from what Phase 1's 34 tests exercised**. Two
concrete unknowns need resolving before anyone should treat Phase 1 as fully proven end-to-end:
- Did Phase 1's regression suite call `can_trade()` / `execute_auto_trade()` through the same
  argument-passing route `auto_trader.py` actually uses in production, or did it test
  `has_active_trade_for_strategy()` and a synthetic harness that never exercised these two adjacent
  functions' own argument-matching bugs?
- Is it possible Phase 1's fix is *itself* correct and fully tested, but simply narrower in scope
  than these two adjacent, never-fixed call sites — i.e., Phase 1 fixed one function
  (`has_active_trade_for_strategy`) while `can_trade()` and `execute_auto_trade()`'s own
  independent hardcoded-string checks were never in Phase 1's Blast Radius at all?

Both bugs are **confirmed independent of, unaffected by, and not caused by** Phase 15's own fix
(Phase 15 only renamed `propose_trade()`'s argument two lines away from the `can_trade()` call site
at `:2153`, and did not touch `execute_auto_trade()`'s `sig["strategy"]`-fed check at `:1190`).
They are real, live, currently-active gaps in a live-money system's daily-trade-cap and
strategy-collision defenses.

**RESOLVED INTO A PHASE (02-09-26):** this item is no longer an open recommendation — a dedicated
debugger investigation confirmed both bugs exhaustively, and a full phase plan was created:
`phase-16-strategy1-identity-fixes_PLAN_02-09-26.md`. RESEARCH and INNOVATE are complete; PVL is the
next step before EXECUTE. See that plan for the full fix approach (hoist a shared `strat_name`
local in `run_strat_1()` for Bug 1; exact-match-on-split at `auto_trader.py:1190` for Bug 2) and its
Open Questions section for the still-undecided directional-guard design question. This phase runs in
parallel with Phase 4's resume per the recommendation below (disjoint files).

Backlog note (full technical detail, proposed fix — now superseded by the Phase 16 plan itself, kept
for historical trace): see
`## Backlog Items (cross-phase index)` → `strategy-1-daily-cap-and-collision-bugs_NOTE_01-09-26.md`
below.

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

## Audit-Phase Methodology Note

**[Found in Phase 3 — apply this lens to every remaining audit-only phase: 4, 6, 7, 8, 9, 10, 11]**
Phase 3 was scoped "audit-only, no known bug" per Phase 0's baseline research — a plain code review
of `strategy_926.py` genuinely found no live bug (both historical bugs were confirmed already
fixed). The real bug (unarmed direct-jump signal bypassing the 1-trade/day cap) was found only
because EXECUTE **wrote a regression test that exercised the actual runtime path** (arm-then-recover
vs. bare threshold cross), not by re-reading the source. A static code review of the same lines
would very plausibly have missed it, since the bug is about *dedent depth relative to a guard
clause* — exactly the kind of thing that reads fine at a glance and only breaks under an executed
scenario.

**Lesson for Phases 4, 6-11 (all still audit-only, no known bug from Phase 0):** treat writing the
regression-test suite as part of the investigation, not a formality bolted on after RESEARCH
concludes "no bug found." RESEARCH's job is scoping and reading the source; INNOVATE's "no fix
needed" verdict should be held provisional until EXECUTE's test-writing pass has actually exercised
each documented behavior (window enforcement, one-shot/one-trade flags, arm/trigger sequencing,
sizing math, fallback paths) against the live function — not just asserted from reading it. If
EXECUTE's tests surface a real behavior gap, escalate via the same pattern used here: document,
seek explicit user sign-off (this is audit-only scope, not a license for silent fixes), fix
minimally if approved, pin with a renamed/updated test, and mark the backlog note RESOLVED with a
pointer to the fix. Do not treat "audit-only" as "test-writing is optional cleanup" — it is the
actual verification mechanism for the program's "verified" bar per the Program Goal Charter's
Definition of Done.

## Test Infra Improvement Notes

**[Found in Phase 3 — concrete guidance for every remaining phase: fix the pytest-hang workaround
now, don't rediscover it 8 more times]** `cd trading-app/tests && python3 -m pytest -q` (the
documented workaround for the root-level `test_*.py` collection break) finishes its actual test run
and prints the summary line in ~15s, but the **process itself does not exit** afterward — a
foreground run of this command therefore appears to hang forever. Confirmed pre-existing (reproduces
identically on a `git stash`ed baseline, not caused by any strategy-rebuild phase's changes) —
almost certainly a non-daemon thread or unclosed event loop left behind by one of the suite's own
modules. **Concrete workaround for every remaining phase (4, 5, 6-14): never run this command in the
foreground and wait on it.** Instead redirect output to a file and poll/kill once the summary line
appears, e.g.:
```bash
cd trading-app/tests && (python3 -m pytest -q > /tmp/pytest_out.txt 2>&1 &) ; sleep 20 && cat /tmp/pytest_out.txt
pkill -f "pytest -q" 2>/dev/null  # reap the hung process once the summary has been read
```
(Exact polling mechanics are the executing agent's choice — the invariant is: redirect to a file,
poll for the summary line, then kill the process; do not block a foreground shell call on this
command.) Root-causing the hang (find and close the leaked thread/loop) is a separate, not-yet-scoped
follow-up — raise it as a dedicated fix phase or fold into Phase 14 if time allows; not required to
unblock any individual audit phase since the workaround above is sufficient.

**[Found in Phase 1 — flag for every subsequent phase, do not re-discover from scratch]**
`trading-app/engine/backtest_runner.py` has **no CLI entrypoint** — no `__main__` block, no
`argparse`, no arg handling. It is a library module exposing
`async backtest_strategy(strategy_name, real_client, days_back)`, which requires a **live Fyers
client** to fetch historical candles. Every phase plan in this program (1-14) names a
`backtest_runner.py --strategy "<name>"` command as a Hybrid test gate — as written, that command
is a **silent no-op** (imports cleanly, exits 0, prints nothing; it is not a real gate as invoked
from the shell). Phase 1 hit this and recorded it as a known-gap rather than blocking the phase
(materiality was low there because zero strategy-logic files changed).

This will very likely recur for Phases 2-14, several of which depend on the backtest gate more
heavily than Phase 1 did (e.g. Phase 2's ORB window-bug fix is exactly the kind of change a backtest
should catch). Two resolution options, to be decided once (not re-litigated per phase):
1. Add a real `argparse`/`__main__` entrypoint to `backtest_runner.py` backed by a recorded-candle
   fixture (no live broker dependency) — turns it into a genuine Fully-Automated/Hybrid gate.
2. Reclassify every backtest-gate row across Phases 2-14's plans as Agent-Probe/Known-Gap up front,
   and rely on the pytest regression-test tier (as Phase 1 did) as the actual proof of each fix.
Recommendation: raise this decision explicitly at or before Phase 2's PLAN-SUPPLEMENT step, since
Phase 2 is a window/timing bug that a working backtest would verify well. Not resolved by this
UPDATE PROCESS session — flagging only, per orchestrator instruction not to silently act on it.

**[Found in Phase 15 — cleanup item, non-blocking, added at UPDATE PROCESS 01-09-26]** Two
pre-existing, unrelated test failures were hit while running Phase 15's regression sweep
(`test_p0_fixes.py::test_gap_strategy_filters_todays_candles_with_unix_ts` — fails with "no current
event loop"; `test_auto_trader.py::test_atr_sl_field_separation` — a source-string assertion about
`t["trailing_sl_price"]`). Both were reproduced identically on the unmodified pre-Phase-15 files via
`git stash` — confirmed unrelated to Phase 15's own changes, not a regression it introduced. Not
blocking any phase; worth a dedicated test-suite cleanup pass whenever one is scheduled (candidate:
fold into Phase 14's shared-infrastructure phase, or a standalone maintenance task).

`process/context/tests/all-tests.md` is still the unfilled `vc-setup` template (routing table is
commented-out placeholders) — Phase 1 derived test commands from the validate-contract and direct
inspection instead of this router. Filling it in would remove this repeated workaround for every
remaining phase.

**[Found in Phase 2, confirms a pattern first hit in Phase 1 — now CONFIRMED TWICE, treat as
settled fact for every remaining phase, do not re-discover]** `pytest trading-app/` (bare, or the
umbrella's own literal `pytest trading-app/ -k "<selector>"` test-gate command as written in every
phase plan) does **not run** — pytest collects root-level diagnostic scripts under `trading-app/`
that are named `test_*.py` (e.g. `test_webhook.py`, `test_mcx_quote.py`, `test_fyers_token.py`,
`test_active_symbols.py`) but are not real test modules; several call `sys.exit(1)` at import time,
which pytest turns into `INTERNALERROR> SystemExit: 1` before any real test runs. Phase 1 and Phase
2 both hit this independently and both worked around it the same way: **scope every test-gate
command to `trading-app/tests/` specifically** (the actual suite root `conftest.py` serves), e.g.
`pytest trading-app/tests/ -k "<selector>"` instead of `pytest trading-app/ -k "<selector>"`. Every
phase plan (3-14) that copies the umbrella's literal gate-command template should apply this scoping
from the start rather than rediscovering the INTERNALERROR each time. Two resolution options exist
if a phase wants to fix the root cause instead of continuing to work around it (not required, not
blocking): (1) rename the root-level diagnostic scripts away from the `test_*.py` pattern, or (2)
add a `testpaths = trading-app/tests` (or `norecursedirs`) entry to a pytest config file. Neither is
in scope for any phase unless explicitly picked up.

**[Found in Phase 2 — line-number drift warning for all remaining phases]** Phase 2's EXECUTE added
a new module-level function (~7 lines) to `trading-app/workers/auto_trader.py`. Every line number
in that file at or after the insertion point (~line 188) is now shifted **+7** relative to any
cached line numbers from Phase 0's baseline research or from Phase 1's/Phase 2's own RESEARCH notes.
Any later phase whose blast radius touches `auto_trader.py` (per the umbrella's Touchpoints table:
Phase 14's directional-regime-gate / MTF-alignment-gate sections) must **re-grep for exact line
numbers at RESEARCH time**, not trust any previously-recorded line number for that file. This is the
same discipline Phase 2's own plan already enforced for its own edits ("re-confirm the exact current
line number before editing") — the lesson generalizes to every subsequent phase touching a
file another phase has already modified, not just to editing your own phase's target lines.

---

## Backlog Items (cross-phase index)

- `process/features/strategy-rebuild/backlog/strategy2-unarmed-direct-jump-signal_NOTE_31-08-26.md`
  — **RESOLVED (31-08-26).** Found during Phase 3 EXECUTE test-writing: an unarmed direct-jump to
  entry price in Strategy 2 returned a full BUY signal without consuming the 1-trade-per-day flag.
  User-approved supplement fix landed same phase (one-line dedent); pinned by
  `test_direct_jump_without_arming_still_sets_triggered_flag`; committed at `a38fdef`. No
  follow-up action required.
- `process/features/strategy-rebuild/backlog/eval-strat3-clock-injection_NOTE_28-08-26.md` —
  clock-injection testability gap for `eval_strat_3()` (deferred from Phase 2; not blocking any
  phase; pick up opportunistically or as a dedicated follow-up).
- `process/features/strategy-rebuild/backlog/admin-dashboard-disabled-vs-shadow-label_NOTE_31-08-26.md`
  — admin dashboard has no visual distinction between auto-disabled (3 consecutive real losses,
  `swarm_agent_configs.status='DISABLED'`) and shadow-mode demoted (`state.shadow_strategies`)
  strategies; discovered via a side investigation during Phase 2's UPDATE PROCESS session (not part
  of Phase 2's formal scope). Strategy 11 (this program's Phase 9 subject) is currently `DISABLED`
  on the live dashboard — fold this item into Phase 9's PLAN-SUPPLEMENT step as an optional scope
  addition, or split it into its own follow-up if it would grow Phase 9's blast radius beyond a
  single-strategy engine-logic audit (dashboard/UI code is a different surface).
- `process/features/strategy-rebuild/backlog/strategy-1-daily-cap-and-collision-bugs_NOTE_01-09-26.md`
  — **SUPERSEDED by Phase 16 (02-09-26).** Found during Phase 15's PVL cycle-2 sweep (01-09-26),
  confirmed independently unrelated to and unaffected by Phase 15's own fix. Two live bugs: (a)
  `automation.py:733`'s `can_trade()` Strategy-1 daily-cap check requires a colon-suffixed name but
  its only call site (`auto_trader.py:2153`, inside `run_strat_1()`) passes the bare short string —
  the cap has never fired. (b) `auto_trader.py:1190`'s `execute_auto_trade()` uses naive substring
  containment (`"Strategy 1" in strategy_name`), which also matches Strategy 10/11's full names — a
  second, independent instance of the exact collision class Phase 1's
  `has_active_trade_for_strategy()` fix was built to prevent. Both bugs are now scoped into a full
  phase plan: `phase-16-strategy1-identity-fixes_PLAN_02-09-26.md` (RESEARCH + INNOVATE complete,
  PVL next). This backlog note is retained for historical trace only — the phase plan is now
  authoritative.
- `process/features/strategy-rebuild/backlog/config-drift-validation-check_NOTE_01-09-26.md` —
  linked here per Phase 15's INNOVATE Decision item 4 (explicitly out of Phase 15's scope). Proposes
  a startup/nightly check cross-referencing every `propose_trade` call-site strategy-name string
  against DB-seeded `swarm_agent_configs` names, so a future name-mismatch (the same bug class
  Phase 15 just fixed) is caught before reaching production rather than discovered by audit again.
  Not scheduled; pick up as a dedicated follow-up when capacity allows.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
