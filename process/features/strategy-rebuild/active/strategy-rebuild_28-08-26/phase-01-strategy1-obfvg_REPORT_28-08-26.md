---
phase: phase-01-strategy1-obfvg
date: 2026-08-28
status: COMPLETE_WITH_GAPS
feature: strategy-rebuild
plan: process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_PLAN_28-08-26.md
---

# Phase 01 EXECUTE Report — Strategy 1 (OB+FVG) Name-Collision Fix + Entry-Logic Audit

**TL;DR** — The 3-call-site name-collision bug is fixed in `trading-app/engine/automation.py` and
locked behind 13 new regression tests (confirmed red before the fix, green after). The OB/FVG audit
found **no further structural bug**, but surfaced 2 non-blocking observations (one dead-code branch,
one comment/code mismatch) that are NOT fixed here because they touch core entry logic and need user
sign-off. `STRAT1_CONFLUENCE_ONLY` was NOT flipped. The Step F backtest gate could not run
(known-gap — `backtest_runner.py` has no CLI entrypoint and needs a live broker client).

---

## What Was Done

### Step A — Fresh audit (A1–A4, A3b)

**A1/A2 — bug confirmed, line numbers re-verified against live code.** Repo-wide grep for
`startswith("Strategy 1")` in `trading-app/` returned exactly 2 literal call sites (no 4th site):

| Call site | Line (pre-fix) | Mechanism |
|---|---|---|
| `can_trade()` Strategy-1 daily cap | 728 | `str(strategy_name).startswith("Strategy 1")` — also True for "Strategy 10:…"/"Strategy 11:…" |
| `add_active_trade()` counter increment | 987 | `str(strategy).startswith("Strategy 1")` — same |
| `has_active_trade_for_strategy()` | 660–667 | bidirectional `startswith` on `.split(":")[0]` — matched both directions across S1/S10/S11 |

Confirmed impact: **both** failure modes are real. S10/S11 activity (a) falsely blocked Strategy 1's
active-trade guard, and (b) inflated `strat_1_trades_today`, exhausting Strategy 1's 2/day cap; and
symmetrically Strategy 1 falsely blocked S10/S11 via the same cap and guard.

**A3 — OB/FVG entry-logic audit (`signals.py`, `order_blocks.py`, `fvg.py`, all read in full).**
No further structural bug found that would render Strategy 1 dead. Detection chain verified sound:
`detect_order_blocks()` → `_check_mitigation()` → `get_active_order_blocks()`; `detect_fvg()` (with
C++ native fast path + Python fallback) → `_check_fvg_fill()` → `get_active_fvg()`;
`find_ob_fvg_confluence()`; then `detect_retest_and_rejection()` (liquidity-sweep + rejection-candle)
gating signal emission at `signals.py:228`.

Two **observations** recorded, deliberately NOT fixed (see § Flagged For User Sign-Off):
1. `signals.py:223` — `if setup.get("score", 0) < 80: continue` is **dead code**. No setup dict in
   `all_setups` carries a `"score"` key (OBs carry `impulse_strength`, confluences carry
   `confluence_score`), so `.get("score", 0)` is always `0` and the condition is always true. Net
   effect: the documented "skip counter-trend setups *unless it's a very strong OB*" escape hatch
   never fires — **all** counter-trend setups are skipped unconditionally.
2. `signals.py:208–210` — the comment justifying `STRAT1_CONFLUENCE_ONLY = False` claims standalone
   setups are admitted with "higher confidence thresholds (>70)". No such threshold exists in code:
   confidence is computed as `min(95, 60 + trend_strength/5)` (+15 at a key level) and is never
   gated. The stated mitigation for loosening the filter was never implemented.

**A3b — `STRAT1_CONFLUENCE_ONLY` explicitly re-examined.** Confirmed at `signals.py:211`, value
`False`. The in-code history matches the plan's hypothesis: it was flipped from `True` because
confluence-only "produced zero signals for a week", and that dead week overlaps the phantom-expiry
bug window and this phase's collision bug — so the zero-signal period is plausibly explained by
those bugs rather than by confluence-only being genuinely worse. Combined with observation (2)
above (the compensating confidence gate was never built), there is a **credible case for reverting
to `True`**, but reverting is a core entry-intent change. Per the umbrella's hard safety constraint
and the plan's explicit A3b instruction, **the flag was NOT changed.** Flagged for sign-off.

### Step B — Fix approach (B1–B3)

