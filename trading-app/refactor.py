import os
FILE_PATH = "/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app/workers/auto_trader.py"

with open(FILE_PATH, 'r') as f:
    content = f.read()

# Import
content = content.replace(
    "from engine.ws_feed import ws_feed",
    "from engine.ws_feed import ws_feed\nfrom engine.risk_orchestrator import orchestrator as risk_orchestrator"
)

# Strategy 2
content = content.replace(
    "await execute_auto_trade(sig_926['symbol'], sig_926, {\"trend\": trend_dict}, client)",
    "await risk_orchestrator.propose_trade(\"Strategy 2\", sig_926['symbol'], sig_926, {\"trend\": trend_dict}, client, state)"
)

# Strategy 3
content = content.replace(
    "await execute_auto_trade(symbol, sig_orb, {\"trend\": \"NEUTRAL\"}, client)\n                                            state.strat_orb_triggered = True\n                                            state.save()",
    "await risk_orchestrator.propose_trade(\"Strategy 3\", symbol, sig_orb, {\"trend\": \"NEUTRAL\"}, client, state)"
)

# Strategy 5
content = content.replace(
    "await execute_auto_trade(sig_strat5['symbol'], sig_strat5, {\"trend\": \"N/A\"}, client)",
    "await risk_orchestrator.propose_trade(\"Strategy 5\", sig_strat5.get('symbol', 'NSE:NIFTY50-INDEX'), sig_strat5, {\"trend\": \"N/A\"}, client, state)"
)

# Strategy 4
content = content.replace(
    "await execute_auto_trade(symbol, sig_wisdom, {\"trend\": sig_wisdom.get(\"metadata\", {}).get(\"trend\", \"NEUTRAL\")}, client)\n                                        state.strat_4_trades = getattr(state, \"strat_4_trades\", 0) + 1\n                                        state.save()",
    "await risk_orchestrator.propose_trade(\"Strategy 4\", symbol, sig_wisdom, {\"trend\": sig_wisdom.get(\"metadata\", {}).get(\"trend\", \"NEUTRAL\")}, client, state)"
)

# Strategy 6
content = content.replace(
    "await execute_auto_trade(symbol, sig_gap, {\"trend\": {\"trend\": \"NEUTRAL\"}}, client)\n                                        state.strat_6_trades_today = getattr(state, \"strat_6_trades_today\", 0) + 1\n                                        state.save()\n                                        continue",
    "await risk_orchestrator.propose_trade(\"Strategy 6\", symbol, sig_gap, {\"trend\": {\"trend\": \"NEUTRAL\"}}, client, state)\n                                        continue"
)

# Strategy 7 (Initial)
content = content.replace(
    "await execute_auto_trade(symbol, sig_swing, {\"trend\": \"NEUTRAL\"}, client)\n                                            state.strat_7_trades_today = getattr(state, \"strat_7_trades_today\", 0) + 1\n                                            state.strat_7_pending_order = None\n                                            state.save()\n                                            continue",
    "await risk_orchestrator.propose_trade(\"Strategy 7\", symbol, sig_swing, {\"trend\": \"NEUTRAL\"}, client, state)\n                                            state.strat_7_pending_order = None\n                                            state.save()\n                                            continue"
)

# TIER 1 auto-trade generic blocks (Strategy 1, 8, 9)
# These fall into the "if tech_conf >= 70" block.
content = content.replace(
    "await execute_auto_trade(symbol, sig, analysis, client)",
    "await risk_orchestrator.propose_trade(sig.get('strategy_name', 'Strategy 1'), symbol, sig, analysis, client, state)"
)


with open(FILE_PATH, 'w') as f:
    f.write(content)
print("Updated auto_trader.py directly")
