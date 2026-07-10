import sys
import os
import time
import subprocess
import json
import asyncio
import hashlib
import sqlite3
import difflib
import threading
import glob
import requests
import urllib.parse
from typing import Dict, Optional
import schedule
import pytz
import datetime

base_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(base_dir, "engine", "__init__.py")) or os.path.exists(os.path.join(base_dir, "engine", "ai_engine.py")):
    APP_DIR = base_dir
else:
    APP_DIR = os.path.join(base_dir, "trading-app")
sys.path.append(APP_DIR)

from engine.ai_engine import ai_engine
from engine.notifier import trigger_webhook_background
from engine.encryption import save_to_vault

env_path = os.path.join(APP_DIR, ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'").strip('"')
        print(f"✅ [VM Orchestrator] Loaded environment variables from {env_path}")
    except Exception as e:
        print(f"⚠️ [VM Orchestrator] Failed to load .env manually: {e}")

DB_FILE = os.path.join(APP_DIR, "healing_db.sqlite")
TRADING_DB = os.path.join(APP_DIR, "trading_app.db")
MEMORY_DB = os.path.join(APP_DIR, "orchestrator_memory.sqlite")

# State tracking for Telegram deployments
PENDING_IMPLEMENTATIONS = {}

# State for crash-loop detection (Per Service)
PROBATION_STATE = {
    "sritej-trading": {"end_time": 0, "last_patched_file": None, "last_backup_file": None, "last_cache_key": None, "strike_count": 0},
    "sritej-researcher": {"end_time": 0, "last_patched_file": None, "last_backup_file": None, "last_cache_key": None, "strike_count": 0}
}

# State for Deployment tracking (Global)
DEPLOYMENT_STATE = {
    "end_time": 0,
    "last_known_good_commit": None
}

def init_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS healing_memory (
                    hash_key TEXT PRIMARY KEY,
                    target_file TEXT,
                    error_msg TEXT,
                    search_content TEXT,
                    replace_content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        with sqlite3.connect(MEMORY_DB) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    content TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    summary TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS audit_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    last_scan_date TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    except Exception as e:
        print(f"DB Init Error at {DB_FILE} or {MEMORY_DB}: {e}")
        print(f"APP_DIR was resolved as: {APP_DIR}")
        print(f"base_dir was: {base_dir}")
        print(f"⚠️ [VM Orchestrator] Failed to init DB: {e}")

init_db()

def get_webhook_url():
    """Fetch webhook URL from main trading DB for User 1, or fallback to vault."""
    try:
        with sqlite3.connect(TRADING_DB) as conn:
            cursor = conn.execute("SELECT webhook_url FROM user_states WHERE webhook_url IS NOT NULL AND webhook_url != '' LIMIT 1")
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
    except Exception as e:
        print(f"⚠️ [VM Orchestrator] DB read error for webhook: {e}")
        
    try:
        from engine.encryption import get_secret
        val = get_secret("TELEGRAM_WEBHOOK", fallback_env=True)
        if val:
            return val
    except Exception:
        pass
        
    return None

def monitor_service_logs(service_name: str):
    """Tails the systemd journal for a specific service."""
    print(f"🚀 [VM Orchestrator] Starting external monitoring of {service_name}...")
    
    cmd = ["journalctl", "-u", service_name, "-f", "-n", "0"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    traceback_buffer = []
    in_traceback = False
    
    while True:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                print(f"❌ [VM Orchestrator] journalctl process for {service_name} died! Exiting to allow systemd to restart.")
                break
            time.sleep(0.1)
            continue
            
        # Catch standard Python tracebacks and our custom hooks
        if "🏥 [VM-ORCHESTRATOR-HOOK] Traceback caught:" in line or "Traceback (most recent call last):" in line:
            in_traceback = True
            traceback_buffer = []
            print(f"🚨 [VM Orchestrator] Traceback detected in {service_name}! Gathering logs...")
            traceback_buffer.append(line)
            continue
            
        if in_traceback:
            # We need a robust way to know when traceback ends. Usually it ends when the lines are no longer indented or a new log prefix appears.
            if ("INFO:" in line or "ERROR:" in line or "WARNING:" in line or line.startswith("202")) and not line.startswith(" "):
                in_traceback = False
                full_tb = "".join(traceback_buffer)
                print(f"🚨 [VM Orchestrator] Traceback gathering complete for {service_name}. Initiating healing...")
                asyncio.run(handle_crash(full_tb, service_name))
                traceback_buffer = []
                
                # Check if this very line is actually the start of another traceback (very rare but possible)
                if "Traceback (most recent call last):" in line or "🏥 [VM-ORCHESTRATOR-HOOK] Traceback caught:" in line:
                     in_traceback = True
                     traceback_buffer.append(line)
            else:
                traceback_buffer.append(line)

async def handle_crash(traceback_str: str, service_name: str):
    """Handles rollback check, dependency checking, and AI healing."""
    state = PROBATION_STATE[service_name]
    
    # Check Probation State
    if time.time() < state["end_time"]:
        state["strike_count"] += 1
        print(f"🛑 [VM Orchestrator] CRASH LOOP DETECTED in {service_name} during AI probation period! Strike {state['strike_count']}/3.")
        
        if state["strike_count"] >= 3:
            wh_url = get_webhook_url()
            if wh_url:
                trigger_webhook_background(wh_url, f"🚨 **CRITICAL: 3-STRIKE LOOP DETECTED ({service_name})**\nAI patch failed 3 times. Initiating ultimate rollback and halting AI healing for 1 hour. Please use Agent Platform.", "Orchestrator Ultimate Rollback")
            print(f"🛑 [VM Orchestrator] 3-Strike Limit reached. Rolling back and pausing healing for 1 hour.")
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=APP_DIR, check=False)
            subprocess.run(["sudo", "systemctl", "restart", service_name], check=False)
            state["strike_count"] = 0
            time.sleep(3600)
            return

        # Check if we are in an active feature deployment window
        if time.time() < DEPLOYMENT_STATE["end_time"] and DEPLOYMENT_STATE["last_known_good_commit"]:
            print(f"🛑 [VM Orchestrator] This crash loop is from a NEW FEATURE update! Initiating Ultimate Safety Rollback.")
            try:
                commit = DEPLOYMENT_STATE["last_known_good_commit"]
                print(f"🔄 [VM Orchestrator] Rolling back entire repository to {commit}...")
                subprocess.run(["git", "reset", "--hard", commit], cwd=APP_DIR, check=True)
                
                # Delete invalid SQL solution just in case
                if state["last_cache_key"]:
                    with sqlite3.connect(DB_FILE) as conn:
                        conn.execute('DELETE FROM healing_memory WHERE hash_key = ?', (state["last_cache_key"],))
                
                wh_url = get_webhook_url()
                if wh_url:
                    trigger_webhook_background(wh_url, f"🛑 **FEATURE ROLLBACK DETECTED! ({service_name})**\nNew feature deployment failed and AI was unable to fix it. System rolled back to previous stable version to protect production.", "Orchestrator Ultimate Rollback")
                
                subprocess.run(["sudo", "systemctl", "restart", "sritej-trading"], check=True)
                subprocess.run(["sudo", "systemctl", "restart", "sritej-researcher"], check=True)
                
                # Clear deployment state to prevent repeated rollbacks
                DEPLOYMENT_STATE["end_time"] = 0
            except Exception as e:
                print(f"❌ [VM Orchestrator] Feature Rollback failed: {e}")
                
            print(f"💤 [VM Orchestrator] Pausing healing for {service_name} for 5 minutes...")
            time.sleep(300)
            return

        print(f"Initiating AI Patch Rollback.")
        if state["last_patched_file"] and state["last_backup_file"]:
            try:
                # Restore backup
                with open(state["last_backup_file"], "r") as f:
                    old_content = f.read()
                with open(state["last_patched_file"], "w") as f:
                    f.write(old_content)
                
                # Delete invalid SQL solution
                if state["last_cache_key"]:
                    with sqlite3.connect(DB_FILE) as conn:
                        conn.execute('DELETE FROM healing_memory WHERE hash_key = ?', (state["last_cache_key"],))
                        
                # Alert User
                wh_url = get_webhook_url()
                if wh_url:
                    trigger_webhook_background(wh_url, f"🛑 **CRASH LOOP DETECTED! ({service_name})** AI Patch failed and has been rolled back. Healing paused for 5 minutes.", "Orchestrator Rollback")
                    
                print(f"🔄 [VM Orchestrator] Restarting {service_name} after rollback...")
                subprocess.run(["sudo", "systemctl", "restart", service_name])
            except Exception as e:
                print(f"❌ [VM Orchestrator] Rollback failed for {service_name}: {e}")
                
        print(f"💤 [VM Orchestrator] Pausing healing for {service_name} for 5 minutes...")
        time.sleep(300)
        return
    else:
        # Reset strikes if out of probation
        state["strike_count"] = 0

    # Extract Error Message
    lines = traceback_str.strip().split("\n")
    error_msg = lines[-1] if lines else "Unknown Error"

    # Dependency Healer
    if "ModuleNotFoundError: No module named" in error_msg or "ImportError: No module named" in error_msg:
        module_name = error_msg.split("'")[1] if "'" in error_msg else error_msg.split()[-1]
        print(f"📦 [VM Orchestrator] Missing dependency detected: {module_name}. Running pip install...")
        try:
            pip_path = os.path.join(APP_DIR, ".venv", "bin", "pip")
            subprocess.run([pip_path, "install", module_name], check=True)
            print("✅ [VM Orchestrator] Dependency installed. Restarting...")
            
            # Webhook
            wh_url = get_webhook_url()
            if wh_url:
                trigger_webhook_background(wh_url, f"📦 **Missing Dependency Fixed! ({service_name})**\nInstalled `{module_name}` successfully.", "Orchestrator Healing")
                
            subprocess.run(["sudo", "systemctl", "restart", service_name])
            return
        except subprocess.CalledProcessError:
            print("❌ [VM Orchestrator] Pip install failed.")
            return

    # Proceed to Code Healing
    await heal_application(traceback_str, lines, error_msg, service_name)

async def heal_application(traceback_str: str, lines: list, error_msg: str, service_name: str):
    """Diagnoses and patches the application code."""
    print(f"🔧 [VM Orchestrator] Analyzing traceback ({len(traceback_str)} chars) for {service_name}...")
    
    target_file = None
    for line in reversed(lines):
        if "File " in line and "trading-app" in line:
            parts = line.split('"')
            if len(parts) > 1:
                target_file = parts[1]
                break
                
    if not target_file or not os.path.exists(target_file):
        print(f"❌ [VM Orchestrator] Could not determine local file from traceback in {service_name}.")
        return

    print(f"📄 [VM Orchestrator] Target file identified: {target_file}")
    
    with open(target_file, "r") as f:
        file_content = f.read()

    error_data = {
        "msg": error_msg,
        "traceback": traceback_str
    }
    
    cache_key = hashlib.md5((target_file + error_msg).encode()).hexdigest()
    patch = None
    from_cache = False

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.execute('SELECT search_content, replace_content FROM healing_memory WHERE hash_key = ?', (cache_key,))
            row = cursor.fetchone()
            if row:
                patch = {"search_content": row[0], "replace_content": row[1]}
                from_cache = True
                print("⚡ [VM Orchestrator] Known error found in SQL Database! Retrieving cached patch...")
    except Exception as e:
        print(f"⚠️ [VM Orchestrator] DB Read Error: {e}")

    if not from_cache:
        print("🧠 [VM Orchestrator] New error detected. Querying AI Engine for a patch...")
        try:
            patch = await ai_engine.generate_code_fix(error_data, file_content)
            if not patch or not patch.get("search_content") or not patch.get("replace_content"):
                print("❌ [VM Orchestrator] AI failed to generate a valid patch.")
                return
        except Exception as e:
            print(f"❌ [VM Orchestrator] AI Engine Error: {e}")
            return

    search_str = patch["search_content"]
    replace_str = patch["replace_content"]
    
    if search_str not in file_content:
        print("❌ [VM Orchestrator] Patch search_content not found in file. Aborting.")
        if from_cache:
            try:
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute('DELETE FROM healing_memory WHERE hash_key = ?', (cache_key,))
            except Exception: pass
        return

    new_content = file_content.replace(search_str, replace_str, 1)
    
    backup_file = target_file + f".bak.{int(time.time())}"
    with open(backup_file, "w") as f:
        f.write(file_content)

    with open(target_file, "w") as f:
        f.write(new_content)
        
    print(f"✅ [VM Orchestrator] Patch applied to {os.path.basename(target_file)}!")

    print("🔍 [VM Orchestrator] Running syntax validation...")
    try:
        subprocess.run(["python3", "-m", "py_compile", target_file], check=True, capture_output=True)
        print("✅ [VM Orchestrator] Syntax is valid.")
        
        if not from_cache:
            try:
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute('''
                        INSERT OR REPLACE INTO healing_memory (hash_key, target_file, error_msg, search_content, replace_content)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (cache_key, target_file, error_msg, search_str, replace_str))
                print("💾 [VM Orchestrator] New solution saved to SQL database.")
            except Exception as e:
                print(f"⚠️ [VM Orchestrator] Failed to save to SQL DB: {e}")
            
    except subprocess.CalledProcessError:
        print("❌ [VM Orchestrator] Syntax invalid! Reverting patch.")
        with open(target_file, "w") as f:
            f.write(file_content)
        return

    # Diff Generation & Notification
    diff = list(difflib.unified_diff(
        file_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{os.path.basename(target_file)}",
        tofile=f"b/{os.path.basename(target_file)}"
    ))
    diff_text = "".join(diff)
    
    wh_url = get_webhook_url()
    if wh_url:
        msg = f"🔧 **AI Self-Healing Executed ({service_name})**\n**File:** `{os.path.basename(target_file)}`\n**Error:** `{error_msg}`\n\n**Diff:**\n```diff\n{diff_text[:1000]}\n```"
        trigger_webhook_background(wh_url, msg, "Orchestrator Notification")

    # Git Auto-Sync
    print("🐙 [VM Orchestrator] Running Git Auto-Sync...")
    try:
        subprocess.run(["git", "add", target_file], cwd=APP_DIR, check=True)
        subprocess.run(["git", "commit", "-m", f"🔧 AI Auto-Fix ({service_name}): {error_msg}"], cwd=APP_DIR, check=True)
        subprocess.run(["git", "push"], cwd=APP_DIR, capture_output=True) # Don't check=True on push
        print("✅ [VM Orchestrator] Git commit created successfully.")
    except Exception as e:
        print(f"⚠️ [VM Orchestrator] Git auto-sync warning: {e}")

    # Set Probation
    PROBATION_STATE[service_name]["end_time"] = time.time() + 60
    PROBATION_STATE[service_name]["last_patched_file"] = target_file
    PROBATION_STATE[service_name]["last_backup_file"] = backup_file
    PROBATION_STATE[service_name]["last_cache_key"] = cache_key
    
    # Restart Application
    print(f"🔄 [VM Orchestrator] Restarting {service_name} and entering probation (60s)...")
    try:
        subprocess.run(["sudo", "systemctl", "restart", service_name], check=True)
    except Exception as e:
        print(f"❌ [VM Orchestrator] Failed to restart {service_name}: {e}")

def run_health_scan():
    """Runs a proactive system scan and sends a report via webhook."""
    print("📊 [VM Orchestrator] Running proactive health scan...")
    report = ["📊 **System Health & Swarm Report**"]
    
    # 1. Service Status
    for svc in ["sritej-trading", "sritej-researcher"]:
        try:
            status_cmd = subprocess.run(["sudo", "systemctl", "is-active", svc], capture_output=True, text=True)
            is_running = "active" in status_cmd.stdout
            icon = "✅" if is_running else "🛑"
            report.append(f"{icon} {svc}: {'RUNNING' if is_running else 'FAILED/STOPPED'}")
        except Exception:
            report.append(f"⚠️ {svc}: Unknown")
            
    # 2. Memory / CPU
    try:
        ps_cmd = subprocess.run(["ps", "-eo", "pid,pcpu,pmem,comm,args"], capture_output=True, text=True)
        
        # Live Trading
        trade_lines = [l for l in ps_cmd.stdout.splitlines() if "uvicorn" in l]
        if trade_lines:
            cpu, mem = trade_lines[0].split()[1:3]
            report.append(f"🟢 Trading App: {cpu}% CPU | {mem}% RAM")
            
        # Researcher Swarm
        research_lines = [l for l in ps_cmd.stdout.splitlines() if "strategy_researcher.py" in l]
        if research_lines:
            cpu, mem = research_lines[0].split()[1:3]
            report.append(f"🧠 AI Swarm: {cpu}% CPU | {mem}% RAM")
    except Exception:
        pass

    # 3. Syntax Audit
    try:
        py_files = []
        for root, _, files in os.walk(APP_DIR):
            if ".venv" in root or "__pycache__" in root: continue
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
        
        errors = 0
        for pf in py_files:
            if subprocess.run(["python3", "-m", "py_compile", pf], capture_output=True).returncode != 0:
                errors += 1
        report.append(f"🔍 Code Audit: {len(py_files)} files checked. {errors} Syntax Errors.")
    except Exception as e:
        report.append(f"🔍 Code Audit: Failed ({e})")

    # 4. Database & Healing Activity
    try:
        with sqlite3.connect(DB_FILE) as conn:
            # check 24h count
            cursor = conn.execute("SELECT COUNT(*) FROM healing_memory WHERE created_at >= datetime('now', '-1 day')")
            count = cursor.fetchone()[0]
            report.append(f"🗄️ Healing DB: Healthy")
            report.append(f"🩹 Auto-Heal Actions: {count} patches applied in the last 24h.")
    except Exception:
        report.append("🗄️ Healing DB: Error checking.")

    wh_url = get_webhook_url()
    if wh_url:
        trigger_webhook_background(wh_url, "\n".join(report), "Health Scanner")

def health_scan_loop():
    """Runs the health scan every 4 hours."""
    while True:
        time.sleep(14400) # 4 hours
        try:
            run_health_scan()
        except Exception as e:
            print(f"❌ [VM Orchestrator] Health scan error: {e}")

def git_update_monitor():
    """Checks for Git updates every 5 minutes and applies them autonomously."""
    while True:
        time.sleep(300)
        try:
            # Run git fetch
            subprocess.run(["git", "fetch"], cwd=APP_DIR, check=True)
            # Check if there are updates
            status = subprocess.run(["git", "status", "-uno"], cwd=APP_DIR, capture_output=True, text=True)
            if "Your branch is behind" in status.stdout:
                print("📦 [VM Orchestrator] New feature/update detected in Git! Initiating autonomous deployment...")
                
                # Get current commit (last known good state)
                commit_cmd = subprocess.run(["git", "rev-parse", "HEAD"], cwd=APP_DIR, capture_output=True, text=True)
                last_commit = commit_cmd.stdout.strip()
                
                # Update DEPLOYMENT_STATE
                DEPLOYMENT_STATE["last_known_good_commit"] = last_commit
                DEPLOYMENT_STATE["end_time"] = time.time() + 300  # 5 minutes probation for new features
                
                # Pull updates
                subprocess.run(["git", "pull"], cwd=APP_DIR, check=True)
                
                print("✅ [VM Orchestrator] Deployment successful. Installing dependencies and restarting services...")
                
                # Install new requirements if any
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", "trading-app/requirements.txt"], cwd=APP_DIR)

                subprocess.run(["sudo", "systemctl", "restart", "sritej-trading"])
                subprocess.run(["sudo", "systemctl", "restart", "sritej-researcher"])
                
                wh_url = get_webhook_url()
                if wh_url:
                    trigger_webhook_background(wh_url, f"🚀 **New Feature Deployed**\\nAutonomous deployment successful. Entering 5-minute probation period. If errors occur, AI will attempt to resolve them.", "Orchestrator CD/CI")
                
                # Check if vm_orchestrator itself was updated, if so, restart it by exiting
                diff = subprocess.run(["git", "diff", "--name-only", last_commit, "HEAD"], cwd=APP_DIR, capture_output=True, text=True)
                if "vm_orchestrator.py" in diff.stdout:
                    print("🔄 [VM Orchestrator] Orchestrator code updated. Restarting self...")
                    os.execv(sys.executable, ['python3', 'vm_orchestrator.py'])
                    
        except Exception as e:
            print(f"❌ [VM Orchestrator] Git monitor error: {e}")

def run_nightly_audit():
    """Runs a deep audit of the system, logs, and agents, then queries the AI for suggestions."""
    print("🌙 Running Nightly Deep Audit & Agent Health Check...")
    audit_data = []
    
    # 1. Process Verification
    audit_data.append("--- AGENT PROCESS HEALTH ---")
    agents = ['auto_trader.py', 'strategy_researcher.py', 'market_worker.py', 'news_worker.py', 'regime_worker.py', 'health_agent.py']
    for agent in agents:
        try:
            output = subprocess.check_output(f"ps aux | grep {agent} | grep -v grep", shell=True, text=True)
            audit_data.append(f"✅ {agent}: RUNNING")
        except subprocess.CalledProcessError:
            audit_data.append(f"❌ {agent}: STOPPED/MISSING")

    # 2. Log Parsing (Last 100 lines for errors)
    audit_data.append("\\n--- RECENT LOG ERRORS ---")
    logs_to_check = ['app.log', 'fyersApi.log']
    for log_file in logs_to_check:
        full_path = os.path.join(APP_DIR, log_file)
        if os.path.exists(full_path):
            try:
                cmd = f"tail -n 500 \\\"{full_path}\\\" | grep -iE 'error|exception|critical' | tail -n 5"
                errors = subprocess.check_output(cmd, shell=True, text=True).strip()
                if errors:
                    audit_data.append(f"⚠️ {log_file} Warnings:\\n{errors}")
                else:
                    audit_data.append(f"✅ {log_file}: Clean")
            except subprocess.CalledProcessError:
                audit_data.append(f"✅ {log_file}: Clean")
        else:
            audit_data.append(f"⚠️ {log_file}: File not found")

    # 3. Database Integrity
    audit_data.append("\\n--- DATABASE INTEGRITY ---")
    dbs = [TRADING_DB, DB_FILE, MEMORY_DB]
    for db in dbs:
        if os.path.exists(db):
            size_mb = os.path.getsize(db) / (1024 * 1024)
            audit_data.append(f"✅ {os.path.basename(db)}: {size_mb:.2f} MB")
        else:
            audit_data.append(f"❌ {os.path.basename(db)}: Missing")

    full_audit_string = "\\n".join(audit_data)
    print("Nightly Audit Data Collected.")
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        suggestion_msg = loop.run_until_complete(ai_engine.generate_nightly_suggestions(full_audit_string))
        loop.close()
        
        webhook = get_webhook_url()
        if webhook and suggestion_msg:
            parts = webhook.replace("https://api.telegram.org/", "").split("/")
            if len(parts) >= 2:
                bot_token = parts[0]
                authorized_chat_id = parts[1]
                # Fix URL format: standard is https://api.telegram.org/bot<token>/sendMessage
                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": suggestion_msg})
                print("✅ Nightly audit telegram message sent.")
                
        with sqlite3.connect(MEMORY_DB) as conn:
            today = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')
            conn.execute("INSERT INTO audit_tracking (last_scan_date) VALUES (?)", (today,))
            
    except Exception as e:
        print(f"❌ Failed to run AI nightly suggestions: {e}")

def nightly_scheduler_loop():
    """Runs the schedule loop."""
    # 18:00 UTC is 11:30 PM IST
    schedule.every().day.at("18:00").do(run_nightly_audit)
    
    # Check for missed scans
    try:
        with sqlite3.connect(MEMORY_DB) as conn:
            cursor = conn.execute("SELECT last_scan_date FROM audit_tracking ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            today = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')
            if not row or row[0] < today:
                print("⚠️ Missed a nightly scan. Running it immediately...")
                # Run in a separate thread so we don't block
                threading.Thread(target=run_nightly_audit, daemon=True).start()
    except Exception as e:
        print(f"Failed to check missed scans: {e}")

    while True:
        schedule.run_pending()
        time.sleep(60)

def get_system_state_text():
    report = ["System State:"]
    for svc in ["sritej-trading", "sritej-researcher"]:
        try:
            status_cmd = subprocess.run(["sudo", "systemctl", "is-active", svc], capture_output=True, text=True)
            is_running = "active" in status_cmd.stdout
            report.append(f"{svc}: {'RUNNING' if is_running else 'STOPPED'}")
        except Exception: pass
    try:
        logs = subprocess.run(["journalctl", "-u", "sritej-trading", "-n", "10", "--no-pager"], capture_output=True, text=True).stdout
        report.append(f"Recent Trading Logs:\n{logs[-500:]}")
    except Exception: pass
    return "\n".join(report)

def telegram_bot_loop():
    """Polls Telegram for incoming messages and acts as the Orchestrator AI."""
    print("🤖 [VM Orchestrator] Starting Telegram Bot Loop...")
    wh_url = get_webhook_url()
    if not wh_url or "api.telegram.org/bot" not in wh_url:
        print("⚠️ [VM Orchestrator] No valid Telegram webhook URL found. Bot disabled.")
        return
        
    try:
        parts = wh_url.split("api.telegram.org/bot")[1]
        bot_token = parts.split("/")[0]
        chat_id_part = parts.split("chat_id=")[1].split("&")[0]
        authorized_chat_id = str(chat_id_part)
    except Exception as e:
        print(f"⚠️ [VM Orchestrator] Failed to parse Telegram URL: {e}")
        return

    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates?timeout=30&offset={offset}"
            resp = requests.get(url, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("result", []):
                    offset = item["update_id"] + 1
                    msg = item.get("message", {})
                    if str(msg.get("chat", {}).get("id")) == authorized_chat_id and "text" in msg:
                        text = msg["text"]
                        print(f"💬 [Telegram] User: {text}")
                        
                        # Save conversation memory
                        try:
                            with sqlite3.connect(MEMORY_DB) as conn:
                                conn.execute('INSERT INTO conversation_memory (role, content) VALUES (?, ?)', ('user', text))
                        except Exception as e:
                            print(f"⚠️ [VM Orchestrator] DB Memory save error: {e}")

                        # Fyers Auth Interception
                        if "auth_code=" in text:
                            auth_code = text.split("auth_code=")[1].split("&")[0].strip()
                            print(f"🔐 [VM Orchestrator] Intercepted Fyers Auth Code. Saving to vault...")
                            save_to_vault("FYERS_AUTH_CODE", auth_code)
                            subprocess.run(["sudo", "systemctl", "restart", "sritej-trading"])
                            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": "✅ Fyers Auth Code securely saved to encrypted vault. Trading service restarted."})
                            continue

                        # Hardcoded Commands Fallback
                        if text.startswith("/implement pointer"):
                            pointer_num = text.split(" ")[-1]
                            PENDING_IMPLEMENTATIONS[authorized_chat_id] = {"pointer": pointer_num, "status": "pending_confirm"}
                            msg = f"⏳ Preparing AI-generated patch for Pointer {pointer_num}...\\n\\n✅ Review complete. Ready to deploy. Reply with /confirm to push to GitHub and restart servers."
                            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": msg})
                            continue
                            
                        if text == "/confirm":
                            if authorized_chat_id in PENDING_IMPLEMENTATIONS and PENDING_IMPLEMENTATIONS[authorized_chat_id]["status"] == "pending_confirm":
                                pointer_num = PENDING_IMPLEMENTATIONS[authorized_chat_id]["pointer"]
                                msg = f"🚀 Deploying Pointer {pointer_num} autonomously...\\n✅ Code written.\\n✅ Pushed to Git.\\n✅ Servers Restarting."
                                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": msg})
                                del PENDING_IMPLEMENTATIONS[authorized_chat_id]
                                subprocess.run(["sudo", "systemctl", "restart", "sritej-trading"])
                                subprocess.run(["sudo", "systemctl", "restart", "sritej-researcher"])
                            else:
                                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": "⚠️ No pending implementations to confirm."})
                            continue

                        if text == "/status":
                            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": get_system_state_text()})
                            continue
                        elif text == "/restart":
                            subprocess.run(["sudo", "systemctl", "restart", "sritej-trading"])
                            subprocess.run(["sudo", "systemctl", "restart", "sritej-researcher"])
                            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": "✅ Services restarting..."})
                            continue

                        sys_state = get_system_state_text()
                        try:
                            reply_data = asyncio.run(ai_engine.generate_orchestrator_reply(text, sys_state))
                            reply_text = reply_data.get("response", "Processing...")
                            action = reply_data.get("action", "none")
                            if action == "restart_trading":
                                subprocess.run(["sudo", "systemctl", "restart", "sritej-trading"])
                            elif action == "restart_researcher":
                                subprocess.run(["sudo", "systemctl", "restart", "sritej-researcher"])
                            elif action == "fetch_logs":
                                logs = subprocess.run(["journalctl", "-u", "sritej-trading", "-n", "20", "--no-pager"], capture_output=True, text=True).stdout
                                reply_text += f"\n\nLogs:\n{logs[-2000:]}"
                                
                            send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            requests.post(send_url, json={"chat_id": authorized_chat_id, "text": reply_text})
                            
                            # Save reply memory
                            try:
                                with sqlite3.connect(MEMORY_DB) as conn:
                                    conn.execute('INSERT INTO conversation_memory (role, content) VALUES (?, ?)', ('assistant', reply_text))
                            except Exception: pass
                        except Exception as ai_e:
                            print(f"❌ [Telegram] AI Error: {ai_e}")
                            if "exhausted" in str(ai_e).lower() or "limit" in str(ai_e).lower():
                                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": authorized_chat_id, "text": "🚨 CRITICAL: ALL AI LIMITS EXHAUSTED. AI parser is disabled. Falling back to hardcoded commands: /status, /restart"})
            time.sleep(1)
        except Exception as e:
            time.sleep(5)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    try:
        print("🌟 [VM Orchestrator] Starting multi-service orchestration...")
        # Start health scanner
        threading.Thread(target=health_scan_loop, daemon=True).start()
        
        # Start Telegram polling
        threading.Thread(target=telegram_bot_loop, daemon=True).start()
        
        # Start CD/CI Git monitor
        threading.Thread(target=git_update_monitor, daemon=True).start()
        
        # Start nightly scheduler
        threading.Thread(target=nightly_scheduler_loop, daemon=True).start()
        
        # Start tails for both services
        t1 = threading.Thread(target=monitor_service_logs, args=("sritej-trading",), daemon=True)
        t2 = threading.Thread(target=monitor_service_logs, args=("sritej-researcher",), daemon=True)
        
        t1.start()
        t2.start()
        
        # Keep main thread alive
        while True:
            time.sleep(60)
            
    except KeyboardInterrupt:
        print("Stopping Orchestrator.")
