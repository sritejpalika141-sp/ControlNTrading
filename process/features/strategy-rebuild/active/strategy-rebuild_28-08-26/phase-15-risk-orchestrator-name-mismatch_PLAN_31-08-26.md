---
name: plan:strategy-rebuild-phase-15-risk-orchestrator-name-mismatch
description: "strategy-rebuild — Phase 15: fix strategy-name mismatch between auto_trader.py call sites and swarm_agent_configs DB rows, which silently zeroes win-rate/Kelly-sizing lookups for most strategies"
date: 31-08-26
metadata:
  node_type: memory
  type: plan
  feature: strategy-rebuild
  phase: phase-15
---

# Phase 15 — Risk Orchestrator Strategy-Name Mismatch

**Program:** strategy-rebuild
**Umbrella plan:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
**Phase status:** ✅ VERIFIED (EVL-confirmed 01-09-26; committed + pushed to `origin/main` at `e9c6d63`)
**Report destination:** process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-15-risk-orchestrator-name-mismatch_REPORT_01-09-26.md (flat in the program task folder)

**Insertion note:** This phase was discovered mid-program, during Phase 4's own RESEARCH pass (Phase
4 = Strategy 4 / Wisdom-Aligned Pullback audit, still in progress, PAUSED — not abandoned). Because
the bug affects the shared risk-orchestration path used by nearly every strategy, it is prioritized
to run NOW, ahead of Phase 4 resuming. Phase 4's own RESEARCH already completed for its original
scope and found no bug in `strategy_wisdom.py` itself — Phase 4 will resume/close out (INNOVATE →
PLAN-SUPPLEMENT → PVL → EXECUTE → EVL → UP) after Phase 15 finishes. This phase is numbered 15 and
appended to the existing flat program task folder — it does not replace or renumber phases 1-14.

---

## Purpose

`trading-app/workers/auto_trader.py` calls `risk_orchestrator.propose_trade(strategy_name, ...)`
using SHORT strategy-name strings ("Strategy 2", "Strategy 3", ... "Strategy 9", and — per this
phase's own fresh RESEARCH, see below — "Strategy 1" too) at most call sites, while
`swarm_agent_configs` (the DB table `risk_orchestrator._get_agent_config()` queries by exact string
match) is seeded and written using FULL descriptive names ("Strategy 1: OB + FVG", "Strategy 2: 9:26
- 180 Buy", etc. — confirmed in `trading-app/models.py:465-483` and
`trading-app/engine/nightly_learning.py`). The exact-string mismatch means `_get_agent_config()`
always misses the DB row for the affected strategies and falls back to the hardcoded default
(`{'win_rate': 0.0, 'total_trades': 0}`), which — combined with the orchestrator's grace-period
logic — makes `effective_win_rate` permanently pinned at 100.0 (never expires) for those strategies,
letting them win tie-breaks against strategies with real, possibly-lower, honestly-earned win rates.
Kelly position-sizing multiplier is also permanently pinned to the 1.0 warm-up default for the same
strategies. This phase fixes the call-site names, hardens the lookup itself against future
recurrence, and adds a visibility log line — without building a full config-drift validation system
(that is explicitly out of scope, tracked as a backlog item).

---

## Entry Gate

- Phase 4's RESEARCH step surfaced this bug as a shared-infrastructure finding, not a
  `strategy_wisdom.py`-local one; program owner (this session) elected to run it as an inserted
  phase ahead of Phase 4 resuming.
- No dependency on Phases 1-14 being complete — this phase touches shared orchestration
  infrastructure (`risk_orchestrator.py`) and one caller (`auto_trader.py`), not any individual
  strategy engine file.

---

## Fresh RESEARCH Required (Step 1 — do not skip)

Phase 4's flag left two items explicitly unconfirmed. This phase's own RESEARCH subagent MUST
resolve both before INNOVATE/PLAN-SUPPLEMENT proceeds to the fix:

1. **Strategy 8 / Strategy 9 affected-or-not.** Re-grep `auto_trader.py` for the current exact line
   numbers of the `propose_trade("Strategy 8", ...)` and `propose_trade("Strategy 9", ...)` call
   sites (lines may have shifted since Phase 4's research pass — do not trust cached line numbers,
   per the umbrella's Test Infra Improvement Notes). Cross-check against
   `swarm_agent_configs` seeding (`models.py` default_strats list: `"Strategy 8: Smart Money
   Concepts"`, `"Strategy 9: 9-EMA Momentum Scalper"`) to confirm the exact-string mismatch applies
   to both.
2. **Strategy 1 — new finding, confirm and fold into scope.** A preliminary grep during this plan's
   own drafting found `risk_orchestrator.propose_trade("Strategy 1", symbol, sig, analysis, client,
   state)` at `auto_trader.py` (search for `propose_trade("Strategy 1"` — this is a DIFFERENT call
   site than the strategy's own internal `state.can_trade("Strategy 1", ...)` gate a few lines
   above it, which is a separate, unaffected mechanism). The DB seeds `"Strategy 1: OB + FVG"`
   (full name). If confirmed, **Strategy 1 belongs on the affected list too**, even though it was
   not named in the original mid-program flag — RESEARCH must confirm this is real (not a stale
   grep artifact from plan drafting) and add it to the fix scope if so.
3. Re-grep ALL `risk_orchestrator.propose_trade(` call sites in `auto_trader.py` fresh (do not
   reuse this plan's line numbers verbatim) to produce the final authoritative affected-vs-unaffected
   list before writing the fix. Strategy 10 and Strategy 11 call sites already pass full descriptive
   names (`"Strategy 10: Adaptive ADX Engine"`, `"Strategy 11: FRVP LVN Vacuum"`) — confirmed
   unaffected; re-verify this holds.
4. Confirm zero existing test coverage exists for `risk_orchestrator.py` (`_get_agent_config`,
   `propose_trade`) before assuming test-writing scope in this phase's checklist — search
   `trading-app/tests/` for any existing `test_risk_orchestrator*.py` or equivalent.

---

## INNOVATE Decision (Approach C — already decided this session, PLAN-SUPPLEMENT step should not
re-litigate it, but RESEARCH's item 1-2 findings above may adjust the exact call-site list)

1. Fix the affected `auto_trader.py` call sites to pass FULL descriptive names (matching the DB
   seed strings and matching how Strategies 10/11 already correctly do it).
2. Harden `risk_orchestrator._get_agent_config()`'s lookup to be resilient regardless of caller
   mistakes — reuse (do not re-derive) the exact-match-on-split pattern already proven in
   `trading-app/engine/automation.py`'s `has_active_trade_for_strategy()` (added 28-08-26, Phase 1
   of this program): split both sides on `:`, exact-match the "Strategy N" prefix, never
   `startswith`/`LIKE`/naive substring. This defends against a future typo or a carelessly-added
   new strategy silently reintroducing this exact bug class a second time.
3. Add a minimal `logger.warning` inside `_get_agent_config()`'s fallback-to-default branch (2-3
   lines) so any future name mismatch is immediately visible in logs — not a full validation
   system.
4. **Explicitly OUT of scope** (do not build in this phase): a startup/nightly config-drift
   validation check that cross-references every `propose_trade` call-site name against DB-seeded
   names. Record this as a new backlog note under
   `process/features/strategy-rebuild/backlog/` (e.g.
   `config-drift-validation-check_NOTE_{dd-mm-yy}.md`) during EXECUTE/UPDATE-PROCESS, do not build
   it now.

---

## Blast Radius

- `trading-app/workers/auto_trader.py` — fix short-name call sites to full descriptive names
  (confirmed by this phase's V2 fan-out re-grep: Strategies 1, 2, 3, 4, 5, 6, 7, 8, and 9 are ALL
  affected — MISMATCH on every numbered strategy 1-9; Strategy 10/11 already pass full names and are
  unaffected)
- `trading-app/engine/risk_orchestrator.py` — harden `_get_agent_config()`'s lookup (exact-match-
  on-split normalization) + add fallback-branch warning log
