---
name: plan:strategy-rebuild-phase-02-strategy3-orb
description: "Strategy Rebuild — Phase 02: Strategy 3 (5-Minute ORB) — Time-Window Widen Fix"
date: 28-08-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: phase-02
---

# Phase 02 — Strategy 3 (5-Minute ORB) — Time-Window Widen Fix

**Program:** strategy-rebuild
**Umbrella plan:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
**Phase status:** ✅ VERIFIED — full 7-step inner loop closed (R→I→P→PVL→E→EVL→UP). EXECUTE
implemented D1-D3/E1-E5 with zero plan deviations; EVL independently confirmed all gates green
(py_compile clean, 10/10 tests pass including 2 new pure-function tests, E4 code-trace
re-confirmed). Execution changes committed and pushed to `origin/main` at `ede705e` (verified:
local HEAD matches origin/main).
**Report destination:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-02-strategy3-orb_REPORT_{dd-mm-yy}.md (flat in the program task folder)

---

## Purpose

Fix the confirmed hardcoded time-window bug limiting Strategy 3 (5-Minute Opening Range Breakout)
to a 10-minute evaluation gate (`"09:20:00" <= now <= "09:30:00"`) at
`trading-app/workers/auto_trader.py:2002`, inside `eval_strat_3()`, when the underlying
`trading-app/engine/strategy_orb.py` module is designed for and self-limits to `10:30:00` (its own
expiry check at `strategy_orb.py:83`). Widen the gate to `"10:30:00"` — matching the module's own
boundary exactly, with no partial/conservative widen and no independent smaller number.

This is a **window-only fix**. `strategy_orb.py` itself and the existing one-shot-per-day trigger
flag (`state.strat_orb_triggered`) are NOT touched — the one-shot flag already independently caps
Strategy 3 to exactly 1 trade/day regardless of window width, so trade frequency cannot increase
from this widen.

---

## Entry Gate

- Phase 1 complete (validated, committed) — ✅ satisfied (`97c901c`, VERIFIED)

---

## RESEARCH Findings (locked this session)

- **Confirmed bug location:** `trading-app/workers/auto_trader.py:2002`, inside `eval_strat_3()`:
  `if "09:20:00" <= now <= "09:30:00":` is the ONLY gate controlling when Strategy 3 is evaluated
  at all. This is a hardcoded string-comparison time window, not derived from the module's own
  config.
- **Underlying module's real boundary:** `trading-app/engine/strategy_orb.py` is designed for and
  supports evaluation up to `10:30:00` — its own expiry check is at `strategy_orb.py:83`. The
  10-minute call-site gate is 60 minutes narrower than what the module itself supports.
- **No other filter is time-of-day sensitive in a way that interacts badly with widening.** Volume,
  15-minute trend, gap, range-width, and news filters inside `strategy_orb.py` are independent of
  wall-clock time; none of them assume a 10-minute evaluation window.
- **Trade frequency CANNOT increase from widening.** An independent one-shot-per-day flag —
  `state.strat_orb_triggered` — is checked at `auto_trader.py:1998` and `strategy_orb.py:64-65`, and
  reset daily in `automation.py`. This flag already caps Strategy 3 to exactly 1 trade/day
  regardless of how wide the evaluation window is. Widening the window changes WHEN a qualifying
  setup can be caught, not HOW MANY trades fire.
- **Git history confirms isolation of this bug:** commit `0816016` (23-Jul-26, widened other
  strategies' windows) never touched this call site — `auto_trader.py:2002`'s window has been
  unchanged since the initial commit. No other commit has modified it either. This is a genuinely
  isolated, never-previously-addressed bug.
- **Testability gap identified (deferred, not part of this fix):** `eval_strat_3()` has no
  injectable clock parameter, unlike `evaluate_orb_strategy()` in `strategy_orb.py` which already
  supports one. This makes `eval_strat_3()` harder to unit-test with a simulated "now" — the
  regression test in Step E below must therefore patch `datetime.now` directly rather than pass a
  parameter. See Backlog Item below.

---

## INNOVATE Decision (locked this session)

**Chosen approach:** Widen the hardcoded window in `auto_trader.py:2002` from
`"09:20:00" <= now <= "09:30:00"` to `"09:20:00" <= now <= "10:30:00"` — matching
`strategy_orb.py`'s own expiry boundary exactly. No partial/conservative widen (e.g. `"09:45:00"`
or `"10:00:00"`) was considered credible: there is no code-derived evidence for any number other
than the module's own stated boundary, so picking a smaller number would just reintroduce a second,
un-derived arbitrary cutoff.

**Rejected alternative — also touch `strategy_orb.py` or the one-shot-trigger flag logic:**
Rejected. The RESEARCH findings confirm the only bug is the call-site window; `strategy_orb.py`'s
own boundary and the one-shot flag are both already correct and working as designed. Touching them
would widen this phase's blast radius for zero benefit and risk introducing a real behavior change
(e.g. accidentally allowing >1 trade/day) into a phase that should be a pure window fix.

**Rejected alternative — bundle the clock-injection testability fix into this phase:** Rejected.
Adding an optional `now` parameter to `eval_strat_3()` (matching `evaluate_orb_strategy()`'s
existing pattern) would touch the signature of a live-trading eval function for a fix this small.
The window bug can be regression-tested via `datetime.now` monkeypatching without this change.
Bundling risks scope creep on a live-trading code path; the clock-injection gap is deferred to
backlog as an explicitly-scoped follow-up (see Backlog Item below), not silently dropped.

---

## Backlog Item (recorded, explicitly deferred — not silently done)

