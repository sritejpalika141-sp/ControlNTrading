---
name: note:zero-trade-strategies-1-7
description: "Strategies 1-7 have never produced a real trade (live or paper) — signal-generation root cause, tracked follow-up RESEARCH task"
date: 11-08-26
feature: general
---

# BACKLOG NOTE — Strategies 1-7 Have Zero Real Trades

**STATUS: SUPERSEDED (28-08-26)** by the `strategy-rebuild` phase program.

Closing artifact:
`process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_REPORT_28-08-26.md`

Phase 01 of that program investigated the premise below and found **no shared cross-strategy
dispatch bug for Strategies 1-7 as a group**. The concrete root cause identified and fixed was
narrower and Strategy-1/10/11-specific: `str(strategy).startswith("Strategy 1")` at 3 call sites in
`trading-app/engine/automation.py` also prefix-matched "Strategy 10" and "Strategy 11", so an active
Strategy 10/11 trade silently blocked Strategy 1 from entering (and inflated its daily-cap counter).
Strategy 1's earlier dead period is additionally explained by the since-fixed phantom-expiry bug
(22-Jul-26). The remaining per-strategy questions below are now carried by the `strategy-rebuild`
program's Phases 02-14 (one phase per strategy), not by this note.

Do not re-open this note — route any follow-up to the `strategy-rebuild` program.

---

Opened: 11-08-26. Source: SPEC AC#6 of `strategy-self-improvement_11-08-26`.

## What was observed

As of RESEARCH/SPEC (11-08-26), Strategies 1 through 7 have **zero real trades ever recorded** —
neither live nor paper. Their `swarm_agent_configs` rows carry backtest-derived numbers only, and
`executed_trades` has no rows attributable to them.

## Why this is a distinct problem

This is **not** the backtest-staleness problem that `strategy-self-improvement_11-08-26` fixes.

- Backtest staleness = the *tuning input* was frozen at one stale `run_date`. Fixed by the nightly
  `run_backtests_cron.py` refresh.
- Zero trades = the strategies are not *generating signals* in live/paper execution at all. That is
  a signal-generation / entry-condition problem in the strategy modules themselves, upstream of
  anything nightly learning does.

Fixing the refresh pipeline does not and cannot fix this.

## Scope decision

**CONFIRMED OUT OF SCOPE** for `strategy-self-improvement_11-08-26` — recorded in that effort's
SPEC (AC#6) and PLAN (`## Out of Scope`). This note exists to satisfy AC#6's "tracked follow-up"
requirement, not to investigate.

## Recommended next step

Open a dedicated RESEARCH task once `strategy-self-improvement_11-08-26` has shipped and been
verified over 1-2 nights. That RESEARCH should answer, per strategy 1-7:

1. Is the strategy enabled/approved at all (`status`, `is_paper_trading` in `swarm_agent_configs`)?
2. Does its entry condition ever evaluate true against live market data, or only against the
   backtest's synthetic candle replay?
3. Is it being filtered out upstream (risk orchestrator selection, asset-class gating, market-hours
   gating) before it can ever place an order?
