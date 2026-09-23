"""Shared Strategy 9 gates — live evaluation and rules-only backtest."""
from __future__ import annotations

from datetime import datetime
from typing import Union

import pytz

IST = pytz.timezone("Asia/Kolkata")

MIN_ADX_15M = 25.0
SESSION_START_HOUR = 10
SESSION_START_MINUTE = 0
SESSION_END_HOUR = 13
SESSION_END_MINUTE = 30  # cut late-day chop (was 14:00) toward 55% WR quality


def _as_ist(dt: Union[datetime, None]) -> datetime:
    if dt is None:
        dt = datetime.now(IST)
    if dt.tzinfo is None:
        return IST.localize(dt)
    return dt.astimezone(IST)


def session_allows_entry(dt: Union[datetime, None] = None) -> bool:
    """NSE index/equity: allow new entries 10:00–13:30 IST (exclusive at 13:30)."""
    t = _as_ist(dt)
    start_mins = SESSION_START_HOUR * 60 + SESSION_START_MINUTE
    end_mins = SESSION_END_HOUR * 60 + SESSION_END_MINUTE
    now_mins = t.hour * 60 + t.minute
    return start_mins <= now_mins < end_mins


def adx_gate_passes(adx_15m: float) -> bool:
    return adx_15m >= MIN_ADX_15M
