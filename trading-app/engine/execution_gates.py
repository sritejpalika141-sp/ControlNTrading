"""Pre-trade execution gates — microstructure spread and MTF alignment."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def passes_microstructure_spread(quote: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Reject option entries when bid-ask spread is too wide (>3% of LTP).
    Missing bid/ask passes (unvetted) to avoid blocking on thin quote payloads.
    """
    from workers.microstructure_worker import microstructure_worker

    if not quote:
        return True, "Quote unavailable"
    bid = float(quote.get("bid") or 0)
    ask = float(quote.get("ask") or 0)
    ltp = float(quote.get("lp") or quote.get("ltp") or 0)
    return microstructure_worker.check_option_spread(bid, ask, ltp)


def passes_mtf_alignment(candles_5m: List[Dict], sig_type: str) -> Tuple[bool, str]:
    """
  5m SMA trend must align with option direction: CALL→BULLISH, PUT→BEARISH.
  NEUTRAL consensus blocks entry (theta/chop protection).
    """
    from workers.mtf_aligner_worker import mtf_aligner_worker

    if not candles_5m or len(candles_5m) < 10:
        return True, "MTF skipped (insufficient 5m candles)"

    result = mtf_aligner_worker.evaluate_trend_alignment([], candles_5m, [])
    consensus = (result.get("consensus") or "NEUTRAL").upper()
    sig = (sig_type or "").upper()

    if "CALL" in sig or sig.endswith("CE"):
        if consensus == "BULLISH":
            return True, result.get("reason", "MTF bullish")
        return False, f"MTF {consensus} blocks CALL ({result.get('reason', '')})"

    if "PUT" in sig or sig.endswith("PE"):
        if consensus == "BEARISH":
            return True, result.get("reason", "MTF bearish")
        return False, f"MTF {consensus} blocks PUT ({result.get('reason', '')})"

    return False, f"MTF gate: unknown signal type {sig_type!r}"


async def check_mtf_gate(client, symbol: str, sig_type: str, api_queue) -> Tuple[bool, str]:
    """Fetch underlying 5m history and run MTF alignment gate."""
    try:
        candles = await api_queue.enqueue(2, client.get_historical, symbol, "5", 5)
    except Exception as exc:
        return True, f"MTF skipped (history error: {exc})"
    return passes_mtf_alignment(candles or [], sig_type)