**Clock-injection testability gap for `eval_strat_3()`.** `eval_strat_3()` in
`trading-app/workers/auto_trader.py` has no injectable `now`/clock parameter, unlike
`evaluate_orb_strategy()` in `trading-app/engine/strategy_orb.py`, which already supports one. This
makes `eval_strat_3()` harder to unit-test with a simulated time (requires `datetime.now`
monkeypatching instead of a direct parameter). Recommended follow-up: add an optional `now: datetime
| None = None` parameter to `eval_strat_3()` mirroring `evaluate_orb_strategy()`'s pattern, defaulting
to `datetime.now(IST)` when not supplied. This phase does NOT implement this — it is deferred to a
future backlog item or a future phase-program follow-up, to be raised explicitly during UPDATE
PROCESS for this phase (create a backlog note under
`process/features/strategy-rebuild/backlog/` if not otherwise absorbed by a later phase).

---

## Blast Radius

- `trading-app/workers/auto_trader.py` — `eval_strat_3()`'s single line at (currently) line 2002:
  `if "09:20:00" <= now <= "09:30:00":`, plus one new module-level pure helper function
  (`_strat3_orb_window_ok`) added near the existing module-level helpers (e.g. `_strat_enabled_for`
  at ~line 188). No other function signature, call site, or behavior changes.
- Read-only (confirmed correct, not modified): `trading-app/engine/strategy_orb.py` — expiry check
  (`strategy_orb.py:83`), one-shot trigger check (`strategy_orb.py:64-65`)
- Read-only (confirmed correct, not modified): `state.strat_orb_triggered` daily reset logic in
  `trading-app/engine/automation.py`
- New/updated: existing pytest suite covering `eval_strat_3()` / Strategy 3 ORB dispatch (additive —
  new regression tests)

---

## Implementation Checklist

### Step A — RESEARCH (complete this session)

- [x] A1. Confirm exact bug location and mechanism at `auto_trader.py:2002` — done, see RESEARCH
      Findings above.
- [x] A2. Confirm `strategy_orb.py`'s own boundary (`10:30:00`, `strategy_orb.py:83`) as the correct
      widen target — done.
- [x] A3. Confirm no other filter interacts badly with widening (volume/trend/gap/range/news) —
      done, none are time-of-day sensitive.
- [x] A4. Confirm trade frequency cannot increase — done, `state.strat_orb_triggered` one-shot flag
      independently caps at 1 trade/day (`auto_trader.py:1998`, `strategy_orb.py:64-65`).
- [x] A5. Confirm git history isolation — done, commit `0816016` never touched this call site; no
      other commit has either.
- [x] A6. Identify the clock-injection testability gap on `eval_strat_3()` — done, recorded as a
      Backlog Item above, explicitly deferred.

### Step B — INNOVATE (complete this session)

- [x] B1. Decide fix approach: widen to `"10:30:00"` exactly, matching `strategy_orb.py`'s own
      boundary — done, see INNOVATE Decision above.
- [x] B2. Reject bundling `strategy_orb.py` / one-shot-flag changes into this phase — done.
- [x] B3. Reject bundling the clock-injection fix into this phase; defer to backlog — done.

### Step C — PLAN-SUPPLEMENT (this task)

- [x] C1. Flesh out this stub into a full checklist with concrete file/line references and locked
      RESEARCH/INNOVATE findings — done (this document).

### Step D — Apply the window-widen fix

**[PVL-SUPPLEMENT, this cycle] Resolution to VALIDATE's Open Gap (test coverage CONCERN):**
VALIDATE found `eval_strat_3()` is a non-exported closure nested inside `automation_loop()`
(`auto_trader.py:1996`, defined inside the loop starting at `:1928`, called only at its own
`asyncio.gather` site `~:2429`) — it is not independently callable, so the plan's original
"call `eval_strat_3(client, state, u_id)` directly from a test" design (Steps E2-E4) cannot work
at all, regardless of the datetime-patch question. VALIDATE offered two options (Option A: drive
`automation_loop()` for one mocked tick; Option B: reclassify E2-E4 to Agent-Probe). Neither is
used as-is. Instead: **extract the pure time-window comparison into a small module-level function**
— this is the codebase's own established pattern for making closure-internal logic unit-testable
without touching production risk (`_is_fade_strategy` / `_strat_enabled_for` at
`auto_trader.py:65`/`:188` are both already module-level, non-closure helpers called from inside
`eval_strat_3()`'s sibling closures, and `_is_fade_strategy` is already directly imported and
tested in `trading-app/tests/test_anti_chase_fade.py`: `from workers.auto_trader import
_is_fade_strategy, _is_chase_entry`). This is materially smaller blast radius than Option A (no
`automation_loop()` harness, no mocking `USER_CONTEXTS`/`asyncio.gather`/`asyncio.sleep`) and keeps
genuine Fully-Automated, deterministic proof — improving on Option B, which would drop to
Agent-Probe for no structural reason once this precedent is available.

- [ ] D1. In `trading-app/workers/auto_trader.py`, add a new **module-level** (not nested — placed
      alongside the other module-level pure helpers such as `_strat_enabled_for` at line ~188, NOT
      inside `automation_loop()` or `eval_strat_3()`) pure function:
      ```python
      def _strat3_orb_window_ok(now_str: str) -> bool:
          # Strategy 3 (5-Min ORB) evaluation window check -- pure, no side effects, no I/O.
          # Matches strategy_orb.py's own 10:30:00 expiry boundary exactly (see strategy_orb.py:83).
          # Extracted so the window-widen fix is unit-testable without driving automation_loop().
          return "09:20:00" <= now_str <= "10:30:00"
      ```
      **Before editing, re-confirm the exact current line number** of the module-level helper
      block (currently ~line 188, `_strat_enabled_for`) — do not assume it is still exact if code
      has drifted since this session's research.
