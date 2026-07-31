# Production backup directory

Artifacts pulled from the live GCP VM (`sritej-trading`, `asia-south1-c`) land here.

## Sync status (2026-07-31)

| Layer | Status |
|-------|--------|
| GitHub `main` @ `65acc22` | Matches local application code |
| Production static assets (MD5) | Matches local `trading-app/static/` |
| Production DB / secrets | **Not pulled** — requires GCP SSH credentials in this environment |

## Pull command (run on a machine with `gcloud` auth)

```bash
export GCP_PROJECT=sritej-trading-algo-2026
export GCP_INSTANCE=sritej-trading
export GCP_ZONE=asia-south1-c
bash scripts/pull_production_backup.sh
```

Requires one of:

- `gcloud auth login` (interactive), or
- `GCP_CREDENTIALS` JSON (same secret used by GitHub Actions deploy workflow)

## Compare after pull

```bash
LATEST=$(ls -td backups/production/*/ | head -1)
diff -ru trading-app/ "$LATEST" | less
```

Do **not** overwrite local `.env` or commit `trading_app.db` to git.
