---
name: plan:multi-asset-expansion-umbrella
description: "ControlN multi-asset expansion — umbrella/orchestration plan for the 4-phase program (NIFTY-only → indices/stocks/commodities/currency)"
date: 05-07-26
metadata:
  node_type: memory
  type: plan
  feature: multi-asset-expansion
  phase: umbrella
---

# ControlN Multi-Asset Expansion — Umbrella Plan

**Date:** 05-07-26
**Complexity:** COMPLEX
**Status:** ⏳ PLANNED

- Program type: PHASE PROGRAM (4 phases, sequential with gated joins)
- Date: 05-07-26
- Feature folder: `process/features/multi-asset-expansion/`
- PLANNING ONLY — no code executed by this session. This plan is written to be "one-click start"
  ready: paste the Stable Program Goal block below into a fresh session/`/goal` to begin execution.

---

## Program Goal Charter

```
ControlN Multi-Asset Expansion — Program Goal Charter

North star:
- Expand ControlN from a NIFTY-index-options-only automated trading platform into a multi-asset
  platform that also trades MCX commodity options (all major commodities) and NSE currency
  derivatives, using the same 9-strategy engine (reused + per-asset tuned) — WITHOUT ever
  regressing live NIFTY trading.

Definition of done (an unattended agent must be able to do all of these):
1. Add or configure a new asset class (exchange, sessions, symbol format, lot-size source,
   expiry cycle, volatility measure, risk profile) through the abstraction registry alone —
   no hard-coded market-hours / VIX / symbol-prefix edits needed anywhere else in the codebase.
2. Run NIFTY, MCX Crude Oil options, and (after Phase 4) NSE currency derivatives concurrently
   in the same automation/background-worker process, each respecting its own session hours,
   hard-exit time, volatility proxy, and risk limits.
3. Onboard any additional MCX commodity (gold, silver, natgas, copper, base metals) as a
   configuration-only change once Phase 3 completes the multi-commodity rollout.
4. Prove every new asset class in paper-trading before any live order is placed on it, with an
   explicit go/no-go checkpoint recorded in the phase report.

What "verified" means (program level):
- Phase code changes are VERIFIED only when: (a) the phase's own validate-contract gates are
  green, (b) the NIFTY regression checkpoint (see Global Constraints) passes on the same commit,
  and (c) for any phase introducing a new tradable asset, at least one full paper-trading session
  covering that asset's live session hours has run with results captured in the phase report.
- validate-contract gates must be recorded alongside phase gates and regression evidence for a
  phase to reach VERIFIED. A phase without a validate-contract (or documented skip reason) cannot
  be marked VERIFIED.

Scope tiers → phase mapping:
- Tier 1 (Foundation — asset abstraction layer, zero new trading) → Phase 1
- Tier 2 (Proof — one commodity end-to-end, live-small-size) → Phase 2
- Tier 3 (Commodity breadth — all major MCX commodities) → Phase 3
- Tier 4 (Currency — NSE currency derivatives, config-only) → Phase 4
- This program retires Tiers 1-4 in full when Phase 4's exit gate is green.

Explicitly out of scope (deferred tier):
- Equity cash/futures trading (only index + commodity + currency OPTIONS are in scope).
- Any exchange outside NSE (options+currency) and MCX (commodity options) — e.g. no BSE, no
  international/crypto venues.
- Automated capital-allocation / portfolio-level risk netting ACROSS asset classes (each asset
  class keeps its own risk budget in this program; cross-asset netting is a future program).
- UI/dashboard redesign beyond the minimum needed to select/monitor the new asset classes.

Hard safety constraints (non-negotiable, per phase):
- NIFTY/equity index-options trading is live with real money and must NEVER regress. Every phase
  (1-4) must run the NIFTY regression checkpoint on the same commit before being marked VERIFIED.
- No new asset class may go live (real orders) without a completed paper-trading validation pass
  first — this is a hard stop, not a recommendation.
- Commodity/currency risk limits (SL, position sizing, max exposure) must be asset-class-specific
  configuration — never inherit NIFTY's numeric SL/sizing defaults by omission.
- MCX options liquidity must be checked per-commodity before that commodity goes live (thin-book
  commodities are a known risk — see Phase 3 gate).
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits.
- Never widen Fyers API credential scope or touch `.env` secret values in a way that isn't already
  covered by the existing Session/Trust-Boundary patterns (see `process/context/all-context.md`).
```

