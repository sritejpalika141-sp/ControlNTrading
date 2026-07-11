from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

class BaseBroker(ABC):
    """
    Abstract Base Class for all sharemarket broker integrations (Fyers, Zerodha, Alice Blue).
    Provides a unified interface for the algorithmic trading engine to interact with different APIs.
    """

    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        
    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Return the lowercase name of the broker (e.g., 'fyers', 'zerodha', 'aliceblue')."""
        pass
        
    @abstractmethod
    def get_login_url(self) -> str:
        """Generate the login/auth URL for the broker."""
        pass

    @abstractmethod
    def set_auth_code(self, auth_code: str) -> bool:
        """Exchange the auth code for access tokens and save them securely."""
        pass
        
    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        """Fetch user profile details (name, email, etc)."""
        pass

    @abstractmethod
    def get_funds(self) -> Dict[str, Any]:
        """Fetch available margin/funds."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current open positions."""
        pass

    @abstractmethod
    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch portfolio holdings."""
        pass

    @abstractmethod
    def place_order(self, symbol: str, qty: int, side: int, order_type: int = 2, product_type: str = "INTRADAY", limit_price: float = 0.0, stop_price: float = 0.0) -> Dict[str, Any]:
        """
        Place an order.
        side: 1 for BUY, -1 for SELL
        order_type: 1 for Limit, 2 for Market, 3 for Stop, 4 for StopLimit
        """
        pass
        
    @abstractmethod
    def modify_order(self, order_id: str, qty: int = 0, limit_price: float = 0.0, stop_price: float = 0.0, order_type: int = 2) -> Dict[str, Any]:
        """Modify an existing pending order."""
        pass
        
    @abstractmethod
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a pending order."""
        pass
        
    @abstractmethod
    def get_historical_data(self, symbol: str, resolution: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Fetch historical candle data.
        Returns a dict containing at minimum {"candles": [[timestamp, open, high, low, close, volume], ...]}
        """
        pass

    @abstractmethod
    def get_quotes(self, symbols: str) -> Dict[str, Any]:
        """Fetch latest quotes/LTP for comma-separated symbols."""
        pass
