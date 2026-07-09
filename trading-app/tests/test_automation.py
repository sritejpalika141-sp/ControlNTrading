"""Phase 2 test for engine/automation.py — item D4 (nightly_learning_date persistence).

TradingState.state_file is derived deterministically from user_id (logs/trading_state_<uid>.json),
so this test uses a distinctive non-numeric fake user_id (avoids colliding with any real
integer user id) and removes the state file it creates in a finally block.
"""
import os

from engine.automation import TradingState

_TEST_UID = "phase2_d4_nightly_learning_test"
_STATE_FILE = os.path.join("logs", f"trading_state_{_TEST_UID}.json")


def test_nightly_learning_date_persists_across_save_and_load():
    if os.path.exists(_STATE_FILE):
        os.remove(_STATE_FILE)
    try:
        ts = TradingState(user_id=_TEST_UID)
        ts.nightly_learning_date = "2026-07-04"
        ts.save()

        # Fresh instance with the SAME user_id resolves to the same state_file and runs
        # load() inside __init__ — this is the actual "process restart" scenario D4 covers.
        ts_reloaded = TradingState(user_id=_TEST_UID)
        assert ts_reloaded.nightly_learning_date == "2026-07-04"
    finally:
        if os.path.exists(_STATE_FILE):
            os.remove(_STATE_FILE)


def test_nightly_learning_date_defaults_empty_for_fresh_state():
    fresh_uid = "phase2_d4_fresh_state_test"
    fresh_file = os.path.join("logs", f"trading_state_{fresh_uid}.json")
    if os.path.exists(fresh_file):
        os.remove(fresh_file)
    try:
        ts = TradingState(user_id=fresh_uid)
        assert getattr(ts, "nightly_learning_date", "") == ""
    finally:
        if os.path.exists(fresh_file):
            os.remove(fresh_file)
