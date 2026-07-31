# Cloud security posture — ControlN Trading

Last updated: 2026-07-31

## Production status

- **VM:** `sritej-trading` (GCP `asia-south1-c`), app on port 8000
- **Deploy:** automatic on every `main` merge (`deploy.yml`)
- **Health:** `/api/health` — expect `status: healthy`, `token_valid: true`
- **CI:** `prod-analysis.yml` after deploy (ORB + S9 Fyers backtests, shadow enforcement)

## Applied mitigations (code)

| Control | Location |
|---------|----------|
| Signed session cookies | `auth_utils.py` |
| Login rate limiting | `auth_utils.py` |
| OAuth signed state + verifier | `auth_utils.py`, `/fyers/callback` |
| Encrypted Fyers tokens in DB | `engine/encryption.py` |
| HTTP security headers | `engine/security_middleware.py` |
| Telegram webhook secret | `TELEGRAM_WEBHOOK_SECRET` |
| Execution gates (spread + MTF) | `engine/execution_gates.py` |
| Portfolio cap (max 2 index options) | `workers/auto_trader.py` |
| Shadow week for ORB/S9 | `shadow_strategies` + `enforce_backtest_shadow_gates.py` |
| VM OS package refresh on deploy | `deploy.sh` restart script |

## Known dependency constraint

`fyers-apiv3` **pins** `aiohttp==3.9.3` and `requests==2.31.0`. `pip-audit` reports CVEs until Fyers ships a newer SDK. Do not force-upgrade those packages on production without testing Fyers order flow.

Mitigations: GCP firewall (limit :8000), strong `SECRET_KEY`, no public admin without auth, shadow mode for unproven strategies.

## Profit / strategy gates (not security)

Live ORB on Fyers 59d: **32.4% WR, 0.96 PF** — below gate (≥45% WR, ≥1.3 PF). ORB and S9 stay **paper-only** via shadow until backtests pass.

No infrastructure change guarantees trading profits — tune strategies using Fyers backtest artifacts in CI.

## Manual GCP hardening (optional)

1. Restrict firewall to your IP + GitHub Actions egress if using static IPs
2. Put Cloudflare or HTTPS reverse proxy in front of dashboard
3. Enable GCP OS Login + 2FA on project owners
4. Enable Cloud Resource Manager API (clears CI warning noise)