**Decision Summary.** Chosen: colon-anchor the 2 literal call sites (`"Strategy 1:"`) and replace
the bidirectional `startswith` in `has_active_trade_for_strategy()` with exact equality on
`.split(":")[0].strip()`. Rationale: minimal blast radius, no new dependency, and it can only ever
*narrow* matching — a strictly safer direction on a live-money system.

Rejected alternatives:
- **Regex (`^Strategy 1\b`)** — same effect, higher cost: adds an `re` compile in a hot per-tick
  path and is harder to read/audit than a string compare.
- **Dict-keyed lookup by numeric strategy ID** — structurally the cleanest long-term design, but
  requires touching every strategy-name producer across the engine and workers. Far outside a
  bug-fix phase's blast radius; noted as a possible later refactor.

**B2** — the two OB/FVG findings are classified **observation / needs-sign-off**, not
silently-fixable bugs. No entry-logic change applied (Step D3 = no-op by design).

### Step D — Fix applied

`trading-app/engine/automation.py`, 3 call sites (all with dated inline comments explaining the bug):
- `has_active_trade_for_strategy()` — bidirectional `startswith` → exact match on the split ID.
  `"Strategy 1"` still matches `"Strategy 1: OB + FVG"`; `"Strategy 10"` no longer does.
- `can_trade()` line 733 — `startswith("Strategy 1:")`.
- `add_active_trade()` line 994 — `startswith("Strategy 1:")`.

No changes to `signals.py`, `order_blocks.py`, `fvg.py` (verified via `git status`).

### Step E — Test coverage

`trading-app/tests/test_trading_core.py` — 13 new tests appended in one block, covering **all 3**
call sites (E2 + E2b):
- `has_active_trade_for_strategy()`: 6 cross-block cases (S10→S1, S11→S1, S1→S10, S1→S11, S10↔S11)
  assert `False`; 3 same-strategy cases assert `True` (guard still works); 2 bare-ID cases assert
  `"Strategy 1"` ↔ `"Strategy 1: OB + FVG"` still match.
- `can_trade()`: S10 and S11 are NOT blocked with `strat_1_trades_today=99`; S1 IS still blocked at
  its cap of 2.
- `add_active_trade()`: S10/S11 entries do NOT increment `strat_1_trades_today`; an S1 entry does.

**Red-first confirmed (Mode A).** With the fix reverted, 8 of the new tests failed; with the fix
applied, all pass. This is the sole proof of the collision fix.

### Step G — Backlog note closed

`process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` marked
**SUPERSEDED (28-08-26)**, pointing at this report, and stating the finding: no shared Strategies-1-7
dispatch bug; the actual root cause was the narrower S1/10/11 collision (plus the already-fixed
phantom-expiry bug), with per-strategy follow-ups carried by this program's Phases 02–14.

---

## What Was Skipped or Deferred

- **Step F1/F2 (backtest pre/post run)** — KNOWN-GAP, see below. Plan checkboxes left unticked.
- **Any change to `STRAT1_CONFLUENCE_ONLY` or other core entry logic** — out of scope by explicit
  instruction; flagged for sign-off instead.
- No changes to `sl_guardian.py`, `hindsight_optimizer_worker.py`, or other strategies' files.

---

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| py_compile (4 engine files) | `python3 -m py_compile trading-app/engine/{automation,signals,order_blocks,fvg}.py` | **PASS** — exit 0, no output |
| New + existing core suite | `python3 -m pytest tests/test_trading_core.py -q` (cwd `trading-app/`) | **PASS** — 34 passed |
| Widened plan gate | `python3 -m pytest tests/ -q -k "active_trade or can_trade or add_active_trade or strategy1 or strategy_1"` | **PASS** — 24 passed, 150 deselected |
| Red-first confirmation | same suite with fix reverted | **8 failed, 5 passed** (expected red) |
| Backtest (Step F) | `python3 engine/backtest_runner.py --strategy "Strategy 1: OB + FVG"` | **KNOWN-GAP — not runnable** (see below) |

