import requests
import json
import re

try:
    with open('logs/trading_state_1.json') as f:
        state_data = json.load(f)
        webhook_url = state_data.get('webhook_url')
        
        if webhook_url and "api.telegram.org" in webhook_url:
            # Extract bot token from the URL
            # Format is typically https://api.telegram.org/bot<TOKEN>/sendMessage...
            match = re.search(r"bot([^/]+)/", webhook_url)
            if match:
                bot_token = match.group(1)
                
                # Set Webhook URL
                set_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
                response = requests.post(set_url, json={"url": "https://controlntrading.online/api/telegram/webhook"})
                print("Webhook registration response:", response.json())
            else:
                print("Could not extract bot token from URL")
        else:
            print("Invalid or missing webhook URL in state")
except Exception as e:
    print(f"Error: {e}")
