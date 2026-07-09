---
name: plan:multi-asset-expansion-phase-01-asset-abstraction-layer
description: "Multi-asset expansion — Phase 1: asset-class abstraction layer (foundation, no new trading)"
date: 05-07-26
metadata:
  node_type: memory
  type: plan
  feature: multi-asset-expansion
  phase: phase-01
---

# Phase 1 — Asset-Class Abstraction Layer

**Program:** multi-asset-expansion
**Umbrella plan:** `process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md`
**Phase status:** ⏳ PLANNED
**Report destination:** `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-01-asset-abstraction-layer_REPORT_05-07-26.md`

**Date**: 05-07-26
**Complexity**: COMPLEX
**Status**: ⏳ PLANNED

---

## Overview

Phase 1 of the multi-asset-expansion program. Builds a config-driven AssetClass
abstraction layer so the existing single strategy engine can, in future phases, run on
any Indian derivatives asset class (index/stock/commodity/currency options) — while
Phase 1 itself adds no new trading and leaves NIFTY's live behavior byte-for-byte
unchanged. See Purpose below for full context.

## Acceptance Criteria

1. `trading-app/engine/asset_classes.py` exists with a registry keyed by asset-class
   name, seeded with an `INDEX_OPTIONS` entry whose values are verbatim transcriptions
   of today's live NIFTY constants (session hours, hard-exit time, exchange, symbol
   prefix, lot-size source, volatility measure).
2. `state.is_market_open()` (no-arg call) returns identical results before and after
   the refactor for the full representative timestamp set in Step G1.
3. `daily_hard_exit_scheduler()` still fires at exactly 15:14 IST after the refactor
   (Step G2).
4. `get_volatility("INDEX_OPTIONS")` is a proven transparent passthrough to the
   existing India VIX quote path (Step D4/G3), and existing VIX call sites in
   `regime_worker.py`/`auto_trader.py`/`ai_engine.py` show zero behavioral diff.
5. `build_symbol("INDEX_OPTIONS", ...)` reproduces exact existing NIFTY/VIX symbol
   strings (Step F3).
6. `fetch_lot_sizes.py` successfully downloads and parses MCX_COM.csv and NSE_CD.csv
   in addition to NSE_FO.csv, with TLS verification preserved (`certifi.where()`),
   and existing NSE_FO consumers see unchanged output (Step E).
7. No new live order-placement path is reachable for MCX/NSE_CD symbols — grep-provable
   at Exit Gate.
8. All NIFTY regression checks (G1-G4) are recorded as PASS in the phase report before
   the phase is marked VERIFIED.

## Phase Completion Rules

- This phase is `CODE DONE` only when all checklist items (A1-G5) are checked AND the
  Exit Gate commands have been run with their expected results confirmed.
- This phase is `VERIFIED` only when, in addition to `CODE DONE`: (a) the validate-contract
  gates are green (or explicitly accepted CONDITIONAL), (b) the NIFTY regression
  checkpoint (Step G, all of G1-G4) is recorded as PASS in the phase report, and (c) EVL
  has independently re-confirmed the gates via a spawned `vc-tester` run.
- Code-only completion without regression evidence must be reported as `CODE DONE`,
  never `VERIFIED` — this is a live-money app and the distinction is load-bearing.

---

## Purpose

ControlN is currently a NIFTY-only (INDEX_OPTIONS) options auto-trader with market-hours,
hard-exit timing, volatility scoring, lot-size lookup, and symbol construction all
hard-coded to NSE index-options assumptions. This phase builds the **asset-class
abstraction layer**: a config-driven registry that lets the SAME strategy engine
eventually run on any instrument type (stocks, commodities, currencies) by config,
without touching core logic per asset class.

This phase adds **zero new trading capability**. It is pure refactor + foundation. The
single hardest requirement is that NIFTY's live behavior — market hours, the 15:14
hard-exit, VIX-based regime scoring, and order flow — must be **byte-for-byte
unchanged** after this refactor, because this is a live-money app. Every step below is
written to default to today's NIFTY behavior when no asset class is specified.

---

## Entry Gate

- This is the first phase of the program — no upstream phase dependency.
- Repo is on a clean working tree (or changes are stashed) before EXECUTE begins,
  per environment safety rules.
- Confirm no test-runner exists yet for `trading-app/` (RESEARCH step must verify
  this — search for `pytest.ini`, `conftest.py`, `tests/`); if one is found, treat
  it as ground truth over this plan's assumptions.

