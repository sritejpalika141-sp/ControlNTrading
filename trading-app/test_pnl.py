import pytz
from datetime import datetime

IST = pytz.timezone('Asia/Kolkata')

class DummyState:
    def __init__(self):
        self.pnl_today = 150.0
        self.closed_trades_today = [
            {"symbol": "NSE:NIFTY24DEC24000CE", "pnl": 150.0}
        ]

state_obj = DummyState()

try:
    pnl = state_obj.pnl_today
    closed_trades = getattr(state_obj, 'closed_trades_today', [])
    
    now_str = datetime.now(IST).date().isoformat()
    msg = (
        f"📊 *PnL Report*\n\n"
        f"🗓️ Date: {now_str}\n"
        f"💰 Total PnL Today: ₹{pnl:.2f}\n"
        f"📈 Total Trades Taken: {len(closed_trades)}"
    )
    
    msg += "\n\n*Trade Breakdown:*\n"
    if closed_trades:
        for i, t in enumerate(closed_trades, 1):
            p_icon = "🟢" if t['pnl'] > 0 else "🔴" if t['pnl'] < 0 else "⚪"
            msg += f"{i}. {t['symbol']}: {p_icon} ₹{t['pnl']:.2f}\n"
    else:
        msg += "No trades completed today."
    print(msg)
except Exception as e:
    print(f"Error: {e}")
