---
name: plan:multi-asset-phase-04-currency
description: "Multi-Asset Expansion — Phase 4: NSE Currency Derivatives (CDS) options — proof of abstraction"
date: 05-07-26
metadata:
  node_type: memory
  type: plan
  feature: multi-asset-expansion
  phase: phase-04
---

# Phase 4 — NSE Currency Derivatives (Currency Options)

**Program:** multi-asset-expansion
**Umbrella plan:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md
**Phase status:** ⏳ PLANNED (FUTURE / lower priority — may be deferred; plan is execution-ready regardless)
**Report destination:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-04-currency_REPORT_{dd-mm-yy}.md (flat in the program task folder)
Date: 05-07-26
Status: PLANNED — FUTURE phase, deferrable; execution-ready
Complexity: COMPLEX (phase-program phase — config-only blast radius expected, live-money surface)

---

## Overview

This is Phase 4 (final planned phase) of the multi-asset-expansion program. See Purpose below for
the full context and goal statement.

## Purpose

Add NSE Currency Derivatives (CDS segment) options on USDINR, EURINR, GBPINR, and JPYINR as a new
`AssetClass`, using the abstraction built in Phase 1 and already proven twice over by Phases 2-3
(commodities). This phase is deliberately treated as the **capstone proof of the abstraction**: if
Phase 1 was designed correctly, onboarding currency should be a config exercise — new
`AssetClassConfig` entries, a strike-selection adapter for 0.25-paise intervals, and
currency-tuned strategy parameters — with **no new execution engine, no new session-manager
architecture, and no new risk-engine plumbing**. The size of the diff this phase actually requires
is itself a data point on Phase 1's abstraction quality (see Step G / Abstraction-Completeness
Assessment).

Currency also stresses a dimension the program hasn't tested yet: **overlapping trading sessions**.
Currency's 09:00–17:00 IST window overlaps almost entirely with equity's session, unlike
commodity's evening-heavy MCX session. This phase is the first real test of concurrent multi-asset
session handling within the same clock window.

---

## Entry Gate

- Phase 1 (abstraction layer: `AssetClass` registry, `AssetClassConfig` schema, generic
  session/strategy/risk plumbing) complete and VERIFIED.
- Phase 2 (commodities MCX) complete and VERIFIED — proves the abstraction survives a second asset
  class with a different exchange, session, and lot-size regime.
- Phase 3 (commodities strategy tuning / additional commodity symbols, per umbrella sequencing)
  complete and VERIFIED.
- NSE_CD (currency derivatives) instrument/lot-size master feed is reachable via the existing
  Phase-1 instrument-master fetch pipeline (same pipeline used for NSE_FO and MCX_FO — no new
  fetcher class expected).
- Umbrella plan's Program Goal Charter and hard safety constraints reviewed before any live-money
  step in this phase.

---

## Blast Radius

Expected — CONFIG-ONLY (per Purpose, the point of this phase is that this list stays short):

- `trading-app/config/asset_classes/currency_options.py` (or equivalent config module per Phase 1's
  config-file convention) — new `AssetClassConfig` entry for `CURRENCY_OPTIONS`
- `trading-app/engine/strike_selection.py` (or the Phase-1 strike-selection module) — new strike-step
  adapter for 0.25-paise currency intervals, registered via config, not a new class hierarchy
- `trading-app/engine/risk_config.py` (or equivalent) — currency-tuned risk parameters (SL/target
  distance, position sizing) referenced by the new AssetClassConfig
- `trading-app/config/strategy_params/currency.py` (or equivalent) — currency-tuned parameter sets
  for the subset of the 9 reusable strategies selected in Step C
- `trading-app/engine/liquidity_guard.py` (existing, Phase 1/2) — config-driven liquidity threshold
  entries for USDINR vs cross-pairs, no code change expected
- `trading-app/engine/session_manager.py` (existing, Phase 1) — **read-only verification only**
  unless Step G's concurrent-session check finds a real gap; if code change is required here, that
  is itself a Phase-1-abstraction-incompleteness finding (see Step G)

**If actual code touches expand beyond config/session-manager/liquidity threshold entries into new
classes, new engine methods, or new session-manager logic, that expansion must be explicitly
justified in the phase report as a Phase-1 gap — not silently absorbed as "normal Phase 4 work."**

