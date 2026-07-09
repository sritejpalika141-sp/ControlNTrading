import sys
sys.path.append("/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app")
from engine.strikes import get_dynamic_lot_size

print("NIFTY lot size:", get_dynamic_lot_size("NSE:NIFTY24DEC25000CE"))
print("BANKNIFTY lot size:", get_dynamic_lot_size("NSE:BANKNIFTY24DEC45000CE"))
print("FINNIFTY lot size:", get_dynamic_lot_size("NSE:FINNIFTY24DEC20000CE"))
print("MIDCPNIFTY lot size:", get_dynamic_lot_size("NSE:MIDCPNIFTY24DEC10000CE"))
