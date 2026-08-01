"""Unit: paper automation toggle does not require Fyers auth."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_toggle_automation_paper_skips_fyers_auth():
    from app import toggle_automation

    state = SimpleNamespace(
        paper_trading=True,
        square_off_in_progress=False,
        hard_exit_triggered=False,
        automation_enabled=False,
        save=lambda: None,
    )
    client = SimpleNamespace(user_id=1, is_authenticated=AsyncMock(return_value=False))
    req = SimpleNamespace()
    req.json = AsyncMock(return_value={"enabled": True})

    with patch("app.get_current_client", AsyncMock(return_value=client)):
        with patch("app.get_user_state", return_value=state):
            with patch("app.api_queue") as aq:
                aq.enqueue = AsyncMock()
                result = await toggle_automation(req)

    assert result["success"] is True
    assert result["enabled"] is True
    aq.enqueue.assert_not_called()
