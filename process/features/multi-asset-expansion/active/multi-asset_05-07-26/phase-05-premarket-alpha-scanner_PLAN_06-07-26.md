---
name: plan:multi-asset-phase-05-premarket-alpha-scanner
description: "Multi-Asset Expansion — Phase 5 (provisional number): Pre-Market AI Alpha Scanner that auto-curates the daily watchlist"
date: 06-07-26
metadata:
  node_type: memory
  type: plan
  feature: multi-asset-expansion
  phase: phase-05
---

# Phase 5 (PROVISIONAL NUMBER) — Pre-Market AI Alpha Scanner

**Program:** multi-asset-expansion
**Umbrella plan:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-05-premarket-alpha-scanner_REPORT_{dd-mm-yy}.md (flat in the program task folder)

---

## SEQUENCING — USER TO CONFIRM

The user tentatively called this capability "phase 3", but the program already has an
established `phase-03-expand-commodities`. Existing phases are NOT being renumbered by this
plan. This capability logically depends on both:

- **Phase 1** — Asset Abstraction Layer (asset-class registry the scanner reads to know which
  segments/instrument universes are active)
- **Phase 3** — Expand Commodities (commodities must be tradeable before the scanner can pick
  commodity candidates)

Because of this dependency, it is numbered **Phase 5** here, provisionally, sequenced after the
existing Phase 4 (Currency). **The user will finalize the real phase number/position this
weekend** — do not treat "Phase 5" as locked. When the user confirms, update:
- this file's filename and frontmatter `phase:` field
- the umbrella plan's `## Phase Ordering` and `## Program Status Table`
- the phase-blast-radius registry (if present) — see Phase Insertion Renumbering protocol in
  `process/development-protocols/vc-system-behavior/` if the final slot requires inserting
  between existing phases rather than appending after Phase 4.

No renumbering has been performed. This plan only reserves the "Phase 5 (provisional)" slot.

---

## Purpose

Add a pre-market AI "Alpha Scanner" agent that runs before 9:00 AM IST every trading day,
screens each active asset segment's tradeable universe (stocks, commodities, and any other
segments enabled via the Phase 1 asset-class registry), scores candidates on technical setup +
AI-ranked quality + news catalysts + liquidity, and auto-populates the top 2 picks per segment
into the user's watchlist ("scripts"). The existing strategy-worker → risk-orchestrator flow then
runs unchanged on those instruments, and the orchestrator picks the trade with the highest
win-rate.

This phase also builds the **win-rate tracking foundation** that the orchestrator's "highest
win%" selection actually needs — today that logic compares zeros, because trade outcomes are
never recorded.

---

## Entry Gate

- Phase 1 (Asset Abstraction Layer) complete — asset-class registry exists and is queryable for
  "which segments are active" and "what is the tradeable instrument universe per segment"
- Phase 3 (Expand Commodities) complete — commodities are tradeable end-to-end (order placement,
  lot sizing, risk management) so the scanner has a real commodity universe to pick from
- Phase 4 (Currency) status noted but NOT a hard blocker for this phase unless the user wants
  currency included in the scanner's active segments at launch
- **RESEARCH ITEM (must be resolved in Step 1 RESEARCH before Step C scoring can include
  stocks):** confirm whether stock-options / stock-equity trading has its own onboarding phase.
  `test_lots_stock.py`, `test_lots_stock2.py`, `test_lots_stock3.py` exist in
  `trading-app/` at repo root, suggesting stock-lot-size logic has been prototyped, but there is
  no `phase-0X-onboard-stocks` sibling to `phase-02-onboard-crude`. RESEARCH must determine:
  (a) is stock trading already end-to-end functional (order placement + lot sizing + risk
  management), or (b) does it need its own onboarding phase before the scanner can safely
  auto-add stock picks. If (b), the scanner's Step D (top-2-per-segment) must exclude the stocks
  segment until that onboarding phase exists — do not block the whole scanner phase on it.

---

## Blast Radius

- `trading-app/workers/premarket_scanner.py` (NEW — the scanner worker/scheduler)
- `trading-app/engine/win_rate_tracker.py` (NEW, or extend `engine/risk_orchestrator.py` /
  `models.py` directly — see Step B) — records closed-trade outcomes and computes rolling
  win-rate per strategy (and optionally per-instrument)
- `trading-app/models.py` — add trade-outcome recording call sites; possibly extend
  `swarm_trade_records` usage; add an `auto_added_by_scanner` marker column or a small
  `scanner_picks` table to distinguish scanner-added symbols from user-added ones
