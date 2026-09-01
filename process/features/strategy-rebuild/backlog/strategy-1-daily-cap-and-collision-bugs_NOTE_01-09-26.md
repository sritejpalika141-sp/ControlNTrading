---
name: report:strategy-1-daily-cap-and-collision-bugs
description: "strategy-rebuild backlog — two pre-existing Strategy-1 bugs found during Phase 15's PVL sweep: can_trade() daily cap never fires, and an execute_auto_trade() substring collision with Strategy 10/11"
date: 01-09-26
metadata:
  node_type: memory
  type: report
  feature: strategy-rebuild
  phase: phase-15-backlog
---

# Backlog — Strategy 1 Daily-Cap Miss + Strategy 1-vs-10/11 Collision

**Source:** Phase 15's PVL cycle-2 broadened hardcoded-name sweep (validate-contract `## Open
Gaps`), re-confirmed independently during Phase 15 EXECUTE (Step B1c). Both are **pre-existing**,
both are **outside Phase 15's declared Blast Radius**, and neither is caused by, worsened by, or
fixed by Phase 15's call-site rename. Deliberately NOT fixed in Phase 15.

## Bug (a) — Strategy 1 daily trade cap has never fired

- `trading-app/engine/automation.py:733` — inside `can_trade()`:
  `if strategy_name and str(strategy_name).startswith("Strategy 1:"):` guards the
  `STRAT_1_MAX_TRADES_PER_DAY` (default 2/day) cap.
- Its only call site, `trading-app/workers/auto_trader.py:2153`, passes the bare short string:
  `state.can_trade("Strategy 1", signal_type=..., symbol=...)`.
- `"Strategy 1".startswith("Strategy 1:")` is `False` → the cap branch is unreachable → **Strategy 1
  has no enforced daily trade limit today.**
- `automation.py:994` (`add_active_trade()`) carries the same `.startswith("Strategy 1:")` shape and
  should be reviewed together.

**Important:** this `can_trade()` call site is *separate from* the `propose_trade()` call two lines
below it (line 2165), which Phase 15 DID rename. Phase 15 did not touch `can_trade()`'s argument, so
this bug is exactly as broken after Phase 15 as before it.

**Live-money impact:** real — an unenforced daily-trade cap on a live strategy.

## Bug (b) — Strategy 1 substring collision with Strategy 10/11

- `trading-app/workers/auto_trader.py:1190`, inside the shared `execute_auto_trade()`:
  `if "Strategy 1" in strategy_name:` — naive substring containment.
- `"Strategy 1"` is a literal prefix of `"Strategy 10: Adaptive ADX Engine"` and
  `"Strategy 11: FRVP LVN Vacuum"` (both already full-form before Phase 15), so the Strategy-1
  directional-consistency block also fires for every Strategy 10 and Strategy 11 trade.
- This reintroduces, via a second code path, the exact collision bug class that
  `automation.py`'s `has_active_trade_for_strategy()` was hardened against on 28-08-26 (Phase 1).
- `strategy_name` here is `sig.get("strategy", "")` — set by each engine file, not by
  `propose_trade()`'s argument — so Phase 15's rename neither caused nor changed this.

**Proposed fix (both):** apply the same exact-match-on-split pattern already proven in
`has_active_trade_for_strategy()` and now in `risk_orchestrator._get_agent_config()` —
`name.split(":")[0].strip() == "Strategy 1"` — never `startswith`/substring. Add collision
regression tests mirroring `tests/test_risk_orchestrator.py::test_split_retry_is_not_a_prefix_match`.

**Status:** BACKLOG — recommended as a dedicated follow-up phase; live-money correctness, should
not sit indefinitely.
