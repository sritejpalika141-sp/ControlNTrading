# ORB Backtest Report — 59 sessions (yfinance ^NSEI)

**Generated:** 2026-07-31 (tuned filters)  
**Script:** `scripts/backtest_orb.py`  
**Shared filters:** `engine/orb_filters.py` (live + backtest parity)

## Baseline (pre-tune)

| Metric | Value | Pass gate |
|--------|-------|-----------|
| Trades | 46 | — |
| Win rate | **30.4%** | ≥ 45% ❌ |
| Profit factor | **0.88** | ≥ 1.3 ❌ |
| Total PnL (spot pts) | -80.0 | — |

## Tuned filters (VIX=16, live-cross mode)

| Metric | Value | Pass gate |
|--------|-------|-----------|
| Trades | 46 | — |
| Win rate | **28.3%** | ≥ 45% ❌ |
| Profit factor | **0.79** | ≥ 1.3 ❌ |
| Total PnL (spot pts) | -140.0 | — |

### Skip breakdown (VIX=16)

| Reason | Count |
|--------|-------|
| Volume (adaptive 2×) | 15 |
| 15m trend misalignment | 4 |
| No breakout in window | 5 |
| Gap ≥ 1% | 3 |
| Range out of band | 3 |

## Tuned filters (VIX=14, close-confirm mode)

| Metric | Value | Pass gate |
|--------|-------|-----------|
| Trades | 46 | — |
| Win rate | **37.0%** | ≥ 45% ❌ |
| Profit factor | **1.17** | ≥ 1.3 ❌ |
| Total PnL (spot pts) | +100.0 | — |

Low-VIX close-confirm path improves spot-proxy metrics but still fails gates. Option-premium PnL (Fyers historical) is required before live sizing changes.

## Filters shipped

1. Adaptive volume: 2.5× avg on VIX ≤ 15, else 2× (`volume_multiplier`).
2. ORB width band: 0.08% min, 0.5% max (`orb_range_ok`).
3. 15m trend alignment before entry (`trend_15m_confirms`).
4. VIX>15 live path: breakout candle volume (not ORB candle volume).

Full JSON: `trading-app/reports/orb_backtest_90d.json`

## Next steps

1. Fyers historical backtest (option premium SL/TP, not spot pts).
2. Separate reporting for VIX>15 vs VIX≤15 entry modes.
3. Paper-trade shadow week before raising ORB confidence/size.
