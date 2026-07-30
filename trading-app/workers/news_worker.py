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
        a = (asset or "").upper().replace(" ", "").replace("-", "")
        # Commodities -> MCX prefix (resolved to the current FUT contract downstream, then validated).
        mapping = {
            "CRUDEOIL": "MCX:CRUDEOIL", "CRUDE": "MCX:CRUDEOIL",
            "GOLD": "MCX:GOLD", "SILVER": "MCX:SILVER",
            "NATURALGAS": "MCX:NATURALGAS", "NATGAS": "MCX:NATURALGAS",
            "COPPER": "MCX:COPPER", "ZINC": "MCX:ZINC", "ALUMINIUM": "MCX:ALUMINIUM",
            "LEAD": "MCX:LEAD", "NICKEL": "MCX:NICKEL", "COTTON": "MCX:COTTON",
            # USDINR (currency) intentionally omitted: currency trading is DEFERRED and its Fyers
            # symbol is NSE:USDINR{YYMDD}{STRIKE}{CE|PE} (weekly), NOT CDS:...FUT — the old mapping
            # produced dead symbols. Re-add with correct weekly-FUT resolution when currency is onboarded.
        }
        if a in mapping:
            return mapping[a]
        # Safety net: any residual commodity keyword MUST route to MCX, never NSE:<name>-EQ (that
        # produced the bad NSE:CRUDEOIL-EQ). A commodity is never a valid NSE equity symbol.
        for _kw, _mcx in (("CRUDE", "MCX:CRUDEOIL"), ("GOLD", "MCX:GOLD"), ("SILVER", "MCX:SILVER"),
                          ("NATURALGAS", "MCX:NATURALGAS"), ("NATGAS", "MCX:NATURALGAS"),
                          ("COPPER", "MCX:COPPER"), ("ZINC", "MCX:ZINC")):
            if _kw in a:
                return _mcx
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

    def _inject_asset(self, asset: str, window_ok: bool, kind: str):
        """Resolve -> validate -> inject one AI-picked asset into every user's watchlist.

        Shared by the equity and commodity slots so both go through the SAME live-quote
        validation (an unquotable/expired symbol is never pushed to the WS feed — that is what
        produced the -300 'Invalid symbol' storms). `window_ok` is the caller's session gate:
        equities stop at 15:00, commodities run to 22:00 for the MCX session.
        """
        if not asset or asset == "NONE" or not window_ok:
            return
        try:
            symbol_prefix = self._resolve_symbol(asset)
            if not symbol_prefix:
                return
            val_client = self._get_validation_client()
            if symbol_prefix.startswith("MCX:") or symbol_prefix.startswith("CDS:"):
                from engine.strikes import resolve_current_commodity_expiry
                # Resolve to the LIVE futures contract. Passing the client validates against the
                # history API and rolls past an expired month (crude expires ~19-20th), so we never
                # inject a dead contract like MCX:CRUDEOIL26JULFUT after July expiry.
                exact_symbol = resolve_current_commodity_expiry(symbol_prefix, client=val_client)
            else:
                exact_symbol = symbol_prefix
            if not exact_symbol:
                return

            if not self._is_quotable(val_client, exact_symbol):
                logger.warning(f"⏭️ Skipped unquotable {kind} injection: {exact_symbol} "
                               f"(from '{asset}') — not added to watch")
                return

            logger.info(f"🔥 AI {kind} pick: {asset} → injecting VALID {exact_symbol} "
                        f"— auto-trade ENABLED!")
            for u_id, state in USER_STATES.items():
                if exact_symbol not in state.active_symbols or \
                   exact_symbol not in getattr(state, "enabled_symbols", []):
                    state.add_symbol(exact_symbol, enable=True, by_agent=True)
        except Exception as e:
            logger.error(f"{kind} injection error for '{asset}': {e}")

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
            import state as _state_mod
            _state_mod.global_macro_summary = self.last_summary
            logger.info(f"📰 AI Global Macro Summary Updated: EQ={self.last_summary['equities_trend']}, COM={self.last_summary['commodities_trend']}, FX={self.last_summary['currency_trend']}")
            
            # Auto-Symbol Injection (news-driven). Every candidate is VALIDATED with a live quote
            # before it touches any user's watch / the WS feed — this closes the disconnect-storm
            # vector where AI-hallucinated or wrong-expiry symbols hit Fyers and churned the feed (-300).
            # Do NOT auto-inject in the last part of the session (>= 15:00 IST). Injected scrips are
            # purged at the 15:14 hard-exit; injecting after that would re-populate the watchlist
            # right before/after close. Fresh picks resume next morning.
            import datetime as _dt, pytz as _pytz
            _now_ist = _dt.datetime.now(_pytz.timezone("Asia/Kolkata"))

            # EQUITY window: nothing after 15:00 IST. Injected scrips are purged at the 15:14
            # hard-exit, so a later injection would just re-populate the watchlist at close.
            _equity_ok = _now_ist.hour < 15
            # COMMODITY window: MCX trades until ~23:30, so commodities get their OWN window.
            # The old single `hour < 15` gate meant the agent could NEVER add an MCX scrip during
            # MCX's actual session — one of two reasons it had injected ZERO commodities ever.
            # Stop at 22:00 so a fresh scrip still has runway before the 23:20 MCX hard-exit.
            _commodity_ok = 9 <= _now_ist.hour < 22

            # ── Telegram Concise Global Intelligence Dispatcher ──
            try:
                from engine.notifier import send_webhook_alert
                import os
                wh_url = os.getenv("TELEGRAM_WEBHOOK", "")
                if wh_url:
                    today_str = _now_ist.strftime("%Y-%m-%d")
                    current_hour = _now_ist.hour
                    current_minute = _now_ist.minute

                    is_pre_market = (8 <= current_hour < 9 and current_minute >= 40)
                    is_market_hours = (9 <= current_hour <= 22)

                    last_hourly = getattr(self, "_last_hourly_hour", -1)
                    last_pre_date = getattr(self, "_last_pre_market_date", "")

                    should_send = False
                    title_prefix = "🌐 Global News Brief"

                    if is_pre_market and last_pre_date != today_str:
                        should_send = True
                        self._last_pre_market_date = today_str
                        title_prefix = "🌅 Pre-Market Global Briefing"
                    elif is_market_hours and last_hourly != current_hour:
                        should_send = True
                        self._last_hourly_hour = current_hour
                        title_prefix = f"📊 Market Briefing ({_now_ist.strftime('%H:00 IST')})"

                    if should_send:
                        bullets = result.get("telegram_bullets") or [
                            f"• 📌 Global Summary: {result.get('summary', 'No summary')}",
                            f"• 🎯 Indian Equities: {result.get('equities_trend', 'NEUTRAL')}",
                            f"• 🛢️ Commodities: {result.get('commodities_trend', 'NEUTRAL')}"
                        ]
                        bullet_text = "\n".join(bullets)
                        msg = (
                            f"<b>{title_prefix}</b>\n\n"
                            f"{bullet_text}\n\n"
                            f"<b>Biases:</b> EQ: <code>{self.last_summary['equities_trend']}</code> | "
                            f"MCX: <code>{self.last_summary['commodities_trend']}</code> | "
                            f"FX: <code>{self.last_summary['currency_trend']}</code>"
                        )
                        await send_webhook_alert(wh_url, msg, title=title_prefix)
                        logger.info(f"📲 Sent Telegram Global Intelligence Update ({title_prefix})")
            except Exception as tg_err:
                logger.warning(f"Telegram news dispatch warning: {tg_err}")

            self._inject_asset(result.get("high_conviction_asset", "NONE"), _equity_ok, "equity")
            self._inject_asset(result.get("commodity_pick", "NONE"), _commodity_ok, "commodity")
                                
        except Exception as e:
            logger.error(f"Error updating global news summary: {e}")

    async def run(self):
        logger.info("🚀 Global News Worker started.")
        while True:
            await self.update_summary()
            await asyncio.sleep(self.interval_seconds)

news_worker = NewsWorker()
