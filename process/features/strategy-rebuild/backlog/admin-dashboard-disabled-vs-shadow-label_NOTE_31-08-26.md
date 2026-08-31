---
name: note:admin-dashboard-disabled-vs-shadow-label
description: "Admin dashboard has no visual distinction between auto-disabled (3 consecutive real losses) and shadow-mode demoted strategies"
date: 31-08-26
metadata:
  node_type: memory
  type: note
  feature: strategy-rebuild
  phase: phase-02-side-investigation
---

# Backlog — admin dashboard: no visual distinction between DISABLED and shadow-demoted strategies

**Origin:** Discovered during a side investigation in the strategy-rebuild Phase 2 UPDATE PROCESS
session (not part of Phase 2's formal scope — Phase 2 is the Strategy 3 ORB window-widen fix). Not
implemented here. Recorded so it is not lost and does not need rediscovery.

## The gap

Two distinct "this strategy is not currently live" states exist in the system, and the admin
dashboard shows a label for only one of them:

1. **Auto-disabled from 3 consecutive real losses** — `swarm_agent_configs.status = 'DISABLED'`.
   This state does surface on the dashboard.
2. **Shadow-mode demoted for net-negative PnL** — tracked in `state.shadow_strategies`. This state
   currently has **no dashboard label at all** — a shadow-demoted strategy looks indistinguishable
   from a normal active strategy at a glance, even though it is not really trading live.

An operator glancing at the dashboard cannot tell these two "not really live" states apart, or
tell either apart from "genuinely active."

## Why this matters now

Strategy 11 (FRVP) was found to currently be in the `DISABLED` state on the live dashboard during
this session's side investigation. Phase 9 of this program (`phase-09-strategy11_PLAN_28-08-26.md`)
is the audit phase for Strategy 11 — whoever runs Phase 9's RESEARCH will need to know Strategy 11
is currently disabled (not just "audit its logic") and should ideally also close this dashboard
labeling gap for both states while it has that strategy in front of it.

## Recommended follow-up (not done here)

Add a distinct dashboard label/badge for shadow-demoted strategies (`state.shadow_strategies`),
separate from the existing `DISABLED` badge, so an operator can distinguish:
- genuinely active
- auto-disabled (3 consecutive real losses, `swarm_agent_configs.status='DISABLED'`)
- shadow-demoted (net-negative PnL, `state.shadow_strategies`)

## Fold-in target

Phase 9 — Strategy 11 (FRVP) audit
(`process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-09-strategy11_PLAN_28-08-26.md`).
Not a hard requirement of Phase 9's own audit scope (which is Strategy 11's entry/exit/SL logic) —
raise it during Phase 9's PLAN-SUPPLEMENT step as an optional scope addition, or split into its own
follow-up if it would grow Phase 9's blast radius beyond a single-strategy audit (dashboard/UI code
is a different surface than `engine/strategy_11_frvp.py`).

## Status

Open, unresolved, not actioned. Do not close without either implementing the label distinction or
an explicit user decision that it is not worth doing.
