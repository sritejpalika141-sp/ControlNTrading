import logging
from typing import Dict, List, Any
from kiteconnect import KiteConnect

from engine.brokers.base import BaseBroker
from engine.encryption import get_secret, save_to_vault

logger = logging.getLogger("ZERODHA_CLIENT")

class ZerodhaClient(BaseBroker):
    """Wrapper around Zerodha Kite Connect API for trading operations."""

    @property
    def broker_name(self) -> str:
        return 'zerodha'

    def __init__(self, user_id=None):
        super().__init__(user_id)
        self.api_key = get_secret(f"zerodha_api_key_{self.user_id}") or ""
        self.api_secret = get_secret(f"zerodha_api_secret_{self.user_id}") or ""
        self.access_token = get_secret(f"zerodha_access_token_{self.user_id}") or ""
        
        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)

    def _check_auth(self):
        if not self.access_token:
            logger.error("Zerodha not authenticated - access_token missing")
            return False
        return True

    def get_login_url(self) -> str:
        if not self.api_key:
            return "Zerodha API Key not set."
        return self.kite.login_url()

    def set_auth_code(self, auth_code: str) -> bool:
        if not self.api_key or not self.api_secret:
            logger.error("Zerodha API Key or Secret not set")
            return False
        try:
            data = self.kite.generate_session(auth_code, api_secret=self.api_secret)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)
            save_to_vault(f"zerodha_access_token_{self.user_id}", self.access_token)
            return True
        except Exception as e:
            logger.error(f"Error setting Zerodha auth code: {e}")
            return False

    def get_profile(self) -> Dict[str, Any]:
        if not self._check_auth(): return {}
        try:
            return self.kite.profile()
        except Exception as e:
            logger.error(f"Error fetching profile: {e}")
            return {}

    def get_funds(self) -> Dict[str, Any]:
        if not self._check_auth(): return {}
        try:
            margins = self.kite.margins()
            equity = margins.get('equity', {})
            return {"fund_limit": equity.get('available', {}).get('live_balance', 0)}
        except Exception as e:
            logger.error(f"Error fetching funds: {e}")
            return {}

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self._check_auth(): return []
        try:
            return self.kite.positions().get('net', [])
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_holdings(self) -> List[Dict[str, Any]]:
        if not self._check_auth(): return []
        try:
            return self.kite.holdings()
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return []

    def place_order(self, symbol: str, qty: int, side: int, order_type: int = 2, product_type: str = "INTRADAY", limit_price: float = 0.0, stop_price: float = 0.0) -> Dict[str, Any]:
        if not self._check_auth(): return {"status": "error"}
        
        transaction_type = self.kite.TRANSACTION_TYPE_BUY if side == 1 else self.kite.TRANSACTION_TYPE_SELL
        product = self.kite.PRODUCT_MIS if product_type == "INTRADAY" else self.kite.PRODUCT_CNC
        
        k_order_type = self.kite.ORDER_TYPE_MARKET
        if order_type == 1: k_order_type = self.kite.ORDER_TYPE_LIMIT
        elif order_type == 3: k_order_type = self.kite.ORDER_TYPE_SL
        elif order_type == 4: k_order_type = self.kite.ORDER_TYPE_SLM
        
        # Zerodha expects Exchange:Symbol format
        if ":" not in symbol:
            symbol = f"NSE:{symbol}"
        exchange, tradingsymbol = symbol.split(":")
        
        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=qty,
                product=product,
                order_type=k_order_type,
                price=limit_price if limit_price > 0 else None,
                trigger_price=stop_price if stop_price > 0 else None
            )
            return {"status": "ok", "id": order_id}
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"status": "error", "message": str(e)}

    def modify_order(self, order_id: str, qty: int = 0, limit_price: float = 0.0, stop_price: float = 0.0, order_type: int = 2) -> Dict[str, Any]:
        if not self._check_auth(): return {"status": "error"}
        try:
            order_id = self.kite.modify_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id,
                quantity=qty if qty > 0 else None,
                price=limit_price if limit_price > 0 else None,
                trigger_price=stop_price if stop_price > 0 else None
            )
            return {"status": "ok", "id": order_id}
        except Exception as e:
            logger.error(f"Error modifying order: {e}")
            return {"status": "error", "message": str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self._check_auth(): return {"status": "error"}
        try:
            self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
            return {"status": "ok", "id": order_id}
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return {"status": "error", "message": str(e)}

    def get_historical_data(self, symbol: str, resolution: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Note: Requires manual instrument token resolution in Zerodha."""
        # Simplified stub
        return {"candles": []}

    def get_quotes(self, symbols: str) -> Dict[str, Any]:
        if not self._check_auth(): return {}
        try:
            sym_list = symbols.split(",")
            sym_list = [s if ":" in s else f"NSE:{s}" for s in sym_list]
            res = self.kite.quote(sym_list)
            # Format to match internal expectations if needed
            return res
        except Exception as e:
            logger.error(f"Error fetching quotes: {e}")
            return {}