- [ ] D2. Inside `eval_strat_3()`, change the hardcoded window comparison at (currently) line 2002
      from `if "09:20:00" <= now <= "09:30:00":` to `if _strat3_orb_window_ok(now):`. This is
      behaviorally identical to widening the inline literal to `"10:30:00"` — the extracted
      function's body is exactly that widened comparison, so this is still a pure window-widen with
      zero behavior change beyond the fix itself. **Before editing, re-confirm the exact current
      line number** by grepping for the literal string `09:20:00` in `auto_trader.py` — do not
      assume line 2002 is still exact.
- [ ] D3. Do NOT modify `strategy_orb.py`, the one-shot-trigger flag logic, `eval_strat_3()`'s
      signature, or any other filter — out of scope per the INNOVATE decision. The extraction in
      D1/D2 does not change `eval_strat_3()`'s signature, call site, or any behavior other than
      relocating the literal comparison into a named, independently-callable function.

### Step E — Test coverage (regression-proofing)

- [ ] E1. Confirm `_strat3_orb_window_ok` is importable as
      `from workers.auto_trader import _strat3_orb_window_ok` (module resolves as `workers.auto_trader`
      per `trading-app/tests/conftest.py`'s `sys.path` setup — NOT `trading_app.workers.auto_trader`,
      which does not exist; `trading-app/` is not a valid Python package name). **No datetime
      monkeypatching is needed for E2/E3** — the extracted function takes a plain `now_str` argument,
      so tests pass literal time strings directly. (The datetime-patch technical note is preserved
      for the record: `eval_strat_3()` does `from datetime import datetime` locally inside the
      function, at line 1999 inside its `try:` block, not the module-level `datetime` imported at
      `auto_trader.py:16` — a local import re-fetches `datetime.datetime` fresh from
      `sys.modules["datetime"]` on every call, so any future test that DOES need to patch real
      wall-clock time in this closure must patch the global `unittest.mock.patch("datetime.datetime")`
      target, not a module-attribute path like `workers.auto_trader.datetime`, which the local
      import would silently shadow. Not required for E2/E3/E5 since they call the pure function
      directly with literal strings; recorded here so a future clock-injection follow-up does not
      repeat this investigation.)
- [ ] E2. Add a new unit test (Fully-Automated, pure function, no mocking): call
      `_strat3_orb_window_ok("09:45:00")` and `_strat3_orb_window_ok("10:15:00")` (later-in-window
      times that were previously rejected by the old 10-minute gate) and assert both return `True` —
      proves the window-widen bug is fixed.
- [ ] E3. Add a new unit test (Fully-Automated, pure function, no mocking): call
      `_strat3_orb_window_ok("09:15:00")` and `_strat3_orb_window_ok("10:35:00")` (just outside each
      boundary) and assert both return `False`; additionally assert `_strat3_orb_window_ok("09:20:00")`
      and `_strat3_orb_window_ok("10:30:00")` (inclusive boundaries) both return `True` — proves
      boundary discipline is preserved and matches `strategy_orb.py`'s own `10:30:00` expiry exactly.
