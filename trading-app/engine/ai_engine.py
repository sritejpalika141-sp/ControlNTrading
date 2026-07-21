"""
AI Engine Module — Multi-Provider AI Chain for Trading Signal Confirmation.

Provider Chain (tried in order):
1. Google Gemini 2.0 Flash (free tier — 1500 req/day)
2. Groq (free tier — Llama 3.3 70B, 30 req/min)  
3. Anthropic Claude (premium)
4. OpenAI GPT-4o-mini (premium)
5. Technical fallback (always works, no AI needed)
"""
import os
import asyncio
import json
import logging
import time
import httpx
from typing import Dict, List, Optional
from dotenv import load_dotenv
from pathlib import Path
from .encryption import get_secret

# Throttle for the "AI fully unavailable" alert (full-chain failure). Module-level so it is shared
# across the many AIEngine() instances created around the app. Routine single-provider 429s are NOT
# alerted (they auto-recover via fall-through); only a full-chain failure is, at most once / 15 min.
_LAST_CHAIN_FAIL_ALERT = 0.0




# Setup logging
logger = logging.getLogger("AI_ENGINE")

# Load environment
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR.parent / "fyers-mcp-server" / ".env"
load_dotenv(ENV_PATH)


class AIProvider:
    def __init__(self, name: str, enabled: bool = True, keys: List[str] = None):
        self.name = name
        self.enabled = enabled
        self.keys = keys if keys else []
        self.current_key_idx = 0
        
        self.fail_count = 0
        self.success_count = 0
        self.cooldown_until = 0
        self.quota_exhausted = False
        
    def get_key(self) -> str:
        """Get the current key and rotate to the next one for round-robin usage."""
        if not self.keys:
            return ""
        key = self.keys[self.current_key_idx]
        self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
        return key

    def is_available(self) -> bool:
        if not self.enabled or self.quota_exhausted:
            return False
        if time.time() < self.cooldown_until:
            return False
        return True
    
    def on_success(self):
        self.fail_count = 0
        self.success_count += 1
    
    def on_rate_limit(self, cooldown_seconds: int = 300):
        """Temporary cooldown (e.g., 429 rate limit)."""
        # If we have multiple keys, a 429 just means THIS key is dead. 
        # But for simplicity, we'll just log and maybe apply a short cooldown 
        # so we don't spam if all keys are dead.
        if len(self.keys) > 1:
            cooldown_seconds = 5 # Very short cooldown if rotating keys
            logger.warning(f"⏳ {self.name}: Rate limited. Rotating to next key (cooldown {cooldown_seconds}s).")
        else:
            logger.warning(f"⏳ {self.name}: Rate limited. Cooldown for {cooldown_seconds}s.")
            
        self.fail_count += 1
        self.cooldown_until = time.time() + cooldown_seconds
        # NOTE: no Telegram alert on a routine 429. A single-provider rate limit is auto-recovered
        # by the fall-through to the next provider (~1s), so alerting here was pure noise (one msg
        # every ~30 min). Real problems are still alerted: on_quota_exhausted (permanent disable) and
        # a full-chain failure in _call_chain (every provider failed).
    
    def on_quota_exhausted(self):
        """Permanent disable for this session (e.g., insufficient_quota)."""
        self.quota_exhausted = True
        self.enabled = False
        logger.error(f"❌ {self.name}: Quota exhausted. Disabled for this session.")
        
        try:
            import os
            from engine.notifier import trigger_webhook_background
            wh_url = os.environ.get("TELEGRAM_WEBHOOK")
            if wh_url:
                trigger_webhook_background(wh_url, f"❌ <b>AI Quota Exhausted</b>\nProvider <b>{self.name}</b> quota is completely exhausted and has been disabled.", title="AI Alert")
        except Exception:
            pass