---

## Stable Program Goal (copy-paste this to start autonomous execution)

```
SESSION GOAL: multi-asset-expansion — ControlN Multi-Asset Expansion
Ref: process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md

TARGET: Complete ALL 4 phases until:
- Asset abstraction registry live; NIFTY unchanged through it (Phase 1 exit)
- MCX Crude Oil options paper-validated then live-small (Phase 2 exit)
- All major MCX commodities onboarded with per-commodity risk profiles (Phase 3 exit)
- NSE currency derivatives onboarded config-only (Phase 4 exit)
- Test tiers: automated (iterate-until-green) / hybrid (fix-if-in-blast-radius) / agent-probe (record-judgment)

AUTONOMY: Before ANY subagent spawn, read:
1. Umbrella ## Current Execution State -> loop step + validate-contract status
2. Phase plan ## Phase Loop Progress -> first unchecked box = next subagent to spawn

PER-PHASE LOOP (7-step inner loop R -> I -> P -> PVL -> E -> EVL -> UP, never skip, never reorder; SKIPS SPEC -- SPEC ran once for this umbrella already):
  1. RESEARCH -> 2. INNOVATE -> 3. PLAN-SUPPLEMENT -> 4. PVL -> 5. EXECUTE -> 6. EVL -> 7. UPDATE-PROCESS
- PLAN-SUPPLEMENT: plan-agent writes research/innovate gaps into phase plan (or marks "n/a -- clean")
- PVL NEVER skipped; contract must follow example-validate-output.md full format; a partial
  contract (missing Plan updates applied / Execute-agent instructions / Test gates) = blocked,
  same as a placeholder
- Every subagent FIRST ACTION: run vc-context-discovery (load context group files +
  process/context/tests/all-tests.md routing chain) AND vc-plan-discovery (same-feature full
  depth active/backlog/completed/reports/refs + other features active-only + general-plans active)
- Every phase-END: invoke vc-agent-strategy-compare for next step strategy recommendation

Report via phase reports. No approval between phases unless a hard stop is hit.

HARD STOPS (pause, wait for user):
- Any live order placement on a new asset class before a completed paper-trading pass is on record
- NIFTY regression checkpoint fails on any phase's commit
- Net gate = BLOCKED with no backlog resolution path
- Plan file marks "pause required" or agent count > 100
- Validate-contract is placeholder and vc-validate-agent cannot run
- MCX commodity going live while its options book is flagged thin/illiquid (Phase 3 gate)

SAFETY (never override):
- NIFTY/equity trading must never regress -- run the regression checkpoint every phase
- Never reuse NIFTY numeric SL/position-sizing defaults for a new asset class by omission
- Commit each phase before advancing; process and execution commits kept separate

TEST GATES (every phase exit -- exact commands sourced from process/context/tests/all-tests.md
at PLAN/VALIDATE time for each phase; program-level regression command below runs every phase):
  pytest trading-app/ -k "nifty or regression" -q   # NIFTY regression smoke (confirm exact path/marker at Phase 1 VALIDATE -- no pytest suite confirmed yet, flag as Test Infra gap)
  node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs
  node .claude/skills/vc-audit-context/scripts/validate-context-discovery.mjs

VALIDATE CONTRACT: Per-phase contracts written by vc-validate-agent into each phase plan before EXECUTE.

START: Phase 1 (Asset Abstraction Layer), loop step RESEARCH (pending). Spawn vc-research-agent
for Phase 1 with this umbrella plan + phase-01 plan as context.
```

---

## Phase Sequence

