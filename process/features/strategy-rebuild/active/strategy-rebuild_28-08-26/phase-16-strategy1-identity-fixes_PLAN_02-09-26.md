---
name: plan:strategy-rebuild-phase-16-strategy1-identity-fixes
description: "strategy-rebuild — Phase 16: fix Strategy 1's two strategy-name identity bugs (bare-string daily-cap bypass in run_strat_1, and substring-collision directional guard misidentifying Strategy 10/11 as Strategy 1) surfaced by Phase 15's PVL sweep"
date: 02-09-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: phase-16
---

# Phase 16 — Strategy 1 Identity Fixes (Daily-Cap Bypass + Substring Collision)

**Program:** strategy-rebuild
**Umbrella plan:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
**Phase status:** 🚧 IN PROGRESS (RESEARCH + INNOVATE + PLAN + PVL complete — Gate: PASS after 1
validate-fix loop; ready for EXECUTE)
**Report destination:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-16-strategy1-identity-fixes_REPORT_{dd-mm-yy}.md (flat in the program task folder, written at UPDATE PROCESS)

**Insertion note:** This phase was discovered during Phase 15's PVL cycle-2 independent
re-verification sweep (01-09-26) and flagged in the umbrella as a `## HIGH-PRIORITY Open Item` —
not routine backlog. It directly concerns whether Phase 1's already-shipped, already-✅-VERIFIED fix
(`97c901c`) actually covers the real live call path end-to-end, or only a narrower/different one its
own 34 tests exercised. This session ran a dedicated debugger investigation confirming both bugs
exhaustively (see RESEARCH findings below) and locked the fix approach (INNOVATE). It is numbered 16
and appended to the existing flat program task folder — it does not replace or renumber Phases 1-15.
Per the umbrella's own recommendation, this runs in parallel with (not blocking) Phase 4's resume,
since the two touch entirely disjoint files (`automation.py`/`auto_trader.py` here vs
`strategy_wisdom.py` for Phase 4).

---

## Purpose

Two independent, pre-existing bugs live on Strategy 1's real production call path inside
`trading-app/workers/auto_trader.py`, both confirmed unrelated to and unaffected by Phase 1's own
shipped fix or Phase 15's shipped fix:

1. **Daily-cap bypass (dead code).** `run_strat_1()` calls `state.can_trade("Strategy 1", ...)` at
   `auto_trader.py:2153` using a bare string. `engine/automation.py:733`'s cap-check gate (added by
   Phase 1's fix, `97c901c`) requires `.startswith("Strategy 1:")` (with colon). The bare string
   never matches, so Strategy 1's 2-trades/day cap has **never fired** via this call path. The sibling
   call two lines later (`auto_trader.py:2165`, `propose_trade("Strategy 1: OB + FVG", ...)`,
   already fixed by Phase 15) proves the two literals had already drifted apart inside the same
   function — the exact structural hazard this phase's fix eliminates.
2. **Substring-collision directional guard.** `auto_trader.py:1190`: `if "Strategy 1" in
   strategy_name:` inside a directional-consistency guard (CALL/PUT vs trend; bare `return`, no
   logging on mismatch). `strategy_name` for Strategy 10 is `"Strategy 10: Adaptive ADX Engine"` and
   for Strategy 11 is `"Strategy 11: FRVP LVN Vacuum"` — both contain `"Strategy 1"` as a literal
   substring, so this branch silently executes for every Strategy 10/11 trade, misidentifying them
   as Strategy 1. Currently dormant/harmless **by coincidence** (Strategy 10's trend label is always
   `"TRENDY"`/`"CHOPPY"`, Strategy 11's direction/type are always pre-aligned) — not fixed, just
   lucky. This is the same bug class Phase 1 already fixed once in `automation.py`
   (`has_active_trade_for_strategy()`), reoccurring here because `auto_trader.py:1190` was outside
   Phase 1's declared Blast Radius.

Phase 1's own regression test (`test_trading_core.py:86-95`, `test_strategy1_daily_cap`) called
`can_trade("Strategy 1: OB + FVG", ...)` — the CORRECT full-name format — which is why it passed
despite the real call site being broken with a bare string. This mirrors the exact test-design
failure mode Phase 15 already learned from once (a hand-constructed "string I think gets passed"
test can pass while the real call site is broken); this phase's test design is built specifically to
not repeat it a second time.

---

## Entry Gate

- Umbrella `## HIGH-PRIORITY Open Item` flagged this for investigation before or in parallel with
  Phase 4's resume.
- This session's dedicated debugger investigation (exhaustive, evidence-first) confirmed both bugs
  and their scope — see RESEARCH Findings below.
- No dependency on Phases 1-15 being complete beyond Phase 1 and Phase 15 themselves already having
  shipped (both are ✅ VERIFIED) — this phase touches only `auto_trader.py`'s own call sites, not
  `automation.py` or `risk_orchestrator.py`'s internals.

---

## RESEARCH Findings (confirmed, exhaustive debugger investigation — Step 1, complete this session)

1. **Bug 1 — `auto_trader.py:2153`** (inside `run_strat_1()`): `state.can_trade("Strategy 1", ...)` —
   bare string, no colon. `automation.py:733`'s gate requires `.startswith("Strategy 1:")`. Bare
   `"Strategy 1"` never matches → `can_trade()`'s cap-check branch for Strategy 1 is dead code; the
   2-trades/day cap has never fired via this call path. The counter itself
   (`state.strat_1_trades_today`) DOES correctly increment elsewhere (fed by the full name from
   `engine/signals.py`) — only the gate-check call site is broken, not the counter. Sibling call
   `auto_trader.py:2165` (two lines later, same function) already correctly passes
   `"Strategy 1: OB + FVG"` to `propose_trade()` (fixed by Phase 15, `e9c6d63`) — confirming two
   independent string literals for the same logical value existed in the same function.
2. **Bug 2 — `auto_trader.py:1190`**: `if "Strategy 1" in strategy_name:` — substring containment
   inside a directional-consistency guard (CALL/PUT vs trend, bare `return` on mismatch, no
   logging). Fires for every Strategy 10 (`"Strategy 10: Adaptive ADX Engine"`) and Strategy 11
   (`"Strategy 11: FRVP LVN Vacuum"`) trade, misidentifying them as Strategy 1. Currently
   dormant/harmless by coincidence only (Strategy 10's trend label space and Strategy 11's
   direction/type are always pre-aligned today) — not a safe design, just lucky so far. Same bug
   class Phase 1 fixed in `automation.py`, reoccurring in `auto_trader.py` outside Phase 1's
   declared Blast Radius.
3. Phase 1's own test `test_trading_core.py:86-95` (`test_strategy1_daily_cap`) called
   `can_trade("Strategy 1: OB + FVG", ...)` (correct full-name format) — passed despite the real
   call site being broken with a bare string. This is the critical lesson driving this phase's test
   design (Step C below): a hand-constructed "string I think gets passed" test is not sufficient
   proof; the test must exercise the REAL call site.

---

## INNOVATE Decision (confirmed this session — PLAN-SUPPLEMENT should not re-litigate; RESEARCH's
findings above are final and do not need re-confirmation before EXECUTE begins)