- [ ] E4. **Reclassified to Agent-Probe / documented-judgment, not a new runtime test.** The
      one-shot-flag safety claim (widening the window cannot increase trade count) is already
      independently proven by this plan's own validate-contract (see "Independent verification...
      item 2" in the `## Validate Contract` section below): a complete code-trace of
      `state.strat_orb_triggered`'s full lifecycle across `auto_trader.py`, `strategy_orb.py`, and
      `automation.py` shows both read-gates occur strictly before signal generation and the single
      write occurs strictly after trade execution, independent of window width. Building a runtime
      test for this would require driving `automation_loop()` (VALIDATE's Option A) purely to
      re-prove a claim already established by exhaustive code-reading — disproportionate for a
      single-line, git-history-isolated fix, consistent with INNOVATE's minimal-blast-radius
      philosophy. E4's proof is: (a) this documented code-trace, plus (b) E5's existing regression
      suite continuing to pass (confirms no accidental disturbance of the one-shot flag's own
      module, `strategy_orb.py`, which E5 already covers). No new test file/function is added for E4.
- [ ] E5. Run the full existing test suite covering Strategy 3 / ORB dispatch to confirm no
      regression in already-passing behavior (e.g. pre-`09:20:00` and post-`10:30:00` rejection,
      which already existed before the fix and must continue to hold).

---

## Exit Gate

```bash
# Compile check
python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/strategy_orb.py
# Expected: exit 0, no output

# Regression test suite (existing + new)
pytest trading-app/ -k "strat_3 or strategy3 or orb or eval_strat_3 or strat3_orb_window"
# Expected: all pass, including the new _strat3_orb_window_ok unit tests (Step E2/E3, pure-function,
# no mocking) and the existing E5 regression suite. E4 is documented judgment (code-trace), not a
# pytest node -- see Step E4.
```

- All checklist items (A-E) checked
- No FAIL in py_compile or the regression test suite
- The new pure-function unit tests in Step E (E2, E3) are the sole automated proof of the
  window-widen fix; E4's one-shot safety claim is proof by documented code-trace (already completed
  in this plan's `## Validate Contract` section, item 2), not a new runtime test -- see Step E4 for
  the explicit rationale.
- `backtest_runner.py` is NOT a required gate command for this phase — it remains a known-gap per
  the umbrella's Test Infra Improvement Notes (no CLI entrypoint, needs live Fyers client). Do not
  re-discover this gap; reference the umbrella's existing note.
- Backlog item (clock-injection testability gap) recorded in the phase report, explicitly deferred
- Phase report written to report destination above

---

## Blockers That Would Justify BLOCKED Status

- The exact current line number/content at `auto_trader.py:2002` has drifted materially from the
  RESEARCH findings above (e.g. `eval_strat_3()` has been restructured) and the fix target cannot be
  confidently identified without a fresh RESEARCH pass — re-run RESEARCH before proceeding.
- Step E1's confirmation of the `datetime.now` import/namespace reveals a materially different
  patch target than expected, and the monkeypatch approach in E2-E4 needs redesign.
- A regression is found in Step E5 indicating the widen interacts badly with a filter not
  identified in RESEARCH — requires a fresh audit before proceeding to fix.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: prior phase report read (Phase 1); confirmed bug location,
      mechanism, module boundary, no adverse filter interaction, no frequency-increase risk, git
      history isolation, and identified the clock-injection testability gap (Step A)
- [x] 2. INNOVATE — innovate-agent: widen-to-`10:30:00` approach decided; bundling rejections
      documented; Decision Summary written (Step B)
- [x] 3. PLAN-SUPPLEMENT — plan-agent: this stub fleshed out into a full checklist with concrete
      file/line references and locked RESEARCH/INNOVATE findings (Step C, this document)
- [x] 4. PVL — vc-validate-agent: full V1-V7 (cycle 2 re-validation); validate-contract written per
      `.claude/skills/vc-validate-findings/references/example-validate-output.md`; Gate: PASS
- [x] 5. EXECUTE — all checklist items (D, E) done; per-section test gates run and green — zero
      plan deviations (see phase report)
- [x] 6. EVL — all EVL gates green; follow-up stubs registered (clock-injection backlog item); EVL
      independently re-confirmed py_compile clean and 10/10 tests pass
- [x] 7. UPDATE PROCESS — phase report written (including the backlog item), umbrella state
      updated, commit done (`ede705e`, verified local HEAD == origin/main)

**Validate-contract required before execute.** If step 4 (PVL) is unchecked or `## Validate
Contract` reads "(placeholder — vc-validate-agent writes this section before EXECUTE)",
orchestrator must spawn vc-validate-agent first.

---

## Touchpoints

- `trading-app/workers/auto_trader.py` — new module-level pure helper `_strat3_orb_window_ok()`
  (placed alongside existing module-level helpers such as `_strat_enabled_for`), plus the one-line
  call-site change inside `eval_strat_3()` to use it
- Existing pytest test file(s) covering Strategy 3 / ORB dispatch logic (new pure-function unit
  tests added for `_strat3_orb_window_ok`, following the `test_anti_chase_fade.py` precedent of
  directly importing module-level helpers from `workers.auto_trader`)

---

## Public Contracts

- No external API surface change — this is internal automation-loop logic only.
- Strategy 3's core entry/exit intent is unchanged — this is a pure evaluation-window widen, not a
  change to the ORB pattern, trend/volume/gap/range/news filters, or the one-shot-per-day cap.
- Strategy 3's daily trade cap (1 trade/day via `state.strat_orb_triggered`) remains unchanged;
  the safety claim is proven by documented code-trace (validate-contract item 2), not a new test
  (Step E4 reclassified to Agent-Probe/documented-judgment per PVL-supplement — see Step D/E).
- New module-level function `_strat3_orb_window_ok()` is an internal-only pure helper (no I/O, no
  side effects) — it is not a new public/external contract, mirroring the existing internal-only
  status of `_strat_enabled_for` and `_is_fade_strategy`.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| `python3 -m py_compile` on `auto_trader.py` and `strategy_orb.py` | Fully-Automated | Fix does not introduce a syntax/compile error |
| New unit test: `_strat3_orb_window_ok("09:45:00")` / `("10:15:00")` return `True` | Fully-Automated | The window-widen bug is fixed — Strategy 3's window check now admits signals later in the widened window |
| New unit test: `_strat3_orb_window_ok("09:15:00")` / `("10:35:00")` return `False`; `("09:20:00")` / `("10:30:00")` return `True` | Fully-Automated | Boundary discipline preserved — widen matches `strategy_orb.py`'s own `10:30:00` boundary exactly, no over-widen, inclusive-boundary correctness |
| One-shot-flag safety claim: documented code-trace of `state.strat_orb_triggered` lifecycle (this plan's `## Validate Contract`, item 2) | Agent-Probe (documented judgment, PVL-supplement reclassification — see Step E4) | The one-shot-per-day flag independently caps trade frequency — widening the window cannot increase trade count |
| Existing pytest suite for Strategy 3 / ORB dispatch | Fully-Automated | No regression in already-correct pre-09:20/post-10:30 rejection behavior |

```bash
# Verification command — run after phase complete
git log --oneline -1 -- trading-app/workers/auto_trader.py
# Expected: shows this phase's commit (window-widen fix)
```

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-02-strategy3-orb_PLAN_28-08-26.md`
- Last completed step: Step 4 PVL (cycle 2) — full V1-V7 re-validation, Gate: PASS
- Validate-contract status: written — PASS (cycle 2, `generated-by: inner-pvl: phase-2`,
  supersedes cycle 1's CONDITIONAL contract)
- Supporting context files loaded: `process/context/all-context.md`,
  `process/development-protocols/phase-programs.md`,
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-01-strategy1-obfvg_PLAN_28-08-26.md`
  (as the sibling reference for phase-plan fleshing depth/format)
- Next step: Spawn vc-execute-agent for Step 5 EXECUTE — implement Steps D1-D3 and E1-E5 exactly as
  written in this plan (extract `_strat3_orb_window_ok()`, update the call site, add the E2/E3 pure
  unit tests, run the E5 regression suite).

---

## Test Infra Improvement Notes

- Backlog: `eval_strat_3()` lacks an injectable clock parameter (unlike `evaluate_orb_strategy()`
  in `strategy_orb.py`, which already has one). Regression tests in Step E must monkeypatch
  `datetime.now` directly instead of injecting a simulated time — more brittle than a parameterized
  approach. Recommended follow-up: add optional `now: datetime | None = None` parameter to
  `eval_strat_3()` mirroring `evaluate_orb_strategy()`'s existing pattern, deferred to backlog (see
  Backlog Item section above), not bundled into this fix.
- `backtest_runner.py` remains a known-gap (no CLI entrypoint, needs live Fyers client) per the
  umbrella's Test Infra Improvement Notes — not re-discovered as a new gap here.

---

## Validate Contract

Status: PASS
Date: 28-08-26
date: 2026-08-28
generated-by: inner-pvl: phase-2
supersedes: 2026-08-28 (inner-pvl: phase-2) — PVL cycle 2; the cycle-1 CONDITIONAL contract's sole
headline gap (Test coverage — E2-E4 non-executable as originally written) was resolved by a
plan-supplement extracting a new module-level pure function `_strat3_orb_window_ok()`; every
material claim in the resolution was independently re-verified against live code (not just plan
prose) — see V1/V3 below.

Parallel strategy: sequential
Rationale: Signal count 1/7 (single-file source change; no schema/auth/API/billing surface; no new
dependencies) — a single-agent sequential pass covers V2 fully; parallel fan-out would cost more
agents than the investigation warrants. Unchanged from cycle 1.

**V1 pre-check results (cycle 2 — fresh re-scan, not reused from cycle 1):**
- Plan file path confirmed readable. All referenced file paths confirmed to exist on disk.
- **Line-number claim RE-VERIFIED, unchanged since cycle 1:** `grep -n "09:20:00\|09:30:00"
  trading-app/workers/auto_trader.py` returns exactly one hit, line 2002:
  `if "09:20:00" <= now <= "09:30:00":`. No drift since cycle 1 — EXECUTE should still re-grep per
  D1/D2's own "re-confirm before editing" instruction as a matter of discipline.
- `eval_strat_3()` re-confirmed still a non-exported closure nested inside `automation_loop()`:
  `def automation_loop():` at line 1928, `async def eval_strat_3(client, state, u_id):` at line
  1996, sole call site inside `automation_loop()`'s own `asyncio.gather` block at line 2429. This
  re-confirms cycle 1's finding still holds (EXECUTE has not yet run — the extraction is still
  pending, exactly as expected at this point in the loop).
