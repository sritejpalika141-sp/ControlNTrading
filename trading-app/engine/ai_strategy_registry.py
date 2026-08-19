"""
AI / auto-generated strategy registry.

Wires `engine/strategy_auto_*.py` (from Strategy Researcher) into live evaluation
under names like `AI_strategy_N` stored in `swarm_agent_configs`.

Safety:
  - AI strategies default to PAPER only until `is_paper_trading=0` in agent config.
  - Modules are loaded from `engine/` only; failed loads are skipped (never crash the loop).
  - Candle OHLC keys are dual-cased so LLM-generated code using Close/Open still works
    against live lowercase candles.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("AI_STRATEGY_REGISTRY")

ENGINE_DIR = Path(__file__).resolve().parent
_MODULE_CACHE: Dict[str, Any] = {}
_FN_CACHE: Dict[str, Callable] = {}


def _dual_case_candles(candles: list) -> list:
    """Ensure both lowercase and Title-case OHLC keys exist on each candle dict."""
    if not candles:
        return []
    out = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        d = dict(c)
        for lo, hi in (
            ("open", "Open"),
            ("high", "High"),
            ("low", "Low"),
            ("close", "Close"),
            ("volume", "Volume"),
        ):
            if lo in d and hi not in d:
                d[hi] = d[lo]
            elif hi in d and lo not in d:
                d[lo] = d[hi]
        out.append(d)
    return out


def list_auto_strategy_files() -> List[str]:
    """Basenames of engine/strategy_auto_*.py (excludes __pycache__)."""
    files = []
    try:
        for p in sorted(ENGINE_DIR.glob("strategy_auto_*.py")):
            if p.name.endswith(".py") and not p.name.startswith("strategy_auto___"):
                files.append(p.name)
    except Exception as e:
        logger.warning(f"list_auto_strategy_files failed: {e}")
    return files


def _load_module(module_file: str):
    """Load (and cache) a strategy_auto_*.py module by basename."""
    base = os.path.basename(module_file)
    if not base.startswith("strategy_auto_") or not base.endswith(".py"):
        raise ValueError(f"refusing to load non-auto strategy file: {base}")
    path = ENGINE_DIR / base
    if not path.is_file():
        raise FileNotFoundError(str(path))
    mtime = path.stat().st_mtime
    cached = _MODULE_CACHE.get(base)
    if cached and cached.get("mtime") == mtime:
        return cached["mod"]
    spec = importlib.util.spec_from_file_location(f"engine.{base[:-3]}", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {base}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MODULE_CACHE[base] = {"mod": mod, "mtime": mtime}
    _FN_CACHE.pop(base, None)
    return mod


def find_evaluate_fn(mod) -> Optional[Callable]:
    """Prefer async evaluate_auto_* ; fall back to any evaluate_* coroutine/function."""
    preferred = []
    fallback = []
    for name, obj in inspect.getmembers(mod, inspect.isfunction):
        if name.startswith("evaluate_auto_"):
            preferred.append(obj)
        elif name.startswith("evaluate_"):
            fallback.append(obj)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


def normalize_auto_signal(raw: Any, strategy_name: str, symbol: str) -> Optional[Dict]:
    """Convert researcher/LLM signal shapes into the orchestrator/execute contract."""
    if not raw or not isinstance(raw, dict):
        return None

    t = raw.get("type") or raw.get("signal") or raw.get("direction") or raw.get("side")
    if not isinstance(t, str):
        return None
    tu = t.strip().upper()
    if tu in ("BUY", "LONG", "BULL", "BULLISH", "CALL", "CE"):
        typ = "CALL"
    elif tu in ("SELL", "SHORT", "BEAR", "BEARISH", "PUT", "PE"):
        # Options buy-only: bearish = BUY PUT, never short CE
        typ = "PUT"
    else:
        return None

    conf = raw.get("confidence", 70)
    try:
        conf = int(float(conf))
    except Exception:
        conf = 70

    paper = raw.get("paper_trade_only")
    if paper is None:
        paper = True  # default safe for AI strategies

    out = {
        "symbol": symbol,
        "type": typ,
        "side": "BUY",
        "strategy": strategy_name,
        "reason": raw.get("reason") or raw.get("entry_reason") or f"{strategy_name} signal",
        "confidence": conf,
        "paper_trade_only": bool(paper),
        "is_ai_strategy": True,
    }
    if raw.get("entry_price") is not None:
        try:
            out["entry_price"] = float(raw["entry_price"])
        except Exception:
            pass
    if raw.get("sl_points") is not None:
        try:
            out["sl_points"] = float(raw["sl_points"])
        except Exception:
            pass
    # Pass through direct-option fields if the auto strategy already selected a strike
    for k in ("is_direct_option", "strike_info", "qty", "target_1", "target_2"):
        if k in raw:
            out[k] = raw[k]
    return out


async def resolve_ai_strategy_bindings() -> List[Dict[str, Any]]:
    """
    Bind AI_strategy_* swarm rows to on-disk strategy_auto_*.py files.
    Returns list of {strategy_name, module_file, is_paper_trading, status, evaluate_fn}.
    """
    from models import Database

    configs = await Database.get_all_agent_configs()
    ai_cfgs = [
        c for c in (configs or [])
        if str(c.get("strategy_name") or "").startswith("AI_strategy_")
        and str(c.get("status") or "APPROVED").upper() in ("APPROVED", "PENDING")
    ]
    disk_files = list_auto_strategy_files()
    used_files = set()
    bindings = []

    for cfg in ai_cfgs:
        name = cfg["strategy_name"]
        conf = cfg.get("config_json") or {}
        if isinstance(conf, str):
            try:
                import json
                conf = json.loads(conf) if conf else {}
            except Exception:
                conf = {}
        module_file = conf.get("module_file") or conf.get("filename") or ""
        module_file = os.path.basename(str(module_file)) if module_file else ""
        if module_file and module_file not in disk_files:
            logger.warning(f"{name}: module_file={module_file} missing on disk — skip")
            continue
        if not module_file:
            # Assign first unused auto file (legacy rows with empty config)
            free = [f for f in disk_files if f not in used_files and f != "strategy_auto_dummy.py"]
            if not free:
                free = [f for f in disk_files if f not in used_files]
            if not free:
                logger.info(f"{name}: no strategy_auto_*.py available to bind")
                continue
            module_file = free[0]
            # Persist the link so future nights stay stable
            try:
                conf = dict(conf)
                conf["module_file"] = module_file
                conf["paper_trade_only"] = True
                await Database.update_agent_config(
                    strategy_name=name,
                    config_dict=conf,
                    win_rate=float(cfg.get("win_rate") or 0),
                    total_trades=int(cfg.get("total_trades") or 0),
                    winning_trades=int(cfg.get("winning_trades") or 0),
                    status=cfg.get("status") or "APPROVED",
                    pending_config_json=cfg.get("pending_config_json"),
                    is_paper_trading=int(
                        cfg.get("is_paper_trading") if cfg.get("is_paper_trading") is not None else 1
                    ),
                    continuous_losses=int(cfg.get("continuous_losses") or 0),
                    asset_class=cfg.get("asset_class") or "EQUITY",
                )
            except Exception as e:
                logger.warning(f"Failed to persist module_file for {name}: {e}")

        try:
            mod = _load_module(module_file)
            fn = find_evaluate_fn(mod)
            if not fn:
                logger.warning(f"{name}: no evaluate_* in {module_file}")
                continue
            used_files.add(module_file)
            is_paper = int(cfg.get("is_paper_trading") if cfg.get("is_paper_trading") is not None else 1)
            bindings.append({
                "strategy_name": name,
                "module_file": module_file,
                "is_paper_trading": is_paper,
                "status": cfg.get("status") or "APPROVED",
                "evaluate_fn": fn,
            })
        except Exception as e:
            logger.warning(f"{name}: load failed for {module_file}: {e}")

    return bindings


async def evaluate_bound_strategy(
    binding: Dict[str, Any],
    client,
    state,
    symbol: str,
    candles_5m: list,
    candles_daily: list = None,
    vix: float = 15.0,
) -> Optional[Dict]:
    """Run one bound AI strategy and return a normalized signal or None."""
    fn = binding.get("evaluate_fn")
    name = binding.get("strategy_name", "AI_strategy")
    if not fn or not candles_5m:
        return None
    candles = _dual_case_candles(candles_5m)
    daily = _dual_case_candles(candles_daily or [])
    try:
        if inspect.iscoroutinefunction(fn):
            raw = await fn(client, state, symbol, candles, daily, vix)
        else:
            raw = await asyncio.to_thread(fn, client, state, symbol, candles, daily, vix)
    except TypeError:
        # Some generated signatures omit daily/vix
        try:
            if inspect.iscoroutinefunction(fn):
                raw = await fn(client, state, symbol, candles)
            else:
                raw = await asyncio.to_thread(fn, client, state, symbol, candles)
        except Exception as e:
            logger.warning(f"{name} eval TypeError retry failed: {e}")
            return None
    except Exception as e:
        logger.warning(f"{name} eval failed: {e}")
        return None

    # Some generators return (has_sig, sig)
    if isinstance(raw, tuple) and len(raw) == 2:
        has, sig = raw
        raw = sig if has else None

    sig = normalize_auto_signal(raw, name, symbol)
    if not sig:
        return None
    # Enforce paper until graduated
    if int(binding.get("is_paper_trading", 1)) == 1:
        sig["paper_trade_only"] = True
    return sig


async def evaluate_enabled_ai_strategies(
    client,
    state,
    symbol: str,
    candles_5m: list,
    candles_daily: list = None,
    vix: float = 15.0,
) -> List[Tuple[str, Dict]]:
    """
    Evaluate AI strategies that are enabled in state.active_strategies.
    Returns list of (strategy_name, normalized_signal).
    """
    active = set(getattr(state, "active_strategies", []) or [])
    # Also allow any AI_strategy_* that appears in active list, OR if user has
    # "AI Strategies" enabled via name prefix match.
    bindings = await resolve_ai_strategy_bindings()
    results = []
    for b in bindings:
        name = b["strategy_name"]
        if name not in active and not any(name.startswith(a) or a.startswith(name) for a in active):
            # Not selected in settings — skip (user must enable the checkbox)
            continue
        if symbol.startswith(("MCX:", "CDS:")) and (b.get("asset_class") or "EQUITY") == "EQUITY":
            # Equity AI candidates stay off commodity symbols
            continue
        sig = await evaluate_bound_strategy(b, client, state, symbol, candles_5m, candles_daily, vix)
        if sig:
            results.append((name, sig))
    return results