---

## Implementation Checklist

### Step A — Register CURRENCY_OPTIONS asset class config

- [ ] A1. Confirm NSE_CD instrument/lot-size master is fetched by the existing Phase-1 instrument
      master pipeline (same mechanism as NSE_FO/MCX_FO); if a new fetch path is needed, document why
      (this is a config-only phase — a new fetcher would be a gap finding).
- [ ] A2. Add `AssetClassConfig` entry for `CURRENCY_OPTIONS`:
      - `exchange`: `NSE` (CDS segment / `NSE_CD` symbol namespace)
      - `session`: `09:00–17:00 IST` (distinct from equity `09:15–15:30` and commodity's
        evening-heavy MCX window — shortest session-length delta of any asset class added so far
        relative to equity, and the FIRST asset class whose session window mostly overlaps equity's)
      - `symbol_format`: `NSE:USDINR{expiry}{strike}{CE/PE}` pattern (confirm exact format against
        the fetched NSE_CD instrument master — do not hardcode from assumption)
      - `lot_size`: sourced from NSE_CD master (per-pair; USDINR/EURINR/GBPINR/JPYINR each have
        their own lot size — do not assume a single shared lot size across pairs)
      - `expiry_cycle`: weekly + monthly (confirm which pairs get weekly vs monthly-only expiries
        from the instrument master — USDINR typically has weekly, cross-pairs may be monthly-only)
      - `volatility_measure`: ATR-based, tuned tighter than commodities (currency's daily range is
        materially smaller — see Step C for the numeric basis)
      - `risk_config_ref`: pointer to the new currency-tuned risk config from Step A3
      - `hard_exit_time`: `16:50 IST` (10 minutes before session close, consistent with the
        program's existing hard-exit-before-close pattern from Phases 2-3)
- [ ] A3. Add currency-tuned risk config (SL distance, target distance, position sizing) as a new
      config entry referenced by `risk_config_ref` above — do NOT reuse NIFTY or commodity risk
      config defaults; USDINR's ~0.3-0.8% daily move requires SL/target distances roughly an order
      of magnitude tighter than commodity ATR-based defaults. Document the derivation (e.g. from
      historical USDINR ATR) in the config comments or an inline reference note.
- [ ] A4. Confirm the AssetClass registry (Phase 1) accepts the new config with no registry-code
      change — register `CURRENCY_OPTIONS` purely via config entry + registry lookup, per the
      abstraction contract. If the registry requires a code change to accept a 4th asset class,
      that is a Phase-1 gap finding (see Step G).

### Step B — Currency option strike selection (0.25-paise intervals)

- [ ] B1. Confirm actual strike interval for each currency pair from the NSE_CD instrument master
      (USDINR is commonly quoted in 0.25-paise/0.0025 strike steps; verify per-pair — cross-pairs
      may differ) — do not hardcode 0.25 paise without confirming against the live master.
- [ ] B2. Extend the Phase-1 strike-selection module with a currency strike-step adapter, registered
      via the `AssetClassConfig` (e.g. a `strike_step` field or `strike_step_fn` reference) — the
      adapter itself should be a small, generic "step + round to nearest step" function, reusable
      for any future asset class with a fixed strike interval, not currency-specific logic hardcoded
      into the selection engine.
- [ ] B3. Verify ATM/ITM/OTM strike selection produces sane strikes for at least USDINR and one
      cross-pair (e.g. EURINR) using a paper/dry-run instrument snapshot — confirm no off-by-one or
      rounding errors from the interval adapter before wiring into live strategy logic.

### Step C — Apply reusable strategies with currency-tuned parameters

- [ ] C1. Review all 9 reusable strategies from the program's strategy library against currency's
      volatility profile (USDINR ~0.3-0.8% daily range, materially calmer than NIFTY and commodities).
      Classify each strategy as:
      - **Suited** (range/mean-reversion strategies — low-volatility regimes reward fading extremes
        rather than chasing breakouts)
      - **Marginal** (works with heavy parameter retuning — e.g. momentum strategies with much
        tighter breakout thresholds)
      - **Unsuited** (breakout/high-volatility-expansion strategies that need a bigger move than
        currency typically produces to clear cost + slippage)
      Document the classification with one-line rationale per strategy in the phase report — this
      classification IS a required deliverable of this phase, not an implementation detail to skip.
- [ ] C2. For each Suited/Marginal strategy, create a currency-tuned parameter set: candle
      interpretation thresholds, SL/target distances, and any volatility-regime filters, scaled to
      currency's smaller absolute moves — do not reuse NIFTY or commodity parameter sets unscaled.
- [ ] C3. Explicitly exclude Unsuited strategies from the `CURRENCY_OPTIONS` asset class's active
      strategy set in config (do not silently leave them wired in "just in case" — an unsuited
      breakout strategy running against currency's low-vol regime is a live-money risk, not a
      harmless no-op).

### Step D — Currency-specific considerations (risk/reward profile)

- [ ] D1. Document RBI-intervention risk explicitly in the phase report and in a config-level
      comment/note: RBI can intervene in USDINR to defend a band, causing sudden low-volatility →
      sharp-move regime shifts that do not resemble either NIFTY gap risk or commodity
      supply-shock risk. Note whether any Phase-1/2/3 risk-engine hook (e.g. a "regime shift"
      circuit-breaker) already covers this, or whether it is an accepted known-gap for this phase.
- [ ] D2. Document the fundamentally different risk/reward shape versus NIFTY and commodities:
      tighter spreads, smaller absolute moves, meaning theta decay and cost-of-carry matter
      proportionally more for currency options than for the wider-ranging asset classes already
      onboarded. Note the implication for position sizing (Step A3) and strategy selection (Step C1).
- [ ] D3. Confirm the hard-exit and stop-loss logic (existing, Phase 1) behaves correctly given
      currency's tighter SL distances — verify no minimum-tick or minimum-SL-distance assumption
      baked into the shared risk engine silently floors currency SLs to a NIFTY/commodity-scale
      value (this would be a Phase-1 gap, not a currency-specific bug).

### Step E — Liquidity guard tuning

- [ ] E1. Reuse the existing Phase-1/2 liquidity guard (bid-ask spread / OI / volume thresholds) —
      no new liquidity-checking code expected.
- [ ] E2. Set liquidity thresholds via config per pair: USDINR — live-viable threshold (USDINR
      options are liquid); EURINR/GBPINR/JPYINR — paper-only threshold initially (cross-pairs are
      materially less liquid on NSE CDS) . Confirm current live OI/volume figures for cross-pairs
      via the instrument master or a live quote snapshot before setting the paper-only gate, rather
      than assuming from general knowledge.
- [ ] E3. Confirm the liquidity guard's existing paper-only override mechanism (used in Phases 2-3
      for less-liquid commodity contracts) applies cleanly to currency cross-pairs with no code
      change — config-only gating, per the Purpose section's thesis.

### Step F — Paper → validate → live-small (per-pair rollout discipline)

- [ ] F1. USDINR: run in paper mode across at least one full session covering both a quiet session
      and a session with an RBI-relevant macro print (e.g. a scheduled RBI policy date or major
      US/India macro release), to exercise the Step D1 regime-shift consideration under paper
      conditions before any live exposure.
- [ ] F2. USDINR: after paper validation, promote to live-small (minimum lot size, single pair)
      per the umbrella plan's live-money discipline (see Program Goal Charter hard safety
      constraints in the umbrella plan).
