---
name: plan:multi-asset-phase-03-expand-commodities
description: "Multi-Asset Expansion — Phase 3: replicate proven crude commodity-options pattern across all major MCX commodities"
date: 05-07-26
metadata:
  node_type: memory
  type: plan
  feature: multi-asset-expansion
  phase: phase-03
---

# Phase 3 — Expand Commodities (Natural Gas, Bullion, Base Metals)

**Program:** multi-asset
**Umbrella plan:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md
**Phase status:** ⏳ PLANNED
**Report destination:** process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-03-expand-commodities_REPORT_05-07-26.md (flat in the program task folder)

> **Grounding note (read before executing):** As of this plan's write date, `trading-app/engine/asset_classes.py` (Phase 1 abstraction layer) and the Phase 2 crude onboarding plan/report do not yet exist on disk in this repo. This plan assumes both are complete and VERIFIED before Phase 3 starts (per Entry Gate below) and documents the *expected* Phase-1/Phase-2 contract shape based on the task brief. **The first action of Phase 3 RESEARCH (Step 1) must re-confirm the actual `AssetClass` registry shape, the actual crude config keys, and the actual liquidity-guard function signature against the real files** — do not assume this plan's placeholder field names are final; treat them as the best-known contract until RESEARCH re-verifies.

---

## Purpose

Phase 3 takes the crude-oil options pattern proven in Phase 2 (built on the Phase 1 `AssetClass`
abstraction layer) and replicates it — as **configuration and per-commodity tuning**, not new
architecture — across the remaining major MCX commodities: Natural Gas, Gold, Silver, Copper, and
base metals (Zinc, Lead, Aluminium). Each commodity gets its own tuned parameter profile, risk
config, and liquidity classification registered in the asset-class registry. The phase deliberately
avoids inventing new mechanisms: if a commodity needs something the registry/abstraction layer
cannot express, that is a signal to stop and route back to Phase 1, not to bolt on a one-off hack
in Phase 3.

This is a **live-money** expansion. Every new commodity follows paper → validate → live-small,
one at a time. NIFTY (pre-existing) and crude (Phase 2) must not regress at any point.

---

## Entry Gate

- Phase 1 (asset-class abstraction layer) complete — `AssetClass` registry exists, is documented,
  and is proven to support at least one non-trivial asset class end-to-end.
- Phase 2 (crude onboarding) complete and marked VERIFIED — crude options trading through the
  registry, paper-validated, and (per the umbrella's scope tier for Phase 2) live-small where
  applicable, with its own validate-contract PASS/accepted-CONDITIONAL on file.
- Phase 2's liquidity guard function is identified by name/path and confirmed reusable (not
  crude-hardcoded) — if it is crude-hardcoded, this is a blocker for Step D below (see
  Blockers section) and must be generalized as a small Phase-3 pre-step, not skipped.
- Umbrella plan's Phase Ordering confirms Phase 3 is next and Phase 2's exit gate evidence is on
  file in the phase-02 report.

---

## Blast Radius

- `trading-app/engine/asset_classes.py` — register 7 new `AssetClass` entries (NATURALGAS, GOLD,
  SILVER, COPPER, ZINC, LEAD, ALUMINIUM); no changes to the class/registry *shape* expected — if a
  shape change is needed, that is an escalation back to Phase 1's owner, not a Phase 3 checklist item.
- `trading-app/engine/risk_orchestrator.py` — per-commodity risk profile lookup wired for the 7
  new asset classes (max trades, SL range, position sizing) — reusing the crude per-asset lookup
  path added in Phase 2, not introducing a new dispatch mechanism.
- `trading-app/engine/strategy_orb.py`, `strategy_5.py`, `strategy_8.py`, `strategy_9.py`,
  `strategy_926.py`, `strategy_gap.py`, `strategy_swing.py`, `strategy_wisdom.py` — **read-only
  for logic**; add per-asset-class parameter overrides only where these strategies already accept
  a config/profile object (no new strategy files, no new signal logic).
