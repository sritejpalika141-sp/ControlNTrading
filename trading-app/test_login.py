import asyncio
from models import Database
from passlib.context import CryptContext


async def main():
    user = await Database.get_user_by_username("admin")
    if user:
        print("User found:", user["username"])
        print("Hash:", user["password_hash"])
        is_valid = Database.verify_password("admin123", user["password_hash"])
        print("Password valid:", is_valid)
    else:
        print("User not found")


if __name__ == "__main__":
    asyncio.run(main())