- [ ] F3. EURINR/GBPINR/JPYINR: remain paper-only for this phase given Step E2's liquidity
      classification — do NOT promote cross-pairs to live in this phase unless Step E2's live
      quote snapshot shows liquidity materially better than assumed (if so, document the finding
      and treat live promotion for that pair as a phase report follow-up, not an in-scope live
      change without a fresh validate-contract sign-off).
- [ ] F4. Confirm the automation_loop / trailing_monitor / token-refresh background loops (existing,
      shared across asset classes per `process/context/all-context.md`'s Security Remediation Phase
      2 notes on `purge_user_runtime()` and per-user scoping) correctly include/exclude currency
      positions using the same `USER_CONTEXTS`/`USER_STATES` mechanism already proven for equity and
      commodity — no currency-specific background-loop branch expected.

### Step G — Final program regression + abstraction-completeness assessment (capstone)

- [ ] G1. Run all four asset classes (NIFTY equity, and whichever commodity pairs are live from
      Phases 2-3, plus USDINR from this phase) concurrently in a paper/staging session that spans
      the overlapping 09:00–17:00 IST window, and confirm:
      - no asset class's automation loop starves or blocks another's (session manager correctly
        handles concurrent asset-class sessions sharing the same clock window — this is the first
        phase where two asset classes' sessions overlap almost entirely)
      - no shared state (USER_CONTEXTS, risk engine, liquidity guard, strike selection) leaks
        parameters or state across asset classes (e.g. a currency SL distance accidentally applied
        to a NIFTY position, or vice versa)
      - hard-exit times for each asset class fire independently and correctly (equity ~15:20-15:30,
        currency ~16:50, commodity per its own MCX close) with no cross-asset-class interference
- [ ] G2. Re-run the Phase 1/2/3 regression checks (narrowest representative check per prior phase,
      per `phase-programs.md` §Regression Checkpoint Standard) to confirm NIFTY and commodity
      trading still behave identically after currency onboarding — no shared config file or shared
      engine code path regressed.
- [ ] G3. **Abstraction-completeness assessment (required deliverable).** In the phase report,
      answer explicitly: did onboarding currency require ANY change outside config files, the
      strike-step adapter (a generic reusable adapter, not currency-specific logic), and
      strategy-parameter files?
      - If YES (config-only, as intended): state this as evidence the Phase 1 abstraction is
        sound — record it in the umbrella plan's program-level learnings.
      - If NO (session-manager code changed, risk-engine code changed, registry code changed,
        or a new fetcher/class was needed): document exactly what changed and why, and add this as
        an explicit **Phase 1 abstraction gap** finding in the umbrella plan / feature backlog —
        this feedback loop is a required output of this phase, not optional commentary.

---

## Exit Gate

```bash
# Confirm CURRENCY_OPTIONS asset class registers cleanly with no registry code change
python -c "from trading_app.engine.asset_classes import registry; print(registry.get('CURRENCY_OPTIONS'))"
# Expected: prints the config-driven AssetClassConfig for CURRENCY_OPTIONS with no import errors

# Confirm strike-step adapter produces correct strikes for USDINR and one cross-pair
python -m trading_app.engine.strike_selection --asset-class CURRENCY_OPTIONS --symbol USDINR --dry-run
python -m trading_app.engine.strike_selection --asset-class CURRENCY_OPTIONS --symbol EURINR --dry-run
# Expected: strike ladder aligned to the confirmed per-pair strike interval, no rounding errors

# Confirm liquidity guard gates cross-pairs to paper-only and USDINR to live-viable
python -m trading_app.engine.liquidity_guard --asset-class CURRENCY_OPTIONS --report
# Expected: USDINR marked live-viable; EURINR/GBPINR/JPYINR marked paper-only (or documented override)

# Concurrent multi-asset-class regression (paper/staging session)
python -m trading_app.engine.session_manager --simulate-concurrent --classes NIFTY,COMMODITY,CURRENCY_OPTIONS
# Expected: all three asset classes run their full session with no cross-class state leakage,
# each hard-exit fires independently at its own configured time
```

- All checklist items (A-G) checked
- USDINR currency options paper-validated, then live-small-promoted per Step F2
- Cross-pairs (EURINR/GBPINR/JPYINR) confirmed paper-only per Step E2/F3
- Currency-suitable strategy classification (Step C1) recorded in phase report
- Final concurrent-session regression (Step G1) green
- Abstraction-completeness assessment (Step G3) explicitly answered — YES/NO with evidence
- Validators run: `node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs`,
  `node .claude/skills/vc-generate-phase-program/scripts/validate-phase-stub.mjs
  process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-04-currency_PLAN_05-07-26.md`
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- Phase 1/2/3 exit gates not yet passed (abstraction not proven twice over yet) — this phase must
  not start ahead of its dependencies regardless of /goal autonomy.
- NSE_CD instrument/lot-size master unreachable or its symbol/strike-interval format does not match
  Step A2/B1 assumptions closely enough to proceed without new fetch/parsing code (would convert
  this from a config-only phase into a code phase — flag and re-scope before continuing).
- The Phase-1 AssetClass registry, session manager, or risk engine requires a code change to accept
  a 4th asset class or the 09:00-17:00 overlapping session — this is itself the key signal this
  plan is designed to surface (see Step G3); if it happens, BLOCK on Step A/D/G until the Phase 1
  gap is either fixed upstream or explicitly accepted as scope creep for this phase.
- Live NSE_CD quote/OI/volume data for cross-pairs cannot be obtained to confirm the Step E2
  liquidity classification (defaults to conservative paper-only until confirmed — not a hard block,
  but promotion to live-small for USDINR should not proceed without at least a same-session
  liquidity snapshot).
- Umbrella program Program Goal Charter marks this phase deferred/out-of-scope for the current
  execution window — this phase is explicitly noted as FUTURE/lower-priority; a deferral decision
  from the umbrella plan is not itself a blocker of this plan's readiness, only of its scheduling.

---

## Phase Completion Rules

This phase is complete only when every Implementation Checklist item (A-G) is checked, the Exit
Gate commands all pass, the Step G3 abstraction-completeness assessment is explicitly answered,
and the Phase Loop Progress steps 1-7 below are all checked (validate-contract PASS or explicitly
accepted CONDITIONAL, EVL green, phase report written, umbrella state updated). Code-only
completion (checklist done, gates not yet independently re-run via EVL) is `CODE DONE`, not
`VERIFIED` — do not mark this phase VERIFIED without both phase evidence and the Step G regression
evidence.

## Acceptance Criteria

See the `## Verification Evidence` table below — each row is a testable acceptance criterion with
its proving strategy (Fully-Automated / Hybrid / Agent-Probe). Summary:

- USDINR currency options tradeable (paper-validated, then live-small per Step F)
- Currency-suitable strategies identified and tuned (Step C1-C2); unsuited strategies explicitly excluded (Step C3)
- All 4 asset classes (NIFTY, commodities, currency) coexist without interference (Step G1 — capstone regression)
- Abstraction-completeness explicitly assessed (Step G3) — YES/NO with evidence, feeding back into the umbrella plan's program-level learnings

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: prior phase reports (Phases 1-3) read; NSE_CD instrument master
      format confirmed; test context loaded; plan drift checked against current Phase 1 abstraction
      state
- [ ] 2. INNOVATE — innovate-agent: approach decided (config-only vs. any code-change scope); Decision
      Summary written if any Step A4/D3/G3 gap surfaces requiring a design choice
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: existing phase plan updated with RESEARCH findings; Inner Loop
      Refresh Note if sections changed (or "n/a — research clean")
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md` (Status / Gate /
      Plan updates applied / Execute-agent instructions / Test gates / High-risk pack / Backlog
      artifacts / Known gaps / Accepted by) — note: this phase touches live money (Step F) and a
      currency risk-config surface (Step A3), so the high-risk pack is expected to trigger
- [ ] 5. EXECUTE — all checklist items (A-G) done; per-section test gates run and green (or gaps
      documented); Step F's paper→live-small sequencing followed in order, never skipped ahead
- [ ] 6. EVL — all EVL gates green (including the concurrent-session regression from Step G1);
      follow-up stubs registered for any cross-pair live-promotion deferred by Step E2/F3; EVL
      HANDOFF SUMMARY written
- [ ] 7. UPDATE PROCESS — phase report written (including Step G3 abstraction-completeness
      assessment), umbrella state updated, commit done

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder. Given this phase touches live
money and a new risk-config surface, do NOT accept a CONDITIONAL gate on Step A3 (risk config) or
Step F (live promotion sequencing) without explicit user sign-off — these map to the program's
high-risk classes (auth/billing is N/A here, but "destructive data mutation"-equivalent risk exists
via live order placement).

---

## Touchpoints

- `trading-app/config/asset_classes/currency_options.py` (new `AssetClassConfig` entry)
- `trading-app/engine/strike_selection.py` (new generic strike-step adapter, config-registered)
- `trading-app/engine/risk_config.py` (new currency-tuned risk config entry)
- `trading-app/config/strategy_params/currency.py` (new currency-tuned strategy parameter sets)
- `trading-app/engine/liquidity_guard.py` (new config entries only — USDINR live-viable,
  cross-pairs paper-only)
- `trading-app/engine/session_manager.py` (read-only verification; code change only if a Phase-1
  gap is found)
- `trading-app/engine/asset_classes.py` / registry (read-only verification; code change only if a
  Phase-1 gap is found)
- Phase report file (new): `phase-04-currency_REPORT_{dd-mm-yy}.md`
- Umbrella plan: `## Current Execution State`, `## Phase Ordering`, program-level learnings section
  (updated with Step G3's abstraction-completeness finding)

---

## Public Contracts

- No new public API surface — this phase adds a new tradeable asset class through existing
  internal config/registry contracts (Phase 1), not a new external interface.
- Existing NIFTY equity and commodity trading behavior, contracts, and UI surfaces (admin/user
  dashboards) remain unchanged — currency positions surface through the SAME generic
  position/order UI components already built for equity and commodity (no new UI contract).
- Existing background-loop contracts (`purge_user_runtime()`, `USER_CONTEXTS`/`USER_STATES`
  scoping, per `process/context/all-context.md`) are reused unchanged — currency-holding users
  must be cleaned up correctly on deactivate/delete via the same shared mechanism, with no
  currency-specific carve-out.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Registry accepts `CURRENCY_OPTIONS` config with no code change (Exit Gate cmd 1) | Fully-Automated | USDINR currency options tradeable via config-only onboarding |
| Strike-step adapter produces correct strikes for USDINR + EURINR (Exit Gate cmd 2) | Fully-Automated | Currency option strike selection adapted correctly for 0.25-paise intervals |
| Liquidity guard gates USDINR live-viable / cross-pairs paper-only (Exit Gate cmd 3) | Fully-Automated | Liquidity guard correctly distinguishes USDINR from less-liquid cross-pairs |
| Currency strategy suitability classification documented (Step C1) | Agent-Probe | Currency-suitable strategies identified and tuned; unsuited strategies excluded |
| RBI-intervention / regime-shift risk documented + risk-engine hook checked (Step D1/D3) | Hybrid | Currency-specific risk/reward profile is accounted for, not silently inherited from NIFTY/commodity defaults |
| Concurrent 4-asset-class session simulation, overlapping 09:00-17:00 window (Exit Gate cmd 4 / Step G1) | Hybrid | All asset classes coexist without interference (capstone multi-asset architecture proof) |
| Phase 1/2/3 regression checks re-run clean (Step G2) | Hybrid | Nothing else regresses |
| USDINR paper-validated across a quiet + RBI-relevant session (Step F1) before live-small promotion (Step F2) | Hybrid | Paper → validate → live-small discipline followed for live money |
| Abstraction-completeness assessment answered YES/NO with evidence (Step G3) | Agent-Probe | Proves (or disproves) that Phase 1 abstraction makes new asset-class onboarding a config exercise |

---

## Test Infra Improvement Notes

(none identified yet)

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-04-currency_PLAN_05-07-26.md`
- Last completed step: not started — PLANNING ONLY, no code executed. This is a FUTURE/lower-priority
  phase per the umbrella plan; it may be deferred, but this plan is execution-ready as written.
- Validate-contract status: pending — placeholder below; requires Phase 1-3 exit gates confirmed
  complete before Step 4 (PVL) can meaningfully run
- Supporting context files loaded for this plan: `process/context/all-context.md` (Security
  Remediation Phase 2 patterns re: `purge_user_runtime()`/`USER_CONTEXTS` scoping, referenced in
  Step F4/Public Contracts), umbrella plan
  `multi-asset-expansion-umbrella_PLAN_05-07-26.md` (Program Goal Charter, hard safety constraints,
  phase sequencing)
- Next step: confirm Phase 1 (abstraction) and Phases 2-3 (commodities) are VERIFIED per the
  umbrella plan's `## Current Execution State`; when this phase is scheduled (not deferred), spawn
  vc-research-agent for Step 1 (RESEARCH) — prioritize confirming the actual NSE_CD instrument
  master symbol format and strike-interval-per-pair BEFORE writing any config, since Step A2/B1
  assumptions are stated as "confirm against live master, do not hardcode."

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
