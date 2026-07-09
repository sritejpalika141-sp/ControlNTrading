"""Phase 2 B0 minimal pytest harness.

Makes the trading-app/ package root importable so tests can import the modules under test
(models, auth_utils, state, workers.auto_trader, workers.health_agent, engine.automation)
without installing the app as a package. Scope: unit-testing Phase 2 items B2, B3, B5, B6,
D1, D4, D5, D6 in isolation. This is intentionally a small harness, not a full test-infra
buildout.
"""
import os
import sys

# trading-app/ (parent of tests/) must be on sys.path so `import models` etc. resolve.
_TRADING_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TRADING_APP_DIR not in sys.path:
    sys.path.insert(0, _TRADING_APP_DIR)
