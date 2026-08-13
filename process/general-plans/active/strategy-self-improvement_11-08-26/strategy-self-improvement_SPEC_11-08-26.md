---
name: plan:strategy-self-improvement-spec
description: "Requirements doc — fix nightly strategy self-improvement pipeline (stale backtests, mislabeled stats, zero-trade strategies scope) — LOCKED"
date: 11-08-26
feature: general
---

# SPEC — Fix Strategy Self-Improvement Pipeline

**Status: LOCKED (all Open Questions resolved via user SPEC review, 11-08-26). Ready for INNOVATE.**

## Summary

Every night, the trading app is supposed to look at how each strategy has been performing and
automatically tune or shut down the ones that are losing money. That nightly process (the
"self-improvement" / nightly learning job) does run reliably, and its safety net (automatically
shadowing out a strategy that is net-losing) works even when the AI provider is down. But the
numbers it's tuning against are stale: the underlying backtest data hasn't refreshed since
2026-08-05, six days ago, and nothing on the server is re-running it. On top of that, when those
stale backtest numbers get written back into each strategy's live config, there's no label saying
"this came from a backtest, not from real trading" — so a dashboard or report can show a strategy
as having 158 trades and a 17.7% win rate when in reality it only ever placed 4 real trades. This
SPEC defines what needs to change so self-improvement tunes against genuinely current evidence
(refreshed nightly, immediately before each tuning run), and so backtest-derived numbers never get
confused with real trading performance. The separate issue of 7 strategies never placing a single
trade is confirmed OUT of scope for this effort — it is a distinct root cause and will be raised as
its own follow-up RESEARCH task.

## User Stories / Jobs To Be Done

1. **As the strategy owner (user),** I want the nightly self-improvement process to evaluate each
   strategy against backtest evidence that was refreshed that same night, immediately before
   tuning runs, so that its nightly tuning decisions reflect current market conditions rather than
   a six-day-old (and growing staler) snapshot.

2. **As the strategy owner,** I want to be able to look at any strategy's stats (win rate, trade
   count) and know immediately whether I'm looking at real trading results or a backtest estimate,
   so I don't mistake a synthetic number for live performance when deciding whether to trust or
   intervene in a strategy.

3. **As the strategy owner,** I want the self-improvement pipeline to keep working safely even
   though the automated backtest refresh currently requires a live authenticated broker session,
   so that a lapsed/expired session doesn't silently break nightly tuning or fail in a way I don't
   notice — if refresh can't run on a given night, nightly learning should fall back to the last
   good backtest data (not block, not silently continue as if nothing happened) and the failure
   itself must be visible.

4. **As the strategy owner,** when I ask "is self-improvement actually working, are strategies
   being properly investigated and fixed," I want a clear, reviewable answer about what's broken,
   what's already fine, and what's explicitly being deferred — so I can decide with full
   information rather than assume everything nightly touches is trustworthy.

## What The User Wants (Behavioral Outcomes)

- The backtest evidence that nightly self-improvement reads from is refreshed **nightly,
  immediately before each `nightly_learning.py` tuning run** — not a single one-time manual run,
  and not left on an open/flexible cadence. The data self-improvement tunes against should never
  silently go stale indefinitely.
- If the nightly refresh cannot run on a given night (e.g. no live authenticated Fyers session at
  refresh time), nightly learning **falls back to the last good backtest data** rather than
  blocking or silently continuing with no signal — and the failure is recorded somewhere a human
  can see it (log line, alert, or status field).
- Wherever a strategy's performance stats are surfaced (config, dashboard, reports), it's visually
  or structurally clear whether those numbers came from a backtest run or from real executed
  trades — no more "158 trades" showing for a strategy that has only traded 4 times live. This
  applies directly to `swarm_agent_configs` and any downstream report/dashboard reading it.
- The nightly self-improvement job's existing safety behavior (net-losing strategies get shadowed
  out, independent of AI availability) continues to work exactly as it does today — this SPEC does
  not touch or risk regressing that.
- The question of why 7 of 11 strategies have never placed a trade is **confirmed out of scope**
  for this effort (see Out Of Scope) — it will be raised as a separate follow-up RESEARCH task
  once this effort ships, not silently ignored.

## Flow / State Diagram

Current (broken) nightly flow:

