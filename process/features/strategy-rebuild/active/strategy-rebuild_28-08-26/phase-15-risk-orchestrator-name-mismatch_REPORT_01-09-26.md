---
phase: phase-15-risk-orchestrator-name-mismatch
date: 2026-09-01
status: COMPLETE
feature: strategy-rebuild
plan: process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-15-risk-orchestrator-name-mismatch_PLAN_31-08-26.md
---

# Phase 15 EXECUTE Report — Risk Orchestrator Strategy-Name Mismatch

**TL;DR:** All checklist items (A, B incl. B1b/B1c, C) implemented exactly as planned. Strategies
1-9 now pass their full descriptive names to `propose_trade()`; `flush_signals()`'s three daily-cap
literals were migrated in the same change; `_get_agent_config()` gained an exact-match-on-split
retry plus a fallback warning. New `tests/test_risk_orchestrator.py` — 27/27 pass. `py_compile`
clean. No commit made. Two backlog notes written. Ready for independent EVL.

## What Was Done

### Step A — Fresh RESEARCH (A1-A6)

Re-grepped `trading-app/workers/auto_trader.py` fresh this session (did not trust cached line
numbers). **A6 authoritative affected-call-site list**, cross-checked byte-for-byte against
`trading-app/models.py:465-476` `default_strats`:

| Line | Strategy | Was (short) | Now (full, = DB seed) | Verdict |
|---|---|---|---|---|
| 1999 | 2 | `"Strategy 2"` | `"Strategy 2: 9:26 - 180 Buy"` | MISMATCH → fixed |
| 2023 | 3 | `"Strategy 3"` | `"Strategy 3: 5-Minute ORB"` | MISMATCH → fixed |
| 2035 | 5 | `"Strategy 5"` | `"Strategy 5: Optimized Aerospace Mean Reversion"` | MISMATCH → fixed |
| 2055 | 4 | `"Strategy 4"` | `"Strategy 4: Wisdom-Aligned Pullback"` | MISMATCH → fixed |
| 2062 | 6 | `"Strategy 6"` | `"Strategy 6: Gap Fill Reversal"` | MISMATCH → fixed |
| 2085 | 7 | `"Strategy 7"` | `"Strategy 7: Swing-Pivot Breakout"` | MISMATCH → fixed |
| 2101 | 8 | `"Strategy 8"` | `"Strategy 8: Smart Money Concepts"` | MISMATCH → fixed (**confirms A3**) |
| 2108 | 9 | `"Strategy 9"` | `"Strategy 9: 9-EMA Momentum Scalper"` | MISMATCH → fixed (**confirms A3**) |
| 2165 | 1 | `"Strategy 1"` | `"Strategy 1: OB + FVG"` | MISMATCH → fixed (**confirms A4** — real, distinct call site, NOT the `state.can_trade("Strategy 1", ...)` gate at line 2153) |
| 2115 | 10 | — | `"Strategy 10: Adaptive ADX Engine"` | already MATCH — untouched |
| 2122 | 11 | — | `"Strategy 11: FRVP LVN Vacuum"` | already MATCH — untouched |
| 2256 | crude pending | `pending["strategy_name"]` (`"Commodity: Evening Momentum"` / `"Commodity: EIA Volatility (Wed)"`) | unchanged | **Out of numbered-strategy MISMATCH scope** — never seeded in `default_strats` under any name; hits the zeroed default for a different, pre-existing reason. Explicitly classified, not overlooked. |
| 2307 | AI strategy | `ai_name` (loop var) | unchanged | Same classification as above — out of the numbered-strategy bug class. |

**A5 — test coverage:** confirmed zero. `find trading-app/tests -iname "*risk_orch*"` → no matches
before this phase.

### Step B — Fix call sites + harden lookup

- **B1** — 9 call sites renamed in `trading-app/workers/auto_trader.py` (table above). Each literal
  verified against `models.py`'s `default_strats` before writing; no guessing.
