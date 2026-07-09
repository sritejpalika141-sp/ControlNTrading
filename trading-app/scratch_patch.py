import re

with open("app.py", "r") as f:
    code = f.read()

# Pattern for basic one-line asyncio.to_thread(client.method, args...)
# We can just substitute `asyncio.to_thread(client.` with `api_queue.enqueue(1, client.`
# Wait, some are Priority 2, but for `app.py` mostly it's Live or frontend requests, which should be fast. 
# We'll use 1 for place_order and get_positions, get_historical can be 2.

code = re.sub(r'asyncio\.to_thread\(client\.place_order,', r'api_queue.enqueue(1, client.place_order,', code)
code = re.sub(r'asyncio\.to_thread\(\s*client\.place_order,', r'api_queue.enqueue(\n                                1, client.place_order,', code)
code = re.sub(r'asyncio\.to_thread\(client\.get_positions\)', r'api_queue.enqueue(1, client.get_positions)', code)
code = re.sub(r'asyncio\.to_thread\(client\.get_funds\)', r'api_queue.enqueue(1, client.get_funds)', code)
code = re.sub(r'asyncio\.to_thread\(client\.get_orders\)', r'api_queue.enqueue(1, client.get_orders)', code)

# Other client methods get Priority 2
code = re.sub(r'asyncio\.to_thread\(client\.', r'api_queue.enqueue(2, client.', code)

with open("app.py", "w") as f:
    f.write(code)
print("Patched app.py")