**Backtest known-gap detail.** `trading-app/engine/backtest_runner.py` has **no `__main__` block, no
`argparse`, and no CLI arg handling** — it is a library module exposing
`async backtest_strategy(strategy_name, real_client, days_back)`, which requires a live Fyers client
for historical candles. Running the plan's Exit Gate command is a silent no-op (imports the module,
exits 0, prints nothing) — it is not a real gate. This matches the plan's pre-declared blocker
("`backtest_runner.py` cannot run … missing data dependency … document as a known-gap, do not block
the phase"). Materiality is low: this gate was only ever meant to prove the OB/FVG *audit* outcome
and S10/11 non-regression, and **zero** lines of `signals.py`/`order_blocks.py`/`fvg.py` were
changed, so there is nothing for it to regress against. The collision fix is proven solely by the
E2/E2b unit tests, exactly as the validate-contract states.

---

## Flagged For User Sign-Off (NOT changed — core entry-logic intent)

1. **`STRAT1_CONFLUENCE_ONLY = False` (`signals.py:211`)** — recommend reconsidering a revert to
   `True`. The reason it was flipped ("zero signals for a week") is plausibly attributable to the
   phantom-expiry bug and/or this phase's collision bug, both now fixed. Its stated compensating
   safeguard (a >70 confidence gate) was never implemented. Backtest evidence in the same comment
   block favours confluence-only (win rate 14.7% → 54.8%, max DD −348 → −68 pts).
2. **Dead counter-trend escape hatch (`signals.py:223`)** — `setup.get("score", 0)` never resolves;
   either populate a `score` key or delete the branch. Behaviour-affecting either way.

Both are recorded as candidates for Phase 14 (shared gate stack) or a dedicated follow-up, at the
user's discretion.

---

## Plan Deviations

None functional. Two in-plan documentation edits made as instructed:
- `## Verification Evidence` backtest row reworded to match the corrected Step F3 / Exit Gate
  language (was still claiming the backtest proves the collision fix).
- Checklist ticked; F1/F2 left unticked with an inline `KNOWN-GAP` marker rather than falsely ticked.

---

## Test Infra Gaps Found

- `CONTEXT_PARTIAL: tests` — `process/context/tests/all-tests.md` is still the unfilled vc-setup
  template (routing table is commented-out placeholders). Test commands were derived from the
  validate-contract and direct inspection instead.
- `backtest_runner.py` has no CLI entrypoint, so no phase in this program can use it as an automated
  gate as currently written. Follow-up options: add an `argparse __main__` with a recorded-candle
  fixture, or reclassify every backtest gate in Phases 02–14 as agent-probe/known-gap.

---

## Closeout Packet

- **Selected plan:** `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_PLAN_28-08-26.md`
- **Finished:** Steps A, B, C, D, E, G in full; F3 (documented understanding) done.
- **Verified:** py_compile green; 34/34 core tests green; 24/24 widened gate green; red-first proven.
- **Unverified:** Step F backtest (known-gap); live/paper monitoring window (5 days / 10 signals per
  the umbrella's "what verified means") — not started, tracked at program level.
- **Remaining:** independent EVL confirmation run (vc-tester), then commit. **Not committed** per
  instruction.
- **Classification:** `Keep in active/testing` — EVL + live monitoring still pending.

---

## Forward Preview

**Test Infra Found** — `trading-app/tests/test_trading_core.py` is the right home for
automation.py-level regression tests; `make_state()` builds a side-effect-free `TradingState` via
`__new__` and stubs `has_active_trade_for_strategy` (delete the stub attribute to exercise the real
method). `add_active_trade()` needs `st.save` stubbed and
`engine.automation.trigger_webhook_background` monkeypatched. Run tests with cwd `trading-app/`
(conftest handles `sys.path`); `PYTHONPATH=.` is required for direct `engine/*.py` script runs.

**Blast Radius Changes** — `trading-app/engine/automation.py` line numbers shifted +5 after the fix
(`can_trade` S1 cap now 733, `add_active_trade` counter now 994). Later phases quoting automation.py
line numbers should re-grep, not trust stale numbers.

**Commands to Stay Green** —
`python3 -m py_compile trading-app/engine/automation.py` and, from `trading-app/`,
`python3 -m pytest tests/test_trading_core.py -q` (expect 34 passed).

**Dependency Changes** — none. No new imports, packages, or runtime surfaces.

---

## Files Touched

| File | Change |
|---|---|
| `trading-app/engine/automation.py` | 3 call sites fixed (collision) + dated comments |
| `trading-app/tests/test_trading_core.py` | +13 regression tests (all 3 call sites) |
| `process/general-plans/backlog/zero-trade-strategies-1-7_NOTE_11-08-26.md` | marked SUPERSEDED |
| `process/features/.../phase-01-strategy1-obfvg_PLAN_28-08-26.md` | checklist ticked, status updated, Verification Evidence backtest row corrected |
| `process/features/.../phase-01-strategy1-obfvg_REPORT_28-08-26.md` | this report (new) |
