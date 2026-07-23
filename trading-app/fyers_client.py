"""
Fyers API Client Wrapper
Handles authentication, historical data, quotes, option chain, and order management.
"""

import os
import json
import logging
import threading
import pytz
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from pathlib import Path
from engine.encryption import get_secret, save_to_vault

IST = pytz.timezone('Asia/Kolkata')

# Load credentials from fyers-mcp-server .env
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ENV_PATH = PROJECT_ROOT / "fyers-mcp-server" / ".env"
load_dotenv(ENV_PATH)

logger = logging.getLogger("FYERS_CLIENT")

class FyersClient:
    """Wrapper around Fyers API v3 for trading operations."""

    def __init__(self, user_id=None):
        self.user_id = user_id
        self.client = None
        self._cooldown_until = 0
        self._cache = {
            "funds": {"data": None, "ts": 0},
            "positions": {"data": None, "ts": 0},
            "orders": {"data": None, "ts": 0}
        }
        self._last_refresh_date = None  # Tracks the IST date when token was last refreshed
        # Option-chain / historical caches + an in-flight lock to coalesce concurrent fetches.
        # Strategies evaluate concurrently (asyncio.gather), so without this lock every concurrent
        # caller misses the cache at the same instant and stampedes the Fyers optionchain API the
        # moment a cooldown lifts -> instant re-429 -> permanent cooldown loop. The lock ensures
        # exactly one thread fetches per key while the others reuse the freshly-cached result.
        self._oc_cache = {}
        self._oc_lock = threading.Lock()
        self._hist_cache = {}
        # SEPARATE cooldown for the option-chain endpoint. The option chain is the most
        # rate-limited Fyers endpoint; routing its 429s through the shared _trigger_cooldown()
        # froze ALL data (candles, quotes, funds) for 60s, which blanked charts / analysis /
        # regime / trend and blocked trades. Isolating it means an option-chain 429 only pauses
        # the option chain — candle/quote fetches keep flowing.
        self._oc_cooldown_until = 0
        self._init_client()

    @staticmethod
    def _get_master_credentials():
        """Fetch Admin's Master App ID and Secret as fallback for sub-users (SaaS model)."""
        try:
            from models import Database
            return Database.get_master_app_credentials_sync()
        except Exception:
            return ("", "")

    def _is_success(self, resp: Dict) -> bool:
        if not resp or not isinstance(resp, dict):
            return False
        if resp.get("s") == "ok":
            return True
        code = resp.get("code")
        if code in [200, 201, 1101]:
            return True
        if str(code) in ["200", "201", "1101"]:
            return True
        message = str(resp.get("message", "")).lower()
        if "success" in message:
            return True
        return False

    def _get_active_client(self):
        """Get the active client for public/data operations, falling back to admin or env variables."""
        if self.client:
            return self.client
        
        # Avoid circular import at load time
        try:
            import app
            if 1 in app.USER_CONTEXTS and app.USER_CONTEXTS[1].client:
                return app.USER_CONTEXTS[1].client
        except Exception:
            pass
            
        return None

    def _init_client(self):
        """Initialize Fyers client with stored credentials."""
        if self.user_id == 0:
            self.client = None
            return

        from models import Database
        try:
            from fyers_apiv3 import fyersModel
            
            client_id = None
            access_token = None
            
            # Load from DB if user_id provided
            if self.user_id:
                user = Database.get_user_by_id_sync(self.user_id)
                if user:
                    db_client_id = user.get("fyers_client_id")
                    db_access_token = user.get("fyers_access_token")
                    
                    # Client ID can fall back so users can share the Admin's App ID
                    client_id = db_client_id or get_secret("FYERS_CLIENT_ID") or FyersClient._get_master_credentials()[0]
                    
                    # Access Token MUST NEVER fall back to Admin's token for non-admin users!
                    access_token = db_access_token
                    if not access_token and user.get("is_admin"):
                        access_token = get_secret("FYERS_ACCESS_TOKEN")
            else:
                # Default fallback if no user_id (system internal or CLI)
                client_id = get_secret("FYERS_CLIENT_ID")
                access_token = get_secret("FYERS_ACCESS_TOKEN")

            if not client_id or not access_token:
                raise ValueError(f"Missing FYERS_CLIENT_ID or FYERS_ACCESS_TOKEN for user {self.user_id}")
            
            # Use the client_id as configured in the DB without forcing -100
            if client_id and len(client_id.split("-")) == 1:
                client_id = f"{client_id}-100"

            self.client = fyersModel.FyersModel(
                client_id=client_id,
                is_async=False,
                token=access_token,
                log_path=str(BASE_DIR / "logs")
            )
        except Exception as e:
            print(f"❌ Fyers client init error for user {self.user_id}: {e}")
            self.client = None

    def reinit_with_fresh_token(self):
        """Re-read token from DB and re-create the Fyers model. Call after token refresh."""
        print(f"🔄 Reinitializing FyersClient for user {self.user_id} with fresh token...", flush=True)
        # Clear all auth caches so next check hits Fyers API
        if hasattr(self, '_last_auth_check'):
            delattr(self, '_last_auth_check')
        if hasattr(self, '_cached_auth_status'):
            delattr(self, '_cached_auth_status')
        if hasattr(self, '_last_auto_refresh_attempt'):
            delattr(self, '_last_auto_refresh_attempt')
        self._cooldown_until = 0
        self._last_refresh_date = datetime.now(IST).date()
        # Re-init will re-read from DB
        self._init_client()
        if self.client:
            print(f"✅ FyersClient reinitialized for user {self.user_id}", flush=True)
        else:
            print(f"❌ FyersClient reinit failed for user {self.user_id} — client is None", flush=True)

    def _check_cooldown(self) -> bool:
        """Check if we are in a rate-limit cooldown period."""
        import time
        if time.time() < self._cooldown_until:
            return True
        return False

    def _check_oc_cooldown(self) -> bool:
        """Option-chain-only cooldown (does NOT block candles/quotes/funds)."""
        import time
        return time.time() < self._oc_cooldown_until

    def _trigger_oc_cooldown(self, duration=60):
        """Cool down ONLY the option-chain endpoint after its own 429."""
        import time
        self._oc_cooldown_until = time.time() + duration
        print(f"⏳ Option-chain cooldown {duration}s (candles/quotes unaffected).")

    def _trigger_cooldown(self, duration=60):
        """Set a cooldown period (e.g., after a 429 error)."""
        import time
        self._cooldown_until = time.time() + duration
        print(f"⏳ API Global Cooldown triggered for {duration} seconds.")

    def get_synced_data(self) -> Dict:
        """Fetch funds, positions, and orders in one batch with smart caching."""
        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                return {
                    "funds": self.get_funds(),
                    "positions": self.get_positions(),
                    "orders": self.get_orders(),
                    "cooldown": False
                }
        except Exception:
            pass

        import time
        now = time.time()
        
        # If in cooldown, return whatever we have in cache
        if self._check_cooldown():
            return {
                "funds": self._cache["funds"]["data"],
                "positions": self._cache["positions"]["data"],
                "orders": self._cache["orders"]["data"],
                "cooldown": True
            }

        # Decide what to fetch based on age
        results = {}
        
        # Positions & Orders (15s cache)
        if now - self._cache["positions"]["ts"] > 15:
            pos = self.get_positions()
            if isinstance(pos, dict) and pos.get("code") == -429:
                self._trigger_cooldown() # Stop everything if one fails
            else:
                self._cache["positions"] = {"data": pos, "ts": now}
                self._cache["orders"] = {"data": self.get_orders(), "ts": now}
        
        # Funds (60s cache)
        if now - self._cache["funds"]["ts"] > 60:
            funds = self.get_funds()
            if isinstance(funds, dict) and funds.get("code") == -429:
                self._trigger_cooldown()
            else:
                self._cache["funds"] = {"data": funds, "ts": now}

        return {
            "funds": self._cache["funds"]["data"],
            "positions": self._cache["positions"]["data"],
            "orders": self._cache["orders"]["data"],
            "cooldown": False
        }

    def get_access_token_for_ws(self):
        """Returns the token in 'appid:token' format required for websockets."""
        if self.user_id:
            try:
                from models import Database
                user = Database.get_user_by_id_sync(self.user_id)
                if user:
                    db_client_id = user.get("fyers_client_id")
                    db_access_token = user.get("fyers_access_token")
                    client_id = db_client_id or get_secret("FYERS_CLIENT_ID") or FyersClient._get_master_credentials()[0]
                    # SECURITY: Non-admin users must NOT fall back to the admin's token.
                    # BUG FIX: for the ADMIN this must mirror __init__ (the REST path) which DOES
                    # fall back to the vault token — the login persists the token to the encrypted
                    # vault (get_secret 'FYERS_ACCESS_TOKEN'), NOT users.fyers_access_token (that
                    # column is empty). Without this fallback the WS feed alone got no token
                    # ("Missing access token") while REST/balance worked — so the app showed
                    # "connected" but produced no ticks, no signals, no trades.
                    access_token = db_access_token
                    if not access_token and user.get("is_admin"):
                        access_token = get_secret("FYERS_ACCESS_TOKEN")
                    if client_id and access_token:
                        # Allow any valid suffix like -100, -200, -300 for websocket
                        if "-" in client_id:
                            client_id = client_id.split("-")[0]
                        return f"{client_id}:{access_token}"
            except Exception:
                pass
            return None
        else:
            client_id = get_secret("FYERS_CLIENT_ID")
            access_token = get_secret("FYERS_ACCESS_TOKEN")
            if not client_id or not access_token:
                return None
            # Allow any suffix like -100, -200 for websocket
            if "-" in client_id:
                client_id = client_id.split("-")[0]
            return f"{client_id}:{access_token}"

    def start_data_socket(self, on_message=None, on_error=None, on_close=None, on_open=None):
        """Initializes and connects the Fyers Data WebSocket."""
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
            token = self.get_access_token_for_ws()
            if not token:
                print("❌ Cannot start WebSocket: Missing token.")
                return None

            fyers_socket = data_ws.FyersDataSocket(
                access_token=token,
                log_path="",
                litemode=False,
                reconnect=False, # We handle reconnections explicitly in app.py
                on_connect=on_open,
                on_close=on_close,
                on_error=on_error,
                on_message=on_message
            )
            fyers_socket.connect()
            return fyers_socket
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            return None

    def is_authenticated(self) -> bool:
        """Check if client is authenticated and working, with local caching.
        
        This method is called frequently by multiple background workers
        (market_data_worker, automation_loop, trailing_monitor) so it MUST
        be fast and avoid hammering the Fyers API.  Key design:
        
        1. Negative results (token expired / 429) are cached for 5 minutes
           so background workers stop retrying immediately.
        2. The cooldown mechanism is respected — if we're in a 429 cooldown,
           return the cached status without any API call.
        3. Token refresh is NOT attempted here — that's the job of
           fyers_token_refresh_scheduler and market_data_worker's dedicated
           refresh_via_refresh_token path.
        """
        if self.user_id is None:
            return False

        now = datetime.now(IST)
        today = now.date()
        
        # New day boundary check: clear cached auth status if date changed
        if self._last_refresh_date != today:
            if hasattr(self, '_last_auth_check'):
                delattr(self, '_last_auth_check')
            if hasattr(self, '_cached_auth_status'):
                delattr(self, '_cached_auth_status')

        # Ensure user has initialized client correctly
        if not self.client:
            self._init_client()
        if not self.client:
            return False

        # Check cooldown — if rate-limited, don't even try the API
        if self._check_cooldown():
            return getattr(self, '_cached_auth_status', False)

        # Cache auth result for 5 minutes regardless of success/failure
        # This prevents spamming the Fyers API when a token is expired
        cache_duration = 300
        
        if hasattr(self, '_last_auth_check') and (now - self._last_auth_check).total_seconds() < cache_duration:
            return getattr(self, '_cached_auth_status', False)

        if not self.client:
            self._init_client()
        if not self.client:
            return False
            
        try:
            resp = self.client.get_profile()
            
            if resp.get("code") != 200:
                print(f"⚠️ [User {self.user_id}] Auth check failed! ClientID: {self.client.client_id}, Response: {resp}", flush=True)

            self._last_auth_check = now
            
            if resp.get("code") == 200:
                self._cached_auth_status = True
                self._last_refresh_date = today  # Mark as verified for today
                return True
                
            # Fyers code -353 is "API Limit exceeded per day"
            # This means the token is likely valid, but we are being throttled.
            if resp.get("code") == -353:
                print("⚠️ Fyers API Daily Limit Reached. Treating as Authenticated.", flush=True)
                self._cached_auth_status = True
                self._last_refresh_date = today  # Mark as verified for today
                return True

            if resp.get("code") == 429:
                # Rate limited — trigger cooldown so ALL methods stop calling Fyers
                self._trigger_cooldown(120)  # 2 minute cooldown for 429
                self._cached_auth_status = False
                return False

            if resp.get("code") == -8:
                print("🔐 Fyers token expired.", flush=True)
                # Do NOT attempt inline refresh here — that causes cascading
                # API calls from every background worker.  The dedicated
                # fyers_token_refresh_scheduler and market_data_worker handle
                # refresh_via_refresh_token separately.
                self._cached_auth_status = False
                return False
                
            self._cached_auth_status = False
            return False
        except Exception as e:
            logger.debug(f"Profile Check Exception: {e}")
            self._cached_auth_status = False
            return False

    def check_auth_status(self) -> bool:
        """Alias for is_authenticated used by app.py."""
        return self.is_authenticated()

    def auto_login(self) -> bool:
        """DEPRECATED: Fyers Vagator V2 API has been blocked (-1025 error).
        This method now tries refresh_via_refresh_token as a fallback.
        For fresh logins, use the manual OAuth flow via the browser."""
        print(f"⚠️ auto_login called for User {self.user_id} — Vagator V2 API is deprecated. Trying refresh_token instead.", flush=True)
        try:
            return self.refresh_via_refresh_token()
        except Exception as e:
            print(f"⚠️ auto_login fallback (refresh_token) failed: {e}", flush=True)
            return False

    def get_login_url(self) -> str:
        """Generate the Fyers authorization URL."""
        try:
            from fyers_apiv3 import fyersModel
            from models import Database
            
            client_id = get_secret("FYERS_CLIENT_ID")
            secret_key = get_secret("FYERS_SECRET_KEY")
            redirect_uri = get_secret("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")
            
            # Load from DB if user_id provided (v4.4.2 multi-user fix)
            if self.user_id:
                user = Database.get_user_by_id_sync(self.user_id)
                if user:
                    if user.get("fyers_client_id"): client_id = user["fyers_client_id"]
                    if user.get("fyers_secret"): secret_key = user["fyers_secret"]
                    # SaaS fallback: use Master App ID if user has no personal keys
                    if not client_id: client_id = FyersClient._get_master_credentials()[0]
                    if not secret_key: secret_key = FyersClient._get_master_credentials()[1]

            if not client_id or not secret_key:
                print(f"⚠️ Missing Client ID or Secret for login URL (User {self.user_id})", flush=True)
                return ""

            cid_display = (client_id[:5] + "...") if client_id else "NONE"
            print(f"🔗 Generating Login URL: Client={cid_display} | Redirect={redirect_uri}", flush=True)
            session = fyersModel.SessionModel(
                client_id=client_id,
                secret_key=secret_key,
                redirect_uri=redirect_uri,
                response_type="code",
                grant_type="authorization_code"
            )
            return session.generate_authcode()
        except Exception as e:
            print(f"❌ Error generating login URL: {e}", flush=True)
            return ""

    def get_profile(self) -> Dict[str, Any]:
        """Compat shim for the multi-broker interface / broker-factory login flow. The original
        FyersClient (the complete, fully-fixed client the app runs on) didn't expose this; the
        parallel engine/brokers/fyers.py wrapper is abstract/incomplete, so the factory now returns
        THIS client and needs get_profile()."""
        try:
            client = self._get_active_client()
            return client.get_profile() if client else {}
        except Exception as e:
            print(f"get_profile error: {e}", flush=True)
            return {}

    def _save_cache(self, access_token: str, refresh_token: str = None, authed: bool = True):
        """Compat shim: persist a freshly-obtained token (broker-factory login flow at app.py:3142).
        Mirrors set_auth_code's persistence without re-doing the auth-code exchange."""
        try:
            from models import Database
            Database.update_fyers_tokens_sync(self.user_id, access_token, refresh_token or "")
        except Exception as e:
            print(f"_save_cache token persist failed: {e}", flush=True)
        self._cached_auth_status = bool(authed)

    def set_auth_code(self, code: str) -> Dict[str, Any]:
        """Exchange auth code for access token and save to Database (and .env for fallback)."""
        try:
            from fyers_apiv3 import fyersModel
            from models import Database
            
            client_id = get_secret("FYERS_CLIENT_ID")
            secret_key = get_secret("FYERS_SECRET_KEY")
            # Try to determine best redirect_uri
            redirect_uri = get_secret("FYERS_REDIRECT_URI")
            if not redirect_uri:
                redirect_uri = "https://trade.fyers.in/api-login/redirect-uri/index.html"
            
            # Load from DB if user_id provided (v4.4.2 multi-user fix)
            if self.user_id:
                user = Database.get_user_by_id_sync(self.user_id)
                if user:
                    if user.get("fyers_client_id"): client_id = user["fyers_client_id"]
                    if user.get("fyers_secret"): secret_key = user["fyers_secret"]
                    # SaaS fallback: use Master App ID if user has no personal keys
                    if not client_id: client_id = FyersClient._get_master_credentials()[0]
                    if not secret_key: secret_key = FyersClient._get_master_credentials()[1]

            cid_display = (client_id[:5] + "...") if client_id else "NONE"
            print(f"🔄 Exchanging code for token... User: {self.user_id} | Client: {cid_display} | Code: {code[:10]}... | Redirect: {redirect_uri}", flush=True)
            
            if not client_id or not secret_key:
                return {"success": False, "message": "Missing Client ID or Secret Key"}

            # List of possible redirect URIs to try
            possible_uris = list(dict.fromkeys([
                redirect_uri,
                "https://trade.fyers.in/api-login/redirect-uri/index.html",
                get_secret("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html"),
            ]))
            
            response = None
            last_error = None
            
            for r_uri in possible_uris:
                try:
                    print(f"🔄 Attempting exchange with redirect: {r_uri}", flush=True)
                    session = fyersModel.SessionModel(
                        client_id=client_id,
                        secret_key=secret_key,
                        redirect_uri=r_uri,
                        response_type="code",
                        grant_type="authorization_code"
                    )
                    session.set_token(code)
                    response = session.generate_token()
                    if response.get("code") == 200:
                        print(f"✅ Successful exchange with {r_uri}", flush=True)
                        break
                    else:
                        print(f"⚠️ Exchange failed with {r_uri}: {response}", flush=True)
                except Exception as e:
                    print(f"❌ Error with {r_uri}: {e}", flush=True)
                    last_error = e
                    continue
            
            if not response or response.get("code") != 200:
                msg = response.get("message") if response else str(last_error)
                return {"success": False, "message": f"All redirect URIs failed. Last error: {msg}"}

            _safe_resp = {k: ("<REDACTED>" if k in ("access_token", "refresh_token") else v) for k, v in (response or {}).items()}
            print(f"📥 Token Generation Response: {_safe_resp}", flush=True)
            
            if response.get("code") == 200:
                access_token = response.get("access_token")
                refresh_token = response.get("refresh_token")
                # Save both tokens atomically; refresh_token enables ~14-day auto-refresh
                self._save_tokens(access_token, refresh_token)

                client_id_for_rest = client_id
                if client_id and len(client_id.split("-")) == 1:
                    client_id_for_rest = f"{client_id}-100"
                # Re-init the local client immediately
                self.client = fyersModel.FyersModel(
                    client_id=client_id_for_rest,
                    is_async=False,
                    token=access_token,
                    log_path=str(BASE_DIR / "logs")
                )

                # Clear local cache to force immediate re-validation
                if hasattr(self, '_last_auth_check'):
                    delattr(self, '_last_auth_check')

                if refresh_token:
                    print(f"💾 Refresh token captured for User {self.user_id} (enables daily auto-refresh)", flush=True)
                else:
                    print(f"⚠️ No refresh_token in Fyers response — daily auto-refresh disabled. Re-login required tomorrow.", flush=True)

                return {"success": True, "message": "Token generated successfully"}
            else:
                return {"success": False, "message": response.get("message", "Token generation failed")}
        except Exception as e:
            print(f"❌ Token Exchange Exception: {e}", flush=True)
            return {"success": False, "message": str(e)}

    def _save_token(self, token: str):
        """Save access token to Database (multi-user) and .env (fallback)."""
        from models import Database

        # 1. Update Database (Priority for v4.4.2)
        if self.user_id:
            try:
                Database.update_fyers_token_sync(self.user_id, token)
                print(f"✅ Token saved to DB for User {self.user_id}")
            except Exception as e:
                print(f"⚠️ Failed to save token to DB: {e}")

        # 2. Update Vault
        try:
            save_to_vault("FYERS_ACCESS_TOKEN", token)
            print("✅ Token securely saved to encrypted vault.")
        except Exception as e:
            print(f"⚠️ Failed to save token to vault: {e}")

    def _save_tokens(self, access_token: str, refresh_token: Optional[str]):
        """Save both access and refresh tokens. Refresh token enables ~14-day auto-refresh."""
        from models import Database
        # Persist access token using existing helper (also writes to .env)
        if access_token:
            self._save_token(access_token)
        # Persist refresh token (DB only — secret, shouldn't go to .env)
        if refresh_token and self.user_id:
            try:
                Database.update_fyers_tokens_sync(self.user_id, None, refresh_token)
                print(f"✅ Refresh token saved to DB for User {self.user_id}", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to save refresh token to DB: {e}", flush=True)

    def refresh_via_refresh_token(self) -> bool:
        """
        Use Fyers' official refresh_token endpoint to get a new access_token.
        Returns True on success, False otherwise. Caller can fall back to other auth paths.

        Fyers V3 spec:
          POST https://api-t1.fyers.in/api/v3/validate-refresh-token
          payload: {grant_type, appIdHash (sha256(client_id:secret_key)), refresh_token, pin}
        """
        import hashlib
        import requests
        from models import Database

        if not self.user_id:
            print("⚠️ refresh_via_refresh_token: no user_id", flush=True)
            return False

        try:
            user = Database.get_user_by_id_sync(self.user_id)
            refresh_token = (user or {}).get("fyers_refresh_token")
            if not refresh_token:
                print(f"⚠️ refresh_via_refresh_token: no refresh_token stored for User {self.user_id}", flush=True)
                return False

            client_id = (user or {}).get("fyers_client_id") or get_secret("FYERS_CLIENT_ID") or FyersClient._get_master_credentials()[0]
            secret_key = (user or {}).get("fyers_secret") or get_secret("FYERS_SECRET_KEY") or FyersClient._get_master_credentials()[1]
            pin = (user or {}).get("fyers_pin") or get_secret("FYERS_PIN")
            if not (client_id and secret_key and pin):
                print(f"⚠️ refresh_via_refresh_token: missing client_id/secret_key/PIN for User {self.user_id}", flush=True)
                return False

            app_id_hash = hashlib.sha256(f"{client_id}:{secret_key}".encode()).hexdigest()
            payload = {
                "grant_type": "refresh_token",
                "appIdHash": app_id_hash,
                "refresh_token": refresh_token,
                "pin": pin,
            }
            print(f"🔄 Calling Fyers validate-refresh-token for User {self.user_id}...", flush=True)
            resp = requests.post(
                "https://api-t1.fyers.in/api/v3/validate-refresh-token",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            data = {}
            try:
                data = resp.json()
            except Exception:
                pass

            new_access = data.get("access_token")
            new_refresh = data.get("refresh_token")  # Fyers may rotate it
            if resp.status_code == 200 and new_access:
                self._save_tokens(new_access, new_refresh)
                # Re-init local client with new token
                try:
                    from fyers_apiv3 import fyersModel
                    client_id_for_rest = client_id
                    if client_id and len(client_id.split("-")) == 1:
                        client_id_for_rest = f"{client_id}-100"
                        
                    self.client = fyersModel.FyersModel(
                        client_id=client_id_for_rest,
                        is_async=False,
                        token=new_access,
                        log_path=str(BASE_DIR / "logs"),
                    )
                except Exception as e:
                    print(f"⚠️ Re-init after refresh failed: {e}", flush=True)
                # Reset auth cache
                if hasattr(self, "_last_auth_check"):
                    delattr(self, "_last_auth_check")
                print(f"✅ refresh_via_refresh_token success for User {self.user_id}", flush=True)
                return True

            # Likely expired refresh_token (every ~15 days) — caller should re-OAuth
            print(f"❌ refresh_via_refresh_token failed: http={resp.status_code} resp={data}", flush=True)
            return False
        except Exception as e:
            print(f"❌ refresh_via_refresh_token exception: {e}", flush=True)
            return False

    async def refresh_via_refresh_token_with_retry(self, max_retries: int = 3) -> bool:
        """Refresh token with retry and exponential backoff.
        
        Handles transient failures (network issues, 429 rate limits) by retrying
        with increasing delays. Falls back to manual re-auth after all retries fail.
        
        Args:
            max_retries: Maximum number of retry attempts (default 3)
        
        Returns:
            True if refresh succeeded, False if all retries failed
        """
        import asyncio
        
        for attempt in range(max_retries):
            try:
                success = self.refresh_via_refresh_token()
                if success:
                    return True
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"⚠️ Token refresh attempt {attempt + 1}/{max_retries} failed. "
                          f"Retrying in {wait_time}s...", flush=True)
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                print(f"❌ Token refresh attempt {attempt + 1}/{max_retries} exception: {e}", flush=True)
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
        
        # All retries exhausted
        print(f"❌ Token refresh failed after {max_retries} attempts for User {self.user_id}. "
              f"Manual re-authentication required.", flush=True)
        
        # Alert via Telegram if available
        try:
            await broadcast_log(
                f"❌ Token refresh failed for User {self.user_id} after {max_retries} attempts. "
                f"Manual re-auth required.",
                level="error",
                user_id=self.user_id,
                telegram_alert=True
            )
        except Exception:
            pass
        
        return False

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get live quote for a single symbol. Checks WebSocket cache first."""
        try:
            from engine.ws_feed import ws_feed
            if ws_feed.is_connected():
                q = ws_feed.get_quote_from_ws(symbol)
                if q: return q
        except Exception:
            pass

        if self._check_cooldown(): return None
        client = self._get_active_client()
        if not client:
            return None
        try:
            resp = client.quotes({"symbols": symbol})
            if resp.get("code") == 200:
                data = resp.get("d", [])
                if data and isinstance(data, list):
                    v = data[0].get("v", {})
                    if v.get("lp", 0) > 0:
                        return v
            elif resp.get("code") in (-8, -348, -99):
                # Mark auth as failed but do NOT invalidate the cache timer.
                # This prevents background workers from hammering get_profile().
                self._cached_auth_status = False
                print(f"⚠️ Auth error in get_quote ({resp.get('code')}). Cached as unauthenticated.", flush=True)
            elif resp.get("code") in (-429, 429):
                self._trigger_cooldown()
            return None
        except Exception as e:
            print(f"Quote error for {symbol}: {e}")
            return None

    def get_quotes(self, symbols: List[str], force_rest: bool = False) -> Dict[str, Dict]:
        """Get live quotes for multiple symbols. Checks WebSocket cache first unless force_rest is True."""
        results = {}
        missing = symbols.copy()

        if not force_rest:
            try:
                from engine.ws_feed import ws_feed
                if ws_feed.is_connected():
                    ws_feed.subscribe(symbols)
                    cached = ws_feed.get_quotes_from_ws(symbols)
                    for sym, data in cached.items():
                        results[sym] = data
                        if sym in missing:
                            missing.remove(sym)
            except Exception:
                pass

        if not missing:
            return results

        if self._check_cooldown(): return results
        client = self._get_active_client()
        if not client:
            return results
        try:
            symbols_str = ",".join(missing)
            resp = client.quotes({"symbols": symbols_str})
            if resp.get("code") == 200:
                for item in resp.get("d", []):
                    v = item.get("v", {})
                    if v.get("lp", 0) > 0:
                        results[item["n"]] = v
            elif resp.get("code") in (-8, -348, -99):
                # Mark auth as failed but do NOT invalidate the cache timer.
                # This prevents background workers from hammering get_profile().
                self._cached_auth_status = False
                print(f"⚠️ Auth error in get_quotes ({resp.get('code')}). Cached as unauthenticated.", flush=True)
            elif resp.get("code") in (-429, 429):
                self._trigger_cooldown()
            return results
        except Exception as e:
            print(f"Quotes error for {symbols}: {e}")
            return results

    def get_historical(self, symbol: str, resolution: str, days_back: int = 10) -> List[Dict]:
        """
        Get historical candle data.

        Args:
            symbol: e.g., 'NSE:NIFTY50-INDEX'
            resolution: '1', '5', '15', '60', 'D' (minutes or day)
            days_back: number of days of history

        Returns:
            List of candle dicts with keys: timestamp, open, high, low, close, volume
        """
        import time
        # Candle cache (cache-through-cooldown, same pattern as get_funds / get_option_chain_strikes).
        # The analysis pipeline fetches 4 timeframes EVERY cycle; without a cache this hammers the
        # Fyers REST history API into a 429 cooldown, after which get_historical returns [] ->
        # empty candles -> the analysis bails before computing spot/expiry -> "No expiry found" ->
        # every auto-trade is skipped. TTLs are far shorter than each candle's own period so signals
        # stay fresh; during a cooldown/error we serve the last-good candles instead of [].
        _now = time.time()
        # Cache key is symbol:resolution ONLY — deliberately ignoring days_back. Different callers
        # request the same resolution with slightly different day spans (chart=3, analysis=4, etc.);
        # keying on days_back fragmented the cache so each variant separately hammered the Fyers
        # history API. Fyers then SILENTLY throttles a busy session (returns HTTP 200 with an EMPTY
        # candle list, no 429/error), which blanked charts/analysis/regime/trend. Collapsing to one
        # key per resolution + longer TTLs keeps history calls well under the throttle. All callers
        # want "recent candles", so sharing the first fetch's span is fine.
        _ck = f"{symbol}:{resolution}"
        if not hasattr(self, '_hist_cache'):
            self._hist_cache = {}
        _ttl = {"1": 30, "5": 60, "60": 300, "D": 900}.get(str(resolution), 60)
        _cached = self._hist_cache.get(_ck)
        if _cached and (_now - _cached['ts'] < _ttl) and _cached['data']:
            return _cached['data']

        def _stale():
            return _cached['data'] if _cached else []

        if self._check_cooldown(): return _stale()
        client = self._get_active_client()
        if not client:
            return _stale()
        try:
            end_date = datetime.now(IST)
            start_date = end_date - timedelta(days=days_back)

            data = {
                "symbol": symbol,
                "resolution": resolution,
                "date_format": "1",
                "range_from": start_date.strftime("%Y-%m-%d"),
                "range_to": end_date.strftime("%Y-%m-%d")
            }
            
            # Only use cont_flag for futures
            if "-FUT" in symbol:
                data["cont_flag"] = "1"

            resp = client.history(data)
            logger.debug(f"History response for {symbol}: {resp.get('code') if isinstance(resp, dict) else 'Error'}")

            if resp.get("code") == 200:
                candles = resp.get("candles", [])
                result = []
                for c in candles:
                    result.append({
                        "timestamp": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5])
                    })
                if result:
                    self._hist_cache[_ck] = {'data': result, 'ts': _now}
                return result
            elif resp.get("code") in (-8, -348, -99):
                # Mark auth as failed but do NOT invalidate the cache timer.
                self._cached_auth_status = False
                print(f"⚠️ Auth error in get_historical ({resp.get('code')}). Cached as unauthenticated.", flush=True)
                return _stale()
            elif resp.get("code") in (-429, 429):
                self._trigger_cooldown()
                print("History error: Request Limit reached")
                return _stale()
            else:
                print(f"History error: {resp.get('message', 'Unknown')}")
                return _stale()
        except Exception as e:
            print(f"Historical data error: {e}")
            return _stale()

    def resolve_active_commodity_contract(self, prefix: str, max_months_ahead: int = 4) -> str:
        """Nearest TRADEABLE MCX/CDS future for a commodity prefix (e.g. 'MCX:CRUDEOIL'),
        validated against the history API and cached ~2h.

        Why this exists: the old resolver just stamped the current CALENDAR month
        (MCX:CRUDEOIL26JULFUT). MCX crude expires mid-month (~19-20th), and an EXPIRED contract
        still returns a stale QUOTE but its history comes back -300 "Invalid symbol" — so from the
        20th onward the watchlist/agent kept pointing at a dead contract: 0 candles -> strategies
        had no data -> zero MCX trades. History (code 200 + candles) is the authoritative "is this
        contract live" signal, so we roll month-by-month until one returns candles.
        """
        import time as _t
        cache = getattr(self, "_commodity_contract_cache", {})
        hit = cache.get(prefix)
        if hit and hit.get("until", 0) > _t.time():
            return hit["sym"]

        now = datetime.now(IST)
        client = self._get_active_client()
        end_s = now.strftime("%Y-%m-%d")
        start_s = (now - timedelta(days=4)).strftime("%Y-%m-%d")
        fallback = f"{prefix}{now.strftime('%y')}{now.strftime('%b').upper()}FUT"
        if client is None or self._check_cooldown():
            return fallback

        for m in range(max_months_ahead + 1):
            month0 = now.month - 1 + m
            year = now.year + month0 // 12
            mon = month0 % 12 + 1
            d = now.replace(year=year, month=mon, day=1)
            sym = f"{prefix}{d.strftime('%y')}{d.strftime('%b').upper()}FUT"
            try:
                r = client.history({"symbol": sym, "resolution": "5", "date_format": "1",
                                    "range_from": start_s, "range_to": end_s, "cont_flag": "1"})
                if r and r.get("code") == 200 and r.get("candles"):
                    self._commodity_contract_cache = {**cache, prefix: {"sym": sym, "until": _t.time() + 7200}}
                    if m > 0:
                        print(f"🛢️ Rolled {prefix} to live contract {sym} (current month expired).", flush=True)
                    return sym
            except Exception:
                continue
        return fallback

    def get_option_chain_strikes(self, spot: float, expiry_code: str = None, num_strikes: int = 10, base_symbol: str = "NSE:NIFTY50-INDEX") -> dict:
        """
        Cached, stampede-safe wrapper around the Fyers optionchain API.
        Strikes are stable intraday and the premiums here only RANK strikes (the entry order
        re-fetches the live premium at fill), so a 60s cache is safe. The in-flight lock ensures
        that when a cooldown lifts only ONE thread calls the API per key — the concurrent strategy
        evaluations reuse its result instead of stampeding the rate limit (the root cause of the
        earlier permanent 429 loop).
        """
        import time
        _now = time.time()
        _ck = f"{base_symbol}:{num_strikes}"
        _TTL = 60
        _cached = self._oc_cache.get(_ck)
        if _cached and (_now - _cached['ts'] < _TTL) and _cached['data'].get('calls'):
            return _cached['data']
        with self._oc_lock:
            # Re-check inside the lock: another thread may have just populated the cache.
            _now = time.time()
            _cached = self._oc_cache.get(_ck)
            if _cached and (_now - _cached['ts'] < _TTL) and _cached['data'].get('calls'):
                return _cached['data']
            # During a cooldown (global OR option-chain-specific), serve the last good chain.
            if self._check_cooldown() or self._check_oc_cooldown():
                return _cached['data'] if _cached else {"calls": [], "puts": [], "atm": spot}
            result = self._fetch_option_chain(spot, expiry_code, num_strikes, base_symbol)
            if result.get("calls") or result.get("puts"):
                self._oc_cache[_ck] = {'data': result, 'ts': _now}
                return result
            # Fetch failed / empty — serve stale if we have it.
            return _cached['data'] if _cached else result

    def _fetch_option_chain(self, spot: float, expiry_code: str = None, num_strikes: int = 10, base_symbol: str = "NSE:NIFTY50-INDEX") -> dict:
        """Raw Fyers optionchain fetch + parse. No caching/cooldown — callers hold the lock."""
        # Call the API directly
        data = {
            "symbol": base_symbol,
            "strikecount": num_strikes,
            "timestamp": "" # Let Fyers pick the nearest expiry automatically
        }
        
        try:
            resp = self.client.optionchain(data)
            if not resp or resp.get("code") != 200:
                if resp and resp.get("code") == -429:
                    self._trigger_oc_cooldown()  # option-chain-only — never freeze candles/quotes
                import logging
                logger = logging.getLogger("DASHBOARD")
                logger.error(f"Fyers Option Chain API failed for {base_symbol}: {resp}")
                return {"calls": [], "puts": [], "atm": spot}
                
            oc = resp.get("data", {}).get("optionsChain", [])
            
            # The API returns all strikes, mixed CE and PE. We need to split them.
            calls = []
            puts = []
            
            # Determine ATM strike from the API response (closest strike to spot)
            valid_strikes = [item.get("strike_price") for item in oc if item.get("strike_price", -1) > 0]
            atm = min(valid_strikes, key=lambda x: abs(x - spot)) if valid_strikes else spot
            
            for item in oc:
                strike = item.get("strike_price", -1)
                if strike <= 0:
                    continue
                    
                sym = item.get("symbol", "")
                opt_type = item.get("option_type", "")
                
                entry = {
                    "strike": strike,
                    "symbol": sym,
                    "ltp": item.get("ltp", 0),
                    "bid": item.get("bid", 0),
                    "ask": item.get("ask", 0),
                    "volume": item.get("volume", 0),
                    "oi": item.get("oi", 0),
                    "prev_close": item.get("ltp", 0) - item.get("ltpch", 0),
                    "change_pct": item.get("ltpchp", 0),
                }
                
                if opt_type == "CE":
                    calls.append(entry)
                elif opt_type == "PE":
                    puts.append(entry)
                    
            # Sort by strike
            calls.sort(key=lambda x: x["strike"])
            puts.sort(key=lambda x: x["strike"])
            
            # ═══ CANDLE FALLBACK ═══
            all_ltps_zero = all(c.get("ltp", 0) == 0 for c in calls) and all(p.get("ltp", 0) == 0 for p in puts)
            if all_ltps_zero:
                import logging
                logger = logging.getLogger("DASHBOARD")
                logger.info("📊 Option chain quotes empty — using candle fallback for LTPs")
                
                key_strikes = sorted(set(valid_strikes), key=lambda x: abs(x - atm))[:5]
                for strike_list in [calls, puts]:
                    for opt in strike_list:
                        if opt["strike"] not in key_strikes or opt.get("ltp", 0) > 0:
                            continue
                        try:
                            candles = self.get_historical(opt["symbol"], "1", 1)
                            if candles and len(candles) > 0:
                                opt["ltp"] = candles[-1].get("close", 0)
                        except Exception:
                            pass
                            
            return {"calls": calls, "puts": puts, "atm": atm}

        except Exception as e:
            import logging
            logger = logging.getLogger("DASHBOARD")
            logger.error(f"Error fetching option chain for {base_symbol}: {e}")
            return {"calls": [], "puts": [], "atm": spot}

    def _nearest_real_expiry(self, base_symbol: str = "NSE:NIFTY50-INDEX") -> Optional[Dict]:
        """AUTHORITATIVE nearest expiry from Fyers' actual expiryData (cached ~1h).

        The programmatic path below assumed NIFTY weeklies fall on THURSDAY and hand-built the
        expiry code. NSE has since moved NIFTY weekly expiry to TUESDAY and many indices are
        effectively monthly-only, so the computed code (e.g. '26723') was a PHANTOM contract:
        every option symbol built from it returned no quote, the option chain came back empty,
        and Strategy 1 / Strategy 2 could never find strikes -> zero trades. Reading Fyers' real
        expiry list removes the guesswork. Code format matches Fyers' own option symbols:
        monthly -> YYMMM (e.g. 26JUL), weekly -> YYMDD (e.g. 26804 for 04-Aug)."""
        import time as _t
        from datetime import datetime
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)

        cache = getattr(self, "_expiry_cache", None)
        if cache and cache.get("symbol") == base_symbol and cache.get("until", 0) > _t.time():
            exps = cache["exps"]
        else:
            if self._check_cooldown():
                return None
            client = self._get_active_client()
            if not client:
                return None
            resp = client.optionchain({"symbol": base_symbol, "strikecount": 1, "timestamp": ""})
            if not resp or resp.get("code") != 200:
                return None
            exps = resp.get("data", {}).get("expiryData", []) or []
            self._expiry_cache = {"symbol": base_symbol, "exps": exps, "until": _t.time() + 3600}

        today = now.date()
        best = None
        for e in exps:
            try:
                ed = datetime.strptime(e["date"], "%d-%m-%Y").date()
            except Exception:
                continue
            if ed < today:
                continue
            if ed == today and now.hour >= 16:   # today's expiry already settled
                continue
            if best is None or ed < best[0]:
                best = (ed, e)
        if not best:
            return None

        d, e = best
        yy = d.strftime("%y")
        if e.get("expiry_flag", "M") == "M":
            code, etype = f"{yy}{d.strftime('%b').upper()}", "monthly"
        else:
            m_map = {10: "O", 11: "N", 12: "D"}
            code, etype = f"{yy}{m_map.get(d.month, str(d.month))}{d.strftime('%d')}", "weekly"
        return {"date": d.strftime("%Y-%m-%d"), "day": d.strftime("%A"),
                "code": code, "dte": (d - today).days, "type": etype}

    def find_nearest_expiry(self, spot: float, base_symbol: str = "NSE:NIFTY50-INDEX") -> Optional[Dict]:
        """
        Find the nearest valid expiry. Prefers Fyers' REAL expiry list (_nearest_real_expiry);
        falls back to programmatic computation only if the API is unavailable.
        Index weeklies historically: NIFTY (Thu) — NOW Tuesday per NSE. Stocks: last Thursday.
        """
        from datetime import datetime, timedelta
        import pytz
        import calendar

        # AUTHORITATIVE first — this is the fix for "no option strikes / no trades".
        try:
            real = self._nearest_real_expiry(base_symbol)
            if real and real.get("code"):
                return real
        except Exception:
            pass

        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        today = now.date()

        is_index = "INDEX" in base_symbol
        d = None

        if not is_index:
            # Stock options: Last Thursday of the current month (or next month if past)
            def get_last_thursday(year, month):
                c = calendar.monthcalendar(year, month)
                for week in reversed(c):
                    if week[calendar.THURSDAY] != 0:
                        return datetime(year, month, week[calendar.THURSDAY]).date()
            
            d = get_last_thursday(today.year, today.month)
            if d < today or (d == today and now.hour >= 16):
                # Move to next month
                next_month = today.month + 1 if today.month < 12 else 1
                next_year = today.year if today.month < 12 else today.year + 1
                d = get_last_thursday(next_year, next_month)
        else:
            # Determine target weekday based on Index
            target_weekday = 3 # Default Thursday (NIFTY)
            if "BANKNIFTY" in base_symbol: target_weekday = 2 # Wed
            elif "FINNIFTY" in base_symbol: target_weekday = 1 # Tue
            elif "MIDCPNIFTY" in base_symbol: target_weekday = 0 # Mon

            for delta in range(0, 8):
                d_candidate = today + timedelta(days=delta)
                if d_candidate.weekday() != target_weekday:
                    continue
                if d_candidate == today and now.hour >= 16:
                    continue
                d = d_candidate
                break

        if not d:
            return None

        dte = (d - today).days
        
        # Build the Fyers option code
        yy = d.strftime("%y")
        month_map = {10: "O", 11: "N", 12: "D"}
        m_code = month_map.get(d.month, str(d.month))
        dd = d.strftime("%d")
        
        # Weekly format: YYMDD (e.g., "26527" for 2026 May 27th)
        weekly_code = f"{yy}{m_code}{dd}"
        
        # Monthly format: YYMMM (e.g., "26MAY")
        mmm = d.strftime("%b").upper()
        monthly_code = f"{yy}{mmm}"
        
        # Try to validate with a quick quote check (optional — don't block on failure)
        atm = round(spot / 50) * 50
        expiry_type = "monthly" if not is_index else "weekly"
        final_code = monthly_code if not is_index else weekly_code
        
        # For indices, optionally check if weekly code works, else fallback to monthly
        if is_index:
            try:
                ce_sym = f"NSE:NIFTY{weekly_code}{atm}CE"
                quote = self.get_quote(ce_sym)
                
                if quote and isinstance(quote, dict) and quote.get("lp", 0) > 0:
                    expiry_type = "weekly"
                    final_code = weekly_code
                else:
                    ce_sym_monthly = f"NSE:NIFTY{monthly_code}{atm}CE"
                    quote_m = self.get_quote(ce_sym_monthly)
                    if quote_m and isinstance(quote_m, dict) and quote_m.get("lp", 0) > 0:
                        expiry_type = "monthly"
                        final_code = monthly_code
                    else:

                        # API failed (rate limited etc.) — use weekly by default
                        expiry_type = "weekly_computed"
                        final_code = weekly_code
            except Exception:
                # API unavailable — use computed weekly
                expiry_type = "weekly_computed"
                final_code = weekly_code
            
        return {
            "date": d.strftime("%Y-%m-%d"),
            "day": d.strftime("%A"),
            "code": final_code,
            "dte": dte,
            "type": expiry_type
        }
        
        # Absolute fallback: shouldn't reach here, but compute next Tuesday anyway
        days_until_tuesday = (1 - today.weekday()) % 7
        if days_until_tuesday == 0 and now.hour >= 16:
            days_until_tuesday = 7
        next_tue = today + timedelta(days=days_until_tuesday)
        yy = next_tue.strftime("%y")
        month_map = {10: "O", 11: "N", 12: "D"}
        m_code = month_map.get(next_tue.month, str(next_tue.month))
        dd = next_tue.strftime("%d")
        weekly_code = f"{yy}{m_code}{dd}"
        
        return {
            "date": next_tue.strftime("%Y-%m-%d"),
            "day": next_tue.strftime("%A"),
            "code": weekly_code,
            "dte": (next_tue - today).days,
            "type": "weekly_fallback"
        }

    def get_positions(self) -> List[Dict]:
        """Get current trading positions."""
        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                updated = False
                for p in state.paper_positions:
                    if p.get("qty", 0) == 0:
                        continue
                    quote = self.get_quote(p["symbol"])
                    if quote and "lp" in quote:
                        ltp = quote["lp"]
                        qty = p["qty"]
                        side = p.get("side", 1)
                        new_pl = round((ltp - p["entryPrice"]) * qty * side, 2)
                        if p.get("pl") != new_pl:
                            p["pl"] = new_pl
                            updated = True
                if updated:
                    state.save()
                return state.paper_positions
        except Exception as e:
            print(f"Error in paper positions: {e}")

        if not self.client:
            return []
        try:
            resp = self.client.positions()
            if resp.get("code") == 200:
                return resp.get("netPositions", [])
            return []
        except Exception:
            return []

    def get_trade_book(self) -> List[Dict]:
        """Today's executed fills. Used to recover a closed trade's REAL realized P&L when the
        broker has dropped the position from the positions feed (Issue 3 — so wins aren't logged
        as breakeven)."""
        try:
            import app
            if app.get_user_state(self.user_id).paper_trading:
                return []
        except Exception:
            pass
        if not self.client:
            return []
        try:
            resp = self.client.tradebook()
            if isinstance(resp, dict) and resp.get("code") == 200:
                return resp.get("tradeBook", []) or []
            return []
        except Exception:
            return []

    def get_orders(self) -> List[Dict]:
        """Get order book."""
        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                return state.paper_orders
        except Exception:
            pass

        if not self.client:
            return []
        try:
            resp = self.client.orderbook()
            if resp.get("code") == 200:
                return resp.get("orderBook", [])
            return []
        except Exception:
            return []

    def check_margin(self, symbol: str, qty: int, side: str, product: str,
                     limit_price: float, sl_points: float = 0) -> Dict:
        """Query Fyers margin API to get actual margin required for an order.

        Returns {"total_margin": float, "available_margin": float, "error": str|None}.
        Uses the /api/v3/multiorder/margin endpoint with a single-order basket.
        Falls back to {"total_margin": 0, "available_margin": 0, "error": "..."} on failure
        so callers can decide whether to proceed or skip.
        """
        try:
            if not self.client:
                return {"total_margin": 0, "available_margin": 0, "error": "No Fyers client"}

            # Resolve auth credentials from the DB for this user
            from models import Database
            user = Database.get_user_by_id_sync(self.user_id) if self.user_id else None
            if not user:
                return {"total_margin": 0, "available_margin": 0, "error": "User not found"}

            client_id = user.get("fyers_client_id") or get_secret("FYERS_CLIENT_ID")
            access_token = user.get("fyers_access_token")
            if not access_token and user.get("is_admin"):
                access_token = get_secret("FYERS_ACCESS_TOKEN")
            if not client_id or not access_token:
                return {"total_margin": 0, "available_margin": 0, "error": "Missing credentials"}

            if client_id and len(client_id.split("-")) == 1:
                client_id = f"{client_id}-100"

            side_int = 1 if side.upper() == "BUY" else -1
            product_map = {"NRML": "MARGIN", "MIS": "INTRADAY"}
            mapped_product = product_map.get(product.upper(), product.upper())
            if product.upper() == "CO":
                mapped_product = "CO"

            order_payload = {
                "symbol": symbol,
                "qty": qty,
                "type": 1,  # LIMIT
                "side": side_int,
                "productType": mapped_product,
                "limitPrice": limit_price,
                "stopPrice": 0,
                "disclosedQty": 0,
                "validity": "DAY",
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0,
            }
            if mapped_product == "CO" and sl_points > 0:
                order_payload["stopLoss"] = round(limit_price - sl_points, 2)

            import requests
            resp = requests.post(
                "https://api-t1.fyers.in/api/v3/multiorder/margin",
                json=[order_payload],
                headers={
                    "Authorization": f"{client_id}:{access_token}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            data = resp.json()

            if data.get("code") == 200 and data.get("margin"):
                m = data["margin"]
                total = float(m.get("total_margin", 0) or 0)
                available = float(m.get("available_margin", 0) or 0)
                logger.info(f"💰 Margin check for {symbol}: required=₹{total:.0f}, available=₹{available:.0f}")
                return {"total_margin": total, "available_margin": available, "error": None}
            else:
                msg = data.get("message", str(data))
                logger.warning(f"⚠️ Margin API error for {symbol}: {msg} | resp={str(data)[:200]}")
                return {"total_margin": 0, "available_margin": 0, "error": msg}
        except Exception as e:
            logger.warning(f"⚠️ Margin check failed for {symbol}: {e}")
            return {"total_margin": 0, "available_margin": 0, "error": str(e)[:80]}

    def get_funds(self) -> Dict:
        """Get account funds."""
        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                return state.paper_funds
        except Exception:
            pass

        if not self.client:
            return {}
        # During a rate-limit cooldown, serve the LAST GOOD funds from cache instead of an
        # error, so the dashboard keeps showing funds through transient Fyers 429s.
        if self._check_cooldown():
            cached = getattr(self, '_funds_cache', None)
            return cached if cached else {"s": "error", "message": "Rate Limited (Cooldown)", "code": -429}
        try:
            resp = self.client.funds()
            if resp.get("code") == 200:
                fund_limit = resp.get("fund_limit", [])
                if isinstance(fund_limit, list) and fund_limit:
                    result = fund_limit[0]
                else:
                    result = fund_limit if isinstance(fund_limit, dict) else {}
                self._funds_cache = result  # remember last good funds for cooldown/error fallback
                return result
            elif resp.get("code") in (-8, -348, -99):
                self._cached_auth_status = False
                if hasattr(self, '_last_auth_check'): delattr(self, '_last_auth_check')
                print(f"⚠️ Auth error from API ({resp.get('code')}). Cache invalidated.", flush=True)
            elif resp.get("code") == -429:
                self._trigger_cooldown()
                cached = getattr(self, '_funds_cache', None)
                if cached: return cached  # serve stale funds through the cooldown
            return resp # Return full error dict (including code/message)
        except Exception as e:
            cached = getattr(self, '_funds_cache', None)
            if cached: return cached
            return {"s": "error", "message": str(e), "code": 500}

    def place_order(self, symbol: str, qty: int, side: str,
                    order_type: str = "MARKET", product: str = "NRML",
                    limit_price: float = 0, stop_price: float = 0,
                    sl_points: float = 12.0, target_points: float = 0.0) -> Dict:
        """
        Place an order.
        For MARKET orders: auto-fetches LTP and places as LIMIT with buffer
        (Fyers Algo apps require Market Price Protection — no true market orders).
        """
        # Check global KILL SWITCH
        from models import Database
        if Database.is_kill_switch_active():
            print(f"🛑 [KILL SWITCH ACTIVE] Order rejected: {symbol} {side} {qty}")
            return {"success": False, "message": "SYSTEM LOCKED: Global Kill-Switch is active."}

        # POSITION SIZING: If qty is 0 or not provided, calculate based on risk.
        # Lazy import — see the note at the top of this file: importing from `state` at module
        # level creates a circular import (state.py imports FyersClient from here).
        if qty <= 0 and limit_price > 0:
            from state import calculate_position_size
            qty = calculate_position_size(self.user_id, limit_price, sl_points, symbol)
            print(f"📊 POSITION SIZING: Calculated qty={qty} for {symbol} (risk={sl_points}pts)")

        side_int = 1 if side.upper() == "BUY" else -1
        sl_order_type = 0

        # Check paper trading
        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                # 1. Fetch live price
                quote = self.get_quote(symbol)
                ltp = quote.get("lp", 0) if quote else limit_price
                if ltp <= 0 and limit_price <= 0:
                    return {"success": False, "message": "Could not fetch live price for " + symbol}
                    
                entry_price = limit_price if limit_price > 0 else ltp
                
                # 2. Generate Order IDs
                import time
                t_ms = int(time.time() * 1000)
                order_id = f"PO-{t_ms}"
                sl_order_id = f"SL-{t_ms+1}" if sl_points > 0 else ""
                tgt_order_id = f"TGT-{t_ms+2}" if target_points > 0 else ""
                
                # 3. Create main order entry
                from engine.automation import IST
                main_order = {
                    "id": order_id,
                    "symbol": symbol,
                    "qty": qty,
                    "side": side_int,
                    "type": 2 if limit_price <= 0 else 1,
                    "limitPrice": entry_price,
                    "stopPrice": 0,
                    "status": 2, # FILLED
                    "orderDateTime": datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S"),
                    "productType": product,
                    "message": "Order Filled (Paper Mode)"
                }
                state.paper_orders.insert(0, main_order)
                
                # Create pending SL / Target orders
                sl_trigger = 0.0
                if sl_points > 0:
                    sl_trigger = round(round((entry_price - sl_points if side_int == 1 else entry_price + sl_points) / 0.05) * 0.05, 2)
                    sl_order = {
                        "id": sl_order_id,
                        "symbol": symbol,
                        "qty": qty,
                        "side": -side_int,
                        "type": 4, # Stop Limit
                        "limitPrice": sl_trigger,
                        "stopPrice": sl_trigger,
                        "status": 6, # PENDING
                        "orderDateTime": datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S"),
                        "productType": product,
                        "message": "SL Pending (Paper Mode)",
                        "parentId": order_id
                    }
                    state.paper_orders.insert(0, sl_order)
                    
                target_price = 0.0
                if target_points > 0:
                    target_price = round(round((entry_price + target_points if side_int == 1 else entry_price - target_points) / 0.05) * 0.05, 2)
                    tgt_order = {
                        "id": tgt_order_id,
                        "symbol": symbol,
                        "qty": qty,
                        "side": -side_int,
                        "type": 1, # LIMIT
                        "limitPrice": target_price,
                        "stopPrice": 0,
                        "status": 6, # PENDING
                        "orderDateTime": datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S"),
                        "productType": product,
                        "message": "Target Pending (Paper Mode)",
                        "parentId": order_id
                    }
                    state.paper_orders.insert(0, tgt_order)
                    
                # 4. Update Position
                pos = next((p for p in state.paper_positions if p["symbol"] == symbol), None)
                if pos:
                    current_qty = pos["qty"] * pos["side"]
                    new_qty = qty * side_int
                    total_qty = current_qty + new_qty
                    
                    # Track realized profit/loss if exiting
                    if (pos["side"] != side_int) and pos["qty"] > 0:
                        closed_qty = min(pos["qty"], qty)
                        trade_pnl = round((entry_price - pos["entryPrice"]) * closed_qty * pos["side"], 2)
                        state.paper_funds["realizedPnl"] = round(state.paper_funds.get("realizedPnl", 0.0) + trade_pnl, 2)
                    
                    if total_qty == 0:
                        pos["qty"] = 0
                        pos["buyQty"] = 0
                        pos["sellQty"] = 0
                    else:
                        if total_qty > 0:
                            pos["side"] = 1
                            pos["qty"] = total_qty
                        else:
                            pos["side"] = -1
                            pos["qty"] = abs(total_qty)
                            
                        if (current_qty > 0 and new_qty > 0) or (current_qty < 0 and new_qty < 0):
                            pos["entryPrice"] = round(((pos["entryPrice"] * abs(current_qty)) + (entry_price * qty)) / abs(total_qty), 2)
                        
                        if side_int == 1:
                            pos["buyQty"] += qty
                        else:
                            pos["sellQty"] += qty
                else:
                    pos = {
                        "symbol": symbol,
                        "qty": qty,
                        "side": side_int,
                        "entryPrice": entry_price,
                        "buyQty": qty if side_int == 1 else 0,
                        "sellQty": qty if side_int == -1 else 0,
                        "buyAvg": entry_price if side_int == 1 else 0,
                        "sellAvg": entry_price if side_int == -1 else 0,
                        "pl": 0.0
                    }
                    state.paper_positions.append(pos)
                    
                # 5. Deduct/Add Funds
                order_cost = entry_price * qty
                if side_int == 1:
                    state.paper_funds["availableBalance"] -= order_cost
                else:
                    state.paper_funds["availableBalance"] += order_cost
                    
                if sl_points > 0:
                    sl_order_type = 4
                state.save()
                
                print(f"📄 [Paper Mode] Executed transaction for {symbol}: qty={qty}, price={entry_price}, side={side}")
                sl_msg = f" | SL placed at ₹{sl_trigger}" if sl_points > 0 else ""
                target_msg = f" | TGT placed at ₹{target_price}" if target_points > 0 else ""
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "sl_order_id": sl_order_id,
                    "tgt_order_id": tgt_order_id,
                    "sl_order_type": sl_order_type,
                    "message": f"Order placed at ₹{entry_price}{sl_msg}{target_msg}",
                }
        except Exception as e:
            print(f"Exception in paper trading place_order: {e}")

        if not self.client:
            return {"success": False, "message": "Not authenticated"}

        # If limit_price <= 0, auto-fetch live price and use LIMIT with buffer
        if limit_price <= 0:
            quote = self.get_quote(symbol)
            ltp = 0
            ask = 0
            bid = 0
            
            if quote:
                ltp = quote.get("lp", 0)
                ask = quote.get("ask", ltp)
                bid = quote.get("bid", ltp)
            
            if ltp <= 0:
                # Fallback: try historical candle
                try:
                    candles = self.get_historical(symbol, "1", 1)
                    if candles and len(candles) > 0:
                        ltp = candles[-1].get("close", 0)
                        ask = ltp
                        bid = ltp
                        logger.info(f"📊 Order price from candle fallback: ₹{ltp}")
                except Exception:
                    pass

            if ltp <= 0:
                logger.warning(f"⚠️ Cannot get any price for {symbol}. Order cannot be placed.")
                return {"success": False, "message": f"Could not fetch live price for {symbol} to calculate Limit Buffer. Is WebSocket active?"}

            if side_int == 1:  # BUY — use ask price + 1% buffer (wider for throttled markets)
                raw = (ask if ask > 0 else ltp) * 1.01
            else:  # SELL — use bid price - 1% buffer
                raw = (bid if bid > 0 else ltp) * 0.99

            # Round to tick size 0.05
            limit_price = round(round(raw / 0.05) * 0.05, 2)

            # Force LIMIT type (type=1) since algo apps don't allow true MARKET
            actual_type = 1  # LIMIT order
            print(f"📊 AUTOLIMIT: {symbol} LTP={ltp} Ask={ask} Bid={bid} → Limit={limit_price}")
        else:
            type_map = {"MARKET": 2, "LIMIT": 1, "STOP": 3, "STOPLIMIT": 4}
            actual_type = type_map.get(order_type.upper(), 1)
            # Round limit price to tick
            if limit_price > 0:
                limit_price = round(round(limit_price / 0.05) * 0.05, 2)
                
                # Fyers rejects actual_type=2 (MARKET) if limit_price > 0
                if actual_type == 2:
                    actual_type = 1
                    print(f"🔄 Forced order type to LIMIT (1) because limit_price > 0 ({limit_price})")
            elif actual_type in [1, 4]: # LIMIT or STOPLIMIT requires limitPrice > 0
                return {"success": False, "message": f"Order rejected: limit_price must be > 0 for {order_type} orders."}

        # Map product types (Fyers v3 dropped NRML, uses MARGIN for F&O)
        product_map = {"NRML": "MARGIN", "MIS": "INTRADAY"}
        mapped_product = product_map.get(product.upper(), product.upper())

        is_bo = False
        is_co = False
        if product.upper() == "CO":
            is_co = True
            mapped_product = "CO"
        elif sl_points > 0 and target_points > 0:
            is_bo = True
            mapped_product = "BO"

        stop_trigger = 0.0
        if is_co and sl_points > 0:
            if side_int == 1: # BUY
                stop_trigger = limit_price - sl_points
            else: # SELL
                stop_trigger = limit_price + sl_points
            stop_trigger = round(round(stop_trigger / 0.05) * 0.05, 2)

        order_data = {
            "symbol": symbol,
            "qty": qty,
            "type": actual_type,
            "side": side_int,
            "productType": mapped_product,
            "limitPrice": limit_price,
            "stopPrice": stop_price if actual_type in [3, 4] else 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }

        # Fyers v3 SDK requires 'stopLoss' field for CO orders (absolute point diff)
        if is_co and sl_points > 0:
            order_data["stopLoss"] = round(sl_points, 2)

        if is_bo:
            order_data["stopLoss"] = sl_points
            order_data["takeProfit"] = target_points

        try:
            print(f"📤 Placing order: {order_data}")
            resp = self.client.place_order(order_data)
            print(f"📥 Response: {resp}")

            # CO rejected → ABORT (do not place a naked entry). The old fallback bought the option
            # as INTRADAY and then tried a SEPARATE SELL stop-loss; on a long option that pending
            # short reserves ~₹1.2L naked-short margin, gets rejected, and leaves the position with
            # NO stop-loss. For options the SL must ride as the CO's own (margin-benefited) leg, so
            # if the CO can't be placed we place nothing rather than hold an unprotected trade.
            if not self._is_success(resp) and is_co:
                print(f"⚠️ CO Rejected — aborting order (no naked entry without SL): {resp.get('message')}")
                return {"success": False, "message": f"CO rejected, order aborted (no SL possible): {resp.get('message', 'unknown')}"}

            # Fallback if BO fails or is rejected
            if not self._is_success(resp) and is_bo:
                print(f"⚠️ BO Rejected. Falling back to INTRADAY with separate SL.")
                is_bo = False
                mapped_product = "INTRADAY"
                order_data["productType"] = mapped_product
                order_data.pop("stopLoss", None)
                order_data.pop("takeProfit", None)
                resp = self.client.place_order(order_data)
                print(f"📥 Fallback Response: {resp}")

            if not self._is_success(resp):
                return {"success": False, "message": resp.get("message", "Order failed")}

            main_order_id = resp.get("id", "")
            entry_price = limit_price

            sl_result = {"success": False}
            sl_msg = ""
            target_msg = ""

            if is_bo:
                sl_msg = f" | BO SL: {sl_points} pts"
                target_msg = f" | BO TGT: {target_points} pts"
                
                # Fetch leg IDs for BO trailing
                bo_legs = self._get_bo_legs(main_order_id)
                sl_result["order_id"] = bo_legs.get("sl_id", "")
                tgt_result = {"order_id": bo_legs.get("tgt_id", "")}
            elif is_co:
                sl_msg = f" | CO SL: {sl_points} pts"
                # Fetch leg ID for CO trailing (same parent logic as BO)
                co_legs = self._get_bo_legs(main_order_id)
                sl_result = {
                    "success": True if co_legs.get("sl_id") else False,
                    "order_id": co_legs.get("sl_id", ""),
                    "sl_price": stop_trigger
                }
            else:
                # === AUTO STOP LOSS ===
                if sl_points > 0:
                    sl_result = self._place_stop_loss(
                        symbol=symbol,
                        qty=qty,
                        entry_side=side.upper(),
                        entry_price=entry_price,
                        sl_points=sl_points,
                        product=mapped_product,
                    )

                if sl_result.get("success"):
                    sl_msg = f" | SL placed at ₹{sl_result.get('sl_price', '?')}"
                elif sl_points > 0:
                    sl_msg = f" | ⚠️ SL failed: {sl_result.get('message', 'unknown')}"

                # === AUTO TARGET ===
                if target_points > 0:
                    tgt_result = self._place_target(
                        symbol=symbol,
                        qty=qty,
                        entry_side=side.upper(),
                        entry_price=entry_price,
                        target_points=target_points,
                        product=mapped_product,
                    )
                    if tgt_result.get("success"):
                        target_msg = f" | TGT placed at ₹{tgt_result.get('target_price', '?')}"
                    else:
                        target_msg = f" | ⚠️ TGT failed: {tgt_result.get('message', 'unknown')}"

            if is_co:
                sl_order_type = 3
            elif is_bo:
                sl_order_type = 4
            elif sl_points > 0:
                sl_order_type = 4

            return {
                "success": True,
                "order_id": main_order_id,
                "sl_order_id": sl_result.get("order_id", ""),
                "tgt_order_id": tgt_result.get("order_id", "") if 'tgt_result' in locals() else "",
                "sl_order_type": sl_order_type,
                "message": f"Order placed at ₹{entry_price}{sl_msg}{target_msg}",
            }

        except Exception as e:
            print(f"❌ Place order exception: {e}")
            return {"success": False, "message": str(e)}

    def _place_stop_loss(self, symbol: str, qty: int, entry_side: str,
                         entry_price: float, sl_points: float = 12,
                         product: str = "MARGIN") -> Dict:
        """
        Place a stop loss order (SL-Limit, type=4).
        For BUY entry → SL is SELL at entry - sl_points
        For SELL entry → SL is BUY at entry + sl_points
        """
        if not self.client:
            return {"success": False, "message": "Not authenticated"}

        if entry_side == "BUY":
            sl_trigger = round(round((entry_price - sl_points) / 0.05) * 0.05, 2)
            sl_limit = round(round((entry_price - sl_points - 1) / 0.05) * 0.05, 2)
            sl_side = -1  # SELL
        else:
            sl_trigger = round(round((entry_price + sl_points) / 0.05) * 0.05, 2)
            sl_limit = round(round((entry_price + sl_points + 1) / 0.05) * 0.05, 2)
            sl_side = 1  # BUY

        sl_order = {
            "symbol": symbol,
            "qty": qty,
            "type": 4,  # Stop Limit (SL)
            "side": sl_side,
            "productType": product,
            "limitPrice": sl_limit,
            "stopPrice": sl_trigger,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }

        try:
            print(f"🛡️ Placing SL: trigger=₹{sl_trigger} limit=₹{sl_limit} | {sl_order}")
            resp = self.client.place_order(sl_order)
            print(f"🛡️ SL Response: {resp}")

            if self._is_success(resp):
                return {
                    "success": True,
                    "order_id": resp.get("id", ""),
                    "sl_price": sl_trigger,
                    "message": f"SL at ₹{sl_trigger}",
                }
            else:
                return {"success": False, "message": resp.get("message", "SL failed")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _place_target(self, symbol: str, qty: int, entry_side: str,
                      entry_price: float, target_points: float = 20.0,
                      product: str = "MARGIN") -> Dict:
        """
        Place a target order (LIMIT, type=1).
        """
        if not self.client:
            return {"success": False, "message": "Not authenticated"}

        if entry_side == "BUY":
            target_price = round(round((entry_price + target_points) / 0.05) * 0.05, 2)
            target_side = -1  # SELL
        else:
            target_price = round(round((entry_price - target_points) / 0.05) * 0.05, 2)
            target_side = 1  # BUY

        target_order = {
            "symbol": symbol,
            "qty": qty,
            "type": 1,  # LIMIT
            "side": target_side,
            "productType": product,
            "limitPrice": target_price,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }

        try:
            print(f"🎯 Placing TGT: limit=₹{target_price} | {target_order}")
            resp = self.client.place_order(target_order)
            print(f"🎯 TGT Response: {resp}")

            if self._is_success(resp):
                return {
                    "success": True,
                    "order_id": resp.get("id", ""),
                    "target_price": target_price,
                    "message": f"TGT at ₹{target_price}",
                }
            else:
                return {"success": False, "message": resp.get("message", "TGT failed")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _get_bo_legs(self, parent_id: str) -> Dict:
        """
        Scans order book to find SL and TGT leg IDs for a given BO parent ID.
        """
        import time
        try:
            # Give Fyers a moment to populate child orders in the book
            time.sleep(1.0)
            resp = self.client.orderbook()
            if resp.get("code") != 200:
                return {}

            orders = resp.get("orderBook", [])
            legs = {"sl_id": "", "tgt_id": ""}
            
            for o in orders:
                if o.get("parentId") == parent_id:
                    # Type 3 or 4 are SL legs
                    if o.get("type") in [3, 4]:
                        legs["sl_id"] = o.get("id")
                    # Type 1 is Target (Limit) leg
                    elif o.get("type") == 1:
                        legs["tgt_id"] = o.get("id")
            
            if legs["sl_id"]: print(f"🔍 Found BO Legs: SL={legs['sl_id']}, TGT={legs['tgt_id']}")
            return legs
        except Exception as e:
            print(f"❌ Error fetching BO legs: {e}")
            return {}

    def modify_order(self, order_id: str, order_type: int, limit_price: float = 0, stop_price: float = 0, qty: int = 0) -> Dict:
        """
        Modify an existing order.
        order_type: 1 for LIMIT (Target), 4 for SL-LIMIT (Stop Loss)
        """
        # Determine actual order type from orderbook/cache
        actual_type = order_type
        try:
            orders = self.get_orders()
            matching_order = next((o for o in orders if str(o.get("id")) == str(order_id)), None)
            if matching_order:
                actual_type = matching_order.get("type", order_type)
                print(f"🔍 Found order {order_id} in orderbook. Type: {actual_type}")
        except Exception as e:
            print(f"⚠️ Error fetching order type: {e}")

        if actual_type == 3:
            order_type = 3
            limit_price = 0  # Do not send limit price for Stop Market orders

        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                modified = False
                for o in state.paper_orders:
                    if o["id"] == order_id:
                        if limit_price > 0 and o.get("type") != 3:
                            o["limitPrice"] = round(round(limit_price / 0.05) * 0.05, 2)
                        if stop_price > 0:
                            o["stopPrice"] = round(round(stop_price / 0.05) * 0.05, 2)
                        if qty > 0:
                            o["qty"] = qty
                        o["message"] = "Order Modified (Paper Mode)"
                        modified = True
                        break
                if modified:
                    state.save()
                    return {"success": True, "message": f"Order {order_id} modified successfully (Paper Mode)"}
                return {"success": False, "message": f"Order {order_id} not found in paper orders"}
        except Exception as e:
            print(f"Exception in paper modify_order: {e}")

        if not self.client:
            return {"success": False, "message": "Not authenticated"}

        data = {"id": order_id, "type": order_type}
        if actual_type == 3:
            data["limitPrice"] = 0.0
        
        # Format prices to valid tick sizes if provided
        if limit_price > 0 and actual_type != 3:
            data["limitPrice"] = round(round(limit_price / 0.05) * 0.05, 2)
        if stop_price > 0:
            data["stopPrice"] = round(round(stop_price / 0.05) * 0.05, 2)
        if qty > 0:
            data["qty"] = qty

        try:
            print(f"🔄 Modifying Order {order_id}: {data}")
            resp = self.client.modify_order(data)
            print(f"🔄 Modify Response: {resp}")

            if self._is_success(resp):
                return {"success": True, "message": f"Order {order_id} modified successfully"}
            else:
                return {"success": False, "message": resp.get("message", "Modify failed")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an existing order."""
        try:
            import app
            state = app.get_user_state(self.user_id)
            if state.paper_trading:
                # Find order and mark cancelled
                for o in state.paper_orders:
                    if o["id"] == order_id:
                        o["status"] = 5 # CANCELLED
                        o["message"] = "Order Cancelled (Paper Mode)"
                        break
                state.save()
                return {"success": True, "message": f"Order {order_id} cancelled (Paper Mode)"}
        except Exception as e:
            print(f"Exception in paper cancel_order: {e}")

        if not self.client:
            return {"success": False, "message": "Not authenticated"}
        try:
            resp = self.client.cancel_order({"id": order_id})
            if self._is_success(resp):
                return {"success": True, "message": f"Order {order_id} cancelled"}
            return {"success": False, "message": resp.get("message", "Cancel failed")}
        except Exception as e:
            return {"success": False, "message": str(e)}