- `trading-app/state.py` — `TradingState` gains a way to distinguish user-added vs
  scanner-added symbols (needed for safe rotation in Step E); reads `get_holiday_reason()`
- `trading-app/app.py` — register the new scheduler task alongside
  `fyers_token_refresh_scheduler` at startup (`asyncio.create_task(...)`); no new HTTP routes
  required unless a "view scanner picks + rationale" endpoint is added for the UI (optional,
  Step F)
- `trading-app/engine/risk_orchestrator.py` — `_get_agent_config` / `flush_signals` consume the
  now-real `win_rate` from `swarm_agent_configs` (already wired to read it — Step B feeds real
  data into the existing read path, does not change `risk_orchestrator.py`'s read logic unless
  per-instrument win-rate is added, which would be an additive column)
- `trading-app/engine/ai_engine.py` — reused read-only (`run_trading_agent` /
  `get_ai_trend`) for candidate ranking; no changes expected unless a new prompt template is
  added for ranking
- `trading-app/workers/news_worker.py` — reused read-only for catalyst signal; no changes
  expected unless a "get today's headlines for symbol X" helper needs to be extracted
- `static/admin.html` or a new UI panel (optional, Step F) — transparency log view of picks +
  rationale (defer to a UI sub-step; not required for the exit gate)

---

## Implementation Checklist

### Step A — Pre-market scheduler + segment/universe config

- [ ] A1. Create `trading-app/workers/premarket_scanner.py` modeled on
  `fyers_token_refresh_scheduler` (`app.py:1033`) and `regime_evaluator`
  (`workers/regime_worker.py:14`): compute `datetime.now(IST)`, target a run window of
  ~08:00–08:45 IST, sleep until target, loop daily. Use the same `IST = pytz.timezone(...)`
  pattern already used in `state.py`/`regime_worker.py`.
- [ ] A2. Before running, call `state.get_holiday_reason()` (see `state.py:199`) — if it returns
  non-`None`, log skip reason and sleep to next day without scanning.
- [ ] A3. Add a segment/universe config source: read the Phase 1 asset-class registry to get the
  list of currently active segments (e.g. `stocks`, `commodities`, optionally `indices`,
  `currency`). Do not hardcode segment list — must reflect Phase 1's registry so a newly
  onboarded asset class (e.g. future Phase 6) is picked up automatically.
- [ ] A4. Define the per-segment liquid candidate universe:
  - stocks: the ~180 NSE F&O liquid stocks list (confirm exact source list during RESEARCH — no
    existing "F&O stock list" constant was found in this codebase scan; likely needs a new static
    list or a Fyers API-backed lookup — flag as RESEARCH item if no authoritative list exists)
  - commodities: MCX symbols already onboarded via Phase 2/3
  - other active segments per registry (optional at launch)
- [ ] A5. Register the new scheduler task in `trading-app/app.py` startup (near
  `asyncio.create_task(fyers_token_refresh_scheduler())`, `app.py:141`):
  `asyncio.create_task(premarket_scanner_loop())`.
- [ ] A6. Add a config flag (e.g. env var or per-user setting) to gate the scanner:
  `ALPHA_SCANNER_MODE` = `off` / `dry_run` / `live` — see Step G for why `dry_run` must be the
  initial default.

### Step B — Win-rate tracking foundation (REQUIRED — orchestrator selection is currently meaningless without this)

- [ ] B1. Confirm the exact point(s) in the codebase where a trade is closed (likely in
  `workers/auto_trader.py` — `execute_auto_trade` / trailing exit logic, or wherever P&L is
  finalized). RESEARCH must locate this exit point precisely before B2.
- [ ] B2. At trade-close time, insert a row into `swarm_trade_records`
  (`models.py` schema at line 239) with `strategy_name`, `symbol`, `entry_time`, `exit_time`,
  `entry_price`, `exit_price`, `pnl`, `vix`, `market_trend` — the columns already exist; only the
  insert call site is missing today.
- [ ] B3. After each insert (or on a rolling schedule, e.g. nightly), recompute `win_rate`,
  `total_trades`, `winning_trades` per `strategy_name` from `swarm_trade_records` and call the
  existing `Database.update_agent_config(...)` (`models.py:703`) to persist it into
  `swarm_agent_configs`. This is the exact write path `risk_orchestrator._get_agent_config`
  (`engine/risk_orchestrator.py:21`) already reads from — no orchestrator code changes needed once
  this write path is real.
- [ ] B4. (Optional, recommended) Add a per-instrument win-rate dimension —
  `(strategy_name, symbol)` pair — either as an additional query against
  `swarm_trade_records` at selection time, or a new lightweight aggregation table, so the
  scanner's own picks can eventually be cross-checked against "has this strategy actually won on
  this symbol before." Not required for the exit gate; document as a natural follow-on if
  deferred.
