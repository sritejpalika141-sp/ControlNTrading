# Production Analysis Report — 2026-07-31

**Latest pipeline:** Deploy [#30628471071](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30628471071) (PR #22) → Production Analysis [#30628570474](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30628570474)  
**Artifacts:** `prod-analysis` (DB + code snapshot), `prod-analysis-backtest` (`orb_fyers_backtest.json`) — `backups/ci-download/run-30628570474/`

## Session deliverables (complete)

| Item | Status |
|------|--------|
| Deploy pipeline (VM upload + health check) | ✅ PRs #14–#17 |
| Auto prod-analysis after deploy | ✅ PR #14 |
| Fyers ORB backtest on prod VM | ✅ PRs #18–#20 |
| 59-day backtest default | ✅ PR #21 |
| ORB+S9 shadow week (user 1, 7d) | ✅ until **2026-08-07** |
| Volume filter fix for NIFTY index (Fyers) | ✅ PR #22 |

## Infrastructure fixes (PRs #14–#22)

| Issue | Fix |
|-------|-----|
| Deploy `scp` Permission denied (silent failure) | `/tmp` tarball + `sudo rsync` (`scripts/gcloud_deploy_upload.sh`) — PR #15 |
| `cpp_core` missing in repo broke deploy | Skip when absent — PR #16 |
| `/tmp/restart_app.sh` not writable | Unique `/tmp/sritej-restart-<ts>.sh` — PR #17 |
| Prod-analysis auto-run | `workflow_run` after successful deploy — PR #14 |
| Fyers backtest: `yfinance` import at module load | Lazy import in `backtest_orb.py` — PR #18 |
| Fyers backtest: cannot read `fyers-mcp-server/.env` | `sudo -u sritejpalika` in `run_orb_fyers_on_prod.sh` — PR #19 |
| Artifact missing when `pass_gate` false | Upload JSON if produced — PR #20 |
| 296 volume skips / 0 trades on Fyers 59d | Skip volume gate for index spot symbols — PR #22 |

Deploy completes with health check green; Production Analysis auto-triggers on each successful deploy.

## Fyers ORB backtest — before vs after volume fix

| Run | PR | Days | Sessions | Trades | Volume skips | no_breakout | WR | PF | Gate |
|-----|-----|------|----------|--------|--------------|-------------|-----|-----|------|
| [#30628009327](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30628009327) | #21 | 59 | 43 | **0** | **296** | 38 | — | — | Fail |
| [#30628570474](https://github.com/sritejpalika141-sp/ControlNTrading/actions/runs/30628570474) | #22 | 59 | 43 | **34** | **0** | 4 | 32.4% | 0.96 | Fail |

**Post–PR #22 (59d, Fyers `NSE:NIFTY50-INDEX`):**

| Metric | Value |
|--------|-------|
| Wins / losses | 11 / 23 |
| Total PnL (pts) | -20.0 |
| Skip breakdown | gap: 3, range: 2, no_breakout: 4 |
| `pass_gate` | **No** (needs ≥45% WR and ≥1.3 PF) |

The backtest script exits 1 when the gate fails, so CI shows `::warning::Fyers backtest did not complete` even though the JSON was produced and uploaded.

## Shadow week (ORB + S9)

Enabled on production for **user 1 (admin)** in runs #30628009327 and #30628570474:

- **Until:** 2026-08-07  
- **Strategies:** Strategy 3 (5-Minute ORB), Strategy 9 (9-EMA Momentum Scalper)  
- **Behavior:** Signals execute in **paper mode** only; account stays live for other strategies (`auto_trader.execute_auto_trade` temporarily forces `paper_trading=True` for shadow strategies).

## Users (production DB)

| id | username | Fyers client | Refresh token |
|----|----------|--------------|---------------|
| 1 | admin | yes | yes (encrypted) |
| 3 | naveen | no | no |
| 5 | controln | no | no |

Health API (`http://35.234.213.226:8000/api/health`): `token_valid: true`, `automation_active: true`, `version: 6.0.0`.

## Offline backtests (yfinance spot proxy, 59d, tuned filters)

| Strategy | Win rate | PF | Gate |
|----------|----------|-----|------|
| ORB (VIX=14) | 37.0% | 1.17 | Fail (≥45% / ≥1.3) |
| S9 rules (ADX≥25, 10:00–14:00) | 33.1% | 0.99 | Fail (≥1.2) |

Fyers live 59d ORB (32.4% / 0.96) is **below** both the production gate and the offline yfinance proxy — shadow week is appropriate before live ORB sizing.

## Known CI noise (non-blocking)

- **Sync scripts step** (`fyers_client.py` scp) intermittently fails; full `deploy.sh` on push still syncs the app. Backtest uses scripts uploaded via `run_orb_fyers_on_prod.sh` remote prep.
- **Summarize warning** when `pass_gate: false` — cosmetic; artifact upload succeeds.

## Recommended next steps

1. **Keep shadow week** through 2026-08-07; compare live paper fills vs backtest assumptions.
2. **ORB tuning** — 32.4% WR / 0.96 PF on Fyers does not meet gate; consider trend filter, VIX breakout path, or session filters before promoting to live.
3. **S9** — run Fyers-native S9 backtest when script exists; offline yfinance still below gate.
4. **Optional:** Treat backtest exit 0 when JSON is written (gate result as field only) to clear CI warning.

## Re-run

[Production Analysis workflow](https://github.com/sritejpalika141-sp/ControlNTrading/actions/workflows/prod-analysis.yml) — automatic after deploy to `main`, or manual dispatch with `backtest_days: 59`.
