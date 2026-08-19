"""MCX SL must use 0.1 ticks; naked options must not stay open without SL."""
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fyers_client import (  # noqa: E402
    get_price_tick,
    round_to_tick,
    compute_sl_limit_price,
    FyersClient,
)


def test_mcx_tick_is_point_one():
    assert get_price_tick("MCX:CRUDEOIL26AUG7400PE") == 0.1
    assert get_price_tick("NSE:NIFTY25AUG24000CE") == 0.05


def test_mcx_sl_prices_on_valid_tick():
    """Regression: 257.75/257.25 (0.05) was rejected by Fyers on MCX 0.1 tick."""
    sym = "MCX:CRUDEOIL26AUG7400PE"
    entry, pts = 292.9, 35.15
    trigger = round_to_tick(entry - pts, get_price_tick(sym))
    limit = compute_sl_limit_price(trigger, exit_side=-1, symbol=sym)
    assert abs(round(trigger / 0.1) * 0.1 - trigger) < 1e-9
    assert abs(round(limit / 0.1) * 0.1 - limit) < 1e-9
    assert abs(trigger - limit - 0.5) < 0.001
    # Must NOT be the old invalid .x5/.x75 pair when trigger was floored to 0.05
    assert trigger != 257.75
    assert limit != 257.25


def test_place_stop_loss_mcx_uses_point_one_tick():
    client = FyersClient.__new__(FyersClient)
    client.client = MagicMock()
    client._is_option_symbol = MagicMock(return_value=True)
    client._is_success = MagicMock(return_value=True)
    client.client.place_order = MagicMock(return_value={"s": "ok", "id": "SL1", "code": 1101})

    FyersClient._place_stop_loss(
        client, "MCX:CRUDEOIL26AUG7400PE", 1, "BUY", 292.9, sl_points=35.15, product="INTRADAY"
    )
    payload = client.client.place_order.call_args[0][0]
    assert abs(round(payload["stopPrice"] / 0.1) * 0.1 - payload["stopPrice"]) < 1e-9
    assert abs(round(payload["limitPrice"] / 0.1) * 0.1 - payload["limitPrice"]) < 1e-9
    assert abs(payload["stopPrice"] - payload["limitPrice"] - 0.5) < 0.001


def test_compute_gap_still_half_on_mcx():
    assert abs(compute_sl_limit_price(100.0, -1, "MCX:CRUDEOIL26AUGFUT") - 99.5) < 0.001


def test_fail_closed_source_contract():
    """place_order must retry SL-M and emergency-exit — never return success with empty sl_order_id after SL fail."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "fyers_client.py"),
        encoding="utf-8",
    ).read()
    assert "retrying SL-M" in src
    assert "emergency MARKET exit" in src
    assert "emergency_exit" in src
    assert "Entry filled but SL failed — position squared off" in src
