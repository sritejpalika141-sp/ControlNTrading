import sys
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from models import Database
import asyncio

print(type(Database.insert_log))
coro = Database.insert_log("info", "test", "2026", 1)
print(type(coro))
