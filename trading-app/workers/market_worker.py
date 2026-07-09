"""
Multi-user market data worker.

Background task that polls Fyers (and falls back to NSE public quotes / candles)
to keep each user's cache populated with spot, VIX, positions, orders, funds.
Uses smart phase-based polling to avoid rate-limit churn outside market hours.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from state import (
    IST,
    USER_CACHES,
    USER_CONTEXTS,
    broadcast_log,
    get_user_cache,
    get_user_state,
    logger,
    _token_ready,
)
from fyers_client import FyersClient
from engine.ws_feed import ws_feed


def get_market_phase(active_symbols: list = None) -> str:
    """Determine current market phase for smart polling.
    Returns: 'pre_open', 'market', 'post_close', 'closed'
    """
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Weekend
        return "closed"
    hour, minute = now.hour, now.minute
    time_val = hour * 60 + minute  # Minutes since midnight

    has_mcx = any(s.startswith("MCX:") for s in (active_symbols or []))
    has_cds = any(s.startswith("CDS:") for s in (active_symbols or []))

    if time_val < 540:        # Before 9:00 AM
        return "closed"
    elif time_val < 555:      # 9:00 - 9:15 AM (Pre-open)
        return "pre_open"
    elif time_val < 930:      # 9:15 AM - 3:30 PM (Market hours)
        return "market"
    elif time_val < 1020 and has_cds: # Until 5:00 PM for CDS
        return "market"
    elif time_val < 1410 and has_mcx: # Until 11:30 PM for MCX
        return "market"
    elif time_val < 945:      # 3:30 - 3:45 PM (Post-close / closing auction)
        return "post_close"
    else:                     # After 3:45 PM (or 11:30 PM for MCX)
        return "closed"


# Underscore alias kept for callers that referenced the old name.
_get_market_phase = get_market_phase


# Polling intervals per phase (in loop iterations, each ~1s base)
POLL_CONFIG = {
    "market":     {"quotes_every": 1,  "sync_every": 12, "sleep": 0.5},  # Every 0.5s quotes, 6s sync
    "pre_open":   {"quotes_every": 10, "sync_every": 30, "sleep": 2},    # Every 20s quotes, 60s sync
    "post_close": {"quotes_every": 15, "sync_every": 30, "sleep": 3},    # Every 45s quotes, 90s sync
    "closed":     {"quotes_every": 0,  "sync_every": 30, "sleep": 10},   # No quotes, 300s sync
}


async def market_data_worker():
    """Background task to fetch all market data and update the shared cache.
    Uses smart adaptive polling based on market phase to prevent API rate limiting."""
    # Lazy import to avoid circular dependency at module load time.
    from app import get_nse_public_quotes
    from state import get_user_state

    # === INSTANT TICK PROCESSOR ===
    async def tick_processor(q):
        while True:
            try:
                symbol, tick_data = await q.get()
                for u_id_key, cache in USER_CACHES.items():
                    if not cache.get("is_auth"): continue
                    try: u_id = int(u_id_key)
                    except: continue
                    
                    state = get_user_state(u_id)
                    if symbol in state.active_symbols or symbol in ["NSE:INDIAVIX-INDEX", "NSE:NIFTY50-INDEX"]:
                        if "quotes" not in cache: cache["quotes"] = {}
                        cache["quotes"][symbol] = tick_data
                        
                        if "all_spots" not in cache: cache["all_spots"] = {}
                        cache["all_spots"][symbol] = {
                            "lp": tick_data.get("ltp", 0),
                            "ch": tick_data.get("ch", 0),
                            "chp": tick_data.get("chp", 0)
                        }
                        
                        if symbol == "NSE:NIFTY50-INDEX":
                            cache["spot"] = {
                                "lp": tick_data.get("ltp", 0),
                                "ch": tick_data.get("ch", 0),
                                "chp": tick_data.get("chp", 0)
                            }
                            # backward compatibility
                            cache["spot_price"] = tick_data.get("ltp", 0)
                            cache["spot_ch"] = tick_data.get("ch", 0)
                            cache["spot_chp"] = tick_data.get("chp", 0)
                        elif symbol == "NSE:INDIAVIX-INDEX":
                            cache["vix"] = {
                                "lp": tick_data.get("ltp", 0),
                                "ch": tick_data.get("ch", 0),
                                "chp": tick_data.get("chp", 0)
                            }
                        
                        # Tell WS loop new data is available instantly
                        cache["last_update"] = datetime.now(IST).timestamp()
            except Exception as e:
                print(f"⚠️ Tick processor error: {e}")


    print("🚀 Multi-User Market Worker started.", flush=True)
    await broadcast_log("🚀 Market Data Worker started. Waiting for Fyers token gate...", "info")
    
    # Wait for the Fyers token startup refresh attempt to complete
    await _token_ready.wait()
    await broadcast_log("🔓 Fyers token gate opened. Market Data Worker starting polling.", "success")
    
    # Initialize Instant Tick Queue
    tick_queue = asyncio.Queue()
    ws_feed.register_queue(tick_queue, asyncio.get_running_loop())
    asyncio.create_task(tick_processor(tick_queue))
    
    tick = 0
    last_phase_log = ""
    backoff_seconds = 0  # Exponential backoff for 429 errors

    while True:
        try:
            # Gather all active symbols to check if MCX/CDS are present
            active_users = list(USER_CONTEXTS.keys())
            all_active = []
            for u_id in active_users:
                st = get_user_state(u_id)
                if hasattr(st, 'active_symbols'):
                    all_active.extend(st.active_symbols)

            phase = get_market_phase(all_active)
            config = POLL_CONFIG[phase]

            # Log phase transitions
            if phase != last_phase_log:
                last_phase_log = phase
                phase_names = {
                    "market": "🟢 Market Open — Full-speed polling (every 3s)",
                    "pre_open": "🟡 Pre-Open — Reduced polling (every 10s)",
                    "post_close": "🟠 Post-Close — Minimal polling (every 15s)",
                    "closed": "🔴 Market Closed — Paused (auth-only every 5 min)",
                }
                await broadcast_log(phase_names.get(phase, phase), "info")

            # Handle exponential backoff (from 429 errors)
            if backoff_seconds > 0:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = 0  # Reset after waiting

            # Fetch public quotes if appropriate (every 5 ticks)
            public_quotes = {}
            if tick % 5 == 0:
                try:
                    public_quotes = await get_nse_public_quotes()
                except Exception as e:
                    print(f"⚠️ Failed to fetch public NSE quotes: {e}")

            # 1. Maintenance: Cleanup stale contexts or restore missing ones
            for u_id_key in list(USER_CACHES.keys()):
                u_id = int(u_id_key)  # Normalize to int for consistent key usage
                if u_id not in USER_CONTEXTS:
                    try:
                        client = FyersClient(user_id=u_id)
                        if client.is_authenticated():
                            USER_CONTEXTS[u_id] = client
                            USER_CACHES[u_id_key]["is_auth"] = True
                            if not ws_feed._started:
                                # ws_feed.start is an async function!
                                asyncio.create_task(ws_feed.start(client))
                                asyncio.create_task(broadcast_log(f"✅ Fyers WS started on context recovery for User {u_id}", "success"))
                    except Exception:
                        pass

            active_users = list(USER_CONTEXTS.keys())
            if not active_users and tick % 20 == 0:
                await broadcast_log("⏳ Waiting for active connections...", "info")

            for u_id in active_users:
                client = USER_CONTEXTS.get(u_id)
                if not client:
                    continue
                cache = get_user_cache(u_id)
                state = get_user_state(u_id)
                state.check_daily_reset()

                # Check auth status (always, but at reduced frequency outside market)
                auth_check_interval = 5 if phase == "market" else 30
                if tick % auth_check_interval == 0:
                    try:
                        new_auth = await asyncio.to_thread(client.is_authenticated)
                        old_auth = cache.get("is_auth", False)
                        cache["is_auth"] = new_auth
                        if new_auth != old_auth:
                            status = "Connected" if new_auth else "Disconnected"
                            await broadcast_log(
                                f"🔄 Fyers {status} for user {u_id}",
                                "success" if new_auth else "warning",
                            )
                            if new_auth:
                                cache["login_attempts"] = 0
                    except Exception:
                        cache["is_auth"] = False

                if not cache.get("is_auth"):
                    # Check if user is still active before attempting anything
                    from models import Database
                    user_data = await Database.get_user_by_id(u_id)
                    
                    if not user_data or not user_data.get("is_active", 1):
                        # Reset login attempts and skip if deactivated
                        cache["login_attempts"] = 0
                        continue
                        
                    username = user_data.get("username", f"User {u_id}")

                    # Try refresh_token once every 5 minutes (official Fyers API)
                    # Don't spam retries — if refresh_token fails, manual login is required
                    login_attempts = cache.get("login_attempts", 0)
                    if login_attempts < 2:  # Max 2 attempts via refresh_token
                        last_auto_login = cache.get("last_auto_login", 0)
                        now = datetime.now(IST).timestamp()
                        if (now - last_auto_login) > 300:  # Every 5 min instead of 60s
                            cache["last_auto_login"] = now
                            cache["login_attempts"] = login_attempts + 1
                            await broadcast_log(
                                f"🔄 {username} disconnected. Attempting refresh_token ({login_attempts + 1}/2)...",
                                "warning",
                            )
                            login_success = await asyncio.to_thread(client.refresh_via_refresh_token)
                            if login_success:
                                client.reinit_with_fresh_token()
                                cache["is_auth"] = True
                                cache["login_attempts"] = 0
                                await broadcast_log(f"✅ Token refreshed for {username}", "success")
                                try:
                                    await broadcast_log("🔄 Restarting WS Feed with refreshed token...", "info")
                                    ws_feed.restart(client)
                                except Exception as ws_err:
                                    print(f"❌ Error restarting WS Feed after refresh: {ws_err}")
                            else:
                                if cache["login_attempts"] >= 2:
                                    await broadcast_log(
                                        f"⚠️ Token refresh exhausted for {username}. Please login manually via the Fyers button.",
                                        "error",
                                    )
                                else:
                                    await broadcast_log(
                                        f"⚠️ Token refresh failed for {username}. Will retry in 5 min.",
                                        "warning",
                                    )
                    continue

                # --- DYNAMIC TASK MAPPING PER USER ---
                task_defs = {}

                # Start WS feed if not started yet, or self-heal if disconnected during market hours
                if cache.get("is_auth"):
                    if not ws_feed._started:
                        await ws_feed.start(client)
                    elif not ws_feed.is_connected() and phase in ["market", "pre_open"]:
                        # Auto-heal: if WS is completely dead, hard restart it quickly.
                        # Reduced to 30s to prevent missed trades.
                        now_ts = datetime.now(IST).timestamp()
                        last_ws_check = cache.get("last_ws_check", 0)
                        if now_ts - last_ws_check > 30:
                            cache["last_ws_check"] = now_ts
                            await broadcast_log("⚠️ WS Feed unresponsive. Hard restarting WebSocket...", "warning")
                            try:
                                ws_feed.restart(client)
                            except Exception as ws_err:
                                print(f"❌ Error during auto-heal WS restart: {ws_err}")

                # 1. Quotes (Polling from WS Cache) — Only during trading phases, respecting phase interval
                #    EXCEPT: do ONE initial fetch when user first connects (so last prices show after hours)
                quotes_interval = config["quotes_every"]
                needs_initial_fetch = cache.get("is_auth") and not cache.get("_initial_quotes_fetched")
                if needs_initial_fetch or (quotes_interval > 0 and tick % quotes_interval == 0):
                    is_stale = (datetime.now(IST).timestamp() - cache.get("last_update", 0)) > (quotes_interval * 0.8)
                    if is_stale:
                        base_symbols = ["NSE:NIFTY50-INDEX", "NSE:INDIAVIX-INDEX"]
                        for sym in state.active_symbols:
                            if sym not in base_symbols:
                                base_symbols.append(sym)

                        # Subscribe to WS
                        quotes = {}
                        if ws_feed.is_connected():
                            ws_feed.subscribe(base_symbols)
                            quotes = ws_feed.get_quotes_from_ws(base_symbols)
                        
                        # --- PREV_CLOSE SEEDING (ONE-TIME) ---
                        # The WS in LiteMode only sends LTP. We need prev_close_price to calculate
                        # ch (change) and chp (change %). We seed this ONCE from either REST quotes
                        # or daily candle data. After seeding, the WS _on_message handler calculates
                        # ch/chp automatically on every tick — no more REST API calls needed.
                        if cache.get("is_auth"):
                            symbols_needing_seed = [s for s in base_symbols 
                                                    if s not in quotes or quotes.get(s, {}).get("prev_close_price", 0) == 0]
                            if symbols_needing_seed:
                                # Try REST quotes first (one attempt)
                                try:
                                    rest_quotes = await asyncio.to_thread(
                                        lambda: client.get_quotes(symbols_needing_seed, force_rest=True)
                                    )
                                    if isinstance(rest_quotes, dict):
                                        seeded_count = 0
                                        for sym, q in rest_quotes.items():
                                            prev_close = q.get("prev_close_price", 0)
                                            if prev_close == 0 and q.get("lp", 0) > 0 and q.get("ch") is not None:
                                                prev_close = q["lp"] - q["ch"]
                                            if prev_close > 0:
                                                ws_feed.inject_quote(sym, {**q, "prev_close_price": prev_close})
                                                seeded_count += 1
                                                if sym not in quotes:
                                                    quotes[sym] = q
                                                quotes[sym]["prev_close_price"] = prev_close
                                        if seeded_count > 0:
                                            print(f"✅ Seeded prev_close for {seeded_count} symbols via REST API", flush=True)
                                except Exception as rest_err:
                                    print(f"⚠️ REST seed failed: {rest_err}. Trying candle fallback...", flush=True)
                                
                                # If REST failed, try daily candle fallback for any unseeded symbols
                                unseeded = [s for s in symbols_needing_seed if s not in quotes or quotes.get(s, {}).get("prev_close_price", 0) == 0]
                                if unseeded:
                                    try:
                                        for sym in unseeded:
                                            candles = await asyncio.to_thread(
                                                client.get_historical, sym, "D", days_back=5
                                            )
                                            if candles and len(candles) >= 2:
                                                # Previous day's close = prev_close for today
                                                prev_day_close = candles[-2].get("close", 0)
                                                today_close = candles[-1].get("close", 0)
                                                if prev_day_close > 0:
                                                    ch = round(today_close - prev_day_close, 2)
                                                    chp = round((ch / prev_day_close) * 100, 2)
                                                    seed_data = {
                                                        "lp": today_close,
                                                        "ch": ch,
                                                        "chp": chp,
                                                        "prev_close_price": prev_day_close
                                                    }
                                                    ws_feed.inject_quote(sym, seed_data)
                                                    quotes[sym] = seed_data
                                                    print(f"✅ Seeded prev_close for {sym} via daily candle: {prev_day_close}", flush=True)
                                    except Exception as candle_err:
                                        print(f"⚠️ Candle seed also failed: {candle_err}", flush=True)
                                        # Will retry next tick for unseeded symbols
                        
                        # --- UPDATE CACHE FROM WS QUOTES ---
                        # After seeding, WS quotes will have correct ch/chp on every tick
                        if quotes:
                            if "all_spots" not in cache:
                                cache["all_spots"] = {}
                            for sym, q in quotes.items():
                                cache["all_spots"][sym] = q

                            cache["last_update"] = datetime.now(IST).timestamp()
                            cache["_initial_quotes_fetched"] = True

                # 2. Sync Core Data (Funds, Positions, Orders) — Frequency depends on phase
                sync_interval = config["sync_every"]
                if tick % sync_interval == 0 and cache.get("is_auth"):
                    task_defs["synced"] = asyncio.to_thread(client.get_synced_data)

                # Execute tasks
                if task_defs:
                    names = list(task_defs.keys())
                    cors = [task_defs[n] for n in names]
                    results_list = await asyncio.gather(*cors, return_exceptions=True)
                    results = dict(zip(names, results_list))

                    # Handle Sync
                    synced = results.get("synced")
                    if isinstance(synced, dict):
                        updated_any = False
                        if synced.get("positions") is not None:
                            pos_list = synced["positions"]
                            has_open = any(p.get("netQty", 0) != 0 or p.get("qty", 0) != 0 for p in pos_list)
                            
                            # Sync manual Fyers trades to the app state (after 9 AM when Fyers has cleared yesterday's positions)
                            if len(pos_list) > 0 and not state.paper_trading:
                                now = datetime.now(IST)
                                if now.hour >= 9:
                                    # Only count manual trades that are closed AND resulted in a loss
                                    losing_trades = sum(1 for p in pos_list if p.get("qty", 0) == 0 and p.get("pl", 0) < 0)
                                    if losing_trades > state.live_trades_today:
                                        state.live_trades_today = losing_trades
                                        state.save()
                            if not has_open and state.trades_today == 0:
                                pos_list = []
                                total_pnl = 0.0
                            else:
                                total_pnl = sum(p.get("pl", 0) for p in pos_list)
                            
                            cache["active_positions"] = pos_list
                            cache["total_pnl"] = total_pnl
                            state.update_pnl(total_pnl)
                            updated_any = True
                        if synced.get("orders") is not None:
                            cache["orders"] = synced["orders"][-10:]
                            updated_any = True
                        if synced.get("funds") is not None:
                            cache["funds"] = synced["funds"]
                            updated_any = True
                        if updated_any:
                            cache["last_update"] = datetime.now(IST).timestamp()

            # Update public quotes for all users in USER_CACHES if we fetched new ones
            if public_quotes:
                for u_id_key in list(USER_CACHES.keys()):
                    u_cache = USER_CACHES[u_id_key]
                    if "NSE:NIFTY50-INDEX" in public_quotes:
                        u_cache["spot"] = public_quotes["NSE:NIFTY50-INDEX"]
                    if "NSE:INDIAVIX-INDEX" in public_quotes:
                        u_cache["vix"] = public_quotes["NSE:INDIAVIX-INDEX"]

                    is_stale = (datetime.now(IST).timestamp() - u_cache.get("last_update", 0)) > 10
                    if not u_cache.get("is_auth") or is_stale or phase == "closed":
                        if "all_spots" not in u_cache:
                            u_cache["all_spots"] = {}
                        for sym, q in public_quotes.items():
                            u_cache["all_spots"][sym] = q
                        u_cache["last_update"] = datetime.now(IST).timestamp()
                    else:
                        # Even for authenticated users, use public quotes to fix ch/chp
                        # when WS feed hasn't seeded prev_close yet (LiteMode issue)
                        for sym, pq in public_quotes.items():
                            prev_close = pq.get("prev_close", 0)
                            if prev_close > 0:
                                # Inject prev_close into WS feed so future ticks calculate ch/chp
                                ws_feed.inject_quote(sym, {
                                    "lp": pq.get("lp", 0),
                                    "ch": pq.get("ch", 0),
                                    "chp": pq.get("chp", 0),
                                    "prev_close_price": prev_close,
                                    "open_price": pq.get("open", 0),
                                    "high_price": pq.get("high", 0),
                                    "low_price": pq.get("low", 0),
                                })
                            # Fill in ch/chp from public quotes if WS cache shows 0
                            cached_spot = u_cache.get("spot", {})
                            if sym == "NSE:NIFTY50-INDEX" and cached_spot:
                                if cached_spot.get("ch", 0) == 0 and cached_spot.get("chp", 0) == 0:
                                    if pq.get("ch", 0) != 0 or pq.get("chp", 0) != 0:
                                        cached_spot["ch"] = pq["ch"]
                                        cached_spot["chp"] = pq["chp"]
                                        u_cache["spot"] = cached_spot
                                        u_cache["last_update"] = datetime.now(IST).timestamp()
                            if "all_spots" not in u_cache:
                                u_cache["all_spots"] = {}
                            cached_q = u_cache["all_spots"].get(sym, {})
                            if cached_q.get("ch", 0) == 0 and cached_q.get("chp", 0) == 0:
                                if pq.get("ch", 0) != 0 or pq.get("chp", 0) != 0:
                                    cached_q["ch"] = pq["ch"]
                                    cached_q["chp"] = pq["chp"]
                                    u_cache["all_spots"][sym] = cached_q

            tick += 1
            await asyncio.sleep(config["sleep"])
        except Exception as e:
            print(f"⚠️ Market Data Worker Error: {e}")
            await asyncio.sleep(5)
