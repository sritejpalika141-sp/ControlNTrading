---
name: note:eval-strat3-clock-injection
description: "Deferred testability gap — eval_strat_3() has no injectable clock parameter, unlike evaluate_orb_strategy()"
date: 28-08-26
metadata:
  node_type: memory
  type: note
  feature: strategy-rebuild
  phase: phase-02
---

# Backlog — clock-injection testability gap for `eval_strat_3()`

**Origin:** strategy-rebuild Phase 02 (Strategy 3 ORB time-window widen). Explicitly deferred
by the phase's INNOVATE decision (rejected alternative B3) and recorded in the phase plan's
`## Backlog Item` section. NOT implemented in Phase 02.

## The gap

`eval_strat_3()` in `trading-app/workers/auto_trader.py` (~line 1996) is a non-exported closure
nested inside `automation_loop()` and takes no injectable `now`/clock parameter. Its sibling in
the engine layer, `evaluate_orb_strategy()` in `trading-app/engine/strategy_orb.py`, already
supports one. This makes `eval_strat_3()` itself impossible to unit-test with a simulated
wall-clock time.

## Recommended follow-up (not done)

Add an optional `now: datetime | None = None` parameter to `eval_strat_3()`, mirroring
`evaluate_orb_strategy()`'s existing pattern, defaulting to `datetime.now(IST)` when not
supplied. This would also require lifting or otherwise exposing the closure so a test can call
it — the whole nested-evaluator family (`eval_strat_2`, `eval_strat_5`, `eval_symbol_strats`,
`run_strat_4`, `run_strat_6`) shares this architecture and this gap, so a follow-up may want to
address the family rather than Strategy 3 alone.

## Why it was deferred

Touching the signature of a live-money trading eval function was judged disproportionate for
Phase 02's single-line window fix. Phase 02 instead extracted the pure time-window comparison
into a module-level helper (`_strat3_orb_window_ok()`), which made the fix fully unit-testable
with zero mocking and zero signature change.

## Reduced scope after Phase 02

Phase 02 shrank this gap in practice: the window-comparison behavior no longer needs clock
injection to be tested. The remaining value of this item is limited to any *future* test that
must simulate real wall-clock time **inside** `eval_strat_3()` itself.

## Technical note for whoever picks this up (preserved from Phase 02 research/validate)

`eval_strat_3()` does `from datetime import datetime` **locally inside the function** (inside its
`try:` block), not via the module-level `datetime` import at `auto_trader.py:16`. A local import
re-fetches `datetime.datetime` from `sys.modules["datetime"]` on every call, so patching a module
attribute path such as `workers.auto_trader.datetime` has **zero effect** — the local import
shadows it. The correct patch target is the global `unittest.mock.patch("datetime.datetime")`,
with `.now.return_value` set to a real localized `datetime` object. Also note the module imports
as `workers.auto_trader` (per `trading-app/tests/conftest.py`'s `sys.path` setup), never
`trading_app.workers.auto_trader` — `trading-app/` is not a valid Python package name.
