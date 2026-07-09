"""
Candle Builder — Constructs 5m, 15m, 1H OHLCV candles from live WebSocket ticks.
====================================================================================
Zero extra Fyers API calls during market hours. All candle data comes from the
existing WebSocket feed.

Usage:
    from engine.candle_builder import candle_builder

    # Called automatically by ws_feed._on_message for every tick
    candle_builder.on_tick("NSE:NIFTY50-INDEX", ltp=24850.5, timestamp=1716625200)

    # Get closed candles for trend analysis
    candles_5m  = candle_builder.get_candles("NSE:NIFTY50-INDEX", "5m")
    candles_15m = candle_builder.get_candles("NSE:NIFTY50-INDEX", "15m")
    candles_1h  = candle_builder.get_candles("NSE:NIFTY50-INDEX", "1h")
"""

import threading
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pytz

IST = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger("CANDLE_BUILDER")

# Timeframe durations in seconds
TF_SECONDS = {
    "5m": 5 * 60,      # 300s
    "15m": 15 * 60,     # 900s
    "1h": 60 * 60,      # 3600s
}

MAX_CANDLES = 25  # Rolling buffer size per timeframe


class _SymbolCandleState:
    """Tracks candle state for a single symbol across all timeframes."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        # Closed candle buffers (rolling, max MAX_CANDLES each)
        self.closed: Dict[str, List[Dict]] = {
            "5m": [],
            "15m": [],
            "1h": [],
        }
        # Currently forming (unclosed) candle per timeframe
        self.current: Dict[str, Optional[Dict]] = {
            "5m": None,
            "15m": None,
            "1h": None,
        }
        self._bootstrapped = False


def _candle_start_ts(tick_ts: float, tf_seconds: int) -> float:
    """Align a tick timestamp to the start of its candle period.
    E.g., tick at 09:17:32 with 5m TF → candle start = 09:15:00."""
    return (int(tick_ts) // tf_seconds) * tf_seconds


def _new_candle(ltp: float, start_ts: float) -> Dict:
    """Create a fresh candle with a single price point."""
    return {
        "timestamp": start_ts,
        "open": ltp,
        "high": ltp,
        "low": ltp,
        "close": ltp,
        "volume": 0,
    }


class CandleBuilderEngine:
    """Aggregates live WebSocket ticks into multi-timeframe OHLCV candles."""

    def __init__(self):
        self._symbols: Dict[str, _SymbolCandleState] = {}
        self._lock = threading.Lock()
        self._last_candle_close_callbacks: List = []  # optional hooks

    # ==================== PUBLIC API ====================

    def on_tick(self, symbol: str, ltp: float, timestamp: float = 0.0, volume: int = 0):
        """Called on every WebSocket tick. Updates current candle for all TFs.
        
        Args:
            symbol: e.g. "NSE:NIFTY50-INDEX"
            ltp: Last Traded Price
            timestamp: Unix epoch (uses time.time() if 0)
            volume: Traded quantity for this tick (optional)
        """
        if ltp <= 0:
            return

        ts = timestamp if timestamp > 0 else time.time()

        with self._lock:
            state = self._symbols.get(symbol)
            if not state:
                state = _SymbolCandleState(symbol)
                self._symbols[symbol] = state

            for tf, tf_secs in TF_SECONDS.items():
                candle_start = _candle_start_ts(ts, tf_secs)
                cur = state.current[tf]

                if cur is None:
                    # First tick ever for this TF
                    state.current[tf] = _new_candle(ltp, candle_start)
                elif candle_start > cur["timestamp"]:
                    # New period started — close the current candle and archive it
                    state.closed[tf].append(cur)
                    # Trim rolling buffer
                    if len(state.closed[tf]) > MAX_CANDLES:
                        state.closed[tf] = state.closed[tf][-MAX_CANDLES:]
                    # Start new candle
                    state.current[tf] = _new_candle(ltp, candle_start)
                else:
                    # Same period — update OHLCV
                    cur["high"] = max(cur["high"], ltp)
                    cur["low"] = min(cur["low"], ltp)
                    cur["close"] = ltp
                    cur["volume"] += volume

    def get_candles(self, symbol: str, timeframe: str) -> List[Dict]:
        """Return closed candles for the given symbol and timeframe.
        
        Args:
            symbol: e.g. "NSE:NIFTY50-INDEX"
            timeframe: "5m", "15m", or "1h"
            
        Returns:
            List of closed OHLCV candle dicts, oldest first.
        """
        with self._lock:
            state = self._symbols.get(symbol)
            if not state:
                return []
            return list(state.closed.get(timeframe, []))

    def get_current_candle(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Return the currently forming (unclosed) candle."""
        with self._lock:
            state = self._symbols.get(symbol)
            if not state:
                return None
            return state.current.get(timeframe)

    def bootstrap_from_historical(self, symbol: str, timeframe: str, candles: List[Dict]):
        """Seed the candle buffer with historical data from a one-time REST call.
        
        Call this once at startup. The candles should be sorted oldest → newest.
        Each candle dict must have: timestamp, open, high, low, close, volume.
        """
        if not candles:
            return

        with self._lock:
            state = self._symbols.get(symbol)
            if not state:
                state = _SymbolCandleState(symbol)
                self._symbols[symbol] = state

            # Normalize keys (Fyers uses different key names)
            normalized = []
            for c in candles:
                normalized.append({
                    "timestamp": c.get("timestamp", c.get("t", 0)),
                    "open": c.get("open", c.get("o", 0)),
                    "high": c.get("high", c.get("h", 0)),
                    "low": c.get("low", c.get("l", 0)),
                    "close": c.get("close", c.get("c", 0)),
                    "volume": c.get("volume", c.get("v", 0)),
                })

            state.closed[timeframe] = normalized[-MAX_CANDLES:]
            state._bootstrapped = True
            logger.info(
                f"📊 Bootstrapped {symbol} {timeframe}: {len(state.closed[timeframe])} candles "
                f"(latest: {datetime.fromtimestamp(normalized[-1]['timestamp'], IST).strftime('%H:%M')})"
            )

    def is_bootstrapped(self, symbol: str) -> bool:
        """Check if a symbol has been seeded with historical data."""
        with self._lock:
            state = self._symbols.get(symbol)
            return state._bootstrapped if state else False

    def get_stats(self) -> Dict:
        """Return stats about all tracked symbols."""
        with self._lock:
            stats = {}
            for sym, state in self._symbols.items():
                stats[sym] = {
                    tf: {
                        "closed": len(state.closed[tf]),
                        "current": state.current[tf] is not None,
                    }
                    for tf in TF_SECONDS
                }
            return stats


# ==================== SINGLETON ====================
candle_builder = CandleBuilderEngine()
