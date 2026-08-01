# Strategy 3 (ORB) + Strategy 9 (AI EMA) — Backtest & Hardening Plan

**Date:** 31-07-26  
**Scope:** Deep-dive validation for the two highest-impact intraday strategies after P0 fixes.  
**Charter:** Prove edge with historical replay before increasing live sizing.

---

## Executive summary

| Strategy | Role | Maturity | Priority action |
|----------|------|----------|-----------------|
| **S3 — 5-Min ORB** | Morning breakout (9:20–10:30) | **High** — most complete checklist | Backtest 90d NIFTY; tune volume/gap filters |
| **S9 — AI 9-EMA Retest** | Mid-session LLM + rules | **Medium** — ADX now real (P0 fix) | Shadow-mode paper replay; reduce LLM cost |

---

## Strategy 3: 5-Minute ORB — technical deep-dive

### Entry logic (current)

1. Opening range = first 5m candle (9:15–9:20 IST).
2. **VIX > 15:** live spot cross of ORB high/low (aggressive).
3. **VIX ≤ 15:** wait for 5m **close** outside range (cautious).
4. Checklists: volume ≥ 2× historical 9:20 avg; gap < 1%; ORB width < 0.5%; economic events (stub).

### Strengths

- Institutional ORB pattern with VIX-adaptive entry mode.
- Direct option routing with ITM/ATM preference (`dte=0`).
- SL capped at 50 option points; T1/T2 targets defined.

### Weaknesses / test focus

| Risk | Test |
|------|------|
| Volume fallback uses all-history avg when no prior 9:20 bars | Measure false positives on low-volume days |
| Economic calendar always `True` | Inject RBI/Budget blackout dates in backtest |
| Hardcoded 0.55 delta for SL sizing | Sensitivity sweep 0.45–0.65 |
| One trade/day — missed re-entry after failed breakout | Compare vs 2-trade cap variant |

### Backtest protocol

```bash
cd trading-app
# Extend scripts/run_backtests.py OR add scripts/backtest_orb.py
.venv/bin/python scripts/backtest_orb.py \
  --symbol NSE:NIFTY50-INDEX \
  --days 90 \
  --output reports/orb_backtest_90d.json
```

**Metrics to capture:** win rate, avg R, max consecutive losses, trades/month, skip reasons (volume/gap/range).

**Pass gate:** win rate ≥ 45% AND profit factor ≥ 1.3 over 90 sessions (excluding event blackout days).

---

## Strategy 9: AI 9-EMA Retest — technical deep-dive

### Entry logic (current)

- Runs **only on 5m candle close** (minute % 5 == 0, first 20s).
- Builds snapshot: 5m EMA9 structure, 15m ADX/DI (now real via `technical_indicators.calculate_adx`).
- LLM applies 9-module rule set (VIX, ADX, EMA retest, session windows, SL/target).
- Max 3 trades/day (`strat_9_trades_today` — recommend persisting in `TradingState.save`).

### Strengths

- Richest rule documentation in system prompt.
- De-duplicated LLM calls (cost control).
- Commodity session aware (MCX full session).

### Weaknesses / test focus

| Risk | Test |
|------|------|
| LLM non-determinism | Run same snapshot 10×; measure signal variance |
| `strat_9_trades_today` not persisted across restart | Chaos test: restart mid-session |
| Option chain fetch every 5m | Latency under API queue load |
| ADX gate now functional — may **reduce** signal count | Compare signal rate before/after P0 |

### Backtest / shadow protocol

**Phase 1 — Rule engine only (no LLM):**

Replay historical 5m/15m candles; implement `evaluate_strategy_9_rules_only()` that parses the same modules deterministically from OHLC (skip LLM).

**Phase 2 — LLM shadow:**

During live/paper session, log LLM decisions without executing; compare to rule-only replay on same bars.

```bash
.venv/bin/python scripts/backtest_strategy9_shadow.py \
  --days 30 \
  --mode rules-only
```

**Pass gate:** rules-only variant PF ≥ 1.2; LLM shadow must not exceed 2× false entry rate vs rules-only.

---

## Implementation phases

| Phase | Deliverable | Owner lane |
|-------|-------------|------------|
| **C1** | `scripts/backtest_orb.py` + 90d report | vc-execute-agent |
| **C2** | RBI/Budget calendar for `check_no_economic_events()` | vc-execute-agent |
| **C3** | `strat_9_trades_today` persistence in `automation.py` | vc-quick-fix-agent |
| **C4** | S9 rules-only replay script | vc-research-agent → vc-execute-agent |
| **C5** | Walk-forward report in `process/general-plans/active/` | vc-update-process-agent |

---

## Subagent routing (recommended)

| Task | Agent / skill |
|------|----------------|
| ORB backtest script | `vc-execute-agent` + `vc-web-testing` |
| S9 LLM cost / prompt tuning | `vc-innovate-agent` |
| Live incident (missing SL, token -8) | `vc-debugger` |
| Pre-market checklist | New optional `vc-trading-auditor` (after Phase A green) |

**No new harness subagents required for C1–C5** — use existing RIPER-5 actors.

---

## Validate contract (before live sizing increase)

```bash
cd trading-app
.venv/bin/python smoke_test.py
.venv/bin/pytest -q tests/test_p0_fixes.py
# After backtest scripts exist:
.venv/bin/python scripts/backtest_orb.py --days 90 --dry-run
```

Gate: smoke PASS, P0 tests PASS, ORB backtest report committed to task folder.

## Execution status (2026-07-31)

| Phase | Status | Artifact |
|-------|--------|----------|
| A — P0 fixes | **MERGED** (PR #2) | Deployed via GitHub Actions |
| B — Production pull | **Blocked** (no GCP auth in cloud VM) | `scripts/pull_production_backup.sh` |
| C1 — ORB backtest | **Done** | `scripts/backtest_orb.py`, `reports/orb_backtest_90d.json` |
| C2 — Economic calendar | **Done** | `engine/economic_calendar.py` |
| C3 — S9 persistence | **Done** | `strat_9_trades_today` in `automation.py` |
| C4 — S9 rules replay | **Done** | `scripts/backtest_strategy9_rules.py` |
| C5 — Reports | **Done** | `orb_backtest_REPORT_31-07-26.md`, `strategy9_rules_REPORT_31-07-26.md` |


## Execution status update (2026-08-01)

| Item | Status |
|------|--------|
| C1–C5 (original) | Done |
| S9 LLM shadow JSONL + shadow script | **Done** |
| ADX 27 sweep | **Done** — keep ADX 25 |
| ORB delta sweep | **Done** — keep 0.55 |
| Square-off re-entry + OAuth cookie + AST lock test | **Done** (security residuals) |
| Shadow week through 2026-08-07 | **In progress** (prod paper) |
| Live sizing increase | **Blocked** — gates still fail |
| See | `offline_closeout_REPORT_01-08-26.md` |