---

## Blast Radius

**Risk class:** live-money trading logic (highest severity — no auth/billing/schema
surface touched directly, but a regression here breaks real order flow).

**Files/modules that WILL be touched:**
- `trading-app/state.py` — `is_market_open()`, `get_holiday_reason()`, market-phase
  logic (currently module-level functions, no asset-class parameter)
- `trading-app/app.py` — the hard-coded 9:15–15:30 market-hour checks (`market_start`/
  `market_end` patterns, `_is_market_open()` wrapper at line ~2443, `market_phase`
  status field at line ~295, `market_open` field at line ~2651), the
  `daily_hard_exit_scheduler()` function (line ~1364, hard-coded `hour=15, minute=14`),
  and any symbol/USER_CONTEXTS handling that assumes NSE index options
- `trading-app/engine/automation.py` — `market_end_today` (line ~696, hard-coded
  `hour=15, minute=30`) and `market_end_learning` (line ~760, hard-coded `hour=15,
  minute=35`) EOD-report timing checks; `hard_exit_triggered` flag plumbing
- `trading-app/engine/ws_feed.py` — hard-coded subscription to
  `"NSE:NIFTY50-INDEX"` / `"NSE:INDIAVIX-INDEX"` (line ~14, ~159)
- `trading-app/workers/market_worker.py` — hard-coded VIX symbol
  `"NSE:INDIAVIX-INDEX"` cache population (lines ~80, ~101, ~281, ~416-417)
- `trading-app/workers/regime_worker.py` — `state.is_market_open()` call (line ~41,
  no-arg) and VIX-driven regime prompt (line ~73/81)
- `trading-app/workers/auto_trader.py` — imports `is_market_open` (line ~27), calls
  it no-arg (line ~1280), and does inline VIX quote fetch + adjustment (line ~988-990)
- `trading-app/engine/ai_engine.py` — India VIX used directly in regime prompt text
  (multiple lines, ~615-947) — read-only volatility CONSUMER, not a session/hours owner
- `trading-app/engine/signals.py` — VIX adjustment logic (line ~218)
- `trading-app/engine/strategy_orb.py` — VIX filter logic (line ~108)
- `trading-app/engine/strategy_9.py` — hard VIX gate thresholds specific to the NIFTY
  strategy (lines ~35-40, ~246) — these are strategy-owned VIX *thresholds*, NOT the
  volatility *source*; this phase abstracts the source, not per-strategy thresholds
- `trading-app/engine/strategy_wisdom.py` — VIX dependency (to be confirmed exact
  lines during RESEARCH; not yet read line-by-line in this planning pass — flag as
  a RESEARCH follow-up, see Blockers)
- `trading-app/fetch_lot_sizes.py` — currently downloads only
  `https://public.fyers.in/sym_details/NSE_FO.csv` (line ~11); needs MCX_COM.csv and
  NSE_CD.csv support added
- `trading-app/fyers_client.py` — symbol handling is currently ad-hoc string literals
  (`"NSE:..."` prefixes scattered through method calls like `get_quote`,
  `get_option_chain_strikes` at line ~793, `find_nearest_expiry` at line ~883); no
  centralized exchange-prefix-by-asset-class builder exists yet
- **New file:** `trading-app/engine/asset_classes.py` (or `trading-app/config/asset_classes.py`
  — final placement decided in INNOVATE/RESEARCH; default assumption: `engine/asset_classes.py`
  to sit alongside other engine modules) — the new AssetClass registry

**Files/modules this phase explicitly does NOT touch:**
- `static/*` (all UI files — no user-facing asset-class picker in this phase)
- Auth/session logic (`auth_utils.py`, session cookie signing) — untouched
- `models.py` schema — **conditionally flagged**: if the AssetClass registry needs a
  per-user default asset class persisted (e.g. a `users.default_asset_class` column),
  that is a schema change and must be called out explicitly in RESEARCH/INNOVATE before
  PLAN-SUPPLEMENT adds it here. Default assumption for Phase 1: **no schema change** —
  asset class defaults to `INDEX_OPTIONS` in code, not persisted per-user yet. If this
  assumption is wrong, PLAN-SUPPLEMENT must add a Step to this checklist.
- Actual commodity/currency order placement logic — Phase 3+ scope, not touched here
- `workers/health_agent.py` LLM auto-remediation guardrails — unrelated surface

---

## Design: Target Architecture (put in place by this phase)

