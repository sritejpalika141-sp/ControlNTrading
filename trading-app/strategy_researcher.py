import asyncio
import httpx
import os
import sys
import base64
import time
import json
import sqlite3

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(APP_DIR)

from engine.notifier import trigger_webhook_background
from dotenv import load_dotenv

load_dotenv(os.path.join(APP_DIR, ".env"))

TRADING_DB = os.path.join(APP_DIR, "trading_db.sqlite")

def get_webhook_url():
    try:
        with sqlite3.connect(TRADING_DB) as conn:
            cursor = conn.execute("SELECT webhook_url FROM user_states WHERE user_id=1")
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return None

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_CONTENTS_API = "https://api.github.com/repos/{owner}/{repo}/contents/{path}"

QUERIES = [
    "NSE algorithmic trading options buying strategy python",
    "Nifty options buying strategy python",
    "BankNifty options buying python",
    "MCX commodities options buying strategy python",
    "Currency options buying trading python"
]

async def search_github(query: str):
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = get_secret("GITHUB_API_KEYS")
    if token:
        headers["Authorization"] = f"token {token}"
        
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                GITHUB_SEARCH_API,
                params={"q": query, "sort": "updated", "order": "desc", "per_page": 2},
                headers=headers
            )
            resp.raise_for_status()
            return resp.json().get("items", [])
        except Exception as e:
            print(f"❌ [Strategy Researcher] GitHub API Error: {e}")
            return []

