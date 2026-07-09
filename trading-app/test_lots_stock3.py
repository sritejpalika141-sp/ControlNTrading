import sys
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from engine.strikes import get_dynamic_lot_size

print("RELIANCE CE lot size:", get_dynamic_lot_size("NSE:RELIANCE26JUN820CE"))
