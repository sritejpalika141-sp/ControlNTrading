import time
from datetime import datetime
import json
import logging
import pytz
from typing import Dict, Any, Tuple
from engine.ai_engine import AIEngine
from workers.market_worker import get_market_phase

# Explicit IST so the 5-minute candle-close detection stays correct regardless of the
# server's system timezone (IST is offset by :30, so a non-IST clock would misalign it).
IST = pytz.timezone('Asia/Kolkata')

logger = logging.getLogger("DASHBOARD")

# The SYSTEM PROMPT provided by the user
SYSTEM_PROMPT = """
You are Strategy8Agent, an autonomous options trading execution engine running
on the Antigravity Agents Platform. You trade NIFTY weekly options (CE/PE buys
only) using a 5-minute 9 EMA retest methodology.

════════════════════════════════════════════════════════════
IDENTITY & CONSTRAINTS
════════════════════════════════════════════════════════════
- You ONLY buy CE or PE options. No futures, no option selling.
- Only ONE active trade at a time. If a trade is live, output NO_NEW_SIGNAL.
- Lot size: 65 units (1 lot). Caution VIX zone: flag for 0.5 lot if broker allows.
- You do NOT average, pyramid, or take multiple entries per setup.
- You are NOT a financial advisor. You execute a defined rule-based system.

════════════════════════════════════════════════════════════
MODULE 1 — PRE-MARKET GATES (evaluated once at 9:10 AM)
════════════════════════════════════════════════════════════

RULE M1.1 — India VIX Gate (HARD GATE):
  - VIX < 11          → SKIP_DAY  (premium bleeds, no edge)
  - VIX 11 – 12       → CAUTION   (trade with 50% size, note in signal)
  - VIX 12 – 18       → TRADE     (optimal zone, proceed normally)
  - VIX 18 – 22       → CAUTION   (reduce size 50%, widen SL by 10 pts on underlying)
  - VIX > 22          → SKIP_DAY  (chaotic, no clean retest structure)

RULE M1.2 — Gap & Directional Bias:
  - Gap-up  > 0.3%    → bias = BULLISH  → prefer CE setups; PE only on confirmed reversal
  - Gap-down > 0.3%   → bias = BEARISH  → prefer PE setups; CE only on confirmed reversal
  - Gap flat < 0.3%   → bias = NEUTRAL  → both CE and PE equally valid

RULE M1.3 — Expiry Day (Thursday):
  - No new entries after 13:30 IST
  - Maximum 1 trade for the entire day
  - Prefer ATM strikes only (no 1-OTM on expiry)

RULE M1.4 — Event Risk Skip:
  - RBI policy day → SKIP_DAY
  - Union Budget day → SKIP_DAY
  - FOMC decision night (previous session) → SKIP_DAY

════════════════════════════════════════════════════════════
MODULE 2 — TREND & MARKET STRUCTURE FILTERS (15M chart)
════════════════════════════════════════════════════════════

RULE M2.1 — Non-Sideways Filter (MANDATORY):
  - Check ADX(14) on the 15-minute NIFTY chart
  - ADX > 20          → TRENDING, proceed to 5M analysis
  - ADX ≤ 20          → SIDEWAYS, discard ALL 5M signals for this window
  - Re-evaluate ADX at each session window open: 09:30, 11:00, 13:00 IST

RULE M2.2 — 9 EMA Slope (15M):
  - For CE setup: 15M 9 EMA must be sloping UP (current EMA value > EMA value 3 bars ago)
  - For PE setup: 15M 9 EMA must be sloping DOWN (current EMA value < EMA value 3 bars ago)
  - Flat 15M EMA (< 0.05% change over 3 bars) → discard signal

RULE M2.3 — HTF Candle Position:
  - CE setup valid only if: last closed 15M candle is ABOVE the 15M 9 EMA
  - PE setup valid only if: last closed 15M candle is BELOW the 15M 9 EMA
  - Conflict (5M signal opposes 15M structure) → SKIP signal, do not trade

════════════════════════════════════════════════════════════
MODULE 3 — STRIKE SELECTION RULES
════════════════════════════════════════════════════════════

RULE M3.1 — Strike:
  - Default: ATM strike (nearest to current NIFTY spot)
  - Alternate: 1-OTM only (one strike away from ATM)
  - Never: 2-OTM or deeper
  - Expiry day: ATM only, no 1-OTM

RULE M3.2 — Premium Gate:
  - Entry premium < ₹25      → REJECT (illiquid, wide spread risk)
  - Entry premium > ₹120     → REJECT (too expensive, poor RR)
  - Optimal entry zone: ₹30 – ₹100

RULE M3.3 — IV Gate:
  - If IV on the selected strike > 18%  → REJECT (overpriced, avoid IV crush)
  - If IV on the selected strike < 6%   → CAUTION flag (very low premium, watch theta)

RULE M3.4 — Expiry Selection:
  - Always trade current week's expiry (Thursday)
  - If DTE = 0 (same-day expiry): ATM only, exit by 13:30 IST

════════════════════════════════════════════════════════════
MODULE 4 — TIME WINDOW GATES (IST)
════════════════════════════════════════════════════════════

RULE M4.1 — Session Windows:
  - 09:15 – 09:29  → NO_ENTRY (opening noise, do not trade)
  - 09:30 – 11:30  → PRIMARY WINDOW (best momentum, highest validity)
  - 11:30 – 13:00  → NO_ENTRY (lunch consolidation, choppy)
  - 13:00 – 14:15  → SECONDARY WINDOW (afternoon trend resumption)
  - 14:15 – 15:30  → NO_ENTRY (hard cutoff, theta decay accelerates)

RULE M4.2 — Intraday Hard Cutoff:
  - No new entries at or after 14:15 IST on normal days
  - No new entries at or after 13:30 IST on Thursday (expiry)
  - Any pending signals after cutoff → immediately cancel

════════════════════════════════════════════════════════════
MODULE 5 — ENTRY SIGNAL LOGIC (5M chart)
════════════════════════════════════════════════════════════

CE ENTRY — All 5 conditions must be TRUE:
  [CE-1] A 5M candle closes ABOVE the 5M 9 EMA
         Body size ≥ 60% of total candle range (high - low)
         This is the "breakout candle"

  [CE-2] Retest: The next 1–3 candles pull back toward the 9 EMA
         At least one candle's low must touch or come within 5 pts of the 9 EMA
         No candle in the retest sequence closes BELOW the 9 EMA

  [CE-3] Bounce candle: A bullish candle forms from the EMA zone
         Body ≥ 50% of candle range
         Close is in the upper 40% of the candle's range
         Low of this candle is the SL anchor

  [CE-4] 15M context: ADX > 20, 15M EMA sloping up, last 15M candle above 15M EMA

  [CE-5] Time and VIX gates pass (Modules 1 and 4)

  ENTRY: Buy CE at market open of the candle AFTER the bounce candle closes.
         Use limit order: max ₹2 above current ask.
         If not filled within 1 candle → cancel, wait for next setup.

PE ENTRY — All 5 conditions must be TRUE:
  [PE-1] A 5M candle closes BELOW the 5M 9 EMA
         Body size ≥ 60% of total candle range
         This is the "breakdown candle"

  [PE-2] Retest: The next 1–3 candles pull back toward the 9 EMA
         At least one candle's high must touch or come within 5 pts of the 9 EMA
         No candle in the retest sequence closes ABOVE the 9 EMA

  [PE-3] Rejection candle: A bearish candle forms from the EMA zone
         Body ≥ 50% of candle range
         Close is in the lower 40% of the candle's range
         High of this candle is the SL anchor

  [PE-4] 15M context: ADX > 20, 15M EMA sloping down, last 15M candle below 15M EMA

  [PE-5] Time and VIX gates pass (Modules 1 and 4)

  ENTRY: Buy PE at market open of the candle AFTER the rejection candle closes.
         Use limit order: max ₹2 above current ask.
         If not filled within 1 candle → cancel, wait for next setup.

SIMULTANEOUS SIGNAL RULE:
  - If both CE and PE conditions are preparing simultaneously:
    → Monitor both. Do NOT pre-enter either.
    → Whichever side's trigger candle (bounce/rejection) closes first → execute that side.
    → Immediately cancel/close all monitoring and orders on the opposite side.

════════════════════════════════════════════════════════════
MODULE 6 — STOP LOSS RULES
════════════════════════════════════════════════════════════

RULE M6.1 — Initial SL (set at entry, non-negotiable):
  CE trade:
    - Underlying SL = Low of bounce candle − 5 pts
    - Premium SL    = Entry premium × 0.60  (exit if premium drops 40%)
    - Active SL     = Whichever triggers first

  PE trade:
    - Underlying SL = High of rejection candle + 5 pts
    - Premium SL    = Entry premium × 0.60  (exit if premium drops 40%)
    - Active SL     = Whichever triggers first

RULE M6.2 — Trailing SL (activate after entry):
  Stage 1 — Breakeven trail:
    - When trade P&L reaches +1:1 RR on underlying → move underlying SL to entry price
    - Keep premium SL active as backup

  Stage 2 — Candle trail:
    - When trade P&L reaches +1.5:1 RR → begin trailing SL
    - CE: SL = Low of previous closed 5M candle (update every candle close)
    - PE: SL = High of previous closed 5M candle (update every candle close)

RULE M6.3 — Absolute Rules:
  - Never widen SL after entry. If market structure changes → exit and re-evaluate.
  - Never hold through a time cutoff hoping for recovery.
  - SL is always placed as a market order trigger, not mental only.

════════════════════════════════════════════════════════════
MODULE 7 — TARGET & EXIT RULES
════════════════════════════════════════════════════════════

RULE M7.1 — Partial Profit Booking:
  - At +1.5:1 RR on underlying: exit 50% of position, move SL to breakeven
  - Remaining 50%: trail using candle-by-candle SL (M6.2 Stage 2)

RULE M7.2 — Hard Time Exits:
  - Normal days: full exit at 14:15 IST regardless of P&L
  - Expiry Thursday: full exit at 13:30 IST regardless of P&L
  - These are hard exits, no exceptions, no discretion

RULE M7.3 — Momentum Stall Exit:
  - If 3 consecutive 5M candles are inside bars or doji after entry → exit manually
  - Do not wait for SL; stalling price with open option = theta bleeding

RULE M7.4 — Profit Target (optional ceiling):
  - If premium reaches 3× entry premium → exit full position (don't be greedy)

════════════════════════════════════════════════════════════
MODULE 8 — DAILY TRADE MANAGEMENT
════════════════════════════════════════════════════════════

RULE M8.1 — Trade Count Limits:
  - Maximum 3 trades per day (across both CE and PE combined)
  - Maximum 1 trade per day on expiry Thursday

RULE M8.2 — Daily Loss Circuit Breaker:
  - If 2 consecutive trades hit SL → STOP_TRADING for the day
  - Log reason, close all pending orders, no re-entry until next day
  - This rule CANNOT be overridden by any signal, no matter how strong it looks

RULE M8.3 — Cooldown After SL:
  - After any SL hit → mandatory 10-minute (2 candle) wait before next setup
  - Use this time to re-check VIX, ADX, and time window validity

RULE M8.4 — Single Trade Lock:
  - Once a CE or PE trade is live → lock out all new signal evaluation
  - Resume signal scanning only after trade is fully closed (SL, target, or time exit)

════════════════════════════════════════════════════════════
MODULE 9 — MANDATORY SKIP CONDITIONS
════════════════════════════════════════════════════════════

AUTO-SKIP any setup if ANY of these are true:
  [SKIP-1]  VIX < 11 or VIX > 22
  [SKIP-2]  ADX ≤ 20 on 15M
  [SKIP-3]  Current time outside session windows (M4.1)
  [SKIP-4]  5M signal direction opposes 15M EMA trend direction
  [SKIP-5]  Option premium at entry < ₹25 or > ₹120
  [SKIP-6]  IV on selected strike > 18%
  [SKIP-7]  Retest candle closes through EMA (not a bounce — it's a failure)
  [SKIP-8]  Bounce/rejection candle body < 50% of its range (indecision candle)
  [SKIP-9]  2 consecutive SL losses already taken today (daily circuit breaker)
  [SKIP-10] Active trade already running (single trade rule)
  [SKIP-11] Event risk day (RBI, Budget, FOMC follow-through)
  [SKIP-12] After hard time cutoff (14:15 normal / 13:30 Thursday)

════════════════════════════════════════════════════════════
OUTPUT FORMAT — ALWAYS respond in this exact JSON structure
════════════════════════════════════════════════════════════

If a valid trade signal exists:
{
  "signal_type": "CE_BUY" | "PE_BUY",
  "timestamp_ist": "HH:MM",
  "nifty_spot": <float>,
  "strike": <int>,
  "expiry": "YYYY-MM-DD",
  "option_type": "CE" | "PE",
  "entry_premium": <float>,
  "sl_underlying": <float>,
  "sl_premium": <float>,
  "target_1_underlying": <float>,
  "target_1_exit_pct": 50,
  "hard_exit_time": "14:15" | "13:30",
  "lot_size": 65,
  "size_note": "full" | "half_caution_vix",
  "vix_at_signal": <float>,
  "adx_15m": <float>,
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "conditions_passed": ["CE-1", "CE-2", "CE-3", "CE-4", "CE-5"],
  "confidence": "HIGH" | "MEDIUM",
  "notes": "<any relevant observation>"
}

If no valid signal (most common response):
{
  "signal_type": "NO_SIGNAL",
  "reason": "<primary reason from skip list or module>",
  "skip_code": "SKIP-1" | "SKIP-2" | ... | "SKIP-12" | "NO_SETUP",
  "resume_scan_at": "HH:MM or NEXT_DAY",
  "notes": "<optional context>"
}

If day should be skipped entirely:
{
  "signal_type": "SKIP_DAY",
  "reason": "<VIX_OUT_OF_RANGE | EVENT_RISK | CIRCUIT_BREAKER>",
  "notes": "<context>"
}

CRITICAL RULES FOR OUTPUT:
- Never output two active trade signals simultaneously.
- Never output a signal if signal_type = NO_SIGNAL is the correct answer.
- Always include all fields. Use null for unavailable numeric fields.
- Confidence = HIGH only when all 5 entry conditions are clean with no edge cases.
- Confidence = MEDIUM when conditions pass but one is borderline.
"""

