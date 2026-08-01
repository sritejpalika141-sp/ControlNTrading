"""Phase-1 registry smoke tests (offline — no Fyers/MCX required)."""
from engine.asset_classes import get_asset_class, build_symbol


def test_index_options_registry_defaults():
    ac = get_asset_class("INDEX_OPTIONS")
    assert ac.name == "INDEX_OPTIONS"
    assert ac.strike_interval == 50
    assert ac.session_open == (9, 15)
    assert ac.hard_exit_time == (15, 14)
    assert ac.symbol_prefix == "NSE:"


def test_build_symbol_nifty_shape():
    sym = build_symbol("INDEX_OPTIONS", "NIFTY50-INDEX")
    assert sym == "NSE:NIFTY50-INDEX"
