import sqlite3
from datetime import datetime

conn = sqlite3.connect('/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app/trading_app.db')
c = conn.cursor()

print("--- PnL History ---")
c.execute("SELECT date, pnl, trades FROM daily_pnl_history ORDER BY date DESC LIMIT 5")
for row in c.fetchall():
    print(f"Live PnL [{row[0]}]: {row[1]} ({row[2]} trades)")

c.execute("SELECT date, pnl, trades FROM paper_pnl_history ORDER BY date DESC LIMIT 5")
for row in c.fetchall():
    print(f"Paper PnL [{row[0]}]: {row[1]} ({row[2]} trades)")

print("\n--- Recent Logs ---")
c.execute("SELECT timestamp, level, message FROM system_logs ORDER BY id DESC LIMIT 20")
for row in c.fetchall():
    print(f"[{row[0]}] {row[1]}: {row[2]}")

conn.close()
