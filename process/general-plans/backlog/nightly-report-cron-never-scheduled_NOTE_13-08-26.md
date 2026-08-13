---
name: note:nightly-report-cron-never-scheduled
description: "check_nightly_learning_report.py was never scheduled on the VM — crontab was empty before 13-08-26"
date: 13-08-26
feature: general
---

# BACKLOG NOTE — `check_nightly_learning_report.py` Is Not Scheduled (G3)

Opened: 13-08-26. Found during EXECUTE of `strategy-self-improvement_11-08-26`.
**Not fixed — out of scope for that plan.**

## What was found

Before the `run_backtests_cron.py` entry was installed on 13-08-26, the VM had **no scheduled job
at all** for `check_nightly_learning_report.py`, despite that script's own docstring stating it is
"Cron-invoked, run every 10 min in the evening window."

Verified on the VM:

- `crontab -l` (user `sritejpalika`) → empty
- `sudo crontab -l` (root) → empty
- `/etc/cron.d/` → only `certbot` and `e2scrub_all`
- `systemctl list-timers --all` → no timer matching `backtest` / `nightly` / `trading`

## Impact

The nightly learning Telegram report has not been firing. Combined with G2
(`telegram-webhook-resolution-broken_NOTE_13-08-26.md`), there are two independent reasons that
report has been silent — it is not scheduled, and even if it were, its webhook lookup resolves to
an empty string.

Note this does **not** affect nightly learning itself, which runs inside the app process via
`engine/automation.py`'s `check_and_run_nightly_learning()`, not via cron. Only the *observer/report*
script is unscheduled.

## Recommended next step

Decide whether the report is still wanted. If yes, add a crontab entry alongside the new backtest
refresh job and fix G2 first (otherwise it will run and silently send nothing). Suggested entry,
matching the script's documented evening window:

```
*/10 23,0 * * * cd /home/sritejpalika/trading-app && .venv/bin/python3 check_nightly_learning_report.py >> logs/nightly_report_cron.log 2>&1
```

Confirm the exact window against the script's own `sent_marker` / midnight-boundary logic before
installing.