- New/updated test file under `trading-app/tests/` (exact filename TBD by RESEARCH/EXECUTE — likely
  `trading-app/tests/test_risk_orchestrator.py`, new file, since RESEARCH is expected to confirm
  zero existing coverage)
- New backlog note under `process/features/strategy-rebuild/backlog/` (config-drift validation
  check, out-of-scope item, written during EXECUTE/UPDATE-PROCESS, not code)

---

## Implementation Checklist

### Step A — Fresh RESEARCH (confirm affected list)

- [x] A1. Re-grep `trading-app/workers/auto_trader.py` for every `risk_orchestrator.propose_trade(`
  call site; record exact current line numbers.
- [x] A2. For each call site, extract the passed strategy-name string; cross-check against
  `trading-app/models.py` `default_strats` (or the live `swarm_agent_configs` table if DB is
  reachable) to classify each as MATCH (full name passed) or MISMATCH (short name passed).
- [x] A3. Confirm/refute Strategy 8 and Strategy 9 affected status (Fresh RESEARCH item 1 above).
- [x] A4. Confirm/refute the Strategy 1 finding (Fresh RESEARCH item 2 above) — verify it is a real
  distinct `propose_trade` call site passing a short name, not a duplicate of the unrelated
  `state.can_trade("Strategy 1", ...)` gate call.
- [x] A5. Confirm zero existing test coverage for `risk_orchestrator.py` (Fresh RESEARCH item 4).
- [x] A6. Produce the final authoritative affected-call-site list (file + line + current short name
  + required full name) as a RESEARCH finding, superseding this plan's provisional list above where
  they differ.

### Step B — Fix call sites + harden lookup

- [x] B1. In `trading-app/workers/auto_trader.py`, change each MISMATCH call site (per A6's final
  list) from its short name to the corresponding full descriptive name exactly as seeded in
  `models.py` `default_strats` (e.g. `"Strategy 2"` → `"Strategy 2: 9:26 - 180 Buy"`).
- [x] B1b. **(Added by PVL supplement, 31-08-26 — required to close the BLOCKED gate.)** In
  `trading-app/engine/risk_orchestrator.py`'s `flush_signals()` (lines ~164-172), update the three
  hardcoded exact-string checks that currently compare `s_name` against the SHORT form — `s_name ==
  "Strategy 3"`, `s_name == "Strategy 4"`, `s_name == "Strategy 6"` — to compare against the NEW
  full-name strings that B1 will make `auto_trader.py` pass instead (verify each exact string
  against `models.py`'s `default_strats` seeding before writing the literal check, e.g. `s_name ==
  "Strategy 3: 5-Minute ORB"`, `s_name == "Strategy 4: Wisdom-Aligned Pullback"`, `s_name ==
  "Strategy 6: Gap Fill Reversal"`). These three checks drive `state.strat_orb_triggered` (Strategy
  3's one-shot/day gate, read by `strategy_orb.py:64`), `state.strat_4_trades` (Strategy 4's
  2-trades/day cap, read by `strategy_wisdom.py:107`), and `state.strat_6_trades_today` (Strategy
  6's 2-trades/day cap, read by `strategy_gap.py:42`) — without this fix, B1's rename would silently
  freeze all three daily-trade-frequency risk caps, letting those strategies exceed their intended
  daily limits. Do this edit in the SAME change as B1, not a follow-up.
- [x] B1c. **(Added by PVL supplement, 31-08-26.)** Grep `risk_orchestrator.py`,
  `trading-app/engine/automation.py`, and `trading-app/workers/auto_trader.py` for ANY OTHER
  hardcoded short-name string comparison beyond the three found in B1b, using both `grep -n '==
  "Strategy'` and `grep -n 'in \["Strategy'` (and the reverse `in (` tuple form used at
  `risk_orchestrator.py:72`) across each file. Confirm the `risk_orchestrator.py:72`
  CHOPPY_SIDEWAYS substring-containment check (`any(s in strategy_name for s in ("Strategy 3",
  "Strategy 6", "Strategy 7"))`) remains safe post-fix (it already is — substring containment still
  matches full names — but re-confirm as part of this grep pass rather than relying solely on the
  V2 finding). Record the full list of every short-name comparison found (safe or unsafe) in the
  phase report, not just the three fixed in B1b.
- [x] B2. In `trading-app/engine/risk_orchestrator.py`'s `_get_agent_config(self, s_name)`, add a
  defensive normalization pass reusing the exact-match-on-split pattern from
  `automation.py:has_active_trade_for_strategy()`: if the direct `Database.get_agent_config(s_name)`
  lookup misses, retry by exact-matching `s_name.split(":")[0].strip()` against the `strategy_name`
  prefix of rows in `swarm_agent_configs` (via a new `Database` helper or an in-memory fallback
  using the already-cached config set) before falling back to the `{'win_rate': 0.0, 'total_trades':
  0}` default. Never use `startswith`/`LIKE`/substring matching (that is the exact bug class Phase
  1 already fixed once — do not reintroduce it, especially for the "Strategy 1" vs "Strategy 10"/
  "Strategy 11" collision risk).
- [x] B3. In the same fallback branch (only reached when both the direct lookup and the
  exact-match-on-split retry miss), add `logger.warning(f"⚠️ No agent config found for strategy
  '{s_name}' — using zeroed defaults (win_rate=0.0). Check for a name mismatch against
  swarm_agent_configs.")` (2-3 lines, no new dependency).
