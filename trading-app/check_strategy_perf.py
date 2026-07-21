"""
Read-only performance report per strategy. Run after any session to see whether
Strategy 1 (Variant L) is actually working, using REAL recorded outcomes.

    .venv/bin/python3 check_strategy_perf.py

Reads swarm_trade_records (per-trade outcomes) + daily_pnl_history (daily totals).
Writes nothing, places no orders, touches no state.

Data-integrity note: rows with exit_price = 0 are UNRELIABLE — they predate the
outcome-integrity guard (or hit a broker dict with no sellAvg/buyAvg). They are
counted separately so they cannot silently distort the win rate.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models  # noqa: E402


def main():
    conn = sqlite3.connect(models.Database.DB_NAME)
    conn.row_factory = sqlite3.Row

    print("=" * 72)
    print("PER-STRATEGY RECORDED OUTCOMES  (swarm_trade_records)")
    print("=" * 72)
    rows = conn.execute("""
        SELECT strategy_name,
               COUNT(*)                                        AS n,
               SUM(CASE WHEN exit_price>0 THEN 1 ELSE 0 END)    AS valid,
               SUM(CASE WHEN exit_price<=0 THEN 1 ELSE 0 END)   AS unreliable,
               SUM(CASE WHEN pnl>0 AND exit_price>0 THEN 1 ELSE 0 END) AS wins,
               ROUND(SUM(CASE WHEN exit_price>0 THEN pnl ELSE 0 END),2) AS pnl
        FROM swarm_trade_records GROUP BY strategy_name ORDER BY n DESC
    """).fetchall()
    if not rows:
        print("  (no trades recorded yet)")
    for r in rows:
        v = r["valid"] or 0
        wr = f"{(r['wins'] / v * 100):5.1f}%" if v else "   n/a"
        flag = f"  ⚠️ {r['unreliable']} unreliable(exit=0)" if r["unreliable"] else ""
        print(f"  {r['strategy_name'][:38]:<38} n={r['n']:<4} valid={v:<4} "
              f"win={wr}  pnl=Rs{r['pnl'] or 0:<10}{flag}")

    print("\n" + "=" * 72)
    print("STRATEGY 1 — recent trades (Variant L: confluence-only, BE-trail, 2/day)")
    print("=" * 72)
    s1 = conn.execute("""
        SELECT entry_time, exit_time, symbol, entry_price, exit_price, pnl, market_trend
        FROM swarm_trade_records WHERE strategy_name LIKE 'Strategy 1%'
        ORDER BY entry_time DESC LIMIT 12
    """).fetchall()
    if not s1:
        print("  (no Strategy 1 trades recorded yet — it only fires on OB+FVG confluence)")
    for t in s1:
        bad = "  ⚠️UNRELIABLE" if (t["exit_price"] or 0) <= 0 else ""
        print(f"  {t['entry_time']}  {t['symbol'][:26]:<26} "
              f"in={t['entry_price']:<8} out={t['exit_price']:<8} pnl={t['pnl']:<9}{bad}")

    print("\n" + "=" * 72)
    print("DAILY P&L — last 10 active days (all strategies, live)")
    print("=" * 72)
    for r in conn.execute("""
        SELECT date, ROUND(pnl,2) pnl, trades FROM daily_pnl_history
        WHERE pnl != 0 OR trades > 0 ORDER BY date DESC LIMIT 10
    """):
        print(f"  {r['date']}   pnl=Rs{r['pnl']:<12} trades={r['trades']}")

    tot = conn.execute("SELECT ROUND(SUM(pnl),2), COUNT(*) FROM daily_pnl_history").fetchone()
    print(f"\n  lifetime: Rs{tot[0]} over {tot[1]} recorded days")
    print("=" * 72)


if __name__ == "__main__":
    main()
