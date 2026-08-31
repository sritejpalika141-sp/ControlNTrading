---
phase: phase-03-strategy2
date: 2026-08-31
status: COMPLETE_WITH_GAPS
feature: strategy-rebuild
plan: process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-03-strategy2_PLAN_28-08-26.md
---

# Phase 03 — Strategy 2 (9:26 - 180 Buy) Audit — EXECUTE Report

**TL;DR:** Docstring corrected (text-only, zero behavior change) and
`trading-app/tests/test_strategy_926.py` created with 7 tests covering all 6 planned
scenarios — all green, py_compile clean. **Two deviations from the plan's test
expectations, both discovered empirically and both confined to the test file.** The
material one: the plan's B4 assumed an unarmed direct jump to the entry price returns
`None`; it does not — the live code returns a full BUY signal. Registered as a backlog
note, not fixed (audit-only phase forbids runtime changes). Not committed — awaiting
independent EVL.

## What Was Done

### Step A — docstring correction (`trading-app/engine/strategy_926.py`)

Replaced the stale line in `evaluate_926_strategy`'s docstring
(`"Strictly aligns with the market trend. Blocks entirely if NEUTRAL."`) with wording that
states `current_trend` is accepted for signature compatibility but never evaluated in this
function body, and that trend/directional-regime alignment is enforced downstream by the
shared gate stack in `auto_trader.py`'s `execute_auto_trade()`.

- Signature UNCHANGED: `async def evaluate_926_strategy(client, state, current_trend="NEUTRAL", now=None):`
- `current_trend` parameter kept (explicitly not removed, per A1).
- No functional/logic line touched anywhere in the file.

### Step B — new regression test file (`trading-app/tests/test_strategy_926.py`)

Follows the sibling style exactly (`SECRET_KEY` env default, `sys.path.insert`,
`unittest.mock`, no network). `client.get_quotes` / `client.find_nearest_expiry` mocked as
plain `MagicMock` (both are sync methods invoked via `asyncio.to_thread`) — confirmed
correct in practice. `find_nearest_expiry` mocked with the real `{code, date}` shape.

| Test | Plan item | Covers |
|---|---|---|
| `test_entry_window_enforcement` | B2 | `None` before 09:26; `None` + `strat_926_expired=True` after 09:40 |
| `test_one_trade_per_day_cap` | B3 | `strat_926_triggered=True` short-circuits immediately |
| `test_arm_then_recover_crossover` | B4 | dip below arming ARMS (no signal); later cross above entry TRIGGERS BUY/CALL @180.5 and sets the flag |
| `test_direct_jump_without_arming_does_not_set_triggered_flag` | B4 (adjusted) | characterization of the unarmed direct-jump path — see Plan Deviations |
| `test_atm_based_sl_target_sizing` | B5 | entry 95%, arming 99% of entry, SL 15%, target 30% of ATM premium (190.0 fixture) |
| `test_zero_atm_premium_fallback` | B6 | ATM CE+PE both 0 → falls back to `ENTRY_PRICE`/`ARMING_THRESHOLD`/`SL_POINTS`/`TARGET_POINTS` |
| `test_no_duplicate_find_180_strikes_definition` | B7 | exactly one real `async def _find_180_strikes` definition, plus end-to-end reachability (returns non-`None`) |

The `side_effect`-based `get_quotes` mock flagged by VALIDATE was implemented as advised:
a `_atm_quote_client()` helper that returns the spot dict for the single-symbol spot call
and the constructed ATM/CE/PE chunk dict for the strike-chunk call, keeping the mocked
spot (`24000`) and the derived ATM symbols (`round(spot/50)*50`) mutually consistent.

`get_dynamic_lot_size` was verified offline-safe (returns `65` for a NIFTY option symbol
with no network), so the trigger path needed no additional patching.

## What Was Skipped or Deferred

- **Fixing the unarmed direct-jump signal path** — explicitly out of scope (audit-only
  phase; the plan forbids runtime-logic changes to `strategy_926.py`). Backlog note
  written: `process/features/strategy-rebuild/backlog/strategy2-unarmed-direct-jump-signal_NOTE_31-08-26.md`
- **Removing the unused `current_trend` parameter** — rejected in INNOVATE; honored.
- **Commit / push** — deliberately not performed; awaiting independent EVL.

## Test Gate Outcomes

| criterion | Command | Result |
|---|---|---|
| A2 | `python3 -m py_compile trading-app/engine/strategy_926.py` | **PASS** — exit 0, no output |
| B2–B7 | `cd trading-app/tests && python3 -m pytest test_strategy_926.py -v` | **PASS** — 7 passed |
| C1 | `cd trading-app/tests && python3 -m pytest -q` | see "Full scoped suite" below |

### Full scoped suite (C1)

**PASS — no regressions.** Explicitly diffed against a stashed baseline, per the plan's
`## Blockers` instruction:

