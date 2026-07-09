import sqlite3
import datetime

def seed():
    conn = sqlite3.connect("trading-app/trading_app.db")
    cursor = conn.cursor()
    
    agents = [
        ("OB + FVG — Smart Money", "{}", datetime.datetime.now().isoformat(), 55.0, 10, 5),
        ("9:26 Buy Breakout", "{}", datetime.datetime.now().isoformat(), 60.0, 15, 9),
        ("5-Minute ORB", "{}", datetime.datetime.now().isoformat(), 58.5, 20, 11),
        ("Wisdom-Aligned Pullback", "{}", datetime.datetime.now().isoformat(), 52.0, 8, 4),
        ("Aerospace Mean Reversion", "{}", datetime.datetime.now().isoformat(), 65.0, 12, 8)
    ]
    
    for agent in agents:
        cursor.execute("""
            INSERT OR IGNORE INTO swarm_agent_configs (strategy_name, config_json, last_updated, win_rate, total_trades, winning_trades)
            VALUES (?, ?, ?, ?, ?, ?)
        """, agent)
        
    conn.commit()
    conn.close()
    print("Seeded swarm_agent_configs")

if __name__ == "__main__":
    seed()