- [x] B4. Re-run `grep -rn "propose_trade(" trading-app/workers/auto_trader.py` after the edit to
  confirm no MISMATCH call sites remain (Strategy 10/11's full-name calls and any confirmed-
  unaffected calls must be untouched).

### Step C — Tests

- [x] C1. Add `trading-app/tests/test_risk_orchestrator.py` (or extend an existing file if A5 found
  one) with cases:
  - each confirmed-affected strategy's now-fixed full-name call resolves to its real DB row via
    `_get_agent_config()` (mock/seed `swarm_agent_configs` with a known win_rate/total_trades and
    assert the returned dict matches, not the zeroed default)
  - the exact-match-on-split normalization retry does NOT collide "Strategy 1" with "Strategy 10"
    or "Strategy 11" (adapt the collision-regression pattern used for Phase 1's
    `has_active_trade_for_strategy` fix — same assertion shape, new file)
  - the fallback-warning log fires (assert via `caplog` or similar) when a genuinely unmatched name
    (e.g. a typo'd `"Strategy 99"`) is queried, and the returned config is still the safe zeroed
    default (no crash)
  - **(Added by PVL supplement, 31-08-26 — closes the BLOCKED gate.)** `flush-signals-caps`
    regression case: after applying B1 + B1b, simulate a completed trade for Strategy 3 (now using
    its full name) through `flush_signals()` and assert `state.strat_orb_triggered` is set `True`;
    simulate two completed Strategy 4 trades and assert `state.strat_4_trades` increments to `2`;
    simulate two completed Strategy 6 trades and assert `state.strat_6_trades_today` increments to
    `2`. This is the exact regression this supplement exists to prevent — if B1b's literal-string
    updates are wrong or missing, this test must fail.
- [x] C2. If any pre-existing win-rate/Kelly-sizing tests reference `risk_orchestrator.py` or
  `propose_trade`, run them and confirm they still pass unchanged (per A5, RESEARCH expects none to
  exist — if any are found, this item becomes mandatory rather than a no-op).

---

## Exit Gate

```bash
# Compile check
python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/risk_orchestrator.py
# Expected: exit 0, no output

# Regression test suite (redirected-to-file pytest-hang workaround per documented project pattern)
cd trading-app/tests && python3 -m pytest test_risk_orchestrator.py -v > /tmp/phase15_pytest.log 2>&1; echo "exit:$?"; cat /tmp/phase15_pytest.log
# Expected: exit 0, all new tests pass, no collection errors

# Diff scope confirmation — only intended files touched
git diff --stat
# Expected: only trading-app/workers/auto_trader.py, trading-app/engine/risk_orchestrator.py, and
# the new/updated test file appear (plus this program's own plan/report/backlog artifacts)
```

- All checklist items (A, B, C) checked.
- py_compile clean on both touched Python files.
- New/updated `risk_orchestrator` test file passes 100%.
- `git diff --stat` shows no files outside the declared Blast Radius.
- Phase report written to report destination above, including the final A6 authoritative
  affected-call-site list (this plan's provisional list is NOT authoritative — RESEARCH's finding
  is).
- Backlog note for the out-of-scope config-drift validation check is written.

---

## Blockers That Would Justify BLOCKED Status

- RESEARCH cannot determine with confidence whether Strategy 8/9 (or any other call site) is
  actually affected (e.g. DB schema differs from what `models.py` shows, live data unavailable to
  cross-check) — in that case, narrow the fix to only the call sites confirmed affected and file a
  backlog note for the unresolved ones, rather than guessing.
- The exact-match-on-split hardening in `_get_agent_config()` cannot be added without a schema or
  API change to `Database.get_agent_config()` that would widen blast radius beyond this phase's
  scope — if so, do the call-site fix (Step B1) only, defer the defensive-hardening layer (B2/B3) to
  a backlog note, and mark this phase CONDITIONAL/complete-with-known-gap rather than blocking
  entirely.

---

## Phase Loop Progress

Orchestrator reads this before deciding which subagent to spawn next. The canonical 7-step inner loop
`R → I → P → PVL → E → EVL → UP` SKIPS SPEC (SPEC runs once in the outer program loop).

- [x] 1. RESEARCH — research-agent: mid-program discovery during Phase 4's research pass (this
  session) surfaced the name-mismatch bug and traced it to `auto_trader.py` call sites vs
  `swarm_agent_configs` seeding in `models.py`/`nightly_learning.py`; confirmed the
  exact-match-on-split fix pattern already exists in `automation.py`. **Note:** this tick covers the
  discovery/scoping pass that justified inserting this phase. The narrower Fresh RESEARCH items
  (Step A1-A6 above — confirming Strategy 8/9/1 status and zero test coverage) still need to run as
  part of this phase's own execution before Step B begins; they are checklist items, not a
  re-opening of Step 1.
- [x] 2. INNOVATE — innovate-agent: Approach C decided this session (fix call sites + harden lookup
  + add warning log; explicitly defer full config-drift validation to backlog). See "INNOVATE
  Decision" section above.
- [x] 3. PLAN-SUPPLEMENT — plan-agent: this phase plan created fresh (mid-program insertion, not a
  supplement to an existing phase plan — no prior Phase 15 plan existed).
- [x] 4. PVL — vc-validate-agent: full V1-V7 across 2 cycles; validate-contract written, Gate: PASS
  (31-08-26, cycle 2, `generated-by: inner-pvl: phase-15`). Cycle 1 found FAIL (Item 3 flush_signals
  collateral regression), PVL-supplement (B1b/B1c/C1) applied, cycle 2 independently re-verified
  the fix and ran a broadened hardcoded-name-check sweep (found 2 new pre-existing, out-of-scope
  bugs, recorded as Open Gaps + backlog-note recommendation, non-blocking).
- [x] 5. EXECUTE — all checklist items (A, B incl. B1b/B1c, C) done 01-09-26; py_compile clean; new `tests/test_risk_orchestrator.py` 27/27 green; 2 backlog notes written.
- [x] 6. EVL — independent EVL confirmation run (orchestrator-owned, separate session) re-ran the exact validate-contract gate commands (py_compile, `test_risk_orchestrator.py` 27/27, `grep -n 'propose_trade("Strategy [0-9]"'` zero-hit check, `git diff --stat` scope check) — all green, matching EXECUTE's self-reported results with no discrepancy. Follow-up stubs registered as backlog notes (both already written by EXECUTE: `config-drift-validation-check_NOTE_01-09-26.md`, `strategy-1-daily-cap-and-collision-bugs_NOTE_01-09-26.md`). Execution changes committed and pushed to `origin/main` at `e9c6d63` ("fix(trading): strategy names didn't match database, breaking fair trade-slot selection").
- [x] 7. UPDATE PROCESS — this session (01-09-26). Phase report finalized; umbrella `## Current Execution State` rewritten (Phase 15 verified, Phase 4 resuming); context (`process/context/all-context.md`) updated; Phase 1 daily-cap/collision backlog item flagged HIGH-PRIORITY in the umbrella. No source re-commit needed (already at `e9c6d63`, verified local == `origin/main`); a docs-only commit for this closeout is recommended, not yet made.

