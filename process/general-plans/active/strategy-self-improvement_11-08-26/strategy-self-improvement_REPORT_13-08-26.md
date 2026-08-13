---
phase: strategy-self-improvement
date: 2026-08-13
status: COMPLETE_WITH_GAPS
feature: general
plan: process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_PLAN_11-08-26.md
---

# EXECUTE REPORT — Strategy Self-Improvement Pipeline

## What Was Done

Implementation Checklist items 1–21 complete. Item 22 (1–2 night observation) is inherently
deferred; item 23 (commit) is deliberately left to the orchestrator post-EVL.

**Files touched (6):**
- `trading-app/models.py` — `stats_source` column on `swarm_agent_configs` (CREATE + ALTER
  migration + backfill), new `backtest_refresh_status` single-row table,
  `set_backtest_refresh_status()` / `get_backtest_refresh_status()` helpers, `stats_source` kwarg
  on `update_agent_config()`, explicit `stats_source='live'` at the `record_trade_outcome()` call.
- `trading-app/engine/nightly_learning.py` — `stats_source='backtest'` on all 5
  `update_agent_config()` call sites.
- `trading-app/run_backtests_cron.py` — NEW standalone cron entry point.
- `trading-app/static/app.js` — provenance badge under Win Rate and Total Trades.
- `trading-app/static/admin.html` — badge on both renderers (swarm-status card + admin card).
- `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` — NEW backlog stub.

**VM crontab installed:** `20 15 * * * cd /home/sritejpalika/trading-app && .venv/bin/python3 run_backtests_cron.py >> logs/backtest_cron.log 2>&1`

## Test Gate Outcomes

| Gate | Tier | Result |
|---|---|---|
| `py_compile` 3 files (local + VM) | Fully-Automated | PASS |
| `precommit_check.py` | Fully-Automated | PASS (180 files, 18 tests) |
| `smoke_test.py` (local + VM) | Fully-Automated | PASS |
| Migration safety (before/after values) | Fully-Automated | PASS — all `win_rate`/`total_trades` byte-identical; 0 NULL `stats_source` |
| AC#6 backlog stub | Fully-Automated | PASS |
| AC#1 `run_date` advances | Hybrid | PASS — `2026-08-05` (pinned) → `2026-08-13`, 13/13 saved |
| CAUTION cron runtime | Hybrid | PASS — **157 s (2 m 37 s)**, far below the 10-min threshold; 15:20 IST stands |
| AC#2 failure path | Agent-Probe | PASS (4/4) — log line, Telegram webhook resolved + sent, status row `FAILED`, `backtest_results` unchanged (39 rows both sides) |
| AC#4/AC#5 badges | Agent-Probe | PASS — markup deployed and served (4 hits in each asset), API exposes `stats_source`, and all 11 rows now carry an accurate label after the G1 correction |
| AC#3 shadow-out unregressed | Hybrid | DEFERRED — needs 2 post-fix nightly runs |

## Plan Deviations

All three are within blast radius (same files the plan designates), documented inline in code.

1. **`_candidate_user_ids()` replaces the `USER_STATES` loop.** The plan's sketch looped
   `state.USER_STATES`, which is populated lazily by the long-running app process and is
   **always empty in a fresh standalone cron process** (`state.py:45`) — the loop would have found
   zero users and failed every single night. Now reads active ids from the `users` table; identical
   semantics ("first authenticated client wins").
2. **`_resolve_webhook_url()` reads `logs/trading_state_1.json`.** The plan's
   `get_user_state(1).webhook_url` returns `""` standalone (no hydration). The real persisted
   source is the state JSON that `engine/automation.py:231` hydrates from. Verified: that file
   holds the live Telegram webhook, while `user_states.webhook_url` is empty for every user. This
   deviation is *closer* to plan intent than a literal reading would have been.
3. **Backfill is ALTER-guarded, not date-gated.** The plan's
   `WHERE ... last_updated < '2026-08-11'` assumed same-day EXECUTE. EXECUTE ran 13-08-26, and
   `nightly_learning` had rewritten the backtest-derived rows at `2026-08-11 15:18` — i.e. *not*
   `< '2026-08-11'` — so the literal form tagged the exact rows SPEC AC#5 targets as `live`, the
   opposite of the plan's stated intent. Replaced with an idempotent-by-construction backfill
   inside the ALTER `try` block; date-free, cannot later mis-flip a genuinely live row.

