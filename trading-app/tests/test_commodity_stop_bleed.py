"""Commodity stop-bleed: defaults off; all-day ORB/9-EMA/Swing stripped on load."""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.automation import TradingState  # noqa: E402


def test_new_state_commodity_strategies_empty():
    st = TradingState(user_id=987654)
    assert st.commodity_strategies == []


def test_load_strips_buy_high_commodity_strategies(tmp_path):
    st = TradingState(user_id=987655)
    path = tmp_path / "trading_state_987655.json"
    today = __import__("datetime").datetime.now(__import__("pytz").timezone("Asia/Kolkata")).date().isoformat()
    payload = {
        "last_reset_date": today,
        "commodity_strategies": [
            "Commodity: 5-Minute ORB",
            "Commodity: 9-EMA Momentum",
            "Commodity: Swing-Pivot Breakout",
            "Commodity: EIA Volatility (Wed)",
            "Commodity: Evening Momentum",
        ],
        "active_strategies": ["Strategy 1: OB + FVG"],
        "trades_today": 0,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with patch.object(st, "state_file", str(path)):
        with patch.object(st, "save"):  # avoid rewriting unexpected paths
            st.load()
    assert "Commodity: 5-Minute ORB" not in st.commodity_strategies
    assert "Commodity: 9-EMA Momentum" not in st.commodity_strategies
    assert "Commodity: Swing-Pivot Breakout" not in st.commodity_strategies
    assert "Commodity: EIA Volatility (Wed)" in st.commodity_strategies
    assert "Commodity: Evening Momentum" in st.commodity_strategies