**Validate-contract written, Gate: PASS (31-08-26, cycle 2, inner-pvl: phase-15).** Step 4 (PVL)
is complete. Cycle 1 found one unresolved FAIL (Item 3: fixing Strategy 3/4/6 call sites per Step
B1 as originally written would have silently broken the `strat_orb_triggered` / `strat_4_trades` /
`strat_6_trades_today` daily-cap gates). The PVL-supplement (B1b + B1c + C1) closed it; cycle 2
independently re-verified the fix from source (exact-string cross-check against `models.py`,
non-vacuous regression-test check, and a broadened hardcoded-name-comparison sweep beyond the
plan's own specified grep patterns). The sweep found 2 additional pre-existing bugs
(`automation.py`'s Strategy-1 `can_trade()` daily-cap mismatch; a Strategy-1-vs-10/11 substring
collision in `execute_auto_trade()`) — both confirmed unrelated to and unaffected by this phase's
B1 rename, both out of this phase's declared Blast Radius, recorded as Open Gaps with a
backlog-note recommendation rather than blocking this phase. **Ready for EXECUTE MODE.**

---

## Touchpoints

- `trading-app/workers/auto_trader.py`
- `trading-app/engine/risk_orchestrator.py`
- `trading-app/tests/test_risk_orchestrator.py` (new, or extended existing file per RESEARCH)
- `process/features/strategy-rebuild/backlog/` (new NOTE for out-of-scope config-drift check)

---

## Public Contracts

- No external API surface change — `propose_trade()`'s signature and calling convention are
  unchanged; only the string VALUE of the `strategy_name` argument changes at affected call sites.
- Internal contract change: `_get_agent_config()`'s fallback path gains a warning log and a second
  normalization lookup attempt before returning the zeroed default — callers see no interface
  change, only more-correct win_rate/total_trades values for previously-mismatched strategies.
- No schema change to `swarm_agent_configs` — seeding and full-name convention are unchanged; only
  the caller-side strings are corrected to match the existing convention.

---

## Verification Evidence

| Gate / Scenario | Strategy | Proves SPEC criterion |
|---|---|---|
| py_compile on `auto_trader.py` + `risk_orchestrator.py` | Fully-Automated | Fix does not introduce a syntax/compile error — proven by: py_compile exit 0 |
| New `test_risk_orchestrator.py` — affected-strategy lookup resolves real DB row post-fix | Fully-Automated | The exact-string mismatch is actually fixed for confirmed-affected strategies — proven by: assertion that `_get_agent_config()` returns seeded win_rate/total_trades, not the zeroed default |
| New `test_risk_orchestrator.py` — exact-match-on-split does not collide "Strategy 1" with "Strategy 10"/"Strategy 11" | Fully-Automated | The defensive hardening does not reintroduce the Phase-1-fixed collision bug class — proven by: adapted collision-regression assertion |
| New `test_risk_orchestrator.py` — fallback warning log fires on genuine mismatch, returns safe default | Fully-Automated | Future mismatches are visible in logs and do not crash the orchestrator — proven by: caplog assertion + returned-default assertion |
| `git diff --stat` scope check | Fully-Automated | Change is scoped to the declared Blast Radius only — proven by: diff file list matches Blast Radius section |
| Fresh RESEARCH audit confirming Strategy 8/9/1 affected status | Agent-Probe | The final fix list is accurate (not over- or under-scoped) — proven by: RESEARCH finding cross-checked against `models.py`/`nightly_learning.py` seeding, recorded in phase report |
| New `test_risk_orchestrator.py` — flush-signals-caps regression (added by PVL supplement, 31-08-26) | Fully-Automated | `flush_signals()`'s daily-cap side effects for Strategy 3/4/6 (`strat_orb_triggered`, `strat_4_trades`, `strat_6_trades_today`) are NOT silently broken by the B1 call-site rename — proven by: assertions that all three state fields still update correctly when queried with the new full-name strings (see checklist item C1, flush-signals-caps case, and B1b's literal-string fix) |

```bash
python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/risk_orchestrator.py
# Expected: exit 0, no output

cd trading-app/tests && python3 -m pytest test_risk_orchestrator.py -v > /tmp/phase15_pytest.log 2>&1; echo "exit:$?"; cat /tmp/phase15_pytest.log
# Expected: exit 0, all tests pass
```

---

## Test Infra Improvement Notes

(none identified yet — RESEARCH is expected to confirm zero existing `risk_orchestrator.py` test
coverage prior to this phase; if RESEARCH instead finds partial coverage, record the gap here during
EXECUTE.)

---

## Resume and Execution Handoff

- Selected plan file path:
  `process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/phase-15-risk-orchestrator-name-mismatch_PLAN_31-08-26.md`
- **Phase closed 01-09-26 — ✅ VERIFIED.** Last completed step: UPDATE PROCESS (Step 7). Full
  7-step inner loop (R→I→P→PVL→E→EVL→UP) closed with no unresolved gaps within this phase's own
  Blast Radius.
