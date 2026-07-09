import asyncio
from engine.ws_feed import ws_feed
from models import Database

async def test():
    await Database.init()
    print("Testing symbols from WS...")

asyncio.run(test())
