import asyncio
import traceback
import json
import os
import subprocess
from datetime import datetime
from engine.ai_engine import AIEngine

error_queue = asyncio.Queue()
# Ensure we don't heal the same error repeatedly
healed_errors = set()

class SelfHealer:
    # Daily auto-fix cap (runaway guard) + counter state.
    MAX_FIXES_PER_DAY = 5
    _fix_day = ""
    _fix_count = 0

    @staticmethod
    async def _alert(msg: str, title: str = "🏥 Self-Healer"):
        """Best-effort Telegram/webhook alert to the owner. Never raises."""
        print(msg)
        try:
            from engine.notifier import send_webhook_alert
            import app as _app
            wh = getattr(_app.get_user_state(1), "webhook_url", "")
            if wh:
                await send_webhook_alert(wh, msg, title=title)
        except Exception:
            pass

    @staticmethod
    async def push_error(error_msg: str, tb_str: str):
        """Push a critical error to the self-healing agent."""
        # Signature of the error to prevent loops
        sig = str(error_msg) + str(tb_str)[:200]
        if sig in healed_errors:
            return
        healed_errors.add(sig)

        await error_queue.put({
            "msg": error_msg,
            "traceback": tb_str,
            "timestamp": datetime.now().isoformat()
        })
        print(f"🏥 [Self-Healer] Caught error for triage: {error_msg}")

    @staticmethod
    async def _analyze_and_fix(error_data: dict, ai_engine: AIEngine) -> bool:
        """Query AI, get patch, apply it, and validate."""
        tb = error_data["traceback"]
        print(f"🏥 [Self-Healer] Analyzing error: {error_data['msg']}")
        
        # 1. Identify the file from the traceback
        target_file = None
        for line in reversed(tb.split("\n")):
            if "File " in line and "trading-app" in line:
                parts = line.split('"')
                if len(parts) > 1:
                    target_file = parts[1]
                    break
        
        if not target_file or not os.path.exists(target_file):
            print("🏥 [Self-Healer] Could not identify target file from traceback.")
            return False

        # NEVER self-modify — a heal-loop that patches the healer itself could corrupt the safety
        # logic and cascade. This one file stays alert-only, always.
        if "self_healer.py" in target_file:
            print("🏥 [Self-Healer] Error is in self_healer.py — alert-only (never self-modify).")
            await SelfHealer._alert(f"🚨 Self-Healer: error in self_healer.py — NOT auto-editing "
                                    f"(never self-modify). Review manually.\nError: {error_data['msg']}",
                                    title="⚠️ Self-Healer: manual fix needed")
            return False

        # TRADING-CRITICAL files (owner directive 31-07-26): auto-healing is now ALLOWED here too,
        # but gated by the FULL validation suite (compile + 18 core trading tests + smoke) below —
        # NOT just a syntax check — so a syntactically-valid-but-logically-wrong patch to live-money
        # code is caught and auto-reverted before it can ever run. Non-critical files keep the lighter
        # compile-only gate.
        TRADING_CRITICAL = (
            "auto_trader.py", "fyers_client.py", "risk_orchestrator.py", "models.py",
            "automation.py", "app.py", "/brokers/", "strategy_", "nightly_learning.py",
        )
        is_critical = any(m in target_file for m in TRADING_CRITICAL)

        # Daily auto-fix cap — a runaway healer must not rewrite the codebase unbounded. Max 5/day.
        today = datetime.now().strftime("%Y-%m-%d")
        if SelfHealer._fix_day != today:
            SelfHealer._fix_day, SelfHealer._fix_count = today, 0
        if SelfHealer._fix_count >= SelfHealer.MAX_FIXES_PER_DAY:
            await SelfHealer._alert(f"🚨 Self-Healer: daily auto-fix cap ({SelfHealer.MAX_FIXES_PER_DAY}) "
                                    f"reached — skipping {os.path.basename(target_file)}. Review manually.\n"
                                    f"Error: {error_data['msg']}", title="⚠️ Self-Healer: daily cap hit")
            return False

        # 2. Read the file
        with open(target_file, "r") as f:
            file_content = f.read()

        # 3. Ask AI for a fix
        print(f"🏥 [Self-Healer] Requesting patch from AI for {os.path.basename(target_file)}...")
        try:
            patch = await ai_engine.generate_code_fix(error_data, file_content)
            if not patch or not patch.get("search_content") or not patch.get("replace_content"):
                print("🏥 [Self-Healer] AI failed to generate a valid patch.")
                return False
        except Exception as e:
            print(f"🏥 [Self-Healer] AI Exception: {e}")
            return False

        # 4. Apply the patch
        search_str = patch["search_content"]
        replace_str = patch["replace_content"]
        
        if search_str not in file_content:
            print("🏥 [Self-Healer] AI patch search_content not found in file.")
            return False

        new_content = file_content.replace(search_str, replace_str, 1)
        
        # Save backup
        backup_file = target_file + f".bak.{int(datetime.now().timestamp())}"
        with open(backup_file, "w") as f:
            f.write(file_content)

        # Write patch
        with open(target_file, "w") as f:
            f.write(new_content)
            
        print(f"🏥 [Self-Healer] Applied patch to {os.path.basename(target_file)}")

        def _revert():
            with open(target_file, "w") as f:
                f.write(file_content)

        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 5a. Syntax check (always).
        try:
            subprocess.run(["python3", "-m", "py_compile", target_file], check=True, capture_output=True)
            print("🏥 [Self-Healer] Syntax check passed.")
        except subprocess.CalledProcessError:
            print("🏥 [Self-Healer] Syntax check FAILED. Reverting.")
            _revert()
            return False

        # 5b. FULL validation gate for trading-critical files: the 18 core trading tests + smoke.
        # A patch that compiles but breaks trading logic (or won't boot) is reverted here BEFORE it
        # can run against live money. This is the safety that lets auto-fixing trading code be sane.
        if is_critical:
            py = os.path.join(app_root, ".venv", "bin", "python3")
            py = py if os.path.exists(py) else "python3"
            for script, label in (("precommit_check.py", "core trading tests"), ("smoke_test.py", "smoke/boot")):
                spath = os.path.join(app_root, script)
                if not os.path.exists(spath):
                    continue
                try:
                    r = subprocess.run([py, spath], cwd=app_root, capture_output=True, timeout=180)
                except Exception as _ve:
                    print(f"🏥 [Self-Healer] {label} gate errored ({_ve}). Reverting (fail-safe).")
                    _revert()
                    return False
                if r.returncode != 0:
                    print(f"🏥 [Self-Healer] {label} gate FAILED for critical patch. Reverting.")
                    _revert()
                    await SelfHealer._alert(
                        f"🏥 Self-Healer TRIED to fix {os.path.basename(target_file)} but the {label} "
                        f"gate failed — patch REVERTED, live code unchanged. Manual fix needed.\n"
                        f"Error: {error_data['msg']}", title="⚠️ Self-Healer: patch reverted")
                    return False
            print("🏥 [Self-Healer] Full trading-critical validation passed (tests + smoke).")

        SelfHealer._fix_count += 1
        if is_critical:
            await SelfHealer._alert(
                f"🏥 Self-Healer AUTO-FIXED trading-critical file {os.path.basename(target_file)} "
                f"(passed tests + smoke) and will restart the app. Review + git-commit from the VM.\n"
                f"Error was: {error_data['msg']}", title="🏥 Self-Healer: trading-code fix applied")
        return True

    @staticmethod
    async def loop():
        """Background loop monitoring the error queue."""
        print("🏥 [Self-Healer] Monitoring loop started.")
        ai_engine = AIEngine()
        
        while True:
            try:
                error_data = await error_queue.get()
                
                # Check if we should attempt a fix
                success = await SelfHealer._analyze_and_fix(error_data, ai_engine)
                
                if success:
                    print("🏥 [Self-Healer] Fix applied successfully! Deploying changes...")
                    await asyncio.sleep(2)  # Give time for logs to flush
                    
                    # Log the fix so the user can sync locally
                    print(f"🚨🚨 [Self-Healer] ALERT: Live code has been modified! You MUST sync your local machine with the VM to avoid overwriting fixes on the next deploy.")
                    try:
                        from engine.notifier import send_webhook_alert
                        import app as _app
                        wh = getattr(_app.get_user_state(1), "webhook_url", "")
                        if wh:
                            await send_webhook_alert(wh, "🏥 Self-Healer applied a code fix on the VM and restarted the app. SYNC your local copy from the VM before your next deploy, or the fix will be overwritten.", title="🏥 Self-Healer applied a fix")
                    except Exception:
                        pass
                    # Restart the service to load the patched code. NOTE: do NOT run deploy.sh here —
                    # that is a LOCAL push script (uploads local->VM) and running it on the VM would
                    # clobber the just-applied fix with the older local copy.
                    subprocess.Popen(["sudo", "systemctl", "restart", "sritej-trading"], start_new_session=True)
                        
            except Exception as e:
                print(f"🏥 [Self-Healer] Loop internal error: {e}")
            finally:
                await asyncio.sleep(5)