async def fetch_file_content(owner, repo, path):
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = get_secret("GITHUB_API_KEYS")
    if token:
        headers["Authorization"] = f"token {token}"
        
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(GITHUB_CONTENTS_API.format(owner=owner, repo=repo, path=path), headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "content" in data:
                return base64.b64decode(data["content"]).decode('utf-8', errors='ignore')
        except Exception:
            pass
    return None

async def explore_repo(owner, repo):
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = get_secret("GITHUB_API_KEYS")
    if token:
        headers["Authorization"] = f"token {token}"
        
    repo_code = ""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1", headers=headers)
            if resp.status_code == 200:
                tree = resp.json().get("tree", [])
                # Prioritize strategy logic files
                python_files = [item for item in tree if item["path"].endswith(".py") and "test" not in item["path"].lower()][:3]
                
                for pf in python_files:
                    content = await fetch_file_content(owner, repo, pf["path"])
                    if content:
                        repo_code += f"\n\n# File: {pf['path']}\n{content}"
        except Exception:
            pass
    return repo_code

async def translate_to_controln(repo_name, repo_code):
    if not repo_code.strip():
        return None
        
    prompt = f"""
    You are an expert quantitative developer for the ControlN Trading Bot framework.
    I have downloaded the following algorithmic trading strategy repository from GitHub ({repo_name}):
    
    ```python
    {repo_code[:10000]} # Truncated for context limits
    ```
    
    Translate this strategy logic into a single async Python function compatible with my framework.
    CRITICAL RULE: We do STRICTLY Options Buying. Your translated strategy must ONLY generate BUY signals (long positions) for Call or Put options. It must NEVER generate SELL short signals.
    
    The function signature must be:
    `async def evaluate_auto_{repo_name.replace('-','_').replace('.','')}_strategy(client, state, symbol: str, candles_5m: list, candles_daily: list = None, vix: float = 15.0) -> Optional[dict]:`
    
    The function must return a dictionary if a signal is found:
    {{
        "signal": "BUY",  # ONLY BUY is allowed!
        "entry_price": float,
        "stop_loss": float,
        "target": float,
        "reason": "String explaining the signal",
        "paper_trade_only": True  # MUST ALWAYS BE TRUE for auto-learned strategies!
    }}
    or `None` if no signal.
    
    Return ONLY the RAW python code block (do not wrap in markdown ```). Do not include any imports unless absolutely necessary (like datetime or math). 
    """
    
    
    openrouter_key = get_secret("OPENROUTER_API_KEY")
    if not openrouter_key:
        print("❌ [Strategy Researcher] OPENROUTER_API_KEY not found.")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {openrouter_key}"},
                json={
                    "model": "meta-llama/llama-3.1-70b-instruct",
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                cleaned = text.replace("```python", "").replace("```", "").strip()
                return cleaned
    except Exception as e:
        print(f"❌ [Strategy Researcher] AI Translation Error: {e}")
        
    return None

async def optimize_strategy_code(repo_name, strategy_code, backtest_report):
    """Feeds a failed strategy back into Llama-3 to fix and optimize it based on the backtest report."""
    prompt = f"""
    You are an expert quantitative developer for the ControlN Trading Bot framework.
    I wrote the following Options Buying algorithmic trading strategy ({repo_name}):
    
    ```python
    {strategy_code}
    ```
    
    I ran a 60-day historical backtest, but it performed poorly. Here is the failure report:
    {json.dumps(backtest_report, indent=2)}
    
    Identify why it might be failing (e.g., stop loss too tight, missing trend filter, bad indicators, taking trades too late) and rewrite the `evaluate_auto_*` function to optimize its parameters and logic so it becomes profitable.
    Keep the same function signature. 
    Ensure `paper_trade_only = True` remains in the return dict.
    CRITICAL RULE: The strategy must remain STRICTLY Options Buying (only "BUY" signals allowed).
    
    Return ONLY the RAW python code block (do not wrap in markdown ```). Do not include any imports unless absolutely necessary.
    """
    
    openrouter_key = get_secret("OPENROUTER_API_KEY")
    if not openrouter_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {openrouter_key}"},
                json={
                    "model": "meta-llama/llama-3.1-70b-instruct",
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                cleaned = text.replace("```python", "").replace("```", "").strip()
                return cleaned
    except Exception as e:
        print(f"❌ [Strategy Researcher] AI Optimization Error: {e}")
        
    return None

async def run_learning_cycle():
    print("🎓 [Strategy Researcher] Starting daily learning cycle...")
    
    for query in QUERIES:
        print(f"🔍 Searching GitHub for: '{query}'")
        repos = await search_github(query)
        
        for repo in repos:
            owner = repo["owner"]["login"]
            name = repo["name"]
            print(f"📥 Exploring repo: {owner}/{name}")
            
            repo_code = await explore_repo(owner, name)
            if repo_code and len(repo_code) > 200:
                print(f"🧠 Translating {name} to ControlN format...")
                strategy_code = await translate_to_controln(name, repo_code)
                
                if strategy_code and "async def evaluate_auto_" in strategy_code:
                    clean_name = name.replace('-','_').replace('.','')
                    filename = f"strategy_auto_{clean_name}_{int(time.time())}.py"
                    filepath = os.path.join(APP_DIR, "engine", filename)
                    
                    with open(filepath, "w") as f:
                        f.write(strategy_code)
                        
                    print(f"✅ Learned new strategy! Saved to {filename}")
                    
                    # --- True Adaptive Self-Learning (Reinforcement Loop) ---
                    max_iterations = 3
                    iteration = 1
                    success = False
                    
                    while iteration <= max_iterations:
                        try:
                            from engine.backtester_core import run_backtest_for_strategy
                            report = await run_backtest_for_strategy(filepath)
                            
                            if report:
                                net_points = float(report['net_points'])
                                win_rate = float(report['win_rate'].replace('%', ''))
                                
                                bt_summary = f"\n\n**Backtest (Iter {iteration}):**\nWin Rate: {report['win_rate']}\nNet Points: {report['net_points']}"
                                
                                # Strict Profitability Check
                                if net_points > 0 and win_rate >= 45.0:
                                    success = True
                                    
                                    # Auto-Naming & Injection
                                    import aiosqlite
                                    from models import Database
                                    async with aiosqlite.connect(Database.DB_NAME) as conn:
                                        conn.row_factory = aiosqlite.Row
                                        async with conn.execute("SELECT COUNT(*) as count FROM swarm_agent_configs WHERE strategy_name LIKE 'AI_strategy_%'") as c:
                                            row = await c.fetchone()
                                            ai_count = row['count'] if row else 0
                                            
                                    ai_strategy_name = f"AI_strategy_{ai_count + 1}"
                                    print(f"🌟 Registering new AI Strategy: {ai_strategy_name}")
                                    
                                    await Database.update_agent_config(
                                        strategy_name=ai_strategy_name,
                                        config_dict={},
                                        win_rate=0.0,
                                        total_trades=0,
                                        winning_trades=0,
                                        status='APPROVED',
                                        pending_config_json=None,
                                        is_paper_trading=1, # Starts in paper trading
                                        continuous_losses=0,
                                        asset_class='EQUITY' # Or infer from query context
                                    )
                                    
                                    wh_url = get_webhook_url()
                                    if wh_url:
                                        trigger_webhook_background(
                                            wh_url, 
                                            f"🎓 **New Strategy Learned & Optimized!**\n\n**Name:** `{ai_strategy_name}`\n**Source:** `{owner}/{name}`\n**File:** `{filename}`\n**Status:** `PAPER_TRADE_ONLY` enforced.{bt_summary}\n\nThe orchestrator digested and validated this repo as a highly profitable sandboxed strategy.", 
                                            "Strategy Researcher"
                                        )
                                    break
                                else:
                                    print(f"⚠️ Iteration {iteration} failed (Net: {net_points}, Win: {win_rate}%). Triggering optimization...")
                                    if iteration < max_iterations:
                                        new_code = await optimize_strategy_code(name, strategy_code, report)
                                        if new_code:
                                            strategy_code = new_code
                                            with open(filepath, "w") as f:
                                                f.write(strategy_code)
                                            print(f"🔧 Overwrote {filename} with optimized Version {iteration + 1}")
                                        else:
                                            print("❌ AI failed to provide optimized code. Breaking loop.")
                                            break
                            else:
                                print(f"❌ [Strategy Researcher] Backtest Failed to return report on iter {iteration}")
                                break
                                
                        except Exception as e:
                            print(f"❌ [Strategy Researcher] Backtest Exception: {e}")
                            break
                            
                        iteration += 1
                    
                    if not success:
                        print(f"🗑️ Strategy failed to become profitable after {max_iterations} iterations. Discarding file.")
                        try:
                            if os.path.exists(filepath):
                                os.remove(filepath)
                        except Exception:
                            pass
                    
                    return # Learn 1 per cycle to avoid API overload
                    
    print("💤 [Strategy Researcher] Cycle complete. Found no valid new strategies today.")

if __name__ == "__main__":
    from datetime import datetime
    import pytz

    ist = pytz.timezone('Asia/Kolkata')

    while True:
        now_ist = datetime.now(ist).time()
        
        # Check if we are inside market hours (9:15 AM to 3:30 PM)
        from datetime import time as dt_time
        market_start = dt_time(9, 15)
        market_end = dt_time(15, 30)
        
        if market_start <= now_ist <= market_end:
            print("💤 [Strategy Researcher] Market is open. Sleeping to preserve CPU/RAM...")
            time.sleep(3600) # Sleep for 1 hour and check again
            continue

        try:
            asyncio.run(run_learning_cycle())
        except Exception as e:
            print(f"❌ [Strategy Researcher] Global Error: {e}")
            
        print("⏳ Waiting 24 hours until next learning cycle...")
        time.sleep(86400) # Run once a day
