import asyncio
from engine.notifier import trigger_webhook_background
import json

try:
    with open('logs/trading_state_1.json') as f:
        data = json.load(f)
        url = data.get('webhook_url')
        print("URL is:", url)
        if url:
            trigger_webhook_background(url, "✅ All systems are online and working perfectly! This is a test message.", title="System Test")
            print("Message sent.")
except Exception as e:
    print(e)
