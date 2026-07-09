import asyncio
import logging
import httpx
import xml.etree.ElementTree as ET
try:
    import defusedxml.ElementTree as dET
except ImportError:
    dET = ET
from engine.ai_engine import AIEngine
import time

logger = logging.getLogger("NEWS_WORKER")

class NewsWorker:
    def __init__(self):
        self.ai = AIEngine()
        self.last_summary = {"trend": "NEUTRAL", "summary": "Waiting for first news fetch...", "ts": 0}
        self.interval_seconds = 1800  # 30 mins
        # Use Moneycontrol top news RSS
        self.rss_urls = [
            "https://www.moneycontrol.com/rss/MCtopnews.xml",
            "https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms"
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

    async def update_summary(self):
        try:
            logger.info("📰 Fetching market news...")
            headlines = await self.fetch_rss_headlines()
            if not headlines:
                logger.warning("No headlines fetched.")
                return

            # Keep it reasonable, AI shouldn't read 100 headlines
            top_headlines = headlines[:20]
            
            result = await self.ai.get_daily_news_summary(top_headlines)
            self.last_summary = {
                "trend": result.get("trend", "NEUTRAL"),
                "summary": result.get("summary", "No clear sentiment."),
                "ts": time.time()
            }
            logger.info(f"📰 AI News Summary Updated: {self.last_summary['trend']}")
        except Exception as e:
            logger.error(f"Error updating news summary: {e}")

    async def run(self):
        logger.info("🚀 News Worker started.")
        while True:
            await self.update_summary()
            await asyncio.sleep(self.interval_seconds)

news_worker = NewsWorker()
