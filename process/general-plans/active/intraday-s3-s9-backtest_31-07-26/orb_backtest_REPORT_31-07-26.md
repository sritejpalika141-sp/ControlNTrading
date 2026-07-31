# ORB Backtest Report — 59 sessions (yfinance ^NSEI)

**Generated:** 2026-07-31  
**Script:** `scripts/backtest_orb.py`

## Results

| Metric | Value | Pass gate |
|--------|-------|-----------|
| Sessions | 57 | — |
| Trades | 46 | — |
| Win rate | **30.4%** | ≥ 45% ❌ |
| Profit factor | **0.88** | ≥ 1.3 ❌ |
| Total PnL (spot pts) | -80.0 | — |

## Skip breakdown

| Reason | Count |
|--------|-------|
| Volume < 2× avg | 15 |
| No breakout in window | 5 |
| Gap ≥ 1% | 3 |
| Range ≥ 0.5% | 3 |

## Recommendations (next iteration)

1. Tighten volume filter to 2.5× on low-VIX days.
2. Require 15m trend alignment before ORB entry.
3. Re-run with Fyers historical data (option-premium PnL, not spot proxy).
4. Review 9:20–9:25 live-cross vs close-confirm mode separately.

Full JSON: `trading-app/reports/orb_backtest_90d.json`
