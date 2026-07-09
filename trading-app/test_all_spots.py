import asyncio
from app import USER_CACHES, get_user_state
from models import Database

async def test():
    await Database.init()
    for u_id_key, cache in USER_CACHES.items():
        print(f"User {u_id_key} active symbols: {get_user_state(int(u_id_key)).active_symbols}")
        print(f"User {u_id_key} all_spots keys: {cache.get('all_spots', {}).keys()}")
        print(f"User {u_id_key} all_spots values: {cache.get('all_spots', {})}")
    print("Done")

asyncio.run(test())
