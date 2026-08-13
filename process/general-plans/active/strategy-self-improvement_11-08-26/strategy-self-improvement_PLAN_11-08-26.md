---
name: plan:strategy-self-improvement
description: "Fix stale nightly backtest refresh, add stats_source provenance to swarm_agent_configs, surface it on dashboard/admin"
date: 11-08-26
feature: general
phase: "complex"
---

# PLAN — Fix Strategy Self-Improvement Pipeline

Date: 11-08-26
Status: DRAFT — pending VALIDATE
Complexity: COMPLEX (multi-file, live-money system, touches DB schema + 2 frontend surfaces +
new cron script; single plan file, not a phase program — 3 independent-ish work areas but no
inter-phase validation gates needed, one VALIDATE pass covers all of it).

**Phase Completion Rules:** A section (1/2/3/4) is CODE DONE when its Execution Checklist items are
applied and `py_compile` passes locally. It is VERIFIED only after the matching Verification
Evidence row(s) for that section have been executed with observed evidence (log lines / DB query
output / screenshot) recorded in the phase report — code-complete is not the same as verified for
this live-money system. The plan as a whole is VERIFIED only when all rows in the Verification
Evidence table have been executed post-VM-deploy.

**Context loaded:** `process/context/all-context.md` (root router) plus
`process/context/tests/all-tests.md` (confirms no automated test harness exists for
`nightly_learning.py`/`backtest_runner.py`/`run_backtests.py` — Agent-Probe/Hybrid tiers below are
intentional per that gap, not a shortcut).

**Locked inputs:** SPEC at
`process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_SPEC_11-08-26.md`
(6 acceptance criteria, LOCKED). INNOVATE Decision Summary (in orchestrator task prompt, 11-08-26):
VM-cron refresh script + `stats_source` column + status-field/Telegram-alert failure signaling.

---

## Overview

Three coupled fixes, landing together:

1. **Provenance column** — add `stats_source TEXT` to `swarm_agent_configs` so every write of
   `win_rate`/`total_trades`/`winning_trades` is tagged `'backtest'` or `'live'`. Backfill existing
   rows. Every nightly_learning.py write site (backtest-derived) gets `stats_source='backtest'`;
   `record_trade_outcome()` (live-derived) gets `stats_source='live'`.
2. **Frontend label** — `static/app.js` and `static/admin.html` render a small "(backtest)" /
   "(live)" badge next to win-rate/trade-count wherever `agent.win_rate`/`total_trades` is shown.
