import asyncio
import logging
from datetime import datetime
import pytz
import json
import os
import aiosqlite
from models import Database
from engine.ai_engine import AIEngine

logger = logging.getLogger("NIGHTLY_LEARNING")
IST = pytz.timezone('Asia/Kolkata')

# ── SELF-TUNING (owner directive 30/31-07-26 + STRICT LOSS LEARNING 03-08-26) ──
# Reads REAL results from the executed-trades ledger + 3-month 5-min market structure.
# STRICT RULE (owner): losing trades ALWAYS force AI critique — even a single closed loss
# bypasses MIN_TRADES_FOR_LEARNING. Aggregate-only tuning (no losses yet) still needs
# >= MIN_TRADES_FOR_LEARNING closed trades so noise does not rewrite params.
# Auto-apply rails:
#   • AUTO_APPLY_MINOR=True: MINOR AI parameter changes (<=20% per-param swing) auto-apply
#     when learning runs (loss-driven OR enough trades).
#   • MAJOR changes (>20% swing) STILL go PENDING/approval-required unless
#     REQUIRE_APPROVAL_FOR_MAJOR=False.
# NOTE (merge 19-08-26): the backtest pipeline (run_backtests_cron.py, backtest_results,
# stats_source provenance badges) is retained, but it is NOT the tuning input — the executed-trades
# ledger is. Backtest numbers stay informational/dashboard-only.
SELF_TUNING_ENABLED = True
AUTO_APPLY_MINOR = True
REQUIRE_APPROVAL_FOR_MAJOR = True
MIN_TRADES_FOR_LEARNING = 10
# Max losing-trade rows injected into the AI prompt (keeps tokens bounded).
MAX_LOSS_TRADES_IN_PROMPT = 25


def _format_losing_trades_for_prompt(losing_trades: list) -> str:
    """Compact, loss-first ledger dump for the nightly AI critique."""
    if not losing_trades:
        return "No closed losing trades in the lookback window."
    lines = []
    for i, t in enumerate(losing_trades, 1):
        lines.append(
            f"{i}. {t.get('trade_date','?')} {t.get('symbol','?')} "
            f"{t.get('side','?')} qty={t.get('qty','?')} | "
            f"entry ₹{float(t.get('entry_price') or 0):.2f} → exit ₹{float(t.get('exit_price') or 0):.2f} | "
            f"PnL ₹{float(t.get('pnl') or 0):.2f} | "
            f"SL pts={t.get('sl_points')} method={t.get('sl_method')} "
            f"initial_sl={t.get('initial_sl_price')} final_sl={t.get('final_sl_price')} "
            f"trails={t.get('sl_trail_count')} | "
            f"regime={t.get('regime')} trend={t.get('trend')} | "
            f"entry_reason={t.get('entry_reason') or '-'} | "
            f"exit_reason={t.get('exit_reason') or '-'}"
        )
    return "\n".join(lines)


def should_run_self_tuning(total_trades: int, loss_count: int) -> tuple:
    """Gate for nightly AI param changes.
    Returns (should_run: bool, reason: str).
    STRICT: any closed loss (loss_count >= 1) ALWAYS runs learning.
    Without losses, require >= MIN_TRADES_FOR_LEARNING closed trades.
    """
    if not SELF_TUNING_ENABLED:
        return False, "SELF_TUNING_ENABLED=False"
    losses = int(loss_count or 0)
    total = int(total_trades or 0)
    if losses >= 1:
        return True, f"STRICT loss-learning ({losses} closed losses)"
    if total >= MIN_TRADES_FOR_LEARNING:
        return True, f"aggregate tuning ({total} trades, 0 losses)"
    return False, (
        f"no losses and real trades={total} (need ≥{MIN_TRADES_FOR_LEARNING} "
        "or ≥1 closed loss) — no AI param change"
    )


