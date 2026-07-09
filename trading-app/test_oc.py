import asyncio
from fyers_client import FyersClient

async def main():
    client = FyersClient()
    oc = client.get_option_chain_strikes(1300, base_symbol="NSE:RELIANCE-EQ")
    print("With -EQ:", oc)
    oc2 = client.get_option_chain_strikes(1300, base_symbol="NSE:RELIANCE")
    print("Without -EQ:", oc2)

asyncio.run(main())