- Validate-contract status: written, Gate: PASS (31-08-26, cycle 2, `generated-by: inner-pvl:
  phase-15`, supersedes cycle-1's BLOCKED contract) — EVL independently re-confirmed all gates
  green against this contract on 01-09-26.
- Execution changes committed and pushed to `origin/main` at `e9c6d63` (verified: local HEAD
  matched `origin/main` at UPDATE PROCESS time — no further commit needed for source).
- This phase's own scope is fully closed. Two out-of-Blast-Radius findings surfaced during PVL/EVL
  were NOT fixed here (by design) and are tracked as backlog notes — see the umbrella plan's
  `## HIGH-PRIORITY Open Item` and `## Backlog Items (cross-phase index)` sections.
- Next step for a fresh agent: this phase requires no further action. Resume Phase 4
  (`phase-04-strategy4_PLAN_28-08-26.md`) from its next un-checked Phase Loop Progress step
  (Step 1 RESEARCH is now ticked in the Phase 4 plan itself — see that file; next is Step 2
  INNOVATE for Phase 4). The orchestrator's call whether to run the flagged Phase-1 verification
  item before, or in parallel with, Phase 4's resume — see the umbrella's HIGH-PRIORITY section.

---

## Validate Contract

Status: PASS
Date: 31-08-26
date: 2026-08-31
generated-by: inner-pvl: phase-15
supersedes: 2026-08-31 (inner-pvl: phase-15) — cycle-1 BLOCKED contract superseded by this cycle-2
contract after the PVL-supplement cycle (B1b + B1c + C1 flush-signals-caps addition) closed the
cycle-1 FAIL.

Parallel strategy: sequential
Rationale: Signal count 1/7 — single small phase (2 source files + 1 new test file), no
independent parallel-safe dimensions worth fanning agents across; direct investigation (grep +
read of the actual call sites, DB seeding, and downstream consumers) is faster and more precise
than a multi-agent fan-out for a scope this narrow. `vc-agent-strategy-compare` signal table:
files touched=2 (low), new-surface=0, cross-package=0, ambiguity=0, reversibility=easy (all git),
risk-class=live-money-correctness (elevated but doesn't require parallel debate, requires
precision), size=small → sequential wins on cost with no coverage loss.

### Cycle 2 — Independent Re-Verification of the PVL-Supplement (B1b + B1c + C1)

Performed fresh, from source, not trusting the plan's cached cycle-1 findings — direct grep and
read of `risk_orchestrator.py`, `automation.py`, `auto_trader.py`, and `models.py` in this session.

**Check 1 — B1c grep sweep, run independently (this is the most important check: does any OTHER
hardcoded "Strategy N" comparison exist that B1's rename would silently break, beyond the 3
already found?):**

- Full-file read of `risk_orchestrator.py` (only 179 lines): confirms the ONLY hardcoded
  exact-match checks anywhere in the file are the 3 at lines 164/167/170 (Strategy 3/4/6 in
  `flush_signals()`) — the ones B1b already fixes. The CHOPPY_SIDEWAYS check at line 72
  (`any(s in strategy_name for s in ("Strategy 3", "Strategy 6", "Strategy 7"))`) is substring
  containment, not exact-match — re-confirmed safe post-fix (a full name still contains its short
  prefix as a substring). **No 4th hardcoded check exists inside `risk_orchestrator.py`.**
- Broadened the B1c-specified grep patterns (`== "Strategy`, `in ["Strategy`, `in ("Strategy`)
  with `.startswith("Strategy` and a same-value trace of every hit, across all three files. This
  surfaced 5 additional hit locations beyond the 3 already fixed:
  - `auto_trader.py:642, 679, 1328` (`t.get("strategy") == "Strategy 5/6/3: <full name>"`) and
    `auto_trader.py:714` (`t.get("strategy") in ["Strategy 3: ...", "Strategy 9: ..."]`) and
    `auto_trader.py:2030` (`"Strategy 5: ..." in state.active_strategies`): traced `t["strategy"]`
    / `sig["strategy"]` back to source — each strategy's OWN engine file
    (`strategy_orb.py:328`, `strategy_5.py:209`, `strategy_gap.py:165`, `strategy_9.py:614`)
    already hardcodes the FULL descriptive name into `sig["strategy"]` independently of what
    string `propose_trade()`'s first positional argument receives. These checks are fed by a
    completely different string flow than the one B1 changes — **confirmed safe, unaffected by
    B1, no action needed.**
  - `automation.py:733` (`can_trade()`) and `automation.py:994` (`add_active_trade()`):
    `str(strategy_name).startswith("Strategy 1:")` — this is a **real, pre-existing, currently-broken
    check, but NOT caused by this phase's B1 rename.** Traced the call site:
    `auto_trader.py:2153` calls `state.can_trade("Strategy 1", signal_type=..., symbol=...)` with
    the bare short string, directly and independently of `propose_trade()`'s argument two lines
    below it (same distinction the plan's original RESEARCH already correctly drew between these
    two call sites). `"Strategy 1".startswith("Strategy 1:")` is `False`, so the Strategy 1 daily
    2-trade cap (`STRAT_1_MAX_TRADES_PER_DAY`) inside `can_trade()` has **never actually fired** —
    a bug that predates this phase, is not touched by B1 (B1 only renames the `propose_trade`
    call site, not the separate `can_trade` call site), and remains exactly as broken after this
    phase's fix as before it. Not a FAIL against this phase's own change; recorded as a new Open
    Gap below (not silently dropped).
  - `auto_trader.py:1190` inside the shared `execute_auto_trade()`: `if "Strategy 1" in
    strategy_name:` — naive substring containment. Since `"Strategy 1"` is a literal string-prefix
    of `"Strategy 10: Adaptive ADX Engine"` and `"Strategy 11: FRVP LVN Vacuum"` (both already full
    names today, unaffected by B1), this check also fires for every Strategy 10/11 trade,
    reintroducing — via a second, different code path — the exact "Strategy 1 vs Strategy
    10/11 collision" bug class that `automation.py`'s `has_active_trade_for_strategy()` was
    hardened against on 28-08-26 (Phase 1 of this program). Also pre-existing, also unaffected by
    B1 (Strategy 10/11's `sig["strategy"]` was already full-form before this phase). Recorded as
    the same new Open Gap below.
  - No other `.startswith("Strategy`, `== "Strategy`, `in ["Strategy`, or `in ("Strategy` hit
    exists anywhere in the three files beyond what is listed above — this is now an exhaustive
    account, not a sampled one.

  **Conclusion on Check 1:** the plan's B1c checklist item, scoped to its own stated goal (find
  every hardcoded check that B1's rename would silently break), is CORRECT and COMPLETE — the 3
  checks it already targets in `flush_signals()` are the only ones actually affected by the
  rename. The additional hits my broader sweep found are real bugs but are independent of and
  unaffected by B1 — they do not belong in B1c's fix scope, but they do need to be on record (see
  Open Gaps).

**Check 2 — exact-string cross-check against `models.py` seeding (a typo here would silently
break the caps again, just differently):**

`models.py:465-476` `default_strats` seeds, byte-for-byte: `"Strategy 3: 5-Minute ORB"`,
`"Strategy 4: Wisdom-Aligned Pullback"`, `"Strategy 6: Gap Fill Reversal"`. The plan's B1b
checklist item specifies the identical three literal strings for the corresponding
`risk_orchestrator.py` `flush_signals()` checks. **Exact match confirmed, character for
character — no typo.**

**Check 3 — does the new flush-signals-caps regression test (C1) genuinely exercise the fix (not
vacuous/tautological)?**

The checklist's C1 description requires the test to: (a) call the real `flush_signals()`
function end-to-end (not a mock of the comparison itself), (b) drive it with a signal whose
`strategy_name` is the NEW full-name string (post-B1 value, not the old short form), and (c)
assert concrete, independently-meaningful state-field side effects
(`state.strat_orb_triggered is True`, `state.strat_4_trades == 2`, `state.strat_6_trades_today ==
2`) rather than re-asserting something the code trivially guarantees. This is a genuine
regression-test specification — it would fail today if B1b's literal strings were wrong or
missing, which is exactly the property required to close the cycle-1 FAIL. (The test file does
not exist yet — RESEARCH/A5 confirmed zero pre-existing coverage — so this is a specification
review, not a run; EVL will confirm the implemented test actually asserts this once EXECUTE
writes it.)

### V2 Fan-Out Findings (independent re-verification — do not trust Phase 4 or plan-drafting cache)

**Item 1 — Definitive affected-strategy list (re-grepped fresh, this session):**

All `risk_orchestrator.propose_trade(` call sites in `trading-app/workers/auto_trader.py`,
current line numbers:

| Line | Strategy | String passed | DB seed (`models.py:466-476` `default_strats`) | Verdict |
|---|---|---|---|---|
| 1999 | 2 | `"Strategy 2"` | `"Strategy 2: 9:26 - 180 Buy"` | **MISMATCH** |
| 2023 | 3 | `"Strategy 3"` | `"Strategy 3: 5-Minute ORB"` | **MISMATCH** |
| 2035 | 5 | `"Strategy 5"` | `"Strategy 5: Optimized Aerospace Mean Reversion"` | **MISMATCH** |
| 2055 | 4 | `"Strategy 4"` | `"Strategy 4: Wisdom-Aligned Pullback"` | **MISMATCH** |
| 2062 | 6 | `"Strategy 6"` | `"Strategy 6: Gap Fill Reversal"` | **MISMATCH** |
| 2085 | 7 | `"Strategy 7"` | `"Strategy 7: Swing-Pivot Breakout"` | **MISMATCH** |
| 2101 | 8 | `"Strategy 8"` | `"Strategy 8: Smart Money Concepts"` | **MISMATCH — confirms Fresh RESEARCH item 1** |
| 2108 | 9 | `"Strategy 9"` | `"Strategy 9: 9-EMA Momentum Scalper"` | **MISMATCH — confirms Fresh RESEARCH item 1** |
| 2115 | 10 | `"Strategy 10: Adaptive ADX Engine"` | not in bootstrap `default_strats` (only 1-9 are) | MATCH in form; row is created later via `Database.update_agent_config()` upsert (nightly self-improvement) using this same full string — no mismatch once a row exists |
| 2122 | 11 | `"Strategy 11: FRVP LVN Vacuum"` | same as above | MATCH in form, same cold-start caveat |
| 2165 | 1 | `"Strategy 1"` | `"Strategy 1: OB + FVG"` | **MISMATCH — confirms Fresh RESEARCH item 2 (new finding); real, distinct call site, NOT the `state.can_trade("Strategy 1", ...)` gate at line 2153 which is a separate mechanism as the plan already noted** |
| 2256 | Crude pending | `pending["strategy_name"]` → traced to `_queue_crude_pending("Commodity: Evening Momentum" \| "Commodity: EIA Volatility (Wed)", sig)` (lines 2271/2278) | not in `default_strats` under any form | Out of the numbered-strategy MISMATCH bug class (never seeded under any name — a different, pre-existing zeroed-default cause). **Not silently missed: still covered by Step A1's "re-grep ALL call sites" instruction, which does not restrict itself to numbered strategies** — flagging as an Open Gap below so it isn't accidentally left unresolved by a narrower reading of Step A1. |
| 2307 | AI strategy signal | `ai_name` (loop var from AI-strategy `hits`) | not in `default_strats` | Same as above — out of the numbered-strategy bug class, flagged as Open Gap for RESEARCH to classify explicitly, not silently skip. |

**Verdict: ALL NINE numbered strategies (1 through 9) are affected — not just 8/9 as originally
flagged, and Strategy 1 is confirmed real, not a stale grep artifact.** Only Strategy 10 and 11
already pass full names. This fully resolves Fresh RESEARCH Step A items 1–2; RESEARCH (Step A)
still needs to formally record this in the phase report per A6, but the fix scope itself is no
longer ambiguous.

Test coverage confirmed zero (Fresh RESEARCH item 4): `find trading-app/tests -iname
"*risk_orch*"` → no matches.

**Item 2 — exact-match-on-split pattern reuse: confirmed SAFE.** Read
`trading-app/engine/automation.py:654-670` (`has_active_trade_for_strategy`, the actual Phase-1
fix). Its logic: `t_strat == strategy_name or t_strat.split(":")[0].strip() ==
strategy_name.split(":")[0].strip()` — an exact-equality comparison on the split prefix, never
`startswith`/`LIKE`/substring. This is genuinely collision-safe: `"Strategy 1".split(":")[0]`
(`"Strategy 1"`) never equals `"Strategy 10".split(":")[0]` (`"Strategy 10"`). The plan's Step B2
description ("split both sides on `:`, exact-match the prefix... never startswith/LIKE/substring")
matches this pattern conceptually. **Requirement for EXECUTE:** the implementation must do the
same split-then-equality comparison, not a lookalike that calls `.startswith()` on the unsplit
string (which would reintroduce the exact collision Phase 1 fixed). The plan's C1 second bullet
already requires a Strategy-1-vs-10/11 collision regression test — keep it mandatory, it is the
only thing that will catch an incorrect implementation. Feasibility: `Database.get_all_agent_configs()`
already exists (`models.py`), so the split-based retry fallback needs no new DB API surface.

**Item 3 — downstream unintended effects of changing `strategy_name` to full form: FOUND A REAL
REGRESSION in cycle 1 — RESOLVED in cycle 2 by the B1b/C1 supplement (see Cycle 2 Check 1/3
above), plus one confirmed-safe path.**

- Confirmed SAFE: `risk_orchestrator.py:72`, the CHOPPY_SIDEWAYS confidence-override check, uses
  `any(s in strategy_name for s in ("Strategy 3", "Strategy 6", "Strategy 7"))` — substring
  containment (`in`), not exact equality. `"Strategy 3" in "Strategy 3: 5-Minute ORB"` is still
  `True` after the fix. No break here.
- **FOUND — NOT SAFE:** `risk_orchestrator.py:164-172`, inside `flush_signals()`, post-execution
  state updates use hardcoded exact-string equality against the SHORT form:
  ```python
  if s_name == "Strategy 3":
      state.strat_orb_triggered = True
  elif s_name == "Strategy 4":
      state.strat_4_trades = getattr(state, "strat_4_trades", 0) + 1
  elif s_name == "Strategy 6":
      state.strat_6_trades_today = getattr(state, "strat_6_trades_today", 0) + 1
  ```
  `s_name` here is `winning_sig['strategy_name']`, fed directly from `propose_trade()`'s
  `strategy_name` argument — the EXACT SAME value Step B1 is about to change from short to full
  form for Strategy 3, 4, and 6. Once those call sites pass full names, these three `==` checks
  will never match again. These three state fields are not cosmetic — they are load-bearing daily
  trade-frequency risk caps, confirmed by tracing every consumer:
  - `state.strat_orb_triggered` → checked in `trading-app/engine/strategy_orb.py:64` as a
    once-per-day fire gate for Strategy 3 (ORB).
  - `state.strat_4_trades` → checked in `trading-app/engine/strategy_wisdom.py:107`
    (`if strat_4_trades >= 2:`) — a 2-trades/day cap for Strategy 4.
  - `state.strat_6_trades_today` → checked in `trading-app/engine/strategy_gap.py:42`
    (`if getattr(state, 'strat_6_trades_today', 0) >= 2:`) — a 2-trades/day cap for Strategy 6.

  Fixing the name-mismatch bug as currently scoped (Step B1 alone) would silently defeat all three
  caps: the counters/flags would freeze at their last pre-fix value and these strategies could fire
  more often than their designed daily limit — a genuine live-money risk-exposure regression, not a
  cosmetic string change. This directly contradicts the plan's own "Public Contracts" claim of "no
  behavior change to any strategy's trading logic itself." **This must be fixed in the same PR as
  Step B1, not deferred**, or Step B1 must NOT be applied to Strategy 3/4/6 until it is.
  (Strategy 1/2/5/7/8/9 have no equivalent `==` literal found anywhere in the codebase — confirmed
  via `grep -rn '== "Strategy'` across `trading-app/` — so only 3, 4, and 6 carry this collateral
  risk.)
  **RESOLVED in cycle 2:** Step B1b now updates these three literal checks to the post-fix full
  names, cross-checked byte-for-byte against `models.py` seeding (Cycle 2 Check 2), and Step C1's
  flush-signals-caps case (Cycle 2 Check 3) is a genuine, non-vacuous regression test for exactly
  this failure mode.

**Item 4 — live-money relevance / hard-safety-constraint check: PASS.** This is a genuine
correctness fix (restoring intended win-rate/Kelly tie-break fairness across strategies that have
been silently zeroed) and does not change any strategy's signal-generation logic — it only
corrects the risk-orchestrator's lookup key and (per the FAIL above, once supplemented) preserves
the existing daily-cap side effects exactly as they behave today. No core-intent sign-off is
required beyond this phase's own INNOVATE decision (already recorded). The umbrella's hard safety
constraints are not blocked by this fix — they are, in fact, exactly what the Item 3 finding is
protecting.

### Net-Gate Vacuous-Green Check

This cycle's Gate is a terminal PASS. Checked for vacuous-green: every developed behavior in the
Blast Radius has a Fully-Automated or Agent-Probe proving gate in the Test gates table below (none
rest on Known-Gap alone) — not vacuous. The 2 new pre-existing findings recorded under Open Gaps
below are explicitly out of this phase's Blast Radius (neither `automation.py`'s `can_trade()`/
`add_active_trade()` nor the `execute_auto_trade()` trend-alignment block are files/functions this
phase's checklist touches) and are carried as named residuals with a backlog-note commitment, not
as the reason any developed behavior passes.

Test gates (C3 5-column table):

| criterion id | behavior | strategy | proving test | gap-resolution |
|---|---|---|---|---|
| affected-list | Final affected-call-site list matches this V2 table (Strategies 1-9 mismatched, 10-11 correct) | Agent-Probe | RESEARCH re-grep cross-checked against `models.py` seeding, recorded in phase report (A6) | A |
| call-site-fix | Each MISMATCH call site now passes the full descriptive name | Fully-Automated | `grep -rn "propose_trade(\"Strategy [0-9]\"" trading-app/workers/auto_trader.py` returns zero short-form numbered matches (10/11 already full, excluded) | B |
| lookup-hardening | `_get_agent_config()` split-based retry resolves a full-name row when queried with a short name, without new API surface | Fully-Automated | new `test_risk_orchestrator.py` case: seed DB with full name, query with short name, assert real `win_rate`/`total_trades` returned | B |
| collision-safety | Split-based retry does not collide "Strategy 1" with "Strategy 10"/"Strategy 11" | Fully-Automated | new `test_risk_orchestrator.py` collision-regression case (adapted from automation.py's Phase-1 pattern) | B |
| fallback-log | Fallback branch logs a warning and still returns the safe zeroed default on genuine mismatch | Fully-Automated | new `test_risk_orchestrator.py` case with `caplog` + returned-default assertion | B |
| flush-signals-caps | `strat_orb_triggered` / `strat_4_trades` / `strat_6_trades_today` still update correctly after Strategy 3/4/6 call sites switch to full names | Fully-Automated | `test_risk_orchestrator.py` flush-signals-caps case (checklist C1, added by cycle-1 supplement; confirmed non-vacuous in Cycle 2 Check 3) | B — in plan checklist as of the cycle-1 PVL-supplement; confirmed present and correctly scoped in cycle 2 |
| b1c-sweep-complete | No hardcoded "Strategy N" comparison besides the 3 in `flush_signals()` is broken by B1's rename | Agent-Probe | Cycle-2 independent grep sweep of all 3 Blast-Radius-adjacent files using `== "Strategy`, `in ["Strategy`, `in ("Strategy`, and `.startswith("Strategy` patterns, each hit traced to its string source | A — proven this cycle |
| compile | No syntax/compile error introduced | Fully-Automated | `python3 -m py_compile trading-app/workers/auto_trader.py trading-app/engine/risk_orchestrator.py` | A |
| scope | Diff touches only declared Blast Radius files | Fully-Automated | `git diff --stat` matches Blast Radius section | A |

gap-resolution legend: A — proven now. B — fixed in this plan's checklist (once supplemented for
the new row above). C — deferred to a named later phase/plan. D — backlog test-building stub.

C-4 reconciliation: no `Known-Gap` strategy values used above.

Legacy line form:
- risk_orchestrator fix: [Fully-automated: `pytest trading-app/tests/test_risk_orchestrator.py -v`] | [known-gap: none]

Dimension findings:
- Infra fit: PASS — no new dependency, agent, or runtime surface; reuses an existing DB helper
  (`Database.get_all_agent_configs()`) and an already-proven pattern from `automation.py`.
- Test coverage: PASS — zero existing `risk_orchestrator.py` coverage confirmed (expected), but the
  plan's own checklist (C1, including the flush-signals-caps case) fully closes the gap
  (gap-resolution B — fixed in this plan's checklist).
- Breaking changes: PASS — cycle-1's FAIL (Step B1 alone would have silently broken the
  `strat_orb_triggered` / `strat_4_trades` / `strat_6_trades_today` daily-cap gates for Strategy
  3/4/6) is resolved by the B1b/C1 supplement, independently re-verified in cycle 2 (Checks 1-3
  above). No other hardcoded check in `risk_orchestrator.py`, and no check fed by `propose_trade()`'s
  argument elsewhere, is broken by the rename.
- Security surface: PASS — no auth, schema, API-contract, or secret-handling surface touched.

Open gaps:
- Crude-strategy (`"Commodity: Evening Momentum"` / `"Commodity: EIA Volatility (Wed)"`) and
  AI-strategy (`ai_name`) `propose_trade` call sites are not seeded in `default_strats` under any
  name — they hit the same zeroed-default fallback for an unrelated reason (never seeded, not a
  name mismatch). Not a plan defect (Step A1's "re-grep ALL call sites" already covers them
  literally), but RESEARCH must explicitly classify them as "out of numbered-strategy MISMATCH
  scope, separate pre-existing gap" in the phase report rather than silently omitting them from
  the A6 list, so a future reader doesn't assume they were overlooked.
- Strategy 10/11 have no bootstrap-seeded DB row (only Strategy 1-9 are in `default_strats`) — their
  row is created on first live/paper trade via the nightly `update_agent_config()` upsert. This is
  pre-existing cold-start behavior, unrelated to and unaffected by this phase's fix; noted for
  awareness only.
- **NEW (cycle 2) — Strategy 1 daily-cap and Strategy 1-vs-10/11 collision bugs, both pre-existing
  and both unaffected by this phase's fix:** known-gap: documented as NEW PLAN REQUIRED.
  (a) `automation.py:733`'s `can_trade()` Strategy-1 daily-cap check requires
  `strategy_name.startswith("Strategy 1:")`, but its only call site
  (`auto_trader.py:2153`, `state.can_trade("Strategy 1", ...)`) passes the bare short string with
  no colon — the cap (`STRAT_1_MAX_TRADES_PER_DAY`, default 2/day) has never actually fired. This
  call site is separate from and untouched by `propose_trade()`'s call two lines below (which B1
  does rename) — B1 does not fix, and does not worsen, this bug.
  (b) `auto_trader.py:1190`, inside the shared `execute_auto_trade()`: `if "Strategy 1" in
  strategy_name:` uses naive substring containment, which also matches `"Strategy 10: Adaptive ADX
  Engine"` and `"Strategy 11: FRVP LVN Vacuum"` (both already full-form today, independent of this
  phase) — reintroducing, via a second code path, the same "Strategy 1 vs 10/11" collision class
  that `has_active_trade_for_strategy()` was hardened against on 28-08-26. Also pre-existing,
  also unaffected by B1.
  Both are real, live, load-bearing bugs in the same bug family this phase addresses, but neither
  is caused by, nor blocks, this phase's declared fix — `automation.py`'s `can_trade`/
  `add_active_trade` and this region of `execute_auto_trade()` are outside this phase's Blast
  Radius. **Recommend a dedicated backlog note** (e.g.
  `strategy-1-daily-cap-and-collision-bugs_NOTE_{dd-mm-yy}.md` under
  `process/features/strategy-rebuild/backlog/`) written during EXECUTE/UPDATE-PROCESS alongside the
  already-planned config-drift-validation-check note, so these are not silently dropped a second
  time.

