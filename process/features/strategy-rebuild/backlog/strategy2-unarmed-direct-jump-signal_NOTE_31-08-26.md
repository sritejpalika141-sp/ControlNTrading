---
name: note:strategy2-unarmed-direct-jump-signal
description: "RESOLVED — Strategy 2 unarmed direct-jump no longer skips the 1-trade/day flag; fixed in Phase 03 supplement (strategy_926.py)"
status: RESOLVED
date: 31-08-26
metadata:
  node_type: memory
  type: report
  feature: strategy-rebuild
  phase: phase-03
---

# Strategy 2 — unarmed direct-jump still emits a signal

**Found during:** strategy-rebuild Phase 03 (Strategy 2 audit), EXECUTE step.
**Status:** RESOLVED / SUPERSEDED (31-08-26). Fixed by a user-approved Phase 03 supplement:
`state.strat_926_triggered = True` was dedented out of the `if strike_info.get('armed')`
block in `trading-app/engine/strategy_926.py` so the 1-trade-per-day flag is consumed
whenever the BUY signal is returned. Pinned by
`test_direct_jump_without_arming_still_sets_triggered_flag` in
`trading-app/tests/test_strategy_926.py`. See the "Supplement fix" addendum in
`process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-03-strategy2_REPORT_31-08-26.md`.

Historical description below (pre-fix).

## What

`trading-app/engine/strategy_926.py`, `evaluate_926_strategy()` monitoring phase:

```python
elif ltp >= _entry:
    if strike_info.get('armed', False):
        logger.info(...)
        state.strat_926_triggered = True

    return {            # <-- at the `elif` level, NOT inside the `armed` check
        ...
    }
```

The `return` is dedented one level relative to the `if strike_info.get('armed', False):`
block. Consequence: a strike whose LTP goes straight to/above `_entry_price` on its very
first observed tick — never having dipped below `_arming_threshold` — **still returns a
full BUY signal dict** to the caller. Only the one-trade-per-day flag
(`state.strat_926_triggered`) is gated on `armed`.

## Why it matters

1. The documented strategy is arm-then-recover (dip below arming, then cross back above
   entry). Today it also fires on a bare threshold cross, which is a different — and on a
   gapping/one-sided open, materially worse — entry.
2. Because `strat_926_triggered` is NOT set on the unarmed path, the "strictly ONE trade
   per day" cap is not consumed by such a signal. If the shared downstream gate stack in
   `auto_trader.py` accepts the signal and places a trade, the strategy could emit a
   further signal in the same 09:26-09:40 window. Live-money impact is therefore not
   purely academic.

## Current coverage

Pinned as a characterization test (asserts the ACTUAL behavior, explicitly labelled as a
known gap, not an endorsement):
`trading-app/tests/test_strategy_926.py::test_direct_jump_without_arming_does_not_set_triggered_flag`

Any future change to this behavior will show up as a diff in that test.

## Suggested fix (for a later phase — NOT done here)

Move the `return {...}` inside the `if strike_info.get('armed', False):` block so the
signal and the one-per-day flag are set atomically on the same condition. This is a real
behavior change on a live-money strategy and needs its own RESEARCH → PLAN → VALIDATE
cycle plus a backtest comparison, not a drive-by edit.

Candidate home: a follow-up Strategy 2 fix phase, or Phase 14 (shared gate stack) if the
downstream gate turns out to already reject unarmed signals — that dependency is
unverified and should be checked first.
