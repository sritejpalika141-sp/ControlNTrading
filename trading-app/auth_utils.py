"""
Session cookie signing + verification (Phase 1 security remediation, Item 1).

Pure, import-light logic so it can be unit-tested without importing the full app.py.

The `user_id` session cookie used to be the raw integer user id, which any client could
forge (e.g. `user_id=1` to impersonate the admin). This module signs the cookie value with
`itsdangerous.URLSafeTimedSerializer` so it is unforgeable, while accepting the old raw-integer
cookie for a bounded grace window so already-logged-in live traders are not mass-logged-out on
deploy day.
"""
import os
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# --- OAuth state nonce (Phase 2 Item A2) ---------------------------------
# The Fyers OAuth `state` used to be the raw `user_id`, so anyone who observed/guessed a
# user_id could complete another user's callback and receive their session cookie. We now
# issue a signed, single-use, short-TTL nonce keyed to the initiating user and validate it
# on callback. Single-use is enforced in-memory (safe for this single-process Uvicorn
# deployment). Signature + TTL are enforced by a dedicated URLSafeTimedSerializer salt.
_OAUTH_STATE_SALT = "fyers-oauth-state"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes: long enough for a login, short enough to limit replay
_oauth_serializer: Optional[URLSafeTimedSerializer] = None
# nonce -> expiry-epoch of nonces already consumed (used-once guard). Pruned lazily.
_USED_OAUTH_NONCES: Dict[str, float] = {}

_MODULE_DIR = Path(__file__).resolve().parent
_ENV_PATH = _MODULE_DIR / ".env"

# Cookie signing constants.
_COOKIE_SALT = "user-id-cookie"
# Signed cookies remain valid for 30 days (matches the existing set_cookie max_age).
SIGNED_MAX_AGE = 86400 * 30

# Grace period: during this window a legacy raw-integer cookie is still honored so that
# users already logged in at deploy time are not surprise-logged-out. After the cutoff,
# only signed cookies are accepted. Chosen over a forced mass re-login (see plan Item A1).
# Deploy target 04-07-26; 7-day grace window.
SESSION_MIGRATION_CUTOFF = datetime(2026, 7, 11)

_serializer: Optional[URLSafeTimedSerializer] = None