async def _build_market_context(user_id, days=90, lookback_trades_days=30):
    """Summarize ~3 MONTHS of 5-MINUTE candles per traded underlying for the nightly strategy
    analysis (owner directive 30-07-26: 'check the 5 min charts for past 3 months for analysing
    the strategies'). 3 months of 5-min bars is ~4.7k per symbol — far too much to feed an LLM raw —
    so this computes compact per-symbol stats: 3-month trend, volatility (5-min + daily range),
    up/down/flat day mix, and where price sits in the 3-month range. Best-effort; never raises."""
    import datetime as _dt
    lines = []
    try:
        rows = await Database.get_executed_trades(days=lookback_trades_days)
        unders = []
        for r in rows:
            u = r.get("underlying") or r.get("symbol")
            if u and u not in unders:
                unders.append(u)
        unders = unders[:6]  # cap: each symbol pulls 3 months of 5-min in ~3 chunked calls
        if not unders:
            return "No underlyings traded in the lookback window to analyse."
        from fyers_client import FyersClient
        fc = FyersClient(user_id=user_id)
        for u in unders:
            try:
                candles = await asyncio.to_thread(fc.get_history_range, u, "5", days)
                if not candles or len(candles) < 20:
                    lines.append(f"{u}: insufficient 5-min history ({len(candles) if candles else 0} bars).")
                    continue
                # 5-min volatility (whole window vs most-recent ~5 sessions ≈ 390 bars)
                rngs = [c["high"] - c["low"] for c in candles]
                avg5 = sum(rngs) / len(rngs)
                tail = rngs[-390:] or rngs
                recent5 = sum(tail) / len(tail)
                vol_trend = "rising" if recent5 > avg5 * 1.15 else ("falling" if recent5 < avg5 * 0.85 else "stable")
                # Aggregate 5-min bars into daily O/H/L/C
                by_day = {}
                for c in candles:
                    d = _dt.datetime.fromtimestamp(c["timestamp"], IST).strftime("%Y-%m-%d")
                    dd = by_day.get(d)
                    if dd is None:
                        by_day[d] = {"o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}
                    else:
                        dd["h"] = max(dd["h"], c["high"]); dd["l"] = min(dd["l"], c["low"]); dd["c"] = c["close"]
                dl = [by_day[k] for k in sorted(by_day)]
                up = sum(1 for d in dl if d["c"] > d["o"])
                down = sum(1 for d in dl if d["c"] < d["o"])
                flat = len(dl) - up - down
                avg_dr = sum(d["h"] - d["l"] for d in dl) / len(dl)
                hi = max(d["h"] for d in dl); lo = min(d["l"] for d in dl)
                last_c = dl[-1]["c"]
                pos = round((last_c - lo) / (hi - lo) * 100) if hi > lo else 50
                closes = [d["c"] for d in dl]
                first_avg = sum(closes[:20]) / len(closes[:20])
                last_avg = sum(closes[-20:]) / len(closes[-20:])
                trend = "UP" if last_avg > first_avg * 1.01 else ("DOWN" if last_avg < first_avg * 0.99 else "SIDEWAYS")
                lines.append(
                    f"{u}: {len(dl)}d/{len(candles)} 5m-bars | 3mo trend {trend} | "
                    f"avg daily range {avg_dr:.1f} | avg 5m range {avg5:.2f} (recent {vol_trend}) | "
                    f"up/down/flat days {up}/{down}/{flat} | 3mo hi {hi:.1f} lo {lo:.1f}, now {pos}% of range")
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"3-month 5-min market context failed: {e}")
    return "\n".join(lines) if lines else "No market context available."

