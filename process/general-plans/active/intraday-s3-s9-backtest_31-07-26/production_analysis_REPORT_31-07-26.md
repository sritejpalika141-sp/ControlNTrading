# Production Analysis Report — 2026-07-31

**Latest pull:** GitHub Actions [#30624355503](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30624355503)  
**Latest deploy:** [#30625060122](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30625060122) (PR #13 merge)  
**Artifact:** `backups/ci-download/production-backup/` (Actions → `prod-analysis`)

## Critical finding (2026-07-31)

**Deploy SCP was failing silently** — VM `trading-app/` files were root-owned, so `gcloud compute scp` returned “Permission denied” for `app.py`, `backtest_orb_fyers.py`, etc. The workflow still reported green because `deploy.sh` did not fail on scp errors.

**Fix:** PR #14 added chown prep (insufficient — CI SSH user ≠ `sritejpalika`). **PR #15** uploads via `/tmp` tarball + `sudo rsync` (`scripts/gcloud_deploy_upload.sh`).

## Pull summary

| Item | Value |
|------|-------|
| `trading_app.db` | **5.2 MB** — pulled successfully |
| VM instance | `sritej-trading` (asia-south1-c) |
| Prod deploy commit | `0f3ba8a` (per `git_info.txt`) |
| GitHub `main` at pull time | Ahead by CI-only commits (`3f25052`) |

## Users (production DB)

| id | username | active | Fyers client ID | Fyers refresh | Fyers access |
|----|----------|--------|-----------------|---------------|--------------|
| 1 | admin | yes | **yes** | **yes** (~972 chars enc.) | **no** (refresh-only OAuth) |
| 3 | naveen | yes | no | no | no |
| 5 | controln | yes | no | no | no |

**Fyers backtest (run #30624355503)** failed with old script message (“Set up FYERS credentials”) — VM never received PR #13 `backtest_orb_fyers.py` due to deploy scp failures. Health API reports `token_valid: true` (runtime refresh works).

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

1. ~~**Prod Fyers login**~~ — Done (refresh token in DB; `token_valid: true` on health API).
2. **Merge deploy fix** (`gcloud_remote_prep.sh` + fail-fast scp) → confirm deploy logs show no “Permission denied”.
3. **Production Analysis** after successful deploy — PR #13 backtest script + refresh token path; expect **`prod-analysis-backtest`** artifact. Auto-runs after deploy once `workflow_run` trigger is merged.
4. **Paper/shadow week** — ORB + S9 with tuned filters before sizing up.
5. **Reconcile open trades** — check OPEN rows in `executed_trades` on prod dashboard.

## Re-run production pull

```bash
# GitHub UI: Actions → Production Analysis → Run workflow
# Direct link: https://github.com/sritejpalika141-sp/ControlNTrading/actions/workflows/prod-analysis.yml
```