| Run | Result |
|---|---|
| Baseline (`git stash` on `strategy_926.py` + new test file moved aside) | `6 failed, 170 passed in 16.32s` |
| With this phase's changes | `6 failed, 177 passed in 15.38s` |

**Identical 6 failures in both runs** — all pre-existing, none in this phase's blast radius:

- `test_anti_chase_fade.py::test_chase_near_local_high` — `RuntimeError: There is no current event loop` (Python 3.14 removed the implicit loop that `asyncio.get_event_loop()` relied on)
- `test_anti_chase_fade.py::test_not_chase_on_pullback` — same root cause
- `test_auto_trader.py::test_atr_sl_field_separation`
- `test_p0_fixes.py::test_gap_strategy_filters_todays_candles_with_unix_ts`
- `test_smart_sl_3candle.py::test_smart_sl_uses_exact_3_candle_1m_low_not_12pct_floor`
- `test_smart_sl_3candle.py::test_smart_sl_ignores_wider_5_candle_low_when_3_is_valid`

Delta is exactly `+7 passed` — this phase's new tests. Zero pre-existing tests regressed.

Classification of the 6: **pre-existing** (2 are `harness-drift` — Python 3.14 event-loop
API removal; the other 4 need their own triage). Not absorbed silently; recorded here and
recommended for program-level triage at UPDATE PROCESS.

## Plan Deviations

Both deviations are confined to `trading-app/tests/test_strategy_926.py`. No source-logic
change was made, and the blast radius is unchanged.

### Deviation 1 (MATERIAL) — B4's "direct jump does not trigger" assertion is false

**Plan text (B4):** "Also assert a direct jump (LTP never dips below arming, straight
to/above entry on the very first tick with `armed` still `False`) does NOT trigger
(returns `None` for that tick) — proves the arm-then-recover ordering is enforced, not a
bare threshold check."

**Actual behavior:** it DOES return a signal. In `evaluate_926_strategy`, the
`return {...}` sits at the `elif ltp >= _entry:` level, one indent level OUTSIDE the
`if strike_info.get('armed', False):` block. Only `state.strat_926_triggered` is gated on
`armed`. Verified empirically (the assertion as written fails; the characterization
assertion passes).

**How handled (escalation ladder — document + backlog + continue):** the test was rewritten
as an explicitly-labelled characterization test asserting the ACTUAL behavior
(`armed` stays `False`, `strat_926_triggered` stays `False`, but a signal dict IS
returned), with an in-test docstring marking it as a KNOWN GAP rather than an endorsement.
A backlog note was written with the root cause, the live-money risk (the one-trade-per-day
cap is not consumed on this path, so a second signal is possible in the same window), and
a suggested fix requiring its own R→P→V cycle plus backtest comparison.

**Not fixed here** because this phase's approved scope explicitly excludes any change to
`strategy_926.py`'s runtime logic. Flagging for orchestrator/user decision.

### Deviation 2 (MINOR) — B7's substring count needed line anchoring

**Plan text (B7):** assert `"async def _find_180_strikes"` occurs exactly once via
`.count(...) == 1`.

**Problem:** the file's trailing historical `NOTE` comment (lines ~272-276) itself quotes
the string `async def _find_180_strikes(client):` while describing the removed duplicate,
so the naive substring count is `2` and the test fails against correct source.

**Fix applied:** counted real definitions only, via
`re.findall(r"^async def _find_180_strikes\b", src, re.MULTILINE)` — anchored to line
start, so commented-out or quoted occurrences do not match. Same regression class is still
caught (a genuine second top-level definition would be counted). Within blast radius,
test-file only.

## Test Infra Gaps Found

`CONTEXT_PARTIAL: none.`

- **Pre-existing, confirmed still present:** bare `pytest .` / `pytest trading-app/` cannot
  be used (root-level `test_*.py` diagnostic scripts `sys.exit(1)` at import → pytest
  `INTERNALERROR`). The documented workaround (`cd trading-app/tests && python3 -m pytest -q`)
  was used throughout, per the plan. Classification: **harness-drift**, pre-existing,
  already raised in the Phase 02 report — still unaddressed at program level.
- **New observation (harness-drift): the `pytest` process does not exit after the run
  completes.** The full scoped suite finishes its work in ~15s and prints its summary
  line, but the process then hangs indefinitely instead of returning — a foreground
  `cd trading-app/tests && python3 -m pytest -q` therefore appears to never finish and had
  to be run redirected to a file and reaped with `pkill`. Almost certainly a non-daemon
  thread or unclosed event loop left behind by one of the suite's modules. Impact: C1 is
  unrunnable as a plain foreground gate command; all 11 remaining phases inherit this.
  Recommend a program-level follow-up. Not caused by this phase — reproduced identically
  on the stashed baseline.