**1. AssetClass registry (`trading-app/engine/asset_classes.py`, new module)**

A single source of truth, one entry per asset class, containing:

```
AssetClass:
  name: str                    # "INDEX_OPTIONS", "STOCK_OPTIONS", "COMMODITY_OPTIONS", "CURRENCY_OPTIONS"
  exchange: str                 # "NSE", "MCX", "NSE_CD"
  session_open: (hour, minute)  # e.g. (9, 15) equity/index; (9, 0) MCX; (9, 0) currency
  session_close: (hour, minute) # e.g. (15, 30) equity/index; (23, 30) MCX; (17, 0) currency
  symbol_prefix: str            # e.g. "NSE:", "MCX:", "NSE_CD:" (source of truth for symbol construction)
  lot_size_source: str          # "NSE_FO" | "MCX_COM" | "NSE_CD" — matches fetch_lot_sizes.py CSV keys
  expiry_cycle: str             # e.g. "weekly-thursday" (index), "monthly" (commodity) — descriptive only in Phase 1, not enforced yet
  volatility_measure: str        # "india_vix" | "atr" — drives get_volatility() dispatch
  hard_exit_time: (hour, minute) # e.g. (15, 14) equity/index; (23, 20) commodity; (16, 50) currency
  risk_config: dict              # SL ranges / max trades / position sizing — Phase 1 carries the field, does not wire it into strategies yet (that's Phase 3 scope)
```

Registry is a `Dict[str, AssetClass]` keyed by name, with `DEFAULT_ASSET_CLASS =
"INDEX_OPTIONS"` matching today's live NIFTY config exactly (`(9,15)`–`(15,30)`,
`"NSE:"`, `"NSE_FO"`, `"india_vix"`, `(15,14)`).

**2. Session manager (in `state.py`)**

- `is_market_open(asset_class: str = DEFAULT_ASSET_CLASS) -> bool` — becomes registry-driven:
  looks up `session_open`/`session_close` from the `AssetClass` entry instead of the
  hard-coded `(9,15)`/`(15,30)` literals. **Backward compat:** calling with no argument
  must return byte-identical results to today's function for every timestamp, since
  `DEFAULT_ASSET_CLASS` mirrors today's values exactly.
- All 4+ scattered `(hour=9,minute=15)`/`(hour=15,minute=30)` literal comparisons in
  `app.py` and `engine/automation.py` are migrated to call through this one function
  (or a thin per-asset-class helper) instead of re-deriving hours inline.

**3. Per-asset hard-exit**

- `daily_hard_exit_scheduler()` in `app.py` (line ~1364) changes its single hard-coded
  `target = now.replace(hour=15, minute=14, ...)` to iterate per active asset class (or,
  in Phase 1 since no non-index trading exists yet, simply read the hard-exit time from
  the `INDEX_OPTIONS` registry entry instead of a bare literal). **Backward compat:**
  since only `INDEX_OPTIONS` users exist today, the effective wall-clock trigger time
  must remain exactly 15:14 IST.

**4. Volatility abstraction**

- New function `get_volatility(asset_class: str, symbol: str) -> Optional[float]` (new
  module or added to `engine/signals.py`) that dispatches: `india_vix` → today's exact
  `"NSE:INDIAVIX-INDEX"` quote path (delegates to existing `market_worker.py` cache /
  `fyers_client.get_quote`); `atr` → **stub only in Phase 1** (raises
  `NotImplementedError` or returns `None` with a log line — commodities aren't traded
  yet, so this branch has no live caller). Existing call sites
  (`regime_worker.py`, `auto_trader.py`, `ai_engine.py`) are **not required to switch
  call sites in Phase 1** if that risks regression — see Step D below for the
  conservative sequencing choice.

**5. Lot-size fetching**

- `fetch_lot_sizes.py` extended to also download+parse
  `https://public.fyers.in/sym_details/MCX_COM.csv` and
  `https://public.fyers.in/sym_details/NSE_CD.csv`, producing a per-exchange lot-size
  map (e.g. `{"NSE_FO": {...}, "MCX_COM": {...}, "NSE_CD": {...}}`) instead of a single
  flat map. **Backward compat:** existing NSE_FO consumers must get the exact same
  values via the exact same access pattern (either keep a flat top-level dict merged
  from NSE_FO for old callers, or update the 1-2 call sites — confirm via grep in
  RESEARCH before choosing).

**6. Exchange-aware symbol construction**

