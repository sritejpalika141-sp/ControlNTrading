"""
Fyers ORDER WebSocket — real-time order / trade / position updates.

Why: positions, orders and P&L used to be REST-POLLED by market_worker every few seconds (and were
subject to the REST cooldown). This feed subscribes to the Fyers Order socket so a fill/exit/order
change updates the dashboard INSTANTLY instead of on the next poll.

Design (robust, not payload-fragile): every order/trade/position event is treated as a TRIGGER to
do ONE authoritative REST refresh of positions + funds into USER_CACHES (throttled). We do not try
to reconstruct broker state from partial socket payloads — the WS tells us "something changed", and
we then read the broker's own truth. The existing /ws/live push loop ships the refreshed cache to
the browser, so the UI reflects the fill within ~1s of it happening.

Mirrors engine/ws_feed.py's lifecycle: background daemon thread, token from
FyersClient.get_access_token_for_ws(), guarded restart(), auto-reconnect.
"""
import logging
import threading
import time

logger = logging.getLogger("ORDER_WS")


class FyersOrderFeed:
    def __init__(self):
        self._client = None
        self._user_id = 1
        self._socket = None
        self._thread = None
        self._started = False
        self._connected = False
        self._reconnecting = False
        self._last_refresh = 0.0
        self._refresh_min_interval = 1.0  # throttle: at most 1 broker refresh/sec on event bursts

    # ── lifecycle ────────────────────────────────────────────────────────────────────────────
    async def start(self, client):
        if self._started:
            logger.info("Order WS already started, skipping duplicate start")
            return
        self._client = client
        self._user_id = getattr(client, "user_id", 1) or 1
        self._started = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        logger.info("🟢 Fyers Order WebSocket feed starting…")

    def stop(self):
        self._started = False
        self._connected = False
        if self._socket:
            try:
                self._socket.close_connection()
            except Exception as e:
                # The SDK sometimes raises internally when closing a not-fully-established socket
                # (e.g. join on a None thread). Harmless — the daemon thread dies regardless.
                logger.debug(f"Order WS close quirk (ignored): {e}")
            self._socket = None

    def restart(self, client=None):
        """Guarded restart (mirrors ws_feed.restart) — a new token after re-login, or a health check."""
        if self._reconnecting:
            logger.info("🔄 Order WS restart already in progress — ignoring duplicate.")
            return
        self._reconnecting = True
        try:
            if client:
                self._client = client
                self._user_id = getattr(client, "user_id", 1) or 1
            old = self._thread
            self.stop()
            if old and old.is_alive() and old is not threading.current_thread():
                old.join(timeout=4)
            self._started = True
            self._thread = threading.Thread(target=self._connect, daemon=True)
            self._thread.start()
            logger.info("✅ Order WS restart thread spawned.")
        finally:
            def _release():
                time.sleep(3)
                self._reconnecting = False
            threading.Thread(target=_release, daemon=True).start()

    def is_connected(self) -> bool:
        return self._connected

    # ── connection (background thread) ───────────────────────────────────────────────────────
    def _connect(self):
        if not self._started:
            return
        try:
            from fyers_apiv3.FyersWebsocket import order_ws

            token = self._client.get_access_token_for_ws()
            if not token:
                logger.error("❌ Cannot start Order WS: missing access token")
                self._started = False
                return

            sock = order_ws.FyersOrderSocket(
                access_token=token,
                write_to_file=False,
                log_path="",
                on_connect=self._on_connect,
                on_close=self._on_close,
                on_error=self._on_error,
                on_orders=self._on_orders,
                on_trades=self._on_trades,
                on_positions=self._on_positions,
                on_general=self._on_general,
                reconnect=True,
            )
            # Assign BEFORE connect(): the SDK fires on_connect() synchronously inside connect(),
            # and on_connect() calls self._socket.subscribe(...). If we assign after connect(),
            # self._socket is still None on the first connect and the subscribe raises
            # "'NoneType' has no attribute 'subscribe'" (forcing an extra reconnect).
            self._socket = sock
            sock.connect()
            if self._socket is sock:
                sock.keep_running()
        except Exception as e:
            logger.error(f"Order WS connect error: {e}")
            self._connected = False

    # ── callbacks ────────────────────────────────────────────────────────────────────────────
    def _on_connect(self, *args):
        self._connected = True
        logger.info("✅ Fyers Order WebSocket CONNECTED")
        # Subscribe to order, trade and position streams. Retry briefly: on_connect can fire a hair
        # before self._socket is fully assigned in rare timing, so don't give up on the first miss.
        for _attempt in range(5):
            sock = self._socket
            if sock is not None:
                try:
                    sock.subscribe(data_type="OnOrders,OnTrades,OnPositions")
                    logger.info("📡 Order WS subscribed: OnOrders, OnTrades, OnPositions")
                    break
                except Exception as e:
                    logger.warning(f"Order WS subscribe attempt {_attempt+1} failed: {e}")
            time.sleep(0.3)
        # Prime the cache once on connect so the dashboard is fresh immediately.
        self._refresh_from_broker(reason="connect")

    def _on_close(self, *args):
        self._connected = False
        logger.warning("⚠️ Fyers Order WebSocket closed.")

    def _on_error(self, *args):
        logger.error(f"Order WS error: {args}")

    def _on_orders(self, msg=None):
        logger.info(f"📥 Order update: {str(msg)[:160]}")
        self._refresh_from_broker(reason="order")

    def _on_trades(self, msg=None):
        # A trade = a FILL. This is the moment positions AND funds change.
        logger.info(f"✅ Trade fill: {str(msg)[:160]}")
        self._refresh_from_broker(reason="trade", include_funds=True, force=True)

    def _on_positions(self, msg=None):
        logger.info(f"📊 Position update: {str(msg)[:160]}")
        self._refresh_from_broker(reason="position")

    def _on_general(self, msg=None):
        logger.debug(f"Order WS general: {str(msg)[:120]}")

    # ── authoritative refresh (the WS event is only a trigger) ──────────────────────────────────
    def _refresh_from_broker(self, reason="event", include_funds=False, force=False):
        """Read the broker's own positions (+ funds on fills) into USER_CACHES. Throttled so an
        event burst can't hammer the REST API; a real fill (force=True) bypasses the throttle."""
        now = time.time()
        if not force and (now - self._last_refresh) < self._refresh_min_interval:
            return
        self._last_refresh = now
        try:
            from state import get_user_cache, get_user_state
            cache = get_user_cache(str(self._user_id))
            client = self._client
            try:
                pos = client.get_positions() or []
                open_pos = [p for p in pos if p.get("qty", p.get("netQty", 0))]
                cache["active_positions"] = pos
                cache["total_pnl"] = sum(p.get("pl", 0) for p in pos)
                try:
                    get_user_state(self._user_id).update_pnl(cache["total_pnl"])
                except Exception:
                    pass
                logger.info(f"🔄 Order-WS refresh ({reason}): {len(open_pos)} open pos, pnl ₹{cache['total_pnl']:.0f}")
            except Exception as e:
                logger.warning(f"Order-WS position refresh failed: {e}")
            if include_funds:
                try:
                    f = client.get_funds()
                    if f and f.get("equityAmount") is not None:
                        cache["funds"] = f
                except Exception as e:
                    logger.warning(f"Order-WS funds refresh failed: {e}")
            cache["last_update"] = now
        except Exception as e:
            logger.error(f"Order-WS refresh error: {e}")


# Singleton
order_feed = FyersOrderFeed()
