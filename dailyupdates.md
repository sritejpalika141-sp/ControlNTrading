# Daily Updates Changelog

## 2026-05-25

### 13:21:00
- **Action:** Initialized the project changelog and agent rules.
- **Files Changed:** `AGENT_RULES.md`, `dailyupdates.md` (Created)
- **Details:** Created the `dailyupdates.md` file to track all future changes and `AGENT_RULES.md` to ensure Antigravity logs intent prior to making any modifications.

### 13:30:00
- **Action:** Updating agent rules for task complexity analysis.
- **Files Changed:** `AGENT_RULES.md`
- **Details:** Updating the rules to require the agent to analyze task complexity (Simple/Normal/Complex), recommend the appropriate AI model, and mandate formal implementation plans for Complex tasks before coding begins.

### 13:35:00
- **Action:** Fix Telegram Buy/TG identical bug & enable post-trade PnL notifications.
- **Files Changed:** `engine/automation.py`, `workers/auto_trader.py`
- **Details:** In `automation.py`, I am formatting the Target price string in `add_active_trade` to show "None (Trailing)" if `target_points` is 0, which fixes the identical Buy/TG bug. In `auto_trader.py`, I am updating the calls to `record_trade_close` to properly pass the position details (`pos`, `pnl`, `exit_price`, `reason`) so that the webhook sends the final trade PnL alert to Telegram when a trade is squared off.

### 13:42:00
- **Action:** Executing deployment script.
- **Files Changed:** N/A (Deployment only)
- **Details:** Running `bash deploy.sh` to push the recent Telegram notification fixes to the Google Cloud VM instance.

### 13:50:00
- **Action:** Add Stop Loss and Target price display to the Active Trade Strip on the dashboard.
- **Files Changed:** `static/app.js`
- **Details:** Updating the `renderPositions` function to pull the SL and Target prices from the global `lastKnownActiveTrades` variable and display them in the Active Trade Strip HTML UI.

### 13:54:00
- **Action:** Add task explanation and confirmation rule to AGENT_RULES.md.
- **Files Changed:** `AGENT_RULES.md`
- **Details:** Updating the agent rules to make it mandatory to explain my understanding of every new task and wait for the user's explicit confirmation before proceeding with any action.

### 14:14:00
- **Action:** COMPLEX TASK — Multi-Timeframe Intraday Trend Regime + AI Confirmation.
- **Files Changed:** `engine/candle_builder.py` (NEW), `engine/ws_feed.py`, `engine/key_levels.py`, `engine/ai_engine.py`, `app.py`, `static/app.js`
- **Details:** Building a complete multi-timeframe intraday trend system:
  1. NEW `candle_builder.py` — Constructs 5m, 15m, 1H candles from live WebSocket ticks (zero API calls).
  2. MODIFY `ws_feed.py` — Hook CandleBuilder into the `_on_message` tick callback.
  3. MODIFY `key_levels.py` — Add `detect_intraday_trend()` that requires all 3 timeframes (5m, 15m, 1H) to agree.
  4. MODIFY `ai_engine.py` — Add a simplified AI trend prompt: "For [Scrip], what is the intraday trend now?"
  5. MODIFY `app.py` — Wire the new multi-TF + AI pipeline into `run_full_analysis()`.
  6. MODIFY `app.js` — Show per-timeframe bias (1H/15m/5m) and AI confirmation on the dashboard.

### May 25, 2026 - 17:56 IST
- **Task:** Bypass strict multi-timeframe AI trend regime lockout for Strategy 2 (9:26) and Strategy 3 (ORB).
- **Complexity:** Normal
- **Files to be Modified:**
  - `trading-app/app.py`: To update signal execution / manual trade logic to only block Strategy 1 (OB + FVG) when trend is NEUTRAL.
  - `trading-app/engine/signals.py` / relevant strategy evaluation scripts: To ensure other strategies generate valid signals ignoring the global trend state.
- **Description:** Implement condition to restrict the new strict trend checks to Strategy 1 only, ensuring independent execution for time-based and breakout strategies.

