import sys
import logging
logging.basicConfig(level=logging.ERROR)
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from engine.strikes import get_dynamic_lot_size

print("RELIANCE base:", get_dynamic_lot_size("NSE:RELIANCE24DEC2500CE"))
print("NIFTY base:", get_dynamic_lot_size("NSE:NIFTY24DEC2500CE"))
print("TCS base:", get_dynamic_lot_size("NSE:TCS24DEC2500CE"))
print("HDFCBANK base:", get_dynamic_lot_size("NSE:HDFCBANK24DEC2500CE"))
