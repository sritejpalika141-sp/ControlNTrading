---
name: plan:strategy-rebuild-phase-09-strategy11
description: "Strategy Rebuild — Phase 09: Strategy 11 (FRVP) — Audit"
date: 28-08-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: phase-09
---

# Phase 09 — Strategy 11 (FRVP) — Audit

**Program:** strategy-rebuild
**Umbrella plan:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-09-strategy11_REPORT_{dd-mm-yy}.md (flat in the program task folder)

---

## Purpose

Audit-only pass on Strategy 11 (active strategy, Tier 2) to confirm entry/exit/SL logic is correct; apply minor cleanup if a bug is confirmed. Also re-confirm no residual cross-block with Strategy 1/10 remains after Phase 1's fix.

**This is a lightweight stub.** Purpose and known Blast Radius below are best-known from Phase 0
research; the Implementation Checklist is a placeholder only. This phase will be fully fleshed out
via its own RESEARCH pass when the program reaches it — do not trust the file mapping or scope
below as final without re-verifying against current code.

**[Added at Phase 2's UPDATE PROCESS, 31-08-26 — read before RESEARCH]** Strategy 11 was found to
be currently `DISABLED` on the live dashboard during a side investigation (`swarm_agent_configs.status
= 'DISABLED'`, auto-disabled from 3 consecutive real losses) — RESEARCH should confirm this and
factor "why is it disabled" into the audit, not just review logic in isolation. Also carries a
folded-in backlog item (optional scope addition, not a hard requirement):
`process/features/strategy-rebuild/backlog/admin-dashboard-disabled-vs-shadow-label_NOTE_31-08-26.md`
— the admin dashboard has no visual distinction between this `DISABLED` state and a separate
shadow-mode-demoted state (`state.shadow_strategies`). Raise both at this phase's PLAN-SUPPLEMENT
step; if the dashboard-label fix would grow this phase's blast radius beyond a single-strategy
engine-logic audit (dashboard/UI code is a different surface than `engine/strategy_11_frvp.py`),
split it into its own follow-up instead of bundling it silently.

---

## Entry Gate

- Phase 8 complete (validated, committed)

---

## Blast Radius

- trading-app/engine/strategy_11_frvp.py

(Best-known from this session's research — RESEARCH step for this phase must re-confirm exact
file(s) and line ranges before INNOVATE/PLAN-SUPPLEMENT proceed.)

---

## Implementation Checklist

### Step A — Fresh RESEARCH pass (placeholder)

- [ ] A1. Fresh RESEARCH pass on this strategy (do not trust Phase 0's summary-level findings
      alone — re-verify against current code).

### Step B — Fix (placeholder)

- [ ] B1. Apply audit + targeted fix per RESEARCH findings (or record "no fix needed, confirmed
      working as intended" if the audit finds nothing).

---

## Exit Gate

```bash
# Compile check (placeholder — narrow to the confirmed file(s) once RESEARCH completes)
python3 -m py_compile trading-app/engine/*.py trading-app/workers/*.py
# Expected: exit 0, no output

# Backtest verification (placeholder — scope to this strategy once confirmed)
python3 trading-app/engine/backtest_runner.py --strategy "<Strategy Name>"
# Expected: runs without error; signal counts pre/post fix comparable except for the specific
# finding being addressed
```

- All checklist items checked
- py_compile and regression tests green
- Backtest pre/post comparison documented (or "no fix needed" finding documented with rationale)
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 08 exit gate not yet passed (strictly sequential program — this phase cannot start early)
- RESEARCH reveals the file mapping above is stale/incorrect and the real target file cannot be
  identified without user input
- RESEARCH reveals a core entry/exit-intent change is needed (not a pure bug fix) — requires
  explicit user sign-off before proceeding, per umbrella hard safety constraints

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase report read; test context loaded; fresh audit of
      this strategy's current code completed (re-verify Blast Radius above)
- [ ] 2. INNOVATE — innovate-agent: approach decided; Decision Summary written
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this stub fleshed out into a full checklist with concrete
      file paths and line references (or "n/a — research clean" if truly nothing to add)
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md`
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- trading-app/engine/strategy_11_frvp.py

---

## Public Contracts

- No external API surface change expected — internal automation-loop logic only.
- This strategy's core entry/exit intent must remain unchanged unless RESEARCH surfaces and gets
  sign-off for a genuine behavior fix.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `python3 -m py_compile` on the confirmed target file(s) | Fully-Automated | Fix does not introduce a syntax/compile error |
| Existing + new regression tests for this strategy | Fully-Automated | Confirmed bug fix does not regress; TBD exact tests pending RESEARCH |
| `backtest_runner.py` pre/post signal-count comparison | Hybrid (requires historical data fixture) | Fix only addresses the confirmed finding, does not alter unrelated signal generation |
| Fresh audit read of this strategy's entry/exit/SL logic | Agent-Probe | Confirms (or refutes) further structural issues beyond any already-known finding |

```bash
# Verification command — run after phase complete
git log --oneline -1 -- trading-app/engine/strategy_11_frvp.py
# Expected: shows this phase's commit (or no commit if "no fix needed" finding)
```

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-09-strategy11_PLAN_28-08-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) once Phase 08 is complete —
  do not start early even under autonomous /goal execution (strictly sequential program).

---

## Test Infra Improvement Notes

(none identified yet)

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