- Module-level pure-helper precedent re-confirmed on live code: `_is_fade_strategy` (line 65) and
  `_strat_enabled_for` (line 188) are both genuinely module-level (not nested inside
  `automation_loop()` or any closure) and both import cleanly:
  `from workers.auto_trader import _is_fade_strategy, _strat_enabled_for` succeeds at runtime
  (verified via direct `python3 -c` import in the `trading-app/` working directory, matching the
  `sys.path` setup `conftest.py` gives every test). `test_anti_chase_fade.py:10` independently
  confirms the same import pattern is already live in the test suite:
  `from workers.auto_trader import _is_fade_strategy, _is_chase_entry`.
- `now` variable type re-confirmed at the call site (line 1999-2000, inside `eval_strat_3`'s `try:`
  block): `now = datetime.now(IST).strftime("%H:%M:%S")` — a plain zero-padded `"HH:MM:SS"` string,
  identical in shape to what the original inline literal comparison operated on. This directly
  answers the orchestrator's Question 2 (see Independent Verification item 1 below).
- `## Inner Loop Refresh Note` not present as a separate section — the plan-supplement was applied
  directly in-place to Step D/E and the Open Gaps entry (marked `[RESOLVED by this PVL-supplement
  cycle]`), which is how this program's inner PVL loop has been operating (matches Phase 1's cycle-2
  pattern of applying the supplement directly into the existing checklist rather than via a
  separate note section).
- No `## Phase Ordering` or `## Pre-PVL Conflict Resolution` sections present — not applicable.
- Existing `## Validate Contract` (cycle 1, CONDITIONAL) present — this write REPLACES it per the
  Inner PVL overwrite rule; `supersedes:` recorded above.
- Structural validator re-run (mandatory, 3b):
  `node .claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs <this-plan>` →
  **2 failures, 3 warnings** (down from 6 failures in cycle 1 — the supplement's added content
  satisfied 4 of the prior structural expectations). The remaining 2 failures (missing
  overview/context section header, missing Complexity metadata field) are the exact same kind, and
  the exact same count, as Phase 1's own contract — which reached `Gate: PASS` while carrying this
  identical finding class and did not even list it under Infra fit in its final dimension findings.
  Following that precedent directly (see Dimension findings below): this is a purely cosmetic
  plan-shape/documentation-metadata gap with zero functional, dependency, schema, auth, API, or
  billing surface implication — it does not block Infra fit PASS.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| exit-gate-compile | Fix does not introduce a syntax/compile error | Fully-Automated | `python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/strategy_orb.py` | A |
