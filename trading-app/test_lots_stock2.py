import sys
import logging
logging.basicConfig(level=logging.DEBUG)
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from engine.strikes import get_dynamic_lot_size, _lot_sizes_cache

print("RELIANCE CE lot size:", get_dynamic_lot_size("NSE:RELIANCE24DEC2500CE"))
print("Cache size:", len(_lot_sizes_cache))
