"""
Fyers WebSocket Real-Time Data Feed
====================================
Replaces REST polling (get_quote/get_quotes) with a persistent WebSocket connection.
Fyers pushes tick data in real-time — no rate limits, no 429 errors.

Usage:
    from engine.ws_feed import ws_feed
    
    # Start the feed (call once at app startup)
    await ws_feed.start(client)
    
    # Subscribe to symbols
    ws_feed.subscribe(["NSE:NIFTY50-INDEX", "NSE:INDIAVIX-INDEX"])
    
    # Get latest tick data (instant, from memory cache)
    ltp = ws_feed.get_ltp("NSE:NIFTY50-INDEX")  # Returns float
    tick = ws_feed.get_tick("NSE:NIFTY50-INDEX")  # Returns full tick dict
"""

import asyncio
import time
import threading
import logging
from typing import Dict, Optional, List, Set
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger("DASHBOARD")


class FyersWSFeed:
    """Manages a persistent Fyers WebSocket connection for real-time market data."""
    
    def __init__(self):
        self._ticks: Dict[str, Dict] = {}  # symbol -> latest tick data
        self._subscribed: Set[str] = set()
        self._socket = None
        self._connected = False
        self._reconnect_count = 0
        self._max_reconnects = 10
        self._last_tick_time: float = 0
        self._client = None  # Broker reference
        self._started = False
        self._lock = threading.Lock()
        self._ws_thread = None
        self._redundancy_thread = None
        self._redundancy_running = False
        self._queues = []  # List of (asyncio.Queue, asyncio.AbstractEventLoop)
    
    # ==================== PUBLIC API ====================
    
    def register_queue(self, q: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        """Register an asyncio Queue to receive instant tick updates."""
        self._queues.append((q, loop))
    
    def get_ltp(self, symbol: str) -> float:
        """Get Last Traded Price for a symbol. Returns 0 if not available."""
        tick = self._ticks.get(symbol)
        if tick:
            return tick.get("ltp", 0)
        return 0
    
    def get_tick(self, symbol: str) -> Optional[Dict]:
        """Get full tick data for a symbol.
        Returns dict with: ltp, ch, chp, high_price, low_price, open_price, prev_close_price, vol, bid, ask
        """
        return self._ticks.get(symbol)
    
    def get_quote_from_ws(self, symbol: str) -> Optional[Dict]:
        """Get quote-compatible dict from WebSocket cache.
        Returns data in same format as REST get_quote() for backward compatibility.
        """
        tick = self._ticks.get(symbol)
        if not tick or tick.get("ltp", 0) <= 0:
            return None
        
        return {
            "lp": tick.get("ltp", 0),
            "ch": tick.get("ch", 0),
            "chp": tick.get("chp", 0),
            "high_price": tick.get("high_price", 0),
            "low_price": tick.get("low_price", 0),
            "open_price": tick.get("open_price", 0),
            "prev_close_price": tick.get("prev_close_price", 0),
            "bid": tick.get("bid", 0),
            "ask": tick.get("ask", 0),
            "volume": tick.get("vol_traded_today", 0),
            "last_update": tick.get("_update_time", 0)
        }
    
    def get_quotes_from_ws(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get quotes for multiple symbols from WebSocket cache."""
        result = {}
        for sym in symbols:
            q = self.get_quote_from_ws(sym)
            if q:
                result[sym] = q
        return result
    
    def inject_quote(self, symbol: str, quote_data: Dict):
        """Inject REST API quote data into WS cache to populate missing fields like prev_close_price."""
        with self._lock:
            current = self._ticks.get(symbol, {})
            current["ltp"] = quote_data.get("lp", current.get("ltp", 0))
            current["ch"] = quote_data.get("ch", current.get("ch", 0))
            current["chp"] = quote_data.get("chp", current.get("chp", 0))
            current["open_price"] = quote_data.get("open_price", current.get("open_price", 0))
            current["high_price"] = quote_data.get("high_price", current.get("high_price", 0))
            current["low_price"] = quote_data.get("low_price", current.get("low_price", 0))
            
            # The Fyers Quotes API sometimes omits prev_close_price for indices.
            # We must reconstruct it mathematically so the UI shows the correct daily change.
            prev_close = quote_data.get("prev_close_price", 0)
            if prev_close == 0 and quote_data.get("lp", 0) > 0 and quote_data.get("ch") is not None:
                prev_close = quote_data["lp"] - quote_data["ch"]
                
            current["prev_close_price"] = round(prev_close, 2) if prev_close > 0 else current.get("prev_close_price", 0)
            current["bid"] = quote_data.get("bid", current.get("bid", 0))
            current["ask"] = quote_data.get("ask", current.get("ask", 0))
            current["vol_traded_today"] = quote_data.get("volume", current.get("vol_traded_today", 0))
            current["_update_time"] = time.time()
            self._ticks[symbol] = current

    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected and receiving data."""
        if not self._connected:
            return False
            
        if self._last_tick_time > 0:
            elapsed = time.time() - self._last_tick_time
            
            # Fast-fail if completely dead for 5 mins (even off-market)
            if elapsed > 300:
                return False
                
            # If during market hours, be strict (20 seconds)
            if elapsed > 20:
                now = datetime.now(IST).time()
                # 09:15 to 15:30 IST
                if (9, 15) <= (now.hour, now.minute) <= (15, 30):
                    return False
                    
        return self._connected
    def get_stats(self) -> Dict:
        """Get WebSocket feed stats."""
        return {
            "connected": self._connected,
            "symbols_subscribed": len(self._subscribed),
            "symbols_with_data": len(self._ticks),
            "reconnect_count": self._reconnect_count,
            "last_tick_age_seconds": round(time.time() - self._last_tick_time, 1) if self._last_tick_time else -1
        }
    
    # ==================== SUBSCRIPTION ====================
    
    def subscribe(self, symbols: List[str]):
        """Subscribe to symbols for real-time data."""
        # NOTE: NIFTY50-INDEX and INDIAVIX-INDEX used to be excluded here and fetched via REST
        # instead. That made the auto-trade symbol (NIFTY50) depend entirely on the Fyers REST
        # quote API — which, under rate-limit cooldown (429), returns no spot. No spot -> the
        # expiry fallback is skipped -> "No expiry found" -> every auto-trade is skipped. Feeding
        # them over the WebSocket (like NIFTYBANK already is) gives NIFTY50 a live spot that does
        # not depend on the REST rate limit. The tick-contamination guard in _on_message protects
        # against any cross-symbol price bleed.
        ignored = set()
        new_symbols = [s for s in symbols if s not in self._subscribed and s not in ignored]
        if not new_symbols:
            return
        
        self._subscribed.update(new_symbols)
        
        if self._socket and self._connected:
            try:
                self._socket.subscribe(symbols=new_symbols, data_type="SymbolUpdate")
                logger.info(f"📡 WS subscribed: {new_symbols}")
            except Exception as e:
                logger.error(f"WS subscribe error: {e}")
    
    def unsubscribe(self, symbols: List[str]):
        """Unsubscribe from symbols."""
        to_remove = [s for s in symbols if s in self._subscribed]
        if not to_remove:
            return
        
        for s in to_remove:
            self._subscribed.discard(s)
        
        if self._socket and self._connected:
            try:
                self._socket.unsubscribe(symbols=to_remove)
                logger.info(f"📡 WS unsubscribed: {to_remove}")
            except Exception as e:
                logger.error(f"WS unsubscribe error: {e}")
    
    # ==================== LIFECYCLE ====================
    
    async def start(self, client):
        """Start the WebSocket data feed. Call once at app startup."""
        if self._started:
            logger.info("WS Feed already started, skipping duplicate start")
            return
        
        self._client = client
        self._started = True
        self._reconnect_count = 0
        
        # Start WebSocket in a background thread (it runs its own event loop)
        self._ws_thread = threading.Thread(target=self._connect, daemon=True)
        self._ws_thread.start()
        
        # Start Redundancy Monitor Thread
        self._redundancy_running = True
        self._redundancy_thread = threading.Thread(target=self._redundancy_monitor, daemon=True)
        self._redundancy_thread.start()
        
        # Wait a moment for connection
        await asyncio.sleep(2)
        
        if self._connected:
            logger.info(f"✅ Fyers WebSocket connected. Subscribing to {len(self._subscribed)} symbols.")
        else:
            logger.warning("⚠️ WebSocket not connected yet. Will retry automatically.")

    def stop(self):
        """Stop the WebSocket data feed and close connection."""
        logger.info("Stopping Fyers WebSocket Data Feed...")
        self._started = False
        self._connected = False
        self._redundancy_running = False
        if self._socket:
            try:
                self._socket.close_connection()
            except Exception as e:
                logger.error(f"Error closing WS connection: {e}")
            self._socket = None

    def restart(self, client=None):
        """Restart the WebSocket data feed with a new client/token."""
        logger.info("🔄 Request to restart Fyers WebSocket received.")
        if client:
            self._client = client
        self.stop()
        
        # Clear ticks cache so stale price data from yesterday doesn't persist
        with self._lock:
            self._ticks.clear()
            logger.info("🧹 Cleared WebSocket tick cache.")
        
        # Give the old thread a tiny moment to unblock and exit
        time.sleep(0.5)
        
        self._started = True
        self._reconnect_count = 0
        self._ws_thread = threading.Thread(target=self._connect, daemon=True)
        self._ws_thread.start()
        logger.info("✅ Fyers WebSocket Data Feed restart thread spawned.")
    
    def _connect(self):
        """Connect to Fyers WebSocket (runs in background thread)."""
        if not self._started:
            return
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
            
            token = self._client.get_access_token_for_ws()
            if not token:
                logger.error("❌ Cannot start WS Feed: Missing access token")
                self._started = False
                return
            
            self._socket = data_ws.FyersDataSocket(
                access_token=token,
                log_path="",
                litemode=True,  # Lite mode (LTP only) to prevent drops on indices
                write_to_file=False,
                reconnect=True,  # Auto-reconnect
                reconnect_retry=self._max_reconnects,
                on_connect=self._on_connect,
                on_close=self._on_close,
                on_error=self._on_error,
                on_message=self._on_message
            )
            
            self._socket.connect()
            # keep_running blocks the thread
            self._socket.keep_running()
            
        except Exception as e:
            logger.error(f"❌ WS Feed connect error: {e}")
            self._connected = False
            # Schedule reconnect ONLY if we are still supposed to be running
            if self._started:
                self._schedule_reconnect()
    
    def _schedule_reconnect(self):
        """Schedule a reconnection attempt."""
        if not self._started:
            return
        if self._reconnect_count >= self._max_reconnects:
            logger.error("❌ Max WebSocket reconnection attempts reached. Giving up.")
            return
        
        self._reconnect_count += 1
        delay = min(5 * (2 ** (self._reconnect_count - 1)), 60)  # 5, 10, 20, 40, 60
        logger.info(f"🔄 WS reconnecting in {delay}s (attempt {self._reconnect_count}/{self._max_reconnects})")
        
        # Sleep in small chunks to detect if stop() was called in the meantime
        for _ in range(int(delay)):
            if not self._started:
                return
            time.sleep(1)
            
        if self._started:
            self._connect()
    
    # ==================== CALLBACKS ====================
    
    def _on_connect(self):
        """Called when WebSocket connects successfully."""
        self._connected = True
        self._reconnect_count = 0
        logger.info("✅ Fyers WebSocket CONNECTED")
        
        # Subscribe to all tracked symbols
        if self._subscribed:
            symbols_list = list(self._subscribed)
            try:
                self._socket.subscribe(symbols=symbols_list, data_type="SymbolUpdate")
                logger.info(f"📡 WS auto-subscribed to {len(symbols_list)} symbols: {symbols_list[:5]}...")
            except Exception as e:
                logger.error(f"WS auto-subscribe error: {e}")
    
    def _on_message(self, message):
        """Called for every tick update. This is the HOT PATH — keep it fast."""
        try:
            # DEBUG LOG
            if getattr(self, '_msg_count', 0) < 5:
                print(f"📡 WS MESSAGE RECEIVED: {message}", flush=True)
                self._msg_count = getattr(self, '_msg_count', 0) + 1

            if not isinstance(message, dict):
                return
            
            symbol = message.get("symbol", "")
            if not symbol:
                return
            
            # Extract tick data
            with self._lock:
                current = self._ticks.get(symbol, {})
                
                ltp = message.get("ltp")
                if not ltp:
                    ltp = current.get("ltp", 0)

                # Data-sanity guard for the live tick cross-contamination bug where a tick's price
                # lands on the wrong symbol's key — e.g. BANKNIFTY's ~58000 showing up on RELIANCE
                # trading ~1300. Reject an ltp grossly outside this symbol's expected band. The band
                # prefers the established day range, but falls back to the last good ltp / prev-close
                # so the guard is ALSO active from the 2nd tick of a fresh subscription (the exact
                # window — right after enabling a symbol — where contamination slipped through before
                # a day range had formed). The 3x / 0.33x bounds are far beyond any real intraday or
                # circuit move, so legitimate moves always pass.
                _hi = current.get("high_price", 0)
                _lo = current.get("low_price", 0)
                if _hi > 0 and _lo > 0:
                    _ref_hi, _ref_lo = _hi, _lo
                else:
                    _anchor = current.get("ltp", 0) or message.get("prev_close_price", 0)
                    _ref_hi = _ref_lo = _anchor
                if ltp and _ref_hi > 0 and _ref_lo > 0 and (ltp > _ref_hi * 3 or ltp < _ref_lo / 3):
                    print(f"⚠️ TICK-CONTAMINATION guard: rejected ltp={ltp} for {symbol} "
                          f"(expected band {_ref_lo}-{_ref_hi}); keeping last good ltp.", flush=True)
                    ltp = current.get("ltp", 0)

                prev_close = message.get("prev_close_price", current.get("prev_close_price", 0))
                
                # In LiteMode, we only get ltp. Recalculate ch and chp if we have prev_close.
                ch = message.get("ch", current.get("ch", 0))
                chp = message.get("chp", current.get("chp", 0))
                if prev_close > 0 and "ch" not in message:
                    ch = round(ltp - prev_close, 2)
                    chp = round((ch / prev_close) * 100, 2)

                self._ticks[symbol] = {
                    "ltp": ltp,
                    "ch": ch,
                    "chp": chp,
                    "open_price": message.get("open_price", current.get("open_price", 0)),
                    "high_price": message.get("high_price", current.get("high_price", 0)),
                    "low_price": message.get("low_price", current.get("low_price", 0)),
                    "prev_close_price": prev_close,
                    "vol_traded_today": message.get("vol_traded_today", current.get("vol_traded_today", 0)),
                    "bid": message.get("bid", current.get("bid", 0)),
                    "ask": message.get("ask", current.get("ask", 0)),
                    "last_traded_qty": message.get("last_traded_qty", current.get("last_traded_qty", 0)),
                    "last_traded_time": message.get("last_traded_time", current.get("last_traded_time", 0)),
                    "_update_time": time.time(),
                    "_symbol": symbol
                }
                tick_copy = self._ticks[symbol].copy()
            
            # Dispatch to queues instantly
            for q, loop in self._queues:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(q.put_nowait, (symbol, tick_copy))
            
            self._last_tick_time = time.time()
            
            # Feed tick into CandleBuilder for multi-TF candle construction
            try:
                from engine.candle_builder import candle_builder
                tick_ts = message.get("last_traded_time", 0) or time.time()
                tick_vol = message.get("last_traded_qty", 0)
                candle_builder.on_tick(symbol, ltp, tick_ts, tick_vol)
            except Exception:
                pass  # Don't let candle builder errors break the hot path
            
        except Exception as e:
            # Don't log every error on hot path — too noisy
            pass
    
    def _on_error(self, message):
        """Called on WebSocket error."""
        logger.error(f"❌ WS Feed Error: {message}")
    
    def _on_close(self, message):
        """Called when WebSocket closes."""
        self._connected = False
        logger.warning(f"⚠️ WS Feed Closed: {message}")
        
        # Send Telegram alert if we lose WS during market hours
        from datetime import datetime
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        now = datetime.now(IST).time()
        # 09:15 to 15:30 IST
        if (9, 15) <= (now.hour, now.minute) <= (15, 30):
            try:
                from engine.notifier import trigger_webhook_background
                from models import Database
                if hasattr(self, '_client') and self._client and self._client.user_id:
                    user = Database.get_user_by_id_sync(self._client.user_id)
                    if user and user.get("webhook_url"):
                        last_ws_alert = getattr(self, "_last_ws_alert", None)
                        if last_ws_alert is None or (datetime.now() - last_ws_alert).total_seconds() > 900:
                            self._last_ws_alert = datetime.now()
                            login_url = self._client.get_login_url() if hasattr(self._client, 'get_login_url') else ""
                            msg = f"⚠️ <b>Fyers Data Feed Disconnected</b>\n\nWebSocket connection lost during market hours. Attempting auto-reconnect..."
                            if login_url:
                                msg += f"\n\nIf manual login is required, click here:\n{login_url}\n\nOnce logged in, paste the 'auth_code=' part here."
                            trigger_webhook_background(user["webhook_url"], msg, title="Data Feed Alert")
            except Exception as e:
                logger.error(f"Failed to send WS disconnect alert: {e}")
                
        # Auto-reconnect is handled by fyers_apiv3 if reconnect=True

    def _redundancy_monitor(self):
        """Background thread that monitors for WebSocket freezes and injects Yahoo Finance data."""
        import yfinance as yf
        
        # Map Fyers index symbols to Yahoo Finance symbols
        yf_mapping = {
            "NSE:NIFTY50-INDEX": "^NSEI",
            "NSE:NIFTYBANK-INDEX": "^NSEBANK",
            "NSE:INDIAVIX-INDEX": "^INDIAVIX",
            "NSE:FINNIFTY-INDEX": "NIFTY_FIN_SERVICE.NS"
        }
        
        while self._redundancy_running:
            time.sleep(3)
            
            if not self._started or not self._subscribed:
                continue
                
            # Only apply fail-over during active market hours
            now = datetime.now(IST).time()
            if not ((9, 15) <= (now.hour, now.minute) <= (15, 30)):
                continue
                
            # Check if Fyers went silent
            silence_duration = time.time() - self._last_tick_time
            if silence_duration > 5:
                # Iterate over subscribed symbols that we can fallback for
                for fyers_sym in self._subscribed:
                    yf_sym = yf_mapping.get(fyers_sym)
                    if not yf_sym:
                        continue # Skip options or unknown stocks
                        
                    try:
                        ticker = yf.Ticker(yf_sym)
                        # Fetch the most recent 1m candle (fastest way to get real-time price on yf)
                        df = ticker.history(period="1d", interval="1m")
                        if df.empty:
                            continue
                            
                        last_row = df.iloc[-1]
                        ltp = round(float(last_row['Close']), 2)
                        
                        if ltp > 0:
                            # Inject into WS cache manually
                            with self._lock:
                                current = self._ticks.get(fyers_sym, {})
                                current["ltp"] = ltp
                                current["_update_time"] = time.time()
                                current["_symbol"] = fyers_sym
                                current["_is_fallback"] = True
                                self._ticks[fyers_sym] = current
                                tick_copy = current.copy()
                                
                            # Dispatch to queues instantly so UI and engines see it
                            for q, loop in self._queues:
                                if not loop.is_closed():
                                    loop.call_soon_threadsafe(q.put_nowait, (fyers_sym, tick_copy))
                                    
                            # Push to candle builder
                            try:
                                from engine.candle_builder import candle_builder
                                candle_builder.on_tick(fyers_sym, ltp, time.time(), 0)
                            except Exception:
                                pass
                                
                            print(f"🔄 [FAIL-OVER] Injected live Yahoo Finance price for {fyers_sym}: {ltp}")
                            
                    except Exception as e:
                        print(f"⚠️ [FAIL-OVER] Failed to fetch {yf_sym} from yfinance: {e}")


# ==================== SINGLETON ====================
ws_feed = FyersWSFeed()
