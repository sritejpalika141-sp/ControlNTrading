import re
import os

filepath = "/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app/workers/auto_trader.py"
with open(filepath, "r") as f:
    code = f.read()

# Add import if missing
if "from engine.api_queue import api_queue" not in code:
    code = code.replace("from models import Database", "from engine.api_queue import api_queue\nfrom models import Database")

# Replace asyncio.to_thread with api_queue.enqueue
code = re.sub(r'asyncio\.to_thread\(client\.place_order,', r'api_queue.enqueue(1, client.place_order,', code)
code = re.sub(r'asyncio\.to_thread\(client\.get_positions\)', r'api_queue.enqueue(1, client.get_positions)', code)
code = re.sub(r'asyncio\.to_thread\(client\.', r'api_queue.enqueue(2, client.', code)

with open(filepath, "w") as f:
    f.write(code)
print("Patched auto_trader.py")
