import logging
from typing import Dict, List, Any

from engine.brokers.base import BaseBroker
from engine.encryption import get_secret, save_to_vault

logger = logging.getLogger("ALICEBLUE_CLIENT")

class AliceBlueClient(BaseBroker):
    """Wrapper around Alice Blue pya3 API for trading operations."""

    @property
    def broker_name(self) -> str:
        return 'aliceblue'

    def __init__(self, user_id=None):
        super().__init__(user_id)
        self.api_key = get_secret(f"aliceblue_api_key_{self.user_id}") or ""
        self.user_id_ab = get_secret(f"aliceblue_user_id_{self.user_id}") or ""
        self.session_id = get_secret(f"aliceblue_session_id_{self.user_id}") or ""
        
        # We lazily import Aliceblue to avoid crashing if pya3 isn't installed
        try:
            from pya3 import Aliceblue
            self.alice = Aliceblue(user_id=self.user_id_ab, api_key=self.api_key)
            if self.session_id:
                # pya3 sets session_id directly
                self.alice.session_id = self.session_id
        except ImportError:
            logger.warning("pya3 not installed. AliceBlue will not work.")
            self.alice = None

    def _check_auth(self):
        if not self.alice or not self.session_id:
            logger.error("AliceBlue not authenticated")
            return False
        return True

    def get_login_url(self) -> str:
        # Alice blue V2 API generates session ID without a redirect URL if API Key is correct
        return "AliceBlue uses direct API Key auth, not OAuth redirect."

    def set_auth_code(self, auth_code: str) -> bool:
        """For Alice Blue, we just need to get the session ID using user_id and API key."""
        if not self.alice: return False
        try:
            res = self.alice.get_session_id()
            if res.get("stat") == "Ok":
                self.session_id = res.get("sessionID")
                save_to_vault(f"aliceblue_session_id_{self.user_id}", self.session_id)
                return True
            return False
        except Exception as e:
            logger.error(f"Error setting AliceBlue session: {e}")
            return False

    def get_profile(self) -> Dict[str, Any]:
        if not self._check_auth(): return {}
        try:
            return self.alice.get_profile()
        except Exception as e:
            logger.error(f"Error fetching profile: {e}")
            return {}

    def get_funds(self) -> Dict[str, Any]:
        if not self._check_auth(): return {}
        try:
            res = self.alice.get_balance()
            return {"fund_limit": res[0].get('net', 0) if isinstance(res, list) and len(res)>0 else 0}
        except Exception as e:
            logger.error(f"Error fetching funds: {e}")
            return {}

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self._check_auth(): return []
        try:
            res = self.alice.get_netwise_positions()
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_holdings(self) -> List[Dict[str, Any]]:
        if not self._check_auth(): return []
        try:
            res = self.alice.get_holding_positions()
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return []

    def place_order(self, symbol: str, qty: int, side: int, order_type: int = 2, product_type: str = "INTRADAY", limit_price: float = 0.0, stop_price: float = 0.0) -> Dict[str, Any]:
        if not self._check_auth(): return {"status": "error"}
        
        try:
            from pya3 import TransactionType, OrderType, ProductType
        except ImportError:
            return {"status": "error", "message": "pya3 not installed"}
            
        t_type = TransactionType.Buy if side == 1 else TransactionType.Sell
        p_type = ProductType.Intraday if product_type == "INTRADAY" else ProductType.Delivery
        
        o_type = OrderType.Market
        if order_type == 1: o_type = OrderType.Limit
        elif order_type == 3: o_type = OrderType.StopLossMarket
        elif order_type == 4: o_type = OrderType.StopLossLimit
        
        # simplified instrument resolution
        try:
            res = self.alice.place_order(
                transaction_type=t_type,
                instrument=self.alice.get_instrument_by_symbol("NSE", symbol),
                quantity=qty,
                order_type=o_type,
                product_type=p_type,
                price=limit_price if limit_price > 0 else 0.0,
                trigger_price=stop_price if stop_price > 0 else 0.0,
                is_amo=False
            )
            return {"status": "ok", "id": res.get("NOrdNo")}
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"status": "error", "message": str(e)}

    def modify_order(self, order_id: str, qty: int = 0, limit_price: float = 0.0, stop_price: float = 0.0, order_type: int = 2) -> Dict[str, Any]:
        # Simplified stub
        return {"status": "error", "message": "Not implemented"}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        # Simplified stub
        return {"status": "error", "message": "Not implemented"}

    def get_historical_data(self, symbol: str, resolution: str, start_date: str, end_date: str) -> Dict[str, Any]:
        return {"candles": []}

    def get_quotes(self, symbols: str) -> Dict[str, Any]:
        return {}
