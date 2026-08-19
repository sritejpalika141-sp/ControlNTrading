"""Tests for NewsWorker scrip injection gates and active-user fan-out."""
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.news_worker import NewsWorker  # noqa: E402


def test_inject_skips_when_fyers_disconnected():
    nw = NewsWorker()
    with patch.object(nw, "_get_validation_client", return_value=None):
        assert nw._inject_asset("RELIANCE", True, "equity") is None
    assert "no_authenticated_fyers" in nw.last_summary["last_skip_reason"]


def test_inject_skips_outside_equity_window():
    nw = NewsWorker()
    assert nw._inject_asset("RELIANCE", False, "equity") is None
    assert nw.last_summary["last_skip_reason"] == "equity_outside_window"


def test_inject_adds_to_all_active_users():
    nw = NewsWorker()
    client = MagicMock()
    client.get_quote.return_value = {"lp": 2500.0}

    states = {}

    def fake_get_user_state(uid):
        if uid not in states:
            st = MagicMock()
            st.active_symbols = ["NSE:NIFTY50-INDEX"]
            st.enabled_symbols = ["NSE:NIFTY50-INDEX"]
            st.agent_added_symbols = []
            st.add_symbol = MagicMock(
                side_effect=lambda sym, enable=False, by_agent=False: (
                    st.active_symbols.append(sym),
                    st.enabled_symbols.append(sym) if enable else None,
                    st.agent_added_symbols.append(sym) if by_agent else None,
                )
            )
            states[uid] = st
        return states[uid]

    with patch.object(nw, "_get_validation_client", return_value=client), \
         patch.object(nw, "_active_user_ids_for_inject", return_value=[1, 3]), \
         patch("state.get_user_state", side_effect=fake_get_user_state):
        # _inject_asset imports get_user_state inside the function
        with patch("workers.news_worker.get_user_state", create=True):
            pass
        with patch.dict(sys.modules):
            import state as state_mod
            with patch.object(state_mod, "get_user_state", side_effect=fake_get_user_state):
                sym = nw._inject_asset("RELIANCE", True, "equity")

    assert sym == "NSE:RELIANCE-EQ"
    assert "NSE:RELIANCE-EQ" in nw.last_summary["last_injected"]
    assert 1 in states and 3 in states
    assert states[1].add_symbol.called
    assert states[3].add_symbol.called


def test_resolve_commodity_not_nse_equity():
    nw = NewsWorker()
    assert nw._resolve_symbol("CRUDEOIL") == "MCX:CRUDEOIL"
    assert nw._resolve_symbol("GOLD") == "MCX:GOLD"
    assert nw._resolve_symbol("INFY") == "NSE:INFY-EQ"


def test_schedule_refresh_after_auth_creates_task():
    nw = NewsWorker()
    created = []

    class _Loop:
        def create_task(self, coro):
            created.append(coro)
            coro.close()  # prevent "never awaited" warning
            return MagicMock()

    with patch("asyncio.get_running_loop", return_value=_Loop()):
        nw.schedule_refresh_after_auth("test")
    assert len(created) == 1
