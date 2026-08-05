"""
check_nightly_learning_report.py (05-08-26)

Cron-invoked, run every 10 min in the evening window. Checks whether tonight's natural
nightly_learning run (fires once ALL markets — NSE + MCX crude — are closed, gated at >=15:35
IST as a floor but really bound by MCX's ~23:20-23:30 close) has completed, and if so, sends a
ONE-TIME Telegram report summarizing every strategy's backtest performance and what
nightly_learning actually decided for it. Uses a per-day sent-marker file so it only sends once,
regardless of how many times cron ticks afterward.

Does NOT trigger nightly_learning itself — purely observes and reports on the real, naturally
scheduled run (engine.automation.TradingState.check_and_run_nightly_learning, called from
workers/auto_trader.py's automation_loop once all markets are closed).
"""
import os
import sys
import re
import sqlite3
import requests
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_LOG = os.path.join(BASE_DIR, "logs", "dashboard.log")
DB_PATH = os.path.join(BASE_DIR, "trading_app.db")
MIN_TRADES_FOR_LEARNING = 10

# All 13 strategies, in report order.
ALL_STRATEGIES = [
    "Strategy 1: OB + FVG", "Strategy 2: 9:26 - 180 Buy", "Strategy 3: 5-Minute ORB",
    "Strategy 4: Wisdom-Aligned Pullback", "Strategy 5: Optimized Aerospace Mean Reversion",
    "Strategy 6: Gap Fill Reversal", "Strategy 7: Swing-Pivot Breakout",
    "Strategy 8: Smart Money Concepts", "Strategy 9: 9-EMA Momentum Scalper",
    "Strategy 10: Adaptive ADX Engine", "Strategy 11: FRVP LVN Vacuum",
    "Crude Evening Momentum", "Crude EIA Volatility",
]


def load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def nightly_learning_completed_today(today_str: str) -> bool:
    """Look for tonight's success line in dashboard.log — the same 'Nightly Learning Complete'
    line the real run always prints on success, regardless of what it decided per strategy."""
    if not os.path.exists(DASHBOARD_LOG):
        return False
    try:
        with open(DASHBOARD_LOG, "r", errors="ignore") as f:
            for line in f:
                if today_str in line and "Nightly Learning Complete" in line:
                    return True
    except Exception:
        pass
    return False


def build_report(today_str: str, yesterday_str: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Latest backtest_results per strategy (today's run, if present, else whatever's latest).
    backtest = {}
    for r in cur.execute("""
        SELECT b.strategy_name, b.trades, b.wins, b.losses, b.win_rate, b.total_pnl, b.run_date
          FROM backtest_results b
          INNER JOIN (SELECT strategy_name, MAX(run_date) md FROM backtest_results GROUP BY strategy_name) l
            ON b.strategy_name = l.strategy_name AND b.run_date = l.md
    """):
        backtest[r["strategy_name"]] = dict(r)

    configs = {}
    for r in cur.execute("SELECT strategy_name, status, is_paper_trading, pending_config_json, last_updated FROM swarm_agent_configs"):
        configs[r["strategy_name"]] = dict(r)
    conn.close()

    lines = [f"🌙 <b>Nightly Learning Report — {today_str}</b>", ""]
    any_applied = False
    any_pending = False
    any_ai_failed = False

    for strat in ALL_STRATEGIES:
        bt = backtest.get(strat)
        cfg = configs.get(strat)
        if not bt:
            lines.append(f"• <b>{strat}</b>: no backtest data found.")
            continue
        trades, win_rate, pnl = bt["trades"], bt["win_rate"], bt["total_pnl"]
        gate = "✅ crossed" if trades >= MIN_TRADES_FOR_LEARNING else "⏭️ below"
        line = f"• <b>{strat}</b>: {trades} backtested trades, {win_rate:.1f}% win, {pnl:+.0f} pts — gate {gate} ({MIN_TRADES_FOR_LEARNING} needed)"
        if trades >= MIN_TRADES_FOR_LEARNING and cfg:
            last_upd = (cfg.get("last_updated") or "")[:10]
            if last_upd == today_str:
                if cfg.get("pending_config_json"):
                    line += "\n   → 🟡 AI suggested a MAJOR change — pending your approval."
                    any_pending = True
                else:
                    line += "\n   → 🟢 AI critique ran and applied/updated config tonight."
                    any_applied = True
            else:
                line += "\n   → 🔴 AI critique did not update this strategy tonight (likely provider exhaustion again)."
                any_ai_failed = True
        lines.append(line)

    lines.append("")
    if any_applied or any_pending:
        lines.append(f"Summary: {'some changes applied. ' if any_applied else ''}{'some pending your approval. ' if any_pending else ''}")
    if any_ai_failed and not (any_applied or any_pending):
        lines.append("⚠️ Every qualifying strategy's AI critique failed again tonight (provider exhaustion) — same as this afternoon's manual run. Worth looking at AI provider quotas/config directly.")
    elif not any_applied and not any_pending and not any_ai_failed:
        lines.append("No strategy crossed the 10-trade backtest threshold yet — nothing to tune.")

    return "\n".join(lines)


def send_telegram(webhook_url: str, message: str, title: str = "Nightly Learning Report"):
    if not webhook_url:
        print("No webhook_url configured — cannot send report.")
        return False
    url = webhook_url.split("&text=")[0].split("?text=")[0]
    payload = {"text": f"<b>{title}</b>\n{message}", "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=15.0)
        ok = resp.status_code in (200, 204)
        if not ok:
            print(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"Telegram send exception: {e}")
        return False


def main():
    load_env()
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    sent_marker = os.path.join(BASE_DIR, "logs", f".nightly_report_sent_{today_str}")
    if os.path.exists(sent_marker):
        print(f"Already sent today's report ({sent_marker} exists) — nothing to do.")
        return

    if not nightly_learning_completed_today(today_str):
        print(f"Nightly learning has not completed yet as of {now.strftime('%H:%M:%S')} IST — will retry next tick.")
        return

    report = build_report(today_str, yesterday_str)

    sys.path.insert(0, BASE_DIR)
    try:
        from state import get_user_state
        state = get_user_state(1)
        webhook_url = getattr(state, "webhook_url", "") or os.getenv("TELEGRAM_WEBHOOK", "")
    except Exception as e:
        print(f"Could not load webhook_url from state, falling back to env: {e}")
        webhook_url = os.getenv("TELEGRAM_WEBHOOK", "")

    ok = send_telegram(webhook_url, report)
    if ok:
        with open(sent_marker, "w") as f:
            f.write(now.isoformat())
        print("Report sent and marker written.")
    else:
        print("Report send FAILED — will retry next cron tick (no marker written).")


if __name__ == "__main__":
    main()
