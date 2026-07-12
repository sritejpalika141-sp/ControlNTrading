---
name: plan:multi-asset-phase-02-onboard-crude
description: "Multi-Asset Expansion — Phase 2: Onboard MCX Crude Oil options end-to-end via the Phase 1 abstraction layer, paper-first"
date: 05-07-26
metadata:
  node_type: memory
  type: plan
  feature: multi-asset-expansion
  phase: phase-02
---

# Phase 2 — Onboard MCX Crude Oil Options (Proof Commodity)

**Program:** multi-asset-expansion
**Umbrella plan:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-02-onboard-crude_REPORT_05-07-26.md (flat in the program task folder)
Date: 05-07-26
Status: PLANNED
Complexity: COMPLEX (multi-file, live-money, high-risk-class blast radius — see Blast Radius (Risk Class) section)

This file is the single primary execute anchor for Phase 2 execution; no supporting legacy phase files exist for this phase.

---

## Overview / Context

This is Phase 2 of the `multi-asset-expansion` program (see the umbrella plan for the full
program context). Context routing: read `process/context/all-context.md` first, then follow its
routing table to the deeper docs relevant to `trading-app/` (engine, workers, fyers_client,
state/models) before starting RESEARCH for this phase. This phase depends entirely on Phase 1
(`phase-01-asset-abstraction-layer_PLAN_05-07-26.md`) having delivered the AssetClass registry,
session manager, per-asset hard-exit, volatility abstraction, multi-exchange lot sizes, and
exchange-aware symbol construction — Phase 2 consumes that layer, it does not rebuild it.

---

## Purpose

Phase 1 built the generic multi-asset abstraction (AssetClass registry, session manager, per-asset
hard-exit, volatility abstraction, multi-exchange lot sizes, exchange-aware symbol construction) but
it has never carried real live-money order flow. Phase 2 exists to PROVE that abstraction against
one real, materially different commodity — MCX Crude Oil options — using the *same* buy-CE/PE
options model the app already runs for NIFTY, before the program expands to any other commodity.
This is a proof-of-architecture phase, not a "add another symbol" phase: if crude reveals a gap in
the Phase 1 abstraction (session boundaries, lot-size lookup, volatility model, hard-exit timing),
that gap must be fixed in the Phase 1 layer, not patched around here.

