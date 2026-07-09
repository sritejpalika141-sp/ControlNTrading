import sys
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from engine.notifier import trigger_webhook_background
from engine.automation import TradingState

state = TradingState("1")
url = state.webhook_url
if not url:
    print("No webhook URL configured.")
    sys.exit(1)

msg = f"📊 *End of Day Report (SAMPLE)*\n\n"
msg += f"🗓️ Date: 2026-05-21\n"
msg += f"💰 Total PnL Today: ₹1550.00\n"
msg += f"📈 Total Trades Taken: 2\n"

trigger_webhook_background(url, msg, title="Market Closed (Sample)")
print("Sent sample webhook!")
