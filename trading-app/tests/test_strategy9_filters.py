"""Unit tests for Strategy 9 shared gates."""
from datetime import datetime

import pytz

from engine.strategy9_filters import (
    MIN_ADX_15M,
    adx_gate_passes,
    session_allows_entry,
)

IST = pytz.timezone("Asia/Kolkata")


def _ist(h: int, m: int) -> datetime:
    return IST.localize(datetime(2026, 7, 31, h, m))


def test_session_allows_entry_window():
    assert session_allows_entry(_ist(10, 0)) is True
    assert session_allows_entry(_ist(13, 55)) is True
    assert session_allows_entry(_ist(9, 45)) is False
    assert session_allows_entry(_ist(14, 0)) is False


def test_adx_gate_passes():
    assert adx_gate_passes(MIN_ADX_15M) is True
    assert adx_gate_passes(MIN_ADX_15M - 0.1) is False
    assert adx_gate_passes(30.0) is True
