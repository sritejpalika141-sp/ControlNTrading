---
name: backlog:tick-contamination-rootcause
description: "Full root-cause fix for WS tick cross-contamination (stock LTPs getting other symbols' prices)"
date: 06-07-26
metadata:
  node_type: memory
  type: backlog-note
  feature: multi-asset-expansion
---

# Live Tick Cross-Contamination — Root-Cause Fix (backlog)

**Severity: HIGH** — affects live trading (strategies read the contaminated LTP).

## ✅ RESOLVED 13-07-26 (commit 0e2e127)

**Root cause found:** a torn read of the Fyers SDK's shared message dict. `ws_feed._on_message`
read `symbol` from `message`, THEN acquired `self._lock` (a GIL yield point), THEN read `ltp` from
the SAME dict. The SDK invokes the callback from a background thread and reuses/mutates one message
object, so a second tick mutated the dict between the two reads — crossing a symbol with another
tick's price. Confirmed live: NIFTY's ~24232 landed on SBIN AND INDIAVIX simultaneously.

**Fix:** snapshot the tick atomically at the top of `_on_message` (`msg = dict(message)`) before the
lock / any GIL-yield, and read every field from `msg`. **Verified live (market hours): 0
contaminations over ~3 min post-deploy vs 225 in ~1 min before.** Interim value-guard retained as a
belt-and-suspenders backstop; a RAW[] diagnostic was added on its rejection path for future
monitoring. The prior investigation notes below are kept for history.

---

## Confirmed symptom (2026-07-06, market hours)
Stock watchlist LTPs intermittently show ANOTHER symbol's price while their OHLC stays correct:
- `NSE:RELIANCE-EQ` showed `lp=58416` (BANKNIFTY's price) while its O/H/L were ~1304/1319/1299.
- `NSE:SBIN-EQ` showed `lp=827.8` (wrong) then self-corrected to ~1045.
- Self-corrects on the next clean tick → intermittent, not permanent.
- Over ~400 log lines, **101 gross contaminations** were caught by the interim guard — so it is FREQUENT.

## Interim mitigation SHIPPED (commit pending / deployed 2026-07-06)
`engine/ws_feed.py` `_on_message`: a data-sanity guard rejects an incoming `ltp` grossly outside the
symbol's established day range (`ltp > high*3` or `ltp < low/3`) and logs it (`TICK-CONTAMINATION guard`).
- **Catches:** gross cases (an index price ~58000 landing on a stock ~1300). RELIANCE/SBIN now correct.
- **Does NOT catch:** subtle stock-on-stock contamination where the wrong price is still within the
  symbol's day range (e.g. SBIN's 827 was within [low*0.5, high*1.5], so a value-guard can't catch it).
- 3x/0.33x bounds are far beyond any real intraday/circuit move, so legitimate moves are never rejected.

## Root-cause investigation (do after market close — do NOT live-patch price code under load)
All mapping code was traced and is correctly dict-keyed by symbol (`ws_feed._on_message` keys by
`message.get("symbol")`; `market_worker.tick_processor` keys `cache["all_spots"][symbol]`;
`get_quotes` maps by response `item["n"]`; frontend `renderScriptsList` maps `dataMap[s]`). So the
contamination is in the LIVE tick ATTRIBUTION, not a static mapping bug. Investigate:
1. **Capture raw ticks**: temporarily raise the `_msg_count` debug cap (ws_feed.py:325) or add
   targeted logging of `(message.get("symbol"), message.get("ltp"))` for the contaminated symbols, to
   see whether Fyers itself sends a tick with `symbol=RELIANCE, ltp=58416`, or the app mis-attributes it.
2. **Fyers WS subscription/token mapping**: check whether rapid subscribe/unsubscribe (watchlist
   rotation) or a symbol-token collision causes ticks to be delivered under the wrong symbol. Review
   `ws_feed.subscribe`/`unsubscribe` and the FyersDataSocket token handling.
3. **LiteMode**: confirm whether the contamination correlates with LiteMode ticks (ltp-only) where the
   guard/OHLC context is absent.
4. If Fyers is genuinely mis-delivering, add a stronger per-symbol validation (e.g. verify the tick's
   symbol against the subscribed set + a token map) rather than a value-range heuristic.

## Related
- STRATEGY_8 (SMC) was firing repeatedly on `NSE:SBIN-EQ` during the contamination window — verify it was
  not reacting to bad ticks. Consider gating stock auto-trade until the full fix lands.
- This surfaced while trialling stocks (SBIN/RELIANCE) in the watchlist ahead of the multi-asset program.
