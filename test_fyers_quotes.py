import sys
import os
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from fyers_client import FyersClient
import asyncio

async def test():
    client = FyersClient(user_id=1)
    if not client.is_authenticated():
        print("Not auth")
        return
    res = client.get_quotes(["NSE:NIFTY50-INDEX"], force_rest=True)
    print("REST QUOTE RESULT:", res)

asyncio.run(test())
