"""Shared profitability gates targeting ≥55% win-rate quality.

Hindsight optimizer writes these knobs into swarm_agent_configs.config_json;
this module is the LIVE consumer so learning actually affects entries.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("PROFITABILITY_GATES")

# Owner target — strategies below this live WR (with enough sample) get shadowed.
TARGET_WIN_RATE_PCT = 55.0
MIN_TRADES_FOR_WR_SHADOW = 10

# Defaults (match hindsight_optimizer_worker.DEFAULTS)
DEFAULT_ENTRY_CONFIDENCE_FLOOR = 70  # raised from 60 toward 55% WR quality
DEFAULT_CHASE_BUFFER_PCT = 1.0       # tighter than 0.8 — block nearer the high
DEFAULT_STRIKE_OFFSET = 0

MAX_CHASE_BUFFER_PCT = 2.0
MIN_CHASE_BUFFER_PCT = 0.5


async def load_strategy_tunables(strategy_name: str) -> Dict[str, Any]:
    """Best-effort load of hindsight / nightly knobs for a strategy."""
    out = {
        "entry_confidence_floor": DEFAULT_ENTRY_CONFIDENCE_FLOOR,
        "chase_buffer_pct": DEFAULT_CHASE_BUFFER_PCT,
        "strike_offset": DEFAULT_STRIKE_OFFSET,
    }
    if not strategy_name:
        return out
    try:
        from models import Database
        cfg = await Database.get_agent_config(strategy_name)
        if not cfg:
            return out
        conf = cfg.get("config_json") or {}
        if isinstance(conf, str):
            import json
            try:
                conf = json.loads(conf) if conf else {}
            except Exception:
                conf = {}
        if not isinstance(conf, dict):
            return out
        if conf.get("entry_confidence_floor") is not None:
            try:
                out["entry_confidence_floor"] = max(
                    50, min(90, float(conf["entry_confidence_floor"]))
                )
            except Exception:
                pass
        if conf.get("chase_buffer_pct") is not None:
            try:
                out["chase_buffer_pct"] = max(
                    MIN_CHASE_BUFFER_PCT,
                    min(MAX_CHASE_BUFFER_PCT, float(conf["chase_buffer_pct"])),
                )
            except Exception:
                pass
        if conf.get("strike_offset") is not None:
            try:
                out["strike_offset"] = max(0, min(2, int(conf["strike_offset"])))
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"load_strategy_tunables({strategy_name}) failed: {e}")
    return out


def passes_confidence_floor(sig: Dict, floor: float) -> Tuple[bool, str]:
    """Reject weak signals below the (hindsight-tuned) confidence floor."""
    try:
        conf = float(sig.get("confidence") or 0)
    except Exception:
        conf = 0.0
    if conf <= 0:
        # Some strategies omit confidence — allow but note
        return True, ""
    if conf < float(floor):
        return False, f"confidence {conf:.0f} < floor {floor:.0f}"
    return True, ""


def chase_threshold_multiplier(chase_buffer_pct: float) -> float:
    """Convert chase_buffer_pct (e.g. 1.0 = 1%) into entry/high ratio threshold.
    Entry >= local_high * multiplier  ⇒ chase.
    1.0% buffer ⇒ 0.990; 0.8% ⇒ 0.992.
    """
    pct = max(MIN_CHASE_BUFFER_PCT, min(MAX_CHASE_BUFFER_PCT, float(chase_buffer_pct or DEFAULT_CHASE_BUFFER_PCT)))
    return 1.0 - (pct / 100.0)