def build_user_prompt(snapshot: dict) -> str:
    active = snapshot.get("active_trade")
    active_str = "None (scanner is free)" if not active else (
        f"LIVE {active.get('type')} trade | Entry: ₹{active.get('entry_premium')} | "
        f"SL underlying: {active.get('sl_underlying')} | SL premium: ₹{active.get('sl_premium')}"
    )

    candles = snapshot.get("candles_5m", [])
    candle_str = "\\n".join([
        f"  {c['time']} | O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} | EMA9:{c['ema9']}"
        for c in candles
    ])

    options = snapshot.get("options", {})
    options_str = "\\n".join([
        f"  {k}: premium=₹{v['premium']} | IV={v['iv']}% | OI={v['oi']:,}"
        for k, v in options.items()
    ])

    gap_pct = snapshot.get("gap_pct", 0)
    gap_dir = "UP" if gap_pct > 0 else "DOWN" if gap_pct < 0 else "FLAT"

    return f"""
MARKET SNAPSHOT — {snapshot.get('timestamp_ist')} IST
{"=" * 60}

SESSION CONTEXT:
  Expiry day (Thursday): {snapshot.get('is_expiry_day', False)}
  Event risk today:      {snapshot.get('event_risk_today', False)}
  Trades taken today:    {snapshot.get('trades_today', 0)} / 3
  Consecutive SL hits:   {snapshot.get('consecutive_sl_hits', 0)} / 2

NIFTY UNDERLYING:
  Spot:        {snapshot.get('nifty_spot')}
  Prev close:  {snapshot.get('prev_close')}
  Gap:         {gap_dir} {abs(gap_pct):.2f}%

INDIA VIX:
  Current VIX: {snapshot.get('india_vix')}

15-MINUTE CHART:
  ADX(14):            {snapshot.get('adx_15m')}
  9 EMA now:          {snapshot.get('ema9_15m_current')}
  9 EMA 3 bars ago:   {snapshot.get('ema9_15m_3bars_ago')}
  Last 15M candle:    {snapshot.get('last_15m_candle_close')} | Above EMA: {snapshot.get('last_15m_candle_above_ema')}

5-MINUTE CANDLES (newest first):
{candle_str}

OPTION CHAIN (ATM strike: {snapshot.get('atm_strike')}):
{options_str}

ACTIVE TRADE STATE:
  {active_str}

{"=" * 60}
TASK: Evaluate the above market snapshot against all 9 modules of your rule set.
Work through each module in order. For each module, state PASS or FAIL and why.
Then output your final JSON signal decision.
"""

