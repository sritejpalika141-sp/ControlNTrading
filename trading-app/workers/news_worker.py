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
        """Helper to resolve high conviction asset to a Fyers Symbol prefix.
        Whatever this returns is VALIDATED against a live quote before injection (see update_summary),
        so a wrong guess is skipped, never pushed onto the WS feed."""
        # Commodities -> MCX prefix (resolved to the current FUT contract downstream, then validated).
        mapping = {
            "CRUDEOIL": "MCX:CRUDEOIL",
            "GOLD": "MCX:GOLD",
            "SILVER": "MCX:SILVER",
            # USDINR (currency) intentionally omitted: currency trading is DEFERRED and its Fyers
            # symbol is NSE:USDINR{YYMDD}{STRIKE}{CE|PE} (weekly), NOT CDS:...FUT — the old mapping
            # produced dead symbols. Re-add with correct weekly-FUT resolution when currency is onboarded.
        }
        if asset in mapping:
            return mapping[asset]
        if asset and asset != "NONE":
            return f"NSE:{asset}-EQ"
        return ""

    def _get_validation_client(self):
        """Return one authenticated Fyers client for symbol validation (symbol validity is global,
        so any authenticated user's client works). None if nobody is authenticated (e.g. token
        expired) — in which case injection is skipped rather than pushing an unvalidated symbol."""
        try:
            from state import USER_STATES
            from fyers_client import FyersClient
            for u_id in list(USER_STATES.keys()):
                try:
                    c = FyersClient(user_id=u_id)
                    if c.is_authenticated():
                        return c
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _is_quotable(self, client, symbol: str) -> bool:
        """True only if the symbol returns a live last-price > 0 — the same gate nightly_learning uses."""
        if client is None or not symbol:
            return False
        try:
            q = client.get_quote(symbol)
            return bool(q and q.get("lp", 0) > 0)
        except Exception:
            return False

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
            
            # Auto-Symbol Injection (news-driven). Every candidate is VALIDATED with a live quote
            # before it touches any user's watch / the WS feed — this closes the disconnect-storm
            # vector where AI-hallucinated or wrong-expiry symbols hit Fyers and churned the feed (-300).
            # Do NOT auto-inject in the last part of the session (>= 15:00 IST). Injected scrips are
            # purged at the 15:14 hard-exit; injecting after that would re-populate the watchlist
            # right before/after close. Fresh picks resume next morning.
            import datetime as _dt, pytz as _pytz
            _now_ist = _dt.datetime.now(_pytz.timezone("Asia/Kolkata"))
            _inject_ok = _now_ist.hour < 15
            high_conviction = result.get("high_conviction_asset", "NONE")
            if _inject_ok and high_conviction and high_conviction != "NONE":
                symbol_prefix = self._resolve_symbol(high_conviction)
                if symbol_prefix:
                    is_commodity = symbol_prefix.startswith("MCX:") or symbol_prefix.startswith("CDS:")
                    if is_commodity:
                        from engine.strikes import resolve_current_commodity_expiry
                        # Resolve to the exact current futures symbol, e.g. MCX:CRUDEOIL26JULFUT.
                        # The guessed contract month may not exist (esp. gold/silver) — validation below
                        # skips it cleanly rather than pushing a dead symbol to the feed.
                        exact_symbol = resolve_current_commodity_expiry(symbol_prefix)
                    else:
                        exact_symbol = symbol_prefix
                    if exact_symbol:
                        val_client = self._get_validation_client()
                        if not self._is_quotable(val_client, exact_symbol):
                            logger.warning(f"⏭️ Skipped unquotable news-injection symbol: {exact_symbol} "
                                           f"(from '{high_conviction}') — not added to watch")
                        else:
                            enable = True
                            mode = "auto-trade ENABLED"
                            logger.info(f"🔥 AI selected {high_conviction} based on news trends. "
                                        f"Injecting VALID {exact_symbol} — {mode}!")
                            for u_id, state in USER_STATES.items():
                                if exact_symbol not in state.active_symbols or (enable and exact_symbol not in getattr(state, 'enabled_symbols', [])):
                                    state.add_symbol(exact_symbol, enable=enable, by_agent=True)
                                
        except Exception as e:
            logger.error(f"Error updating global news summary: {e}")

    async def run(self):
        logger.info("🚀 Global News Worker started.")
        while True:
            await self.update_summary()
            await asyncio.sleep(self.interval_seconds)

news_worker = NewsWorker()
