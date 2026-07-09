import sqlite3

conn = sqlite3.connect('/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app/trading_app.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("SELECT * FROM user_states")
rows = c.fetchall()
if rows:
    for row in rows:
        print(f"User ID: {row['user_id']}")
        print(f"Active Strategies: {row['active_strategies']}")
        print(f"Active Auto Trades: {row['active_auto_trades']}")
        print(f"Trades Today: {row['trades_today']}")
        print(f"PnL Today: {row['pnl_today']}")
else:
    print("No user states found in database.")

conn.close()
