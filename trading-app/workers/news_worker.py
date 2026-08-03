import asyncio
import json
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
            "high_conviction_asset": "NONE",
            "commodity_pick": "NONE",
            "last_injected": [],
            "last_skip_reason": "",
            "ts": 0,
        }
        self.interval_seconds = 1800  # 30 mins
        self._refresh_lock = asyncio.Lock()
        self.rss_urls = [
            "https://www.moneycontrol.com/rss/MCtopnews.xml",
            "https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms",
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000811",
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000836",
        ]

    async def fetch_rss_headlines(self) -> list:
        headlines = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for url in self.rss_urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        root = dET.fromstring(resp.text)
                        for item in root.findall(".//item")[:10]:
                            title = item.find("title")
                            if title is not None and title.text:
                                headlines.append(title.text)
                except Exception as e:
                    logger.warning(f"Failed to fetch RSS {url}: {e}")
        return headlines

    def _resolve_symbol(self, asset: str) -> str:
        """Resolve high-conviction asset to a Fyers symbol prefix (validated before inject)."""
        a = (asset or "").upper().replace(" ", "").replace("-", "")
        mapping = {
            "CRUDEOIL": "MCX:CRUDEOIL", "CRUDE": "MCX:CRUDEOIL",
            "GOLD": "MCX:GOLD", "SILVER": "MCX:SILVER",
            "NATURALGAS": "MCX:NATURALGAS", "NATGAS": "MCX:NATURALGAS",
            "COPPER": "MCX:COPPER", "ZINC": "MCX:ZINC", "ALUMINIUM": "MCX:ALUMINIUM",
            "LEAD": "MCX:LEAD", "NICKEL": "MCX:NICKEL", "COTTON": "MCX:COTTON",
        }
        if a in mapping:
            return mapping[a]
        for _kw, _mcx in (
            ("CRUDE", "MCX:CRUDEOIL"), ("GOLD", "MCX:GOLD"), ("SILVER", "MCX:SILVER"),
            ("NATURALGAS", "MCX:NATURALGAS"), ("NATGAS", "MCX:NATURALGAS"),
            ("COPPER", "MCX:COPPER"), ("ZINC", "MCX:ZINC"),
        ):
            if _kw in a:
                return _mcx
        if asset and asset != "NONE":
            return f"NSE:{asset}-EQ"
        return ""

    def _get_validation_client(self):
        """Return one authenticated Fyers client, or None if nobody is connected."""
        try:
            from state import USER_STATES, USER_CONTEXTS
            from fyers_client import FyersClient
            for _u_id, c in list(USER_CONTEXTS.items()):
                try:
                    if c and getattr(c, "is_authenticated", lambda: False)():
                        return c
                except Exception:
                    continue
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

    def _active_user_ids_for_inject(self) -> list:
        """All active DB users plus in-memory states — do not require dashboard open."""
        ids = set()
        try:
            ids.update(int(u) for u in USER_STATES.keys())
        except Exception:
            pass
        try:
            from models import Database
            import sqlite3
            conn = sqlite3.connect(Database.DB_NAME)
            try:
                rows = conn.execute("SELECT id FROM users WHERE is_active=1").fetchall()
                ids.update(int(r[0]) for r in rows)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"active user enumerate for inject failed: {e}")
        return sorted(ids)

    def _is_quotable(self, client, symbol: str) -> bool:
        if client is None or not symbol:
            return False
        try:
            q = client.get_quote(symbol)
            return bool(q and q.get("lp", 0) > 0)
        except Exception:
            return False

    def _inject_asset(self, asset: str, window_ok: bool, kind: str):
        """Resolve → validate → inject one AI pick into every active user's watchlist."""
        if not asset or asset == "NONE":
            logger.info(f"ℹ️ No {kind} pick this cycle (asset={asset!r})")
            return None
        if not window_ok:
            logger.info(f"ℹ️ Skipping {kind} pick {asset!r} — outside session window")
            self.last_summary["last_skip_reason"] = f"{kind}_outside_window"
            return None
        try:
            from state import get_user_state
            symbol_prefix = self._resolve_symbol(asset)
            if not symbol_prefix:
                self.last_summary["last_skip_reason"] = f"{kind}_unresolved:{asset}"
                return None
            val_client = self._get_validation_client()
            if val_client is None:
                msg = f"no_authenticated_fyers_client_for_{kind}"
                logger.warning(
                    f"⏭️ Skipped {kind} injection ({asset}): Fyers not connected — "
                    f"reconnect then agent will retry"
                )
                self.last_summary["last_skip_reason"] = msg
                return None
            if symbol_prefix.startswith("MCX:") or symbol_prefix.startswith("CDS:"):
                from engine.strikes import resolve_current_commodity_expiry
                exact_symbol = resolve_current_commodity_expiry(symbol_prefix, client=val_client)
            else:
                exact_symbol = symbol_prefix
            if not exact_symbol:
                self.last_summary["last_skip_reason"] = f"{kind}_empty_resolve:{asset}"
                return None

            if not self._is_quotable(val_client, exact_symbol):
                logger.warning(
                    f"⏭️ Skipped unquotable {kind} injection: {exact_symbol} "
                    f"(from '{asset}') — not added to watch"
                )
                self.last_summary["last_skip_reason"] = f"{kind}_unquotable:{exact_symbol}"
                return None

            logger.info(
                f"🔥 AI {kind} pick: {asset} → injecting VALID {exact_symbol} "
                f"— auto-trade ENABLED!"
            )
            for u_id in self._active_user_ids_for_inject():
                state = get_user_state(u_id)
                if exact_symbol not in state.active_symbols or \
                   exact_symbol not in getattr(state, "enabled_symbols", []):
                    state.add_symbol(exact_symbol, enable=True, by_agent=True)
            injected = list(self.last_summary.get("last_injected") or [])
            if exact_symbol not in injected:
                injected.append(exact_symbol)
            self.last_summary["last_injected"] = injected[-10:]
            self.last_summary["last_skip_reason"] = ""
            return exact_symbol
        except Exception as e:
            logger.error(f"{kind} injection error for '{asset}': {e}")
            self.last_summary["last_skip_reason"] = f"{kind}_error:{e}"
            return None

    async def update_summary(self):
        """Fetch news, update macro summary, inject AI scrips (locked — safe after reconnect)."""
        async with self._refresh_lock:
            await self._update_summary_unlocked()

    async def _update_summary_unlocked(self):
        try:
            logger.info("📰 Fetching global market news...")
            headlines = await self.fetch_rss_headlines()
            if not headlines:
                logger.warning("No headlines fetched.")
                self.last_summary["last_skip_reason"] = "no_headlines"
                return

            top_headlines = headlines[:30]
            result = await self.ai.get_global_macro_summary(top_headlines)
            eq_pick = str(result.get("high_conviction_asset", "NONE") or "NONE").upper()
            mcx_pick = str(result.get("commodity_pick", "NONE") or "NONE").upper()
            self.last_summary = {
                "equities_trend": result.get("equities_trend", "NEUTRAL"),
                "commodities_trend": result.get("commodities_trend", "NEUTRAL"),
                "currency_trend": result.get("currency_trend", "NEUTRAL"),
                "summary": result.get("summary", "No clear sentiment."),
                "high_conviction_asset": eq_pick,
                "commodity_pick": mcx_pick,
                "last_injected": list(self.last_summary.get("last_injected") or []),
                "last_skip_reason": "",
                "ts": time.time(),
            }
            import state as _state_mod
            _state_mod.global_macro_summary = self.last_summary
            logger.info(
                f"📰 AI Global Macro Summary Updated: EQ={self.last_summary['equities_trend']}, "
                f"COM={self.last_summary['commodities_trend']}, "
                f"FX={self.last_summary['currency_trend']}, picks={eq_pick}/{mcx_pick}"
            )

            import datetime as _dt
            import pytz as _pytz
            _now_ist = _dt.datetime.now(_pytz.timezone("Asia/Kolkata"))
            _equity_ok = _now_ist.hour < 15
            _commodity_ok = 9 <= _now_ist.hour < 22

            try:
                from engine.notifier import send_webhook_alert
                from state import get_user_state
                import os
                st = get_user_state(1)
                wh_url = (
                    os.getenv("TELEGRAM_WEBHOOK", "")
                    or os.getenv("WEBHOOK_URL", "")
                    or getattr(st, "webhook_url", "")
                )
                if wh_url:
                    today_str = _now_ist.strftime("%Y-%m-%d")
                    current_hour = _now_ist.hour
                    current_minute = _now_ist.minute

                    is_pre_market = (8 <= current_hour < 9 and current_minute >= 40)
                    is_market_hours = (9 <= current_hour <= 22)

                    last_hourly = getattr(self, "_last_hourly_hour", -1)
                    last_pre_date = getattr(self, "_last_pre_market_date", "")
                    last_init_date = getattr(self, "_last_init_date", "")

                    should_send = False
                    title_prefix = "🌐 Global Market Briefing"

                    if is_pre_market and last_pre_date != today_str:
                        should_send = True
                        self._last_pre_market_date = today_str
                        title_prefix = "🌅 Pre-Market Global Briefing"
                    elif is_market_hours and (last_hourly != current_hour or last_init_date != today_str):
                        should_send = True
                        self._last_hourly_hour = current_hour
                        self._last_init_date = today_str
                        title_prefix = f"📊 Market Briefing ({_now_ist.strftime('%H:%M IST')})"

                    if should_send:
                        bullets = result.get("telegram_bullets") or []
                        brief_ok = bool(bullets) and "Failed to parse" not in str(result.get("summary", ""))
                        if not brief_ok:
                            try:
                                from engine.cursor_agent_bridge import escalate_to_cursor_agent
                                escalate_to_cursor_agent(
                                    issue_type="news_brief_parse_quality",
                                    summary="Global news researcher produced empty/failed telegram_bullets for market briefing.",
                                    evidence=json.dumps(
                                        {
                                            "summary": result.get("summary"),
                                            "equities_trend": result.get("equities_trend"),
                                            "headlines_sample": top_headlines[:8],
                                        },
                                        indent=2,
                                    )[:4000],
                                    suggested_files=[
                                        "trading-app/workers/news_worker.py",
                                        "trading-app/engine/ai_engine.py",
                                    ],
                                    issue_key=f"newsbrief:{today_str}:{current_hour}",
                                )
                            except Exception as _esc:
                                logger.warning(f"Cursor escalate (news brief) failed: {_esc}")
                        if not bullets:
                            bullets = [
                                f"• 📌 Global Summary: {result.get('summary', 'No summary')}",
                                f"• 🎯 Indian Equities: {result.get('equities_trend', 'NEUTRAL')}",
                                f"• 🛢️ Commodities: {result.get('commodities_trend', 'NEUTRAL')}",
                                f"• ⚡ FX bias: {result.get('currency_trend', 'NEUTRAL')}",
                            ]
                        bullet_text = "\n".join(bullets)
                        msg = (
                            f"<b>{title_prefix}</b>\n\n"
                            f"{bullet_text}\n\n"
                            f"<b>Biases:</b> EQ: <code>{self.last_summary['equities_trend']}</code> | "
                            f"MCX: <code>{self.last_summary['commodities_trend']}</code> | "
                            f"FX: <code>{self.last_summary['currency_trend']}</code>\n"
                            f"<b>Agent picks:</b> EQ <code>{eq_pick}</code> | MCX <code>{mcx_pick}</code>"
                        )
                        await send_webhook_alert(wh_url, msg, title=title_prefix)
                        logger.info(f"📲 Sent Telegram Global Intelligence Update ({title_prefix})")
            except Exception as tg_err:
                logger.warning(f"Telegram news dispatch warning: {tg_err}")

            self._inject_asset(eq_pick, _equity_ok, "equity")
            self._inject_asset(mcx_pick, _commodity_ok, "commodity")

        except Exception as e:
            logger.error(f"Error updating global news summary: {e}")

    def schedule_refresh_after_auth(self, reason: str = "fyers_reconnect"):
        """Fire-and-forget news+inject cycle after Fyers reconnect (no wait for 30m timer)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(f"Cannot schedule news refresh ({reason}): no running loop")
            return

        async def _run():
            try:
                logger.info(f"🔁 Immediate news/scrip refresh after {reason}")
                await asyncio.sleep(2)  # let token/context settle
                await self.update_summary()
            except Exception as e:
                logger.error(f"Post-auth news refresh failed: {e}")

        loop.create_task(_run())

    async def run(self):
        logger.info("🚀 Global News Worker started.")
        while True:
            await self.update_summary()
            await asyncio.sleep(self.interval_seconds)


news_worker = NewsWorker()
