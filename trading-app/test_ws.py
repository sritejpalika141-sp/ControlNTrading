from dotenv import load_dotenv
load_dotenv()
import asyncio
from engine.ws_feed import ws_feed
from fyers_client import FyersClient
import logging
logging.basicConfig(level=logging.INFO)

async def main():
    print("Testing FyersClient auth...")
    c = FyersClient(user_id=1)
    if c.is_authenticated():
        print("Auth True. Starting WS feed...")
        await ws_feed.start(c)
        await asyncio.sleep(5)
        print("WS Status:", ws_feed.get_stats())
    else:
        print("Auth False!")

asyncio.run(main())