1. **Bug 1 fix.** Hoist a single local variable (e.g. `strat_name = "Strategy 1: OB + FVG"`) at the
   top of `run_strat_1()`'s trade-attempt block, and use that SAME variable for BOTH the
   `can_trade()` call (currently `auto_trader.py:2153`) and the `propose_trade()` call (currently
   `auto_trader.py:2165`). This eliminates the two-independent-literals structural hazard
   permanently — not just today's instance — rather than patching one string in isolation, which
   would leave the same class of drift possible again on the next edit.
2. **Bug 2 fix.** Replace `auto_trader.py:1190`'s substring check with the exact-match-on-split
   pattern already proven twice in this codebase (`automation.py:654-670`
   `has_active_trade_for_strategy()`, Phase 1; `risk_orchestrator.py`'s
   `_get_agent_config()` normalization retry, Phase 15):
   `strategy_name.split(":")[0].strip() == "Strategy 1"`. Apply the pattern locally at this ONE
   call site only.
   - **Explicitly OUT of scope (decided this session, do not do it in this phase):** extracting a
     shared cross-file helper function for this comparison pattern. Flagged as a separate backlog
     item (scope creep) — three independent call sites now use the same hand-written pattern
     (`automation.py`, `risk_orchestrator.py`, and this phase's `auto_trader.py` fix); a shared
     helper would reduce future drift risk but is a refactor, not a bug fix, and would widen this
     phase's Blast Radius beyond "fix two identified bugs."
   - **Explicitly an OPEN QUESTION, not decided here:** whether Strategy 1 should have this
     directional-consistency guard at all. This phase does NOT redesign or remove the guard — it
     only makes the guard correctly identify Strategy 1 (vs. Strategy 10/11) when it does fire.
     Record as an open design question in this plan's Open Questions section, not as a decision.
3. **Test approach — the deliberate point of this phase.** Both bugs must be pinned with
   INTEGRATION-style tests that exercise the REAL `run_strat_1()` / `execute_auto_trade()` code
   paths (or a minimal extracted slice containing the actual lines, if full-function mocking proves
   disproportionate), with mocked `state`/`client`/`risk_orchestrator.propose_trade`, asserting on
   the ACTUAL string passed to `can_trade()` and the ACTUAL branch outcome inside the directional
   guard at the real call sites — NOT hand-constructed "string I think gets passed" unit tests (that
   exact test design already failed once, per Phase 1's `test_strategy1_daily_cap`). Also:
   - Check whether `test_strategy1_daily_cap` becomes redundant once the new integration test
     exists, or whether it should be updated/retired so it cannot mask future divergence again.
     Decide during EXECUTE (Step C) — do not leave a stale test that could hide a future regression
     the way this one did.
   - For Bug 2: test the real directional-consistency-guard code path with real Strategy
     10/11-shaped signal dicts (not synthetic strings), confirming the fixed exact-match no longer
     misidentifies them as Strategy 1.
4. **Single phase, both bugs.** Same file (`auto_trader.py`), same root cause class (name-identity
   mismatch), same test-design lesson, no meaningful rollback-granularity benefit from splitting
   into two phases.

---

## Testability Extraction (PVL-supplement resolution — resolves SUPPLEMENT REQUEST Gap 1)

VALIDATE found Step C1's original plan ("exercise the REAL `run_strat_1()` code path") unreachable
as worded: `run_strat_1()` is a zero-arg nested closure inside `eval_symbol_strats()`, itself
nested inside `automation_loop()` — neither is a module-level name, so neither is importable or
callable from a test. VALIDATE also flagged a trap in its FALLBACK option: `get_analysis` is
imported LOCALLY inside `automation_loop()` (`from app import get_analysis` at
`auto_trader.py:1937`), not a module attribute of `auto_trader.py` — patching
`auto_trader.get_analysis` would silently no-op.

**Resolution chosen: Option 1, the PREFERRED extract-function refactor** (matching the program's
established precedent — Phase 3 extracted `_strat3_orb_window_ok()` out of a similar
closure-testability bind, and Phase 2 also chose "extract a testable pure function" over both
VALIDATE-proposed alternatives when it hit the same class of problem). No third option was found
that beats this — the extraction is simple because `run_strat_1()`'s body already depends on
nothing but its own closure variables (`symbol`, `analysis`) plus `eval_symbol_strats()`'s
parameters (`state`, `client`), and `risk_orchestrator` is already a module-level import
(`auto_trader.py:39`), so it doesn't even need to be threaded through as a parameter — this is a
cleaner extraction than the SUPPLEMENT REQUEST's own sketch anticipated.

**Concrete shape (binding for EXECUTE — see Step B1):**
- New function: `async def _strat1_attempt_trade(state, client, symbol, analysis):` — module-level,
  placed near `_strat_enabled_for` (line ~188) / `_strat3_orb_window_ok` (line ~200).
- Body: verbatim copy of the current `run_strat_1()` trade-attempt logic (lines ~2126-2166),
  unchanged in order/variables, with Bug 1's `strat_name` hoist applied inside it.
- `run_strat_1()` becomes: `async def run_strat_1(): await _strat1_attempt_trade(state, client,
  symbol, analysis)` — still exists, so `eval_symbol_strats()`'s `asyncio.gather(...)` call site
  (line ~2323) is untouched.
- Bug 2's fix (in `execute_auto_trade()`, a separate, already-module-level function) is entirely
  unaffected by this extraction — the two fixes compose cleanly because they touch different
  functions.
- This IS a small structural change beyond the original "just fix two bugs" framing — it is
  documented here, in Blast Radius, and in Touchpoints/Public Contracts below so EXECUTE and
  UPDATE PROCESS both treat it as an intentional, scoped, behavior-preserving addition, not scope
  creep or an undocumented surprise.

The FALLBACK option (driving `automation_loop()` with `app.get_analysis` monkeypatched at its
actual lookup site) is retained below only as a documented escape hatch if EXECUTE discovers the
extraction is unexpectedly unsafe (e.g. some other caller depends on `run_strat_1` being a closure
— not expected, but Step A1 should re-confirm no other reference to `run_strat_1` exists in the
file before EXECUTE relies on this). Absent such a discovery, Option 1 is the fix to implement —
EXECUTE does not need to re-litigate this choice.

---

## Blast Radius

- `trading-app/workers/auto_trader.py` — Bug 1 fix, now including a small testability-driven
  extraction resolved during PVL-supplement (see "Testability Extraction (PVL-supplement
  resolution)" below): `run_strat_1()`'s trade-attempt body is hoisted into a new module-level
  async helper `_strat1_attempt_trade(state, client, symbol, analysis)`, placed alongside the
  file's other top-level `_strat*` helpers (`_strat_enabled_for` at line ~188,
  `_strat3_orb_window_ok` at line ~200). `run_strat_1()` itself becomes a one-line wrapper. This is
  a pure behavior-preserving hoist, not a design change — same logic, same order, same variables,
  now callable from a test. Bug 1's hoisted `strat_name` local variable fix lives inside this new
  function. Bug 2 fix (replace substring check at line ~1190 with exact-match-on-split, inside the
  separate module-level `execute_auto_trade()`) is unaffected by this extraction.
- `trading-app/tests/test_trading_core.py` — evaluate whether `test_strategy1_daily_cap` needs
  updating/retiring once the new integration test supersedes it (per INNOVATE item 3)
- New or extended test file under `trading-app/tests/` (exact filename/location TBD by EXECUTE —
  likely `test_auto_trader.py` if that file already covers `run_strat_1()`/`execute_auto_trade()`
  call paths, else a new file; RESEARCH did not find zero-coverage confirmed here the way Phase 15
  found for `risk_orchestrator.py` — EXECUTE must check first)
- No changes to `trading-app/engine/automation.py` or `trading-app/engine/risk_orchestrator.py` —
  both already correctly implement the exact-match-on-split pattern this phase's Bug 2 fix reuses;
  this phase only fixes the CALLER-side identity mismatch and the CALLER-side substring check, not
  the already-correct gate/lookup implementations themselves.

---

## Implementation Checklist

### Step A — Pre-EXECUTE confirmation (re-verify RESEARCH findings from source, do not trust cache)

- [ ] A1. Re-grep `trading-app/workers/auto_trader.py` for the current exact line numbers of
  `state.can_trade("Strategy 1"` and the `propose_trade("Strategy 1: OB + FVG"` call two lines
  later inside `run_strat_1()` — confirm they are still ~2153/~2165 or record the drifted line
  numbers (per the umbrella's Test Infra Improvement Notes: never trust cached line numbers across
  phases).
- [ ] A2. Re-grep `auto_trader.py` for the current exact line number of `if "Strategy 1" in
  strategy_name:` inside `execute_auto_trade()` — confirm it is still ~1190 or record the drifted
  line number.
- [ ] A3. Confirm test coverage state: search `trading-app/tests/` for any existing test that
  exercises `run_strat_1()`'s `can_trade()` call site or `execute_auto_trade()`'s directional guard
  through the real function (not a synthetic string assertion). Confirm `test_strategy1_daily_cap`
  in `test_trading_core.py:86-95` is the only existing related test and confirm it calls
  `can_trade()` directly with a hand-constructed full-name string (per RESEARCH finding 3) rather
  than exercising `run_strat_1()` itself.

### Step B — Fix both bugs

- [ ] B1. **Extract, then fix (PVL-supplement resolution — see "Testability Extraction" section
  below for full rationale).** In `trading-app/workers/auto_trader.py`:
  1. Extract `run_strat_1()`'s entire trade-attempt body (the guard checks, the `for sig in
     analysis["signals"]:` loop, the `can_trade()` call, and the `propose_trade()` call — currently
     lines ~2126-2166) into a new module-level `async def _strat1_attempt_trade(state, client,
     symbol, analysis):` function, placed near the file's other top-level `_strat*` helpers
     (`_strat_enabled_for` at line ~188, `_strat3_orb_window_ok` at line ~200). Copy the body
     verbatim — do not alter logic, order, or variable names during the move.
     `risk_orchestrator` does NOT need to be passed as a parameter — it is already a module-level
     import (`auto_trader.py:39`, `from engine.risk_orchestrator import orchestrator as
     risk_orchestrator`) and the extracted function can reference it directly, exactly as the
     original closure body does today.
  2. Replace the body of the closure `run_strat_1()` (inside `eval_symbol_strats()`) with a
     one-line wrapper: `await _strat1_attempt_trade(state, client, symbol, analysis)`. The closure
     still exists (so the `asyncio.gather(...)` call site inside `eval_symbol_strats()` at line
     ~2323 needs no change), it just delegates to the new testable function.
  3. THEN, inside the newly extracted `_strat1_attempt_trade()`, apply Bug 1's fix: hoist a single
     local variable (e.g. `strat_name = "Strategy 1: OB + FVG"`) at the top of the trade-attempt
     block (before the `can_trade()` call). Replace the bare `"Strategy 1"` argument at the
     `can_trade()` call site with `strat_name`. Replace the existing `"Strategy 1: OB + FVG"`
     literal at the `propose_trade()` call site with the SAME `strat_name` variable (not a second
     independent literal), per INNOVATE item 1. Doing the hoist inside the extracted function
     (rather than before extraction) avoids doing the same edit twice.
- [ ] B2. In `trading-app/workers/auto_trader.py`'s `execute_auto_trade()`, replace
  `if "Strategy 1" in strategy_name:` with
  `if strategy_name.split(":")[0].strip() == "Strategy 1":` — exact-match-on-split, never
  `startswith`/`LIKE`/substring, per INNOVATE item 2. Do not touch any other logic inside this
  guard block.
- [ ] B3. Re-run `grep -n 'can_trade("Strategy 1"' trading-app/workers/auto_trader.py` and
  `grep -n '"Strategy 1" in strategy_name' trading-app/workers/auto_trader.py` after the edit to
  confirm both bare-string/substring patterns are gone and no other occurrence was missed within
  this file. Also run `grep -n 'async def _strat1_attempt_trade\|async def run_strat_1' trading-app/workers/auto_trader.py`
  to confirm the new module-level function exists and the closure wrapper is now a one-line
  delegator (no leftover duplicate trade-attempt logic in both places).

### Step C — Tests

- [ ] C1. **Resolved (PVL-supplement — see "Testability Extraction" section above; this
  replaces the plan's original C1 wording, which assumed `run_strat_1()` was directly
  callable/importable — it is not, see Verification Evidence CONCERN below).** Add an
  integration-style test that calls the new module-level `_strat1_attempt_trade(state, client,
  symbol, analysis)` (added by Step B1) DIRECTLY — this is the real Bug-1 code, unchanged by the
  extraction, so calling it directly is not a "synthetic string" test, it is the actual production
  call path. Test setup:
  - Build a real (or lightly-constructed) `state` object with `active_strategies = ["Strategy 1:
    OB + FVG"]`, `strat_1_trades_today` set to `STRAT_1_MAX_TRADES_PER_DAY` (to test the blocked
    case) and a value below the cap (to test the allowed case) — use the real `can_trade()`
    implementation in `automation.py`, do not mock `can_trade()` itself.
  - Build an `analysis` dict fixture with a `signals` list containing at least one signal shaped
    like a real Strategy 1 signal (`type` in `("CALL", "PUT")`, `confidence` >= 70, matching
    `trend` field) — reuse or adapt any existing analysis-dict fixture in `test_auto_trader.py` if
    one exists (confirm during Step A3).
  - Monkeypatch `risk_orchestrator.propose_trade` (imported at `auto_trader.py:39` as `from
    engine.risk_orchestrator import orchestrator as risk_orchestrator` — patch
    `auto_trader.risk_orchestrator.propose_trade`, the name as looked up inside `auto_trader.py`,
    not `engine.risk_orchestrator.orchestrator.propose_trade`) to capture calls without placing a
    real trade.
  - `await _strat1_attempt_trade(state, client, symbol, analysis)` directly — no need to touch
    `eval_symbol_strats()`, `automation_loop()`, or `app.get_analysis` at all, since the extraction
    means `get_analysis` is never called inside the unit under test.
  - Assert the captured `can_trade()` call (or its outcome, if `can_trade()` isn't itself mocked)
    received `"Strategy 1: OB + FVG"` — must be the full name, not a bare string — and assert
    `risk_orchestrator.propose_trade` was NOT called when the cap was already reached, and WAS
    called with the expected args when under the cap.
- [ ] C2. Add an integration-style test exercising the REAL `execute_auto_trade()` directional-
  consistency guard with a Strategy-10-shaped signal dict (`strategy_name = "Strategy 10: Adaptive
  ADX Engine"`) and a Strategy-11-shaped signal dict (`strategy_name = "Strategy 11: FRVP LVN
  Vacuum"`), asserting the guard's Strategy-1-specific branch does NOT fire for either (i.e. the
  fixed exact-match correctly distinguishes them from genuine Strategy 1 signals). Include a
  positive case with an actual Strategy 1 signal dict confirming the branch still fires correctly
  for real Strategy 1 trades (no false-negative introduced by the fix).
- [ ] C3. Evaluate `test_strategy1_daily_cap` (`test_trading_core.py:86-95`) per INNOVATE item 3:
  determine whether it is now redundant (superseded by C1's integration test) or should be updated
  to also assert against the real call site. Update or explicitly retire it with a comment
  explaining why, rather than leaving it silently unchanged and potentially misleading about what
  it actually proves.
- [ ] C4. Confirm no other existing test regresses: run the full relevant test file(s) touched by
  this phase and record pass/fail counts in the phase report.

---

## Exit Gate

```bash
# Compile check
python3 -m py_compile trading-app/workers/auto_trader.py
# Expected: exit 0, no output

# Regression test suite (redirected-to-file pytest-hang workaround per umbrella Test Infra Improvement Notes)
cd trading-app/tests && (python3 -m pytest -q test_trading_core.py test_auto_trader.py > /tmp/phase16_pytest.log 2>&1 &) ; sleep 20 && cat /tmp/phase16_pytest.log
# Expected: summary line shows all tests passing, including new/updated integration tests
# (exact test filenames confirmed/adjusted by Step A3/C3; adjust command to match)

# Bare-string / substring pattern elimination check
grep -n 'can_trade("Strategy 1"' trading-app/workers/auto_trader.py
grep -n '"Strategy 1" in strategy_name' trading-app/workers/auto_trader.py
# Expected: zero matches for both (both patterns eliminated by B1/B2)

# Diff scope confirmation — only intended files touched
git diff --stat
# Expected: only trading-app/workers/auto_trader.py, the test file(s) touched by Step C, plus this
# program's own plan/report artifacts appear
```

- All checklist items (A, B, C) checked.
- py_compile clean on `auto_trader.py`.
- New/updated tests pass 100%; both bare-string and substring patterns confirmed eliminated.
- `git diff --stat` shows no files outside the declared Blast Radius.
- Phase report written to the report destination above, explicitly noting the Bug 1 daily-cap
  BEHAVIOR CHANGE callout (see below) so it is not mistaken for a new regression.
- Open Questions section (below) carried forward to the umbrella or a backlog note if still
  unresolved at UPDATE PROCESS.

---

## Callouts for the Phase Report (per vc-predict — record verbatim, do not drop)

- **Bug 1's fix is a live BEHAVIOR CHANGE, not just a silent bug fix.** Strategy 1's daily 2-trade
  cap will actually enforce for the first time in production once this ships. Flag this explicitly
  in the phase report and in the UPDATE PROCESS closeout — Strategy 1's trade volume may visibly
  drop after this deploys, and that is EXPECTED, not a new bug. Do not let a future session
  mistake a volume drop for a regression.
- **Check whether `test_strategy1_daily_cap` needs updating or retiring** once the new integration
  test (C1) supersedes it — this is Step C3 above; the phase report must state the final
  disposition (updated / retired / kept-as-is-with-rationale), not leave it implicit.

---

## Open Questions — Requires User Sign-Off (do NOT silently act on these)

1. **Should Strategy 1 have a directional-consistency guard at all?** This phase does not decide
   this — it only makes the existing guard correctly identify Strategy 1 vs. Strategy 10/11 when it
   fires. If a future session wants to remove or redesign the guard, that is a core-behavior
   decision requiring explicit sign-off, per the umbrella's hard safety constraint. Recorded here so
   it is not silently forgotten.
2. **Shared cross-file helper for the exact-match-on-split pattern** (now hand-written independently
   in `automation.py`, `risk_orchestrator.py`, and this phase's `auto_trader.py` fix) — explicitly
   deferred as scope creep this phase. Candidate backlog item if a future maintenance pass wants to
   consolidate it.

---

## Blockers That Would Justify BLOCKED Status

- Step A1/A2 re-grep finds the call sites have moved to a materially different code structure than
  RESEARCH described (e.g. `run_strat_1()` or `execute_auto_trade()` refactored since Phase 15) —
  in that case, re-run a scoped RESEARCH pass on the new structure before proceeding to Step B,
  rather than applying the fix blindly to stale line numbers.
- Step C1/C2's integration-test approach proves genuinely disproportionate (e.g. `run_strat_1()`
  cannot be exercised without a much larger mocking surface than expected) — in that case, fall back
  to a minimal extracted-slice test (per INNOVATE item 3's stated fallback) rather than blocking the
  phase entirely; only escalate to BLOCKED if even the minimal-slice fallback is infeasible.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — dedicated debugger investigation (this session) exhaustively confirmed both
  bugs: Bug 1 (`auto_trader.py:2153`'s bare-string `can_trade()` call vs `automation.py:733`'s
  colon-suffixed match requirement — dead-code daily-cap bypass) and Bug 2 (`auto_trader.py:1190`'s
  substring-containment directional guard misidentifying Strategy 10/11 as Strategy 1). Confirmed
  the counter itself (`strat_1_trades_today`) increments correctly elsewhere — only the gate-check
  call site is broken. Confirmed Phase 1's own test used the correct full-name format, masking the
  bug. See "RESEARCH Findings" section above.
- [x] 2. INNOVATE — approach decided this session: hoist a shared `strat_name` local in
  `run_strat_1()` for both call sites (Bug 1); reuse the proven exact-match-on-split pattern
  locally at `auto_trader.py:1190` (Bug 2), explicitly declining to extract a shared cross-file
  helper (scope creep) and explicitly declining to redesign whether the directional guard should
  exist at all (open question, not decided). Test approach: real-call-path integration tests, not
  synthetic-string unit tests — the same lesson Phase 15 already learned once. See "INNOVATE
  Decision" section above.
- [ ] 3. PLAN-SUPPLEMENT — plan-agent: this phase plan created fresh (mid-program insertion, not a
  supplement to an existing phase plan — no prior Phase 16 plan existed). RESEARCH and INNOVATE are
  already folded into this plan at creation time; PLAN-SUPPLEMENT should mark "n/a — research/
  innovate already integrated at plan-creation time" unless the PVL step below surfaces new gaps.
- [x] 4. PVL — vc-validate-agent: **PASS 2 COMPLETE — Gate: PASS (after 1 validate-fix loop).**
  Cycle 1 found one CONCERN: Step C1's test approach targeted `run_strat_1()`, an unreachable nested
  closure. A PVL-supplement cycle resolved this by extracting `run_strat_1()`'s trade-attempt body
  into a new module-level `_strat1_attempt_trade(state, client, symbol, analysis)` (matching the
  program's `_strat3_orb_window_ok()` precedent), with `run_strat_1()` becoming a one-line delegator.
  Cycle 2 (this pass) independently re-verified the supplement against the LIVE current source
  (not cache): (1) every line of `run_strat_1()`'s actual body (`auto_trader.py:2124-2166`) maps 1:1
  into the proposed extraction with nothing dropped/duplicated; (2) the proposed 4-parameter
  signature captures every closure variable the body actually uses (`state`, `client`, `symbol`,
  `analysis` — confirmed `client` IS used, at the `propose_trade()` call; `risk_orchestrator` is
  correctly excluded, already module-level); (3) the extracted function is directly testable in
  isolation using `test_auto_trader.py`'s existing `import workers.auto_trader as at` +
  `monkeypatch.setattr(at, ...)` pattern; (4) the `asyncio.gather(...)` call site
  (`auto_trader.py:2321-2326`) invokes `run_strat_1()` with the identical zero-arg signature at the
  identical list position — no double-execution or dropped-execution risk from the delegator
  pattern. All four re-verification items CONFIRMED. No new CONCERN or FAIL found. Net gate: PASS —
  **PHASE_COMPLETE: VALIDATE — validate-contract written (after 1 validate-fix loop). Proceed to
  EXECUTE.**
- [ ] 5. EXECUTE — not started (unblocked — validate-contract Gate: PASS).
- [ ] 6. EVL — not started.
- [ ] 7. UPDATE PROCESS — not started.

**Validate Contract: written below — Gate: PASS (cycle 2, after 1 validate-fix loop).** RESEARCH and
INNOVATE findings remain confirmed accurate against current `main`. The cycle-1 CONCERN (Step C1
test-entry feasibility) is resolved in-plan via the Testability Extraction section and independently
re-verified against live source this cycle. EXECUTE may now proceed per Steps A/B/C as written.

---

## Touchpoints

- `trading-app/workers/auto_trader.py` — Bug 1/Bug 2 fixes, PLUS a new module-level function
  `_strat1_attempt_trade()` (extracted from the `run_strat_1()` closure — see "Testability
  Extraction" above; behavior-preserving, no new file)
- `trading-app/tests/test_trading_core.py` (evaluate `test_strategy1_daily_cap` disposition)
- `trading-app/tests/` — new or extended integration test file, calling `_strat1_attempt_trade()`
  directly (exact name TBD by EXECUTE)

---

## Public Contracts

- No external API surface change — `can_trade()` and `execute_auto_trade()`'s signatures and
  calling conventions are unchanged; only the string VALUES passed to `can_trade()` at the
  `run_strat_1()` call site, and the comparison logic inside `execute_auto_trade()`'s directional
  guard, change.
- **New internal symbol (not externally exposed):** `_strat1_attempt_trade(state, client, symbol,
  analysis)`, module-level in `auto_trader.py`. Internal, underscore-prefixed, same convention as
  the file's other `_strat*` helpers — not a public API, not imported by any other module. Added
  solely to make Bug 1's fix directly testable; `run_strat_1()` remains the real call site invoked
  by `eval_symbol_strats()`'s `asyncio.gather(...)`, now as a one-line delegator.
- **Behavior change (flagged, not silent):** Strategy 1's daily 2-trade cap will begin actually
  enforcing for the first time once Bug 1's fix ships — this is the intended fix, not a side effect
  to hide. See "Callouts for the Phase Report" above.
- No schema change — no DB surface touched by this phase.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| py_compile on `auto_trader.py` | Fully-Automated | Fix does not introduce a syntax/compile error — proven by: py_compile exit 0 |
| New/updated integration test — `_strat1_attempt_trade()` (extracted from `run_strat_1()`, same code, see "Testability Extraction") passes full name to `can_trade()`, cap correctly blocks after limit reached | Fully-Automated | Bug 1 (daily-cap bypass) is actually fixed at the real call site, not just in a synthetic assertion — proven by: assertion on the real string argument + real `can_trade()` gate behavior (checklist C1, resolved) |
| New/updated integration test — Strategy 10/11-shaped signals do not trigger the Strategy-1 directional branch; genuine Strategy 1 signals still do | Fully-Automated | Bug 2 (substring collision) is fixed without introducing a false-negative for real Strategy 1 signals — proven by: real-call-path assertions on `execute_auto_trade()`'s guard outcome (checklist C2) |
| `test_strategy1_daily_cap` disposition (updated/retired/kept, with stated rationale) | Agent-Probe | The old synthetic-input test no longer silently masks a future divergence between what it asserts and what the real call site does — proven by: explicit disposition recorded in phase report (checklist C3) |
| `grep` zero-hit check for both eliminated patterns | Fully-Automated | Both bug patterns are fully eliminated, not just patched in one spot — proven by: checklist B3 |
| `git diff --stat` scope check | Fully-Automated | Change is scoped to the declared Blast Radius only — proven by: diff file list matches Blast Radius section |

```bash
python3 -m py_compile trading-app/workers/auto_trader.py
# Expected: exit 0, no output

cd trading-app/tests && (python3 -m pytest -q test_trading_core.py test_auto_trader.py > /tmp/phase16_pytest.log 2>&1 &) ; sleep 20 && cat /tmp/phase16_pytest.log
# Expected: all tests pass, including new/updated integration tests (adjust filenames per Step A3)
```

---

## Test Infra Improvement Notes

(none identified yet — Step A3 will confirm the exact test-coverage baseline for `auto_trader.py`'s
`run_strat_1()` and `execute_auto_trade()` call paths before EXECUTE begins; record any gap found
here during EXECUTE.)

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-16-strategy1-identity-fixes_PLAN_02-09-26.md`
- Last completed step: PVL (Step 4), cycle 2 — Gate: PASS. RESEARCH (Step 1) and INNOVATE (Step 2)
  are both complete and folded into this plan at creation time (mid-program plan creation, per
  `MID_PROGRAM_PLAN_CREATED` signal contract); PLAN-SUPPLEMENT (Step 3) resolved the cycle-1 PVL
  CONCERN via the Testability Extraction section.
- Validate-contract status: **written — Gate: PASS (cycle 2, after 1 validate-fix loop).** See
  `## Validate Contract` below for the full V6 output; the resolved cycle-1 SUPPLEMENT REQUEST is
  retained immediately below it for audit trail.
- Supporting context files loaded: this plan itself (self-contained RESEARCH + INNOVATE findings
  above); umbrella plan `## HIGH-PRIORITY Open Item` and `## Backlog Items (cross-phase index)` →
  `strategy-1-daily-cap-and-collision-bugs_NOTE_01-09-26.md`; Phase 15 plan (source of the original
  finding and the proven exact-match-on-split pattern); Phase 1 plan/report (original
  `has_active_trade_for_strategy()` fix and its test suite, for the fix-pattern precedent).
- Next step for a fresh agent: spawn `vc-execute-agent` with this plan file path. Steps A/B/C
  (Implementation Checklist) are ready to implement exactly as written — Step B1's extraction shape
  and Step C1's test approach are both binding, independently re-verified against live source, and
  should not be re-litigated. This phase may run in parallel with Phase 4's resume
  (INNOVATE step next in `phase-04-strategy4_PLAN_28-08-26.md`) — the two touch disjoint files.

---

## Validate Contract

Status: PASS
Date: 02-09-26
date: 2026-09-02
generated-by: inner-pvl: phase-16
supersedes: 02-09-26 (inner-pvl: phase-16) — inner PVL has current evidence (cycle 2: PVL-supplement
resolved the sole cycle-1 CONCERN; this contract supersedes the cycle-1 CONDITIONAL contract)

Parallel strategy: sequential
Rationale: Signal score low (2 files touched, both fixes textually adjacent to already-proven
patterns, all four dimension checks depend on reading the SAME two functions —
`can_trade()`/`run_strat_1()` in `auto_trader.py`/`automation.py` and `execute_auto_trade()`).
No independent, non-overlapping investigation surfaces exist that would benefit from parallel
fan-out; a single sequential pass reading both files end-to-end (plus, this cycle, verifying the
extraction against the live `auto_trader.py` source) was faster and lower-risk than coordinating
multiple agents over the same ~45 lines of code.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| bug1-cap-fix | `_strat1_attempt_trade()` (extracted from `run_strat_1()`, same code) passes the full `"Strategy 1: OB + FVG"` string to `can_trade()` (was bare `"Strategy 1"`), so the daily 2-trade cap actually fires | Fully-Automated | Direct call to the new module-level `_strat1_attempt_trade(state, client, symbol, analysis)` with a constructed `state` (real `can_trade()`, not mocked), a constructed `analysis` dict with a real-shaped Strategy-1 signal, and `risk_orchestrator.propose_trade` monkeypatched at `auto_trader.risk_orchestrator.propose_trade`; assert the captured `can_trade()` call received `"Strategy 1: OB + FVG"` and that the cap blocks after `STRAT_1_MAX_TRADES_PER_DAY` trades | A — testability gap resolved this cycle (extraction verified reachable and behavior-preserving against live source); implementation still pending EXECUTE (checklist B1/C1) |
| bug2-collision-fix | `execute_auto_trade()`'s directional guard no longer misidentifies Strategy 10/11 as Strategy 1 via substring containment | Fully-Automated | Direct call to the module-level `execute_auto_trade(symbol, sig, analysis, client)` (no closure problem — confirmed top-level function at `auto_trader.py:1115`) with Strategy-10-shaped and Strategy-11-shaped `sig` dicts (guard must NOT fire) plus a genuine Strategy-1-shaped `sig` dict (guard must still fire) | A — fixed in this plan's checklist C2, no additional guidance needed |
| pattern-elimination | both the bare-string `can_trade("Strategy 1"` call and the substring `"Strategy 1" in strategy_name` check are fully removed from `auto_trader.py` | Fully-Automated | `grep -n 'can_trade("Strategy 1"' trading-app/workers/auto_trader.py` and `grep -n '"Strategy 1" in strategy_name' trading-app/workers/auto_trader.py` — both zero matches (checklist B3) | A |
| extraction-integrity | `run_strat_1()` becomes a one-line delegator to `_strat1_attempt_trade(state, client, symbol, analysis)`; no logic dropped or duplicated; `eval_symbol_strats()`'s `asyncio.gather(...)` call site invokes it exactly as before (same zero-arg call, same position in the gather list) | Fully-Automated | `grep -n 'async def _strat1_attempt_trade\|async def run_strat_1' trading-app/workers/auto_trader.py` (checklist B3) confirms both exist; `git diff` of the `run_strat_1`/`_strat1_attempt_trade` region reviewed for verbatim body relocation (no line count shrinkage beyond the wrapper collapse) | A |
| compile-clean | fix introduces no syntax/compile error | Fully-Automated | `python3 -m py_compile trading-app/workers/auto_trader.py` — exit 0 | A |
| scope-confined | change touches only the declared Blast Radius | Fully-Automated | `git diff --stat` after EXECUTE — only `auto_trader.py` + touched test file(s) + program plan/report artifacts | A |
| legacy-test-disposition | `test_strategy1_daily_cap` (`test_trading_core.py:86-95`) is explicitly updated, retired, or kept-as-is with stated rationale, not left silently unchanged | Agent-Probe | Phase report states the final disposition per checklist C3 | B |

gap-resolution legend:
- A — proven now (gate passes in this cycle)
- B — fixed in this plan (gate added by this plan's checklist)
- C — deferred to a named later phase/plan
- D — backlog test-building stub (named residual; keep-active; continue)

C-4 reconciliation: the `strategy:` column above carries only Fully-Automated/Agent-Probe (no
Known-Gap rows — every developed behavior has a proving strategy assigned).

Legacy line form (retained so existing validate-contract consumers still parse):
- Bug 1 fix: Fully-automated: direct call to `_strat1_attempt_trade()` (see criterion `bug1-cap-fix`; extraction verified this cycle)
- Bug 2 fix: Fully-automated: direct call to `execute_auto_trade()` (see criterion `bug2-collision-fix`)
- Extraction integrity: Fully-automated: grep + diff-region review (see criterion `extraction-integrity`)
- Pattern elimination + compile + scope: Fully-automated: grep/py_compile/git diff --stat (checklist B3, Exit Gate)
- Legacy test disposition: Agent-probe: phase report states disposition (checklist C3)

Dimension findings:
- Infra fit: PASS — both fixes are surgical single-function edits reusing patterns already proven
  twice in this codebase (`automation.py:654-670` `has_active_trade_for_strategy()`,
  `risk_orchestrator.py:44-49` `_get_agent_config()` retry). No new dependencies, no new runtime
  surface, no schema change. The extraction (new module-level `_strat1_attempt_trade`) follows the
  identical precedent already used twice in this program (Phase 3's `_strat3_orb_window_ok()`,
  Phase 2's extract-a-testable-pure-function resolution) — not a novel infra pattern.
- Test coverage: PASS (cycle-1 CONCERN resolved) — re-read the ACTUAL current `run_strat_1()` body
  end-to-end against live `main` (`auto_trader.py:2124-2166`, confirmed via direct file read, not
  cache). Findings:
  1. **Behavior-preserving extraction confirmed.** Every line currently inside `run_strat_1()`
     (the MCX/CDS guard, the active-strategies/signals guard, the `for sig in analysis["signals"]`
     loop with its trend/confidence/AI-veto checks, the `can_trade()` call, and the `propose_trade()`
     call — lines 2124-2166) maps 1:1 into the proposed `_strat1_attempt_trade(state, client, symbol,
     analysis)` body per the plan's "verbatim copy" instruction; the proposed `run_strat_1()`
     delegator (`await _strat1_attempt_trade(state, client, symbol, analysis)`) is the only remaining
     content. Nothing is dropped or duplicated in the proposed shape.
  2. **Closure-variable coverage confirmed complete.** Grepped every identifier `run_strat_1()`'s
     body actually references: `symbol` (param of `eval_symbol_strats`), `state` (param of
     `eval_symbol_strats`), `analysis` (local var assigned at `eval_symbol_strats` line 2041, closed
     over), and `client` (used at line 2165's `propose_trade(..., client, state)` call — this was
     the one closure variable the plan's prose emphasis on `symbol`/`analysis` under-highlighted, but
     it IS already included in the proposed signature `(state, client, symbol, analysis)`). No other
     closure variable is referenced — `spot`, `candles_5m`, `candles_1m`, `u_id` (all defined in the
     enclosing `eval_symbol_strats`) are used by sibling `run_strat_N` closures but NOT by
     `run_strat_1()`. `risk_orchestrator` is correctly excluded from the parameter list — confirmed
     module-level (`auto_trader.py:39`, `from engine.risk_orchestrator import orchestrator as
     risk_orchestrator`), directly reachable from the new function without threading. The proposed
     4-parameter signature is complete; no missed closure variable.
  3. **Isolated testability confirmed.** `trading-app/tests/test_auto_trader.py` already imports
     `workers.auto_trader as at` and uses `monkeypatch.setattr(at, ..., raising=True)` against
     module-level names (see `test_per_user_isolation`) — the identical pattern applies directly to
     `at._strat1_attempt_trade(state, client, symbol, analysis)` once extracted: a constructed
     `state` (real `can_trade()` from `automation.py`, not mocked, per Step C1's design), a plain
     `client` object/mock (only forwarded to `propose_trade`, never called directly inside the
     function body), a constructed `analysis` dict fixture, and `monkeypatch.setattr(at,
     "risk_orchestrator", ...)`-style patching of `propose_trade`. No import-time side effect, no
     `app.get_analysis` involvement (the FALLBACK option's known trap) — the extraction sidesteps
     that entirely, confirming Step C1's rewritten test plan is mechanically sound.
  4. **Invocation frequency/pattern unchanged.** Re-read the `asyncio.gather(...)` call site
     (`auto_trader.py:2321-2326`, inside `eval_symbol_strats`): `run_strat_1()` is called with zero
     arguments, once per `eval_symbol_strats()` invocation, at the same position in the
     `_strat_names`-ordered gather list (`"Strategy 1"` is index 7, matching `run_strat_1()`'s
     position in the `asyncio.gather(...)` args). The proposed one-line delegator
     (`async def run_strat_1(): await _strat1_attempt_trade(state, client, symbol, analysis)`)
     preserves the exact same zero-arg call signature at the exact same call site — the gather call
     itself needs zero edits. No double-execution risk (the delegator is called exactly once, same
     as today) and no dropped-execution risk (the delegator unconditionally awaits the extracted
     function, same as the original closure body ran unconditionally on invocation). Confirmed via
     grep: `run_strat_1` appears in the file at exactly two locations — its `async def` (line 2124)
     and its one call site inside the gather (line 2323) — no other reference exists that could
     depend on it remaining a closure.
  5. Re-verified Step A1/A2 line numbers against live source: `can_trade("Strategy 1"` at line 2153,
     `propose_trade("Strategy 1: OB + FVG"` at line 2165, `"Strategy 1" in strategy_name` at line
     1190 — all match the plan's stated line numbers exactly (no drift since cycle 1).
- Breaking changes: PASS — read `can_trade()`'s full body (`automation.py:708-771`): the
  `strategy_name` parameter is referenced in exactly ONE branch (line 733's
  `.startswith("Strategy 1:")` cap check); every other check in the function (automation_enabled,
  hard_exit_triggered, square_off_in_progress, per-session EOD, trades_today, pnl_today,
  loss_trades_today, cooldown, double-fire, failure backoff) depends only on `self.*` state and
  `symbol`, never on `strategy_name`. Hoisting a shared `strat_name` variable for Bug 1 therefore has
  zero effect on any other `can_trade()` branch — the only behavior change is the cap check finally
  matching, which is the intended fix. The extraction itself (moving the body into
  `_strat1_attempt_trade`) introduces no additional breaking-change surface: it is a pure code-motion
  refactor with an unchanged call site, not a logic change. For Bug 2: confirmed the ONLY place a
  real Strategy 1 signal's `strategy` field is set is `signals.py:229` (`strategy_name = "Strategy 1:
  OB + FVG"`, always with the colon) flowing into `sig["strategy"]` at `signals.py:259` — so the new
  `strategy_name.split(":")[0].strip() == "Strategy 1"` exact-match at `auto_trader.py:1190` still
  correctly fires for every genuine Strategy 1 signal; only Strategy 10/11 (whose full names also
  start with the "Strategy 1" substring but split to `"Strategy 10"`/`"Strategy 11"`) stop being
  misidentified. No other `can_trade(` call site in `auto_trader.py` uses a bare "Strategy 1"-family
  string (re-verified via full-file grep of all 15 `can_trade(` call sites) — this phase's Blast
  Radius claim of exactly one broken call site is accurate. Bug 1's cap-enforcement is a confirmed,
  intentional, backtest-driven behavior change (automation.py's own comment: "Backtest showed 2/day +
  confluence-only + breakeven-trail was the best risk-adjusted configuration; more trades/day
  degraded drawdown sharply") — the plan's BEHAVIOR CHANGE callout is accurate, not overstated.
- Security surface: PASS — no auth, secrets, schema, or external API surface touched; both edits are
  internal string-identity comparisons; the extraction adds a new internal (underscore-prefixed,
  non-exported) module-level function with no new external surface.

Open gaps: none — the cycle-1 CONCERN (Step C1 test-entry feasibility) is resolved in-plan via the
Testability Extraction section; no gap remains open for EXECUTE to resolve ad hoc.

What this coverage does NOT prove:
- `py_compile`, the two `grep` pattern-elimination checks, `git diff --stat`, and the
  extraction-integrity grep/diff-region review prove structural correctness only (syntax validity,
  pattern removal, scope containment, verbatim relocation) — they do not prove runtime correctness
  under real market data or real signal timing.
- The C1/C2 tests (direct calls to `_strat1_attempt_trade()` and `execute_auto_trade()`) prove
  correctness against constructed `state`/`analysis`/mocked `risk_orchestrator` — they do not prove
  live-broker behavior, real Fyers API timing, or production race conditions between concurrent
  strategy evaluations.
- No gate in this contract proves Strategy 1's live daily trade volume will actually drop
  post-deploy — that is a live-observation confirmation for the phase report/UPDATE PROCESS
  closeout, not a pre-merge automated gate, per the plan's own Callouts section.
- The Agent-Probe row (`test_strategy1_daily_cap` disposition) is judgment-based, not automated —
  a human/agent must read the phase report to confirm the disposition was actually recorded, not
  silently skipped.
- This VALIDATE pass confirms the extraction is CORRECTLY SPECIFIED against the current live source
  — it does not itself execute the extraction. EXECUTE must still apply it exactly as specified
  (Step B1) and the C1/C2 tests must still be written and pass; this contract does not substitute for
  that work.

Gate: PASS (no FAILs, no unresolved CONCERNs — the sole cycle-1 CONCERN was resolved by the
PVL-supplement's Testability Extraction, independently re-verified this cycle against live source)
Accepted by: n/a — PASS requires no acceptance; all findings are clean.

---

**Cycle-1 SUPPLEMENT REQUEST (resolved — retained for audit trail):**
- Gap 1: Section step-c--tests | Concern: Step C1's instruction to "exercise the REAL `run_strat_1()`
  code path" does not name a reachable test entry point — `run_strat_1()` and its container
  `eval_symbol_strats()` are both unreachable nested closures with no module-level name; neither can
  be imported or called directly from a test module. | Severity: CONCERN | Suggested addition: Add
  to Step C1 two explicit sub-options for EXECUTE to choose between, in this priority order:
  (1) PREFERRED — behavior-preserving extract-function refactor: pull `run_strat_1`'s trade-attempt
  body (the loop that calls `can_trade()` then `propose_trade()`) out of the closure into a new small
  top-level async helper function that takes `state, client, symbol, analysis, risk_orchestrator` as
  explicit parameters; `run_strat_1()` becomes a one-line wrapper that calls the new helper with its
  closure variables. The SAME code still runs at the real call site (no duplication, no test-drift
  risk) and the new helper is now directly importable and testable with ordinary mocks. Stays inside
  the already-declared Blast Radius (`auto_trader.py`).
  (2) FALLBACK — full-path invocation via `automation_loop()`: only if EXECUTE judges the refactor in
  (1) too invasive. Monkeypatch `app.get_analysis` (defined in `app.py`; imported LOCALLY inside
  `automation_loop()` at `auto_trader.py:1937` — NOT a module attribute of `auto_trader.py`, so
  patching `auto_trader.get_analysis` would silently no-op) to return a controlled analysis dict; set
  `state.active_strategies = ["Strategy 1: OB + FVG"]` so every sibling `run_strat_N()` self-gates off
  via `_strat_enabled_for`; monkeypatch `risk_orchestrator.propose_trade` (module-level in
  `auto_trader.py`, imported as `from engine.risk_orchestrator import orchestrator as
  risk_orchestrator`) to capture calls; then drive `automation_loop()` for exactly one iteration
  against a controlled `USER_CONTEXTS` fixture, mirroring the existing monkeypatch style already used
  in `test_auto_trader.py:44` (`test_per_user_isolation`). Do NOT attempt a literal copy-pasted
  "minimal extracted slice" test — that reintroduces the exact two-independent-literals drift risk
  this phase exists to eliminate.

**PVL-supplement resolution (applied):** Option (1) PREFERRED was selected and made binding — see
the plan's "Testability Extraction" section and the rewritten Step B1/C1 above. Concrete function
signature: `_strat1_attempt_trade(state, client, symbol, analysis)`, module-level, placed near
`_strat_enabled_for`/`_strat3_orb_window_ok`. `risk_orchestrator` does not need to be passed — it
is already a module-level import in `auto_trader.py`. This matches the program's established
precedent (Phase 3's `_strat3_orb_window_ok()` extraction) for the same closure-testability
problem class; no third, better option was found. Gap 1 is now resolved in-plan; EXECUTE should
proceed directly per Step B1/C1 without re-litigating the choice.

---

**Structural note (advisory, not blocking):** `node
.claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs` on this plan file reports 6
FAILs (missing Date/Status/Complexity metadata, missing "overview/context", "Phase Completion
Rules", "Acceptance Criteria" headings) and 5 warnings (legacy plan shape, no explicit
execute-anchor/supporting-phase-file notes, VERIFIED language, all-context.md mention, testing
context mention). This validator targets the generic SIMPLE/COMPLEX plan template; this file
follows the phase-program phase-plan shape used consistently across all 16 phases of the
`strategy-rebuild` umbrella (Purpose/Blast Radius/Implementation Checklist/Exit Gate/Verification
Evidence stand in for the missing headings, and the umbrella plan's own front matter carries
Date/Complexity/Status for the program). Treated as advisory per established precedent for this
program (see Phase 15's identical Structural note), not as a gate FAIL.
