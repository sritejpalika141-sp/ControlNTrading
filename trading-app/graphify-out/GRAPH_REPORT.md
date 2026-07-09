# Graph Report - .  (2026-06-20)

## Corpus Check
- 68 files · ~92,331 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1795 nodes · 4193 edges · 118 communities (79 shown, 39 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 81 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 97|Community 97]]
- [[_COMMUNITY_Community 98|Community 98]]
- [[_COMMUNITY_Community 110|Community 110]]
- [[_COMMUNITY_Community 111|Community 111]]
- [[_COMMUNITY_Community 115|Community 115]]
- [[_COMMUNITY_Community 116|Community 116]]

## God Nodes (most connected - your core abstractions)
1. `_()` - 161 edges
2. `FyersClient` - 66 edges
3. `an` - 62 edges
4. `xn` - 62 edges
5. `fn` - 57 edges
6. `f()` - 56 edges
7. `os()` - 53 edges
8. `Request` - 51 edges
9. `qi` - 51 edges
10. `Database` - 47 edges

## Surprising Connections (you probably didn't know these)
- `Any` --uses--> `Database`  [INFERRED]
  fyers_client.py → models.py
- `trailing_monitor()` --conceptually_related_to--> `Strategy 3: 5-Minute ORB`  [INFERRED]
  workers/auto_trader.py → dailyupdates.md
- `trailing_monitor()` --conceptually_related_to--> `Strategy 5: Optimized Aerospace Mean Reversion`  [INFERRED]
  workers/auto_trader.py → dailyupdates.md
- `MockAIEngine` --uses--> `TradingState`  [INFERRED]
  app.py → engine/automation.py
- `MockAIEngine` --uses--> `FyersClient`  [INFERRED]
  app.py → fyers_client.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Fyers Authentication Flow** — fyers_client_fyersclient, models_database, state_user_contexts [INFERRED 0.85]
- **Background Workers** — workers_auto_trader_trailing_monitor, workers_market_worker_market_data_worker, workers_news_worker_newsworker_run [INFERRED 0.85]

## Communities (118 total, 39 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (13): c(), en(), f(), fn, hn(), ki, ln(), nn() (+5 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (23): AIEngine, AIProvider, AI Engine Module — Multi-Provider AI Chain for Trading Signal Confirmation.  Pro, Call Google Gemini 2.0 Flash., Call Groq API (OpenAI-compatible, Llama 3.3 70B, free tier)., Call Anthropic Claude API directly via HTTP., Call OpenAI GPT-4o-mini., Call OpenRouter API (free Llama 3 8B). (+15 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (51): admin_add_user(), admin_analytics(), admin_change_password(), admin_change_pin(), admin_delete_user(), admin_list_users(), admin_page(), admin_user_activity() (+43 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (4): ge, ht(), st, vn

