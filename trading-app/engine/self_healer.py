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

        # GUARDRAIL (live-money safety): NEVER let the AI auto-edit trading / order / risk / broker
        # code. A syntactically-valid but logically-wrong AI patch there could lose real money. For
        # these files we alert the user (Telegram) with the error and leave the code untouched for
        # manual review. Auto-healing is limited to non-trading code (UI/display/news/helpers).
        CRITICAL_MARKERS = (
            "auto_trader.py", "fyers_client.py", "risk_orchestrator.py", "models.py",
            "automation.py", "app.py", "/brokers/", "strategy_", "self_healer.py",
        )
        if any(m in target_file for m in CRITICAL_MARKERS):
            base = os.path.basename(target_file)
            alert = (f"🚨 Self-Healer: error in CRITICAL file {base} — NOT auto-editing "
                     f"(live-money safety). Please review manually.\nError: {error_data['msg']}")
            print(alert)
            try:
                from engine.notifier import send_webhook_alert
                import app as _app
                wh = getattr(_app.get_user_state(1), "webhook_url", "")
                if wh:
                    await send_webhook_alert(wh, alert, title="⚠️ Self-Healer: manual fix needed")
            except Exception:
                pass
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

        # 5. Validate Syntax
        try:
            subprocess.run(["python3", "-m", "py_compile", target_file], check=True, capture_output=True)
            print("🏥 [Self-Healer] Syntax check passed.")
        except subprocess.CalledProcessError as e:
            print(f"🏥 [Self-Healer] Syntax check FAILED. Reverting.")
            # Revert
            with open(target_file, "w") as f:
                f.write(file_content)
            return False

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
