---
name: report:config-drift-validation-check
description: "strategy-rebuild backlog — startup/nightly check cross-referencing every propose_trade call-site strategy name against DB-seeded swarm_agent_configs names (deferred out of Phase 15 scope)"
date: 01-09-26
metadata:
  node_type: memory
  type: report
  feature: strategy-rebuild
  phase: phase-15-backlog
---

# Backlog — Config-Drift Validation Check

**Source:** Phase 15 (`phase-15-risk-orchestrator-name-mismatch_PLAN_31-08-26.md`), INNOVATE
Decision item 4 — explicitly declared OUT of scope for Phase 15 and recorded here instead of built.

## Problem

Phase 15 fixed a live instance of a recurring bug class: `auto_trader.py`'s
`risk_orchestrator.propose_trade()` call sites passed SHORT strategy names ("Strategy 4") while
`swarm_agent_configs` rows are seeded with FULL descriptive names ("Strategy 4: Wisdom-Aligned
Pullback"). The exact-string lookup always missed, silently pinning `effective_win_rate` at 100.0
and the Kelly multiplier at 1.0 for Strategies 1-9.

Phase 15 fixed the call sites and hardened `_get_agent_config()` with an exact-match-on-split
retry + a fallback warning log. That makes a future recurrence *survivable and visible*, but it
does not make it *detectable before it reaches production*.

## Proposed work (not built)

A startup and/or nightly validation check that cross-references every `propose_trade` call-site
strategy-name string against the DB-seeded `swarm_agent_configs` names, and fails loudly (or
alerts via Telegram) on any drift.

Design considerations:
- Call-site names are string literals — a static AST scan of `auto_trader.py` would find them
  without running the trading loop.
- Must handle the legitimately-unseeded call sites (crude/commodity strategies and the AI-strategy
  `ai_name` loop variable) without false-positiving.
- Strategy 10/11 have no bootstrap seed row (created by nightly `update_agent_config()` upsert) —
  a cold-start DB is a valid state, not drift.

## Why deferred

Phase 15's scope was a targeted correctness fix on a live-money path. Building a validation
subsystem inside it would have widened the blast radius well beyond the two files under change.

**Status:** BACKLOG — not scheduled.