- `trading-app/engine/signals.py` — session-window and volatility-awareness wiring per commodity
  (e.g. Thursday EIA storage-report flag for Natural Gas), reusing whatever session/volatility
  hook Phase 2 added for crude.
- `trading-app/static/admin.html` (or the admin config surface Phase 2 used for crude) — surface
  per-commodity paper/live status and liquidity classification so the staged rollout (Step G) is
  visible to the operator, mirroring however Phase 2 exposed crude's rollout state.
- `trading-app/data/` — new config/state rows per commodity (liquidity classification, rollout
  stage) using whatever storage Phase 2 used for crude's equivalent state (DB table vs config
  file — RESEARCH Step 1 confirms).
- New file: `trading-app/engine/commodity_profiles.py` (or equivalent, name TBD by RESEARCH if a
  similar file doesn't already exist from Phase 2) — one declarative profile block per commodity
  covering session window, volatility parameters, tick size, SL range, position sizing, and
  liquidity-review cadence. Prefer extending an existing Phase-2 profiles module over creating a
  new one if Phase 2 already introduced one for crude.

**Explicitly NOT in blast radius:** NIFTY equity-index logic, crude's existing config (read-only
reference, never modified by this phase), the `AssetClass` registry's class shape/schema, any new
broker/API integration (MCX symbols are assumed already reachable via the existing Fyers
integration used for crude — RESEARCH Step 1 confirms this holds for all 7 new symbols).

---

## Per-Commodity Config Reference (planning-time defaults — RESEARCH may tune)

| Commodity | Symbol (assumed) | Session | Volatility class | Notes |
|---|---|---|---|---|
| Natural Gas | MCX:NATURALGAS | 09:00–23:30 | Very high (energy-linked) | Thursday EIA storage report volatility spike; widen SL, shrink position size on report day |
| Gold | MCX:GOLD | 09:00–23:30 | Low–moderate, trending | Most liquid MCX commodity options — best real-liquidity candidate; large contract value → careful position sizing |
| Silver | MCX:SILVER | 09:00–23:30 | Moderate, trending | USD/geopolitics-linked; correlates with Gold but higher volatility |
| Copper | MCX:COPPER | 09:00–23:30 | Moderate, industrial-demand-driven | Global-growth sentiment sensitive |
| Zinc | MCX:ZINC | 09:00–23:30 | Moderate | Liquidity TBD by Step D — likely paper-only initially |
| Lead | MCX:LEAD | 09:00–23:30 | Moderate–low | Liquidity TBD by Step D — likely paper-only initially |
| Aluminium | MCX:ALUMINIUM | 09:00–23:30 | Moderate–low | Liquidity TBD by Step D — likely paper-only initially |

This table is a planning-time hypothesis. Step D (liquidity validation) and Step F (risk config)
are the authoritative source once RESEARCH/EXECUTE run — this table must not be treated as final
config.

---

## Implementation Checklist

### Step A — Natural Gas (MCX:NATURALGAS)

- [ ] A1. Confirm Fyers symbol availability and tick size for `MCX:NATURALGAS` options; record in
  `commodity_profiles.py`.
- [ ] A2. Register `NATURALGAS` in the `AssetClass` registry (`trading-app/engine/asset_classes.py`)
  following the exact registration shape crude used in Phase 2.
- [ ] A3. Set session window 09:00–23:30 in the registry entry.
- [ ] A4. Add ATR-based volatility sizing parameters tuned wider than crude's (natural gas is more
  volatile than crude) — wide SL, small position size.
- [ ] A5. Add EIA-storage-report volatility-awareness flag: mark Thursdays (report day) as a
  reduced-size / widened-SL session in the profile, reusing whatever "event-day awareness" hook
  Phase 2 built for crude's own event sensitivity (or add the minimal equivalent if Phase 2 has
  none — flag this as new mechanism and escalate to Phase 1 owner if it requires an abstraction
  change).
