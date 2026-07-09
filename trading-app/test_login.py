import asyncio
from models import Database
from passlib.context import CryptContext

user = await Database.get_user_by_username("admin")
if user:
    print("User found:", user["username"])
    print("Hash:", user["password_hash"])
    is_valid = Database.verify_password("admin123", user["password_hash"])
    print("Password valid:", is_valid)
else:
    print("User not found")
