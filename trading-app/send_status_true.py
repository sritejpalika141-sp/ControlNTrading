import requests
import json
import psutil

try:
    with open('logs/trading_state_1.json') as f:
        state_data = json.load(f)
        
    api_resp = requests.get('http://127.0.0.1:8000/api/auth-status', cookies={'user_id': '1'})
    is_auth = False
    if api_resp.status_code == 200:
        is_auth = api_resp.json().get('status') == 'ok'
        
    webhook_url = state_data.get('webhook_url')
    if webhook_url:
        process = psutil.Process()
        mem_mb = process.memory_info().rss / (1024 * 1024)
        auth_status = "✅ Connected" if is_auth else "❌ Disconnected"
        active_trades = len(state_data.get('active_auto_trades', []))
        
        is_paper = state_data.get('paper_trading', True)
        trades_today = state_data.get('paper_trades_today', 0) if is_paper else state_data.get('live_trades_today', 0)
        pnl = state_data.get('paper_pnl_today', 0.0) if is_paper else state_data.get('live_pnl_today', 0.0)
        max_trades_per_day = state_data.get('max_trades_per_day', 10)
        active_strategies = state_data.get('active_strategies', [])
        strategies_str = ", ".join(active_strategies) if active_strategies else "None"
        
        msg = (
            f"⏱️ *System Status (Manual Trigger)*\n\n"
            f"🟢 *System:* Online ({mem_mb:.1f} MB RAM)\n"
            f"🔐 *Fyers Auth:* {auth_status}\n"
            f"💰 *PnL Today:* ₹{pnl:.2f}\n"
            f"📈 *Active Trades:* {active_trades}\n"
            f"📊 *Trades Taken:* {trades_today}/{max_trades_per_day}\n"
            f"🎯 *Active Strategies:* {strategies_str}"
        )
        
        if "api.telegram.org" in webhook_url:
            webhook_url = webhook_url.split("&text=")[0].split("?text=")[0]
        
        payload = {"text": f"*Status Report*\n{msg}", "parse_mode": "Markdown"}
        requests.post(webhook_url, json=payload)
        print("Sent with auth_status:", auth_status)
except Exception as e:
    print(e)