- [ ] A6. Wire risk_orchestrator.py per-asset lookup for NATURALGAS (max trades/day, SL range,
  position sizing) per the Step F profile.

### Step B — Bullion (Gold + Silver)

- [ ] B1. Confirm Fyers symbol availability and tick size for `MCX:GOLD` and `MCX:SILVER` options.
- [ ] B2. Register `GOLD` and `SILVER` in the `AssetClass` registry, session window 09:00–23:30.
- [ ] B3. Tune volatility/trend parameters for bullion class: lower volatility than energy,
  trending-strategy-favorable (ORB/momentum profiles lean toward trend continuation over crude's
  breakout-heavy tuning).
- [ ] B4. Add large-contract-value position-sizing guard: bullion contract notional is materially
  larger than crude/natgas per lot — position sizing must account for this explicitly, not reuse
  crude's per-lot sizing constant unmodified.
- [ ] B5. Flag Gold as the priority real-liquidity candidate in `commodity_profiles.py` (most
  liquid MCX commodity options) — this informs Step D's expected outcome but does not skip the
  liquidity check itself.
- [ ] B6. Wire risk_orchestrator.py per-asset lookup for GOLD and SILVER.

### Step C — Base Metals (Copper, Zinc, Lead, Aluminium)

- [ ] C1. Confirm Fyers symbol availability and tick size for `MCX:COPPER`, `MCX:ZINC`,
  `MCX:LEAD`, `MCX:ALUMINIUM` options.
- [ ] C2. Register `COPPER` in the `AssetClass` registry (session 09:00–23:30) — treat as the
  base-metals reference profile since it is expected to be the most liquid of the group.
- [ ] C3. Register `ZINC`, `LEAD`, `ALUMINIUM` in the registry using Copper's profile as a
  starting template, tuned per-symbol tick size/contract size.
- [ ] C4. Tune moderate industrial-demand-driven volatility parameters for the base-metals class
  (distinct from bullion's trend profile and energy's high-volatility profile).
- [ ] C5. Wire risk_orchestrator.py per-asset lookup for all 4 base metals.

### Step D — Per-Commodity Liquidity Validation

- [ ] D1. Locate and confirm Phase 2's liquidity guard function (name/path) is genuinely reusable
  across asset classes (not crude-hardcoded). If hardcoded to crude, generalize it minimally
  first (parametrize by symbol/asset class) — this is a small refactor, not new architecture.
- [ ] D2. Run the liquidity guard against each of the 7 new commodities individually (Natural Gas,
  Gold, Silver, Copper, Zinc, Lead, Aluminium).
- [ ] D3. Classify each commodity: `LIVE-VIABLE` (sufficient options liquidity) or `PAPER-ONLY`
  (too thin for live order routing) based on the guard's threshold.
- [ ] D4. Document the classification for all 7 commodities in `commodity_profiles.py` and in the
  phase report — expected outcome per the brief: Gold near-certain LIVE-VIABLE; several base
  metals (Zinc/Lead/Aluminium) likely PAPER-ONLY pending actual guard results.
- [ ] D5. Any commodity classified `PAPER-ONLY` is hard-locked out of live order routing at the
  registry/risk-orchestrator level (not just a UI label) — a config flag alone is not sufficient;
  confirm the lockout is enforced at the order-routing decision point.

### Step E — Per-Commodity Strategy Parameter Profiles