| Phase | Plan file | Scope summary | Depends on |
|---|---|---|---|
| 0 (pre-program) | this file | Confirm folder structure, program charter, create 4 phase plans | — |
| 1 — Asset Abstraction Layer | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-01-asset-abstraction-layer_PLAN_05-07-26.md` | Build per-asset-class config registry (exchange, sessions/hours, symbol format, lot-size source, expiry cycle, volatility measure, risk config); centralize the 27 hard-coded market-hour checks into one session manager; per-asset hard-exit; extend lot-size fetch to MCX_COM/NSE_CD; abstract India-VIX -> per-asset volatility measure; exchange-aware symbol builder. NO new trading. NIFTY regression-proof. | Phase 0 |
| 2 — Onboard Crude Oil | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-02-onboard-crude_PLAN_05-07-26.md` | Onboard MCX Crude Oil options end-to-end through the Phase 1 abstraction: symbols/lots/expiry/sessions wired; reusable strategies (ORB, breakout, momentum, gap-fill) applied with crude-tuned params; 1-2 commodity-specific strategies added; paper-trade -> validate -> live small size. Confirms the abstraction layer actually works on a real second asset. | Phase 1 |
| 3 — Expand Commodities | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-03-expand-commodities_PLAN_05-07-26.md` | Expand to all remaining major MCX commodities (gold, silver, natural gas, copper, base metals) using the Phase 2 pattern; per-commodity parameter + risk profiles; per-commodity liquidity gate before going live. | Phase 1 + Phase 2 |
| 4 — Currency | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-04-currency_PLAN_05-07-26.md` | Add NSE currency derivatives (USDINR etc.) — should be nearly config-only given the abstraction from Phase 1; confirm NSE_CD lot-size/session/expiry config; paper -> live small. | Phase 1 (Phase 2/3 provide the onboarding pattern but are not a hard blocking dependency for currency) |

### Join Conditions

- Phase 1 MUST NOT start until Phase 0 exit gate passes (phase plans exist, charter locked).
- Phase 2 MUST NOT start until Phase 1 exit gate passes (abstraction layer live, NIFTY regression green).
- Phase 3 MUST NOT start until Phase 1 AND Phase 2 exit gates both pass (pattern proven on Crude Oil).
- Phase 4 MUST NOT start until Phase 1 exit gate passes; Phase 4 SHOULD start after Phase 3 in
  practice (reuses the onboarding pattern and keeps regression surface area smaller), but is not
  hard-blocked by Phase 3 if the team wants currency sooner.

---

## Per-Phase Entry / Exit Gates

| Phase | Entry | Exit gate |
|---|---|---|
| 0 | Program start | Feature folder + 4 phase plan files created; charter locked; Stable Program Goal block emitted |
| 1 | Phase 0 complete | Asset-class config registry exists and is the single source of truth for exchange/sessions/symbol-format/lot-size-source/expiry-cycle/volatility-measure/risk-config; all 27 hard-coded market-hour checks route through one session manager; hard-exit is per-asset; lot-size fetch covers NSE_FO + MCX_COM + NSE_CD symbol masters; India-VIX calls are behind a per-asset volatility interface with an ATR-based fallback for non-index assets; NIFTY regression checkpoint green (paper + live-parity smoke); validate-contract PASS or accepted CONDITIONAL; zero new tradable assets introduced |
| 2 | Phase 1 exit met | MCX Crude Oil options: symbols/lots/expiry/sessions resolve correctly via the registry; reused strategies run with crude-tuned params; at least 1 commodity-specific strategy live in paper; ≥1 full paper-trading session across crude's session hours recorded with results; explicit go/no-go for live-small recorded in phase report; if go — live-small trades executed and monitored with no order/risk anomalies; NIFTY regression checkpoint green; validate-contract PASS or accepted CONDITIONAL |
| 3 | Phases 1+2 exit met | All target MCX commodities (gold, silver, natural gas, copper, base metals) onboarded with per-commodity parameter + risk profiles; per-commodity liquidity check recorded (thin-book commodities flagged and either descoped from live or given tighter live-size limits); paper-trading pass per new commodity before its live-small; NIFTY + Crude Oil regression checkpoints both green; validate-contract PASS or accepted CONDITIONAL |
| 4 | Phase 1 exit met (Phase 3 recommended complete first) | NSE currency derivatives (USDINR et al.) onboarded via config-only changes (no new abstraction-layer code needed, or any needed gap is documented and small); paper-trading pass recorded; live-small go/no-go recorded; NIFTY + prior-commodity regression checkpoints green; validate-contract PASS or accepted CONDITIONAL |