- New helper (e.g. `build_symbol(asset_class: str, instrument: str) -> str` in
  `fyers_client.py` or `engine/asset_classes.py`) that derives the exchange prefix from
  the `AssetClass.symbol_prefix` field instead of literal `"NSE:"` strings scattered
  through `fyers_client.py`. **Phase 1 scope:** add the helper and prove it produces
  identical strings for existing INDEX_OPTIONS call sites; do NOT force-migrate every
  existing `"NSE:" + symbol` call site if that expands blast radius unnecessarily —
  migrate only the sites already touched by Steps B/C/D so regression risk stays
  bounded (full sweep can be a Phase 2 cleanup item, documented as a Test Infra /
  follow-up note, not silently dropped).

---

## Implementation Checklist

### Step A — Asset-class registry

- [ ] A1. Create `trading-app/engine/asset_classes.py` with the `AssetClass` dataclass
  (or plain dict-of-dicts, decide in INNOVATE) as specified in "Design" above.
- [ ] A2. Add exactly one entry: `INDEX_OPTIONS`, with values that are a **verbatim
  transcription** of today's live constants (`(9,15)`, `(15,30)`, `"NSE:"`, `"NSE_FO"`,
  `"india_vix"`, `(15,14)`) — sourced from `state.py` lines 222-227 and `app.py` line
  ~1373 (`hour=15, minute=14`).
- [ ] A3. Add `DEFAULT_ASSET_CLASS = "INDEX_OPTIONS"` module constant.
- [ ] A4. Add placeholder (not yet used) entries for `STOCK_OPTIONS`,
  `COMMODITY_OPTIONS`, `CURRENCY_OPTIONS` with best-known values (equity 9:15-15:30 for
  stock options; MCX 9:00-23:30 hard-exit ~23:20 for commodities; currency 9:00-17:00
  hard-exit ~16:50) — clearly commented as **unverified placeholders, not yet
  live-tested**, so Phase 3 RESEARCH has a documented starting point rather than a
  blank slate.
- [ ] A5. Unit-verify (manual or scripted): `registry["INDEX_OPTIONS"].session_open ==
  (9, 15)` and `.hard_exit_time == (15, 14)` match the literals being replaced in Steps B/C.

### Step B — Session manager migration (the ~27 scattered market-hour checks)

- [ ] B1. In `state.py`, change `is_market_open()` signature to
  `is_market_open(asset_class: str = DEFAULT_ASSET_CLASS) -> bool`, sourcing
  `market_start`/`market_end` from `asset_classes.registry[asset_class]` instead of the
  literal `hour=9,minute=15` / `hour=15,minute=30`. Keep `_is_market_open = is_market_open`
  alias intact (line 233) for backward-compat callers.
- [ ] B2. Run `grep -n "is_market_open\|(9, *15)\|(15, *30)" trading-app/app.py
  trading-app/engine/*.py trading-app/workers/*.py` during EXECUTE to get the **exact,
  current, authoritative count and line list** (this plan's grounding pass found ≥4 in
  `app.py` plus 2 more in `engine/automation.py`, `1` in `workers/regime_worker.py`,
  and `1` in `workers/auto_trader.py` — treat the "~27" figure in the task brief as an
  upper-bound estimate to verify, not a hard target; do not force a count).
- [ ] B3. For each no-arg call site found in B2 that implicitly means "is NIFTY's market
  open right now" (e.g. `app.py` line ~2443 `_is_market_open()`, `workers/regime_worker.py`
  line ~41 `state.is_market_open()`, `workers/auto_trader.py` line ~1280
  `is_market_open()`), leave the call **unchanged** (no-arg call now resolves through
  `DEFAULT_ASSET_CLASS` = `INDEX_OPTIONS`, which is byte-identical to today). Do NOT
  thread an `asset_class` parameter through every caller in Phase 1 — that is
  unnecessary blast-radius expansion since no non-index caller exists yet.
- [ ] B4. For the literal inline comparisons found in `engine/automation.py`
  (`market_end_today` line ~696, `market_end_learning` line ~760), leave as literals OR
  migrate to read from the registry — **decide in INNOVATE**: migrating reduces drift
  risk long-term but touches EOD-report timing, a live behavior; the conservative
  default is to leave these two literals untouched in Phase 1 (they are EOD-reporting
  cutoffs, not market-open/close gates, and are lower risk to leave alone) and note them
  as a Phase 2 cleanup candidate.

