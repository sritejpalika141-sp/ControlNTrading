import asyncio
from fyers_client import FyersClient
import os

async def main():
    client = FyersClient()
    expiry = client.find_nearest_expiry(1300, "NSE:RELIANCE-EQ")
    print(f"Expiry: {expiry}")

asyncio.run(main())