---

## Per-Phase Loop

Each phase executes the canonical 7-step inner loop `R → I → P → PVL → E → EVL → UP`. This inner
loop SKIPS SPEC — SPEC ran once for this program (this umbrella plan captures the locked scope),
not per phase. The 7 steps map to:

1. **RESEARCH** — spawn research-agent: load context (`process/context/all-context.md` +
   `process/context/tests/all-tests.md` routing chain), read prior phase reports, re-audit the
   named hard-coded surfaces (market-hours, hard-exit scheduler, India-VIX call sites, "NSE:"
   symbol prefixes, `fetch_lot_sizes.py`) for drift since this plan was written, document findings.
2. **INNOVATE** — spawn innovate-agent: decide the concrete abstraction/config shape for this
   phase's scope; write Decision Summary (chosen approach + rejected alternatives + risk predictions).
3. **PLAN-SUPPLEMENT** — spawn plan-agent: if research/innovate found gaps/pre-conditions not in
   the phase checklist, add them; otherwise mark "n/a — research clean" and tick step 3.
4. **PVL** — spawn vc-validate-agent: full V1-V7; validate-contract written per
   `.claude/skills/vc-validate-findings/references/example-validate-output.md` format (Status /
   Gate / Plan updates applied / Execute-agent instructions / Test gates / High-risk pack /
   Backlog artifacts / Known gaps / Accepted by). MUST include the NIFTY regression checkpoint as
   an explicit gate for every phase, and (Phases 2-4) the new-asset paper-trading-before-live gate.
5. **EXECUTE** — spawn vc-execute-agent per approved plan and validate-contract.
6. **EVL** — spawn vc-tester: run phase test gates to green, INCLUDING the NIFTY regression smoke;
   register follow-up stubs; write EVL HANDOFF SUMMARY.
7. **UPDATE-PROCESS** — write phase report to durable report path, rewrite umbrella
   `## Current Execution State` section (overwrite, not append — git history is the audit log),
   commit execution changes via vc-git-manager before the next phase starts.

**PVL is NEVER skipped.** A placeholder `## Validate Contract` = blocked. Do not spawn
execute-agent while the Validate Contract section reads
"(placeholder — vc-validate-agent writes this section before EXECUTE)".

---

## Autonomous Execution Rules (During /goal)

During /goal execution of this phase program:
- Agent self-decides at all V5 gates — no user approval needed between phases, EXCEPT the hard
  stops listed in the Stable Program Goal block above (live-order-before-paper-trading,
  NIFTY-regression-fail, thin-liquidity-commodity-going-live).
- CONDITIONAL net gate: proceed autonomously, fixes applied in-flight, gaps on record.
- BLOCKED net gate: document items in backlog, continue with remaining phase plans where the
  blocker doesn't hard-depend on the blocked item; backlog is always a valid resolution.
- Hard stops (must pause for user approval):
  - Any live order placement on a new asset class before a completed paper-trading pass is on record
  - NIFTY regression checkpoint fails on any phase's commit
  - Irreversible/outward-facing action without explicit contract instruction (push to remote,
    deploy to production, live order placement not covered by the validate-contract)
  - Plan file explicitly marks "pause required" at a step
  - A commodity flagged thin/illiquid is about to go live without a documented tighter-limits decision
- Agent writes phase reports, updates phase plans, creates new sub-plans as needed — all autonomously.
- The phase report is the communication channel for conflicts, errors, and learnings — not inline questions.

---

## Global Constraints

- NIFTY/equity index-options trading must never regress. Every phase runs a NIFTY regression
  checkpoint (paper-trading smoke + relevant automated tests) against the same commit before that
  phase is marked VERIFIED.
