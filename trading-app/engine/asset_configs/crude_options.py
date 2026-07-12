"""
CRUDE_OIL_OPTIONS — MCX Crude Oil options asset-class config (multi-asset Phase 2, proof commodity).

Importing this module registers CRUDE_OIL_OPTIONS into engine.asset_classes.registry. This is
PAPER-first scaffolding: registering the config does NOT place any order and does not touch the
NIFTY path. The live crude order path is wired only after a market-open MCX data probe passes.

Symbol format (confirmed from the Fyers MCX_COM master, not guessed):
    options : MCX:CRUDEOIL{YY}{MON}{STRIKE}{CE|PE}   e.g. MCX:CRUDEOIL26JUL7600CE
    futures : MCX:CRUDEOIL{YY}{MON}FUT                e.g. MCX:CRUDEOIL26JULFUT
    strike interval: 50 (confirmed from the master's strike ladder)

⚠️ PROVISIONAL values (marked below) are first-cut and MUST be confirmed during the paper-validation
window before any live-small enablement — they are NOT asserted as final:
  - risk multipliers (sl/target) — pending the historical-volatility comparison in the phase report
  - liquidity thresholds (min_oi / min_volume / max_spread_pct) — crude's book is thinner than NIFTY;
    these are conservative first cuts, to be tuned against observed crude option-chain depth
  - lot_size is read live from the MCX_COM master at runtime (NOT hard-coded here)
"""
from engine.asset_classes import AssetClass, register

CRUDE_OIL_OPTIONS = AssetClass(
    name="CRUDE_OIL_OPTIONS",
    exchange="MCX",
    session_open=(9, 0),          # MCX crude session ~09:00
    session_close=(23, 30),       # extends to ~23:30 IST (vs NIFTY 15:30)
    symbol_prefix="MCX:CRUDEOIL",  # build_symbol(...) -> MCX:CRUDEOIL26JUL7600CE
    lot_size_source="MCX_COM",    # lot read live from the MCX_COM master, never hard-coded
    expiry_cycle="monthly",       # crude is monthly, not weekly like NIFTY
    volatility_measure="atr",     # no india_vix analogue for crude
    hard_exit_time=(23, 20),      # square-off before session close (per-asset, NOT NIFTY's 15:14)
    strike_interval=50,           # confirmed from MCX_COM strike ladder
    risk_config={
        # --- PROVISIONAL risk tuning (confirm in paper-validation window) ---
        "sl_multiplier": 1.75,        # crude SL distance ~1.75x the NIFTY SL% (crude ~2-4% intraday vs <1%)
        "target_multiplier": 1.75,
        "max_lots": 1,                # hard position-size cap for the first live-small period (code-enforced later)
        # --- Liquidity guard (crude-specific, thinner book than NIFTY) ---
        "liquidity_guard_required": True,
        "min_oi": 200,                # PROVISIONAL: minimum open interest
        "min_volume": 100,            # PROVISIONAL: minimum traded volume
        "max_spread_pct": 3.0,        # PROVISIONAL: max bid-ask spread as % of ask
        # --- Strategy time windows (IST; PROVISIONAL, confirm exact conventions) ---
        # EIA weekly petroleum report: Wednesdays ~10:30 AM ET -> ~20:00 IST (summer). Window is a
        # cushion around that; NOT the plan's guessed 22:30. Confirm against the EIA schedule.
        "eia_window": ((19, 30), (21, 0)),   # ((start_h,start_m),(end_h,end_m)) Wednesday only
        "evening_session_start": (17, 0),    # evening momentum active after ~17:00 IST
    },
)

register(CRUDE_OIL_OPTIONS)
