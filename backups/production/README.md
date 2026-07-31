# Production backup directory

Artifacts pulled from the live GCP VM (`sritej-trading`, `asia-south1-c`) land here.

## Quick start (with `GCP_CREDENTIALS` secret)

```bash
# From repo root — authenticates via scripts/gcloud_auth_from_env.sh
bash scripts/pull_production_backup.sh
bash scripts/run_orb_fyers_on_prod.sh 30 1
```

See **AGENTS.md → Cloud Agent secrets** for how to add `GCP_CREDENTIALS` in Cursor.

## Sync status (2026-07-31)

| Layer | Status |
|-------|--------|
| GitHub `main` | Application code synced via git |
| Production static assets | Match local when deploy is current |
| Production DB | Pull with `pull_production_backup.sh` when GCP secret is set |

## Pull command

```bash
export GCP_PROJECT=sritej-trading-algo-2026
export GCP_INSTANCE=sritej-trading
export GCP_ZONE=asia-south1-c
bash scripts/pull_production_backup.sh
```

Credentials (pick one):

- Cursor / CI secret **`GCP_CREDENTIALS`** — full service-account JSON (recommended)
- Interactive: `gcloud auth login`

## Compare after pull

```bash
LATEST=$(ls -td backups/production/*/ | head -1)
diff -ru trading-app/ "$LATEST" | less
```

Do **not** overwrite local `.env` or commit `trading_app.db` to git.