| verification-evidence-row-2 (E2) | Window-widen bug fixed — Strategy 3 evaluates a qualifying signal later in the window (e.g. 09:45, 10:15) | Fully-Automated | `_strat3_orb_window_ok("09:45:00")` and `_strat3_orb_window_ok("10:15:00")` both return `True` — pure function, zero mocking, directly importable (import path independently re-verified live, see V1 above) | A |
| verification-evidence-row-3 (E3) | Boundary discipline preserved — no signal before 09:20 or after 10:30; inclusive boundaries hold | Fully-Automated | `_strat3_orb_window_ok("09:15:00")` / `("10:35:00")` → `False`; `("09:20:00")` / `("10:30:00")` → `True` — matches `strategy_orb.py`'s own `> "10:30:00"` expiry check (line ~85), independently re-read: 10:30:00 itself is not expired, i.e. inclusive, consistent with this test | A |
| verification-evidence-row-4 (E4) | One-shot-per-day flag independently caps trade count even with multiple qualifying signals across the widened window | Agent-Probe (documented code-trace, reclassified from Fully-Automated by this PVL-supplement cycle — see Independent Verification item 3 below for why this is sound, not a rigor downgrade) | Exhaustive lifecycle trace of `state.strat_orb_triggered` across `auto_trader.py`, `strategy_orb.py`, `automation.py`, `risk_orchestrator.py` (documented in Independent Verification item 3) plus E5's continued-pass confirmation that the flag's own module is undisturbed | A |
| verification-evidence-row-5 (E5) | No regression in already-correct pre-09:20/post-10:30 rejection behavior | Fully-Automated | `pytest trading-app/ -k "strat_3 or strategy3 or orb or eval_strat_3 or strat3_orb_window"` — re-confirmed non-vacuous THIS session: `pytest --collect-only` on the current filter collects exactly 8 real tests (not 0), matching cycle 1's claim exactly, no drift | A |

gap-resolution legend: A — proven now. B — fixed in this plan's checklist. C — deferred to a named
later phase/plan. D — backlog test-building stub.

