# Planning closeout — offline deliverables (01-08-26)

Closes remaining **code-completable** items from active plans. Live gate promotion and multi-asset Phase 2 MCX probe remain calendar/Fyers-blocked.

## Implemented this pass

| Item | Status |
|------|--------|
| S9 LLM shadow JSONL (`logs/strategy9_llm_shadow.jsonl`) | ✅ `engine/strategy_9.py` |
| `scripts/backtest_strategy9_shadow.py` | ✅ rules-only + live-log compare |
| Wire `event_risk_today` via economic calendar | ✅ |
| ADX 25 vs 27 sweep (59d) | ✅ **keep 25** (27 worse: PF 0.92 vs 0.99) |
| ORB `--delta` 0.45/0.55/0.65 sweep | ✅ WR/PF unchanged; keep live **0.55** |
| Backtest scripts exit 0 when JSON written | ✅ |
| Square-off re-entry guard | ✅ `square_off_in_progress` |
| AST `order_lock`⊃`record_trade` test | ✅ |
| OAuth verifier cookie on JSON login_url + UI→`/fyers/auth` | ✅ |
| Archive secret-leak-monitor + resolved security notes | ✅ |

## Sweep results (yfinance 59d)

| Run | Trades | WR | PF | Gate |
|-----|--------|----|----|------|
| S9 ADX≥25 | 124 | 33.1% | 0.99 | Fail |
| S9 ADX≥27 | 114 | 31.6% | 0.92 | Fail |
| ORB δ=0.45/0.55/0.65 | 47 | 29.8% | 0.85 | Fail |

## Still WAIT (cannot finish offline)

1. **Shadow week** paper fills through **2026-08-07** on prod user 1  
2. Promote ORB/S9 off shadow / raise live size — gates still fail  
3. Fyers-native S9/ORB on authenticated prod VM during market hours  
4. Multi-asset Phase 2 **MCX crude quote probe** (needs market-open Fyers login) then ≥5-day paper window  
5. Multi-asset Phases 3–5 — blocked on Phase 2 VERIFIED  

## Artifacts

- `trading-app/reports/strategy9_rules_adx25.json`
- `trading-app/reports/strategy9_rules_adx27.json`
- `trading-app/reports/strategy9_shadow_rules.json`
- `trading-app/reports/orb_backtest_delta_0_45.json` / `_0_55` / `_0_65`
