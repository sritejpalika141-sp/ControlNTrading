"""SL-L trigger vs limit gap must be exactly 0.5 (owner rule 03-08-26)."""
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fyers_client import (  # noqa: E402
    SL_TRIGGER_LIMIT_GAP,
    compute_sl_limit_price,
    FyersClient,
)


def test_gap_constant_is_half():
    assert SL_TRIGGER_LIMIT_GAP == 0.5


def test_compute_sl_limit_price_close_long():
    # SELL to close → limit 0.5 below trigger
    assert compute_sl_limit_price(100.0, exit_side=-1) == 99.5
    assert abs(compute_sl_limit_price(257.8, exit_side=-1, symbol="MCX:X") - 257.3) < 0.001


def test_compute_sl_limit_price_close_short():
    # BUY to close → limit 0.5 above trigger
    assert compute_sl_limit_price(100.0, exit_side=1) == 100.5


def test_place_stop_loss_uses_half_gap():
    client = FyersClient.__new__(FyersClient)
    client.client = MagicMock()
    client._is_option_symbol = MagicMock(return_value=True)
    client._is_success = MagicMock(return_value=True)
    client.client.place_order = MagicMock(return_value={"s": "ok", "id": "SL1", "code": 1101})

    # entry 292.9, sl_points 4.9 → trigger ~288.0, limit ~287.5
    res = FyersClient._place_stop_loss(
        client, "NSE:NIFTY25AUG24000CE", 25, "BUY", 292.9, sl_points=4.9, product="INTRADAY"
    )
    assert res["success"] is True
    payload = client.client.place_order.call_args[0][0]
    trigger = payload["stopPrice"]
    limit = payload["limitPrice"]
    assert abs(trigger - limit - 0.5) < 0.001
    assert payload["type"] == 4


def test_auto_trader_trail_uses_half_not_one():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "workers", "auto_trader.py"),
        encoding="utf-8",
    ).read()
    assert "new_sl_price - 1.0" not in src
    assert "new_sl_price + 1.0" not in src
    assert "compute_sl_limit_price" in src
