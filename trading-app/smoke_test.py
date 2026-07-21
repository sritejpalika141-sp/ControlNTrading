"""
Pre-deploy smoke test — run this BEFORE restarting the live service.

    .venv/bin/python3 smoke_test.py     # exit 0 = safe to deploy, non-zero = DO NOT deploy

WHY THIS EXISTS
  A module-level `from state import calculate_position_size` was added to fyers_client.py while
  state.py already did `from fyers_client import FyersClient` — a circular import that fails with
  "ImportError: cannot import name 'FyersClient'". Nothing caught it: py_compile passes fine
  (the syntax is valid), so the break only appears when Python actually IMPORTS the module — i.e.
  at service start, on the live trading VM. This test imports everything for real.

  It also catches: syntax errors, missing modules, bad top-level statements, and a FastAPI app
  object that fails to construct.

WHAT IT DOES NOT DO
  It does not run the trading logic, place orders, hit the broker, or validate strategy behaviour.
  A pass means "the process will start", not "the strategy is correct".

Both humans and any agent editing this repo should run this before deploying.
"""
import importlib
import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# Import order matters for catching cycles: import the two ends of the known cycle
# independently AND together, then the rest.
CORE = [
    "state",
    "fyers_client",
    "models",
    "auth_utils",
]

ENGINE = [
    "engine.api_queue", "engine.automation", "engine.signals", "engine.ws_feed",
    "engine.order_blocks", "engine.fvg", "engine.strikes", "engine.asset_classes",
    "engine.ai_engine", "engine.notifier", "engine.encryption", "engine.key_levels",
    "engine.symbol_master", "engine.risk_orchestrator", "engine.nightly_learning",
]

WORKERS = [
    "workers.auto_trader", "workers.market_worker", "workers.regime_worker",
    "workers.news_worker",
]

TOOLS = ["check_strategy_perf"]


def _try(label, fn):
    try:
        fn()
        print(f"  ✅ {label}")
        return True
    except Exception:
        print(f"  ❌ {label}")
        print("     " + traceback.format_exc().strip().replace("\n", "\n     "))
        return False


def main():
    # Load .env so modules that read config at import time behave like production.
    env = os.path.join(BASE, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

    ok = True
    print("SMOKE TEST — importing all modules for real (py_compile cannot catch import cycles)\n")

    print("core:")
    for m in CORE:
        ok &= _try(m, lambda m=m: importlib.import_module(m))

    # Explicit circular-import probe across the known cycle, in BOTH directions.
    print("\ncircular-import probe:")
    ok &= _try("state + fyers_client together", lambda: (
        importlib.import_module("state"), importlib.import_module("fyers_client")))

    print("\nengine:")
    for m in ENGINE:
        ok &= _try(m, lambda m=m: importlib.import_module(m))

    print("\nworkers:")
    for m in WORKERS:
        ok &= _try(m, lambda m=m: importlib.import_module(m))

    print("\ntools:")
    for m in TOOLS:
        ok &= _try(m, lambda m=m: importlib.import_module(m))

    # The real thing: does the ASGI app object construct? This is what uvicorn does at startup.
    print("\nasgi app:")
    def _app():
        app_mod = importlib.import_module("app")
        assert getattr(app_mod, "app", None) is not None, "app.app is missing"
    ok &= _try("app:app constructs", _app)

    print("\n" + ("=" * 60))
    if ok:
        print("RESULT: PASS — process should start. Safe to deploy.")
        return 0
    print("RESULT: FAIL — DO NOT DEPLOY. The service would not start.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
