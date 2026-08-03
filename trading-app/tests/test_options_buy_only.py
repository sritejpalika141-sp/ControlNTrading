"""Options buy-only policy: never sell-to-open / write CE|PE; SELL only closes a matching long."""
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fyers_client import FyersClient  # noqa: E402


def test_is_option_symbol():
    assert FyersClient._is_option_symbol("NSE:NIFTY2560025600PE")
    assert FyersClient._is_option_symbol("NSE:NIFTY2560025600CE")
    assert not FyersClient._is_option_symbol("NSE:NIFTY50-INDEX")
    assert not FyersClient._is_option_symbol("NSE:RELIANCE-EQ")


def test_position_net_qty_long_short():
    assert FyersClient._position_net_qty({"netQty": 65, "symbol": "X"}) == 65
    assert FyersClient._position_net_qty({"netQty": -65}) == -65
    assert FyersClient._position_net_qty({"qty": 65, "side": 1}) == 65
    assert FyersClient._position_net_qty({"qty": 65, "side": -1}) == -65


def test_sell_option_without_long_is_blocked():
    c = FyersClient(user_id=1)
    c.client = MagicMock()
    with patch.object(c, "get_positions", return_value=[]), \
         patch("models.Database.is_kill_switch_active", return_value=False):
        res = c.place_order(
            symbol="NSE:NIFTY2560025600PE",
            qty=65,
            side="SELL",
            order_type="MARKET",
            product="INTRADAY",
            sl_points=0,
            target_points=0,
        )
    assert res["success"] is False
    assert "buy-only" in res["message"].lower() or "SELL blocked" in res["message"]
    c.client.place_order.assert_not_called()


def test_sell_option_with_matching_long_uses_position_product():
    c = FyersClient(user_id=1)
    c.client = MagicMock()
    c.client.place_order.return_value = {"s": "ok", "code": 1101, "id": "ORD1"}
    long_pos = {
        "symbol": "NSE:NIFTY2560025600PE",
        "netQty": 65,
        "qty": 65,
        "side": 1,
        "productType": "CO",
    }
    with patch.object(c, "get_positions", return_value=[long_pos]), \
         patch.object(c, "get_quote", return_value={"lp": 120.0}), \
         patch.object(c, "_is_success", return_value=True), \
         patch("models.Database.is_kill_switch_active", return_value=False), \
         patch("app.get_user_state", side_effect=Exception("no paper")):
        # Bypass paper path by making get_user_state fail into live path
        res = c.place_order(
            symbol="NSE:NIFTY2560025600PE",
            qty=65,
            side="SELL",
            order_type="LIMIT",
            product="INTRADAY",  # wrong book on purpose — must be overridden to CO
            limit_price=120.0,
            sl_points=0,
            target_points=0,
            is_exit=True,
        )
    assert res.get("success") is True
    sent = c.client.place_order.call_args[0][0]
    assert sent["side"] == -1
    assert sent["productType"] == "CO"
    assert sent["qty"] == 65


def test_sell_qty_clamped_to_long():
    c = FyersClient(user_id=1)
    c.client = MagicMock()
    c.client.place_order.return_value = {"s": "ok", "code": 1101, "id": "ORD2"}
    long_pos = {
        "symbol": "NSE:NIFTY2560025600PE",
        "netQty": 65,
        "productType": "MARGIN",
    }
    with patch.object(c, "get_positions", return_value=[long_pos]), \
         patch.object(c, "get_quote", return_value={"lp": 100.0}), \
         patch.object(c, "_is_success", return_value=True), \
         patch("models.Database.is_kill_switch_active", return_value=False), \
         patch("app.get_user_state", side_effect=Exception("no paper")):
        res = c.place_order(
            symbol="NSE:NIFTY2560025600PE",
            qty=130,  # 2x long — must clamp
            side="SELL",
            order_type="LIMIT",
            product="MARGIN",
            limit_price=100.0,
            sl_points=0,
            target_points=0,
        )
    assert res.get("success") is True
    assert c.client.place_order.call_args[0][0]["qty"] == 65


def test_co_reject_aborts_without_intraday_sell_fallback():
    c = FyersClient(user_id=1)
    c.client = MagicMock()
    c.client.place_order.return_value = {"s": "error", "code": -99, "message": "CO not allowed"}
    with patch.object(c, "get_quote", return_value={"lp": 50.0}), \
         patch.object(c, "_is_success", return_value=False), \
         patch("models.Database.is_kill_switch_active", return_value=False), \
         patch("app.get_user_state", side_effect=Exception("no paper")):
        res = c.place_order(
            symbol="NSE:NIFTY2560025600PE",
            qty=65,
            side="BUY",
            order_type="LIMIT",
            product="CO",
            limit_price=50.0,
            sl_points=12.0,
            target_points=0,
        )
    assert res["success"] is False
    assert "abort" in res["message"].lower() or "CO rejected" in res["message"]
    # Only the CO attempt — no INTRADAY retry that would later attach a naked SELL SL
    assert c.client.place_order.call_count == 1


def test_place_stop_loss_blocks_naked_option_sell():
    c = FyersClient(user_id=1)
    c.client = MagicMock()
    c._get_active_client = MagicMock(return_value=c.client)
    with patch.object(c, "get_positions", return_value=[]):
        res = c.place_stop_loss("NSE:NIFTY2560025600PE", 65, 80.0, exit_side=-1)
    assert res.get("s") == "error"
    assert "buy-only" in res.get("message", "").lower()
    c.client.place_order.assert_not_called()
