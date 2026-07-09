---
name: report:phase1-square-off-reentry-guard
description: "Backlog residual — manual automation re-enable during an in-progress emergency square-off can still race with trailing_monitor's exit loop"
date: 03-07-26
metadata:
  node_type: memory
  type: report
  feature: security-remediation
  phase: phase-01
---

# Backlog: Square-off re-entry guard (Phase 1 Item E residual)

## Problem
Phase 1 Item E1 closed the BACKGROUND-loop max-loss race by setting
`state.automation_enabled = False` and `state.hard_exit_triggered = True` BEFORE the
`for pos in open_positions:` square-off loop in `workers/auto_trader.py` (~line 133).

Residual NOT closed: a USER manually re-enabling automation mid-square-off —
via Telegram `/start` (`app.py:2945`) or the toggle-automation API (`app.py:2376`) —
could flip `automation_enabled` back to `True` while `trailing_monitor`'s exit loop is
still closing positions. The next `automation_loop` tick could then open a new position
concurrently with the ongoing emergency exit.

## Why accepted for Phase 1
- Requires precise user-timed action during an active emergency exit (narrow window,
  user-triggered not background-triggered).
- Phase 1's scope is the background-loop race specifically.

## Proposed fix (follow-up, likely Phase 2 or fast-follow)
Introduce a broader "square-off in progress" guard (e.g. `state.square_off_in_progress`)
that the manual re-enable paths (`app.py:2376`, `app.py:2945`) and `automation_loop`
both check before enabling/opening, cleared only after the square-off loop completes.

## Pointers
- `trading-app/workers/auto_trader.py` ~125-160 (square-off block)
- `trading-app/app.py:2376` (toggle-automation), `app.py:2945` (Telegram /start)