class AIEngine:
    def __init__(self):
        self._cache = {}
        self.providers = {}
        
        # === 1. Google Gemini (Free Tier) ===
        raw_gemini = get_secret("GOOGLE_API_KEYS") or get_secret("GOOGLE_API_KEY")
        gemini_keys = [k.strip() for k in raw_gemini.split(",") if k.strip()]
        self.providers["gemini"] = AIProvider("Gemini", enabled=bool(gemini_keys), keys=gemini_keys)
        if gemini_keys:
            logger.info(f"✅ Gemini AI initialized (free tier) with {len(gemini_keys)} keys.")
        
        # === 2. Groq (Free Tier — Llama 3.3 70B) ===
        raw_groq = get_secret("GROQ_API_KEYS") or get_secret("GROQ_API_KEY")
        groq_keys = [k.strip() for k in raw_groq.split(",") if k.strip()]
        self.providers["groq"] = AIProvider("Groq", enabled=bool(groq_keys), keys=groq_keys)
        if groq_keys:
            logger.info(f"✅ Groq AI initialized (free tier) with {len(groq_keys)} keys.")
        else:
            logger.info("ℹ️ Groq not configured. Get a free key at https://console.groq.com")
        
        # === 3. Anthropic Claude ===
        self.claude_key = get_secret("ANTHROPIC_API_KEY") or get_secret("CLAUDE_API_KEY")
        self.providers["claude"] = AIProvider("Claude", enabled=bool(self.claude_key))
        if self.claude_key:
            logger.info("✅ Claude AI initialized.")
        else:
            logger.info("ℹ️ Claude not configured. Set ANTHROPIC_API_KEY in .env")
        
        # === 4. OpenAI (Premium) ===
        openai_key = get_secret("OPENAI_API_KEY")
        self.providers["openai"] = AIProvider("OpenAI", enabled=False)
        if openai_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_key)
                self.providers["openai"].enabled = True
                logger.info("✅ OpenAI initialized (premium fallback).")
            except Exception as e:
                logger.error(f"❌ OpenAI init failed: {e}")
        
        # === 5. OpenRouter (Free Fallback) ===
        self.openrouter_key = get_secret("OPENROUTER_API_KEY")
        self.providers["openrouter"] = AIProvider("OpenRouter", enabled=bool(self.openrouter_key))
        if self.openrouter_key:
            logger.info("✅ OpenRouter AI initialized (free fallback).")
        else:
            logger.info("ℹ️ OpenRouter not configured. Get a free key at https://openrouter.ai")

        # === 6. Hugging Face (Free Open Source) ===
        self.hf_key = get_secret("HF_API_KEYS") or get_secret("HF_API_KEY")
        self.providers["huggingface"] = AIProvider("HuggingFace", enabled=bool(self.hf_key))
        if self.hf_key:
            logger.info("✅ HuggingFace AI initialized (free open source).")

        # === 7. GitHub Models (GPT-4o-mini Free) ===
        self.github_key = get_secret("GITHUB_API_KEYS") or get_secret("GITHUB_API_KEY")
        self.providers["github"] = AIProvider("GitHub", enabled=bool(self.github_key))
        if self.github_key:
            logger.info("✅ GitHub AI initialized (free GPT-4o-mini).")

        # === 8. Ollama (Local AI Fallback) ===
        # Always enable Ollama. It will gracefully fail if the service is down.
        self.providers["ollama"] = AIProvider("Ollama", enabled=True)
        logger.info("✅ Ollama Local AI initialized (ultimate fallback).")

        # Log provider chain
        active = [p.name for p in self.providers.values() if p.enabled]
        logger.info(f"🔗 AI Provider Chain: {' → '.join(active) if active else 'Technical Only'}")
        
        # Backward compat
        self.enabled = any(p.enabled for p in self.providers.values())
        self.openai_enabled = self.providers["openai"].enabled

    # ==================== CACHE ====================
    def _get_cache(self, key: str, duration: int) -> Optional[Dict]:
        if key in self._cache:
            entry = self._cache[key]
            if time.time() - entry["ts"] < duration:
                return entry["result"]
        return None

    def _set_cache(self, key: str, result: Dict):
        self._cache[key] = {"result": result, "ts": time.time()}

    # ==================== PROVIDER CALLS ====================
    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Google Gemini 2.0 Flash."""
        prov = self.providers["gemini"]
        if not prov.is_available():
            return None
        try:
            # Fail-fast timeout (5s): a real Gemini flash response is ~1-2s; if it's slower than
            # 5s in the trade hot path we drop to the next provider rather than stall the trade.
            async with httpx.AsyncClient(timeout=5.0) as client:
                api_key = prov.get_key()
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        # maxOutputTokens caps generation time — the confirm JSON is tiny (~50 tokens).
                        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json", "maxOutputTokens": 128}
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    prov.on_success()
                    return content
                elif response.status_code == 429:
                    prov.on_rate_limit(120)
                    return None
                else:
                    prov.fail_count += 1
                    logger.error(f"Gemini HTTP {response.status_code}: {response.text[:200]}")
                    return None
        except Exception as e:
            prov.fail_count += 1
            logger.error(f"Gemini error: {e}")
            return None

    async def _call_groq(self, prompt: str) -> Optional[str]:
        """Call Groq API (OpenAI-compatible, Llama 3.3 70B, free tier)."""
        prov = self.providers["groq"]
        if not prov.is_available():
            return None
        try:
            # Fail-fast timeout (5s): Groq LPU typically responds in ~0.3-0.6s; 5s is ample
            # headroom while still dropping to the next provider quickly if Groq stalls.
            async with httpx.AsyncClient(timeout=5.0) as client:
                api_key = prov.get_key()
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": "You are a professional trading assistant. Respond with valid JSON only."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "max_tokens": 256
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    prov.on_success()
                    return content
                elif response.status_code == 429:
                    prov.on_rate_limit(60)  # 1 min cooldown
                    return None
                else:
                    prov.fail_count += 1
                    logger.error(f"Groq HTTP {response.status_code}: {response.text[:200]}")
                    return None
        except Exception as e:
            prov.fail_count += 1
            logger.error(f"Groq error: {e}")
            return None

    async def _call_claude(self, prompt: str) -> Optional[str]:
        """Call Anthropic Claude API directly via HTTP."""
        prov = self.providers["claude"]
        if not prov.is_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.claude_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 256,
                        "messages": [
                            {"role": "user", "content": f"{prompt}\n\nRespond with valid JSON only, no other text."}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["content"][0]["text"]
                    prov.on_success()
                    return content
                elif response.status_code == 429:
                    prov.on_rate_limit(120)
                    return None
                elif response.status_code in (401, 403):
                    prov.on_quota_exhausted()
                    return None
                else:
                    prov.fail_count += 1
                    logger.error(f"Claude HTTP {response.status_code}: {response.text[:200]}")
                    return None
        except Exception as e:
            prov.fail_count += 1
            logger.error(f"Claude error: {e}")
            return None

    async def _call_openai(self, prompt: str) -> Optional[str]:
        """Call OpenAI GPT-4o-mini."""
        prov = self.providers["openai"]
        if not prov.is_available():
            return None
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.openai_client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a professional trading assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"}
                ),
                timeout=10.0
            )
            content = response.choices[0].message.content
            prov.on_success()
            return content
        except Exception as e:
            err = str(e)
            if "insufficient_quota" in err or "billing" in err.lower():
                prov.on_quota_exhausted()
            elif "429" in err:
                prov.on_rate_limit(60)
            else:
                prov.fail_count += 1
                logger.error(f"OpenAI error: {e}")
            return None

    async def _call_openrouter(self, prompt: str) -> Optional[str]:
        """Call OpenRouter API (free Llama 3 8B)."""
        prov = self.providers["openrouter"]
        if not prov.is_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "meta-llama/llama-3-8b-instruct:free",
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "user", "content": f"{prompt}\n\nRespond strictly with JSON only."}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    prov.on_success()
                    return content
                elif response.status_code == 429:
                    prov.on_rate_limit(60)
                    return None
                else:
                    prov.fail_count += 1
                    logger.error(f"OpenRouter HTTP {response.status_code}: {response.text[:200]}")
                    return None
        except Exception as e:
            prov.fail_count += 1
            logger.error(f"OpenRouter error: {e}")
            return None

    async def _call_huggingface(self, prompt: str) -> Optional[str]:
        """Call Hugging Face API (Mistral/Llama)."""
        prov = self.providers["huggingface"]
        if not prov.is_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2",
                    headers={
                        "Authorization": f"Bearer {self.hf_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "inputs": f"[INST] {prompt}\n\nRespond strictly with JSON only. [/INST]",
                        "parameters": {"temperature": 0.2, "max_new_tokens": 256, "return_full_text": False}
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data[0]["generated_text"].strip()
                    # HF sometimes wraps json in markdown
                    if content.startswith("```json"):
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif content.startswith("```"):
                        content = content.split("```")[1].split("```")[0].strip()
                    prov.on_success()
                    return content
                elif response.status_code == 429:
                    prov.on_rate_limit(60)
                    return None
                else:
                    prov.fail_count += 1
                    logger.error(f"HuggingFace HTTP {response.status_code}: {response.text[:200]}")
                    return None
        except Exception as e:
            prov.fail_count += 1
            logger.error(f"HuggingFace error: {e}")
            return None

    async def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call local Ollama running on server."""
        prov = self.providers["ollama"]
        if not prov.is_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": "llama3.2:3b",
                        "prompt": f"{prompt}\n\nRespond strictly with JSON only.",
                        "stream": False,
                        "format": "json"
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("response", "").strip()
                    prov.on_success()
                    return content
                else:
                    prov.fail_count += 1
                    return None
        except Exception as e:
            # Short cooldown so it doesn't spam localhost if Ollama is not installed
            prov.on_rate_limit(10)
            return None

    async def _call_github(self, prompt: str) -> Optional[str]:
        """Call GitHub Models API (gpt-4o-mini)."""
        prov = self.providers["github"]
        if not prov.is_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://models.inference.ai.azure.com/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.github_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "user", "content": f"{prompt}\n\nRespond strictly with JSON only."}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    prov.on_success()
                    return content
                elif response.status_code == 429:
                    prov.on_rate_limit(60)
                    return None
                else:
                    prov.fail_count += 1
                    logger.error(f"GitHub HTTP {response.status_code}: {response.text[:200]}")
                    return None
        except Exception as e:
            prov.fail_count += 1
            logger.error(f"GitHub error: {e}")
            return None

    async def _call_chain(self, prompt: str, force_provider: str = None) -> Optional[str]:
        """Try each provider in the chain until one succeeds."""
        if force_provider:
            providers = [force_provider.lower()]
        else:
            # Groq first: fastest free inference (LPU, ~0.3-0.6s) and generous rate limits.
            # Gemini demoted to 2nd — it is fast but rate-limits (429) frequently, which added
            # a wasted round-trip + fall-through on every trade when it was first.
            providers = ["groq", "gemini", "github", "claude", "openai", "huggingface", "openrouter", "ollama"]
            
        for name in providers:
            caller = {
                "gemini": self._call_gemini,
                "groq": self._call_groq,
                "github": self._call_github,
                "claude": self._call_claude,
                "openai": self._call_openai,
                "huggingface": self._call_huggingface,
                "openrouter": self._call_openrouter,
                "ollama": self._call_ollama,
            }.get(name)
            
            if caller:
                result = await caller(prompt)
                if result:
                    return result

        # Full-chain failure: every provider failed for this request. THIS is alert-worthy (AI is
        # effectively down) — but only for the real chain, and throttled to once / 15 min so a
        # sustained outage doesn't spam.
        if not force_provider:
            global _LAST_CHAIN_FAIL_ALERT
            if time.time() - _LAST_CHAIN_FAIL_ALERT > 900:
                _LAST_CHAIN_FAIL_ALERT = time.time()
                try:
                    from engine.notifier import trigger_webhook_background
                    wh = os.environ.get("TELEGRAM_WEBHOOK")
                    if wh:
                        trigger_webhook_background(
                            wh,
                            "❌ <b>AI Unavailable</b>\nEvery AI provider failed for the last request "
                            "(all rate-limited or down). Signals may be delayed until one recovers.",
                            title="AI Alert",
                        )
                except Exception:
                    pass
        return None

    # ==================== PUBLIC API ====================
    async def confirm_signal(self, symbol: str, signal: Dict, context: Dict) -> Dict:
        """Takes a technical signal and market context, returns AI confirmation."""
        sig_id = signal.get("sig_id", f"{symbol}_{signal.get('type')}_{signal.get('time')}")
        cached = self._get_cache(f"conf_{sig_id}", 60)
        if cached:
            return cached

        # Check if any provider is available
        if not any(p.is_available() for p in self.providers.values()):
            res = {
                "ai_confidence": signal.get("confidence", 70),
                "ai_rationale": "All AI providers busy. Using technical analysis confidence.",
                "ai_status": "technical"
            }
            self._set_cache(f"conf_{sig_id}", res)
            return res

        try:
            prompt = self._build_prompt(symbol, signal, context)
            raw = await self._call_chain(prompt)
            
            if raw:
                result = json.loads(raw)
                res = {
                    "ai_confidence": result.get("confidence", 50),
                    "ai_rationale": result.get("rationale", "No rationale provided."),
                    "ai_status": "confirmed"
                }
            else:
                res = {
                    "ai_confidence": signal.get("confidence", 50),
                    "ai_rationale": "AI analysis failed. Using base technical confidence.",
                    "ai_status": "technical"
                }
            
            self._set_cache(f"conf_{sig_id}", res)
            return res
            
        except json.JSONDecodeError:
            logger.error(f"Failed to parse AI JSON: {raw}")
            return {
                "ai_confidence": signal.get("confidence", 50),
                "ai_rationale": "AI returned malformed data.",
                "ai_status": "error"
            }
        except Exception as e:
            logger.error(f"AI Confirmation Error: {e}")
            return {
                "ai_confidence": signal.get("confidence", 50),
                "ai_rationale": f"AI Engine error: {e}",
                "ai_status": "error"
            }

    async def get_ai_trend(self, symbol: str, context: Dict) -> Dict:
        """Determines the trend using AI."""
        cached = self._get_cache(f"trend_{symbol}", 120)
        if cached:
            return cached

        # Check if any provider is available
        if not any(p.is_available() for p in self.providers.values()):
            res = {
                "trend": "NEUTRAL",
                "strength": 50,
                "rationale": "All AI providers busy. Defaulting to neutral."
            }
            self._set_cache(f"trend_{symbol}", res)
            return res

        try:
            prompt = self._build_trend_prompt(symbol, context)
            raw = await self._call_chain(prompt)
            
            if raw:
                result = json.loads(raw)
                res = {
                    "trend": result.get("trend", "NEUTRAL").upper(),
                    "strength": result.get("strength", 50),
                    "rationale": result.get("rationale", "No rationale provided.")
                }
            else:
                res = {
                    "trend": "NEUTRAL",
                    "strength": 50,
                    "rationale": "AI models busy. Defaulting to neutral trend."
                }
            
            self._set_cache(f"trend_{symbol}", res)
            return res

        except Exception as e:
            logger.error(f"AI Trend Error: {e}")
            res = {
                "trend": "NEUTRAL",
                "strength": 50,
                "rationale": f"AI Error: {str(e)[:80]}"
            }
            self._set_cache(f"trend_{symbol}", res)
            return res

    async def get_simple_trend(self, scrip_name: str, spot: float = 0,
                                vix: float = 0, chp: float = 0) -> Dict:
        """Simplified trend check — asks the AI a basic directional question.
        
        Used by the Trend Regime Analyzer for final confirmation after
        the multi-timeframe math has already agreed on a direction.
        
        Args:
            scrip_name: e.g. "NIFTY 50" or "BANKNIFTY"
            spot: Current price
            vix: India VIX value
            chp: Day change percentage
        """
        cache_key = f"simple_trend_{scrip_name}"
        cached = self._get_cache(cache_key, 300)  # 5-minute cache
        if cached:
            cached["cached"] = True
            return cached

        # If no AI provider available → default to NEUTRAL (safe)
        if not any(p.is_available() for p in self.providers.values()):
            res = {
                "trend": "NEUTRAL",
                "strength": 50,
                "rationale": "All AI providers busy. Defaulting to neutral (Capital Protection).",
                "ai_status": "unavailable",
                "cached": False,
            }
            self._set_cache(cache_key, res)
            return res

        try:
            prompt = self._build_simple_trend_prompt(scrip_name, spot, vix, chp)
            raw = await self._call_chain(prompt)

            if raw:
                result = json.loads(raw)
                res = {
                    "trend": result.get("trend", "NEUTRAL").upper(),
                    "strength": result.get("strength", 50),
                    "rationale": result.get("rationale", "No rationale provided."),
                    "ai_status": "confirmed",
                    "cached": False,
                }
            else:
                res = {
                    "trend": "NEUTRAL",
                    "strength": 50,
                    "rationale": "AI models busy. Defaulting to neutral (Capital Protection).",
                    "ai_status": "fallback",
                    "cached": False,
                }

            self._set_cache(cache_key, res)
            return res

        except Exception as e:
            logger.error(f"AI Simple Trend Error: {e}")
            res = {
                "trend": "NEUTRAL",
                "strength": 50,
                "rationale": f"AI Error: {str(e)[:80]}. Defaulting to neutral.",
                "ai_status": "error",
                "cached": False,
            }
            self._set_cache(cache_key, res)
            return res

    async def run_trading_agent(self, system_prompt: str, user_prompt: str, force_provider: str = None) -> dict:
        """Runs the complex trading agent prompt through the multi-provider LLM chain."""
        if not force_provider and not any(p.is_available() for p in self.providers.values()):
            return {"signal_type": "NO_SIGNAL", "reason": "All AI providers busy or rate limited."}
        
        try:
            full_prompt = f"{system_prompt}\n\n==============================\n\n{user_prompt}"
            raw = await self._call_chain(full_prompt, force_provider=force_provider)
            
            if not raw:
                return {"signal_type": "NO_SIGNAL", "reason": "All AI providers failed to return a response."}
                
            # Extract JSON block
            raw_text = raw.strip()
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            brace_start = raw_text.find("{")
            brace_end = raw_text.rfind("}") + 1
            if brace_start != -1 and brace_end > brace_start:
                json_str = raw_text[brace_start:brace_end]
            else:
                json_str = raw_text

            signal = json.loads(json_str)
            return signal
            
        except json.JSONDecodeError:
            logger.error(f"Failed to parse Agent JSON: {raw}")
            return {"signal_type": "PARSE_ERROR", "raw_response": str(raw)}
        except Exception as e:
            logger.error(f"Agent Execution Error: {e}")
            return {"signal_type": "ERROR", "reason": str(e)}

    # ==================== PROMPTS ====================
    def _build_simple_trend_prompt(self, scrip_name: str, spot: float = 0, vix: float = 0, chp: float = 0) -> str:
        """Minimal prompt for the Trend Regime Analyzer.
        
        IMPORTANT: This prompt MUST include actual market data.
        Without it, the AI will hallucinate and can give opposite signals.
        """
        # Build market context from REAL data
        market_info = f"Current Spot Price: {spot}" if spot else "Spot: Unknown"
        vix_info = f"India VIX: {vix}" if vix else ""
        chp_info = ""
        if chp:
            direction = "UP" if chp > 0 else "DOWN"
            chp_info = f"Day Change: {chp:+.2f}% ({direction} from previous close)"

        return f"""
You are a concise intraday trend judge for {scrip_name} (Indian stock market).
Use ONLY the REAL-TIME data below. Do NOT use training data or assume direction.

MARKET DATA:
- {market_info}
{f'- {vix_info}' if vix_info else ''}
{f'- {chp_info}' if chp_info else ''}

RULES (apply in this order):
1. If day change > +0.15% → BULLISH (strength 55-70)
2. If day change < -0.15% → BEARISH (strength 55-70)
3. If day change is between -0.15% and +0.15% → NEUTRAL (strength 40-55)
4. If VIX > 20 AND direction is unclear (<0.3% change) → NEUTRAL (strength 35-50)
5. NEVER default to BEARISH without a negative day change as evidence.
6. Respond with NEUTRAL if data is insufficient or ambiguous.

Respond ONLY with this JSON:
{{"trend": "BULLISH" | "BEARISH" | "NEUTRAL", "strength": <0-100>, "rationale": "<1 sentence citing the actual data>"}}"""

    async def get_global_macro_summary(self, headlines: List[str]) -> Dict:
        """Summarizes global market sentiment for multiple asset classes."""
        if not self.enabled:
            return {
                "equities_trend": "NEUTRAL",
                "commodities_trend": "NEUTRAL",
                "currency_trend": "NEUTRAL",
                "summary": "AI disabled.",
                "high_conviction_asset": "NONE",
                "commodity_pick": "NONE"
            }
        
        prompt = (
            "You are a Global Macro Quantitative Analyst. "
            "Based on the following recent news headlines, provide a brief summary of the overall market sentiment "
            "across three asset classes: Indian Equities (NIFTY), Commodities (Crude Oil, Gold), and Currencies (USDINR).\n"
            "If the news indicates a clear Bullish or Bearish trend for a specific asset (Commodity, Currency, or Indian Stock), "
            "identify the most promising one in 'high_conviction_asset' (otherwise output 'NONE'). For Indian stocks, output the NSE ticker (e.g. RELIANCE, HDFCBANK, INFY). You do not need a massive catalyst, just a clear directional bias.\n\n"
            "SEPARATELY, always pick the single most active/newsworthy MCX COMMODITY in 'commodity_pick' "
            "(CRUDEOIL, GOLD, SILVER, NATURALGAS, COPPER or ZINC). This is a DEDICATED slot: commodities "
            "compete only with each other here, never with equities. Only output 'NONE' if the headlines "
            "contain nothing at all about commodities — prefer CRUDEOIL as the default liquid choice.\n\n"
            "Headlines:\n" + "\n".join(f"- {h}" for h in headlines) + "\n\n"
            "Respond ONLY with this JSON format:\n"
            '{\n'
            '  "equities_trend": "BULLISH" | "BEARISH" | "NEUTRAL",\n'
            '  "commodities_trend": "BULLISH" | "BEARISH" | "NEUTRAL",\n'
            '  "currency_trend": "BULLISH" | "BEARISH" | "NEUTRAL",\n'
            '  "summary": "<2-3 sentences max summarizing the drivers>",\n'
            '  "high_conviction_asset": "CRUDEOIL" | "GOLD" | "SILVER" | "USDINR" | "<NSE_TICKER>" | "NONE",\n'
            '  "commodity_pick": "CRUDEOIL" | "GOLD" | "SILVER" | "NATURALGAS" | "COPPER" | "ZINC" | "NONE"\n'
            '}'
        )

        for prov_name in self.providers:
            prov = self.providers[prov_name]
            if not prov.is_available(): continue
            try:
                if prov_name == "gemini":
                    raw_res = await self._call_gemini(prompt)
                elif prov_name == "groq":
                    raw_res = await self._call_groq(prompt)
                elif prov_name == "github":
                    raw_res = await self._call_github(prompt)
                elif prov_name == "claude":
                    raw_res = await self._call_claude(prompt)
                elif prov_name == "openai":
                    raw_res = await self._call_openai(prompt)
                elif prov_name == "huggingface":
                    raw_res = await self._call_huggingface(prompt)
                elif prov_name == "openrouter":
                    raw_res = await self._call_openrouter(prompt)
                elif prov_name == "ollama":
                    raw_res = await self._call_ollama(prompt)
                
                if raw_res:
                    result = json.loads(raw_res)
                    prov.on_success()
                    return {
                        "equities_trend": result.get("equities_trend", "NEUTRAL").upper(),
                        "commodities_trend": result.get("commodities_trend", "NEUTRAL").upper(),
                        "currency_trend": result.get("currency_trend", "NEUTRAL").upper(),
                        "summary": result.get("summary", "No clear sentiment."),
                        "high_conviction_asset": result.get("high_conviction_asset", "NONE").upper(),
                        "commodity_pick": str(result.get("commodity_pick", "NONE") or "NONE").upper()
                    }
            except Exception as e:
                logger.warning(f"⚠️ {prov.name} news summary failed: {e}")
                
        return {
            "equities_trend": "NEUTRAL",
            "commodities_trend": "NEUTRAL",
            "currency_trend": "NEUTRAL",
            "summary": "Failed to parse news sentiment.",
            "high_conviction_asset": "NONE",
                "commodity_pick": "NONE"
        }

    def _build_trend_prompt(self, symbol: str, context: Dict) -> str:
        """Constructs the prompt for trend detection."""
        vix = context.get("vix", "Unknown")
        gap = context.get("gap_type", "Normal")
        
        # Option Chain Analysis
        oc = context.get("option_chain", {})
        oc_summary = "Not Available"
        if oc:
            total_ce_oi = sum(c.get('oi', 0) for c in oc.get('calls', []))
            total_pe_oi = sum(p.get('oi', 0) for p in oc.get('puts', []))
            pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
            oc_summary = f"PCR: {pcr} | Total CE OI: {total_ce_oi} | Total PE OI: {total_pe_oi}"

        # Spot price
        spot = context.get("spot", "Unknown")
        
        # Market Breath Analysis
        heavyweights = context.get("heavyweights", [])
        breath_summary = "Not Available"
        if heavyweights:
            breath_summary = ", ".join([f"{h['symbol'].split(':')[-1]}: {h['trend']}" for h in heavyweights])

        # Technical trend as fallback/reference
        tech_trend = context.get("trend", {}).get("trend", "NEUTRAL")

        chp = context.get("chp", 0.0)
        ch = context.get("ch", 0.0)
        summary_3d = context.get("three_day_summary", "Not Available")

        # Intraday high/low for gap-fade detection
        day_high = context.get("day_high", 0)
        day_low = context.get("day_low", 0)
        open_price = context.get("open_price", 0)
        prev_close = context.get("prev_close", 0)
        
        # Calculate intraday position
        intraday_info = ""
        if day_high and day_low and spot and day_high != day_low:
            range_pos = round((float(spot) - day_low) / (day_high - day_low) * 100, 1)
            fade_from_high = round(day_high - float(spot), 1) if day_high else 0
            intraday_info = f"""
        - Day's Range: Low {day_low} — High {day_high} (Range: {round(day_high - day_low, 1)} pts)
        - Current Position in Day's Range: {range_pos}% (0%=Day Low, 100%=Day High)
        - Distance from Day's High: {fade_from_high} pts below high"""
            
            # Gap detection
            if open_price and prev_close:
                gap_pts = round(open_price - prev_close, 1)
                if abs(gap_pts) > 30:
                    gap_dir = "UP" if gap_pts > 0 else "DOWN"
                    gap_filled = "YES (FADED)" if (gap_dir == "UP" and float(spot) < open_price) or (gap_dir == "DOWN" and float(spot) > open_price) else "NO (HOLDING)"
                    intraday_info += f"""
        - Gap {gap_dir}: {abs(gap_pts)} pts (Open: {open_price} vs Prev Close: {prev_close})
        - Gap Fill Status: {gap_filled}"""

        prompt = f"""
        You are an expert NIFTY 50 intraday analyst. Determine today's REALISTIC trend.
        
        CRITICAL RULES:
        - A positive daily change does NOT mean BULLISH if price is fading from highs
        - If price gapped up but is now falling back, that is BEARISH (gap fade)
        - If price is stuck in a range (e.g. 23200-23900), it is RANGEBOUND/NEUTRAL
        - Only say BULLISH if price is making HIGHER HIGHS and sustaining them
        - Only say BEARISH if price is making LOWER LOWS consistently
        
        MARKET DATA:
        - Symbol: {symbol}
        - Current Spot Price: {spot}
        - Daily Change from Previous Close: {ch} points ({chp}%)
        - Open Price: {open_price} | Previous Close: {prev_close}
        {intraday_info}
        
        SUPPORTING DATA:
        - India VIX: {vix} (>18 = volatile/uncertain, <13 = calm trending)
        - Gap Type: {gap}
        - Option Chain: {oc_summary}
        - Market Breadth (Heavyweights): {breath_summary}
        - Technical Trend (reference): {tech_trend}
        - Last 3 Days Action: {summary_3d}
        
        DECISION FRAMEWORK:
        - Gap Up + Price falling from high = BEARISH (gap fade/distribution)
        - Gap Up + Price holding near high = BULLISH (momentum)
        - Price in middle of range, no clear direction = NEUTRAL
        - VIX rising + price falling = BEARISH
        - PCR > 1.2 = BULLISH support, PCR < 0.7 = BEARISH pressure
        
        OUTPUT FORMAT (JSON only, no other text):
        {{
            "trend": "BULLISH" | "BEARISH" | "NEUTRAL",
            "strength": <int 0-100 indicating confidence in trend>,
            "rationale": "<1-2 sentence professional explanation — mention specific price levels>"
        }}
        """
        return prompt

    def _build_prompt(self, symbol: str, signal: Dict, context: Dict) -> str:
        """Constructs the prompt for signal confirmation."""
        trend = context.get("trend", {})
        vix = context.get("vix", "Unknown")
        gap = context.get("gap_type", "Normal")
        levels = [f"{l['label']}: {l['price']}" for l in context.get("key_levels", [])[:5]]
        
        # Option Chain Analysis
        oc = context.get("option_chain", {})
        oc_summary = "Not Available"
        if oc:
            total_ce_oi = sum(c.get('oi', 0) for c in oc.get('calls', []))
            total_pe_oi = sum(p.get('oi', 0) for p in oc.get('puts', []))
            pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
            oc_summary = f"PCR: {pcr} | Total CE OI: {total_ce_oi} | Total PE OI: {total_pe_oi}"

        # Correlation Analysis
        bnf_spot = context.get("bnf_spot", "Unknown")
        bnf_trend = context.get("bnf_trend", "Unknown")
        
        # Market Breath Analysis
        heavyweights = context.get("heavyweights", [])
        breath_summary = "Not Available"
        if heavyweights:
            breath_summary = ", ".join([f"{h['symbol'].split(':')[-1]}: {h['trend']}" for h in heavyweights])

        pnl = context.get("pnl_today", 0)
        target_met = context.get("profit_target_met", False)

        prompt = f"""
        You are an expert NIFTY intraday options trading AI. A technical signal has been detected 
        with MODERATE confidence ({signal.get('confidence')}%). Your job is to make the FINAL DECISION 
        on whether to execute this trade based on REAL market conditions.
        
        SIGNAL DETAILS:
        - Symbol: {symbol}
        - Signal Type: {signal.get('type')} (CALL = Bullish, PUT = Bearish)
        - Direction: {signal.get('direction')}
        - Reason: {signal.get('reason')}
        - Technical Confidence: {signal.get('confidence')}%
        
        REAL-TIME MARKET CONDITIONS:
        - Trend: {trend.get('trend')} (Strength: {trend.get('strength')}/10)
        - India VIX: {vix}
        - Gap Type: {gap}
        - Key Levels Near Price: {', '.join(levels)}
        - Option Chain Sentiment: {oc_summary}
        - BANKNIFTY Sync: Spot {bnf_spot}, Trend {bnf_trend}
        - Market Breadth (Heavyweights): {breath_summary}
        
        ACCOUNT STATUS:
        - PnL Today: ₹{pnl}
        - Daily Target Met: {"YES (BE VERY CONSERVATIVE)" if target_met else "NO (Standard mode)"}
        
        YOUR CRITICAL ANALYSIS CHECKLIST:
        1. VOLATILITY CHECK:
           - VIX < 13: Low volatility → Options premiums are cheap, good for directional trades.
           - VIX 13-18: Normal → Standard risk. Proceed if signal is strong.
           - VIX 18-25: High → Wider stop losses needed. Be cautious.
           - VIX > 25: Extreme → Only trade with very high conviction. Consider skipping.
           
        2. NEWS & EVENT RISK:
           - Is it likely that any major event is happening TODAY (RBI policy, GDP data, US Fed, 
             quarterly earnings of NIFTY heavyweights)?
           - If near 12:00-14:00 IST and VIX is rising, global cues may be negative.
           - Post 14:30 IST: Avoid new positions (market close risk).
           
        3. MARKET REGIME:
           - TRENDING: Price making higher highs/lows (or lower). Trade WITH the trend.
           - SIDEWAYS/CHOPPY: Price oscillating. Mean reversion trades only. Lower confidence.
           
        4. CORRELATION CHECK:
           - NIFTY and BANKNIFTY should move together. Divergence = lower confidence.
           - If heavyweights (RELIANCE, HDFC) trend opposes NIFTY signal → REJECT.
           
        5. OPTION CHAIN PCR:
           - PCR > 1.0: Bullish (supports CALL). PCR < 0.7: Bearish (supports PUT).
           - PCR between 0.7-1.0: Neutral. Be cautious.
        
        DECISION RULES:
        - You have FULL AUTHORITY to approve or reject this trade.
        - If you approve: Set confidence 70-100 based on your conviction.
        - If you reject: Set confidence 0-50 and explain why.
        - Be honest. A rejected trade that saves money is better than a forced trade that loses.
        
        OUTPUT FORMAT (JSON only, no other text):
        {{
            "confidence": <int 0-100>,
            "rationale": "<1-2 sentence professional explanation of your decision>"
        }}
        """
        return prompt
        
    async def generate_code_fix(self, error_data: Dict, file_content: str) -> Optional[Dict]:
        """
        Ask the AI to generate a patch for a runtime error.
        Returns a dict with 'search_content' and 'replace_content'.
        """
        prompt = f"""
        You are an expert Python autonomous self-healing agent.
        A critical runtime error occurred in the trading application.
        
        ERROR MESSAGE:
        {error_data.get('msg')}
        
        TRACEBACK:
        {error_data.get('traceback')}
        
        FILE CONTENT (Target File):
        ```python
        {file_content}
        ```
        
        Analyze the traceback and the file content to identify the exact lines causing the error.
        Generate a safe, defensive patch to fix it. 
        Provide the exact string to search for, and the exact string to replace it with.
        
        OUTPUT FORMAT (JSON ONLY, NO MARKDOWN TAGS):
        {{
            "search_content": "exact lines to replace, matching the file exactly including whitespace",
            "replace_content": "the new code to insert"
        }}
        """
        raw = await self._call_chain(prompt)
        if raw:
            try:
                # Clean markdown blocks if LLM adds them
                if raw.startswith("```json"):
                    raw = raw[7:-3]
                elif raw.startswith("```"):
                    raw = raw[3:-3]
                return json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse AI code fix JSON: {raw}")
        return None

    async def generate_orchestrator_reply(self, user_message: str, system_state: str) -> Dict:
        """Processes Telegram messages directed at the VM Orchestrator and decides on actions."""
        prompt = f"""
You are the "ControlNTrading VM Orchestrator", an advanced AI assistant directly controlling a live algorithmic trading server on Google Cloud.
The user (your owner) has just messaged you on Telegram.

CURRENT SYSTEM STATE:
{system_state}

USER MESSAGE:
"{user_message}"

You must respond to the user, and if they asked you to perform a system action, specify it.
Allowed actions: "restart_trading", "restart_researcher", "fetch_logs", "none".

Respond ONLY with this JSON format:
{{
    "response": "<Your natural language reply to the user (can use emojis, keep it concise but helpful)>",
    "action": "<one of the allowed actions>"
}}
"""
        raw = await self._call_chain(prompt)
        if raw:
            try:
                if raw.startswith("```json"):
                    raw = raw[7:-3]
                elif raw.startswith("```"):
                    raw = raw[3:-3]
                return json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse AI orchestrator JSON: {raw}")
        return {"response": "Sorry, my AI brain failed to process that request.", "action": "none"}

    async def generate_nightly_suggestions(self, audit_data: str) -> Optional[str]:
        """Generates powerful application pointers based on the nightly deep audit."""
        prompt = f"""
You are the Omnipotent Orchestrator for an algorithmic trading system.
Review the following end-of-day health and agent audit.
Provide 3-5 visionary, technical pointers on how the user can make this trading application more powerful, autonomous, and self-running, or fix any specific issues found in the audit logs.

NIGHTLY AUDIT RAW DATA:
{audit_data}

Format the output strictly as a professional Telegram message:
📊 NIGHTLY SYSTEM AUDIT
[Brief summary of services and agent health]

💡 AI ARCHITECTURE SUGGESTIONS:
1. [Pointer 1]
2. [Pointer 2]
3. [Pointer 3]

Reply with '/implement pointer X' to deploy.
"""
        raw = await self._call_chain(prompt)
        return raw

# Singleton instance
ai_engine = AIEngine()
