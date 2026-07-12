"""
Asset-class abstraction layer — multi-asset-expansion Phase 1 (foundation, NO new trading).

A config-driven registry so the SAME strategy engine can eventually run on any Indian
derivatives asset class (index / stock / commodity / currency options) by config, without
touching core logic per asset class.

Phase 1 contract: INDEX_OPTIONS is a VERBATIM transcription of today's live NIFTY constants,
and every default (no-arg) lookup returns byte-for-byte identical behavior. This is a live-money
app — do NOT change the INDEX_OPTIONS values; they define the live behavior.
Live sources: state.py is_market_open() (9:15-15:30) and app.py daily_hard_exit_scheduler() (15:14).
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

logger = logging.getLogger("ASSET_CLASSES")


@dataclass(frozen=True)
class AssetClass:
    name: str                          # "INDEX_OPTIONS", "STOCK_OPTIONS", "COMMODITY_OPTIONS", "CURRENCY_OPTIONS"
    exchange: str                      # "NSE", "MCX", "NSE_CD"
    session_open: Tuple[int, int]      # (hour, minute) market open
    session_close: Tuple[int, int]     # (hour, minute) market close
    symbol_prefix: str                 # "NSE:", "MCX:", "NSE_CD:" — source of truth for symbol construction
    lot_size_source: str               # "NSE_FO" | "MCX_COM" | "NSE_CD" — matches fetch_lot_sizes.py CSV keys
    expiry_cycle: str                  # descriptive only in Phase 1 (not enforced yet)
    volatility_measure: str            # "india_vix" | "atr" — drives get_volatility() dispatch
    hard_exit_time: Tuple[int, int]    # (hour, minute) safety-net square-off
    risk_config: dict = field(default_factory=dict)  # carried in Phase 1, wired into strategies in Phase 3
    # strike_interval: fallback ATM rounding step used by engine/strikes.py ONLY when the live option
    # chain does not supply "atm". INDEX_OPTIONS keeps the historical 50 (byte-identical to the old
    # hard-coded round(spot/50)*50). Assign an int here (not 50.0) so INDEX math stays integer-identical.
    strike_interval: float = 50


# INDEX_OPTIONS = today's live NIFTY config, VERBATIM. These must stay byte-for-byte identical to
# the literals in state.py is_market_open() (9:15-15:30) and app.py daily_hard_exit_scheduler() (15:14).
registry: Dict[str, AssetClass] = {
    "INDEX_OPTIONS": AssetClass(
        name="INDEX_OPTIONS", exchange="NSE",
        session_open=(9, 15), session_close=(15, 30),
        symbol_prefix="NSE:", lot_size_source="NSE_FO",
        expiry_cycle="weekly-thursday", volatility_measure="india_vix",
        hard_exit_time=(15, 14), risk_config={}, strike_interval=50,
    ),
    # ─── UNVERIFIED PLACEHOLDERS — not live-tested. Phase 3 RESEARCH starting points only. ───
    # No live caller uses these in Phase 1 (the broker/order path is index-only).
    "STOCK_OPTIONS": AssetClass(
        name="STOCK_OPTIONS", exchange="NSE",
        session_open=(9, 15), session_close=(15, 30),          # equity shares NSE hours
        symbol_prefix="NSE:", lot_size_source="NSE_FO",
        expiry_cycle="monthly-last-thursday", volatility_measure="atr",
        hard_exit_time=(15, 14), risk_config={}, strike_interval=50,
    ),
    "COMMODITY_OPTIONS": AssetClass(                            # MCX — PLACEHOLDER, unverified
        name="COMMODITY_OPTIONS", exchange="MCX",
        session_open=(9, 0), session_close=(23, 30),
        symbol_prefix="MCX:", lot_size_source="MCX_COM",
        expiry_cycle="monthly", volatility_measure="atr",
        hard_exit_time=(23, 20), risk_config={}, strike_interval=50,  # crude confirmed 50 from MCX_COM master
    ),
    "CURRENCY_OPTIONS": AssetClass(                            # NSE_CD — PLACEHOLDER, unverified
        name="CURRENCY_OPTIONS", exchange="NSE_CD",
        session_open=(9, 0), session_close=(17, 0),
        symbol_prefix="NSE_CD:", lot_size_source="NSE_CD",
        expiry_cycle="monthly", volatility_measure="atr",
        hard_exit_time=(16, 50), risk_config={}, strike_interval=0.25,  # USDINR placeholder, unverified
    ),
}

DEFAULT_ASSET_CLASS = "INDEX_OPTIONS"


def get_asset_class(name: Optional[str] = None) -> AssetClass:
    """Look up an asset class; unknown/None -> the default (INDEX_OPTIONS)."""
    return registry.get(name or DEFAULT_ASSET_CLASS, registry[DEFAULT_ASSET_CLASS])


def register(ac: "AssetClass") -> None:
    """Register (or replace) an asset class by name. Used by asset_configs/* modules to add
    specialized entries (e.g. CRUDE_OIL_OPTIONS) without editing this file. Additive: registering
    a new key never affects INDEX_OPTIONS or any existing lookup."""
    registry[ac.name] = ac
    logger.info(f"registered asset class: {ac.name} ({ac.exchange}, {ac.symbol_prefix})")


def build_symbol(asset_class: str, instrument: str) -> str:
    """Prefix an instrument with its asset class's exchange prefix.
    build_symbol("INDEX_OPTIONS", "NIFTY50-INDEX") == "NSE:NIFTY50-INDEX" (byte-identical to today)."""
    return f"{get_asset_class(asset_class).symbol_prefix}{instrument}"


def get_volatility(asset_class: str = DEFAULT_ASSET_CLASS, symbol: str = "NSE:INDIAVIX-INDEX") -> Optional[float]:
    """Volatility for an asset class.
    - india_vix -> transparent passthrough to the EXISTING VIX path (market cache, then live quote).
    - atr       -> stub only in Phase 1 (no commodity trading yet); logs and returns None.
    Additive: existing VIX call sites are intentionally NOT migrated to this in Phase 1 (zero-regression)."""
    ac = get_asset_class(asset_class)
    if ac.volatility_measure == "india_vix":
        try:
            import state as _state
            if hasattr(_state, "get_user_cache"):
                v = (_state.get_user_cache("0") or {}).get("vix", 0)
                if v:
                    return float(v)
            import app as _app
            client = _app.USER_CONTEXTS.get(1)
            if client is not None:
                q = client.get_quote(symbol)
                lp = (q or {}).get("lp", 0)
                return float(lp) if lp else None
        except Exception as e:
            logger.warning(f"get_volatility india_vix passthrough failed: {e}")
        return None
    # atr and anything else: not implemented in Phase 1.
    logger.info(f"ATR volatility not yet implemented — asset_class={asset_class}")
    return None
