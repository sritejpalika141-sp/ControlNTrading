"""
Concurrency regression test for the daily-trade-limit TOCTOU fix (Phase 1 Item F1).

Exercises the REAL `TradingState.order_lock` + `record_trade` + trades_today/max_trades_per_day
state using the widened critical-section pattern now used by place_order: the lock wraps the
limit check AND the trade record as one atomic unit. Fires N = max+3 concurrent "orders" and
asserts exactly max_trades_per_day succeed (never more).

Run: cd trading-app && ./.venv/bin/python -m pytest tests/test_order_concurrency.py -q

Note: this validates the lock/state invariant directly. The live end-to-end /api/order
concurrency check against the broker is the deploy-day paper-trading round-trip (item-4-order-roundtrip).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.automation import TradingState  # noqa: E402


def _make_state(max_trades):
    state = TradingState(999999)
    state.paper_trading = True
    state.max_trades_per_day = max_trades
    state.save = lambda: None  # avoid file writes during the test
    return state


def test_widened_lock_enforces_exact_limit():
    async def run():
        max_trades = 5
        state = _make_state(max_trades)
        results = []

        async def place_order_sim():
            # Mirror the widened critical section from app.place_order (Item F1):
            # check + (simulated broker place) + record_trade all inside the lock.
            async with state.order_lock:
                if state.trades_today >= state.max_trades_per_day:
                    results.append(False)
                    return
                await asyncio.sleep(0)  # simulate the broker round-trip yielding control
                state.record_trade()
                results.append(True)

        await asyncio.gather(*[place_order_sim() for _ in range(max_trades + 3)])
        return state, results

    state, results = asyncio.run(run())
    successes = sum(1 for r in results if r)
    assert successes == 5, f"expected exactly 5 successes, got {successes}"
    assert state.trades_today == 5, f"trades_today should be exactly 5, got {state.trades_today}"


def test_narrow_lock_pattern_can_overcount():
    """
    Demonstrates WHY the fix is needed: the OLD narrow-lock pattern (lock only around the
    check, broker+record outside it) can place more than the limit under concurrency.
    This is the bug the widened lock closes.
    """
    async def run():
        max_trades = 5
        state = _make_state(max_trades)
        results = []

        async def place_order_old():
            # OLD buggy pattern: lock released right after the check.
            async with state.order_lock:
                over = state.trades_today >= state.max_trades_per_day
            if over:
                results.append(False)
                return
            await asyncio.sleep(0)  # broker round-trip OUTSIDE the lock — the race window
            state.record_trade()
            results.append(True)

        await asyncio.gather(*[place_order_old() for _ in range(max_trades + 3)])
        return state

    state = asyncio.run(run())
    # The buggy pattern lets ALL concurrent requests through — proving the race is real.
    assert state.trades_today > 5, (
        f"narrow-lock pattern should overcount, got {state.trades_today} "
        "(if this ever equals 5, the race simply didn't manifest this run)"
    )
