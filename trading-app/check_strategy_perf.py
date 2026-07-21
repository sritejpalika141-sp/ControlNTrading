"""
Read-only per-strategy performance report.

Two entry points, ONE implementation:
  * CLI      : .venv/bin/python3 check_strategy_perf.py      (verbose, plain text)
  * Scheduler: build_report(compact=True) -> HTML for the daily Telegram push
                (see daily_strategy_report_scheduler in app.py)

Reads swarm_trade_records (per-trade outcomes) + daily_pnl_history (daily totals).
Writes nothing, places no orders, touches no state.

Data-integrity note: rows with exit_price = 0 are UNRELIABLE — they predate the
outcome-integrity guard (or hit a broker dict with no sellAvg/buyAvg). They are counted
SEPARATELY so a zero can never silently distort the win rate.
"""
import os
import sqlite3
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")


def _rows(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except Exception:
        return []


def build_report(compact: bool = False) -> str:
    """Build the performance report. compact=True -> short HTML for Telegram."""
    b = (lambda s: f"<b>{s}</b>") if compact else (lambda s: s)
    out = []
    today = datetime.now(IST).date().isoformat()

    try:
        conn = sqlite3.connect(models.Database.DB_NAME)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        return f"⚠️ Strategy report unavailable: {e}"

    # ── today ──────────────────────────────────────────────────────────────
    out.append(f"📊 {b('Daily Strategy Report')}")
    out.append(f"🗓️ {today}\n")
    trow = _rows(conn, "SELECT ROUND(SUM(pnl),2) p, SUM(trades) t FROM daily_pnl_history WHERE date=?", (today,))
    p = (trow[0]["p"] if trow and trow[0]["p"] is not None else 0.0)
    t = (trow[0]["t"] if trow and trow[0]["t"] is not None else 0)
    icon = "🟢" if p > 0 else "🔴" if p < 0 else "⚪"
    out.append(f"{icon} {b('Today')}: ₹{p:.2f} across {t} trade(s)")

    # ── per-strategy recorded outcomes ─────────────────────────────────────
    out.append(f"\n{b('Per-strategy outcomes')}")
    srows = _rows(conn, """
        SELECT strategy_name,
               COUNT(*) n,
               SUM(CASE WHEN exit_price>0 THEN 1 ELSE 0 END) valid,
               SUM(CASE WHEN exit_price<=0 THEN 1 ELSE 0 END) bad,
               SUM(CASE WHEN pnl>0 AND exit_price>0 THEN 1 ELSE 0 END) wins,
               ROUND(SUM(CASE WHEN exit_price>0 THEN pnl ELSE 0 END),2) pnl
        FROM swarm_trade_records GROUP BY strategy_name ORDER BY n DESC
    """)
    if not srows:
        out.append("  (no trades recorded yet)")
    for r in srows:
        v = r["valid"] or 0
        wr = f"{(r['wins'] / v * 100):.0f}%" if v else "n/a"
        warn = f" ⚠️{r['bad']} unreliable" if r["bad"] else ""
        name = r["strategy_name"][:30]
        out.append(f"  {name}: {v} valid, win {wr}, ₹{r['pnl'] or 0}{warn}")

    # ── Strategy 1 today (Variant L) ───────────────────────────────────────
    out.append(f"\n{b('Strategy 1 today (Variant L)')}")
    s1 = _rows(conn, """
        SELECT entry_time, symbol, entry_price, exit_price, pnl
        FROM swarm_trade_records
        WHERE strategy_name LIKE 'Strategy 1%' AND entry_time LIKE ?
        ORDER BY entry_time DESC LIMIT 5
    """, (f"{today}%",))
    if not s1:
        out.append("  No trades today (fires only on OB+FVG confluence).")
    for r in s1:
        bad = " ⚠️unreliable" if (r["exit_price"] or 0) <= 0 else ""
        icon2 = "🟢" if (r["pnl"] or 0) > 0 else "🔴" if (r["pnl"] or 0) < 0 else "⚪"
        out.append(f"  {icon2} {r['symbol'][:24]} in {r['entry_price']} out {r['exit_price']} ₹{r['pnl']}{bad}")

    # ── recent activity + lifetime ─────────────────────────────────────────
    lim = 5 if compact else 10
    out.append(f"\n{b('Recent active days')}")
    for r in _rows(conn, """
        SELECT date, ROUND(pnl,2) pnl, trades FROM daily_pnl_history
        WHERE pnl != 0 OR trades > 0 ORDER BY date DESC LIMIT ?
    """, (lim,)):
        i2 = "🟢" if r["pnl"] > 0 else "🔴" if r["pnl"] < 0 else "⚪"
        out.append(f"  {i2} {r['date']}  ₹{r['pnl']}  ({r['trades']} trades)")

    tot = _rows(conn, "SELECT ROUND(SUM(pnl),2) p, COUNT(*) n FROM daily_pnl_history")
    if tot:
        out.append(f"\n📈 Lifetime: ₹{tot[0]['p']} over {tot[0]['n']} recorded days")

    # ── health flags worth surfacing daily ────────────────────────────────
    bad_total = sum((r["bad"] or 0) for r in srows)
    if bad_total:
        out.append(f"\n⚠️ {bad_total} trade(s) recorded WITHOUT a valid exit price — "
                   f"win-rate stats exclude them.")

    conn.close()
    return "\n".join(out)


def main():
    print(build_report(compact=False))


if __name__ == "__main__":
    main()