### Step C — Per-asset hard-exit

- [ ] C1. In `app.py`, `daily_hard_exit_scheduler()` (line ~1364): replace the literal
  `target = now.replace(hour=15, minute=14, second=0, microsecond=0)` with
  `hh, mm = asset_classes.registry[DEFAULT_ASSET_CLASS].hard_exit_time; target =
  now.replace(hour=hh, minute=mm, second=0, microsecond=0)`.
- [ ] C2. Confirm no other hard-exit time literal exists elsewhere (grep for
  `hard_exit\|15, *14\|15,14` across `trading-app/` during EXECUTE) before declaring
  this step complete.
- [ ] C3. **Regression proof required for this step specifically:** manually compute
  that for any `now` timestamp, the new code path produces the exact same `target`
  wall-clock time (15:14 IST) as the old literal did. This is the single highest-risk
  line in the whole phase — a bug here either fires the safety-net hard-exit early/late
  or not at all, on a live-money app.

### Step D — Volatility abstraction

- [ ] D1. Add `get_volatility(asset_class: str = DEFAULT_ASSET_CLASS, symbol: str =
  "NSE:INDIAVIX-INDEX") -> Optional[float]` (placement TBD in INNOVATE — likely
  `engine/asset_classes.py` or a new `engine/volatility.py`). For `india_vix` measure:
  delegate to the exact existing lookup path used today (prefer routing through
  `market_worker.py`'s cached VIX value if available, falling back to
  `fyers_client.get_quote("NSE:INDIAVIX-INDEX")`, matching `auto_trader.py` line
  ~988-990's existing fallback pattern) — do not introduce a second, divergent VIX
  fetch path.
- [ ] D2. For `atr` measure: implement as a stub that returns `None` and logs
  `"ATR volatility not yet implemented — asset_class={asset_class}"` (no live caller
  exists yet since no commodity trading happens in this phase; do not fabricate ATR
  math without a strategy to validate it against).
- [ ] D3. **Conservative sequencing decision (document in phase report):** existing VIX
  call sites in `regime_worker.py`, `auto_trader.py`, and `ai_engine.py` are **NOT
  required to switch to `get_volatility()` in Phase 1** — leaving them calling
  `fyers_client.get_quote("NSE:INDIAVIX-INDEX")` directly is zero-regression-risk.
  `get_volatility()` exists and is proven correct in isolation (D1/D4) so Phase 2/3 can
  adopt it without needing to re-derive the VIX fetch logic. If INNOVATE decides full
  migration is worth doing now, add explicit sub-steps here before EXECUTE and treat
  each migrated call site as its own regression-checked unit.
- [ ] D4. Add a manual/scripted check: `get_volatility("INDEX_OPTIONS")` returns the
  same numeric value (within one quote-refresh cycle) as the existing direct
  `"NSE:INDIAVIX-INDEX"` quote call, proving the abstraction is a transparent passthrough.

### Step E — Lot-size multi-exchange

- [ ] E1. In `fetch_lot_sizes.py`, refactor the single `NSE_FO.csv` download+parse
  (currently around line 7-11, `requests.get("https://public.fyers.in/sym_details/NSE_FO.csv",
  verify=certifi.where(), ...)`) into a loop/function parameterized by
  `{"NSE_FO": url1, "MCX_COM": url2, "NSE_CD": url3}` (URLs follow the same
  `https://public.fyers.in/sym_details/{KEY}.csv` pattern — confirm exact MCX_COM/NSE_CD
  filenames against Fyers' public listing during RESEARCH before hard-coding).
- [ ] E2. Preserve `verify=certifi.where()` (never `verify=False`) for all 3 new
  requests, per the existing security-remediation TLS-verification pattern already
  established in this codebase (see `process/context/all-context.md` §Security
  Remediation Phase 2 patterns — "any new outbound HTTPS call... should default to
  certifi-backed verification").
- [ ] E3. Output structure: produce a per-exchange dict AND confirm whatever
  currently consumes the flat NSE_FO-only output (grep for the output variable/file
  name during EXECUTE) still receives an identical NSE_FO-shaped result — either via a
  backward-compat flat alias or by updating the 1-2 known call sites, whichever is
  lower-risk once discovered.
- [ ] E4. Do not wire MCX_COM/NSE_CD lot sizes into any live strategy in this phase —
  fetching and storing them is the full scope; consumption is Phase 2/3.

### Step F — Exchange-aware symbol construction

- [ ] F1. Add `build_symbol(asset_class: str, instrument: str) -> str` (placement:
  `engine/asset_classes.py`, imported by `fyers_client.py` — avoids a circular import
  risk of putting it inside `fyers_client.py` itself if `asset_classes.py` ever needs
  to import client utilities later) that returns
  `f"{registry[asset_class].symbol_prefix}{instrument}"`.
- [ ] F2. Migrate ONLY the symbol-construction call sites already touched by Steps B-E
  (e.g. if D1's VIX fetch path or E's lot-size consumption ends up building a symbol
  string) to use `build_symbol("INDEX_OPTIONS", ...)`. Do not sweep every `"NSE:"`
  literal in `fyers_client.py` in this phase — that is a larger, separate cleanup
  (document as a Test Infra / follow-up note, not a silent scope drop).
- [ ] F3. Prove `build_symbol("INDEX_OPTIONS", "NIFTY50-INDEX") == "NSE:NIFTY50-INDEX"`
  and `build_symbol("INDEX_OPTIONS", "INDIAVIX-INDEX") == "NSE:INDIAVIX-INDEX"` exactly
  match today's literal strings used in `ws_feed.py` line ~14 and `market_worker.py`.

### Step G — NIFTY regression verification (mandatory exit-gate step, not optional)

- [ ] G1. **Market hours regression:** for a representative set of timestamps (before
  9:15, exactly 9:15, mid-day, exactly 15:30, after 15:30, on a listed NSE holiday, on a
  weekend), confirm `state.is_market_open()` (no-arg) returns identical boolean results
  before and after the Step B refactor. Prefer an automated script/test if a runner
  exists (see Blockers G-note); otherwise a documented manual walk-through with pinned
  timestamps is acceptable as a Hybrid/Agent-Probe gate.
- [ ] G2. **Hard-exit timing regression:** confirm `daily_hard_exit_scheduler()`
  computes the exact same 15:14 IST trigger wall-clock time after the Step C refactor,
  for at least 2 different "now" timestamps (one before 15:14 same day, one after 15:14
  same day rolling to next day).
- [ ] G3. **VIX/regime regression:** confirm `get_volatility("INDEX_OPTIONS")` (Step D)
  returns a value consistent with the direct `"NSE:INDIAVIX-INDEX"` quote at the same
  moment, and that `regime_worker.py` / `auto_trader.py` / `ai_engine.py` — since they
  are NOT migrated per D3 — are provably untouched by this phase's diff (git diff shows
  zero changes to those 3 files' VIX-reading lines, OR any touched lines are
  whitespace/import-only).
- [ ] G4. **Order-flow smoke check:** confirm `build_symbol` / lot-size changes have not
  altered any string or numeric value actually consumed by `auto_trader.py`'s live
  order-placement path (`client.place_order` call sites) — via direct comparison of
  before/after symbol strings and lot-size values for NIFTY, not just code review.
- [ ] G5. Record all 4 sub-results (G1-G4) as `Regression: [surface] — [PASS|FIXED|BLOCKED]`
  lines in the phase report per the program's Regression Checkpoint Standard.

---

## Exit Gate

```bash
# Confirm no residual bare literal market-hour checks were missed
grep -rn "hour=9, *minute=15\|hour=15, *minute=30\|hour=15, *minute=14" trading-app/app.py trading-app/engine/ trading-app/workers/
# Expected: only inside asset_classes.py registry definitions and/or the two
# EOD-report-cutoff literals explicitly left untouched per Step B4's INNOVATE decision
# (document exactly which literals remain and why in the phase report).

# Confirm registry import resolves and default matches today's constants
python3 -c "from trading_app.engine.asset_classes import registry, DEFAULT_ASSET_CLASS; a=registry[DEFAULT_ASSET_CLASS]; assert a.session_open==(9,15) and a.session_close==(15,30) and a.hard_exit_time==(15,14); print('OK')"
# Expected: OK
# (adjust import path to match actual package layout confirmed during EXECUTE)

# Run whatever validator/test suite RESEARCH confirms exists for trading-app/
# Expected: exact command TBD — see Blockers; if none exists, this becomes a
# Hybrid/Agent-Probe manual walkthrough of Step G, recorded in the phase report.
```

- All checklist items A1-G5 checked.
- NIFTY regression evidence (G1-G4) recorded as PASS in the phase report — no FIXED or
  BLOCKED entries remain unresolved.
- No commodity/currency live trading path exists or is reachable (grep confirms no new
  `client.place_order` call sites were added for MCX/NSE_CD symbols).
- Phase report written to report destination above.
- Program-level validators run (see umbrella `## Stable Program Goal` TEST GATES).

---

## Blockers That Would Justify BLOCKED Status

- No test runner (`pytest`/equivalent) confirmed for `trading-app/` — if RESEARCH
  cannot confirm one exists, Step G's automated proof degrades to Hybrid/manual, which
  is acceptable per this plan's Verification Evidence table but must be flagged, not
  silently accepted as a Known-Gap PASS (see vacuous-green ban in PLAN mode rules).
- `engine/strategy_wisdom.py`'s exact VIX dependency lines were not individually
  grep-verified during this planning pass (only confirmed via directory listing intent)
  — RESEARCH must confirm before EXECUTE touches anything near it; if it has an
  undiscovered hard-coded market-hours or hard-exit check, add a Step B/C sub-item.
- Exact MCX_COM.csv / NSE_CD.csv filenames on `public.fyers.in/sym_details/` are
  assumed by pattern, not confirmed live — Step E1 must verify the real URLs (a 404
  during EXECUTE is expected-and-handled, not a phase blocker, but must be resolved
  before E is marked done).
- If PLAN-SUPPLEMENT / INNOVATE decides a per-user `default_asset_class` DB column is
  needed now (contrary to this plan's "no schema change" assumption), that requires a
  reviewed migration and should be treated as scope-expansion requiring explicit
  sign-off, not silently added.

---

## Phase Loop Progress

- [ ] 1. RESEARCH — research-agent: confirm exact hard-coded check count/locations,
  test-runner existence, `strategy_wisdom.py` VIX lines, and real MCX_COM/NSE_CD CSV
  URLs; check plan drift against this plan.
- [ ] 2. INNOVATE — innovate-agent: decide (a) registry module placement
  (`engine/` vs `config/`), (b) whether `automation.py`'s EOD-cutoff literals migrate
  now or later (Step B4), (c) whether existing VIX call sites migrate to
  `get_volatility()` now or later (Step D3), (d) dataclass vs dict-of-dicts for
  `AssetClass`.
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: fold RESEARCH/INNOVATE findings into this plan
  (exact line numbers, confirmed URLs, INNOVATE decisions locked into Steps B4/D3) or
  mark "n/a — research clean".
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written below.
- [ ] 5. EXECUTE — all checklist items A1-G5 done; per-section test gates run and green.
- [ ] 6. EVL — all EVL gates green; NIFTY regression re-confirmed independently.
- [ ] 7. UPDATE PROCESS — phase report written, umbrella `## Current Execution State`
  updated, commit done.

**Validate-contract required before execute.** Step 4 (PVL) is unchecked and
`## Validate Contract` below is a placeholder — orchestrator must spawn
vc-validate-agent before any EXECUTE spawn for this plan.

---

## Touchpoints

- `trading-app/engine/asset_classes.py` (new)
- `trading-app/state.py`
- `trading-app/app.py`
- `trading-app/engine/automation.py`
- `trading-app/engine/ws_feed.py`
- `trading-app/workers/market_worker.py`
- `trading-app/workers/regime_worker.py`
- `trading-app/workers/auto_trader.py`
- `trading-app/fyers_client.py`
- `trading-app/fetch_lot_sizes.py`
- (read-only / not modified, but VIX-consuming and in blast-radius awareness):
  `trading-app/engine/ai_engine.py`, `trading-app/engine/signals.py`,
  `trading-app/engine/strategy_orb.py`, `trading-app/engine/strategy_9.py`,
  `trading-app/engine/strategy_wisdom.py`

---

## Public Contracts

- `state.is_market_open()` no-arg call signature and return semantics for the default
  (NIFTY) case are UNCHANGED — this is the load-bearing backward-compat contract of
  the whole phase.
- `daily_hard_exit_scheduler()`'s observable trigger time (15:14 IST) is UNCHANGED.
- `fetch_lot_sizes.py`'s existing NSE_FO output shape/access pattern for existing
  callers is UNCHANGED (or explicitly migrated at the 1-2 known call sites, decided in
  EXECUTE per Step E3).
- New public surface added (additive, non-breaking): `asset_classes.registry`,
  `asset_classes.DEFAULT_ASSET_CLASS`, `get_volatility()`, `build_symbol()` —
  all new, none replace an existing external contract.
- No public API (`app.py` route handlers) contract changes in this phase.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `registry["INDEX_OPTIONS"]` values match today's literals (session hours, hard-exit time, exchange, symbol prefix) | Fully-Automated (script check, Step A5) | Foundation registry is correctly seeded from live values |
| `is_market_open()` no-arg returns identical boolean across representative timestamps before/after refactor | Hybrid (manual/scripted timestamp walkthrough — Step G1; upgrade to Fully-Automated once a test runner is confirmed in RESEARCH) | NIFTY market-hours behavior is unchanged (program hard stop #1) |
| `daily_hard_exit_scheduler()` computes 15:14 IST trigger identically before/after refactor | Hybrid (manual timestamp math check — Step G2) | NIFTY hard-exit safety net is unchanged (program hard stop #1) |
| `get_volatility("INDEX_OPTIONS")` matches direct VIX quote value | Hybrid (live/staged quote comparison — Step G3/D4) | Volatility abstraction is a transparent passthrough, no regime-scoring drift |
| VIX call sites in `regime_worker.py`/`auto_trader.py`/`ai_engine.py` show zero behavioral diff (per D3 conservative sequencing) | Fully-Automated (`git diff` inspection of those 3 files — Step G3) | No unintended migration risk introduced to live regime logic |
| `build_symbol("INDEX_OPTIONS", ...)` reproduces exact existing literal strings for NIFTY/VIX symbols | Fully-Automated (string equality assertions — Step F3) | Symbol construction abstraction is byte-identical for existing usage |
| `fetch_lot_sizes.py` NSE_FO output unchanged for existing consumers after multi-exchange refactor | Hybrid (before/after diff comparison — Step E3) | Lot-size lookup backward compatibility preserved |
| MCX_COM.csv / NSE_CD.csv download+parse succeeds with `certifi`-verified TLS | Fully-Automated (script run, checks HTTP 200 + non-empty parse — Step E1/E2) | Multi-exchange lot-size foundation is in place without weakening TLS posture |
| No new live order-placement path reachable for MCX/NSE_CD symbols | Fully-Automated (grep for new `place_order` call sites — Exit Gate) | Program hard stop #2 (no new trading in Phase 1) is respected |
| Order-flow smoke: NIFTY symbol/lot-size values consumed by `auto_trader.py` unchanged | Agent-Probe (manual before/after value comparison — Step G4; live order flow can't be safely fully automated against a live-money broker in this phase) | Existing order flow is unaffected end-to-end |

---

## Test Infra Improvement Notes

- No `pytest`/test-runner configuration was found for `trading-app/` in the grounding
  reads used to write this plan (no `pytest.ini`, `conftest.py`, or `tests/` directory
  observed at the paths checked). RESEARCH must confirm this before PVL finalizes tier
  assignments. If confirmed absent, this phase should ALSO produce a minimal smoke-test
  script (e.g. `trading-app/scripts/smoke_market_hours.py`) as a checklist add-on during
  PLAN-SUPPLEMENT, so Step G1/G2 can be Fully-Automated instead of Hybrid — this is a
  recommended infra improvement, not yet a committed checklist item, pending RESEARCH
  confirmation.
- No fixture/mock for Fyers quote responses was found — `get_volatility()`'s D4
  regression check currently relies on live/staged quote comparison (Hybrid), which is
  a known gap for future automated coverage.

---

## Resume and Execution Handoff

1. Selected plan file path: `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-01-asset-abstraction-layer_PLAN_05-07-26.md`
2. Last completed step: PLAN (this file written; umbrella plan written in parallel at
   `process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md`)
3. Validate-contract status: pending — placeholder below, VALIDATE has not run
4. Supporting context files loaded: `process/context/all-context.md`; direct source
   reads of `trading-app/state.py` (lines ~190-260), `trading-app/app.py` (market-hour
   check sites + `daily_hard_exit_scheduler` lines ~1364-1441), `trading-app/engine/
   automation.py` (lines ~696, ~760), `trading-app/engine/ws_feed.py`,
   `trading-app/workers/{market_worker,regime_worker,auto_trader}.py`,
   `trading-app/fetch_lot_sizes.py`, `trading-app/fyers_client.py`
5. Next step for a fresh agent: spawn `vc-research-agent` for Phase 1 Step 1 RESEARCH
   to confirm exact hard-coded-check inventory, test-runner existence, and the 3
   open Blockers above, before PVL/EXECUTE proceed.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
