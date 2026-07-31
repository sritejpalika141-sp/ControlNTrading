# Production Analysis Report — 2026-07-31

**Source:** GitHub Actions run [#30623696918](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30623696918)  
**Artifact:** `backups/ci-download/production-backup/` (also downloadable from Actions → `prod-analysis`)

## Pull summary

| Item | Value |
|------|-------|
| `trading_app.db` | **5.2 MB** — pulled successfully |
| VM instance | `sritej-trading` (asia-south1-c) |
| Prod deploy commit | `0f3ba8a` (per `git_info.txt`) |
| GitHub `main` at pull time | Ahead by CI-only commits (`3f25052`) |

## Users (production DB)

| id | username | active | Fyers client ID | Fyers access token |
|----|----------|--------|-----------------|-------------------|
| 1 | admin | yes | **yes** | **no** |
| 3 | naveen | yes | no | no |
| 5 | controln | yes | no | no |

**Fyers backtest failed** because user `admin` (id=1) has no `fyers_access_token` in the DB. Fix: log in on prod → complete Fyers OAuth → re-run **Production Analysis**.

## Live trades today (2026-07-31)

| Strategy | Symbol | Status |
|----------|--------|--------|
| Strategy 11: FRVP LVN Vacuum | NIFTY CE (2 strikes) | OPEN |
| Strategy 8: Smart Money Concepts | NIFTY CE (2 strikes) | OPEN |
| Crude Evening Momentum | MCX CRUDEOIL PE | OPEN |

5 open positions in `executed_trades`; no closed outcomes yet today in the snapshot.

## Offline backtests (yfinance, post-tune)

| Strategy | Win rate | PF | Gate |
|----------|----------|-----|------|
| ORB (VIX=14, tuned filters) | 37.0% | 1.17 | Fail (≥45% / ≥1.3) |
| S9 rules-only (ADX≥25, 10:00–14:00) | 33.1% | 0.99 | Fail (≥1.2) |

Spot-proxy only — Fyers historical backtest still pending OAuth on prod.

## Recommended next steps

1. **Prod Fyers login** — `http://35.234.213.226:8000/login` as `admin` → link Fyers → re-run Production Analysis.
2. **Paper/shadow week** — ORB + S9 with tuned filters before sizing up.
3. **Reconcile open trades** — 5 OPEN rows; confirm SL guardian and automation state on prod dashboard.

## Re-run production pull

```bash
# GitHub UI: Actions → Production Analysis → Run workflow
# Or locally with gcloud auth:
bash scripts/pull_production_backup.sh
```