Nothing in the protected set was touched: `engine/risk_orchestrator.py` Kelly path untouched;
`nightly_learning.py` lines 272–326 capital-protection block untouched (verified — the 5 edits are
single-kwarg additions at lines 244, 269, 409, 435, 453).

## What Was Skipped or Deferred

- Checklist #22 — 1–2 night observation (AC#3 shadow-out, AC#1 second-night advance).
- Checklist #23 — commit, deliberately left to the orchestrator after EVL.

## Gaps / Open Items

### G1 — RESOLVED 13-08-26 (user-approved, targeted correction)

The blanket `UPDATE` originally proposed was **rejected** by the coordinator and NOT run. Instead a
row-by-row provenance re-verification was performed, then a single targeted `UPDATE ... WHERE
strategy_name IN (...)` naming exactly the 5 confirmed-mislabeled strategies.

**Evidence used** — config-row numbers cross-referenced against real `executed_trades` counts and
against the `2026-08-05` backtest snapshot that was current when those rows were written
(`2026-08-11 15:18`):

| Strategy | config row | real `executed_trades` | Aug-05 backtest | Verdict |
|---|---|---|---|---|
| Strategy 1: OB + FVG | 42 / 11.9% | **0** | 42 / 11.9 | exact backtest match → mislabeled |
| Strategy 8: Smart Money Concepts | 159 / 18.2% | 5 | 158 / 17.7 | backtest base 158 (+1) → mislabeled |
| Strategy 9: 9-EMA Momentum Scalper | 79 / 13.9% | 1 | 79 / 13.9 | exact backtest match → mislabeled |
| Crude EIA Volatility | 63 / 11.1% | 2 | 63 / 11.1 | exact backtest match → mislabeled |
| Strategy 11: FRVP LVN Vacuum | 133 / 26.3% | 8 | 131 / 26.0 | backtest base 131 (+2) → mislabeled |

**The coordinator's hypothesis that Strategy 11 / Crude EIA might legitimately be `'live'` did not
survive the data.** Strategy 11's config says 133 trades against only 8 real ones, and Crude EIA
says 63 against 2 — both numbers are dominated by the backtest base, not by real trade history.
`Crude Evening Momentum` was also named in the hypothesis but has **no `swarm_agent_configs` row at
all**, so there was nothing to relabel. The 6 rows already tagged `backtest` were left untouched.

**Backup taken before writing** (per engagement discipline):
`trading_app.db.bak-20260813162440` (6,414,336 bytes, on the VM).

**Before → after** (`SELECT strategy_name, stats_source, total_trades, win_rate FROM swarm_agent_configs;`):

```
BEFORE                                                    AFTER
Crude EIA Volatility            live      63   11.1   →   backtest  63   11.1
Strategy 11: FRVP LVN Vacuum    live     133   26.3   →   backtest 133   26.3
Strategy 1: OB + FVG            live      42   11.9   →   backtest  42   11.9
Strategy 2: 9:26 - 180 Buy      backtest   0    0.0   →   backtest   0    0.0   (untouched)
Strategy 3: 5-Minute ORB        backtest   0    0.0   →   backtest   0    0.0   (untouched)
Strategy 4: Wisdom-Aligned      backtest   0    0.0   →   backtest   0    0.0   (untouched)
Strategy 5: Optimized Aerosp.   backtest   0    0.0   →   backtest   0    0.0   (untouched)
Strategy 6: Gap Fill Reversal   backtest   0    0.0   →   backtest   0    0.0   (untouched)
Strategy 7: Swing-Pivot Break.  backtest   0    0.0   →   backtest   0    0.0   (untouched)
Strategy 8: Smart Money Conc.   live     159   18.2   →   backtest 159   18.2
Strategy 9: 9-EMA Momentum      live      79   13.9   →   backtest  79   13.9
```