- **B1b** — `trading-app/engine/risk_orchestrator.py` `flush_signals()` (was lines 164-172): the
  three hardcoded exact-string checks migrated in the SAME change:
  - `s_name == "Strategy 3"` → `s_name == "Strategy 3: 5-Minute ORB"` (drives `state.strat_orb_triggered`)
  - `s_name == "Strategy 4"` → `s_name == "Strategy 4: Wisdom-Aligned Pullback"` (drives `state.strat_4_trades`)
  - `s_name == "Strategy 6"` → `s_name == "Strategy 6: Gap Fill Reversal"` (drives `state.strat_6_trades_today`)
  A comment block was added explaining why these literals must stay byte-identical to the seeding.
- **B1c** — hardcoded short-name comparison sweep, run this session across
  `risk_orchestrator.py`, `automation.py`, `auto_trader.py` with `== "Strategy`, `in ["Strategy`,
  `in ("Strategy`, `startswith("Strategy`, and `"Strategy 1" in `. **Full list of every hit found
  (safe or unsafe):**

  | Location | Form | Verdict |
  |---|---|---|
  | `risk_orchestrator.py:72` | `any(s in strategy_name for s in ("Strategy 3","Strategy 6","Strategy 7"))` — CHOPPY_SIDEWAYS override | **SAFE** — substring containment; a full name still contains its short prefix. Re-confirmed post-fix, untouched. |
  | `risk_orchestrator.py:164/167/170` | `== "Strategy 3"/"4"/"6"` in `flush_signals()` | **UNSAFE** — fixed by B1b. The only checks actually broken by B1. |
  | `auto_trader.py:642` | `t.get("strategy") == "Strategy 5: Optimized Aerospace Mean Reversion"` | SAFE — already full form; fed by `sig["strategy"]` set in `strategy_5.py`, a different string flow than `propose_trade()`'s argument. |
  | `auto_trader.py:679` | `t.get("strategy") == "Strategy 6: Gap Fill Reversal"` | SAFE — same reasoning (`strategy_gap.py`). |
  | `auto_trader.py:714` | `t.get("strategy") in ["Strategy 3: 5-Minute ORB", "Strategy 9: 9-EMA Momentum Scalper"]` | SAFE — same reasoning. |
  | `auto_trader.py:1328` | `sig.get("strategy") == "Strategy 3: 5-Minute ORB"` | SAFE — same reasoning. |
  | `auto_trader.py:1190` | `if "Strategy 1" in strategy_name:` in `execute_auto_trade()` | **Pre-existing bug, unaffected by B1** — `strategy_name` here is `sig.get("strategy","")` (engine-set), not `propose_trade()`'s argument. Collides with Strategy 10/11. Out of scope → backlog note. |
  | `automation.py:733` | `str(strategy_name).startswith("Strategy 1:")` in `can_trade()` | **Pre-existing bug, unaffected by B1** — its call site (`auto_trader.py:2153`) passes bare `"Strategy 1"`, so the daily cap never fires. Out of scope → backlog note. |
  | `automation.py:994` | `str(strategy).startswith("Strategy 1:")` in `add_active_trade()` | Same family as above — recorded in the backlog note. |
  | `automation.py:664` | comment referencing the Phase-1 fix | not a comparison. |

  No other hit exists in the three files. This is an exhaustive account.