3. **Nightly cron refresh** — new standalone script invoked by cron ~15 min before the
   `nightly_learning.py` trigger (~15:35 IST), reusing the `_get_validation_client()` headless-auth
   pattern, running `run_all_backtests()`, saving via `save_backtest_result()`, and on any failure
   (no authenticated session, or exception) logging + firing a Telegram alert + leaving the last
   good `backtest_results` rows untouched (nightly_learning's existing "read latest row per
   strategy" query is the fallback — no code change needed there for the fallback itself).

## Goals

- Backtest evidence advances every night, immediately before `nightly_learning.py` runs (SPEC AC#1).
- Refresh failure is visible and non-blocking; nightly learning falls back to last-good data
  automatically (SPEC AC#2).
- Capital-protection shadow-out logic is untouched (SPEC AC#3).
- Every `swarm_agent_configs` stat is visibly tagged backtest vs live on every surface that reads it
  (SPEC AC#4, AC#5).
- Zero-trade-strategies question stays explicitly out of scope with a backlog stub opened
  (SPEC AC#6).

## Out of Scope (carried from SPEC — do not implement)

- Root-causing Strategies 1-7's zero trades (separate follow-up RESEARCH task — this PLAN creates
  the backlog stub per AC#6, does not investigate it).
- Rewriting `backtest_engine.py`'s premium-modeling approach.
- General headless-Fyers-auth system (only the existing `_get_validation_client()`-style loop over
  already-authenticated sessions is reused — no new auth mechanism).

---

## CAUTION Item — Backtest Runtime vs 15-Minute Lead Window (verified during PLAN)

`run_backtests.py --days 60` calls `run_all_backtests()`, which loops `STRATEGY_META` (13
strategies) and for each calls `backtest_strategy()`, which fetches history for
`meta["needs"] | {"5"}` resolutions (1-4 resolutions per strategy, `D` uses `days_back=90`, others
use `days_back=60`). That is **13 strategies × up to 4 resolutions ≈ 35-45 sequential
`get_historical()` calls** via `asyncio.to_thread` (blocking, one at a time — no concurrency).

`fyers_client.py`'s `get_historical()` (line 862+) has a per-`symbol:resolution` cache (TTL
30s/60s/300s/900s by resolution) but a **fresh cron run with a cold cache will miss on every one of
the ~35-45 calls** — the cache only helps if `market_data_worker`/other loops already warmed it
for the SAME symbol+resolution combo recently, which is plausible for the shared `NSE:NIFTY50-INDEX`
5m/1m/60m/D candles most equity strategies share (12 of 13 strategies use `NSE:NIFTY50-INDEX`), but
NOT for the 2 crude strategies' MCX contract (separate symbol). Effective real Fyers REST calls on a
cold-cache run: roughly **4 unique resolutions for NIFTY (5/60/D/1) + 1 for MCX (5) ≈ 5 REST calls**,
each returning up to 90 days of candles in one call (Fyers history API is windowed, not
paginated-per-day) — NOT 35-45 separate REST round-trips. This is well inside Fyers' documented
rate limits (global cooldown in `fyers_client.py` triggers only after a 429, with a 120s cooldown on
trip) and comfortably fits a 15-minute lead window. **Verified: no rate-limit risk from the refresh
script itself at this frequency (once per night).** If the shared NIFTY history cache is cold AND
Strategy 5 rebuilds its own 3-min candles internally (see backtest_runner.py docstring: "15s
real-time cache TTL... best-effort"), that call is internal to strategy_5.py evaluation and does not
add a new REST symbol/resolution combo beyond what's already counted.

Estimated wall-clock: `run_all_backtests()` runs 13 strategies sequentially; the REST fetch portion
is ~5 calls (a few seconds total including retry backoff), and the in-memory candle-replay loop for
each strategy (up to ~4700 5-min candles for 90-day D-resolution strategies, less for 60-day) is
pure CPU/Python — no network. Existing manual runs of `run_backtests.py` are the ground truth for
actual wall-clock; this PLAN does not have a prior timed run recorded, so **Execution checklist item
17 requires a manual timed dry-run on the VM before installing the cron job**, to confirm real
wall-clock stays safely under the 15-minute window (target: complete in under 5 minutes based on the
call-count analysis above; if the dry run exceeds 10 minutes, move the cron lead time earlier, e.g.
15:10 IST instead of 15:20 IST, rather than proceeding with a lead time that has no safety margin).

---

## Touchpoints

| File | Change |
|---|---|
| `trading-app/models.py` | Add `stats_source TEXT DEFAULT 'live'` column + migration to `swarm_agent_configs` CREATE TABLE + `ALTER TABLE` migration block (near line 298-313); add `stats_source` param to `update_agent_config()` (line 849); tag `record_trade_outcome()`'s call to `update_agent_config()` (line 981) with `stats_source='live'`; add new `Database.get_last_backtest_refresh_status()` / `Database.set_last_backtest_refresh_status()` helpers (new tiny table `backtest_refresh_status`, single-row) for the visible-failure status field. |
| `trading-app/engine/nightly_learning.py` | Every `update_agent_config()` call site that writes from `perf` (backtest-derived) gets `stats_source='backtest'` — 5 call sites: line ~234 (graduation), ~258 (auto-reenable), ~397 (major-change PENDING, writes `old_config`/`win_rate` — still backtest-sourced win_rate), ~422 (minor auto-apply), ~439 (default-safe PENDING path). |
| `trading-app/run_backtests_cron.py` (NEW) | Standalone cron entry point: headless-auth via `_get_validation_client()`-equivalent loop, run `run_all_backtests()`, save via `save_backtest_result()`, write refresh status, fire Telegram alert on failure only. |
| `trading-app/static/app.js` | `renderStrategies()` (line ~3330-3390): add a small provenance badge next to Win Rate / Total Trades using `agent.stats_source`. |
| `trading-app/static/admin.html` | Swarm-status card renderer (~line 965-995) and `fetchAdminStrategies()` card renderer (~line 1000-1030): same badge treatment on both surfaces. |
| `process/features/` or backlog | New backlog stub for the zero-trade-strategies follow-up RESEARCH task (SPEC AC#6). |
| VM crontab | New crontab entry for `run_backtests_cron.py`, installed as a separate deploy step (not a code file — see Execution Checklist). |

## Public Contracts

- `Database.update_agent_config()` gains one new optional kwarg `stats_source: str = 'live'`
  (backwards-compatible default — any caller not passing it keeps today's behavior/shape, avoiding a
  breaking change to the 5+ existing call sites across the codebase that don't need retagging).
- New `swarm_agent_configs.stats_source` column is additive — no existing reader breaks; `SELECT *`
  callers (`get_agent_config`, `get_all_agent_configs`) automatically include it in their dict output
  with zero code change (confirmed: both use `SELECT * FROM swarm_agent_configs`, row_factory=Row →
  dict conversion picks up all columns automatically).
- `/api/admin/swarm-status` and the other 2 read-only endpoints (app.py lines 3017, 3301, 3512) that
  call `get_all_agent_configs()` need NO route code change — `stats_source` flows through
  automatically in the JSON response's `agents[].stats_source` field.
- New backtest_refresh_status surface (table or row) is read-only new API surface — no existing
  contract touched. If exposed on a dashboard, that is optional/future, not required by this PLAN
  (SPEC AC#2 only requires the failure be "visible somewhere a human can see it" — Telegram alert +
  a persisted status field satisfies this; a UI element is not mandated).

## Blast Radius

- **Files touched:** 6 (models.py, nightly_learning.py, new run_backtests_cron.py, app.js,
  admin.html, 1 backlog stub file) + crontab (VM config, not a repo file).
- **Risk class:** schema/migration (new column + new tiny table) — HIGH-RISK CLASS per
  `vc-test-coverage-plan` waterfall, requires at minimum Hybrid-tier verification (satisfied below —
  live-money system, migration is additive/backward-compatible only, no destructive ALTER).
- **No changes to:** `engine/risk_orchestrator.py` (reads `win_rate`/`total_trades` unchanged —
  Kelly sizing logic untouched, confirmed no `stats_source` dependency needed there), the strict
  rule-based capital-protection block in `nightly_learning.py` (lines 272-326, untouched), AI
  critique logic (untouched, only the `update_agent_config()` call sites gain one kwarg),
  `backtest_engine.py`/`backtest_runner.py` core logic (only *invoked* by the new cron script, not
  modified), `run_backtests.py` (kept as-is for manual CLI use; cron script is separate, not a
  refactor of it — SPEC explicitly allows "extend `run_backtests.py` itself if cleaner" but keeping
  them separate avoids risking the existing manual-CLI path while adding cron-specific
  status/alert logic that doesn't belong in the interactive CLI tool).

---

## Section 1 — Provenance Column + Write-Site Tagging (no dependency on cron script)

### 1.1 — `models.py` schema migration

**File:** `trading-app/models.py`

1. In the `swarm_agent_configs` CREATE TABLE statement (line 284-296), add
   `stats_source TEXT DEFAULT 'live'` as a new column in the initial CREATE (for fresh DBs).
2. Add a migration block immediately after the existing `is_paper_trading`/`continuous_losses`/
   `asset_class` migration block (after line 313):
   ```python
   # Migration: add stats_source provenance column (strategy-self-improvement, 11-08-26)
   try:
       c.execute("ALTER TABLE swarm_agent_configs ADD COLUMN stats_source TEXT DEFAULT 'live'")
       print("🆕 Migrated swarm_agent_configs table: added stats_source column", flush=True)
   except sqlite3.OperationalError:
       pass
   ```
3. **Backfill note:** existing rows get the column default `'live'` on ALTER (SQLite applies the
   `DEFAULT` to existing rows on `ADD COLUMN`). This is a deliberate backfill choice: existing rows
   were in fact written by the LAST call to `update_agent_config()` for that strategy, which for
   most rows was a `nightly_learning.py` backtest write (since Aug 5) — so `'live'` as a backfill
   default is technically wrong for rows currently holding backtest-derived numbers. **Decision:**
   backfill as `'backtest'` instead, via a one-time UPDATE immediately after the ALTER succeeds,
   because SPEC's Strategy 8 example (158 trades/17.7% win — a backtest number) is the concrete case
   this must fix, and defaulting new/live-recorded rows to `'live'` going forward while retroactively
   marking existing data `'backtest'` is the correct read of "these are the numbers now on the
   config row, and they came from a backtest run on 2026-08-05." Add:
   ```python
   # One-time backfill: existing rows were last written by nightly_learning's backtest-sourced
   # update_agent_config() calls (confirmed: single backtest_results run_date=2026-08-05 is the
   # only data source that has been feeding writes since Aug 5). Mark them 'backtest' explicitly
   # rather than defaulting to 'live', which would be factually wrong for the Strategy 8 case.
   try:
       c.execute("UPDATE swarm_agent_configs SET stats_source='backtest' WHERE stats_source='live' AND last_updated < '2026-08-11'")
   except sqlite3.OperationalError:
       pass
   ```
   Place this immediately after the ALTER TABLE block, guarded the same way (only meaningful once,
   idempotent because subsequent runs after 11-08-26 won't match `last_updated < '2026-08-11'` for
   newly-written rows).
4. Update `update_agent_config()` signature (line 849) to accept
   `stats_source: str = 'live'` as a new trailing kwarg; add it to the INSERT column list, VALUES
   placeholders, and the `ON CONFLICT ... DO UPDATE SET` clause (mirror the existing
   `asset_class` pattern exactly — same position pattern, new column).
5. New tiny status table + helpers for the visible-failure signal (SPEC AC#2). Add to
   `Database.init_db()` (near the `global_kill_switch` table, single-row pattern):
   ```python
   c.execute('''CREATE TABLE IF NOT EXISTS backtest_refresh_status (
       id INTEGER PRIMARY KEY CHECK (id = 1),
       last_status TEXT,
       last_run_at TEXT,
       last_error TEXT
   )''')
   ```
   Add two new `Database` staticmethods: `set_backtest_refresh_status(status: str, error: str = "")`
   (upsert the single row, id=1, `last_run_at=now IST isoformat`) and
   `get_backtest_refresh_status() -> Optional[Dict]` (read the single row). Follow the exact
   async/sync pattern used elsewhere in this file (aiosqlite, `async with`).

### 1.2 — `nightly_learning.py` write-site tagging

**File:** `trading-app/engine/nightly_learning.py`. All 5 `update_agent_config()` call sites in
this file write `win_rate`/`total_trades`/`winning_trades` sourced from `perf` (the
`get_backtest_performance()` dict, line 212) — every one of them needs `stats_source='backtest'`
added as a kwarg:

1. **Line ~234** (Automated Graduation): add `stats_source='backtest'`.
2. **Line ~258** (Auto-Reenable DISABLED): add `stats_source='backtest'` (this call preserves
   `win_rate`/`total`/`wins` from `perf`, so it's backtest too).
3. **Line ~397** (Major change → PENDING, preserves `old_config`): add `stats_source='backtest'`
   (the `win_rate`/`total_trades`/`winning_trades` args here are still the backtest-sourced `perf`
   values, even though `config_dict=old_config` — the STATS fields, not the config, are what
   `stats_source` tags).
4. **Line ~422** (Minor auto-apply): add `stats_source='backtest'`.
5. **Line ~439** (Default-safe PENDING path): add `stats_source='backtest'`.

**File:** `trading-app/models.py`, `record_trade_outcome()` (line 927-986) — the ONE live-derived
write path. At its `update_agent_config()` call (line 981), add `stats_source='live'` explicitly
(don't rely on the kwarg default — be explicit here since this is the one function whose entire
purpose is recording live outcomes).

**Grep verification after edit** (run before moving to Section 2):
```bash
grep -n "update_agent_config(" trading-app/engine/nightly_learning.py trading-app/models.py
grep -c "stats_source='backtest'" trading-app/engine/nightly_learning.py   # expect 5
grep -c "stats_source='live'" trading-app/models.py                        # expect 1 (record_trade_outcome)
```

---

## Section 2 — Frontend Label/Badge (depends on Section 1's column existing)

### 2.1 — `static/app.js` `renderStrategies()` (~line 3330-3390)

Add a small badge next to the Win Rate stat block. Insert immediately after the Win Rate `<div>`
value (after line 3376's closing `</div>`), inside the same grid cell, a one-line span:
```js
const sourceLabel = agent.stats_source === 'live' ? 'live' : 'backtest';
const sourceBadgeColor = agent.stats_source === 'live' ? 'var(--success)' : 'var(--text-muted)';
```
computed near `winRateColor` (line 3343), then rendered as:
```html
<div style="font-size: 0.65rem; color: ${sourceBadgeColor}; margin-top: 2px;">(${sourceLabel})</div>
```
directly below the win-rate percentage div (line 3376) and below the total-trades div (line 3380) —
both stat blocks get the same badge since both numbers share one provenance per row.

### 2.2 — `static/admin.html` — TWO renderers need the badge

1. **Swarm-status card** (~line 975-990, inside the `agent.active`/insight card): same
   `sourceLabel`/`sourceBadgeColor` computation, badge under both the win-rate div (line 984-985)
   and total-trades div (line 988-989).
2. **Admin strategies card** (`fetchAdminStrategies()`, ~line 1029-1030): this one renders as plain
   text lines (`<div><strong>Win Rate:</strong> ${cfg.win_rate}%</div>`), not styled boxes — append
   inline: `<div><strong>Win Rate:</strong> ${cfg.win_rate}% <span style="color:var(--text-muted); font-size:0.75rem;">(${cfg.stats_source === 'live' ? 'live' : 'backtest'})</span></div>` and
   similarly on the Trades line.

**Manual visual check after edit:** load `/admin.html`, confirm every strategy card shows
`(backtest)` or `(live)` next to its win-rate — this directly satisfies SPEC AC#4/#5's "reviewer can
tell source without cross-referencing."

---

## Section 3 — Cron Refresh Script + Headless Auth + Status + Alert (independent of Sections 1-2, can run in parallel; final wiring needs Section 1's status helpers)

### 3.1 — New file `trading-app/run_backtests_cron.py`

Structure (standalone script, same shape as `check_nightly_learning_report.py` — sync `requests`,
own `.env` loader, no asyncio-app-process dependency):

```python
"""
run_backtests_cron.py — nightly cron entry point (strategy-self-improvement, 11-08-26).

Invoked by cron ~15 min before nightly_learning.py's trigger (~15:35 IST), so backtest_results
is refreshed with a same-night run_date before nightly tuning reads it. Headless auth: reuses
the "any authenticated user's session works" pattern from workers/news_worker.py's
_get_validation_client(). On success: runs run_all_backtests() and saves via save_backtest_result().
On failure (no session, or any exception): logs, writes backtest_refresh_status, fires a
Telegram alert, and leaves prior backtest_results rows untouched — nightly_learning.py's existing
"read latest run_date per strategy" query is the fallback, unchanged.
"""
import asyncio, os, sys, logging
from datetime import datetime
import pytz
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
IST = pytz.timezone("Asia/Kolkata")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("BACKTEST_CRON")


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def send_telegram(webhook_url: str, message: str, title: str = "Backtest Refresh"):
    # identical pattern to check_nightly_learning_report.py's send_telegram()
    ...


def _get_headless_client():
    """Loop USER_STATES, return the first authenticated FyersClient, or None."""
    from state import USER_STATES
    from fyers_client import FyersClient
    for u_id in list(USER_STATES.keys()):
        try:
            c = FyersClient(user_id=u_id)
            if c.is_authenticated():
                return c, u_id
        except Exception:
            continue
    return None, None


async def _run():
    from models import Database
    from engine.backtest_runner import run_all_backtests

    client, u_id = _get_headless_client()
    if client is None:
        msg = "No authenticated Fyers session found at refresh time — backtest refresh skipped tonight."
        logger.error(msg)
        await Database.set_backtest_refresh_status("FAILED", msg)
        _alert_failure(msg)
        return

    try:
        results = await run_all_backtests(client, days_back=60)
        run_date = datetime.now(IST).strftime("%Y-%m-%d")
        saved = 0
        for r in results:
            ok = await Database.save_backtest_result(
                strategy_name=r["strategy"], symbol=r.get("symbol", ""), run_date=run_date,
                window_days=60, trades=r["trades"], wins=r["wins"], losses=r["losses"],
                win_rate=r["win_rate"], total_pnl=r["total_pnl"], avg_pnl=r["avg_pnl"],
                note=r.get("error", ""),
            )
            saved += int(ok)
        logger.info(f"Backtest refresh complete: saved {saved}/{len(results)} (run_date={run_date}).")
        await Database.set_backtest_refresh_status("OK", "")
    except Exception as e:
        msg = f"Backtest refresh crashed: {e}"
        logger.exception(msg)
        await Database.set_backtest_refresh_status("FAILED", msg)
        _alert_failure(msg)


def _alert_failure(msg: str):
    try:
        from state import get_user_state
        state = get_user_state(1)
        webhook_url = getattr(state, "webhook_url", "") or os.getenv("TELEGRAM_WEBHOOK", "")
    except Exception:
        webhook_url = os.getenv("TELEGRAM_WEBHOOK", "")
    send_telegram(webhook_url, msg, title="⚠️ Nightly Backtest Refresh Failed")


if __name__ == "__main__":
    load_env()
    asyncio.run(_run())
```

Notes for EXECUTE:
- Reuse `send_telegram()` body verbatim from `check_nightly_learning_report.py` (lines 127-141) —
  same `webhook_url` splitting logic, same `requests.post` pattern.
- Do NOT import `engine.notifier` (async, app-process-only per INNOVATE decision) — this script is
  a standalone sync process like `check_nightly_learning_report.py`.
- `Database.init_db()` runs on `import models` (models.py line 1287-1288) — safe to import
  standalone, same as `run_backtests.py` already does.

### 3.2 — VM crontab installation (deploy step, not a code file)

Cron entry (added during deploy, documented in `## Resume and Execution Handoff` and VM deploy
notes, installed via `crontab -e` or the `(crontab -l; echo "...") | crontab -` pattern from
`start_cloud.sh` lines 55-60):
```
20 15 * * * cd /home/sritejpalika/trading-app && .venv/bin/python3 run_backtests_cron.py >> logs/backtest_cron.log 2>&1
```
Day-of-week field is `*` (every day) — **confirmed during VALIDATE, not deferred to EXECUTE:**
`engine/automation.py`'s `check_and_run_nightly_learning()` (line 1142-1169) has no weekday or
holiday gate — it fires whenever `now >= 15:35 IST` and today hasn't already run. It is called
unconditionally from `workers/auto_trader.py`'s `automation_loop()` (line 2406-2429) inside the
`if not any_market_open:` branch, which is true every weekend too (market is always closed then).
So `nightly_learning.py` genuinely runs 7 nights/week, and the refresh cron must match that cadence
to satisfy SPEC's locked AC#1 constraint ("refreshed nightly, immediately before each
`nightly_learning.py` run") — a Mon-Fri-only cron would leave weekend nightly-learning runs tuning
against a stale Friday `run_date`, contradicting the locked cadence requirement. **15:20 IST is the
default per the CAUTION analysis above — revise to 15:10 IST if the manual timed dry-run (Execution
Checklist item 20) shows runtime approaching 10 minutes.**

---

## Section 4 — Backlog Stub for Zero-Trade Strategies (SPEC AC#6)

Create `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` (or the
project's standard backlog location — confirm `process/general-plans/backlog/` exists; create if
not) documenting: Strategies 1-7 have zero real trades ever (live or paper) as of RESEARCH/SPEC
(11-08-26); distinct root cause from backtest staleness (signal-generation, not tuning); confirmed
OUT of scope for this effort; recommend opening as a RESEARCH task once this effort ships. This
satisfies SPEC AC#6's "presence of a tracked follow-up backlog/RESEARCH item" proof requirement.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `sqlite3 trading_app.db "SELECT strategy_name, run_date FROM backtest_results ORDER BY run_date DESC LIMIT 15;"` run on 2+ separate nights post-deploy, confirm `run_date` advances (not pinned at one date) | Hybrid (needs VM + live cron firing) | AC#1 |
| Force-unauthenticate all sessions (or run on a VM where the token has expired), invoke `run_backtests_cron.py` manually, confirm: (a) `tail -f logs/backtest_cron.log` or `dashboard.log` shows the "No authenticated Fyers session found" error line, (b) a Telegram alert arrives, (c) `sqlite3 trading_app.db "SELECT * FROM backtest_refresh_status;"` shows `last_status='FAILED'`, (d) `backtest_results` rows are unchanged (same row count / same run_date as before the forced-failure run) | Agent-Probe | AC#2 |
| `grep "RULE-BASED (no AI)" logs/dashboard.log` across 2+ post-fix nightly runs, confirm shadow-out lines still appear for net-losing strategies exactly as before the change (same log format/behavior) | Hybrid | AC#3 |
| `sqlite3 trading_app.db "SELECT strategy_name, stats_source, win_rate, total_trades FROM swarm_agent_configs;"` — confirm every row has a non-null `stats_source` value (`'backtest'` or `'live'`), and manually load `/admin.html` + the user dashboard, confirm each strategy card visually shows the `(backtest)`/`(live)` badge next to its stats | Agent-Probe | AC#4 |
| Manual spot-check: Strategy 8's card on `/admin.html` shows `(backtest)` badge next to its 158-trades/17.7%-win figures (or whatever the current backtest snapshot shows post-refresh), confirming a reviewer sees the provenance tag rather than mistaking it for a real 158-trade track record | Agent-Probe | AC#5 |
| `grep -n "Strategies 1-7\|zero-trade\|CONFIRMED OUT OF SCOPE" process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_SPEC_11-08-26.md` (already present, pre-existing) AND (post-EXECUTE) `find process/general-plans/backlog -iname "*zero-trade*"` returns the new backlog stub file | Fully-Automated | AC#6 |
| `py_compile trading-app/models.py trading-app/engine/nightly_learning.py trading-app/run_backtests_cron.py` exits 0 | Fully-Automated | Regression guard (schema-migration + new-file syntax) |
| `python3 trading-app/precommit_check.py` exits 0 on the VM before scp | Fully-Automated | Regression guard (existing project convention) |
| `python3 trading-app/smoke_test.py` exits 0 on the VM after scp, before crontab install | Fully-Automated | Regression guard (existing project convention) |
| Manual timed dry-run of `run_backtests_cron.py` on the VM (authenticated session present), record wall-clock via `time .venv/bin/python3 run_backtests_cron.py` | Hybrid | CAUTION item — confirms 15-min lead window is safe before installing the cron job |
| `sqlite3 trading_app.db "SELECT win_rate, total_trades FROM swarm_agent_configs LIMIT 1;"` before AND after the migration ALTER runs, confirm no error and values unchanged (pure additive migration, no data loss) | Fully-Automated | Regression guard — migration safety |

## Test Infra Improvement Notes

(none identified yet — no automated test harness exists for this surface per SPEC Constraints; this
PLAN does not attempt to bootstrap one, consistent with SPEC's locked scope. A future improvement
would be a pytest fixture that seeds `backtest_results`/`swarm_agent_configs` and asserts
`stats_source` tagging on each `update_agent_config()` call site, but that is new test infra beyond
this SPEC's scope.)

---

## Implementation Checklist (atomic, ordered)

1. `trading-app/models.py`: add `stats_source TEXT DEFAULT 'live'` to the `swarm_agent_configs`
   CREATE TABLE statement (line ~284-296).
2. `trading-app/models.py`: add the `ALTER TABLE ... ADD COLUMN stats_source` migration block after
   line 313.
3. `trading-app/models.py`: add the one-time backfill `UPDATE ... SET stats_source='backtest' WHERE
   stats_source='live' AND last_updated < '2026-08-11'` immediately after step 2's block.
4. `trading-app/models.py`: add `CREATE TABLE IF NOT EXISTS backtest_refresh_status` to `init_db()`.
5. `trading-app/models.py`: add `Database.set_backtest_refresh_status()` and
   `Database.get_backtest_refresh_status()` staticmethods.
6. `trading-app/models.py`: add `stats_source: str = 'live'` kwarg to `update_agent_config()`
   signature; wire into INSERT columns, VALUES, and `ON CONFLICT ... DO UPDATE SET`.
7. `trading-app/models.py`: in `record_trade_outcome()`, add `stats_source='live'` to its
   `update_agent_config()` call (line ~981).
8. `trading-app/engine/nightly_learning.py`: add `stats_source='backtest'` to all 5
   `update_agent_config()` call sites (lines ~234, ~258, ~397, ~422, ~439).
9. Run grep verification commands from Section 1.2.
10. `trading-app/static/app.js`: add `sourceLabel`/`sourceBadgeColor` computation + badge markup in
    `renderStrategies()` (~line 3343-3382).
11. `trading-app/static/admin.html`: add the same badge treatment to both the swarm-status card
    (~line 975-990) and the admin strategies card (~line 1029-1030).
12. Manual visual check: load `/admin.html` and the main dashboard locally (or on VM after deploy),
    confirm badges render correctly for at least one `'backtest'` and one `'live'` row (may need to
    manually seed a `'live'` row via `record_trade_outcome` test call, or just visually confirm the
    JS renders `(backtest)` for all current rows since none are `'live'` yet in this DB).
13. Create `trading-app/run_backtests_cron.py` per Section 3.1 structure.
14. `py_compile` all 3 touched/new Python files locally.
15. Create the backlog stub file per Section 4.
16. Run `precommit_check.py` and `smoke_test.py` locally.
17. **Deploy to VM**: backup (`.bak-<timestamp>`) the 5 touched files on the VM, `gcloud compute scp`
    the changed files (`models.py`, `nightly_learning.py`, `run_backtests_cron.py`, `app.js`,
    `admin.html`), run `py_compile` + `smoke_test.py` on the VM.
18. **`systemctl restart sritej-trading`** — required because `models.py`/`nightly_learning.py`/
    `app.js`/`admin.html` are imported/served by the running `app.py` process; `run_backtests_cron.py`
    itself does NOT require a restart (standalone cron script, no long-running process imports it).
19. Verify: single process running, `curl -I http://localhost:8000` (or equivalent) returns HTTP 200,
    `tail -f logs/dashboard.log` shows clean startup with no import errors (specifically watch for
    `stats_source`/migration-related errors on the first post-deploy `init_db()` run).
20. **Manual timed dry-run** of `run_backtests_cron.py` on the VM (authenticated session present) —
    confirm the CAUTION item's runtime estimate; adjust cron lead time if needed (see Section 3.2).
21. **Install crontab entry** as a separate step (after 20's dry-run confirms timing is safe) —
    `(crontab -l 2>/dev/null; echo "20 15 * * * cd /home/sritejpalika/trading-app && .venv/bin/python3 run_backtests_cron.py >> logs/backtest_cron.log 2>&1") | crontab -`
    then `crontab -l` to confirm.
22. Run the Verification Evidence table's manual/log checks over the next 1-2 nights.
23. `git commit` directly on `main` (conventional commit prefix, e.g.
    `feat(trading): nightly backtest refresh cron + stats_source provenance tagging`).

---

## Dependencies

- Section 2 (frontend) depends on Section 1's `stats_source` column existing in the DB (badges will
  render `undefined`/`(backtest)` fallback-safe either way due to the `agent.stats_source === 'live'
  ? ... : 'backtest'` ternary, but should not ship before the column exists to avoid a confusing
  intermediate state).
- Section 3 (cron script) has no code dependency on Sections 1-2, but its `save_backtest_result()`
  calls populate `backtest_results` (unrelated table, no `stats_source` needed there — only
  `swarm_agent_configs` gets the provenance tag). Section 3's `set_backtest_refresh_status()` call
  depends on step 4-5 (the new table + helpers) existing.
- Crontab installation (step 21) must happen AFTER the timed dry-run (step 20) confirms safe timing.

## Risks

- **Migration risk (LOW):** additive `ALTER TABLE ADD COLUMN` with `DEFAULT` — SQLite handles this
  safely for existing rows; no data loss possible. Mitigated by the explicit backfill UPDATE being
  scoped/idempotent (`last_updated < '2026-08-11'` guard).
- **Cron auth risk (MEDIUM, accepted per SPEC Constraints):** the refresh depends on at least one
  user having a live authenticated Fyers session at ~15:20 IST. If tokens have expired app-wide,
  refresh fails every night until someone re-authenticates. This is the EXACT failure mode SPEC
  AC#2 requires visible signaling for — accepted risk, not a gap, because the fallback (last-good
  data + Telegram alert) is the designed behavior, not an unhandled edge case.
- **Frontend badge risk (LOW):** if `agent.stats_source` is `null`/`undefined` (e.g. a stale cached
  API response before deploy propagates), the ternary defaults to `'backtest'` display — acceptable
  fail-safe (never silently shows nothing, and 'backtest' is the more conservative/skeptical label
  vs defaulting to 'live').
- **Runtime/rate-limit risk:** addressed exhaustively in the CAUTION section above; residual risk
  mitigated by the mandatory timed dry-run (checklist item 20) before crontab install.

## Integration Notes

- `engine/risk_orchestrator.py`'s Kelly-criterion sizing (lines ~38, 107-115, 152-154) reads
  `win_rate`/`total_trades` from `_get_agent_config()` → `Database.get_agent_config()` — confirmed
  this PLAN does not touch that read path or its field names; `stats_source` is purely additive and
  ignored by the orchestrator (no behavior change there, satisfying the SPEC's hard constraint that
  the numeric write path must keep working unchanged for Kelly sizing).
- `check_nightly_learning_report.py` reads `backtest_results` (unrelated table, no `stats_source`
  needed) — no change required there, but note for EXECUTE: this script's report could optionally
  be extended to also report `backtest_refresh_status` in a future iteration; NOT required by this
  SPEC/PLAN (out of scope — the report already implicitly reflects freshness via `run_date`, and the
  Telegram-alert-on-failure from `run_backtests_cron.py` is the primary visible-failure channel).

---

## Validate Contract

Status: PASS
Date: 12-08-26
date: 2026-08-12
generated-by: outer-pvl

Parallel strategy: sequential (deep verification performed directly against source files in a single validate pass — vc-agent-strategy-compare scored this 3/7 signals (S2 schema surface, S6 high-risk class, S7 6-file blast radius) = MEDIUM, nominally parallel-subagents-eligible, but the two-layer fan-out was executed as direct file-by-file verification rather than spawned agents given tool constraints in this session)
Rationale: 3/7 signals — schema migration + high-risk class + 6-file blast radius, no phase-program/multi-direction signals present

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| AC#1 | `backtest_results.run_date` advances nightly (not pinned stale) | Hybrid | `sqlite3 trading_app.db "SELECT strategy_name, run_date FROM backtest_results ORDER BY run_date DESC LIMIT 15;"` run on 2+ separate nights post-deploy | A |
| AC#2 | refresh failure is visible + nightly learning falls back to last-good data | Agent-Probe | Force-unauthenticate all sessions, run `run_backtests_cron.py` manually; confirm log line + Telegram alert + `backtest_refresh_status` row shows `FAILED` + `backtest_results` unchanged | A |
| AC#3 | capital-protection shadow-out behavior unregressed | Hybrid | `grep "RULE-BASED (no AI)" logs/dashboard.log` across 2+ post-fix nightly runs | A |
| AC#4/AC#5 | every `swarm_agent_configs` stat visibly tagged backtest vs live; Strategy 8 case no longer misleading | Agent-Probe | `sqlite3` row inspection (`stats_source` non-null on every row) + manual `/admin.html` + dashboard visual spot-check | A |
| AC#6 | zero-trade-strategies question documented as confirmed out of scope with a tracked follow-up | Fully-Automated | `grep -n "Strategies 1-7\|zero-trade\|CONFIRMED OUT OF SCOPE" strategy-self-improvement_SPEC_11-08-26.md` (present) AND `find process/general-plans/backlog -iname "*zero-trade*"` (post-EXECUTE) | B |
| Regression — syntax | 3 touched/new Python files compile cleanly | Fully-Automated | `py_compile trading-app/models.py trading-app/engine/nightly_learning.py trading-app/run_backtests_cron.py` exits 0 | A |
| Regression — precommit | project convention gate | Fully-Automated | `python3 trading-app/precommit_check.py` exits 0 (script confirmed present, 6809 bytes) | A |
| Regression — smoke | project convention gate | Fully-Automated | `python3 trading-app/smoke_test.py` exits 0 (script confirmed present, 3902 bytes) | A |
| Regression — migration safety | additive `ALTER TABLE ADD COLUMN`, no data loss | Fully-Automated | `sqlite3 trading_app.db "SELECT win_rate, total_trades FROM swarm_agent_configs LIMIT 1;"` before AND after the ALTER, confirm no error and values unchanged | A |
| CAUTION — cron runtime | `run_backtests_cron.py` completes safely inside the 15-min lead window | Hybrid | `time .venv/bin/python3 run_backtests_cron.py` manual timed dry-run on the VM (authenticated session present) before crontab install | A |

gap-resolution legend: A — proven now (gate passes in this cycle). B — fixed in this plan (backlog stub file created by Implementation Checklist item 15, satisfies AC#6's "tracked follow-up" proof requirement).

C-4 reconciliation: no Known-Gap rows above — every developed behavior in this plan's blast radius has a Fully-Automated, Hybrid, or Agent-Probe gate; the Agent-Probe/Hybrid weighting is intentional (no automated test harness exists for `nightly_learning.py`/`backtest_engine.py`/`run_backtests.py`/the `swarm_agent_configs`/`backtest_results` write paths, confirmed via `process/context/tests/all-tests.md` and SPEC Constraints — not a shortcut).

Legacy line form (retained for existing validate-contract consumers):
- Provenance column + write-site tagging: Hybrid: `sqlite3` before/after value-check | Fully-Automated: `py_compile` + grep verification (`stats_source='backtest'` count=5, `stats_source='live'` count=1)
- Frontend badge: Agent-Probe: manual `/admin.html` + dashboard visual check for `(backtest)`/`(live)` labels
- Cron refresh script: Hybrid: forced-unauth failure-path check + timed dry-run | Agent-Probe: forced-failure Telegram alert confirmation
- Backlog stub: Fully-Automated: `find process/general-plans/backlog -iname "*zero-trade*"`

Failing stub note: this codebase has no pytest infra (confirmed) and none of the Fully-Automated rows above are new source-code *behaviors* to TDD — they are pre-existing regression commands (`py_compile`/`precommit_check.py`/`smoke_test.py`) or one-off grep/sqlite verification checks against a migration that either succeeded or didn't. No JS/pytest-style failing stub applies; each row's command is directly runnable as-is by execute-agent.

Dimension findings:
- Infra fit: PASS — single systemd service (`sritej-trading.service`) owns `models.py`/`app.py`; confirmed no other service (`sritej-orchestrator`, `sritej-researcher`) imports `models.py`, so `systemctl restart sritej-trading` (Implementation Checklist #18) fully gates the migration with no concurrent-process risk. `init_db()` runs synchronously via `sqlite3.connect()` at module-import time, before uvicorn accepts requests — no live-request concurrency during the `ALTER TABLE`. New file `run_backtests_cron.py` introduces no new runtime surface (standalone cron script, same shape as existing `check_nightly_learning_report.py`/`run_backtests.py`).
- Test coverage: PASS — tier assignments correctly follow the waterfall; migration (high-risk class per `vc-test-coverage-plan`) has its required Hybrid-minimum gate satisfied (pre/post-ALTER value-check row).
- Breaking changes: PASS — `update_agent_config()`'s new `stats_source` kwarg is backward-compatible (verified against real signature at `models.py:849`, matches the existing optional-kwarg pattern used by `status`/`pending_config_json`/`is_paper_trading`/`continuous_losses`/`asset_class`). `SELECT *` + `aiosqlite.Row` → `dict()` confirmed for both `get_agent_config`/`get_all_agent_configs` (models.py:801,814) — new column flows through 4 confirmed call sites (`app.py:1388,3017,3301,3512`) with zero route code change. `risk_orchestrator.py`'s Kelly-sizing read path (lines 106-115, 152-154) confirmed to read only `win_rate`/`total_trades` via `get_agent_config()`, no `stats_source` dependency — untouched as claimed.
- Security surface: PASS — no new auth/secrets logic; cron script's headless-auth loop (`_get_headless_client()`) mirrors `news_worker.py`'s `_get_validation_client()` exactly (verified line-for-line); Telegram webhook_url resolution (`getattr(state, "webhook_url", "") or os.getenv("TELEGRAM_WEBHOOK", "")`) copied verbatim from `check_nightly_learning_report.py:165-168`. Additive-only migration, no destructive writes.
- Section 1 (Provenance column) feasibility: PASS — mechanical feasibility confirmed exact (CREATE TABLE 284-296, migration block after 313, `update_agent_config` sig at 849, `record_trade_outcome` call at ~981). Minor doc-accuracy nit (non-blocking): the plan's rationale for `backtest_refresh_status`'s schema ("near the `global_kill_switch` table, single-row pattern") is imprecise — `global_kill_switch` is actually append-only (`AUTOINCREMENT` id, `ORDER BY id DESC LIMIT 1`), not a `CHECK(id=1)` single-row table; no existing table in `models.py` uses that exact pattern. The proposed SQL itself is valid and correct — this introduces a new (sound) pattern rather than copying an existing one. No functional risk.
- Section 2 (Frontend badge) feasibility: PASS — all 4 edit targets verified exact in `app.js` (3344, 3376, 3380) and `admin.html` (985, 988-989, 1029). Purely additive, safe ternary fallback confirmed.
- Section 3 (Cron script) feasibility: PASS (after P1 fix) — every dependency (`run_all_backtests`, `save_backtest_result`, `FyersClient`, `USER_STATES`, `state.webhook_url`) verified to exist with matching signatures. **Cron day-of-week spec corrected during this VALIDATE pass** (P1 applied — see below): `check_and_run_nightly_learning` confirmed to have no weekday gate (fires 7 days/week via `auto_trader.py`'s `if not any_market_open:` branch), so the crontab entry now uses `*` instead of `1-5` to match SPEC's locked "nightly, every run" cadence constraint.
- Section 4 (Backlog stub) feasibility: PASS — `process/general-plans/backlog/` exists, naming convention (`_NOTE_dd-mm-yy.md`) matches `_GUIDE.md`.

Plan updates applied (V6):
- P1 — Corrected crontab day-of-week field from `1-5` (Mon-Fri) to `*` (every day) in Section 3.2 (line 403 cron entry, lines 405-415 rationale text) and Implementation Checklist item 21 (crontab install command) — confirmed via direct read of `engine/automation.py:1142-1169` and `workers/auto_trader.py:2406-2429` that `check_and_run_nightly_learning` has no weekday/holiday gate and fires 7 nights/week, matching SPEC's locked AC#1 cadence constraint. This resolves the plan's own open CAUTION item (previously deferred to "confirm during EXECUTE") before EXECUTE begins.

Open gaps: none unresolved. Minor non-blocking observation carried forward as an execute-agent note (not a gate item): the `backtest_refresh_status` table's design-rationale comment references `global_kill_switch` as a "single-row pattern" precedent that doesn't literally exist in the codebase (see Section 1 feasibility finding above) — cosmetic only, no fix required before EXECUTE.

What this coverage does NOT prove:
- Real production wall-clock timing consistency night-over-night — only one manual dry-run is required before crontab install; a single dry-run doesn't prove the runtime stays stable over time (e.g. as `backtest_results` grows or Fyers API latency varies).
- Behavior when multiple users' Fyers sessions expire at slightly different times around the 15:20 IST refresh window — only "zero authenticated users" and "at least one authenticated user" paths are covered by AC#2's Agent-Probe gate.
- Whether `save_backtest_result`'s `note` field (populated from `r.get("error", "")` on partial-failure strategies like "insufficient historical data") is surfaced anywhere in the UI — not required by SPEC, not gated here.
- Multi-day drift or an unusual null/undefined `stats_source` edge case beyond the single-row spot-check in AC#4/AC#5's Agent-Probe gate.
- Concurrent-migration race with `sritej-orchestrator`/`sritej-researcher` — ruled out by direct code inspection (neither imports `models.py`), not by a live concurrency test.

Gate: PASS (no FAILs, plan updated with P1 fix applied)
Accepted by: N/A — Gate: PASS, no unresolved concerns requiring acceptance. The one CONCERN found (cron day-of-week spec) was resolved directly via Proposed Plan Update P1 during this VALIDATE pass, per explicit user instruction ("apply P1... write the Validate Contract section as Gate: PASS"), rather than being carried forward as an accepted gap.

---

## Resume and Execution Handoff

1. **Selected plan file path:**
   `process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_PLAN_11-08-26.md`
2. **Last completed phase or step:** VALIDATE complete — Gate: PASS (see `## Validate Contract`
   above). No EXECUTE work started.
3. **Validate-contract status:** written, 12-08-26 — Gate: PASS, `generated-by: outer-pvl`. P1 fix
   (crontab day-spec `1-5` → `*`) applied to Section 3.2 and Implementation Checklist #21 during
   this VALIDATE pass.
4. **Supporting context files loaded during PLAN:**
   - `process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_SPEC_11-08-26.md`
   - `trading-app/models.py` (full)
   - `trading-app/engine/nightly_learning.py` (full)
   - `trading-app/engine/backtest_runner.py` (full)
   - `trading-app/run_backtests.py` (full)
   - `trading-app/check_nightly_learning_report.py` (full)
   - `trading-app/engine/risk_orchestrator.py` (lines 1-170)
   - `trading-app/workers/news_worker.py` (`_get_validation_client` region, lines 75-100)
   - `trading-app/fyers_client.py` (rate-limit/cooldown grep + `get_historical` region)
   - `trading-app/static/app.js` (win_rate/total_trades render region, lines 3330-3390)
   - `trading-app/static/admin.html` (both agent-card render regions, lines 965-1035)
   - `start_cloud.sh` (crontab install pattern, lines 1-70)
5. **Next step for a fresh agent picking up mid-execution:** VALIDATE is complete (Gate: PASS) —
   proceed to `ENTER EXECUTE MODE` against this plan, following the Implementation Checklist in
   order. If EXECUTE has already started, check `git diff` against the Touchpoints table above and
   cross-reference the Execution
   Checklist numbering to find the next unstarted step.

---

## Autonomous Goal Block

```
SESSION GOAL: Fix stale nightly backtest refresh; add stats_source provenance to
swarm_agent_configs; surface backtest-vs-live badges on dashboard/admin.
Charter + umbrella plan: N/A — single plan, not a phase program.
Autonomy: Standard RIPER-5 approval gates apply — no standing autopilot/autonomy grant for this
session. EXECUTE requires explicit "ENTER EXECUTE MODE".
Hard stop conditions / safety constraints:
- Live-money system: do not skip the manual timed dry-run (Implementation Checklist #20) before
  installing the crontab entry (#21).
- Do not install the crontab entry before the dry-run confirms runtime safely fits the 15-min lead
  window (revise to 15:10 IST if runtime approaches 10 minutes).
- `systemctl restart sritej-trading` (Implementation Checklist #18) is required after deploying
  models.py/nightly_learning.py/app.js/admin.html — do not skip; the schema migration only runs
  safely at process-restart time (before uvicorn accepts requests).
- Do not touch `engine/risk_orchestrator.py`'s Kelly-sizing read path, or the strict rule-based
  capital-protection block in `nightly_learning.py` (lines 272-326) — both confirmed untouched by
  this plan and must stay that way.
- Backup (.bak-<timestamp>) the 5 touched files on the VM before scp (Implementation Checklist #17).
Next phase: EXECUTE — `process/general-plans/active/strategy-self-improvement_11-08-26/strategy-self-improvement_PLAN_11-08-26.md`
Validate contract: inline in plan (`## Validate Contract` section above, Gate: PASS, 12-08-26)
Execute start: Fully-Automated: `py_compile trading-app/models.py trading-app/engine/nightly_learning.py trading-app/run_backtests_cron.py` | Hybrid/Agent-Probe: see Test Gates table in Validate Contract | high-risk pack: no (schema migration is additive-only, LOW risk per plan's own Risks section — no separate 5-artifact evidence pack required, standard Hybrid migration-safety gate suffices)
```
