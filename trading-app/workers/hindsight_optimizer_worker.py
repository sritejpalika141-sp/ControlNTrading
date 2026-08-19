"""
Hindsight Performance Auto-Optimizer Agent.

After each closed trade (from the executed-trades ledger), auto-tunes per-strategy
swarm hyperparameters that affect strike selection / entry aggressiveness:

  - entry_confidence_floor  (raise after losses, ease after wins)
  - strike_offset           (0=ATM, +1/+2 = ITM for longs — more premium, less gamma wipe)
  - chase_buffer_pct        (anti-chase tightness)

STRICT: losing trades drive tighter floors; wins can relax slightly but never below defaults.
Changes are written into swarm_agent_configs.config_json and logged to swarm_learning_logs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Set

import pytz

logger = logging.getLogger("HINDSIGHT_OPTIMIZER")
IST = pytz.timezone("Asia/Kolkata")

DEFAULTS = {
    "entry_confidence_floor": 60,
    "strike_offset": 0,
    "chase_buffer_pct": 0.8,
}
MIN_FLOOR = 50
MAX_FLOOR = 90
MAX_STRIKE_OFFSET = 2


class HindsightOptimizerWorker:
    def __init__(self, interval_seconds: int = 45):
        self.interval_seconds = interval_seconds
        self._seen_ids: Set[int] = set()
        self._bootstrapped = False

    async def run(self):
        logger.info("📊 Hindsight Performance Auto-Optimizer Agent started.")
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Hindsight Optimizer error: {e}")
            await asyncio.sleep(self.interval_seconds)

    async def _tick(self):
        from models import Database

        rows = await Database.get_executed_trades(days=3, limit=80)
        closed = [r for r in rows if str(r.get("status") or "").upper() == "CLOSED"]
        if not closed:
            return

        # First pass: mark existing closes as seen so we don't rewrite history on restart.
        if not self._bootstrapped:
            for r in closed:
                rid = r.get("id")
                if rid is not None:
                    self._seen_ids.add(int(rid))
            self._bootstrapped = True
            logger.info(f"Hindsight: bootstrapped {len(self._seen_ids)} recent closed trades (no retro-tune).")
            return

        new_closes = []
        for r in closed:
            rid = r.get("id")
            if rid is None:
                continue
            rid = int(rid)
            if rid in self._seen_ids:
                continue
            self._seen_ids.add(rid)
            new_closes.append(r)

        # Bound memory
        if len(self._seen_ids) > 500:
            self._seen_ids = set(list(self._seen_ids)[-400:])

        for trade in new_closes:
            await self._learn_from_trade(trade)

    async def _learn_from_trade(self, trade: Dict[str, Any]):
        from models import Database

        strat = (trade.get("strategy_name") or "").strip()
        if not strat:
            return
        try:
            pnl = float(trade.get("pnl") or 0)
        except Exception:
            return

        cfg_row = await Database.get_agent_config(strat)
        if cfg_row is None:
            # Create a minimal config row so hindsight has somewhere to write.
            await Database.update_agent_config(
                strategy_name=strat,
                config_dict=dict(DEFAULTS),
                win_rate=0.0,
                total_trades=0,
                winning_trades=0,
                status="APPROVED",
                is_paper_trading=1,
            )
            cfg_row = await Database.get_agent_config(strat)
            if cfg_row is None:
                return

        conf = cfg_row.get("config_json") or {}
        if isinstance(conf, str):
            try:
                conf = json.loads(conf) if conf else {}
            except Exception:
                conf = {}
        if not isinstance(conf, dict):
            conf = {}

        old = {
            "entry_confidence_floor": float(conf.get("entry_confidence_floor", DEFAULTS["entry_confidence_floor"])),
            "strike_offset": int(conf.get("strike_offset", DEFAULTS["strike_offset"])),
            "chase_buffer_pct": float(conf.get("chase_buffer_pct", DEFAULTS["chase_buffer_pct"])),
        }
        new = dict(old)
        reason_bits = []

        exit_reason = str(trade.get("exit_reason") or "")
        entry_reason = str(trade.get("entry_reason") or "")

        if pnl < 0:
            # STRICT loss learning: tighten entry, prefer slightly ITM, widen anti-chase.
            new["entry_confidence_floor"] = min(MAX_FLOOR, old["entry_confidence_floor"] + 5)
            new["strike_offset"] = min(MAX_STRIKE_OFFSET, old["strike_offset"] + 1)
            new["chase_buffer_pct"] = round(min(2.0, old["chase_buffer_pct"] + 0.2), 2)
            reason_bits.append(f"LOSS ₹{pnl:.0f} → tighten floor/offset/chase")
            if "Stop Loss" in exit_reason or "SL" in exit_reason.upper():
                reason_bits.append(f"SL exit ({exit_reason})")
            if "chase" in entry_reason.lower() or "high" in entry_reason.lower():
                reason_bits.append("entry looked like chase/high")
        elif pnl > 0:
            # Mild relaxation only — never below defaults.
            new["entry_confidence_floor"] = max(
                DEFAULTS["entry_confidence_floor"],
                old["entry_confidence_floor"] - 1,
            )
            if old["strike_offset"] > 0 and pnl > abs(float(trade.get("entry_price") or 1)) * 0.15:
                # Strong win at ITM — keep offset; weak win — ease toward ATM
                pass
            elif old["strike_offset"] > 0:
                new["strike_offset"] = max(0, old["strike_offset"] - 1)
            new["chase_buffer_pct"] = round(
                max(DEFAULTS["chase_buffer_pct"], old["chase_buffer_pct"] - 0.05), 2
            )
            reason_bits.append(f"WIN ₹{pnl:.0f} → mild ease")
        else:
            return  # breakeven — no tune

        if new == old:
            return

        conf.update(new)
        await Database.update_agent_config(
            strategy_name=strat,
            config_dict=conf,
            win_rate=float(cfg_row.get("win_rate") or 0),
            total_trades=int(cfg_row.get("total_trades") or 0),
            winning_trades=int(cfg_row.get("winning_trades") or 0),
            status=cfg_row.get("status") or "APPROVED",
            pending_config_json=cfg_row.get("pending_config_json"),
            is_paper_trading=int(
                cfg_row.get("is_paper_trading") if cfg_row.get("is_paper_trading") is not None else 1
            ),
            continuous_losses=int(cfg_row.get("continuous_losses") or 0),
            asset_class=cfg_row.get("asset_class") or "EQUITY",
        )
        analysis = (
            f"Hindsight tune for {strat} after trade {trade.get('symbol')} "
            f"({'; '.join(reason_bits)}). {old} → {new}"
        )
        try:
            await Database.insert_learning_log(
                strategy_name=strat,
                llm_analysis=analysis,
                old_config=json.dumps(old),
                new_config=json.dumps(new),
            )
        except Exception as e:
            logger.warning(f"learning log insert failed: {e}")
        logger.info(f"📈 Hindsight: {analysis}")


hindsight_optimizer_worker = HindsightOptimizerWorker()