- [ ] B5. Verify the existing `effective_win_rate` cold-start rule (`risk_orchestrator.py:102`:
  `100.0 if total_trades < 5 else win_rate`) still behaves sanely once real data starts flowing
  in — this is existing logic, confirm no change needed, just note it in the phase report.

### Step C — Candidate scoring pipeline (technical + AI + news + liquidity)

- [ ] C1. Build a technical-feature extractor per candidate: prior-day range, gap-from-close,
  short-term momentum, realized volatility, volume vs average, and pre-market movement if
  available from `fyers_client.py` quotes. Reuse existing quote/caching patterns from
  `market_worker.py` (`USER_CACHES`, `market_data_worker`) rather than adding a second
  quote-polling path.
- [ ] C2. **Mandatory liquidity filter (non-negotiable, must run before any candidate is
  eligible for scoring):** enforce a minimum volume/OI threshold and an acceptable
  bid-ask-spread proxy. A candidate that fails this filter is excluded outright — it cannot be
  promoted even with a high technical/AI score. Document the exact thresholds chosen and cite
  the rationale in the phase report.
- [ ] C3. Call `AIEngine.run_trading_agent(...)` (`engine/ai_engine.py:673`) or
  `get_ai_trend(...)` (`engine/ai_engine.py:558`) with a new ranking-oriented prompt: given N
  liquidity-filtered candidates in a segment plus their technical features, rank by setup
  quality. Reuse the existing multi-provider fallback (`AIProvider` class, `ai_engine.py:33`) —
  do not add a new AI client.
- [ ] C4. Pull same-day/prior-close news catalysts per candidate via
  `workers/news_worker.py` — extract or reuse its fetch logic (news_worker.py is currently a
  background loop; confirm during RESEARCH whether a synchronous "get catalysts for symbol X"
  helper needs to be factored out, or whether the scanner reads the same cache news_worker
  populates).
- [ ] C5. Combine technical + AI ranking + news catalyst signal into one composite score per
  candidate. Weighting scheme must be documented explicitly in the phase report (do not leave
  weights as an unexplained magic formula).

### Step D — Top-2-per-segment selection

- [ ] D1. Within each active segment (post liquidity filter), sort candidates by composite score
  descending and select the top 2.
- [ ] D2. If the stocks segment is excluded per the Entry Gate RESEARCH ITEM (stock onboarding
  incomplete), skip stock selection entirely for this run and log why — do not silently produce
  an empty or partial pick.
- [ ] D3. If fewer than 2 liquidity-eligible candidates exist in a segment on a given day, select
  however many qualify (0, 1, or 2) — never relax the liquidity filter to force exactly 2 picks.

### Step E — Watchlist auto-population + rotation (preserve user symbols + NIFTY)

- [ ] E1. Add a way to tag which symbols in `TradingState.active_symbols` were added by the
  scanner vs added by the user. `state.add_symbol` / `state.remove_symbol` (referenced from
  `app.py:695-763`) currently do not distinguish origin — extend `TradingState` with an
  `auto_added_symbols: set[str]` (or equivalent) alongside `active_symbols`.
- [ ] E2. On each scanner run: remove only the symbols that are in `auto_added_symbols` from
  the PREVIOUS run's picks (rotation) — never remove a symbol that is in `active_symbols` but
  NOT in `auto_added_symbols` (i.e. never remove a user-added symbol).