`rows updated: 5`. Remaining `live` rows: 0. NULL rows: 0. Every `win_rate`/`total_trades` value is
unchanged — only the provenance label moved. Post-write health: service `active`, single uvicorn
process (MainPID 3711748), HTTP 200.

Going forward, correctness is self-maintaining: `record_trade_outcome()` writes an explicit
`stats_source='live'` and `nightly_learning.py` writes `stats_source='backtest'`, so the first real
trade on any strategy flips its own label.

### G1 — original finding (historical, for the record)

Because deviation #3's corrected backfill only fires when the `ALTER` succeeds, and the column was
already added by the first deploy (which ran the stale date-gated form), these 5 rows on the live
VM are still tagged `live` when they are provably backtest-derived:

| Strategy | config row | latest backtest row |
|---|---|---|
| Strategy 1: OB + FVG | 42 trades / 11.9% | 42 / 11.9 |
| Strategy 8: Smart Money Concepts | 159 / 18.2% | 158 / 17.7 |
| Strategy 9: 9-EMA Momentum Scalper | 79 / 13.9% | 79 / 13.9 |
| Crude EIA Volatility | 63 / 11.1% | 63 / 11.1 |
| Strategy 11: FRVP LVN Vacuum | 133 / 26.3% | 131 / 26.0 |

Only 24 real `executed_trades` exist in total, so none of these counts can be live-derived. This is
exactly the misleading Strategy 8 case SPEC AC#5 exists to prevent — and it currently renders a
*wrong* `(live)` badge, which is worse than no badge.

The originally proposed blanket `UPDATE swarm_agent_configs SET stats_source='backtest';` was
**rejected and never executed** — superseded by the targeted, evidence-verified fix above.

**G2 — recorded as backlog, not fixed (out of scope).**
`process/general-plans/backlog/telegram-webhook-resolution-broken_NOTE_13-08-26.md`
`user_states.webhook_url` is empty for all users and `TELEGRAM_WEBHOOK` is unset;
`check_nightly_learning_report.py:165` and `nightly_learning.py:316`/`:392` both resolve that empty
source, so their Telegram alerts have likely been silently failing. `run_backtests_cron.py`
sidesteps this via deviation #2; the sibling scripts were not modified.

**G3 — recorded as backlog, not fixed (out of scope).**
`process/general-plans/backlog/nightly-report-cron-never-scheduled_NOTE_13-08-26.md`
The VM crontab was empty before this deploy — no user crontab, no root crontab, no `/etc/cron.d`
entry, no systemd timer — so `check_nightly_learning_report.py` has never been scheduled.

## Test Infra Gaps Found

None new. Confirmed as documented in SPEC/PLAN: no automated harness covers
`nightly_learning.py` / `backtest_runner.py` / the `swarm_agent_configs` write paths, which is why
AC#1–AC#5 are Hybrid/Agent-Probe rather than Fully-Automated.

## Closeout Packet

- **Selected plan:** `process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_PLAN_11-08-26.md`
- **Finished:** checklist 1–21, all local + VM gates green, cron installed, dry-run 157 s.
- **Verified:** AC#1, AC#2, AC#4, AC#5, AC#6, all regression gates, migration safety, G1 correction.
- **Unverified:** AC#3 (needs 2 post-fix nightly runs).
- **Remaining:** 1–2 night observation (AC#3 + AC#1 second-night advance); commit.
- **Classification:** `Keep in active/testing` — code-complete, verification ongoing.

## Forward Preview

- **Test Infra Found:** `precommit_check.py` (syntax + cycles + 18 unit tests) and
  `smoke_test.py` (import + `app:app` construct) are the only automated gates; both fast and
  reliable. `sqlite3` CLI is **absent** on the VM — use `.venv/bin/python3 -c "import sqlite3..."`.
  `/usr/bin/time` is also absent — use `S=$(date +%s)` bracketing.
- **Blast Radius Changes:** none beyond the plan's 6 files + crontab.
- **Commands to Stay Green:** `python3 -m py_compile trading-app/models.py trading-app/engine/nightly_learning.py trading-app/run_backtests_cron.py`; `python3 trading-app/precommit_check.py`; VM `.venv/bin/python3 smoke_test.py`.
- **Dependency Changes:** none — no new packages.