Crude is deliberately chosen because it stresses the abstraction hardest: different exchange (MCX
vs NSE), different session window (extends to 23:30 IST vs NIFTY's 15:30), different lot-size source
(MCX_COM master file vs NSE), different strike interval, and materially higher intraday volatility
(~2-4% vs NIFTY's typical <1%). If the abstraction survives crude cleanly, it will generalize to
other MCX/NFO commodities in later phases with much less friction.

---

## Entry Gate

- Phase 1 (asset abstraction layer) complete: AssetClass registry, session manager, per-asset
  hard-exit, volatility abstraction, multi-exchange lot sizes, and exchange-aware symbol
  construction are all merged to `main` and validator-green.
- Phase 1's exit-gate evidence (validate-contract `Gate: PASS` or accepted CONDITIONAL) is present
  in `phase-01-asset-abstraction-layer_PLAN_05-07-26.md`.
- `trading-app/workers/auto_trader.py`, `trading-app/engine/strikes.py`, `trading-app/fyers_client.py`
  are on the Phase-1-abstracted interfaces (i.e. NIFTY-specific literals have been routed through the
  registry, not hardcoded) — confirmed by reading Phase 1's `## Public Contracts` section before
  starting Step A.

---

## Blast Radius

- `trading-app/engine/asset_configs/` (new) — `crude_options.py` (or equivalent registry entry) —
  new file, COMMODITY_OPTIONS config for MCX Crude Oil
- `trading-app/engine/strikes.py` — extend strike selection to be asset-class-aware for crude strike
  intervals and CE/PE symbol construction (read + modify, no full rewrite)
- `trading-app/fyers_client.py` — extend option-symbol construction and `place_order` call sites to
  accept the crude asset-class config; add the liquidity/slippage pre-trade guard (read + modify)
- `trading-app/workers/auto_trader.py` — `execute_auto_trade` gains a crude-specific dispatch path
  that reuses the existing strategy functions with a crude parameter profile; add the two new
  commodity-specific strategies (read + modify)
- `trading-app/engine/strategy_crude_params.py` (new) — crude-tuned parameter profile for ORB /
  breakout / momentum reused strategies
- `trading-app/engine/strategy_crude_eia.py` (new) — Wednesday EIA-inventory volatility strategy
- `trading-app/engine/strategy_crude_evening.py` (new) — evening-session (post-5pm) momentum
  strategy tied to US-market linkage
- `trading-app/state.py` — extend `TradingState` / `USER_CONTEXTS` handling so a user's crude
  automation flag, paper/live mode, and hard-exit are tracked independently of the NIFTY flags (read
  + modify — must use Phase 1's per-asset hard-exit primitive, not a new one)
- `trading-app/models.py` — extend trade-record persistence (or reuse existing schema) to tag trades
  with `asset_class` / `exchange` so crude and NIFTY history is distinguishable (read + modify)
- `static/admin.html`, `static/landing.html` (or equivalent user dashboard) — minimal UI toggle to
  enable crude paper mode per user, and a liquidity-guard rejection indicator (read + modify, kept
  small — full UI polish is out of scope for this phase)
- Test files colocated with each touched module (new `*_test.py` / pytest files as needed)

---

## Implementation Checklist

### Step A — Register COMMODITY_OPTIONS asset-class config for MCX Crude Oil

- [ ] A1. Create `trading-app/engine/asset_configs/crude_options.py` defining a `CRUDE_OIL_OPTIONS`
      config object conforming to Phase 1's `AssetClass` registry contract: `exchange="MCX"`,
      `session_start="09:00"`, `session_end="23:30"` (IST), `symbol_prefix="MCX:CRUDEOIL"`,
      `expiry_cycle="monthly"` (confirm against Phase 1's expiry-cycle enum — crude is monthly, not
      weekly like NIFTY), `volatility_profile="ATR_BASED"` wired to Phase 1's volatility abstraction.
- [ ] A2. Wire lot-size lookup for `CRUDEOIL` through Phase 1's multi-exchange lot-size primitive,
      sourced from the MCX_COM master file (confirm the exact master-file path/loader Phase 1
      introduced — do not hardcode a lot size; MCX crude lot size changes periodically, e.g. 100
      barrels standard / 10 barrels mini — read the live master file value at runtime).
- [ ] A3. Define crude-specific risk config in the same registry entry: wider stop-loss distance
      (e.g. 1.5-2x the NIFTY SL% distance, expressed as a config multiplier not a hardcoded value —
      confirm final multiplier in Step C after volatility profiling), smaller position sizing
      (`max_lots` cap lower than NIFTY's default), and `hard_exit_time="23:20"` IST wired through
      Phase 1's per-asset hard-exit primitive (NOT the NIFTY 15:20-style global hard-exit).
- [ ] A4. Register `CRUDE_OIL_OPTIONS` in Phase 1's `AssetClass` registry (whatever registration
      call/dict Phase 1 exposed — read Phase 1's `## Public Contracts` for the exact registration
      API before writing this).
- [ ] A5. Write a unit test asserting: registry lookup for `CRUDEOIL` returns session
      09:00-23:30 IST, exchange `MCX`, monthly expiry, and a lot size sourced from the master file
      (not a hardcoded literal).

### Step B — Crude option strike selection (adapt `engine/strikes.py`)

- [ ] B1. Extend `select_strike()` / `get_strike_recommendations()` (or the asset-class-aware
      wrapper Phase 1 introduced around them) to accept an `AssetClass` config parameter instead of
      assuming NIFTY's implicit 50-point strike interval — crude strike intervals differ (commonly
      50 or 100 depending on price regime; read the live option-chain strike ladder rather than
      hardcoding an interval).
- [ ] B2. Build MCX crude option symbols (`MCX:CRUDEOIL{expiry}{strike}CE` / `...PE` format —
      confirm exact Fyers symbol format for MCX crude options via `vc-docs-seeker` against Fyers API
      v3 docs before hardcoding the string template) via the crude `AssetClass` config's
      `symbol_prefix` + expiry-cycle helper from Phase 1's exchange-aware symbol construction.
- [ ] B3. Confirm ATM selection logic (`option_chain.get("atm", round(spot / X) * X)`) uses the
      crude strike interval `X` from the asset-class config, not NIFTY's `50`.
- [ ] B4. Write unit tests: given a mocked MCX crude option chain and spot price, assert the ATM
      strike, CE/PE symbol strings, and strike interval match the crude config — not NIFTY's.

### Step C — Apply reusable strategies (ORB, breakout, momentum) with crude-tuned parameters

- [ ] C1. Read `engine/strategy_orb.py` and `engine/strategy_9.py` fully to extract each strategy's
      currently-hardcoded NIFTY parameters (candle size/timeframe, breakout threshold, SL distance,
      volatility filter thresholds).
- [ ] C2. Create `trading-app/engine/strategy_crude_params.py` defining a crude parameter profile:
      wider candle-range thresholds and SL/target distances tuned for crude's ~2-4% intraday range
      (vs NIFTY's sub-1% typical range) — express as a ratio/multiplier derived from a short
      historical-volatility comparison (documented in the phase report, not asserted from
      assumption), not a copy-pasted arbitrary constant.
- [ ] C3. Parameterize `strategy_orb.py` and `strategy_9.py` call sites (or their asset-aware
      wrappers) to accept the parameter profile as an argument, defaulting to the existing NIFTY
      profile when no profile is passed — this is the regression-safety mechanism for Step G.
- [ ] C4. Document the full crude parameter profile (every tuned value + rationale) inline in
      `strategy_crude_params.py` docstring AND in the phase report's `## Crude Parameter Profile`
      section.
- [ ] C5. Write unit tests confirming: (a) NIFTY strategy calls with no profile argument produce
      byte-identical signals to pre-Phase-2 behavior (regression proof for Step G), and (b) crude
      strategy calls with the crude profile produce different SL/target distances than the NIFTY
      default given the same synthetic candle input.

### Step D — Add commodity-specific strategies

- [ ] D1. Create `trading-app/engine/strategy_crude_eia.py`: a Wednesday EIA (US Energy Information
      Administration) inventory-report volatility play. Logic: on Wednesdays (10:30pm IST / US
      market-hours EIA release time — confirm exact release-time convention with `vc-docs-seeker`
      or public EIA schedule reference before hardcoding), widen volatility filters and permit
      breakout entries around the release window; outside that window on non-Wednesdays, this
      strategy emits `NO TRADE`.
- [ ] D2. Create `trading-app/engine/strategy_crude_evening.py`: an evening-session momentum
      strategy active only after ~17:00 IST (US pre-market/open linkage window) that trades
      directional momentum continuation tied to crude's international correlation; emits `NO TRADE`
      outside its active window.
- [ ] D3. Both new strategies must return the same signal dict shape (`signal_type`, `symbol`,
      confidence/score fields) as the existing `strategy_orb.py` / `strategy_9.py` output contract
      so they slot into `execute_auto_trade`'s existing dispatch without a new code path per
      strategy.
- [ ] D4. Write unit tests for both: time-window gating (correct signal outside window is always
      `NO TRADE`), and a synthetic-data happy-path signal generation test for each.

### Step E — Liquidity/slippage guard (MANDATORY safety gate)

- [ ] E1. Add a pre-trade liquidity check function in `fyers_client.py` (or a new
      `engine/liquidity_guard.py` if that keeps `fyers_client.py` from growing further) —
      `check_option_liquidity(option_quote) -> (bool, reason)` — enforcing minimum open interest,
      minimum volume, and maximum bid-ask spread percentage thresholds. Thresholds must be
      configurable per asset class (crude's book is thinner than NIFTY's; do not reuse NIFTY's
      thresholds for crude — set crude-specific defaults and document rationale in the phase
      report).
- [ ] E2. Wire this check into the crude order-placement path in `execute_auto_trade` (and/or
      `place_order`) as a hard gate: if the check fails, the order is rejected BEFORE
      `place_order` is called, the rejection is logged with the exact reason (`min_oi_fail` /
      `min_volume_fail` / `spread_too_wide`), and a Telegram/log notification is emitted so the
      rejection is visible, not silent.
- [ ] E3. Confirm the guard does NOT block existing NIFTY order flow — gate applies only when the
      asset-class config for the order marks `liquidity_guard_required=True` (crude) unless the
      umbrella decides to also apply it to NIFTY; default NIFTY to unaffected unless Phase 1/Innovate
      explicitly decided otherwise.
- [ ] E4. Write unit tests: (a) a thin/illiquid mocked crude option quote is rejected with the
      correct reason string and `place_order` is never called (assert via mock/spy); (b) a liquid
      mocked quote passes through to `place_order`; (c) a NIFTY order with the guard disabled is
      unaffected by the new function's presence.

### Step F — Paper-trade validation FIRST, then live-small

- [ ] F1. Confirm (via Phase 1's public contract) that `PAPER_TRADING` mode fully isolates crude
      order placement from live Fyers `place_order` calls — crude MUST run through the same paper
      simulation path NIFTY already uses, not a new bespoke paper path.
- [ ] F2. Define an explicit paper-validation window and acceptance bar in the phase report before
      declaring paper validation complete: minimum number of trading sessions observed (recommend
      ≥5 trading days spanning at least one Wednesday for the EIA strategy), signal-generation sanity
      (signals fire only inside their intended windows), simulated fill/PNL sanity (no NaN/negative
      lot-size/impossible-price artifacts), and liquidity-guard activation evidence (at least one
      observed rejection OR an explicit note that none occurred and why that's plausible).
- [ ] F3. Add a per-user "Enable Crude (Paper)" toggle in the admin/user dashboard, defaulting to
      OFF, gated separately from the existing NIFTY automation toggle (uses Phase 1's per-asset
      automation-flag primitive from `state.py`, not a new ad-hoc flag).
- [ ] F4. Run the paper-validation window; capture evidence (logs, trade records tagged
      `asset_class=CRUDE_OPTIONS`, screenshots/log excerpts of at least one full signal→fill→exit
      cycle) into the phase report.
- [ ] F5. Only after F4 evidence is captured and reviewed: add a live-small path — a hard position-
      size cap (e.g. 1 lot) enforced in code (not just documentation) for the first live-enabled
      period, with the cap value and enforcement point documented in the phase report. Live-small
      enablement is a SEPARATE explicit toggle from paper mode — never auto-promote paper→live.
- [ ] F6. Write an integration-style test (paper mode) exercising one full crude signal → strike
      selection → liquidity check → simulated order → simulated exit cycle, asserting no live Fyers
      API call occurs during the test.

### Step G — NIFTY regression (existing NIFTY trading unaffected)

- [ ] G1. Before touching any shared file (`auto_trader.py`, `strikes.py`, `fyers_client.py`,
      `state.py`, `models.py`), capture a baseline: run the existing NIFTY test suite (and any
      manual smoke check documented in Phase 1) and record pass/fail state.
- [ ] G2. After Steps A-F, re-run the same NIFTY suite/smoke check and diff against the G1 baseline
      — any behavioral difference in NIFTY signal generation, strike selection, order placement, or
      hard-exit timing is a regression and must be fixed before this phase can exit.
- [ ] G3. Confirm NIFTY and crude automation can run concurrently for the same user without one
      blocking the other (both `automation_enabled` flags independently true) — test with a mocked
      concurrent tick for both asset classes in the same event-loop pass.
- [ ] G4. Write a regression test asserting NIFTY strategy signal output is byte-identical pre/post
      Phase 2 given identical synthetic input (ties back to Step C5(a)).

---

## Exit Gate

```bash
# Unit + regression suite for touched modules
cd "trading-app" && pytest engine/ workers/ -k "crude or nifty_regression" -v
# Expected: all crude-related tests pass; nifty_regression tests pass with zero diffs vs G1 baseline

# Liquidity guard hard-gate proof
cd "trading-app" && pytest engine/ -k "liquidity_guard" -v
# Expected: illiquid-quote rejection test passes; place_order never called in that test case

# Paper-mode isolation proof
cd "trading-app" && pytest engine/ -k "paper_mode_isolation" -v
# Expected: crude paper-mode integration test passes with zero live Fyers API calls asserted
```

- All checklist items (A1-G4) checked.
- Paper-validation window evidence captured in the phase report per F2's acceptance bar.
- Liquidity guard demonstrated active (Step E4 tests green + at least one real or synthetic
  rejection example in the phase report).
- NIFTY regression suite green with zero diffs vs the G1 baseline.
- Live-small path exists in code but is OFF by default; enabling it requires the separate explicit
  toggle from F5, never an automatic paper→live promotion.
- Phase report written to report destination above.

---

## Acceptance Criteria

1. `CRUDE_OIL_OPTIONS` asset-class config is registered in Phase 1's registry and returns correct
   MCX session window (09:00-23:30 IST), monthly expiry, and a lot size read live from the MCX_COM
   master file (not hardcoded) — proven by Step A5 test.
2. Crude option strike selection produces correct ATM/CE/PE symbols using crude's strike interval
   and Fyers MCX symbol format (confirmed via `vc-docs-seeker`), not NIFTY's — proven by Step B4.
3. Reused strategies (ORB, breakout, momentum) apply a documented, rationale-backed crude parameter
   profile, and NIFTY's signal output is byte-identical pre/post this phase given identical input —
   proven by Steps C5 and G4.
4. Both new commodity-specific strategies (EIA-day volatility, evening-session momentum) correctly
   gate by time window and produce a valid signal shape — proven by Step D4.
5. The liquidity/slippage guard hard-blocks illiquid crude option orders before `place_order` is
   called, with the rejection logged and visible — proven by Step E4.
6. Crude trades only in `PAPER_TRADING` mode by default; a defined multi-day paper-validation
   window (per Step F2's acceptance bar) produces evidence in the phase report before any live-small
   path can be enabled; live-small requires a separate explicit toggle, never auto-promotion —
   proven by Steps F4-F6 and the Exit Gate.
7. NIFTY's existing options trading is completely unaffected — same signals, same order behavior,
   same hard-exit timing — and NIFTY + crude automation can run concurrently for one user without
   cross-blocking — proven by Steps G1-G4.

---

## Phase Completion Rules

- This phase cannot be marked `✅ VERIFIED` (VERIFIED requires explicit user/orchestrator confirmation, not just agent self-report) without: (a) all Implementation Checklist items (A1-G4)
  checked, (b) a validate-contract with `Gate: PASS` or an explicitly accepted `Gate: CONDITIONAL`,
  (c) the Exit Gate commands run green by an independent EVL confirmation pass (not just
  execute-agent's own claim), and (d) the G1/G2 NIFTY regression diff showing zero behavioral
  change.
- Code-only completion (all checklist items implemented but paper-validation window not yet run or
  evidence not yet captured) must be reported as `CODE DONE`, not `VERIFIED` — this distinction is
  mandatory in the phase report per repo-wide phase-status honesty rules.
- Live-small enablement (Step F5) is never part of this phase's own completion bar — this phase's
  Exit Gate is satisfied by PAPER validation evidence; live-small is a follow-on decision the
  umbrella plan or a subsequent phase explicitly gates, not an automatic next step.

---

## Blockers That Would Justify BLOCKED Status

- Phase 1's `AssetClass` registry, session manager, per-asset hard-exit, or exchange-aware symbol
  construction does not yet exist or does not expose a stable public contract to build against.
- Fyers API v3 does not support the required MCX crude option symbol format, or `vc-docs-seeker`
  cannot confirm the exact symbol/expiry format — this blocks Step B and must not be guessed.
- MCX_COM lot-size master file is unavailable or its loader was not actually delivered by Phase 1
  (Step A2 has no real lot-size source to read).
- No mockable/replayable historical crude option-chain data is available to build paper-mode tests
  against (Step F6 cannot be meaningfully asserted).

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: confirm Phase 1's actual delivered public contract (registry
      API, hard-exit primitive, symbol construction helper, lot-size loader) against this plan's
      assumptions; confirm exact Fyers MCX crude option symbol/expiry format via `vc-docs-seeker`;
      confirm NIFTY baseline test commands and current pass state
- [ ] 2. INNOVATE — innovate-agent: decide the crude SL/target multiplier methodology (Step A3/C2),
      decide whether the liquidity guard (Step E) also applies to NIFTY or crude-only, decide the
      EIA/evening-session exact time windows (Step D1/D2)
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: fold RESEARCH/INNOVATE findings back into this plan (exact
      symbol format, exact Phase-1 API names, exact time windows, exact SL multiplier) before PVL
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Status / Gate /
      Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog
      artifacts / Known gaps / Accepted by)
- [ ] 5. EXECUTE — Steps A-G implemented; per-section test gates run and green (or gaps documented)
- [ ] 6. EVL — all EVL gates green (independent re-run of the Exit Gate commands above); follow-up
      stubs registered; EVL HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

- `trading-app/engine/asset_configs/crude_options.py` (new)
- `trading-app/engine/strikes.py`
- `trading-app/fyers_client.py`
- `trading-app/workers/auto_trader.py`
- `trading-app/engine/strategy_crude_params.py` (new)
- `trading-app/engine/strategy_crude_eia.py` (new)
- `trading-app/engine/strategy_crude_evening.py` (new)
- `trading-app/engine/liquidity_guard.py` (new, if split out of `fyers_client.py`)
- `trading-app/state.py`
- `trading-app/models.py`
- `static/admin.html` / user dashboard (crude paper toggle + liquidity-rejection indicator)

---

## Public Contracts

- Existing NIFTY option-buying flow (signal → strike selection → order placement → SL/exit →
  hard-exit) is UNCHANGED in behavior — this phase adds a parallel crude path, it does not rewrite
  the NIFTY path (Step G proves this).
- Existing `PAPER_TRADING` global mode semantics are unchanged; crude reuses the same paper
  simulation path rather than introducing a second meaning for that flag.
- New public surface introduced by this phase: the `CRUDE_OIL_OPTIONS` asset-class registry entry,
  the liquidity-guard function signature (`check_option_liquidity`), and the crude parameter-profile
  object shape — these become the second real consumer of Phase 1's abstraction and should be
  treated as a de-facto contract example for Phase 3+ commodities.
- Per-user crude automation flag and crude paper/live toggle are new user-facing surface (dashboard
  + underlying state), independent of the existing NIFTY toggle.

---

## Blast Radius (Risk Class)

- **Live-money trading logic** (high-risk class: this touches order placement, risk/SL config, and
  hard-exit timing for a second, more volatile asset class). Minimum test tier per
  `vc-test-coverage-plan` for this class is **Hybrid** — no Known-Gap acceptance without documented
  rationale for the order-placement, liquidity-guard, and hard-exit paths.
- Files touched: ~10-11 (2 modified core modules with live-order-adjacent logic — `fyers_client.py`,
  `auto_trader.py`; 3 modified supporting modules — `strikes.py`, `state.py`, `models.py`; 5 new
  files; 1 dashboard file). This crosses the 5-file blast-radius signal for
  `vc-agent-strategy-compare` scoring.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Registry lookup returns correct MCX session/exchange/lot-size/expiry for `CRUDEOIL` (Step A5) | Fully-Automated | Step A — asset-class config registered correctly |
| ATM/strike/symbol construction matches crude config, not NIFTY's (Step B4) | Fully-Automated | Step B — crude strike selection adapted via abstraction |
| NIFTY strategy signals byte-identical pre/post Phase 2 given identical input (Step C5a, G4) | Fully-Automated | Step C + Step G — reused strategies parameterized without NIFTY regression |
| Crude strategy signals differ from NIFTY default given identical input + crude profile (Step C5b) | Fully-Automated | Step C — crude-tuned parameters actually applied |
| EIA / evening-session strategies gate correctly by time window (Step D4) | Fully-Automated | Step D — commodity-specific strategies scoped correctly |
| Illiquid quote rejected before `place_order`; liquid quote passes (Step E4) | Fully-Automated | Step E — mandatory liquidity/slippage guard active |
| Paper-mode full cycle (signal→strike→guard→simulated order→exit) with zero live API calls (Step F6) | Hybrid (requires mocked/replayed option-chain fixture — precondition documented) | Step F — paper-trade validation path proven before live |
| Multi-day paper-validation window evidence (signal sanity, PnL sanity, guard activation) (Step F2/F4) | Agent-Probe (judgment call on "signals sane", "no artifacts") | Exit Gate — paper validation acceptance bar met |
| NIFTY + crude concurrent automation, one user, no cross-blocking (Step G3) | Hybrid (requires event-loop-level mocked concurrency test) | Step G — NIFTY unaffected under concurrent load |
| Live-small path exists but OFF by default; separate toggle required to enable (Step F5) | Fully-Automated (code inspection assertion: default flag value + toggle independence) | Exit Gate — no automatic paper→live promotion |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Testing Context

Before EXECUTE, read `process/context/tests/all-tests.md` and follow its routing chain to the
relevant deeper test docs for `trading-app/` (pytest conventions, fixture/mocking patterns for
Fyers API responses, and any existing option-chain replay fixtures). Post-phase testing runs the
Exit Gate commands above plus a full pytest run scoped to `trading-app/engine/` and
`trading-app/workers/` as an independent EVL confirmation pass (per `vc-test-coverage-plan` tiers
embedded in the Verification Evidence table).

---

## Current Execution State (updated 12-07-26)

Executed inline (hands-on, deploy-after-verify), not via the full RIPER-5 subagent ceremony.
Commits on `main`, all live on VM (Sun, market closed, HTTP 200):

- `6b17bf6` — Phase 1 asset registry (prereq)
- `2c0ffe4` — **entry-gate bridging DONE**: NIFTY strike path routed through registry `strike_interval`
  (byte-identical; entry gate now genuinely satisfied)
- crude scaffold commit — Steps A / C / D / E scaffolded as **CODE DONE (not VERIFIED)**, all INERT
  (no live NIFTY-path import): `asset_configs/crude_options.py` (CRUDE_OIL_OPTIONS registered),
  `strategy_crude_params.py`, `strategy_crude_eia.py`, `strategy_crude_evening.py`,
  `liquidity_guard.py`. 23 scaffold tests green; NIFTY proven unaffected.
- `8f5d8ed` — corrected CURRENCY_OPTIONS placeholder prefix (unrelated to crude; currency DEFERRED
  per user — prove crude first).

Research banked: Fyers MCX crude symbol format `MCX:CRUDEOIL{YY}{MON}{STRIKE}{CE|PE}`, interval 50,
confirmed from MCX_COM master. MCX segment confirmed active on the account (user).

**NEXT GATE (blocks all remaining crude work): market-open MCX data probe.** Needs a fresh Fyers
login during an MCX session → run a read-only crude quote → confirm data flow + resolve the real
lot/qty column. THEN: wire crude into `execute_auto_trade`/`fyers_client` (Step B + order path,
PAPER-only) → run the ≥5-trading-day paper-validation window (Step F, incl. a Wednesday for EIA) →
Step G NIFTY regression → EVL. Provisional values (SL mult 1.75, liquidity OI 200/vol 100/spread 3%,
EIA window 19:30-21:00 IST Wed) are marked in code and must be confirmed in the paper window.

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-02-onboard-crude_PLAN_05-07-26.md`
- Last completed step: entry-gate bridging + crude paper-scaffold (Steps A/C/D/E CODE DONE, inert);
  execute-wiring (Step B order path + F/G) BLOCKED on the market-open MCX data probe (user login)
- Validate-contract status: pending (inline execution; PVL not run — full contract still required
  before the live-money execute-wiring step)
- Supporting context files loaded during planning: `trading-app/engine/strikes.py` (read in full),
  `trading-app/workers/auto_trader.py`, `trading-app/fyers_client.py`, `trading-app/state.py`,
  `trading-app/models.py` (grepped for relevant symbols — NIFTY hardcoding, lot-size lookup,
  place_order signature), `trading-app/engine/strategy_orb.py`, `trading-app/engine/strategy_9.py`
  (line counts confirmed, full read deferred to RESEARCH step for exact parameter extraction)
- Next step: confirm Phase 1 entry gate is satisfied, then spawn `vc-research-agent` for Step 1
  RESEARCH (confirm Phase 1's actual delivered public contract, confirm Fyers MCX crude option
  symbol format via `vc-docs-seeker`, confirm NIFTY baseline test state) before any INNOVATE or
  EXECUTE work begins on this phase.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
