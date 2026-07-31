# Production Analysis Report — 2026-07-31

**Latest successful pipeline:** Deploy [#30626910011](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30626910011) → Production Analysis [#30627017031](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30627017031) (auto-trigger after deploy, PR #19)  
**Artifact:** `prod-analysis` (DB + code snapshot) — download from Actions or `backups/ci-download/run-30627017031/`

## Infrastructure fixes (PRs #14–#19)

| Issue | Fix |
|-------|-----|
| Deploy `scp` Permission denied (silent failure) | `/tmp` tarball + `sudo rsync` (`scripts/gcloud_deploy_upload.sh`) — PR #15 |
| `cpp_core` missing in repo broke deploy | Skip when absent — PR #16 |
| `/tmp/restart_app.sh` not writable | Unique `/tmp/sritej-restart-<ts>.sh` — PR #17 |
| Prod-analysis auto-run | `workflow_run` after successful deploy — PR #14 |
| Fyers backtest: `yfinance` import at module load | Lazy import in `backtest_orb.py` — PR #18 |
| Fyers backtest: cannot read `fyers-mcp-server/.env` | `sudo -u sritejpalika` in `run_orb_fyers_on_prod.sh` — PR #19 |

Deploy now completes with health check green; Production Analysis auto-triggers on each successful deploy.

## Fyers ORB backtest (live API, 30d) — run #30627017031

| Metric | Value |
|--------|-------|
| Data source | **Fyers** (`NSE:NIFTY50-INDEX`) |
| Sessions | 23 |
| Trades | **0** |
| Win rate | 0% |
| Profit factor | 0.0 |
| Pass gate | **No** |
| Skip breakdown | volume: 180, no_breakout: 23 |

Refresh-token auth succeeded; historical candles fetched. Zero trades means tuned ORB filters (volume + breakout rules) rejected every session in the 30-day Fyers window — not an auth failure.

Note: `prod-analysis-backtest` artifact is not uploaded when `pass_gate` is false (script exits 1). JSON is on VM at `reports/orb_fyers_backtest.json` and printed in the Actions log.

## Users (production DB, pulled 2026-07-31)

| id | username | Fyers client | Refresh token | Access token |
|----|----------|--------------|---------------|--------------|
| 1 | admin | yes | yes (encrypted) | no (refresh-only OAuth) |
| 3 | naveen | no | no | no |
| 5 | controln | no | no | no |

Health API: `token_valid: true` for admin.

## Offline backtests (yfinance spot proxy, 59d, tuned filters)

| Strategy | Win rate | PF | Gate |
|----------|----------|-----|------|
| ORB (VIX=14) | 37.0% | 1.17 | Fail (≥45% / ≥1.3) |
| S9 rules (ADX≥25, 10:00–14:00) | 33.1% | 0.99 | Fail (≥1.2) |

## Recommended next steps

1. **ORB volume filter on Fyers** — 180 volume skips vs 0 trades; compare Fyers index volume units to yfinance proxy (may need lower multiplier for Fyers candles).
2. **Extend Fyers backtest window** — re-run with `backtest_days: 59` via Actions → Production Analysis → Run workflow.
3. **Paper/shadow week** — ORB + S9 before live sizing.
4. **Optional CI tweak** — upload `orb_fyers_backtest.json` even when `pass_gate` is false (report exists on VM).

## Re-run

[Production Analysis workflow](https://github.com/sritejpalika141-sp/ControlNTrading/actions/workflows/prod-analysis.yml) — manual dispatch or automatic after deploy to `main`.
