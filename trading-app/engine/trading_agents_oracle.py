import asyncio
import logging
from datetime import datetime
import pytz

logger = logging.getLogger("AI_ORACLE")
IST = pytz.timezone('Asia/Kolkata')

def _run_oracle_sync(ticker: str, date_str: str) -> str:
    """Synchronous function to run TradingAgents."""
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG
        
        # We can configure the llm_provider to 'google' to use Gemini,
        # but since user might have standard env vars, we leave it to DEFAULT_CONFIG.
        config = DEFAULT_CONFIG.copy()
        
        logger.info(f"🔮 Starting Pre-Market AI Oracle for {ticker} on {date_str}...")
        ta = TradingAgentsGraph(debug=False, config=config)
        
        _, decision = ta.propagate(ticker, date_str)
        
        decision_str = str(decision).upper()
        
        if "BULL" in decision_str or "LONG" in decision_str or "BUY" in decision_str:
            return "BULLISH"
        elif "BEAR" in decision_str or "SHORT" in decision_str or "SELL" in decision_str:
            return "BEARISH"
        else:
            return "NEUTRAL"
            
    except Exception as e:
        logger.error(f"❌ Oracle failed: {e}")
        return "NEUTRAL"

async def get_daily_bias(ticker: str = "^NSEI") -> str:
    """
    Runs the Oracle in a background thread so it doesn't block the main event loop.
    """
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    bias = await asyncio.to_thread(_run_oracle_sync, ticker, today_str)
    logger.info(f"📊 Oracle Result for {today_str}: {bias}")
    return bias
