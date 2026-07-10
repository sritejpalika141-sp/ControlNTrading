import asyncio
import logging
import httpx
import xml.etree.ElementTree as ET
try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET
from engine.ai_engine import AIEngine
from state import USER_STATES
import time

logger = logging.getLogger("NEWS_WORKER")

class NewsWorker:
    def __init__(self):
        self.ai = AIEngine()
        self.last_summary = {
            "equities_trend": "NEUTRAL",
            "commodities_trend": "NEUTRAL",
            "currency_trend": "NEUTRAL",
            "summary": "Waiting for first news fetch...", 
            "ts": 0
        }
        self.interval_seconds = 1800  # 30 mins
        # Use Global & Indian RSS Feeds
        self.rss_urls = [
            "https://www.moneycontrol.com/rss/MCtopnews.xml", # Indian Equities
            "https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms", # General Markets
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000811", # Global Markets
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000836"  # Commodities
        ]

    async def fetch_rss_headlines(self) -> list:
        headlines = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for url in self.rss_urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        root = dET.fromstring(resp.text)
                        # Find all items
                        for item in root.findall(".//item")[:10]:  # limit to top 10 per feed
                            title = item.find("title")
                            if title is not None and title.text:
                                headlines.append(title.text)
                except Exception as e:
                    logger.warning(f"Failed to fetch RSS {url}: {e}")
        return headlines

    def _resolve_symbol(self, asset: str) -> str:
        """Helper to resolve high conviction asset to a Fyers Symbol prefix."""
        # E.g., GOLD -> MCX:GOLD, USDINR -> CDS:USDINR
        mapping = {
            "CRUDEOIL": "MCX:CRUDEOIL",
            "GOLD": "MCX:GOLD",
            "SILVER": "MCX:SILVER",
            "USDINR": "CDS:USDINR"
        }
        return mapping.get(asset, "")

    async def update_summary(self):
        try:
            logger.info("📰 Fetching global market news...")
            headlines = await self.fetch_rss_headlines()
            if not headlines:
                logger.warning("No headlines fetched.")
                return

            # Keep it reasonable, AI shouldn't read 100 headlines
            top_headlines = headlines[:30]
            
            result = await self.ai.get_global_macro_summary(top_headlines)
            self.last_summary = {
                "equities_trend": result.get("equities_trend", "NEUTRAL"),
                "commodities_trend": result.get("commodities_trend", "NEUTRAL"),
                "currency_trend": result.get("currency_trend", "NEUTRAL"),
                "summary": result.get("summary", "No clear sentiment."),
                "ts": time.time()
            }
            logger.info(f"📰 AI Global Macro Summary Updated: EQ={self.last_summary['equities_trend']}, COM={self.last_summary['commodities_trend']}, FX={self.last_summary['currency_trend']}")
            
            # Auto-Symbol Injection
            high_conviction = result.get("high_conviction_asset", "NONE")
            if high_conviction and high_conviction != "NONE":
                symbol_prefix = self._resolve_symbol(high_conviction)
                if symbol_prefix:
                    from engine.strikes import resolve_current_commodity_expiry
                    # We need to resolve it to the exact futures symbol, e.g., MCX:CRUDEOIL24NOVFUT
                    exact_symbol = await resolve_current_commodity_expiry(symbol_prefix)
                    if exact_symbol:
                        logger.info(f"🔥 AI selected {high_conviction} based on news trends. Injecting {exact_symbol} into user market watch!")
                        for u_id, state in USER_STATES.items():
                            if exact_symbol not in state.active_symbols:
                                state.add_symbol(exact_symbol)
                                
        except Exception as e:
            logger.error(f"Error updating global news summary: {e}")

    async def run(self):
        logger.info("🚀 Global News Worker started.")
        while True:
            await self.update_summary()
            await asyncio.sleep(self.interval_seconds)

news_worker = NewsWorker()
