"""Shared technical indicators for strategy modules."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Union

import pytz

IST = pytz.timezone("Asia/Kolkata")


def candle_ist_date(candle: Dict, tz=IST) -> Optional[datetime.date]:
    """Normalize Fyers candle timestamps (unix int/float or ISO string) to IST date."""
    ts = candle.get("timestamp", candle.get("t"))
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=pytz.UTC).astimezone(tz).date()
    if isinstance(ts, str):
        if ts.isdigit():
            return datetime.fromtimestamp(int(ts), tz=pytz.UTC).astimezone(tz).date()
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).date()
    return None


def calculate_ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    multiplier = 2 / (period + 1)
    ema = float(prices[0])
    for price in prices[1:]:
        ema = (float(price) - ema) * multiplier + ema
    return round(ema, 2)


def calculate_adx_di(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Dict[str, float]:
    """Wilder ADX with +DI / -DI. Returns zeros when insufficient bars."""
    n = len(closes)
    if n < period + 2:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

    tr_list: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []

    for i in range(1, n):
        high, low = float(highs[i]), float(lows[i])
        prev_high, prev_low, prev_close = float(highs[i - 1]), float(lows[i - 1]), float(closes[i - 1])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    if len(tr_list) < period:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

    atr = sum(tr_list[:period])
    spdm = sum(plus_dm[:period])
    smdm = sum(minus_dm[:period])

    dx_values: List[float] = []
    plus_di = minus_di = 0.0

    for i in range(period, len(tr_list)):
        if i > period:
            atr = atr - (atr / period) + tr_list[i]
            spdm = spdm - (spdm / period) + plus_dm[i]
            smdm = smdm - (smdm / period) + minus_dm[i]
        if atr <= 0:
            continue
        plus_di = 100.0 * spdm / atr
        minus_di = 100.0 * smdm / atr
        denom = plus_di + minus_di
        if denom > 0:
            dx_values.append(100.0 * abs(plus_di - minus_di) / denom)

    if not dx_values:
        return {"adx": 0.0, "plus_di": round(plus_di, 2), "minus_di": round(minus_di, 2)}

    if len(dx_values) < period:
        adx = dx_values[-1]
    else:
        adx = sum(dx_values[:period]) / period
        for dx in dx_values[period:]:
            adx = ((adx * (period - 1)) + dx) / period

    return {"adx": round(adx, 2), "plus_di": round(plus_di, 2), "minus_di": round(minus_di, 2)}


def calculate_adx(
    highs: List[Union[int, float]],
    lows: List[Union[int, float]],
    closes: List[Union[int, float]],
    period: int = 14,
) -> float:
    """Backward-compatible ADX-only helper."""
    return calculate_adx_di(
        [float(h) for h in highs],
        [float(l) for l in lows],
        [float(c) for c in closes],
        period,
    )["adx"]
