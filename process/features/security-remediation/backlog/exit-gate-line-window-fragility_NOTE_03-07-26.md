---
name: report:exit-gate-line-window-fragility
description: "Backlog — replace the Exit Gate #4 fixed-line-window grep with a semantic block check"
date: 03-07-26
metadata:
  node_type: memory
  type: report
  feature: security-remediation
  phase: phase-01
---

# Backlog: Exit Gate #4 line-window fragility (Phase 1 Item F residual)

## Problem
Exit Gate check #4 for the TOCTOU fix uses a fixed line-count window:

    grep -A 60 "async with state.order_lock:" trading-app/app.py | grep -q "record_trade"

This is fragile — if unrelated code is added/removed between the lock statement and
`record_trade()`, the fixed `-A 60` window can silently miss `record_trade` and report a
false FAIL even when the code is correct. It was widened from 40 to 60 lines during VALIDATE
but remains a heuristic, not a semantic check.

## Status in Phase 1
Currently PASSES (record_trade is well within 60 lines of the lock). Execute-agent verified
by reading the indented block directly (instruction E3). Low priority / cosmetic robustness.

## Proposed fix
Replace with a semantic check that parses the indentation block of the `async with
state.order_lock:` statement and asserts `record_trade` appears at a deeper indent inside it
(e.g. a small Python/AST helper), rather than a fixed grep window.

## Pointers
- `trading-app/app.py` place_order (~line 2083 `async with state.order_lock:`)
- Plan: phase-01-critical-security_PLAN_03-07-26.md Exit Gate check #4 + Test Infra Improvement Notes