- [ ] E1. For each of the 7 commodities, tune the existing reusable strategies (ORB, breakout,
  momentum — whichever of `strategy_orb.py`, `strategy_5.py`, `strategy_8.py`, `strategy_9.py`,
  `strategy_926.py`, `strategy_gap.py`, `strategy_swing.py`, `strategy_wisdom.py` apply per Phase
  2's crude wiring) to that commodity's volatility class and tick size.
- [ ] E2. Document each commodity's tuned strategy parameter profile in `commodity_profiles.py`
  (which strategies are active, and their tuned inputs) — no new strategy logic, only config.
- [ ] E3. Cross-check: bullion profile favors trend-continuation tuning (per B3); energy (Natural
  Gas) favors wider-SL/smaller-size breakout tuning; base metals favor moderate industrial-demand
  tuning — confirm no commodity silently inherited crude's exact tuning unmodified.

### Step F — Per-Commodity Risk Config

- [ ] F1. Define per-commodity risk profile: max trades/day, SL range (min/max), position sizing
  formula/constant — for each of the 7 commodities individually. Bullion, energy, and base-metals
  profiles must differ materially (per brief: "a bullion position ≠ a natgas position").
- [ ] F2. Document each profile in `commodity_profiles.py` alongside the strategy profile from
  Step E, so risk config and strategy config are co-located and auditable per commodity.
- [ ] F3. Confirm risk_orchestrator.py's per-asset lookup path (wired incrementally in Steps A/B/C)
  correctly resolves each commodity's profile at runtime — no silent fallback to a default/crude
  profile for any of the 7 commodities.

### Step G — Staged Rollout (Paper → Validate → Live-Small)

- [ ] G1. Onboard all 7 commodities in `PAPER` mode simultaneously (config-only, no live order
  routing) — this is safe to parallelize since paper mode has no live-money exposure.
- [ ] G2. Run each commodity in paper mode long enough to observe at least one full session cycle
  per commodity, confirming signals fire, risk limits apply, and no crash/exception occurs.
- [ ] G3. For each `LIVE-VIABLE` commodity (per Step D), promote to `LIVE-SMALL` **one commodity
  at a time**, in this order: Gold first (highest confidence liquidity), then Copper, then Silver,
  then Natural Gas (highest volatility — promote last, most caution), then any remaining
  `LIVE-VIABLE` base metals.
- [ ] G4. Before each individual live-small promotion: confirm NIFTY and crude are still trading
  normally (regression checkpoint — see Verification Evidence) and confirm the previously promoted
  commodity (if any) is stable in live-small mode.
- [ ] G5. `PAPER-ONLY` commodities (per Step D) remain in paper mode indefinitely — document this
  explicitly as accepted scope, not a temporary state pending a "will fix later."
- [ ] G6. Never promote more than one new commodity to live-small in the same rollout step —
  sequential promotion only, never all-live-at-once.

---

## Exit Gate

```bash
# Registry check — all 7 commodities present
python3 -c "from trading_app.engine.asset_classes import ASSET_CLASSES; \
missing = [s for s in ['NATURALGAS','GOLD','SILVER','COPPER','ZINC','LEAD','ALUMINIUM'] if s not in ASSET_CLASSES]; \
print('MISSING:', missing) if missing else print('ALL 7 REGISTERED')"
# Expected: ALL 7 REGISTERED

# Liquidity classification present for all 7
grep -c "LIVE-VIABLE\|PAPER-ONLY" trading-app/engine/commodity_profiles.py
# Expected: >= 7 (one classification line per commodity)

# NIFTY + crude regression — reuse Phase 2's own smoke check verbatim
# (exact command confirmed by RESEARCH Step 1 against the real Phase 2 report)
```

- All 7 commodities registered in the `AssetClass` registry with session, volatility, tick-size
  config populated.
- Liquidity classification (`LIVE-VIABLE` / `PAPER-ONLY`) documented and enforced at the
  order-routing level for every one of the 7 commodities.
- Per-commodity strategy parameter profile and risk profile documented in
  `commodity_profiles.py` for all 7 commodities, with bullion/energy/base-metals profiles
  demonstrably distinct (not copy-pasted from crude unmodified).
- Staged rollout complete: all 7 in paper mode validated; all `LIVE-VIABLE` commodities promoted
  to live-small one at a time with a regression check before each promotion; `PAPER-ONLY`
  commodities explicitly documented as paper-only-by-design.
- NIFTY and Phase-2 crude trading unaffected throughout (regression checkpoints clean at every
  promotion step).
- Phase report written to report destination above.

---

## Blockers That Would Justify BLOCKED Status

- Phase 2's liquidity guard is crude-hardcoded and cannot be generalized without a Phase-1
  abstraction change (escalate to Phase 1 owner rather than hacking around it in Phase 3).
- One or more of the 7 MCX symbols is not reachable via the existing Fyers integration used for
  crude (would require new broker/API wiring — out of Phase 3's config-only scope).
- `AssetClass` registry shape cannot express a needed per-commodity parameter (e.g. event-day
  awareness) without a schema change — escalate to Phase 1, do not bolt on a one-off field.
- Phase 2 crude is not actually VERIFIED (Entry Gate fails) — do not begin Phase 3 checklist work
  against an unproven pattern.
- Live-money promotion decision cannot get the required manual-first evidence handoff (per
  `orchestration.md` §High-Risk Execution Handoff) — this phase touches live trading and must not
  self-promote to live-small without that gate.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [ ] 1. RESEARCH — research-agent: confirm actual Phase 1 `AssetClass` registry shape, actual
  Phase 2 crude config/profile module, actual liquidity guard function signature and reusability,
  and actual Fyers symbol reachability for all 7 new MCX symbols; flag any placeholder field name
  in this plan that doesn't match reality.
- [ ] 2. INNOVATE — innovate-agent: decide grouping approach if RESEARCH finds the registry needs
  more than pure config (e.g. whether base metals share one template class vs four independent
  entries); default assumption in this plan is pure config, no new architecture.
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: update this phase plan with RESEARCH findings (real field
  names, real liquidity guard path, confirmed/adjusted symbol list) or mark "n/a — research clean".
- [ ] 4. PVL — vc-validate-agent: full V1-V7; validate-contract written per
  `.claude/skills/vc-validate-findings/references/example-validate-output.md`.
- [ ] 5. EXECUTE — all checklist items (Steps A–G) done; per-section test gates run and green (or
  gaps documented); staged rollout executed with manual-first live-small gate.
- [ ] 6. EVL — all EVL gates green (including NIFTY/crude regression); follow-up stubs registered;
  EVL HANDOFF SUMMARY written.
- [ ] 7. UPDATE PROCESS — phase report written, umbrella state updated, commit done.

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate Contract`
reads "(placeholder — vc-validate-agent writes this section before EXECUTE)", orchestrator must
spawn vc-validate-agent first. A partial contract missing Plan updates applied / Execute-agent
instructions / Test gates sections is treated as a placeholder.

---

## Touchpoints

- `trading-app/engine/asset_classes.py` (modify — register 7 new asset classes)
- `trading-app/engine/risk_orchestrator.py` (modify — per-asset risk lookup for 7 new classes)
- `trading-app/engine/commodity_profiles.py` (create or extend — per-commodity config profiles)
- `trading-app/engine/signals.py` (modify — session/volatility/event-day wiring)
- `trading-app/engine/strategy_orb.py`, `strategy_5.py`, `strategy_8.py`, `strategy_9.py`,
  `strategy_926.py`, `strategy_gap.py`, `strategy_swing.py`, `strategy_wisdom.py` (config-only
  touch — no logic changes)
- `trading-app/static/admin.html` (or Phase 2's equivalent config surface) (modify — expose
  per-commodity rollout/liquidity status)
- `trading-app/data/` (modify — new per-commodity config/state rows)

---

## Public Contracts

- NIFTY equity-index trading behavior — unchanged.
- Phase-2 crude trading behavior and its existing config — unchanged (read-only reference only).
- `AssetClass` registry public shape/schema (as defined by Phase 1) — unchanged; Phase 3 only adds
  entries, never alters the shape.
- Existing Fyers API integration contract — unchanged; Phase 3 adds new symbol subscriptions only.
- Admin/config UI surface used for crude rollout visibility — extended (new commodities added),
  not redesigned.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| Registry contains all 7 new `AssetClass` entries with populated session/volatility/tick-size config | Fully-Automated — `python3 -c "..."` registry membership check (see Exit Gate) | All viable MCX commodities registered |
| Liquidity classification documented + enforced at order-routing level for all 7 commodities | Hybrid — automated grep for classification presence + manual confirmation that `PAPER-ONLY` commodities are actually blocked from live order routing (precondition: registry + risk_orchestrator wiring complete) | Illiquid commodities flagged paper-only, documented |
| Per-commodity strategy + risk profiles distinct across bullion/energy/base-metals groups | Agent-Probe — reviewer inspects `commodity_profiles.py` and confirms bullion/energy/base-metals values are not identical copy-paste of crude's profile | Per-commodity risk/param profiles documented |
| Natural Gas EIA-report-day volatility awareness fires on Thursdays | Hybrid — run signal engine against a mocked Thursday session date, confirm reduced-size/widened-SL branch is taken (precondition: mock/test harness for session-date injection exists or is added) | Natural Gas volatility-awareness requirement met |
| NIFTY trading behavior unaffected after each commodity onboarding step | Hybrid — reuse existing NIFTY smoke/regression check (path confirmed by RESEARCH Step 1), run before and after each Step G promotion | "NIFTY + crude must not regress" |
| Crude (Phase 2) trading behavior unaffected after each commodity onboarding step | Hybrid — reuse Phase 2's own crude regression check verbatim, run before and after each Step G promotion | "NIFTY + crude must not regress" |
| Staged rollout — no commodity ever promoted directly to live without a prior paper-validated cycle | Agent-Probe — reviewer inspects rollout sequence/log for each `LIVE-VIABLE` commodity, confirms paper → validate → live-small order was followed and no two commodities were promoted in the same step | "paper → validate → live-small, one at a time, not all-live-at-once" |
| Live-small promotion decision received manual-first evidence handoff before execution | Agent-Probe — orchestrator/user confirms the high-risk evidence pack (per `orchestration.md` §High-Risk Execution Handoff) was produced and reviewed before each live-small promotion | Live-money safety constraint |

---

## Test Infra Improvement Notes

(none identified yet — RESEARCH Step 1 may surface a need for a session-date-injection test
harness to exercise the Thursday EIA-report volatility branch deterministically; if so, record it
here during PLAN-SUPPLEMENT rather than inventing an ad-hoc mock inline during EXECUTE.)

---

## Resume and Execution Handoff

1. **Selected plan file path:** `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-03-expand-commodities_PLAN_05-07-26.md`
2. **Last completed phase or step:** Not started — this plan has not yet entered the 7-step inner
   loop. Phase 1 and Phase 2 are assumed complete per this plan's Entry Gate but their actual
   on-disk state was NOT confirmed at plan-write time (see grounding note at top of file) — this
   is the first thing RESEARCH (Step 1) must confirm.
3. **Validate-contract status:** pending — placeholder only (see `## Validate Contract` below).
4. **Supporting context files loaded:** `process/context/all-context.md`,
   `process/development-protocols/all-development-protocols.md`,
   `process/development-protocols/phase-programs.md`,
   `process/development-protocols/orchestration.md` (§High-Risk Execution Handoff, §VALIDATE
   Gate). Umbrella plan and Phase 2 plan were referenced by expected path but not confirmed to
   exist on disk at plan-write time.
5. **Next step for a fresh agent picking up mid-execution:** Confirm the umbrella plan and Phase 2
   plan/report actually exist and are VERIFIED before doing anything else. If either is missing,
   this phase is BLOCKED on its Entry Gate and must not proceed past Step 1 RESEARCH — surface
   that to the orchestrator immediately rather than inventing Phase 1/2 details. If both are
   confirmed present and VERIFIED, spawn `vc-research-agent` for Phase 3 Step 1.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