async def run_nightly_learning(state, user_id: int):
    """
    Runs after market close.
    1. Calculates Win Rate from today's trades.
    2. Uses Gemini to critique the strategy and provide updated hyperparameters.
    3. Saves to AgentDB so strategies are smarter the next day.
    """
    logger.info("🌙 Nightly Learning Agent Initiated...")
    
    try:
        # --- Global Macro Analysis & Market Watch Injection ---
        try:
            logger.info("🌍 Scanning Global News for Commodities, Currencies & Stocks volatility...")
            ai = AIEngine()
            macro_prompt = """
            You are a Global Macro Analyst AI. Based on current market conditions, identify the top 3 most volatile and tradeable INDIAN STOCK UNDERLYINGS right now that have LIQUID weekly/monthly option chains and are good candidates for options buying.

            CRITICAL — output rules (do NOT break these):
            1. Return the UNDERLYING symbol only, NOT a specific option contract. The app derives the
               actual option strike/expiry itself from the live option chain.
            2. Use the EXACT NSE equity format: "NSE:<SYMBOL>-EQ" (e.g. "NSE:RELIANCE-EQ", "NSE:SBIN-EQ").
            3. Only real, currently-listed NSE stocks that HAVE option chains. Do NOT invent symbols,
               strikes, or expiries. If unsure a symbol is real, skip it.
            4. Do NOT return commodities (MCX) or currencies (CDS) — the platform cannot trade those yet.

            Return ONLY a valid JSON object with a "symbols" array of underlying equity symbols.
            Example: {"symbols": ["NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ", "NSE:SBIN-EQ"]}
            """
            macro_response = await ai._call_chain(macro_prompt)
            if macro_response:
                start_idx = macro_response.find('{')
                end_idx = macro_response.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = macro_response[start_idx:end_idx+1]
                    macro_data = json.loads(json_str)
                    new_symbols = macro_data.get("symbols", [])
                    injected = 0
                    # VALIDATE each AI-suggested symbol against Fyers before adding it. The model
                    # hallucinates non-existent symbols (bad option/expiry strings) which Fyers then
                    # rejects on the WebSocket (-300), churning the feed (the disconnect storm) and
                    # wasting option-chain calls. Only real, quotable symbols get in; capped at 3 so
                    # the watchlist doesn't balloon (each symbol adds option-chain load).
                    try:
                        from fyers_client import FyersClient
                        _vc = FyersClient(user_id=user_id)
                    except Exception:
                        _vc = None
                    for new_symbol in new_symbols:
                        if injected >= 3:
                            break
                        if not new_symbol or new_symbol in state.active_symbols:
                            continue
                        valid = False
                        if _vc is not None:
                            try:
                                q = _vc.get_quote(new_symbol)
                                valid = bool(q and q.get("lp", 0) > 0)
                            except Exception:
                                valid = False
                        if not valid:
                            logger.warning(f"⏭️ Skipped invalid/unquotable macro symbol: {new_symbol}")
                            continue
                        state.active_symbols.append(new_symbol)
                        injected += 1
                        logger.info(f"💉 Injected VALID options script into Market Watch: {new_symbol}")
                    if injected > 0:
                        state.save()
        except Exception as e:
            logger.error(f"Global Macro Injection Error: {e}")
            
        # --- Hindsight AI Review (Cognitive Risk Orchestrator) ---
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        orchestrator_logs = await Database.get_daily_orchestrator_memory(date_str)
        if orchestrator_logs:
            logger.info(f"🧠 Conducting Hindsight AI Review on {len(orchestrator_logs)} Orchestrator decisions...")
            ai = AIEngine()
            for log in orchestrator_logs:
                win_strat = log.get("winning_strategy")
                rej_strats = log.get("rejected_strategies")
                market_regime = log.get("market_regime", "UNKNOWN")
                
                win_perf = await Database.get_agent_config(win_strat)
                win_rate = win_perf.get("win_rate", 0.0) if win_perf else 0.0
                
                prompt = f"""
                You are the Cognitive Risk Orchestrator for an AI trading swarm.
                In today's {market_regime} market, you received multiple conflicting signals simultaneously.
                You chose to execute: '{win_strat}' (Current Win Rate: {win_rate}%).
                You rejected: '{rej_strats}'.
                
                Based on historical strategy dynamics, was this the correct tie-breaker decision for a {market_regime} regime? 
                Provide a brief hindsight analysis and suggest contextual weight adjustments to improve future conflict resolution.
                """
                
                response = await ai._call_chain(prompt)
                if response:
                    logger.info(f"🔮 Hindsight Analysis for {win_strat} vs [{rej_strats}]:\n{response.strip()}")
        else:
            logger.info("No orchestrator conflicts today. Skipping Hindsight review.")
        # ---------------------------------------------------------

        # Fetch ALL strategies from DB, not just state.active_strategies, because DISABLED ones won't be in state
        all_strategies = await Database.get_all_agent_configs()
        if not all_strategies:
            logger.info("No strategies found in DB. Skipping learning.")
            return

        # REAL per-strategy performance from the executed-trades ledger (authoritative), not the
        # legacy swarm_agent_configs counters the old broken recorder left at 0.
        # Merge note (19-08-26): a local branch had briefly switched this to
        # Database.get_backtest_performance(). That switch is deliberately NOT kept — tuning a
        # live-money strategy must be justified by REAL closed trades. The backtest pipeline
        # (run_backtests_cron.py / backtest_results / stats_source badges) remains, but only as
        # informational dashboard provenance, never as the tuning input.
        perf = await Database.get_strategy_performance(days=30)
        # 3-month 5-minute chart context (stats) for the underlyings actually traded (shared).
        candle_context = await _build_market_context(user_id, days=90)
        logger.info(f"🌙 Nightly learning: real perf for {len(perf)} strategies; 3mo 5-min context:\n{candle_context}")

        for cfg in all_strategies:
            strat = cfg['strategy_name']
            status = cfg.get('status', 'APPROVED')
            is_paper_trading = cfg.get('is_paper_trading', 1)
            _p = perf.get(strat, {})
            total = int(_p.get('trades', 0))
            wins = int(_p.get('wins', 0))
            losses = int(_p.get('losses', 0))
            win_rate = float(_p.get('win_rate', 0.0))
            avg_pnl = float(_p.get('avg_pnl', 0.0))
            total_pnl = float(_p.get('total_pnl', 0.0))

            # Authoritative consecutive-loss streak from ledger (not the possibly-stale counter).
            ledger_streak = await Database.compute_continuous_loss_streak(strat)
            cfg['continuous_losses'] = ledger_streak

            logger.info(
                f"📊 {strat} - Win Rate: {win_rate}% ({wins}/{total}, losses={losses}, "
                f"₹{total_pnl:.0f}) | streak={ledger_streak} | Status: {status} | Paper: {is_paper_trading}"
            )

            # --- Automated Graduation ---
            if is_paper_trading == 1 and total >= 10 and win_rate >= 65.0:
                logger.info(f"🎓 Graduation Event! {strat} achieved {win_rate}% over {total} trades. Graduating to Live Trading.")
                cfg['is_paper_trading'] = 0
                await Database.update_agent_config(
                    strategy_name=strat,
                    config_dict=cfg.get('config_json', {}),
                    win_rate=win_rate,
                    total_trades=total,
                    winning_trades=wins,
                    status=status,
                    pending_config_json=cfg.get('pending_config_json'),
                    is_paper_trading=0,
                    continuous_losses=ledger_streak,
                    asset_class=cfg.get('asset_class', 'EQUITY')
                )

            # --- Auto-Reenable DISABLED Strategies ---
            # Only re-enable when the ledger streak is broken (no active consecutive losses).
            # If still bleeding, keep DISABLED and still run loss-learning below.
            # (06-08-26 fix preserved: the flip is PERSISTED below by the sync write, so it no
            # longer depends on the AI critique succeeding.)
            if status == 'DISABLED':
                if ledger_streak == 0:
                    logger.info(f"🔧 Re-enabling DISABLED strategy (loss streak cleared): {strat}")
                    cfg['status'] = 'APPROVED'
                    cfg['continuous_losses'] = 0
                    status = 'APPROVED'
                else:
                    logger.info(
                        f"🟥 Keeping {strat} DISABLED — ledger streak={ledger_streak}; "
                        "STRICT loss-learning will still critique losing trades."
                    )

            # Sync status + continuous_losses onto the config row even when we skip AI
            # (keeps the dashboard truthful and persists the re-enable above without AI).
            try:
                await Database.update_agent_config(
                    strategy_name=strat,
                    config_dict=cfg.get('config_json', {}) if isinstance(cfg.get('config_json'), dict)
                    else (cfg.get('config_json') or {}),
                    win_rate=win_rate,
                    total_trades=total,
                    winning_trades=wins,
                    status=cfg.get('status', status),
                    pending_config_json=cfg.get('pending_config_json'),
                    is_paper_trading=cfg.get('is_paper_trading', is_paper_trading),
                    continuous_losses=cfg.get('continuous_losses', ledger_streak),
                    asset_class=cfg.get('asset_class', 'EQUITY'),
                )
            except Exception as _sync_e:
                logger.warning(f"continuous_losses sync failed for {strat}: {_sync_e}")

            # ═══════════════════════════════════════════
            # STRICT RULE-BASED capital protection (owner directive 06-08-26): "AI provider should
            # not stop any nightly learning ... it is only seeing the technical analysis and
            # updating the strategies." This block is a deterministic capital-protection rule that
            # uses ONLY the REAL ledger numbers already computed above (trades/win_rate/total_pnl) —
            # no AI call, no text generation. It runs and can take effect regardless of whether the
            # AI critique below succeeds or fails.
            #
            # Uses NET PnL, not win rate, as the deciding signal — win rate alone is misleading for
            # breakout/momentum strategies with an asymmetric payoff (wins much bigger than losses;
            # a naive win-rate cutoff would wrongly flag them).
            #
            # A strategy that is net-LOSING over a real sample (>= MIN_TRADES_FOR_LEARNING closed
            # trades) is moved into shadow mode (simulated-only) — not fully disabled, so it keeps
            # proving/disproving itself risk-free rather than being permanently written off.
            # ═══════════════════════════════════════════
            if total >= MIN_TRADES_FOR_LEARNING:
                shadow_list = list(getattr(state, "shadow_strategies", None) or [])
                already_shadowed = strat in shadow_list
                if total_pnl <= 0 and not already_shadowed:
                    shadow_list.append(strat)
                    state.shadow_strategies = shadow_list
                    state.save()
                    reason = (f"Net-losing over {total} real closed trades (₹{total_pnl:.0f} total, "
                              f"{win_rate}% win, ₹{avg_pnl:.0f} avg/trade) — moved to shadow mode "
                              f"to protect capital.")
                    logger.warning(f"🛡️ RULE-BASED (no AI): {strat} -> SHADOW. {reason}")
                    try:
                        await Database.insert_learning_log(
                            strategy_name=strat,
                            llm_analysis=f"[STRICT RULE-BASED, no AI involved] {reason}",
                            old_config=json.dumps({"shadow": already_shadowed}),
                            new_config=json.dumps({"shadow": True}),
                        )
                    except Exception as _le:
                        logger.warning(f"insert_learning_log failed for {strat}: {_le}")
                    try:
                        async with aiosqlite.connect(Database.DB_NAME) as conn:
                            cursor = await conn.execute("SELECT webhook_url FROM user_states WHERE user_id=?", (user_id,))
                            row = await cursor.fetchone()
                            webhook_url = row[0] if row else os.getenv("TELEGRAM_WEBHOOK", "")
                        from engine.notifier import send_webhook_alert
                        await send_webhook_alert(
                            webhook_url, f"Strategy: <i>{strat}</i>\n{reason}",
                            title="🛡️ Nightly Learning — Moved to Shadow (rule-based, no AI)")
                    except Exception as _e:
                        logger.warning(f"Shadow-move alert failed for {strat}: {_e}")
                elif total_pnl > 0:
                    logger.info(f"✅ RULE-BASED (no AI): {strat} net-positive "
                                f"(₹{total_pnl:.0f} over {total} trades) — no status change needed.")
                elif already_shadowed:
                    logger.info(f"🛡️ RULE-BASED (no AI): {strat} still net-losing/shadowed — no change "
                                f"(promotion back to live is handled by the graduation rule above, not here).")

            # AI Critique — STRICT: any closed loss forces learning. BEST-EFFORT ADDITION on top of
            # the rule-based action above, never a requirement for tonight's run to have had effect.
            run_tune, tune_reason = should_run_self_tuning(total, losses)
            if not run_tune:
                logger.info(f"🧊 Self-tuning skipped for {strat}: {tune_reason} "
                            f"(this does NOT affect the rule-based action above).")
                continue
            logger.info(f"🧠 Self-tuning for {strat}: {tune_reason}")

            losing_trades = await Database.get_losing_trades(
                days=30, strategy_name=strat, limit=MAX_LOSS_TRADES_IN_PROMPT
            )
            loss_block = _format_losing_trades_for_prompt(losing_trades)
            market_regime = getattr(state, "market_regime", "NEUTRAL")

            prompt = f"""
            You are a Quantitative Trading AI. Your PRIMARY job is to LEARN FROM LOSING TRADES.
            Strategy: '{strat}', recent market regime: '{market_regime}'.

            Real performance over the last 30 days (executed-trades ledger):
              - trades: {total}, wins: {wins}, LOSSES: {losses}, win rate: {win_rate}%
              - total P&L: ₹{total_pnl:.0f}, avg P&L/trade: ₹{avg_pnl:.0f}
              - continuous loss streak (newest → older): {ledger_streak}

            STRICT LOSS REVIEW — analyze EACH losing trade below. Identify root causes
            (chased entry, late breakout, fade-into-trend, stop too tight/wide, wrong regime,
            bad exit reason). Parameter changes MUST be justified by these losses.
            Prefer FEWER LOSSES over more wins.

            LOSING TRADES (newest first):
            {loss_block}

            3-MONTH 5-MINUTE chart statistics for underlyings traded (trend, volatility,
            daily range, up/down day mix, position in range):
            {candle_context}

            Return ONLY a valid JSON object with hyperparameters to reduce future losses
            (e.g. 'ema_period', 'breakout_threshold', 'stop_loss_pct', 'entry_chase_buffer_pct').
            Example: {{"ema_period": 10, "stop_loss_pct": 0.5, "entry_chase_buffer_pct": 0.3}}
            """
            
            try:
                ai = AIEngine()
                response = await ai._call_chain(prompt)
                
                if response:
                    start_idx = response.find('{')
                    end_idx = response.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        json_str = response[start_idx:end_idx+1]
                        new_config = json.loads(json_str)
                        
                        # Fetch old config
                        old_config_row = await Database.get_agent_config(strat)
                        old_config = old_config_row['config_json'] if old_config_row and 'config_json' in old_config_row else {}
                        
                        # Compare for > 20% diff
                        is_major = False
                        major_changes = []
                        for k, v in new_config.items():
                            if isinstance(v, (int, float)) and k in old_config:
                                old_val = old_config[k]
                                if old_val != 0:
                                    diff_pct = abs((v - old_val) / old_val)
                                    if diff_pct > 0.20:
                                        is_major = True
                                        major_changes.append(f"{k}: {old_val} -> {v}")
                        
                        # Get Webhook URL
                        async with aiosqlite.connect(Database.DB_NAME) as conn:
                            cursor = await conn.execute("SELECT webhook_url FROM user_states WHERE user_id=?", (user_id,))
                            row = await cursor.fetchone()
                            webhook_url = row[0] if row else os.getenv("TELEGRAM_WEBHOOK", "")

                        from engine.notifier import send_webhook_alert
                        
                        if is_major and REQUIRE_APPROVAL_FOR_MAJOR:
                            logger.info(f"🚨 Major change detected for {strat}: {major_changes}")
                            # Save to AgentDB as PENDING (keep old config active)
                            await Database.update_agent_config(
                                strategy_name=strat,
                                config_dict=old_config,
                                win_rate=win_rate,
                                total_trades=total,
                                winning_trades=wins,
                                status='PENDING',
                                pending_config_json=json_str,
                                is_paper_trading=cfg.get('is_paper_trading', 1),
                                continuous_losses=ledger_streak,
                                asset_class=cfg.get('asset_class', 'EQUITY')
                            )
                            await Database.insert_pending_tuning(
                                strategy_name=strat,
                                param_name="major_config",
                                old_val=json.dumps(old_config),
                                proposed_val=json_str,
                                expectancy_delta=0.0,
                                reason=f"Major parameter shift: {', '.join(major_changes)}"
                            )
                            # Alert Telegram
                            msg = f"<b>Major Parameter Shift Proposed!</b>\nStrategy: <i>{strat}</i>\nChanges: {', '.join(major_changes)}\n\nPlease go to your Dashboard to approve this change."
                            await send_webhook_alert(webhook_url, msg, title="⚠️ AI Strategy Upgrade (Pending)")
                        elif AUTO_APPLY_MINOR:
                            # Minor change + owner opted into auto-apply: write it live.
                            await Database.update_agent_config(
                                strategy_name=strat,
                                config_dict=new_config,
                                win_rate=win_rate,
                                total_trades=total,
                                winning_trades=wins,
                                status=cfg['status'],
                                pending_config_json=cfg.get('pending_config_json'),
                                is_paper_trading=cfg.get('is_paper_trading', 1),
                                continuous_losses=ledger_streak,
                                asset_class=cfg.get('asset_class', 'EQUITY')
                            )
                            msg = f"<b>Minor Optimization Applied</b>\nStrategy: <i>{strat}</i>\nNew Config: <code>{json_str}</code>"
                            await send_webhook_alert(webhook_url, msg, title="🔄 AI Strategy Optimized")
                        else:
                            # DEFAULT SAFE PATH: even minor changes are PROPOSED (PENDING), never
                            # auto-applied to a live strategy. Owner approves on the dashboard.
                            await Database.update_agent_config(
                                strategy_name=strat,
                                config_dict=old_config,
                                win_rate=win_rate,
                                total_trades=total,
                                winning_trades=wins,
                                status='PENDING',
                                pending_config_json=json_str,
                                is_paper_trading=cfg.get('is_paper_trading', 1),
                                continuous_losses=ledger_streak,
                                asset_class=cfg.get('asset_class', 'EQUITY')
                            )
                            await Database.insert_pending_tuning(
                                strategy_name=strat,
                                param_name="minor_config",
                                old_val=json.dumps(old_config),
                                proposed_val=json_str,
                                expectancy_delta=0.0,
                                reason="Loss-driven / minor optimization proposed by Nightly Learning"
                            )
                            msg = f"<b>Optimization Proposed (Pending Approval)</b>\nStrategy: <i>{strat}</i>\nProposed: <code>{json_str}</code>\nWin rate {win_rate}% over {total} trades ({losses} losses). Approve on the Dashboard to apply."
                            await send_webhook_alert(webhook_url, msg, title="🔄 AI Strategy Proposal (Pending)")
                        
                        analysis_text = response.replace(json_str, "").strip()
                        if not analysis_text:
                            analysis_text = (
                                f"STRICT loss review for {strat} in {market_regime}: "
                                f"{losses} losses / {total} trades (streak={ledger_streak}). "
                                f"Parameters tuned to reduce repeat losses."
                            )
                        
                        await Database.insert_learning_log(
                            strategy_name=strat,
                            llm_analysis=analysis_text,
                            old_config=json.dumps(old_config),
                            new_config=json_str
                        )
                        
                        logger.info(f"🧠 {strat} Upgraded! New Config: {new_config}")
                    else:
                        logger.warning(f"⚠️ Failed to parse AI config for {strat}: {response}")
            except Exception as e:
                logger.error(f"❌ AI Critique failed for {strat}: {e}")
                
        # ── Commodity strategy family AI-tuning (the "advised by AI" evolution) ──
        # Review today's COMMODITY paper trades and let the AI refine state.commodity_params
        # (sl / target / breakout-buffer multipliers), separate from the equity tuning above. Only
        # runs when commodity trades exist — until the paper signal-watch produces crude trades there
        # is nothing to tune, so it cleanly no-ops.
        try:
            closed = getattr(state, "closed_trades_today", []) or []
            com_trades = [t for t in closed if str(t.get("symbol", "")).startswith(("MCX:", "CDS:"))]
            if com_trades and SELF_TUNING_ENABLED:
                cur_params = getattr(state, "commodity_params", {})
                wins = sum(1 for t in com_trades if t.get("result") == "profit" or (t.get("pnl", 0) or 0) > 0)
                wr = round(wins / len(com_trades) * 100, 1)
                ai = AIEngine()
                com_prompt = f"""
                You are a Quantitative Commodity (MCX) options-trading AI.
                PRIMARY JOB: learn from LOSING trades.
                Today the commodity strategy family took {len(com_trades)} paper trades with a {wr}% win rate.
                Losing trades today: {json.dumps([
                    {"symbol": t.get("symbol"), "pnl": t.get("pnl")}
                    for t in com_trades
                    if (t.get("pnl", 0) or 0) < 0 or t.get("result") == "loss"
                ], default=str)}.
                Current commodity parameters: {json.dumps(cur_params)}.
                Crude/commodity options move ~2-4% intraday (vs index <1%). Suggest refined multipliers that
                REDUCE FUTURE LOSSES. Return ONLY JSON like
                {{"sl_multiplier": 1.8, "target_multiplier": 2.0, "breakout_buffer_mult": 1.6}}.
                Keep each value between 1.0 and 3.0.
                """
                resp = await ai._call_chain(com_prompt)
                if resp:
                    si, ei = resp.find('{'), resp.rfind('}')
                    if si != -1 and ei != -1:
                        new_p = json.loads(resp[si:ei + 1])
                        clean = {}
                        for k in ("sl_multiplier", "target_multiplier", "breakout_buffer_mult"):
                            v = new_p.get(k)
                            if isinstance(v, (int, float)) and 1.0 <= v <= 3.0:
                                clean[k] = round(float(v), 2)
                        if clean:
                            state.commodity_params = {**cur_params, **clean}
                            state.save()
                            logger.info(f"🛢️ Commodity params AI-tuned ({wr}% WR over {len(com_trades)} trades): {state.commodity_params}")
            else:
                logger.info("🛢️ No commodity paper trades today — commodity params unchanged.")
        except Exception as e:
            logger.error(f"❌ Commodity params tuning failed: {e}")

        logger.info("✅ Nightly Learning Complete. Agents are ready for tomorrow.")

    except Exception as e:
        logger.error(f"❌ Nightly Learning Error: {e}")

if __name__ == "__main__":
    class MockState:
        active_strategies = ["Strategy 3: 5-Minute ORB"]
        market_regime = "BULLISH"
        
    asyncio.run(run_nightly_learning(MockState(), 1))
