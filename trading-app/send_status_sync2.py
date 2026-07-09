import psutil
import requests
import json

try:
    with open('logs/trading_state_1.json') as f:
        state_data = json.load(f)
    
    try:
        with open('logs/trading_cache_1.json') as f:
            cache_data = json.load(f)
    except:
        cache_data = {}

    webhook_url = state_data.get('webhook_url')
    if webhook_url:
        process = psutil.Process()
        mem_mb = process.memory_info().rss / (1024 * 1024)
        
        is_auth = cache_data.get('is_auth', False)
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
        
        payload = {
            "text": f"*Status Report*\n{msg}",
            "parse_mode": "Markdown"
        }
        resp = requests.post(webhook_url, json=payload)
        print("Status Code:", resp.status_code)
        print("Response:", resp.text)
except Exception as e:
    print(e)