def _persist_secret_key(key: str) -> None:
    """Write SECRET_KEY back to .env (mirrors ENCRYPTION_KEY discipline in models.get_cipher)."""
    try:
        existing_lines = []
        if os.path.exists(_ENV_PATH):
            with open(_ENV_PATH, "r") as f:
                existing_lines = f.readlines()
        new_lines = []
        found = False
        for line in existing_lines:
            if line.strip().startswith("SECRET_KEY="):
                new_lines.append(f"SECRET_KEY={key}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"SECRET_KEY={key}\n")
        with open(_ENV_PATH, "w") as f:
            f.writelines(new_lines)
        print(f"🔑 New SECRET_KEY generated and saved to {_ENV_PATH}")
    except Exception as e:
        print(f"⚠️ Error writing SECRET_KEY to .env: {e}")


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        secret = os.getenv("SECRET_KEY")
        if not secret:
            # Generate a strong random key once and persist it, same discipline as ENCRYPTION_KEY.
            secret = os.urandom(32).hex()
            _persist_secret_key(secret)
            os.environ["SECRET_KEY"] = secret
        _serializer = URLSafeTimedSerializer(secret, salt=_COOKIE_SALT)
    return _serializer


def sign_user_id(user_id) -> str:
    """Return a signed, tamper-proof cookie value encoding the given user id."""
    return _get_serializer().dumps(int(user_id))


def resolve_user_id_from_cookie(raw_cookie: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    """
    Resolve a trusted integer user id from a raw cookie value.

    Returns:
      - the signed id when the cookie is a valid, unexpired signed token
      - the legacy raw integer when signature verification fails BUT the migration grace
        period is still active and the value is a plain digit string
      - None otherwise (unauthenticated / forged / expired-after-grace)

    Note: a legacy raw cookie is intentionally NOT re-signed here — the user gets a signed
    cookie only on their next real login, so the raw cookie expires naturally.
    """
    if not raw_cookie:
        return None

    # 1. Preferred path: a valid signed token.
    try:
        uid = _get_serializer().loads(raw_cookie, max_age=SIGNED_MAX_AGE)
        return int(uid)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        pass

    # 2. Grace-period fallback: honor a legacy raw-integer cookie until the cutoff.
    if now is None:
        now = datetime.now()
    if now < SESSION_MIGRATION_CUTOFF and isinstance(raw_cookie, str) and raw_cookie.isdigit():
        return int(raw_cookie)

    return None


def _get_oauth_serializer() -> URLSafeTimedSerializer:
    global _oauth_serializer
    if _oauth_serializer is None:
        # Reuse the same SECRET_KEY as the cookie signer (generated/persisted by _get_serializer),
        # but with a distinct salt so an OAuth-state token can never be substituted for a cookie.
        _get_serializer()  # ensure SECRET_KEY is present/persisted
        secret = os.getenv("SECRET_KEY")
        _oauth_serializer = URLSafeTimedSerializer(secret, salt=_OAUTH_STATE_SALT)
    return _oauth_serializer


def generate_oauth_state(user_id) -> str:
    """Return a signed, single-use, short-TTL OAuth `state` nonce bound to the initiating user."""
    nonce = os.urandom(16).hex()
    return _get_oauth_serializer().dumps({"uid": int(user_id), "nonce": nonce})


def consume_oauth_state(state: Optional[str], now: Optional[float] = None) -> Optional[int]:
    """
    Validate an OAuth `state` value and return the bound integer user id, or None if invalid.

    Rejects when: state is missing, signature is bad/forged, the token is older than
    OAUTH_STATE_TTL_SECONDS, or the nonce has already been consumed (replay). On success the
    nonce is marked used so a second presentation of the same valid state fails.
    """
    if not state:
        return None
    if now is None:
        now = _time.time()

    # Prune expired used-nonce records so the map does not grow unbounded.
    expired = [n for n, exp in _USED_OAUTH_NONCES.items() if exp < now]
    for n in expired:
        _USED_OAUTH_NONCES.pop(n, None)

    try:
        data = _get_oauth_serializer().loads(state, max_age=OAUTH_STATE_TTL_SECONDS)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    nonce = data.get("nonce")
    uid = data.get("uid")
    if not nonce or uid is None:
        return None
    if nonce in _USED_OAUTH_NONCES:
        return None  # replay of an already-consumed nonce

    _USED_OAUTH_NONCES[nonce] = now + OAUTH_STATE_TTL_SECONDS
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Login rate-limiting (Phase 1 Item C2)
#
# In-memory failed-attempt tracking, keyed by username (not IP, which may be shared/proxied).
# Safe for this single-process Uvicorn deployment (no `workers=` arg). After 5 failed attempts
# within a 15-minute window, the account is locked and the password is not even checked (avoids
# a timing oracle). Counter resets on successful login.
# ---------------------------------------------------------------------------
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60

_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}


def _prune_attempts(username: str, now: float) -> List[float]:
    recent = [t for t in _LOGIN_ATTEMPTS.get(username, []) if now - t < LOGIN_LOCKOUT_WINDOW_SECONDS]
    if recent:
        _LOGIN_ATTEMPTS[username] = recent
    else:
        _LOGIN_ATTEMPTS.pop(username, None)
    return recent


def check_login_locked(username: str, now: Optional[float] = None) -> bool:
    """True if this username has reached the failed-attempt limit within the window."""
    if not username:
        return False
    if now is None:
        now = _time.time()
    return len(_prune_attempts(username, now)) >= LOGIN_MAX_ATTEMPTS


def register_failed_login(username: str, now: Optional[float] = None) -> None:
    """Record one failed login attempt for this username."""
    if not username:
        return
    if now is None:
        now = _time.time()
    recent = _prune_attempts(username, now)
    recent.append(now)
    _LOGIN_ATTEMPTS[username] = recent


def reset_login_attempts(username: str) -> None:
    """Clear the failed-attempt counter (called on successful login)."""
    if username:
        _LOGIN_ATTEMPTS.pop(username, None)
