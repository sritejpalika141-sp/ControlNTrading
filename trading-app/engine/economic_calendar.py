"""
Hardcoded high-impact India market event blackout dates for intraday strategies.

Extend this list before RBI policy, Union Budget, and known FOMC overlap sessions.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Set

import pytz

IST = pytz.timezone("Asia/Kolkata")

# YYYY-MM-DD — add dates as they are scheduled
BLACKOUT_DATES: Set[str] = {
    # Union Budget 2026 (illustrative — update when official date confirmed)
    "2026-02-01",
    # RBI MPC policy dates 2026 (illustrative placeholders)
    "2026-02-07",
    "2026-04-09",
    "2026-06-06",
    "2026-08-08",
    "2026-10-09",
    "2026-12-04",
}


def _normalize_day(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.astimezone(IST).date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return datetime.now(IST).date().isoformat()


def is_blackout_day(day=None) -> bool:
    """True when intraday breakout strategies should stand down."""
    return _normalize_day(day) in BLACKOUT_DATES


def check_no_economic_events(day=None, extra_blackouts: Iterable[str] = ()) -> bool:
    """Safe to trade when not on a blackout day."""
    d = _normalize_day(day)
    if d in BLACKOUT_DATES:
        return False
    if d in {b[:10] for b in extra_blackouts}:
        return False
    return True