### May 26, 2026 - 11:06 IST
- **Task:** Explain Strategy 2 (9:26 - 180 Buy) and await user's modification requests.
- **Complexity:** Simple/Normal
- **Description:** Reviewing `engine/strategy_926.py` to provide a clear explanation of how the strategy currently selects and triggers options at 9:26 AM, then waiting for further instructions from the user before making code changes.

### May 26, 2026 - 11:21 IST
- **Task:** Explain Strategy 3 (5-Minute ORB) and await user's modification requests.
- **Complexity:** Simple/Normal
- **Description:** Reviewing `engine/strategy_orb.py` to provide a clear explanation of how the ORB strategy currently evaluates breakouts, and waiting for further instructions from the user before making any code changes.

### May 26, 2026 - Backtesting Framework implementation
- **Status:** Pending User Approval
- **Task:** Build a comprehensive historical backtesting script for all 4 strategies (OB+FVG, 9:26 Breakout, 5-Minute ORB, Wisdom-Aligned Pullback).
- **Files to Modify/Create:** 
  - `scripts/run_backtests.py` (New file)
  - `engine/strategy_wisdom.py` (New file)
- **Details:** The backtester will connect to the Fyers API to download historical data for NIFTY, simulate trade entries/exits day-by-day according to the exact live logic, and output Win Rates, PnL, and trade frequencies to validate the strategies.

### May 26, 2026 - Strategy Profitability Adjustments
- **Status:** Approved & Executing
- **Task:** Apply user-approved risk management and entry filters to Strategy 1, 3, and 4 to improve profitability.
- **Files to Modify:** 
  - `engine/strategy_wisdom.py` (Strat 4: 1H SMA only, dynamic SL, 20 EMA bounce entry)
  - `engine/strategy_orb.py` (Strat 3: 15-Min ORB, candle close confirmation)
  - `engine/auto_trade.py` / `workers/auto_trader.py` / `engine/strategy_1.py` (Strat 1: Block 12:00-13:30, dynamic SL edge)
- **Details:** Implementing data-backed logic changes discovered during backtesting to filter false breakouts and limit stop hunts. Will deploy via deploy.sh once complete.

## 2026-05-27

### 15:07 IST
- **Task:** Debug missing Stop Loss on third auto-trade today.
- **Complexity:** Complex
- **Files to Investigate:**
  - `workers/auto_trader.py` (execute_auto_trade SL placement logic)
  - `fyers_client.py` (place_order / SL order API calls)
  - VM logs: `startup.out`, `logs/signals.log`, `logs/trades.csv`
- **Description:** User reports that the third trade placed today did not have a Stop Loss order placed with the broker. Investigating server logs, Fyers API responses, and the SL placement code path to identify the root cause and fix it.

### 15:40 IST
- **Task:** Implement "One Trade Per Strike Per Day" rule.
- **Complexity:** Medium
- **Files Modified:**
  - `engine/automation.py` (TradingState to track traded_strikes_today)
  - `engine/strikes.py` (get_strike_recommendations to filter exclude_symbols)
  - `workers/auto_trader.py` (Pass excluded symbols, append on execution)
- **Description:** Implemented logic to prevent the algorithm from selecting and trading the exact same strike price more than once per day. If a strike has already been traded (profit, loss, or active), the strike selection engine will skip it and find the next best available strike based on OI, Delta, and Theta. Changes deployed to cloud.

### 16:00 IST
- **Task:** Upgrade Strategy 2 (9:26 - 180 Buy) to continuous scanning.
- **Complexity:** Medium
- **Files Modified:**
  - `engine/strategy_926.py`
- **Description:** Removed the 9:26:00 10-second "snapshot" lock-in rule. Strategy 2 will now continuously scan the entire NIFTY option chain (±500 points around ATM) between 9:26 AM and 9:35 AM. The first option (CE or PE) to cross into the ₹183–₹186 target zone, while aligning with the global market trend, will instantly trigger a BUY order. Changes deployed to cloud.

## 2026-05-29

### 11:15 IST
- **Task:** Revert Strategy 2 to Lock-In Method and remove Trend Filters.
- **Complexity:** Medium
- **Files Modified:**
  - `engine/strategy_926.py`
