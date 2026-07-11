import logging
from typing import Optional

from models import Database
from engine.brokers.base import BaseBroker
# Use the ORIGINAL, complete FyersClient — it has ALL the rate-limit / CO-safe-SL / trade-recording
# / per-underlying-guard fixes. The parallel engine.brokers.fyers wrapper is abstract/incomplete
# (missing get_historical_data/get_profile) and CANNOT be instantiated — routing "fyers" through it
# 500'd every authenticated request and would also regress the fixes.
from fyers_client import FyersClient
from engine.brokers.zerodha import ZerodhaClient
from engine.brokers.aliceblue import AliceBlueClient

logger = logging.getLogger("BROKER_FACTORY")

class BrokerFactory:
    """Factory to instantiate the active broker for a user."""
    
    @staticmethod
    def get_broker(user_id: int) -> Optional[BaseBroker]:
        """
        Reads the user's active_broker setting from the DB
        and returns the corresponding initialized BaseBroker instance.
        """
        if not user_id:
            logger.warning("No user_id provided to BrokerFactory.")
            return None
            
        user = Database.get_user_by_id_sync(user_id)
        if not user:
            logger.error(f"User {user_id} not found in DB.")
            return None
            
        active_broker = user.get("active_broker", "fyers")
        if not active_broker: active_broker = "fyers"
        active_broker = active_broker.lower()

        # Defence-in-depth: Zerodha/AliceBlue are scaffolded but not yet integrated with the app's
        # client surface (they'd crash the live app on missing methods). The settings endpoint gates
        # selection to 'fyers'; this catches any out-of-band active_broker value and falls back to
        # the complete Fyers client instead of returning a broken one.
        if active_broker not in ("fyers",):
            logger.error(f"Broker '{active_broker}' for user {user_id} is not production-ready — falling back to Fyers to avoid a live-app crash.")
            active_broker = "fyers"

        if active_broker == "zerodha":
            return ZerodhaClient(user_id=user_id)
        elif active_broker == "aliceblue":
            return AliceBlueClient(user_id=user_id)
        elif active_broker == "fyers":
            return FyersClient(user_id=user_id)
        else:
            logger.error(f"Unknown active_broker '{active_broker}' for user {user_id}. Defaulting to Fyers.")
            return FyersClient(user_id=user_id)