What This Coverage Does NOT Prove:
- The `affected-list` Agent-Probe gate does not prove the DB's *live* `swarm_agent_configs` table
  matches `models.py`'s `default_strats` seed list on the actual production DB (only that the
  seeding code would produce that result on a fresh DB) — RESEARCH should spot-check the live table
  if DB access is available, per the plan's own Blockers section fallback (narrow the fix to
  confirmed-affected sites if it isn't).
- The collision-safety test proves Strategy 1 vs 10/11 specifically; it does not exhaustively prove
  every possible two-digit-prefix collision pattern (e.g. a hypothetical future "Strategy 12"
  colliding with "Strategy 1" was already ruled out by the split-then-equality approach, but is not
  independently asserted by a dedicated test beyond the 1-vs-10/11 case named in the plan).
- The flush-signals-caps gate (once added) proves state fields update; it does not add a new
  end-to-end test proving the *strategy_orb.py / strategy_wisdom.py / strategy_gap.py* gates
  themselves still correctly block based on those fields post-fix — that behavior was already
  covered by pre-existing strategy-level tests (unchanged by this phase) and is out of this
  phase's Blast Radius.
- This validate cycle's Cycle-2 sweep proves no hardcoded check *fed by `propose_trade()`'s
  argument* breaks under B1's rename. It does NOT prove (and does not need to, for this phase's
  scope) that `automation.py`'s Strategy-1 daily-cap check or `execute_auto_trade()`'s Strategy-1
  substring check are correct — both are pre-existing, independent bugs recorded under Open Gaps
  above and deferred to a backlog note, not proven or fixed by any gate in this table.