- [ ] E3. **Hard invariant: `NSE:NIFTY50-INDEX` (the core instrument, default in
  `get_scripts`'s `enabled_symbols` fallback at `app.py:732`) must never be removed by scanner
  rotation, even if it happens to also appear as `auto_added`.** Exclude it from the removal set
  unconditionally.
- [ ] E4. Add the new top-2-per-segment picks via the same mechanism `add_script`
  (`app.py:695`) uses today (`state.add_symbol(symbol)` + the existing symbol-formatting rules),
  and record them in `auto_added_symbols`.
- [ ] E5. Confirm whether a Fyers-side watchlist API call is also needed (separate from the
  app's own `active_symbols` list) — RESEARCH item: check `fyers_client.py` for any watchlist
  endpoints; if none exist, the app's internal `active_symbols` list is the only "watchlist" and
  E1-E4 fully satisfy this step.

### Step F — Transparency logging of picks + rationale

- [ ] F1. For every symbol added (and every symbol removed during rotation), write a structured
  log entry: symbol, segment, composite score, the individual technical/AI/news sub-scores, and
  a one-line human-readable rationale (e.g. "Selected: high gap-up + AI-flagged breakout setup +
  positive earnings catalyst; Excluded: failed liquidity filter (OI below threshold)").
  Reuse `system_logs` table (`models.py:219`) or a new lightweight log file under
  `trading-app/logs/` — RESEARCH/INNOVATE should pick one, don't invent a third logging path.
- [ ] F2. **Compliance constraint (mandatory, verify in every log/UI string written by this
  step):** no log message, UI copy, or rationale text may claim or imply guaranteed profit or
  predicted outcome. Acceptable framing: "flagged as a promising setup based on technical,
  AI-ranked, and news-catalyst signals" — never "will go up" / "guaranteed" / "sure shot".
- [ ] F3. (Optional, not required for exit gate) Surface today's picks + rationale in
  `static/admin.html` or a new small panel so the user can see selections without reading raw
  logs.

### Step G — Paper/dry-run validation (log-only mode before live auto-add)

- [ ] G1. Implement `ALPHA_SCANNER_MODE=dry_run` (default) as the initial operating mode: the
  scanner runs its full pipeline (Steps A-D), writes the transparency log (Step F), but does
  **NOT** call `state.add_symbol` / mutate the watchlist (Step E is skipped entirely in dry-run).
- [ ] G2. Run dry-run for a minimum observation window (recommend: at least 5-10 trading days)
  and have the user review the logged picks + rationale for plausibility before flipping to
  `live` mode.
- [ ] G3. Only after explicit user sign-off does `ALPHA_SCANNER_MODE=live` enable Step E's
  actual watchlist mutation.
- [ ] G4. Document the dry-run→live promotion decision and date in the phase report — this is a
  manual gate, not an automatic timer-based promotion.

---

## Exit Gate

```bash
# Scanner runs and completes before 9 AM IST without error on a simulated/forced trigger
python3 -c "import asyncio; from trading_app.workers.premarket_scanner import run_scanner_once; asyncio.run(run_scanner_once(dry_run=True))"
# Expected: completes without exception; prints/logs top-2-per-segment picks + rationale; does not mutate active_symbols

# Win-rate tracking is real (not all zeros) after at least one closed trade
sqlite3 trading-app/data/trading_app.db "SELECT strategy_name, win_rate, total_trades FROM swarm_agent_configs;"
# Expected: at least one row with total_trades > 0 and a win_rate computed from real swarm_trade_records rows (not a hardcoded 0.0 default with no matching trade history)

sqlite3 trading-app/data/trading_app.db "SELECT COUNT(*) FROM swarm_trade_records;"
# Expected: > 0 after at least one live/paper trade has closed since this phase's Step B lands

# Watchlist rotation preserves user symbols and NIFTY
# (manual/agent-probe check — see Verification Evidence)
```

- All checklist items in Steps A-G checked off (or explicitly documented as deferred with a
  backlog note, per known-gap rules)
- Dry-run mode has been observed for the agreed window and the user has explicitly approved
  promotion to live mode (Step G3) — OR the phase is intentionally left in `dry_run` state at
  handoff with that decision recorded as pending, not silently skipped
- `swarm_trade_records` / `swarm_agent_configs.win_rate` demonstrably reflect real trade outcomes
- NIFTY (`NSE:NIFTY50-INDEX`) is never removed by any rotation cycle (verified via at least one
  agent-probe scenario simulating multiple rotation cycles)
- Compliance constraint (Step F2) verified: no absolute/guaranteed-profit language in any
  scanner-authored log or UI string
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 3 (Expand Commodities) not actually exit-gate-verified yet (commodities not really
  tradeable end-to-end) — the scanner cannot safely pick commodity candidates
- No authoritative F&O liquid-stock universe list exists in the codebase or an accessible Fyers
  API endpoint, and building one is out of scope for this phase (would need its own research
  spike / data source)
- Stock trading found during RESEARCH to be fundamentally non-functional (not just
  "needs polish") — in that case, D2's segment-exclusion is insufficient and stocks-onboarding
  should become its own upstream phase before this one proceeds with stocks in scope
- No reliable pre-market/pre-open quote source available from `fyers_client.py` before market
  open, making the "pre-market" scoring signal impossible to compute meaningfully (would force a
  redesign to score off prior-day data only — document as a scope reduction, not necessarily a
  hard blocker)

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: resolve the stock-options-onboarding open question (Entry
  Gate RESEARCH ITEM), locate the exact trade-close code path for Step B1, confirm/build the
  F&O liquid-stock universe source, confirm news_worker's catalyst-fetch reuse pattern, confirm
  whether a Fyers watchlist API exists separate from `active_symbols`
- [ ] 2. INNOVATE — innovate-agent: decide the logging destination (system_logs table vs new log
  file), decide the win-rate recompute trigger (on-every-close vs nightly batch), decide whether
  per-instrument win-rate (B4) is in scope for this phase or deferred
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: update this phase plan with research/innovate findings
  (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Status / Gate / Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog artifacts / Known gaps / Accepted by)
- [ ] 5. EXECUTE — all checklist items done; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green; follow-up stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

- `trading-app/workers/premarket_scanner.py` (new)
- `trading-app/engine/win_rate_tracker.py` (new, or logic folded into `models.py` /
  `workers/auto_trader.py` — INNOVATE decides exact home)
- `trading-app/models.py`
- `trading-app/state.py`
- `trading-app/app.py`
- `trading-app/engine/risk_orchestrator.py` (read-only consumer, likely unchanged)
- `trading-app/engine/ai_engine.py` (read-only consumer, likely unchanged unless a new prompt
  template constant is added)
- `trading-app/workers/news_worker.py` (read-only consumer or small factored helper)
- `static/admin.html` (optional, Step F3 only)

---

## Public Contracts

- Existing `/api/scripts/add`, `/api/scripts/remove`, `/api/scripts` endpoints and their request/
  response shapes are unchanged — the scanner calls the same internal `state.add_symbol` /
  `state.remove_symbol` functions these routes already use, it does not bypass them with a
  parallel code path
- `NSE:NIFTY50-INDEX` remains in the tradeable/enabled universe unconditionally — no existing
  behavior around the default NIFTY instrument changes
- `swarm_agent_configs` / `swarm_trade_records` schemas are unchanged (columns already exist);
  only new write-path call sites are introduced
- No breaking change to `risk_orchestrator.flush_signals` signature or selection algorithm —
  Step B only makes the data it already reads real

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Scanner dry-run completes pre-9AM without exception, logs top-2-per-segment picks | Hybrid (requires scheduler/time-mocking or a manual `run_scanner_once(dry_run=True)` invocation) | Scanner runs pre-market and produces segment-scoped top-2 picks |
| Liquidity filter rejects a synthetic illiquid candidate even with a high AI/technical score | Fully-Automated (unit test on the scoring/filter function in isolation) | Liquidity filter is non-negotiable |
| `swarm_trade_records` gains a row after a simulated/paper trade close; `swarm_agent_configs.win_rate` recomputes to a non-default value | Hybrid (requires a real or simulated trade-close event) | Win-rate tracking is real and feeds the orchestrator |
| Rotation cycle run twice with a user-added symbol present: user symbol survives, only scanner-tagged symbols rotate | Agent-Probe (multi-step scenario requiring judgment on before/after `active_symbols` + `auto_added_symbols` state) | Never remove user-manually-added watchlist symbols |
| Rotation cycle run with `NSE:NIFTY50-INDEX` present: NIFTY survives every cycle | Agent-Probe | Must not disrupt existing NIFTY trading |
| All scanner-authored log/UI strings scanned for absolute-profit language (grep for banned terms: "guarantee", "sure shot", "will definitely", "100% profit") | Fully-Automated (grep-based check) | No guaranteed-profit claims (compliance constraint) |
| `ALPHA_SCANNER_MODE=dry_run` default confirmed; `state.add_symbol` NOT called during dry-run pipeline execution | Fully-Automated (mock/spy on `add_symbol` during a dry-run pipeline call) | Dry-run validated before live auto-add (Step G) |
| Stock-segment inclusion/exclusion behaves per the RESEARCH ITEM resolution (excluded cleanly if onboarding incomplete, included if functional) | Known-Gap until RESEARCH (Step 1) resolves the open question — tracked, not silently dropped; plan stays CONDITIONAL on this point until resolved | Segment universe correctly reflects Phase 1 registry + stock-onboarding status |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-05-premarket-alpha-scanner_PLAN_06-07-26.md`
- Last completed step: not started
- Validate-contract status: pending
- Supporting context files loaded: `process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md`, `process/context/all-context.md`, `trading-app/app.py`, `trading-app/state.py`, `trading-app/models.py`, `trading-app/engine/risk_orchestrator.py`, `trading-app/engine/ai_engine.py`, `trading-app/workers/regime_worker.py`, `trading-app/workers/market_worker.py`, `trading-app/workers/news_worker.py`
- Next step: Spawn vc-research-agent for RESEARCH (Step 1) — priority: resolve the
  stock-options-onboarding open question and locate the exact trade-close code path for Step B1
  before any scoring/win-rate code is written

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