- Never hard-code a new asset's market hours, hard-exit time, symbol prefix, or volatility source
  outside the Phase 1 abstraction registry — that registry is the single source of truth from
  Phase 1 onward. Any code added in Phases 2-4 that reintroduces a hard-coded asset assumption is
  a regression of Phase 1's purpose and must be fixed before that phase's exit gate.
- Never place a live order on a new asset class without a completed, recorded paper-trading pass.
- Per-asset risk config (SL, position sizing, max exposure) is mandatory and must be explicit —
  never inherit NIFTY's numeric defaults by omission.
- After every phase that touches shared runtime files (`app.py`, `state.py`,
  `engine/automation.py`, `engine/ws_feed.py`, `fetch_lot_sizes.py`), run the NIFTY regression
  checkpoint and confirm it passes before declaring the phase DONE.
- Commit each phase's execution changes before starting the next phase. Keep process/plan/context
  commits separate from execution commits (per repo's existing commit-hygiene convention — commit
  directly on `main`, no feature branch, per CLAUDE.md §Commit Hygiene override).
- Do not widen Fyers credential scope or touch existing Session/Trust-Boundary auth patterns as
  part of this program — those are out of scope and covered by the completed security-remediation program.

---

## Durable Report Destinations

| Phase | Report path (inside task folder) |
|---|---|
| 0 (pre-program) | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-00-program-kickoff_REPORT_05-07-26.md` |
| 1 — Asset Abstraction Layer | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-01-asset-abstraction-layer_REPORT_{dd-mm-yy}.md` |
| 2 — Onboard Crude Oil | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-02-onboard-crude_REPORT_{dd-mm-yy}.md` |
| 3 — Expand Commodities | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-03-expand-commodities_REPORT_{dd-mm-yy}.md` |
| 4 — Currency | `process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-04-currency_REPORT_{dd-mm-yy}.md` |

Phase blast-radius registry (for the phase-plan-creation agent team coordination token protocol):
`process/features/multi-asset-expansion/active/multi-asset_05-07-26/phase-blast-radius-registry.md`

---

## Program Status Table

| Phase | Status |
|---|---|
| 0 — Pre-program (umbrella + charter) | 🔨 CODE DONE (this document) |
| 01 — Asset Abstraction Layer | ⏳ PLANNED |
| 02 — Onboard Crude Oil | ⏳ PLANNED |
| 03 — Expand Commodities | ⏳ PLANNED |
| 04 — Currency | ⏳ PLANNED |

Status values: ⏳ PLANNED | 🔨 CODE DONE | 🧪 TESTING | ✅ VERIFIED | 🚧 BLOCKED | ✅ COMPLETE

---

## Touchpoints

- `trading-app/app.py` — market-hour checks, symbol handling, hard-exit scheduler, session-aware routing
- `trading-app/state.py` — TradingState / asset-class-aware state shape
- `trading-app/engine/automation.py` — automation loop, per-asset session gating
- `trading-app/engine/ws_feed.py` — websocket feed, exchange-aware subscriptions, VIX dependency site
- `trading-app/engine/strategy_swing.py` — market-hours dependency site
- `trading-app/engine/strategy_orb.py`, `strategy_wisdom.py`, `strategy_9.py` (or equivalent 9-strategy files) — VIX dependency sites needing per-asset volatility abstraction
- `trading-app/ai_engine*` — VIX dependency site
- `trading-app/auto_trader*`, `regime_worker*`, `market_worker*` — VIX dependency sites
- `trading-app/fetch_lot_sizes.py` — extend to MCX_COM + NSE_CD symbol masters
- `trading-app/workers/*` — any background worker iterating hard-coded NIFTY/NSE assumptions
- New: an asset-class config/registry module (exact path/name decided in Phase 1 INNOVATE)
- New: a centralized session-hours manager (exact path/name decided in Phase 1 INNOVATE)
- `static/*` — any UI surfaces that need an asset-class selector (minimal, per Global Constraints scope note)

---

## Public Contracts