```
Every night (confirmed running, Aug 5-10):
  auto_trader.py -> automation.py::check_and_run_nightly_learning
        |
        v
  nightly_learning.py
        |
        +--> reads backtest_results (Database.get_backtest_performance())
        |         |
        |         v
        |    ALWAYS returns run_date = 2026-08-05  <-- STALE, never refreshed
        |         (no cron / systemd timer / in-app scheduler calls
        |          run_all_backtests() -- only manual CLI invocation exists)
        |
        +--> strict rule-based capital-protection block
        |         (shadow-out net-losing strategies)  <-- CONFIRMED WORKING,
        |                                                  AI-independent
        |
        +--> update_agent_config() writes win_rate/total_trades/winning_trades
                  into swarm_agent_configs FROM THE STALE BACKTEST SNAPSHOT
                  |
                  v
             swarm_agent_configs now shows backtest-derived numbers
             with NO flag distinguishing them from real-trade-derived
             numbers  <-- MISLEADING on any dashboard/report reading
                           this table (e.g. Strategy 8: config shows
                           158 trades / 17.7% win rate, but real
                           executed_trades history = 4 trades, last
                           on 2026-08-04)
```

Locked target flow (WHAT, not HOW — no scheduler/schema choice implied; mechanism is INNOVATE's job):

```
Every night, immediately before nightly_learning.py runs:
  backtest evidence refresh
        |
        +--SUCCEEDS--> backtest_results updated with fresh run_date
        |                       |
        |                       v
        |              nightly_learning.py reads CURRENT evidence,
        |              not a frozen 6-day-old snapshot
        |
        +--FAILS (e.g. no authenticated Fyers session at refresh time)
                 |
                 +--> failure is visible/logged (not silent)
                 |
                 +--> nightly_learning.py FALLS BACK to last good
                       backtest data (does not block, does not
                       silently proceed with no signal)
                       |
                       v
  strict capital-protection block runs as today (UNCHANGED, must not regress)
                       |
                       v
  swarm_agent_configs updated, each stat CLEARLY MARKED as
  backtest-derived vs real-trade-derived
                       |
                       v
  any dashboard/report reading these stats can tell the two apart
  at a glance (fixes the Strategy 8 case: 158/17.7% backtest vs
  4 real trades)
```

Zero-trade-strategies question — CONFIRMED out of scope, separate follow-up:

```
Strategy 1-7: zero real trades ever (live or paper)
        |
        v
  CONFIRMED OUT OF SCOPE for this SPEC/effort.
        |
        v
  Follow-up RESEARCH task to be opened once this effort ships
  (distinct root cause: signal-generation, not tuning).
```

## Acceptance Criteria (Testable Outcomes)

1. **Backtest evidence used by nightly self-improvement is refreshed nightly, immediately before
   each `nightly_learning.py` run** — verifiably, the `run_date` on the backtest evidence nightly
   learning reads advances every night instead of staying pinned at one fixed date.
   - proven by: manual/log verification — inspect `backtest_results.run_date` across multiple
     nights after the fix ships and confirm it advances nightly (Agent-Probe/Hybrid; no existing
     automated coverage for this surface per `process/context/tests/all-tests.md` Known Gaps —
     `market_data_worker`/self-improvement logic has zero pytest coverage today).
   - strategy: Hybrid

2. **When the nightly backtest refresh cannot run** (e.g. broker session unauthenticated at the
   scheduled time), nightly learning falls back to the last good backtest data instead of blocking
   or silently continuing with stale data unflagged, AND the failure itself is recorded somewhere a
   human can see it (log line, alert, or status field).
   - proven by: manual log/behavior verification — force an unauthenticated-session condition and
     confirm both (a) a visible failure signal appears and (b) nightly learning proceeds using the
     last known-good backtest snapshot rather than erroring out or silently using undefined data
     (Agent-Probe; no automated harness exists for this failure path).
   - strategy: Agent-Probe

3. **The nightly capital-protection safety behavior (shadow-out net-losing strategies,
   AI-independent) is unchanged and continues to pass** after the fix — this SPEC's changes must
   not regress the one piece of self-improvement already confirmed working.
   - proven by: log evidence review across post-fix nightly runs, same method used in RESEARCH to
     originally confirm this behavior (dashboard.log inspection).
   - strategy: Hybrid

4. **Every strategy performance figure surfaced from `swarm_agent_configs` (or any downstream
   dashboard/report reading it) is distinguishable as backtest-derived vs real-trade-derived** —
   a reviewer looking at any strategy's win-rate/trade-count can tell which source it came from
   without cross-referencing `executed_trades` manually.
   - proven by: manual inspection of `swarm_agent_configs` rows and any UI/report surface after the
     fix, confirming the provenance is visible per strategy (Agent-Probe; no existing test coverage
     of this table's write path).
   - strategy: Agent-Probe

5. **A strategy with real trade history that diverges sharply from its backtest-derived stats (the
   Strategy 8 case: 158/17.7% backtest vs 4 real trades) is presented in a way that does not mislead
   a reviewer** into treating the backtest number as the strategy's real track record.
   - proven by: manual spot-check of Strategy 8's stats display before/after the fix.
   - strategy: Agent-Probe

6. **The zero-trade-strategies question (Strategies 1-7) is documented as confirmed out of scope**,
   with a note that a follow-up RESEARCH task should be opened for it once this effort ships — no
   silent omission.
   - proven by: presence of this SPEC's Out Of Scope entry, plus (post-EXECUTE) presence of a
     tracked follow-up backlog/RESEARCH item.
   - strategy: Fully-Automated (document-presence check — `grep` for the scoping statement in this
     SPEC and, later, for the follow-up item in the backlog)

## Out Of Scope

- **Root-causing why Strategies 1-7 have never placed a trade.** **CONFIRMED OUT OF SCOPE** for
  this SPEC/effort (resolved via user SPEC review, 11-08-26 — no longer a recommended default, this
  is the final decision). This is a distinct root cause from backtest staleness (a
  strategy-triggering/signal-generation question, not a self-improvement-tuning question). **A
  follow-up RESEARCH task should be opened for this once this effort ships.**
- **Rewriting `backtest_engine.py`'s premium-modeling approach** (Black-Scholes-modeled option
  premiums instead of real historical option-chain quotes, uniform SL/target rule instead of each
  strategy's real live trailing logic). This is a pre-existing, already-documented limitation in
  the engine's own docstring — this SPEC treats the backtest as a screening/prioritization signal,
  not an exact live P&L forecast, and does not attempt to make it exact.
- **Choosing the refresh mechanism** (cron, systemd timer, in-app scheduler, or triggering from
  within `nightly_learning.py` itself) — the cadence is locked (nightly, immediately before
  tuning), but the mechanism/implementation is INNOVATE's job, not this SPEC's.
- **Designing the provenance-flag schema** (new column, separate table, in-memory tag, etc.) — that
  decision belongs to INNOVATE/PLAN, not this SPEC. (The requirement that provenance be
  distinguishable is IN scope — see Acceptance Criteria #4 — only the schema/mechanism choice is
  deferred.)
- **Solving the headless-authentication gap for `run_backtests.py`** as a general Fyers-auth
  feature — this SPEC only requires that the refresh mechanism accounts for the session requirement
  and falls back to last-good data with a visible failure signal rather than blocking or failing
  silently; it does not mandate building a new unattended-auth system as part of this work (though
  INNOVATE may propose one as part of "how").

## Constraints

- **Refresh cadence is locked: nightly, immediately before each `nightly_learning.py` tuning run.**
  This is not open for INNOVATE to re-decide — only the implementation mechanism is INNOVATE's
  choice.
- **Fallback behavior is locked:** when the refresh cannot run (no authenticated Fyers session at
  refresh time), nightly learning must fall back to the last good backtest data and log/surface the
  failure — it must not block nightly tuning entirely, and must not silently continue as if nothing
  went wrong.
- The nightly capital-protection (shadow-out net-losing strategies) behavior must not regress — it
  is confirmed working today, independent of AI provider availability, and must remain so.
- `run_backtests.py` currently hard-gates on `client.is_authenticated()` — the refresh design must
  account for the possibility that no live authenticated Fyers session exists at the scheduled
  nightly refresh time.
- `backtest_engine.py`'s modeled-premium approach is a known, accepted limitation (per its own
  docstring) — refreshed backtest data should still be weighted as a screening/prioritization
  signal, not treated as exact predicted live P&L.
- No automated test coverage currently exists for `nightly_learning.py`, `backtest_engine.py`,
  `run_backtests.py`, or the `swarm_agent_configs`/`backtest_results` write paths (confirmed via
  `process/context/tests/all-tests.md` — pytest coverage today is scoped to the security-remediation
  auth/session/concurrency surface only). Acceptance criteria for this SPEC are therefore
  necessarily Agent-Probe/Hybrid rather than Fully-Automated, except for the scope-documentation
  check (#6).
- This is a live-money trading system — any change to the nightly self-improvement flow must be
  verifiable without requiring a live authenticated broker session to be present at review time
  (design for graceful, visible failure when the session isn't available).
- The provenance marker for backtest-derived vs real-trade-derived stats is **in scope for this
  same effort** (not deferred) — it must land alongside the refresh-cadence fix, not as a separate
  later effort.

## Open Questions — RESOLVED (11-08-26, via user SPEC review)

All 3 open questions carried from RESEARCH are now resolved. Recorded here for audit trail; no
questions remain blocking.

1. **Backtest refresh cadence — RESOLVED.** Nightly, immediately before each `nightly_learning.py`
   run (locked — see Constraints). INNOVATE still proposes the actual mechanism/implementation, but
   the cadence itself is fixed. Fallback: if no live authenticated Fyers session exists at refresh
   time, the failure must be visible/logged, and nightly learning falls back to the last good
   backtest data rather than blocking or silently continuing with no signal. Folded into
   Behavioral Outcomes, Acceptance Criteria #1–#2, and Constraints above.

2. **Provenance marker — RESOLVED.** In scope for this same effort. Add whatever's needed
   (flag/column/tag) so backtest-derived stats in `swarm_agent_configs` (and any downstream
   report/dashboard reading it) are never presented as if they were real-trade-derived — directly
   addresses the Strategy 8 case. Folded into Behavioral Outcomes, Acceptance Criteria #4–#5, and
   Constraints above.

3. **Zero-trade strategies (1-7) — RESOLVED.** Confirmed OUT of scope for this SPEC/effort. Distinct
   root cause (signal-generation, not tuning) — a follow-up RESEARCH task should be opened for it
   once this effort ships. Folded into Out Of Scope and Acceptance Criteria #6 above.

## Background / Research Findings

**Confirmed working (do not touch):**
- `engine/nightly_learning.py` runs on schedule every night (verified in VM `dashboard.log`,
  Aug 5-10 unbroken), triggered from `workers/auto_trader.py` →
  `engine/automation.py::check_and_run_nightly_learning`.
- Its strict rule-based capital-protection block (shadow-out net-losing strategies, no AI
  dependency) works correctly even when AI providers (Gemini/Groq/OpenRouter/HuggingFace) are
  erroring nightly — confirmed via log evidence on nights with provider failures.

**Confirmed broken / gaps:**
1. `backtest_results` table has exactly ONE `run_date`, `2026-08-05`, across all 26 rows — 6+ days
   stale as of 2026-08-11 and counting. No cron, no systemd timer, no in-app scheduler re-invokes
   `run_backtests.py` (`crontab -l` empty; `systemctl list-timers` only OS-level timers). The only
   call site for `run_all_backtests()` is `run_backtests.py`, run exactly once manually. Net effect:
   `nightly_learning.py` re-tunes every night against the same static Aug-5 numbers via
   `Database.get_backtest_performance()`, which only reads — never triggers a refresh.
2. `swarm_agent_configs.win_rate/total_trades/winning_trades` get overwritten from the Aug-5
   backtest snapshot (via `update_agent_config()` sourcing `get_backtest_performance()`), with no
   column/flag distinguishing backtest-derived vs real-trade-derived. Example: Strategy 8 shows
   158 trades / 17.7% win rate in config, but its real `executed_trades` history is only 4 trades,
   last on 2026-08-04.
3. `run_backtests.py` requires a live authenticated Fyers session (`client.is_authenticated()`
   hard-gate) — no headless/unattended auth path exists today. Any nightly auto-refresh design must
   account for session/token lifecycle at whatever hour the refresh runs.
4. Separate, distinct problem: 7 of 11 configured strategies (Strategy 1-7) have ZERO real trades
   ever (live or paper). Strategy 8 and 9 stopped trading Aug 3-4. Only Strategy 11 (FRVP LVN
   Vacuum), Crude Evening Momentum, and Crude EIA Volatility have recent real activity. Strategy 11
   took a genuine fresh live loss on 2026-08-11 (-858 after a +1352 win same morning) — real signal,
   not staleness. **Confirmed out of scope for this SPEC** (see Out Of Scope) — flagged for a
   separate follow-up RESEARCH task.
5. `backtest_engine.py` uses Black-Scholes-modeled option premiums (not real historical
   option-chain quotes) and a uniform SL/target rule rather than each strategy's real live trailing
   logic — its own docstring says to treat results as a screening/prioritization signal, not an
   exact live P&L forecast. Pre-existing, already-documented limitation, not new.

**User's own framing (verbatim):** "So, the self-improvement of strategies, selfing is all working
properly, or do we have any things that need to be updated? But strategies are failing nowadays.
Once given to self-improvement, AI should take care of this. This orchestrator self-improvement for
strategies orchestrator should backtest all the charts to improve the strategies."

The user replied "GO" after RESEARCH presented 3 candidate decision points — a continuation signal,
not a scoping answer — so those 3 points were carried forward as Open Questions and have since been
formally resolved via user SPEC review (11-08-26) — see the resolved section above.

**Test coverage context:** No automated tests exist today for `nightly_learning.py`,
`backtest_engine.py`, `run_backtests.py`, or the `swarm_agent_configs`/`backtest_results` write
paths (`process/context/tests/all-tests.md` — pytest coverage is scoped to security-remediation
auth/session/concurrency surfaces only; "No unit tests for most core logic components... pytest
coverage exists only for the auth/session/rate-limit/order-concurrency surfaces"). This is why
acceptance criteria above lean Agent-Probe/Hybrid.