- **Description:** Per user request, reverted Strategy 2 back to the original lock-in mechanism. It now takes a snapshot at 9:26:00 AM, locks the single CE and PE closest to ₹180, and monitors exclusively those two strikes until 9:35 AM. Additionally, removed all market trend logic. Whichever locked-in strike hits ₹183 first will execute immediately, regardless of the overall market momentum. Changes deployed to cloud.

### 11:30 IST
- **Task:** Implemented Strategy 5: Optimized Aerospace Mean Reversion.
- **Complexity:** High
- **Files Modified:**
  - `engine/strategy_5.py` (New)
  - `workers/auto_trader.py`
  - `engine/automation.py`
  - `app.py`
- **Description:** Developed a highly advanced quantitative option buying strategy based on a Kalman Filter state estimator. The engine parses live + historical Nifty 3-minute data to compute a smoothed Fair Value Line (FVL) and a 20-bar 2.5 SD Flight Envelope. Trades are triggered on bearish/bullish volume-confirmed reversals back into the envelope. Orders are routed strictly as Cover Orders (CO) and use dynamic ATR-based trailing SL once the index crosses the FVL. Implemented a strict 45-bar time guardrail. Changes deployed to cloud.

### June 3, 2026 - 12:40 IST
- **Task:** Modify Trade Count Logic to track only losing trades.
- **Complexity:** Normal
- **Files Modified:**
  - `engine/automation.py`
  - `workers/market_worker.py`
- **Details:** Updating the core trading state logic so that the daily "Max Trades" limit functions as a "Max Losing Trades" limit. Removed the increment from the entry `record_trade()` function and moved it to `record_trade_close()`, which now increments the count only if the trade PnL is strictly negative. Also updated the manual trade syncing logic in `market_worker.py` to only count closed positions that resulted in a loss.

### June 3, 2026 - 12:56 IST
- **Task:** Implement Strict Real-Time Max Loss Per Day/Trade Limit
- **Complexity:** Normal/Complex
- **Files Modified:**
  - `workers/auto_trader.py`
- **Details:** Refactored the `trailing_monitor` background task to enforce the `max_loss_per_day` setting instantly at the tick-level. Introduced a fast `ws_feed.get_quotes_from_ws()` check before the existing Emergency Exit block to evaluate the real-time MTM of every active auto-trade. If ANY single trade's running loss breaches the max loss limit, or the total combined PnL breaches the limit, the bot will immediately hard-stop, exit all positions, and disable automation.

### June 3, 2026 - 13:07 IST
- **Task:** Quick fix: Remove trade decrement on profit
- **Complexity:** Simple
- **Files Modified:**
  - `workers/auto_trader.py`
- **Details:** Removed `state.trades_today = max(0, state.trades_today - 1)` from `auto_trader.py` so that a profitable trade explicitly does NOT change the trade counter, ensuring it only increments on loss, perfectly aligning with the previously requested logic.

### June 4, 2026 - 15:51 IST
- **Task:** Server Management, 3:14 PM Hard Exit & Mobile Responsiveness
- **Complexity:** Complex
- **Files to Modify:**
  - `trading-app/app.py` — Add `POST /api/admin/restart-server` endpoint, `daily_restart_scheduler()` (8:55 AM auto-restart), `daily_hard_exit_scheduler()` (3:14 PM exit all trades), register both in lifespan
  - `trading-app/static/index.html` — Add admin-only "🔄 Restart Server" button in settings drawer (below Fyers API Setup) and left sidebar drawer (below Fyers API)
  - `trading-app/static/app.js` — Add `restartServer()` function, show/hide restart buttons for admins in `updateAuthUI()`
  - `trading-app/static/admin.html` — Add mobile-responsive CSS media queries for stacked layout, scrollable table, and touch-friendly buttons
- **Details:** Implementing four features: (1) Admin manual server restart via UI button that sends SIGTERM so systemd restarts the process. (2) Automated 8:55 AM daily restart to guarantee fresh Fyers token before market open. (3) 3:14 PM hard exit scheduler that closes all active positions across all users. (4) Mobile responsiveness for admin panel with proper media queries.