- Existing NIFTY-only behavior (routes, automation loop timing, UI flows) must remain
  byte-for-byte functionally unchanged for NIFTY users after every phase.
- Fyers API integration contract (`fyers_client.py` auth/caching pattern) is unchanged — new asset
  classes use the same Fyers client, just different symbol/exchange parameters.
- Database schema (`models.py`) additions must be additive only (new columns/tables for asset
  class, no destructive migration of existing NIFTY-scoped rows) unless a phase's validate-contract
  explicitly documents and gates a migration.
- Existing admin/user dashboard routes and API response shapes remain unchanged for NIFTY;
  any new asset-class UI surface is additive.

---

## Blast Radius

Files directly modified or created (exact set finalized per-phase in each phase plan's own Blast
Radius section; program-level expected surface):

- 27 hard-coded market-hour check sites across `app.py`, `state.py`, `engine/automation.py`,
  `engine/ws_feed.py`, `engine/strategy_swing.py` (Phase 1)
- 1 hard-exit scheduler (15:14 equity-specific) → made per-asset (Phase 1)
- 9 files with India-VIX dependency: `ai_engine`, `signals`, `strategy_orb`, `strategy_wisdom`,
  `strategy_9`, `auto_trader`, `ws_feed`, `regime_worker`, `market_worker` → per-asset volatility
  abstraction (Phase 1, consumed by Phases 2-4)
- 125 hard-coded "NSE:" symbol-prefix sites → exchange-aware symbol builder (Phase 1)
- `fetch_lot_sizes.py` — add MCX_COM + NSE_CD downloads (Phase 1)
- 165 total NIFTY references across the codebase — audited in Phase 1 RESEARCH, addressed
  incrementally as each site is touched by Phases 1-4 (not all 165 need to change; only sites that
  encode a NIFTY/equity-only assumption)
- New asset-class config registry + session manager modules (Phase 1, new files)
- Crude Oil onboarding wiring — symbol/lot/expiry/session config entries + 1-2 new
  commodity-specific strategy files (Phase 2)
- Per-commodity config entries for gold/silver/natgas/copper/base-metals (Phase 3)
- NSE currency derivative config entries (Phase 4)
- Risk class: HIGH — this program touches live trading automation, order placement, and a
  currently-live-with-real-money system (NIFTY). Every phase requires the NIFTY regression gate.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| NIFTY regression checkpoint (paper-trading smoke + existing automated tests) run on every phase's commit | Hybrid | "NIFTY/equity trading must NEVER regress" hard safety constraint |
| Asset-class config registry unit tests (exchange/sessions/symbol-format/lot-size-source/expiry-cycle/volatility-measure/risk-config resolve correctly per asset) | Fully-Automated | Phase 1 exit gate: registry is single source of truth |
| Session-hours manager returns correct open/close/hard-exit per asset class (NIFTY 9:15-15:30 w/ 15:14 exit; MCX 9:00-23:30; currency 9:00-17:00) | Fully-Automated | Phase 1 exit gate: centralized session manager |
| Lot-size fetch pulls MCX_COM + NSE_CD symbol masters alongside existing NSE_FO | Hybrid (live Fyers call, precondition: Fyers auth available) | Phase 1 exit gate: lot-size source extension |
| Per-asset volatility fallback (ATR-based) used when India-VIX unavailable (non-index assets) | Fully-Automated | Phase 1 exit gate: India-VIX abstraction |
| Crude Oil paper-trading session across full MCX session hours (9:00-23:30) with no session/lot/expiry resolution errors | Agent-Probe | Phase 2 exit gate: paper-trading-before-live |
| Crude Oil live-small trade monitoring — no order/risk anomalies over a defined observation window | Agent-Probe | Phase 2 exit gate: go/no-go recorded |
| Per-commodity liquidity check (bid/ask spread or open-interest threshold) recorded before each MCX commodity goes live in Phase 3 | Hybrid | Global Constraint: MCX liquidity risk gate |
| Currency derivative onboarding requires no new abstraction-layer code (or documents the small gap) | Fully-Automated (config diff check) | Phase 4 exit gate: config-only onboarding |
| `node .claude/skills/vc-audit-vc/scripts/validate-agent-parity.mjs` exits 0 after any harness-file changes made while executing this program | Fully-Automated | Program-level harness integrity (not a trading behavior, but required per repo convention) |