**Structural note (advisory, not blocking):** `node
.claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs` on this plan file reports 4
FAILs (missing "overview/context", "Complexity metadata", "Phase Completion Rules", "Acceptance
Criteria" headings) and 4 warnings (legacy plan shape). This validator targets the generic
SIMPLE/COMPLEX plan template; this file follows the phase-program phase-plan shape used
consistently across all ~15 phases of the `strategy-rebuild` umbrella (Purpose/Blast
Radius/Implementation Checklist/Exit Gate/Verification Evidence stand in for the missing
headings). Treated as advisory per established precedent for this program, not as a gate FAIL —
flagging here so it is on record rather than silently run-and-discarded.

Gate: PASS (cycle-1's unresolved FAIL — Item 3's flush_signals() collateral regression on Strategy
3/4/6 — is resolved by the B1b/C1 supplement and independently re-verified in cycle 2; the
broadened B1c-equivalent sweep found no other hardcoded check broken by B1's rename; 2 new
pre-existing, out-of-Blast-Radius bugs were found and are carried as Open Gaps with a backlog-note
commitment, not as blockers to this phase's own fix)

Accepted by: session (autonomous inner-PVL continuation, cycle 2) — accepted as documented,
non-blocking Open Gaps: (1) crude/AI-strategy call sites out of numbered-strategy scope, (2)
Strategy 10/11 cold-start DB row behavior, (3) NEW — Strategy 1 `can_trade()` daily-cap
`.startswith("Strategy 1:")` mismatch (pre-existing, unaffected by B1), (4) NEW — Strategy
1-vs-10/11 substring collision in `execute_auto_trade()` (pre-existing, unaffected by B1). Items
(3) and (4) are recommended for a dedicated backlog note during EXECUTE/UPDATE-PROCESS.

Reference for latest state: process/features/strategy-rebuild/active/strategy-rebuild_28-08-26/strategy-rebuild-umbrella_PLAN_28-08-26.md
(`## Stable Program Goal` — BRANCH B: umbrella exists, so no `## Autonomous Goal Block` is written
to this phase plan file.)
