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

        for cfg in all_strategies:
            strat = cfg['strategy_name']
            status = cfg.get('status', 'APPROVED')
            is_paper_trading = cfg.get('is_paper_trading', 1)
            total = int(cfg.get('total_trades', 0))
            wins = int(cfg.get('winning_trades', 0))
            win_rate = round(wins / total * 100, 1) if total > 0 else 0.0
            
            logger.info(f"📊 {strat} - Win Rate: {win_rate}% | Status: {status} | Paper Trading: {is_paper_trading}")

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
                    continuous_losses=cfg.get('continuous_losses', 0),
                    asset_class=cfg.get('asset_class', 'EQUITY')
                )
                
            # --- Auto-Reenable DISABLED Strategies ---
            if status == 'DISABLED':
                logger.info(f"🔧 Diagnosing and Re-enabling DISABLED strategy: {strat}")
                # We will let the AI critique it below, and then reset it to APPROVED
                cfg['status'] = 'APPROVED'
                cfg['continuous_losses'] = 0

            # AI Critique (Self-Improvement)
            market_regime = getattr(state, "market_regime", "NEUTRAL")
            
            prompt = f"""
            You are a Quantitative Trading AI.
            Our strategy '{strat}' operated in a '{market_regime}' market today.
            It took {total} trades with a win rate of {win_rate}%.
            
            Suggest optimized hyperparameters for tomorrow to improve this win rate.
            Return ONLY a valid JSON object with parameters like 'ema_period', 'breakout_threshold', 'stop_loss_pct'.
            Example: {{"ema_period": 10, "stop_loss_pct": 0.5}}
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
                        
                        if is_major:
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
                                continuous_losses=cfg.get('continuous_losses', 0),
                                asset_class=cfg.get('asset_class', 'EQUITY')
                            )
                            # Alert Telegram
                            msg = f"<b>Major Parameter Shift Proposed!</b>\nStrategy: <i>{strat}</i>\nChanges: {', '.join(major_changes)}\n\nPlease go to your Dashboard to approve this change."
                            await send_webhook_alert(webhook_url, msg, title="⚠️ AI Strategy Upgrade (Pending)")
                        else:
                            # Save to AgentDB directly
                            await Database.update_agent_config(
                                strategy_name=strat,
                                config_dict=new_config,
                                win_rate=win_rate,
                                total_trades=total,
                                winning_trades=wins,
                                status=cfg['status'],
                                pending_config_json=cfg.get('pending_config_json'),
                                is_paper_trading=cfg.get('is_paper_trading', 1),
                                continuous_losses=cfg.get('continuous_losses', 0),
                                asset_class=cfg.get('asset_class', 'EQUITY')
                            )
                            # Alert Telegram
                            msg = f"<b>Minor Optimization Applied</b>\nStrategy: <i>{strat}</i>\nNew Config: <code>{json_str}</code>"
                            await send_webhook_alert(webhook_url, msg, title="🔄 AI Strategy Optimized")
                        
                        analysis_text = response.replace(json_str, "").strip()
                        if not analysis_text:
                            analysis_text = f"Analyzed {strat} in {market_regime} regime. Optimized hyperparameters based on mathematical patterns to improve future win rate."
                        
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
            if com_trades:
                cur_params = getattr(state, "commodity_params", {})
                wins = sum(1 for t in com_trades if t.get("result") == "profit" or (t.get("pnl", 0) or 0) > 0)
                wr = round(wins / len(com_trades) * 100, 1)
                ai = AIEngine()
                com_prompt = f"""
                You are a Quantitative Commodity (MCX) options-trading AI.
                Today the commodity strategy family took {len(com_trades)} paper trades with a {wr}% win rate.
                Current commodity parameters: {json.dumps(cur_params)}.
                Crude/commodity options move ~2-4% intraday (vs index <1%). Suggest refined multipliers to
                improve tomorrow's win rate. Return ONLY JSON like
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