All five gate rows are now gap-resolution `A` (proven now) — cycle 1's `B` rows (E2-E4, "fixed in
this plan's checklist... via the required supplement cycle") have graduated to `A` because the
supplement that fixes them is now written into Steps D1/D2/E1-E5 above and every material claim in
it has been independently re-verified against live code in this cycle (not merely re-read as plan
prose). The cycle-1 failing stub for E2/E3/E4 is superseded — E2/E3 are now real, non-blocked
Fully-Automated pure-function tests (see Step E2/E3 above and the plan's own inline test code); E4
is Agent-Probe by design, not by blockage, so no failing stub applies to it (Agent-Probe rows do not
receive stubs per this agent's Inline Failing Stub rule).

Dimension findings:
- Infra fit: PASS — structural plan-artifact validator improved to 2 failures (down from 6),
  identical in kind and count to Phase 1's own PASS'd contract, which did not treat this finding
  class as blocking. No new runtime surface, dependency, schema, auth, API, or billing surface
  introduced by the fix or by the extraction of `_strat3_orb_window_ok()`.
- Test coverage: PASS (was the headline CONCERN in cycle 1, now closed) — E2/E3/E5 are genuine
  Fully-Automated pure-function/regression gates, independently re-verified importable and
  non-vacuous this session; E4 is Agent-Probe by sound, disclosed design choice (see item 3 below),
  not a coverage hole.
- Breaking changes: PASS — no public API/contract change; internal automation-loop logic only;
  `eval_strat_3()`'s signature untouched; Strategy 3's entry/exit intent, filters, and
  one-shot-per-day cap are all unchanged (re-asserted, not altered). The new
  `_strat3_orb_window_ok()` function is an internal-only pure helper, mirroring
  `_strat_enabled_for`'s and `_is_fade_strategy`'s existing internal-only status (re-confirmed live:
  neither is imported or referenced anywhere outside `trading-app/`).
- Security surface: PASS — no auth, secrets, billing, migration, or public-API surface touched.
- Step D/E feasibility (Layer 2, single-section plan): Step D (one-line call-site edit + one new
  ~6-line pure helper) is mechanically trivial and fully feasible — confirmed exact current
  line/content, confirmed the extraction pattern already has two live precedents in this exact
  file. Step E as now written (E1-E5) is fully feasible — confirmed via direct import test, direct
  pytest collection count, and direct source read of the `now` variable's type.

**Independent verification of the three items the orchestrator specifically asked to confirm
(cycle 2 — each re-checked against live code this session, not reasoned from plan prose alone):**

1. **Scope growth — CONFIRMED genuine growth, judged appropriately scoped.** EXECUTE will now (a)
   add a new ~6-line module-level pure function and (b) change one call-site line to use it, versus
   the original plan's single literal-value edit. This is judged **appropriately scoped, not a
   phase-boundary violation**, on four independent grounds, each re-verified live: (i) it is already
   explicitly named in this plan's own Blast Radius and Touchpoints sections — not a silent
   expansion discovered at EXECUTE time; (ii) it is small in absolute terms (~6 lines, one function,
   zero new files, zero new imports beyond what the module already imports); (iii) it follows an
   established, already-live pattern in the exact same file — `_strat_enabled_for` (line 188) and
   `_is_fade_strategy` (line 65) are both pre-existing module-level pure helpers extracted from the
   same kind of closure-heavy dispatch code, and `_is_fade_strategy` is already directly unit-tested
   via this identical import technique in `test_anti_chase_fade.py` (re-confirmed importable this
   session), so this is reuse of a proven pattern, not a novel one; (iv) it does not touch
   `eval_strat_3()`'s signature, call-site arity, or any other strategy's code — blast radius stays
   confined to `auto_trader.py`. Net: a slightly larger touchpoint than the original one-line plan,
   correctly flagged as such in-plan, does not warrant returning to PLAN or re-scoping the phase.

2. **Behavioral equivalence — CONFIRMED, extraction does not change what counts as "in window."**
   Direct source read this session at `auto_trader.py:1999-2002` shows
   `now = datetime.now(IST).strftime("%H:%M:%S")` — a plain zero-padded `"HH:MM:SS"` string — is
   what the original inline comparison `"09:20:00" <= now <= "09:30:00"` operates on. The plan's
   replacement function, `return "09:20:00" <= now_str <= "10:30:00"`, uses the **identical
   comparison operators** (`<=` inclusive at both ends) against the **identical string format**,
   with only the upper literal changed from `"09:30:00"` to `"10:30:00"`. This is byte-for-byte the
   same widen that would result from editing the inline literal directly — the extraction changes
   *where* the comparison lives, not *what* it computes. Cross-checked against
   `strategy_orb.py`'s own boundary logic (re-read this session, `if current_time_str >
   "10:30:00":` → expired): `10:30:00` itself is NOT expired under that check, i.e. inclusive —
   exactly matching the new function's `<= "10:30:00"` and confirming E3's inclusive-boundary
   assertion (`_strat3_orb_window_ok("10:30:00")` → `True`) is correct, not an off-by-one.

3. **E4 Agent-Probe reclassification — CONFIRMED legitimate, not a rigor downgrade.** The
   underlying safety property this reclassification relies on (item "2. One-shot-flag safety claim"
   below) is a complete, line-referenced trace of `state.strat_orb_triggered`'s lifecycle across
   four files, establishing that both read-gates occur strictly before signal generation and the
   single write occurs strictly after trade execution — an ordering property that is **completely
   orthogonal to whether the window comparison is written inline or wrapped in a named pure
   function returning the same boolean for the same input.** Extracting `_strat3_orb_window_ok()`
   cannot change this ordering, because the function is a drop-in behavioral replacement (see item
   2 above) — it does not touch the flag, the gates, or the write site at all. The trace was a real,
   specific, exhaustive code investigation with file:line citations (not a hand-wave), it was
   produced independently of this reclassification decision (in cycle 1, before the supplement was
   even proposed), and it is further corroborated by E5's continued pass (re-confirmed this session:
   `pytest --collect-only` on the E5 filter still collects exactly 8 tests, unchanged, meaning
   `strategy_orb.py`'s own module — which owns one of the two read-gates — remains undisturbed).
   This satisfies the bar for a sound Agent-Probe classification (backed by real completed
   evidence) rather than a bar-lowering shortcut to avoid writing a test.

**Cycle-1 investigation record (retained for audit trail — findings unchanged, re-confirmed above):**

1. **Monkeypatch viability — CONFIRMED NOT VIABLE AS WRITTEN, worse than the plan anticipated.**
   The plan's own Step E1 flags patch-target ambiguity and offers
   `unittest.mock.patch("trading_app.workers.auto_trader.datetime")` as an example. That example
   is wrong on two independent grounds and would silently fail to patch anything:
   (a) **Module path is wrong.** `trading-app/` is not a valid Python package name (hyphen); the
   test suite's own `conftest.py` adds `trading-app/` itself to `sys.path`, so the module imports
   as `workers.auto_trader`, never `trading_app.workers.auto_trader`. That attribute path does
   not exist — patching it would raise `ModuleNotFoundError` at collection time, not silently pass.
   (b) **More seriously: `eval_strat_3()` is a nested closure defined INSIDE `automation_loop()`
   (auto_trader.py:1996, nested inside the `while True:` loop worker starting at :1928), never
   bound at module level and never exported.** `grep -n "eval_strat_3\b" auto_trader.py` returns
   exactly 2 hits: the `def` at :1996 and its one call site inside `automation_loop()`'s own
   `asyncio.gather` block at :2429. There is no `from workers.auto_trader import eval_strat_3` —
   that name does not exist on the module. The plan's entire Step E design (`eval_strat_3(client,
   state, u_id)` called directly from a test file) will fail at the very first line with an
   `ImportError`/`AttributeError`, before the datetime-patch question is even reached. This is a
   more fundamental gap than the one RESEARCH identified (RESEARCH found the *missing clock
   parameter*; VALIDATE additionally finds the function is *not independently callable at all*).
   Confirmed systemic, not Strategy-3-specific: none of `eval_strat_3`'s sibling nested evaluators
   (`eval_strat_2`, `eval_strat_5`, `eval_symbol_strats`, `run_strat_4`, `run_strat_6`) are tested
   directly anywhere in `trading-app/tests/` either — this whole dispatch-function family shares
   the same architecture and the same gap.
   Separately, on the datetime-patch question itself (needed once the callability problem above is
   resolved): `eval_strat_3()` does `from datetime import datetime` **locally inside the function**
   (line 1999, inside the `try:` block) rather than referencing the module-level `datetime` name
   already imported at auto_trader.py:16. A local import re-fetches `datetime.datetime` fresh from
   `sys.modules["datetime"]` on every call, so patching any module-level attribute (e.g.
   `workers.auto_trader.datetime`, following this codebase's own convention in
   `test_strategy_runtime_fixes.py`'s `patch("engine.strategy_orb.datetime")`) would have **zero
   effect** — the local import always shadows it. The verified-correct target is the global
   `unittest.mock.patch("datetime.datetime")` (patching the stdlib module's own attribute, which
   the local import reads at call time), with `.now.return_value` set to a real localized
   `datetime` object (matching the existing test suite's own pattern of setting a real value on
   `.now.return_value`, not a bare Mock).

2. **One-shot-flag safety claim — INDEPENDENTLY CONFIRMED, no scenario found where widening
   increases trade count.** Traced the complete lifecycle of `state.strat_orb_triggered`: init
   `False` (automation.py:136) → loaded from persisted disk state (automation.py:251) → read-gated
   at TWO independent checkpoints before any trade can be proposed (`auto_trader.py:1998`, the
   call-site gate now being widened; and `strategy_orb.py:64`, inside the strategy module itself,
   "Strictly 1 trade today") → set `True` exactly once, only AFTER a Strategy-3 trade actually
   executes (`risk_orchestrator.py:165`, inside the post-execution dispatch, gated on
   `s_name == "Strategy 3"`) → persisted (automation.py:398) → reset to `False` only in the daily
   reset block (automation.py:527, alongside Strategy 1/2/4/6's own per-day counters). Both read
   gates occur strictly *before* any signal is generated, and the single write happens strictly
   *after* the one qualifying trade completes — this ordering is independent of how wide the
   evaluation window is. Widening from 10 to 70 minutes only changes *which* wall-clock moments
   can observe a qualifying setup; it cannot change how many times the flag is legitimately
   written per day. No adverse interaction found. (A theoretical concurrent-tick race in
   `risk_orchestrator`'s cross-strategy winner-selection is a pre-existing property of the
   orchestration design, identical regardless of window width — out of scope for this fix's
   safety claim and not introduced or worsened by it.)

3. **Umbrella hard-safety-constraint framing — CONFIRMED, holds up.** The umbrella's Program Goal
   Charter states the fix must not alter "the strategy's core intended behavior (behavior changes
   require explicit user sign-off)" and elsewhere: "Bug fixes are silent-ok within phase scope;
   behavior changes requir[e] explicit user sign-off." This phase's own Public Contracts section
   ("Strategy 3's core entry/exit intent is unchanged... a pure evaluation-window widen, not a
   change to the ORB pattern... or the one-shot-per-day cap") matches that framing exactly: the
   fix restores the call site to the module's own already-designed, already-shipped boundary
   (`strategy_orb.py:83`'s `10:30:00` expiry check, which the call site was arbitrarily gating 60
   minutes narrower than), rather than introducing any new entry/exit/filter/cap logic. This is a
   bug fix under the umbrella's own definition, not a behavior change requiring sign-off.

Open gaps:
- **[Test coverage, CONCERN, CLOSED this cycle]** Cycle 1 found Steps E2/E3/E4 as originally written
  called `eval_strat_3(client, state, u_id)` directly, but that name is a non-exported closure
  nested inside `automation_loop()` — this would have failed at import/call. The PVL-supplement
  applied between cycle 1 and this cycle extracted the pure time-window comparison into a new
  module-level function `_strat3_orb_window_ok()`, following this codebase's own established
  precedent for closure-internal logic. This cycle independently re-verified (not merely re-read)
  every load-bearing claim in that resolution: the function's importability precedent (live import
  test), the `now` variable's type and the comparison's behavioral equivalence (source read), the
  E5 regression suite's continued non-vacuous pass (pytest --collect-only), and the E4 Agent-Probe
  classification's soundness (see Independent Verification items 2-3 above). No residual concern
  remains open on this dimension.
- **[Infra fit, non-blocking, precedented]** Structural plan-artifact validator now reports 2
  failures (down from 6 in cycle 1) — identical in kind and count to Phase 1's own PASS'd contract,
  which did not treat this finding class as blocking Infra fit. No action required.
- backtest_runner.py: known-gap: documented as NEW PLAN REQUIRED — not re-discovered here, per the
  umbrella's existing Test Infra Improvement Notes (no CLI entrypoint, needs live Fyers client).
- Clock-injection testability gap on `eval_strat_3()`: known-gap, already explicitly recorded in
  this plan's own Backlog Item section, deferred to a future phase/backlog note. Note: this gap is
  now smaller in practice than originally scoped — E2/E3 no longer need `datetime.now` monkeypatching
  at all (they call `_strat3_orb_window_ok()` directly with literal strings), so the backlog item's
  remaining value is limited to any *future* test that needs to simulate real wall-clock time inside
  `eval_strat_3()` itself, not to this phase's own gates.

What this coverage does NOT prove:
- `python3 -m py_compile` proves only syntactic validity — it does not prove the window logic is
  correct or that the one-shot flag holds (those are proven by the E2/E3 and E4 rows respectively).
- The existing `-k "... or orb or eval_strat_3"` filter's pre-fix 8 collected tests exercise
  `evaluate_orb_strategy()` and the shared `orb_filters.py` helpers, not `eval_strat_3()`'s own
  call-site window gate directly — E2/E3 (new, targeting `_strat3_orb_window_ok()` directly) are
  what close that specific gap; E5 alone would not have.
- E4's one-shot-flag safety claim is proven by documented code-trace (Agent-Probe), not by a new
  runtime test — this is a deliberate, disclosed design choice (see Independent Verification item 3
  above), not an unproven gap, but it is still not the same evidentiary strength as a passing
  pytest node and should be re-examined if `risk_orchestrator.py`'s winner-selection logic ever
  changes.
- Manual/live monitoring window (per the umbrella's "what verified means") is out of scope for
  this validate-contract and tracked at the program level, same as Phase 1.

Gate: PASS (no FAILs, no unresolved CONCERNs — cycle 1's sole headline CONCERN, test-plan
executability, is closed this cycle with independently re-verified evidence; the remaining Infra-fit
structural-validator finding is precedented non-blocking per Phase 1 and does not rise to an
unresolved CONCERN)
Accepted by: n/a — PASS gate, no CONDITIONAL concerns requiring explicit acceptance.
