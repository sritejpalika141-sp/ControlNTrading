import asyncio, os
from fyers_client import FyersClient
import logging
logging.basicConfig(level=logging.DEBUG)

client = FyersClient(user_id=1)
client.check_auth_status()

# Test option chain for Reliance
chain = client.get_option_chain_strikes(3100.0, None, 5, base_symbol="NSE:RELIANCE-EQ")
print(f"Calls: {len(chain.get('calls', []))}")
print(f"Puts: {len(chain.get('puts', []))}")
if chain.get('calls'):
    print(f"Sample Call: {chain['calls'][0]['symbol']} at {chain['calls'][0]['strike']}")
