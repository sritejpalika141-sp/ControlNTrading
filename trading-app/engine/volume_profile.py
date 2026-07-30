"""
Fixed Range Volume Profile (FRVP) Calculation Module.

Calculates Volume-at-Price distribution over a fixed range of candles:
- Point of Control (POC): Price level with maximum traded volume.
- Value Area High (VAH) & Value Area Low (VAL): 70% volume containment boundaries.
- High Volume Nodes (HVNs): Heavy institutional fair-value / support-resistance zones.
- Low Volume Nodes (LVNs): Thin volume / liquidity vacuum acceleration zones.
"""
from typing import List, Dict, Any, Tuple
import numpy as np


def compute_volume_profile(candles: List[Dict[str, Any]], num_bins: int = 40) -> Dict[str, Any]:
    """
    Computes Fixed Range Volume Profile from 5-minute / 1-minute candles.
    Returns {poc, vah, val, hvns, lvns, profile_bins}
    """
    if not candles or len(candles) < 5:
        return {
            "poc": 0.0, "vah": 0.0, "val": 0.0,
            "hvns": [], "lvns": [], "profile_bins": []
        }

    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    volumes = [float(c.get("volume", c.get("v", 1.0))) for c in candles]

    min_price = min(lows)
    max_price = max(highs)

    if max_price <= min_price:
        return {
            "poc": min_price, "vah": max_price, "val": min_price,
            "hvns": [], "lvns": [], "profile_bins": []
        }

    # Generate price bins
    bin_edges = np.linspace(min_price, max_price, num_bins + 1)
    bin_volumes = np.zeros(num_bins)

    # Distribute volume into price bins based on candle high-low overlap
    for h, l, v in zip(highs, lows, volumes):
        if h == l:
            idx = min(num_bins - 1, int((h - min_price) / (max_price - min_price) * num_bins))
            bin_volumes[idx] += v
        else:
            span = h - l
            for i in range(num_bins):
                b_low = bin_edges[i]
                b_high = bin_edges[i + 1]
                overlap = max(0.0, min(h, b_high) - max(l, b_low))
                if overlap > 0:
                    bin_volumes[i] += v * (overlap / span)

    # Point of Control (POC)
    poc_idx = int(np.argmax(bin_volumes))
    poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2.0

    # High Volume Nodes (HVN) & Low Volume Nodes (LVN)
    vol_70th = np.percentile(bin_volumes, 70) if np.max(bin_volumes) > 0 else 0
    vol_30th = np.percentile(bin_volumes, 30) if np.max(bin_volumes) > 0 else 0

    hvns = []
    lvns = []
    bins_data = []

    for i in range(num_bins):
        mid_p = (bin_edges[i] + bin_edges[i + 1]) / 2.0
        vol_val = float(bin_volumes[i])
        node_type = "NORMAL"
        if vol_val >= vol_70th and vol_val > 0:
            node_type = "HVN"
            hvns.append({"price": round(mid_p, 2), "volume": round(vol_val, 1)})
        elif vol_val <= vol_30th:
            node_type = "LVN"
            lvns.append({"price": round(mid_p, 2), "volume": round(vol_val, 1)})

        bins_data.append({
            "bin_bottom": round(float(bin_edges[i]), 2),
            "bin_top": round(float(bin_edges[i + 1]), 2),
            "mid_price": round(mid_p, 2),
            "volume": round(vol_val, 1),
            "type": node_type
        })

    # Value Area (70% Volume Area calculation)
    total_volume = np.sum(bin_volumes)
    target_va_vol = total_volume * 0.70

    current_va_vol = bin_volumes[poc_idx]
    low_idx = poc_idx
    high_idx = poc_idx

    while current_va_vol < target_va_vol and (low_idx > 0 or high_idx < num_bins - 1):
        next_low_vol = bin_volumes[low_idx - 1] if low_idx > 0 else -1
        next_high_vol = bin_volumes[high_idx + 1] if high_idx < num_bins - 1 else -1

        if next_high_vol >= next_low_vol and next_high_vol >= 0:
            high_idx += 1
            current_va_vol += next_high_vol
        elif next_low_vol > next_high_vol and next_low_vol >= 0:
            low_idx -= 1
            current_va_vol += next_low_vol
        else:
            break

    val = (bin_edges[low_idx] + bin_edges[low_idx + 1]) / 2.0
    vah = (bin_edges[high_idx] + bin_edges[high_idx + 1]) / 2.0

    return {
        "poc": round(poc_price, 2),
        "vah": round(vah, 2),
        "val": round(val, 2),
        "hvns": hvns,
        "lvns": lvns,
        "profile_bins": bins_data
    }