- **Pre-existing failure triage owed:** the 6 baseline failures above (2 of them a Python
  3.14 `asyncio.get_event_loop()` API removal) should be triaged at program level; they
  make "suite fully green" unavailable as an exit signal for every remaining phase.

## Closeout Packet

- **Selected plan:** `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-03-strategy2_PLAN_28-08-26.md`
- **Finished:** A1, A2, B1–B8, C1.
- **Verified:** py_compile green; 7/7 new tests green; docstring edit confirmed
  text-only (signature byte-identical, `current_trend` still unread anywhere in the file).
- **Still unverified:** live-market behavior of Strategy 2; interaction of the unarmed
  direct-jump signal with the downstream `auto_trader.py` gate stack (does the shared gate
  reject it? unknown — flagged in the backlog note as the first thing to check).
- **Follow-up stubs created:**
  `process/features/strategy-rebuild/backlog/strategy2-unarmed-direct-jump-signal_NOTE_31-08-26.md`
- **Remaining cleanup:** independent EVL confirmation, commit, umbrella
  `## Current Execution State` update, orchestrator decision on Deviation 1.
- **Closeout classification:** `Keep in active/testing` — code-complete and internally
  green, but EVL confirmation and a decision on Deviation 1 are pending.

## Forward Preview

### Test Infra Found
- `trading-app/tests/conftest.py` puts `trading-app/` on `sys.path`; import as
  `engine.strategy_926`, never `trading_app.*`.
- Strategies whose sync client methods are called through `asyncio.to_thread` must be
  mocked with `MagicMock`, NOT `AsyncMock`. Confirmed for `get_quotes` and
  `find_nearest_expiry`. Reuse `_atm_quote_client()`'s `side_effect` pattern in later
  strategy phases — most strike-finders call `get_quotes` more than once per invocation
  with different symbol lists.
- `engine.strikes.get_dynamic_lot_size` is offline-safe; no patch needed in tests.
- The `now=` injectable-clock parameter on `evaluate_926_strategy` makes window tests
  trivial — prefer strategies that expose it; the ones that do not need the
  clock-injection backlog item (`eval-strat3-clock-injection_NOTE_28-08-26.md`).

### Blast Radius Changes
- `trading-app/engine/strategy_926.py` — docstring only, +6 lines in the
  `evaluate_926_strategy` docstring. All line numbers below line 37 shift by **+6**
  relative to earlier research notes; later phases should re-grep, not trust cached
  line numbers.
- `trading-app/tests/test_strategy_926.py` — new file, 7 tests.

### Commands to Stay Green
```bash
python3 -m py_compile trading-app/engine/strategy_926.py
cd trading-app/tests && python3 -m pytest test_strategy_926.py -v
```

### Dependency Changes
None. No new packages, imports beyond stdlib `re`/`pytz` (already a project dependency),
runtime surfaces, or config.

---

## Addendum — Supplement fix (31-08-26): unarmed direct-jump trigger flag

**Approved by user** after the bug was independently confirmed twice (execute-agent while
writing tests, then an independent EVL/tester read of the code).

### Bug
In `trading-app/engine/strategy_926.py`, `evaluate_926_strategy()`:
`state.strat_926_triggered = True` was set only inside `if strike_info.get('armed', False):`,
while the `return {...}` emitting the BUY signal was dedented and ran regardless. A direct
jump to/above the entry price without ever dipping below the arming threshold therefore
emitted a BUY signal WITHOUT consuming the 1-trade-per-day cap — contradicting the strategy's
explicit "strictly 1 trade today" intent.

### Fix (minimal diff, one statement moved)
`state.strat_926_triggered = True` dedented out of the `armed` block so it is set
unconditionally alongside the `return`. The `logger.info` "TRIGGERED" line remains gated on
`armed` (unchanged). No other logic in the function was touched.

### Test change
`test_direct_jump_without_arming_does_not_set_triggered_flag` →
renamed `test_direct_jump_without_arming_still_sets_triggered_flag`; assertion flipped from
`strat_926_triggered is False` to `is True`; docstring updated to record it as a confirmed
bug fixed in Phase 3.

### Backlog note
`process/features/strategy-rebuild/backlog/strategy2-unarmed-direct-jump-signal_NOTE_31-08-26.md`
marked RESOLVED / SUPERSEDED with a pointer to this addendum.

### Gate evidence (internal, pre-EVL)
- `python3 -m py_compile engine/strategy_926.py tests/test_strategy_926.py` → clean.
- `python3 -m pytest test_strategy_926.py -v` → **7 passed in 2.50s** (run with output
  redirected + polled, per this phase's documented pytest-hang finding).

### Files touched
- `trading-app/engine/strategy_926.py`
- `trading-app/tests/test_strategy_926.py`
- `process/features/strategy-rebuild/backlog/strategy2-unarmed-direct-jump-signal_NOTE_31-08-26.md`
- this report

Not committed / not pushed — awaiting independent EVL re-confirmation.
