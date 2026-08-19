"""STRICT loss-driven nightly learning — owner rule 03-08-26.

Losing trades must always force self-tuning; continuous_losses only counts real losses;
ledger helpers surface each losing trade for the AI prompt.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime

import pytest
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture()
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("models.Database.DB_NAME", path)
    from models import Database

    async def _init():
        # Minimal tables used by loss-learning helpers
        import aiosqlite
        async with aiosqlite.connect(path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS executed_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER, strategy_name TEXT, symbol TEXT, underlying TEXT,
                    side TEXT, qty INTEGER, entry_price REAL, entry_time TEXT,
                    sl_points REAL, sl_method TEXT, sl_price REAL,
                    initial_sl_price REAL, final_sl_price REAL, sl_trail_count INTEGER DEFAULT 0,
                    target_points REAL, product TEXT, regime TEXT, trend TEXT,
                    entry_reason TEXT, entry_order_id TEXT,
                    status TEXT, trade_date TEXT,
                    exit_price REAL, exit_time TEXT, pnl REAL, outcome TEXT, exit_reason TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS swarm_agent_configs (
                    strategy_name TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    last_updated TEXT,
                    win_rate REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'APPROVED',
                    pending_config_json TEXT,
                    is_paper_trading INTEGER DEFAULT 1,
                    continuous_losses INTEGER DEFAULT 0,
                    asset_class TEXT DEFAULT 'EQUITY',
                    stats_source TEXT DEFAULT 'live'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS swarm_trade_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT, symbol TEXT, entry_time TEXT, exit_time TEXT,
                    entry_price REAL, exit_price REAL, pnl REAL, vix REAL,
                    market_trend TEXT, chart_image_path TEXT
                )
            """)
            await conn.commit()

    asyncio.run(_init())
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def test_should_run_self_tuning_strict_on_any_loss():
    from engine.nightly_learning import should_run_self_tuning, MIN_TRADES_FOR_LEARNING

    ok, reason = should_run_self_tuning(total_trades=1, loss_count=1)
    assert ok is True
    assert "STRICT" in reason

    ok2, reason2 = should_run_self_tuning(total_trades=3, loss_count=2)
    assert ok2 is True
    assert "2 closed losses" in reason2

    # No losses + below threshold → skip
    skip, skip_reason = should_run_self_tuning(total_trades=MIN_TRADES_FOR_LEARNING - 1, loss_count=0)
    assert skip is False
    assert "no losses" in skip_reason

    # No losses but enough trades → aggregate path
    agg, agg_reason = should_run_self_tuning(total_trades=MIN_TRADES_FOR_LEARNING, loss_count=0)
    assert agg is True
    assert "aggregate" in agg_reason


def test_format_losing_trades_includes_pnl_and_exit_reason():
    from engine.nightly_learning import _format_losing_trades_for_prompt

    text = _format_losing_trades_for_prompt([
        {
            "trade_date": "2026-08-03",
            "symbol": "MCX:CRUDEOIL25AUGPE5800",
            "side": "BUY",
            "qty": 1,
            "entry_price": 292.9,
            "exit_price": 257.75,
            "pnl": -3515.0,
            "sl_points": 35.15,
            "sl_method": "3_candle_low",
            "initial_sl_price": 257.75,
            "final_sl_price": 257.75,
            "sl_trail_count": 0,
            "regime": "TRENDING",
            "trend": "UP",
            "entry_reason": "ORB breakout",
            "exit_reason": "Stop Loss Hit",
        }
    ])
    assert "PnL ₹-3515.00" in text
    assert "Stop Loss Hit" in text
    assert "MCX:CRUDEOIL" in text
    assert _format_losing_trades_for_prompt([]) == "No closed losing trades in the lookback window."


def test_get_losing_trades_and_streak(tmp_db):
    from models import Database

    today = datetime.now(IST).strftime("%Y-%m-%d")

    async def _seed():
        # win then two losses (newest last) → streak = 2
        for i, (pnl, outcome) in enumerate([
            (500.0, "WIN"),
            (-200.0, "LOSS"),
            (-300.0, "LOSS"),
        ], start=1):
            await Database.record_trade_entry(
                user_id=1, strategy_name="Strategy 3: 5-Minute ORB",
                symbol=f"NSE:NIFTY{i}", underlying="NSE:NIFTY50-INDEX",
                side="BUY", qty=50, entry_price=100.0, entry_time=f"{today} 10:0{i}:00",
                sl_points=10.0, sl_method="3_candle_low", target_points=20.0,
                product="INTRADAY", regime="TRENDING", trend="UP",
                entry_order_id=f"oid-{i}", trade_date=today, entry_reason="test",
            )
            await Database.record_trade_exit(
                f"NSE:NIFTY{i}", exit_price=100.0 + (pnl / 50.0), pnl=pnl,
                exit_reason="test-exit", user_id=1,
            )

        losses = await Database.get_losing_trades(days=30, strategy_name="Strategy 3: 5-Minute ORB")
        assert len(losses) == 2
        assert all(float(r["pnl"]) < 0 for r in losses)

        streak = await Database.compute_continuous_loss_streak("Strategy 3: 5-Minute ORB")
        assert streak == 2

        perf = await Database.get_strategy_performance(days=30)
        p = perf["Strategy 3: 5-Minute ORB"]
        assert p["trades"] == 3
        assert p["losses"] == 2
        assert p["wins"] == 1

    asyncio.run(_seed())


def test_record_trade_outcome_breakeven_does_not_inflate_streak(tmp_db):
    from models import Database

    async def _run():
        await Database.update_agent_config(
            strategy_name="S-Test", config_dict={}, win_rate=0, total_trades=0,
            winning_trades=0, continuous_losses=1,
        )
        # Loss → streak 2
        await Database.record_trade_outcome(
            "S-Test", "NSE:X", "t0", "t1", 100, 90, pnl=-100.0,
        )
        cfg = await Database.get_agent_config("S-Test")
        assert int(cfg["continuous_losses"]) == 2

        # Breakeven must NOT bump streak
        await Database.record_trade_outcome(
            "S-Test", "NSE:Y", "t2", "t3", 100, 100, pnl=0.0,
        )
        cfg = await Database.get_agent_config("S-Test")
        assert int(cfg["continuous_losses"]) == 2

        # Win resets
        await Database.record_trade_outcome(
            "S-Test", "NSE:Z", "t4", "t5", 100, 110, pnl=50.0,
        )
        cfg = await Database.get_agent_config("S-Test")
        assert int(cfg["continuous_losses"]) == 0

    asyncio.run(_run())


def test_third_loss_disables_strategy(tmp_db):
    from models import Database

    async def _run():
        await Database.update_agent_config(
            strategy_name="S-Bleed", config_dict={}, win_rate=0, total_trades=0,
            winning_trades=0, continuous_losses=0,
        )
        for i in range(3):
            await Database.record_trade_outcome(
                "S-Bleed", f"NSE:L{i}", "t0", "t1", 100, 80, pnl=-200.0,
            )
        cfg = await Database.get_agent_config("S-Bleed")
        assert int(cfg["continuous_losses"]) == 3
        assert cfg["status"] == "DISABLED"

    asyncio.run(_run())