- **B2** — `_get_agent_config()` now retries on a direct-lookup miss using exact-match-on-split
  (`s_name.split(":")[0].strip()` compared for **equality** against each
  `Database.get_all_agent_configs()` row's split prefix). Never `startswith`/`LIKE`/substring —
  this is the same pattern as `automation.py:has_active_trade_for_strategy()`. No new DB API
  surface (`get_all_agent_configs()` already existed). The retry is wrapped in try/except so a DB
  error degrades to the safe zeroed default rather than raising into the trading loop.
- **B3** — the fallback branch (reached only when both the direct lookup and the split retry miss)
  now emits `logger.warning("⚠️ No agent config found for strategy '{s_name}' — using zeroed
  defaults (win_rate=0.0). Check for a name mismatch against swarm_agent_configs.")`.
- **B4** — post-edit re-grep: `grep -n 'propose_trade("Strategy [0-9]"' auto_trader.py` returns
  zero hits. Strategy 10/11 and the crude/AI call sites are untouched.

### Step C — Tests

New file `trading-app/tests/test_risk_orchestrator.py` (27 tests, all passing):

| Test | Covers |
|---|---|
| `test_full_name_resolves_real_db_row` (×9) | each Strategy 1-9 full name resolves to its real seeded row (real `win_rate`/`total_trades`, not the zeroed default) |
| `test_short_name_resolves_via_split_retry` (×9) | the B2 hardening resolves a short name to the correct full-name row |
| `test_strategy_1_does_not_collide_with_10_or_11` | collision regression — "Strategy 1" resolves to `"Strategy 1: OB + FVG"` |
| `test_strategy_10_and_11_resolve_to_themselves` | reverse direction of the collision check |
| `test_split_retry_is_not_a_prefix_match` | **mutation guard** — with the Strategy 1 row removed, a `startswith`/substring implementation would return Strategy 10/11; the correct one returns the zeroed default |
| `test_unknown_strategy_warns_and_returns_zeroed_default` | B3 warning fires via `caplog` AND the safe default is still returned (no crash) |
| `test_known_strategy_does_not_warn` | the warning does not fire spuriously |
| `test_flush_signals_sets_strat_orb_triggered_for_strategy_3` | **flush-signals-caps** — Strategy 3 one-shot flag set through the real `flush_signals()` |
| `test_flush_signals_increments_strat_4_trades_to_two` | **flush-signals-caps** — Strategy 4 counter reaches 2 |
| `test_flush_signals_increments_strat_6_trades_today_to_two` | **flush-signals-caps** — Strategy 6 counter reaches 2 |
| `test_flush_signals_short_names_no_longer_drive_caps` | asserts the literals were genuinely migrated (short name no longer triggers the cap) |

The flush-signals tests drive the **real** `flush_signals()` end-to-end (only `execute_auto_trade`
is stubbed) with the post-B1 full-name strings, and assert concrete state-field side effects — they
fail if B1b's literals are wrong or missing. Non-vacuous, per the validate-contract's Cycle 2 Check 3.

**C2** — pre-existing tests touching the changed surfaces: `test_p0_fixes.py`,
`test_strategy_runtime_fixes.py` (plus `test_auto_trader.py`, `test_orb_filters.py` run for safety).
Result: 21 passed, 2 failed. Both failures
(`test_p0_fixes.py::test_gap_strategy_filters_todays_candles_with_unix_ts` — "no current event loop";
`test_auto_trader.py::test_atr_sl_field_separation` — source-string assertion about
`t["trailing_sl_price"]`) were reproduced **identically on the unmodified files via `git stash`**.
Pre-existing, unrelated to Phase 15.

## What Was Skipped or Deferred

Per the plan's explicit out-of-scope list — none of these were touched:
- The startup/nightly config-drift validation check → backlog note written.
- `automation.py:733`'s Strategy-1 `can_trade()` daily-cap `.startswith("Strategy 1:")` mismatch → backlog note written.
- `auto_trader.py:1190`'s Strategy-1-vs-10/11 substring collision in `execute_auto_trade()` → same backlog note.
- Any change to any strategy's trading/entry/exit logic.
- No commit or push (explicitly instructed to stop before commit).

## Test Gate Outcomes

| Gate | Command | Result |
|---|---|---|
| compile | `python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/risk_orchestrator.py` | **PASS** — exit 0, no output |
| call-site-fix | `grep -n 'propose_trade("Strategy [0-9]"' trading-app/workers/auto_trader.py` | **PASS** — zero short-form hits |
| lookup-hardening / collision-safety / fallback-log / flush-signals-caps | `cd trading-app/tests && python3 -m pytest test_risk_orchestrator.py -v` | **PASS** — 27 passed in 4.16s, exit 0 |
| regression (pre-existing suites) | `pytest test_p0_fixes.py test_strategy_runtime_fixes.py test_auto_trader.py test_orb_filters.py -q` | **PASS with 2 pre-existing failures** (proven pre-existing via `git stash`) |
| scope | `git diff --stat -- trading-app/` | **PASS** — only `risk_orchestrator.py` (+40/-4) and `auto_trader.py` (+9/-9); new test file untracked |
| affected-list (Agent-Probe) | fresh re-grep cross-checked against `models.py` | **PASS** — recorded above as A6 |
| b1c-sweep-complete (Agent-Probe) | exhaustive hardcoded-name sweep | **PASS** — full table above |

## Plan Deviations

None. Every checklist item implemented as written. No hard-stop-class or within-blast-radius
deviations.

## Test Infra Gaps Found

- `pytest` in this repo required the documented redirect-to-file + poll pattern; it worked without
  hanging for these targets.
- Two pre-existing failures in `test_p0_fixes.py` / `test_auto_trader.py` are unrelated to this
  phase but are latent red in the suite — worth a separate cleanup item.

## EVL Confirmation and Commit (added at UPDATE PROCESS, 01-09-26)

Independent EVL (separate session, orchestrator-owned) re-ran the exact validate-contract gate
commands rather than trusting this report's self-reported EXECUTE results:
- `python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/risk_orchestrator.py` — green
- `cd trading-app/tests && python3 -m pytest test_risk_orchestrator.py -v` — 27/27 green
- `grep -n 'propose_trade("Strategy [0-9]"' trading-app/workers/auto_trader.py` — zero hits
- `git diff --stat` — scope matched the declared Blast Radius

No discrepancy from EXECUTE's self-report. Execution changes committed and pushed to `origin/main`
at `e9c6d63` ("fix(trading): strategy names didn't match database, breaking fair trade-slot
selection"); local HEAD confirmed matching `origin/main` at UPDATE PROCESS time.

**Not proven by this phase (carried forward, not silently dropped):** a live-DB spot-check that the
production `swarm_agent_configs` table matches `models.py`'s `default_strats` seeding (the
validate-contract's own "What This Coverage Does NOT Prove" caveat) — this remains an Agent-Probe
gap, not blocking, since the seeding-code proof is what the gate table commits to.

## Closeout Packet

- **Selected plan:** `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-15-risk-orchestrator-name-mismatch_PLAN_31-08-26.md`
- **Finished:** Steps A, B (B1/B1b/B1c/B2/B3/B4), C (C1/C2); 2 backlog notes; EVL confirmation; commit `e9c6d63`.
- **Verified:** py_compile, 27/27 new tests, grep gates, diff scope — confirmed twice (EXECUTE self-report + independent EVL re-run).
- **Still unverified:** live-DB spot-check that the production `swarm_agent_configs` table matches `models.py` seeding (Agent-Probe, non-blocking known-gap, not required by this phase's own gate table).
- **Remaining:** none for this phase. UPDATE PROCESS (this document's finalization) is the last step.
- **Classification:** ✅ VERIFIED. Stays in the program's flat `active/` task folder (program continues — not individually archived; matches Phases 1-3's precedent of staying co-located until the whole umbrella closes).

## Forward Preview

**Test Infra Found:** `trading-app/tests/conftest.py` puts `trading-app/` on `sys.path`;
`pytest.ini` sets `asyncio_mode = auto`, so async tests need no `@pytest.mark.asyncio`.

**Blast Radius Changes:** `trading-app/workers/auto_trader.py`,
`trading-app/engine/risk_orchestrator.py`, new `trading-app/tests/test_risk_orchestrator.py`,
2 new backlog notes under `process/features/strategy-rebuild/backlog/`.

**Commands to Stay Green:**
```bash
python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/risk_orchestrator.py
cd trading-app/tests && python3 -m pytest test_risk_orchestrator.py -v
```

**Dependency Changes:** none.

**Next:** after EVL green + UPDATE PROCESS, resume Phase 4
(`phase-04-strategy4_PLAN_28-08-26.md`) at its INNOVATE step.
