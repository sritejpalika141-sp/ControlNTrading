import asyncio
import logging
from typing import Dict, List, Any, Optional
from models import Database
import time

logger = logging.getLogger("DASHBOARD")

class RiskOrchestrator:
    """
    Master Risk Agent for the Swarm Architecture.
    Collects proposed trades from all strategy agents in a single market tick (0 delay).
    Enforces global risk rules and breaks ties using historical win-rates from AgentDB.
    """
    def __init__(self):
        self.signal_buffer = {}  # u_id -> list of signals
        self.lock = asyncio.Lock()
        self._agent_config_cache = {}
        self._cache_last_updated = 0.0

    async def _get_agent_config(self, s_name: str) -> Dict:
        """Fetch from RAM cache, update from DB every 60s."""
        now = time.time()
        if not self._agent_config_cache or (now - self._cache_last_updated) > 60:
            try:
                # Load all configs at once or just rely on per-request
                self._cache_last_updated = now
            except Exception as e:
                logger.error(f"Error updating agent config cache: {e}")
        
        # We can just cache per strategy if it's missing or stale
        if s_name not in self._agent_config_cache or (now - self._agent_config_cache[s_name].get('_ts', 0)) > 60:
            config = await Database.get_agent_config(s_name)
            if config:
                config['_ts'] = now
                self._agent_config_cache[s_name] = config
            else:
                self._agent_config_cache[s_name] = {'_ts': now, 'win_rate': 0.0, 'total_trades': 0}
                
        return self._agent_config_cache[s_name]

    def propose_trade_sync(self, strategy_name: str, symbol: str, sig: Dict, analysis: Dict, client: Any, state: Any):
        """
        Legacy sync method (not used in async VIBE swarm).
        """
        u_id = client.user_id
        if u_id not in self.signal_buffer:
            self.signal_buffer[u_id] = []
            
        sig['strategy_name'] = strategy_name
        sig['symbol'] = symbol
        sig['analysis'] = analysis
        sig['client'] = client
        sig['state'] = state
        
        self.signal_buffer[u_id].append(sig)

    async def propose_trade(self, strategy_name: str, symbol: str, sig: Dict, analysis: Dict, client: Any, state: Any):
        """
        Called by individual strategy agents simultaneously when they generate a signal.
        The signal is buffered instantly using an async lock to prevent race conditions. NO DELAY.
        """
        u_id = client.user_id

        # High-confidence regime override (user policy). The breakout strategies (3 ORB / 6 Gap /
        # 7 Swing) used to be HARD-blocked whenever the Groq regime was CHOPPY_SIDEWAYS, which meant
        # no trades in choppy sessions. Instead, let them trade in choppy markets ONLY when the
        # signal clears the confidence floor (>=85); weaker signals are still skipped. Non-breakout
        # strategies are unaffected. This is the single chokepoint every strategy signal passes.
        import state as _state_mod
        if (getattr(_state_mod, "market_regime", "") or "").upper() == "CHOPPY_SIDEWAYS":
            if any(s in strategy_name for s in ("Strategy 3", "Strategy 6", "Strategy 7")):
                if sig.get("confidence", 0) < 85:
                    logger.info(f"⏭️ {strategy_name}: CHOPPY regime + confidence {sig.get('confidence', 0)} < 85 — skipped (high-confidence override).")
                    return

        sig['strategy_name'] = strategy_name
        sig['symbol'] = symbol
        sig['analysis'] = analysis
        sig['client'] = client
        sig['state'] = state
        
        # Atomic dictionary operation in Python (GIL), no asyncio.Lock needed
        if u_id not in self.signal_buffer:
            self.signal_buffer[u_id] = []
        self.signal_buffer[u_id].append(sig)

    async def flush_signals(self, u_id: int):
        """
        Called at the very end of the auto_trader loop.
        Instantly evaluates all collected signals from that single ~50ms loop iteration.
        """
        signals = self.signal_buffer.pop(u_id, [])
        if not signals:
            return
            
        valid_signals = []
        for sig in signals:
            state = sig['state']
            s_name = sig['strategy_name']
            
            # 1. Ask State if this strategy is allowed to trade
            can_trade, reason = state.can_trade(s_name, signal_type=sig.get('type', 'BUY'))
            if not can_trade:
                # Removed heavy logging in tight loop
                # logger.info(f"⏭️ Orchestrator blocked {s_name}: {reason}")
                continue
                
            # 2. Query AgentDB for strategy performance (Win Rate)
            agent_config = await self._get_agent_config(s_name)
            win_rate = agent_config.get('win_rate', 0.0) if agent_config else 0.0
            total_trades = agent_config.get('total_trades', 0) if agent_config else 0
            
            # Grace Period Logic: Ignore win rate and guarantee priority if under 5 trades
            effective_win_rate = 100.0 if total_trades < 5 else win_rate
            
            sig['win_rate'] = win_rate
            sig['effective_win_rate'] = effective_win_rate
            sig['total_trades'] = total_trades
            valid_signals.append(sig)
            
        if not valid_signals:
            return
            
        # Tie-Breaker: Sort by highest effective win rate
        valid_signals.sort(key=lambda x: x['effective_win_rate'], reverse=True)
        winning_sig = valid_signals[0]
        
        # --- Memory Logging for Hindsight AI ---
        if len(valid_signals) > 1:
            try:
                import state as _state_mod
                market_regime = getattr(_state_mod, "market_regime", "UNKNOWN")
                rejected = [s['strategy_name'] for s in valid_signals[1:]]
                # Log to DB in background so it doesn't block execution
                asyncio.create_task(
                    Database.insert_orchestrator_memory(winning_sig['strategy_name'], rejected, market_regime)
                )
                logger.info(f"🧠 Orchestrator logged conflict: picked {winning_sig['strategy_name']} over {len(rejected)} others in {market_regime} regime.")
            except Exception as mem_err:
                logger.error(f"Failed to log orchestrator memory: {mem_err}")
        # ----------------------------------------
        
        logger.info(f"🏆 Orchestrator selected {winning_sig['strategy_name']} (Win Rate: {winning_sig['win_rate']:.1f}%, Trades: {winning_sig.get('total_trades', 0)}) instantly out of {len(valid_signals)} signals.")
        
        # Execute the winning trade
        try:
            from workers.auto_trader import execute_auto_trade
            await execute_auto_trade(winning_sig['symbol'], winning_sig, winning_sig['analysis'], winning_sig['client'])
            
            # Handle post-execution state updates per strategy
            s_name = winning_sig['strategy_name']
            state = winning_sig['state']
            if s_name == "Strategy 3":
                state.strat_orb_triggered = True
                state.save()
            elif s_name == "Strategy 4":
                state.strat_4_trades = getattr(state, "strat_4_trades", 0) + 1
                state.save()
            elif s_name == "Strategy 6":
                state.strat_6_trades_today = getattr(state, "strat_6_trades_today", 0) + 1
                state.save()
                
        except Exception as e:
            logger.error(f"Orchestrator Execution Error for {winning_sig['strategy_name']}: {e}")

# Global singleton instance
orchestrator = RiskOrchestrator()
