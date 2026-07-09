import asyncio
from models import Database

async def test():
    username = "admin"
    password = "admin1234"
    user = await Database.get_user_by_username(username)
    print("User:", user)
    if user and Database.verify_password(password, user["password_hash"]):
        print("LOGIN SUCCESS")
    else:
        print("LOGIN FAILED")

asyncio.run(test())
