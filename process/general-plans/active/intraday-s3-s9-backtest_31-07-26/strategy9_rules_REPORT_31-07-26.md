# Strategy 9 Rules-Only Backtest — 59 days (tuned)

**Generated:** 2026-07-31  
**Script:** `scripts/backtest_strategy9_rules.py`  
**Filters:** `engine/strategy9_filters.py` (ADX ≥ 25, session 10:00–14:00 IST)

## Baseline (pre-tune)

| Metric | Value | Pass gate |
|--------|-------|-----------|
| Trades | 154 | — |
| Win rate | **26.0%** | — |
| Profit factor | **0.70** | ≥ 1.2 ❌ |

## Tuned (ADX≥25, 10:00–14:00)

| Metric | Value | Pass gate |
|--------|-------|-----------|
| Trades | **124** | — |
| Win rate | **33.1%** | — |
| Profit factor | **0.99** | ≥ 1.2 ❌ |

Tuning cut 30 low-quality signals and nearly doubled profit factor. Still below the 1.2 rules-only gate — LLM shadow mode remains recommended before disabling the AI layer.

## Live changes

- `strategy_9.py`: hard ADX + session gates before LLM (NSE only; MCX unchanged).
- System prompt updated to match ADX 25 and 10:00–14:00 window.

Full JSON: `trading-app/reports/strategy9_rules_backtest.json`

## Next steps

1. LLM shadow logging for 1–2 weeks; compare false-entry rate vs rules-only. **Started 01-08-26:** live JSONL at `logs/strategy9_llm_shadow.jsonl` + `scripts/backtest_strategy9_shadow.py`.
2. Fyers historical replay when credentials available on analysis VM.
3. ADX 27 sweep — **DONE 01-08-26:** ADX≥27 PF **0.92** vs ADX≥25 PF **0.99** → **keep MIN_ADX_15M = 25**.
