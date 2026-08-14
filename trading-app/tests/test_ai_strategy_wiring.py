"""AI strategy registry + hindsight optimizer wiring tests."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

IST = pytz.timezone("Asia/Kolkata")


def test_normalize_auto_signal_buy_to_call():
    from engine.ai_strategy_registry import normalize_auto_signal

    sig = normalize_auto_signal(
        {"signal": "BUY", "reason": "engulf", "confidence": 80, "paper_trade_only": True},
        "AI_strategy_1",
        "NSE:NIFTY50-INDEX",
    )
    assert sig["type"] == "CALL"
    assert sig["side"] == "BUY"
    assert sig["is_ai_strategy"] is True
    assert sig["paper_trade_only"] is True


def test_normalize_auto_signal_sell_to_put_not_short():
    from engine.ai_strategy_registry import normalize_auto_signal

    sig = normalize_auto_signal({"type": "SELL"}, "AI_strategy_2", "NSE:NIFTY50-INDEX")
    assert sig["type"] == "PUT"
    assert sig["side"] == "BUY"


def test_dual_case_candles_and_dummy_eval():
    from engine.ai_strategy_registry import _dual_case_candles, _load_module, find_evaluate_fn

    candles = [
        {"open": 100, "high": 101, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 102, "low": 99, "close": 101.5},
    ]
    dual = _dual_case_candles(candles)
    assert dual[0]["Open"] == 100
    assert dual[1]["Close"] == 101.5

    mod = _load_module("strategy_auto_dummy.py")
    fn = find_evaluate_fn(mod)
    assert fn is not None
    assert fn.__name__.startswith("evaluate_auto_")


def test_list_auto_strategy_files_includes_dummy():
    from engine.ai_strategy_registry import list_auto_strategy_files

    files = list_auto_strategy_files()
    assert "strategy_auto_dummy.py" in files


@pytest.fixture()
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("models.Database.DB_NAME", path)

    async def _init():
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
                    asset_class TEXT DEFAULT 'EQUITY'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS swarm_learning_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT, date TEXT, llm_analysis TEXT,
                    old_config TEXT, new_config TEXT
                )
            """)
            await conn.commit()

    asyncio.run(_init())
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def test_resolve_binds_ai_strategy_to_module(tmp_db):
    from models import Database
    from engine.ai_strategy_registry import resolve_ai_strategy_bindings

    async def _run():
        await Database.update_agent_config(
            strategy_name="AI_strategy_1",
            config_dict={"module_file": "strategy_auto_dummy.py", "paper_trade_only": True},
            win_rate=0, total_trades=0, winning_trades=0,
            status="APPROVED", is_paper_trading=1,
        )
        bindings = await resolve_ai_strategy_bindings()
        assert len(bindings) == 1
        assert bindings[0]["strategy_name"] == "AI_strategy_1"
        assert bindings[0]["module_file"] == "strategy_auto_dummy.py"
        assert bindings[0]["evaluate_fn"] is not None

    asyncio.run(_run())


def test_hindsight_tightens_on_loss(tmp_db):
    from models import Database
    from workers.hindsight_optimizer_worker import HindsightOptimizerWorker

    async def _run():
        await Database.update_agent_config(
            strategy_name="Strategy 3: 5-Minute ORB",
            config_dict={
                "entry_confidence_floor": 60,
                "strike_offset": 0,
                "chase_buffer_pct": 0.8,
            },
            win_rate=40, total_trades=5, winning_trades=2,
        )
        today = datetime.now(IST).strftime("%Y-%m-%d")
        await Database.record_trade_entry(
            user_id=1, strategy_name="Strategy 3: 5-Minute ORB",
            symbol="NSE:NIFTY1", underlying="NSE:NIFTY50-INDEX",
            side="BUY", qty=65, entry_price=100.0, entry_time=f"{today} 10:00:00",
            sl_points=10.0, sl_method="3_candle_low", target_points=20.0,
            product="INTRADAY", regime="TRENDING", trend="UP",
            entry_order_id="h1", trade_date=today, entry_reason="chased high",
        )
        await Database.record_trade_exit(
            "NSE:NIFTY1", exit_price=80.0, pnl=-1300.0,
            exit_reason="Stop Loss Hit", user_id=1,
        )

        w = HindsightOptimizerWorker(interval_seconds=1)
        # Bootstrap marks existing as seen
        await w._tick()
        # Simulate a NEW close by clearing seen and re-processing
        w._seen_ids.clear()
        w._bootstrapped = True
        await w._tick()

        cfg = await Database.get_agent_config("Strategy 3: 5-Minute ORB")
        conf = cfg["config_json"]
        assert float(conf["entry_confidence_floor"]) == 65
        assert int(conf["strike_offset"]) == 1
        assert float(conf["chase_buffer_pct"]) == 1.0

    asyncio.run(_run())


def test_auto_trader_gathers_ai_strategies_hook():
    """Sanity: automation_loop source includes run_ai_strategies in gather."""
    import inspect
    from workers import auto_trader
    src = inspect.getsource(auto_trader.automation_loop)
    assert "run_ai_strategies" in src
    assert "evaluate_enabled_ai_strategies" in src
