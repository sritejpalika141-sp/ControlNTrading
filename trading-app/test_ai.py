import asyncio
from engine.ai_engine import ai_engine
import json

async def main():
    context = {
        "vix": 19.54,
        "gap_type": "Normal",
        "option_chain": {},
        "spot": 23529.40,
        "heavyweights": [],
        "trend": {"trend": "BULLISH"},
        "chp": -0.48,
        "ch": -114.10,
        "three_day_summary": "Day 1 (High: 24000, Low: 23500) | Day 2 (High: 23900, Low: 23400)"
    }
    symbol = "NSE:NIFTY50-INDEX"
    print(f"Enabled: {ai_engine.enabled}")
    res = await ai_engine.get_ai_trend(symbol, context)
    print(json.dumps(res, indent=2))

asyncio.run(main())