---

## Test Infra Improvement Notes

- No confirmed `pytest`/test-runner configuration was found for `trading-app/` during grounding
  reads for this program. Phase 1 RESEARCH must confirm whether any test runner exists
  (search for `pytest.ini`, `conftest.py`, `tests/` dir) before PVL can assign Fully-Automated
  tiers with real commands. Until confirmed, treat the NIFTY regression checkpoint as Hybrid
  (manual/paper-trading smoke) rather than Fully-Automated, and record this explicitly as a known
  infra gap — not a silent Known-Gap PASS.

---

## Resume and Execution Handoff

- Selected plan file path: `process/features/multi-asset-expansion/active/multi-asset_05-07-26/multi-asset-expansion-umbrella_PLAN_05-07-26.md`
- Last completed phase: Phase 0 (this umbrella plan file = Phase 0 artifact; phase plans 1-4 are
  written next, by other agents per the user's parallel-authoring instruction — coordinate via
  `phase-blast-radius-registry.md` in this same task folder)
- Validate-contract status: pending (vc-validate-agent writes per-phase; this umbrella carries only
  the placeholder below)
- Supporting context files loaded: `process/context/all-context.md`,
  `process/development-protocols/phase-programs.md`,
  `process/development-protocols/orchestration.md`,
  `.claude/skills/vc-generate-phase-program/templates/umbrella-plan-template.md`
- Next step for a fresh agent: Read this umbrella plan in full, then read
  `phase-01-asset-abstraction-layer_PLAN_05-07-26.md` (once written), then run the Phase 1 RESEARCH
  subagent before any EXECUTE work. Do not spawn vc-execute-agent for any phase until that phase's
  validate-contract shows `Gate: PASS` (or accepted CONDITIONAL with ≥1 supplement cycle).
- Current phase: Phase 0 complete (this document); Phase 1 not yet started.
- Next action: Create/confirm the 4 phase plan files (`phase-01-asset-abstraction-layer_PLAN_05-07-26.md`
  through `phase-04-currency_PLAN_05-07-26.md`) in this same task folder, then spawn Phase 1 RESEARCH.
- Execute-agent start instruction: Read this file. Read the Phase 1 plan. Run the Phase 1 research
  subagent first. Never execute against Phase 1 until its validate-contract is written and passing.

---

## Current Execution State

Last updated: 05-07-26
Completed phases: Phase 0 (Planning — this umbrella plan)
Current phase: Phase 1 (Asset Abstraction Layer)
Current loop step: RESEARCH (pending)
Validate-contract status: pending (no phase validate-contracts written yet)
Program Net Gate: PENDING
Latest validator run: 05-07-26 — not yet run (this is planning only; no execution has occurred)

Loop step values: RESEARCH | INNOVATE | PLAN-SUPPLEMENT | PVL | EXECUTE | EVL | UPDATE-PROCESS
Orchestrator rule: read "Current loop step" and "validate-contract status" before spawning any
subagent. Never spawn execute-agent when loop step is RESEARCH, INNOVATE, PLAN-SUPPLEMENT, or PVL.

Note: The Stable Program Goal above is fixed. This section is the only part that changes —
update-process-agent rewrites it after every phase closeout (overwrite, not append — git history
is the audit log).

## Pre-PVL Conflict Resolution

No package conflicts — all phases are parallel-safe. Phase plans 1-4 each own disjoint config-entry
additions layered onto the shared Phase 1 abstraction files; Phases 2-4 do not modify Phase 1's
core registry/session-manager modules once Phase 1 exits, they only add config entries and
strategy-tuning files. Re-verify this section once all 4 phase plans are drafted and their exact
Blast Radius sections can be diffed against each other.

---

## Validate Contract

(placeholder — vc-validate-agent writes this section before EXECUTE)