### Community 4 - "Community 4"
Cohesion: 0.05
Nodes (15): _(), ae(), Cn, ds(), H, he(), hi(), L (+7 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (13): TradingState, Database, decrypt_user_dict(), decrypt_val(), encrypt_val(), get_cipher(), Fetch Admin (is_admin=1) Fyers App ID and Secret as Master credentials for SaaS, Update both access and refresh tokens atomically. Pass None to skip a field. (+5 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (21): FyersWSFeed, Index Prev Close Reconstruction, Check if WebSocket is connected and receiving data., Get WebSocket feed stats., Subscribe to symbols for real-time data., Unsubscribe from symbols., Start the WebSocket data feed. Call once at app startup., Stop the WebSocket data feed and close connection. (+13 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (32): evaluate_926_strategy(), _find_180_strikes(), Strategy 2: 9:26 - 180 Buy At 9:26 AM, find CE and PE nearest to ₹180 (below). F, Find CE and PE strikes with LTP nearest but below ₹180., Find CE and PE strikes with LTP nearest but below ₹180., Strategy 2: 9:26 - 9:35 - 183 Buy     Selects CE/PE nearest to 183 (below) at 9:, evaluate_gap_fill_strategy(), Evaluates Strategy 6: Gap Fill Strategy (Complete Rewrite) (+24 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (10): Reset all daily counters for a fresh trading day., Check if a new trading day has started and reset if needed.         Called every, Check if a specific strategy already has an active trade running.         Each s, Dynamic cooldown based on last trade result., Record when a trade closes. result = 'profit', 'loss', 'manual', 'breakeven', Return current configurable trading parameters., Update configurable trading parameters from user input., Check if market is closed for the day and send EOD report. (+2 more)

### Community 11 - "Community 11"
Cohesion: 0.06
Nodes (18): activeScripts, appendActivityLog(), applyTheme(), bosSeriesList, fvgZoneSeries, globalPnLHistory, globalPnLLiveHistory, globalPnLPaperHistory (+10 more)

### Community 12 - "Community 12"
Cohesion: 0.10
Nodes (29): calculate_bollinger_bands(), calculate_rsi(), fetch_historical_data(), run_backtest(), _check_fvg_fill(), detect_fvg(), find_ob_fvg_confluence(), get_active_fvg() (+21 more)

### Community 15 - "Community 15"
Cohesion: 0.16
Nodes (7): bs(), gs(), hs(), ms, ps(), ws(), xs()

### Community 17 - "Community 17"
Cohesion: 0.08
Nodes (3): pt(), rt, vt()

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (4): bn(), gn, mn, qs()

### Community 19 - "Community 19"
Cohesion: 0.10
Nodes (23): AbstractEventLoop, get_nse_public_quotes(), Helper that queries the NSE India indices API and maps Nifty 50 and India VIX., Fyers WebSocket Real-Time Data Feed ==================================== Replace, Fyers API Client Wrapper Handles authentication, historical data, quotes, option, broadcast_log(), get_lot_size(), get_user_cache() (+15 more)

### Community 22 - "Community 22"
Cohesion: 0.13
Nodes (26): add_script(), get_automation(), get_current_client(), get_pnl_history(), get_positions(), get_scripts(), get_spot(), get_state() (+18 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (25): _calc_level_strength(), cluster_levels(), detect_intraday_trend(), detect_prev_day_levels(), detect_recent_bos(), detect_round_numbers(), detect_swing_highs(), detect_swing_lows() (+17 more)

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (3): bi(), di(), vi()

### Community 25 - "Community 25"
Cohesion: 0.13
Nodes (7): d(), ie(), ne, se(), te(), Un(), v()

### Community 26 - "Community 26"
Cohesion: 0.11
Nodes (16): ws_feed, FyersClient, Re-read token from DB and re-create the Fyers model. Call after token refresh., Modify an existing order.         order_type: 1 for LIMIT (Target), 4 for SL-LIM, Wrapper around Fyers API v3 for trading operations., Check if client is authenticated and working, with local caching., Alias for is_authenticated used by app.py., Initialize Fyers client with stored credentials. (+8 more)

### Community 27 - "Community 27"
Cohesion: 0.19
Nodes (3): ci(), ee(), gi

### Community 29 - "Community 29"
Cohesion: 0.10
Nodes (15): _candle_start_ts(), CandleBuilderEngine, _new_candle(), Candle Builder — Constructs 5m, 15m, 1H OHLCV candles from live WebSocket ticks., Return closed candles for the given symbol and timeframe.                  Args:, Return the currently forming (unclosed) candle., Seed the candle buffer with historical data from a one-time REST call., Check if a symbol has been seeded with historical data. (+7 more)

### Community 31 - "Community 31"
Cohesion: 0.13
Nodes (16): ai_oracle_scheduler(), fyers_token_refresh_scheduler(), hourly_status_scheduler(), lifespan(), Application lifespan: start background tasks on startup., Sends an hourly status report to Telegram for all users with configured webhooks, Sends the Pre-Market AI Oracle bias to Telegram at 8:30 AM and hourly during mar, Refresh Fyers tokens for all users via refresh_token (official API).     The old (+8 more)

### Community 32 - "Community 32"
Cohesion: 0.13
Nodes (10): Check if we are in a rate-limit cooldown period., Set a cooldown period (e.g., after a 429 error)., Fetch funds, positions, and orders in one batch with smart caching., Get live quote for a single symbol. Checks WebSocket cache first., Get the active client for public/data operations, falling back to admin or env v, Get live quotes for multiple symbols. Checks WebSocket cache first unless force_, Get historical candle data.          Args:             symbol: e.g., 'NSE:NIFTY5, Fetch option premiums around ATM using the official Fyers optionchain API. (+2 more)

### Community 34 - "Community 34"
Cohesion: 0.11
Nodes (10): Any, Returns the token in 'appid:token' format required for websockets., Initializes and connects the Fyers Data WebSocket., DEPRECATED: Fyers Vagator V2 API has been blocked (-1025 error).         This me, Generate the Fyers authorization URL., Exchange auth code for access token and save to Database (and .env for fallback), Fetch Admin's Master App ID and Secret as fallback for sub-users (SaaS model)., Save access token to Database (multi-user) and .env (fallback). (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.17
Nodes (3): jn(), lt, qn()

### Community 37 - "Community 37"
Cohesion: 0.16
Nodes (3): j, Ri, X()

### Community 38 - "Community 38"
Cohesion: 0.12
Nodes (4): I, oi(), ui(), wi()

### Community 40 - "Community 40"
Cohesion: 0.18
Nodes (3): ks(), ls(), us()

### Community 43 - "Community 43"
Cohesion: 0.15
Nodes (5): ct, dt(), E, R(), re()

### Community 44 - "Community 44"
Cohesion: 0.19
Nodes (14): anyNeutralOrRange(), clearBOS(), clearFVGZones(), clearKeyLevelLines(), clearOBZones(), fetchAnalysis(), handleVisibilityChange(), refreshAll() (+6 more)

### Community 45 - "Community 45"
Cohesion: 0.15
Nodes (14): closeAuthModal(), closeModal(), confirmOrder(), fetchAutomationStatus(), loadJournalEntries(), resetTradeCount(), restartServer(), runSystemCheck() (+6 more)

### Community 48 - "Community 48"
Cohesion: 0.19
Nodes (3): Et, kt(), zt

### Community 49 - "Community 49"
Cohesion: 0.17
Nodes (13): admin_restart_server(), auth_status(), broadcast_log(), daily_hard_exit_scheduler(), get_user_cache(), health_check(), _is_market_open(), Admin-only endpoint to gracefully restart the server process.     Relies on syst (+5 more)

### Community 50 - "Community 50"
Cohesion: 0.17
Nodes (11): get_analysis(), get_analysis_api(), get_quotes_endpoint(), get_quotes_with_fallback(), MockAIEngine, Get quotes from WS feed if available, otherwise fallback to REST API., Endpoint for retrieving quotes for a comma-separated list of symbols., Group 5-minute REST API candles into 15-minute candles. (+3 more)

### Community 51 - "Community 51"
Cohesion: 0.19
Nodes (12): Manually trigger a test signal to verify UI and History logic., test_signal(), init_logs(), log_signal(), log_trade(), Initialize log directory and files., Log generated high-confidence signals to a file., Log actual order placements. (+4 more)

### Community 54 - "Community 54"
Cohesion: 0.26
Nodes (12): Dashboard HTML, Landing Page HTML, Daily Updates Changelog, Strategy 1: OB + FVG, Strategy 2: 9:26 Breakout, Strategy 3: 5-Minute ORB, Strategy 4: Wisdom-Aligned Pullback, Strategy 5: Optimized Aerospace Mean Reversion (+4 more)

### Community 58 - "Community 58"
Cohesion: 0.27
Nodes (10): compute_kalman_filter(), compute_sd(), compute_sma(), evaluate_strat5_strategy(), get_live_3m_candles(), parse_nifty_3m_csv(), Strategy 5: Optimized Aerospace Mean Reversion, 1D Kalman Filter to compute Fair Value Line (FVL). (+2 more)

### Community 59 - "Community 59"
Cohesion: 0.22
Nodes (5): Place an order.         For MARKET orders: auto-fetches LTP and places as LIMIT, Place a stop loss order (SL-Limit, type=4).         For BUY entry → SL is SELL a, Place a target order (LIMIT, type=1)., Scans order book to find SL and TGT leg IDs for a given BO parent ID., Cancel an existing order.

### Community 60 - "Community 60"
Cohesion: 0.18
Nodes (4): Ft, vs(), wt, yt

### Community 61 - "Community 61"
Cohesion: 0.31
Nodes (3): js(), Me(), ue()

### Community 62 - "Community 62"
Cohesion: 0.22
Nodes (10): addScript(), fetchCandles(), fetchScripts(), fetchSpot(), removeScript(), renderScriptsList(), renderSymbolTabs(), selectScript() (+2 more)

### Community 65 - "Community 65"
Cohesion: 0.24
Nodes (3): b(), qt, Zs()

### Community 66 - "Community 66"
Cohesion: 0.22
Nodes (3): fi(), mi(), xt()

### Community 67 - "Community 67"
Cohesion: 0.24
Nodes (4): ot(), rs(), si, T()

### Community 68 - "Community 68"
Cohesion: 0.31
Nodes (8): calc_atr(), evaluate_swing_pivot_strategy(), get_latest_pivots_for_trailing(), is_in_no_trade_time(), Calculate ATR on a DataFrame with High, Low, Close columns., Helper function to recalculate the latest HL or LH for trailing stops.     Calle, Block entries during 9:15-9:30 AM and 3:00-3:15 PM., Evaluates Strategy 7: Intraday Swing-Pivot Breakout with optimizations:     - Do

### Community 69 - "Community 69"
Cohesion: 0.28
Nodes (9): fetchSignalHistory(), getLotSize(), openOrderFromSignal(), renderSignalHistory(), renderSignals(), renderStrikes(), selectStrikeForCalc(), skipSignal() (+1 more)

### Community 71 - "Community 71"
Cohesion: 0.22
Nodes (8): background_color, description, display, icons, name, short_name, start_url, theme_color

### Community 72 - "Community 72"
Cohesion: 0.29
Nodes (7): AuthSubmission, _exchange_fyers_auth_code(), OrderRequest, Receive auth code (or full redirect URL) and exchange for token (manual paste fa, Shared helper to exchange a Fyers auth_code for an access token.     Used by GET, submit_auth_code(), BaseModel

### Community 73 - "Community 73"
Cohesion: 0.38
Nodes (6): backtest_swing_pivot(), calc_atr(), is_in_no_trade_time(), Backtest: Strategy 7 — Intraday Swing-Pivot (HH/HL/LL/LH) Breakout Strategy Uses, Calculate ATR on a DataFrame with High, Low, Close columns., Block entries during 9:15-9:30 AM and 3:00-3:15 PM.

### Community 74 - "Community 74"
Cohesion: 0.33
Nodes (7): fetchFunds(), fetchPositions(), getLoggedInUser(), renderOrders(), renderPositions(), updateFundsLive(), updatePnlDisplays()

### Community 81 - "Community 81"
Cohesion: 0.33
Nodes (6): checkAuthStatus(), connectWebSocket(), showHolidayModal(), toggleAutomation(), updateAuthUI(), updateOnboardingWizard()

### Community 82 - "Community 82"
Cohesion: 0.40
Nodes (6): openPnLHistoryModal(), renderEquityChart(), renderHeatmapGrid(), renderPnLHistory(), switchPnLMode(), updatePnLModeButtons()

### Community 85 - "Community 85"
Cohesion: 0.50
Nodes (4): get_market_news(), Fetch and parse an RSS feed, using unverified SSL context to handle GCP CA issue, Proxy endpoint: fetches latest Indian market news from Economic Times RSS., _rss_get()

### Community 86 - "Community 86"
Cohesion: 0.50
Nodes (4): get_signal_history_api(), Get signal history from logger., get_signal_history(), Retrieve the most recent logged signals.

### Community 92 - "Community 92"
Cohesion: 0.67
Nodes (3): Control N Trading, Control N Trading Logo, AI Automated Trades

### Community 93 - "Community 93"
Cohesion: 0.67
Nodes (3): AI Automated Trades, Control N Trading, Control N Trading Logo

## Knowledge Gaps
- **33 isolated node(s):** `markers1h`, `markers5m`, `obZoneSeries`, `fvgZoneSeries`, `lastKnownActiveTrades` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_()` connect `Community 4` to `Community 0`, `Community 3`, `Community 5`, `Community 8`, `Community 13`, `Community 14`, `Community 15`, `Community 16`, `Community 17`, `Community 18`, `Community 20`, `Community 21`, `Community 24`, `Community 25`, `Community 27`, `Community 28`, `Community 30`, `Community 33`, `Community 35`, `Community 36`, `Community 37`, `Community 38`, `Community 39`, `Community 40`, `Community 41`, `Community 42`, `Community 43`, `Community 46`, `Community 47`, `Community 48`, `Community 52`, `Community 53`, `Community 56`, `Community 57`, `Community 60`, `Community 61`, `Community 63`, `Community 64`, `Community 65`, `Community 66`, `Community 67`, `Community 76`, `Community 77`, `Community 78`, `Community 79`, `Community 80`, `Community 84`, `Community 88`, `Community 89`, `Community 90`?**
  _High betweenness centrality (0.202) - this node is a cross-community bridge._
- **Why does `FyersClient` connect `Community 26` to `Community 32`, `Community 2`, `Community 34`, `Community 6`, `Community 72`, `Community 49`, `Community 50`, `Community 19`, `Community 81`, `Community 22`, `Community 59`, `Community 31`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `xn` connect `Community 5` to `Community 33`, `Community 4`, `Community 36`, `Community 13`, `Community 18`, `Community 56`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `FyersClient` (e.g. with `AbstractEventLoop` and `AuthSubmission`) actually correct?**
  _`FyersClient` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `NIFTY Options Trading Dashboard — FastAPI Backend`, `Application lifespan: start background tasks on startup.`, `Get the official NSE lot size (effective Jan 2026).` to the rest of the system?**
  _255 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.05238796549547654 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.07402597402597402 - nodes in this community are weakly interconnected._