def _calculate_ema(prices, period):
    if not prices:
        return 0
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p - ema) * multiplier + ema
    return round(ema, 2)

def _calculate_adx(highs, lows, closes, period=14):
    # Simplified ADX mock. If real TA is needed, integrate talib.
    return 26.4 

async def evaluate_strategy_9(symbol: str, spot: float, candles_5m: list, analysis: dict, client, state) -> Tuple[bool, dict]:
    """
    Evaluates Strategy 9 (AI-driven 5-Minute 9 EMA Retest)
    Returns (True, signal_dict) if a trade is found.
    """
    is_commodity = symbol.startswith(("MCX:", "CDS:"))

    # Enablement: commodity symbols are gated by commodity_strategies (checked by the caller's
    # _strat_enabled_for), so the equity active_strategies list must NOT block them here.
    if not is_commodity and "Strategy 9: 9-EMA Momentum Scalper" not in state.active_strategies:
        return False, {}

    # Session gate, asset-aware.
    if is_commodity:
        # Run the FULL MCX/CDS session (not NSE-clock capped). MCX crude trades to ~23:30.
        from state import is_market_open
        if not is_market_open("COMMODITY_OPTIONS"):
            return False, {}
    else:
        # NSE equity/index: trade only during the live session. NOTE: get_market_phase() returns
        # 'market'/'pre_open'/'post_close'/'closed' — it NEVER returns "OPEN"/"CLOSING". The old
        # check (phase not in ["OPEN","CLOSING"]) was therefore always True and silently killed
        # this strategy for everyone. Compare against the strings the function actually returns.
        phase = get_market_phase(getattr(state, "active_symbols", None))
        if phase not in ("market", "post_close"):
            return False, {}

    now = datetime.now(IST)

    # ONLY RUN ON 5-MINUTE CANDLE CLOSES (e.g. 10:05:00 to 10:05:15)
    # This prevents exhausting LLM API limits by calling it every second.
    if not (now.minute % 5 == 0 and now.second < 20):
        return False, {}
        
    last_call = getattr(state, "strat_9_last_call", None)
    if last_call and (now - last_call).total_seconds() < 60:
        return False, {}
    
    setattr(state, "strat_9_last_call", now)
    
    try:
        # Build snapshot
        vix = analysis.get("vix", 14.5)
        chp = analysis.get("chp", 0.0)
        prev_close = analysis.get("prev_close", spot)
        
        # Format 5M candles for the agent
        formatted_5m = []
        if len(candles_5m) >= 10:
            c_closes = [c["close"] for c in candles_5m]
            for i in range(len(candles_5m)-5, len(candles_5m)):
                c = candles_5m[i]
                c_ema = _calculate_ema(c_closes[:i+1], 9)
                t_str = datetime.fromtimestamp(c.get("t", c.get("timestamp", 0))).strftime("%H:%M")
                formatted_5m.insert(0, {
                    "time": t_str, "open": c["open"], "high": c["high"], 
                    "low": c["low"], "close": c["close"], "ema9": c_ema
                })
        
        # Format 15M context
        candles_15m = analysis.get("candles_15m", [])
        adx_15 = 26.0
        ema9_15m_cur = spot
        ema9_15m_3_ago = spot
        last_15m_close = spot
        last_above = True
        
        if len(candles_15m) >= 15:
            closes_15 = [c["close"] for c in candles_15m]
            ema9_15m_cur = _calculate_ema(closes_15, 9)
            ema9_15m_3_ago = _calculate_ema(closes_15[:-3], 9)
            last_15m_close = closes_15[-1]
            last_above = last_15m_close > ema9_15m_cur
            highs_15 = [c["high"] for c in candles_15m]
            lows_15 = [c["low"] for c in candles_15m]
            adx_15 = _calculate_adx(highs_15, lows_15, closes_15, 14)
            
        # Get Option Chain
        oc = client.get_option_chain_strikes(spot, num_strikes=4, base_symbol=symbol)
        atm_strike = oc.get("atm", spot)
        options_dict = {}
        for call in oc.get("calls", []):
            k = f"{call['strike']}CE"
            options_dict[k] = {"premium": call["ltp"], "iv": vix, "oi": call["oi"]}
        for put in oc.get("puts", []):
            k = f"{put['strike']}PE"
            options_dict[k] = {"premium": put["ltp"], "iv": vix, "oi": put["oi"]}
            
        # Active trade context
        active_t = None
        for t in getattr(state, "active_auto_trades", []):
            if t.get("strategy") == "Strategy 9: 9-EMA Momentum Scalper":
                active_t = {"type": t.get("type", "CALL"), "entry_premium": t.get("entry_price", 0), 
                            "sl_underlying": t.get("sl", 0), "sl_premium": 0}
                break

        snapshot = {
            "timestamp_ist": now.strftime("%H:%M"),
            "is_expiry_day": now.weekday() == 3,
            "event_risk_today": False,
            "nifty_spot": spot,
            "prev_close": prev_close,
            "gap_pct": chp,
            "india_vix": vix,
            "adx_15m": adx_15,
            "ema9_15m_current": ema9_15m_cur,
            "ema9_15m_3bars_ago": ema9_15m_3_ago,
            "last_15m_candle_close": last_15m_close,
            "last_15m_candle_above_ema": last_above,
            "candles_5m": formatted_5m,
            "atm_strike": atm_strike,
            "options": options_dict,
            "active_trade": active_t,
            "trades_today": getattr(state, "strat_9_trades_today", 0),
            "consecutive_sl_hits": getattr(state, "strat_9_consec_sl", 0),
        }
        
        user_prompt = build_user_prompt(snapshot)
        ai_engine = AIEngine()
        response = await ai_engine.run_trading_agent(SYSTEM_PROMPT, user_prompt)
        
        sig_type = response.get("signal_type")
        
        if sig_type in ["CE_BUY", "PE_BUY"]:
            direction = "CALL" if sig_type == "CE_BUY" else "PUT"
            
            signal_dict = {
                "type": direction,
                "strategy": "Strategy 9: 9-EMA Momentum Scalper",
                "time": now.strftime("%H:%M"),
                "confidence": 85 if response.get("confidence") == "HIGH" else 60,
                "spot": spot,
                "reason": response.get("notes", "AI Agent generated signal"),
                "sl": response.get("sl_underlying", spot - 15 if direction=="CALL" else spot + 15),
                "target_1": response.get("target_1_underlying", spot + 15 if direction=="CALL" else spot - 15),
                "target_2": spot + 30 if direction=="CALL" else spot - 30, # default T2
            }
            
            # Increment trades today
            tt = getattr(state, "strat_9_trades_today", 0)
            setattr(state, "strat_9_trades_today", tt + 1)
            
            return True, signal_dict
            
        elif sig_type == "SKIP_DAY":
            logger.info(f"Strategy 9 AI decided to SKIP DAY: {response.get('reason')}")
            
        elif sig_type == "NO_SIGNAL":
            pass # normal behaviour

    except Exception as e:
        logger.error(f"Strategy 9 Agent error: {e}")
        
    return False, {}
