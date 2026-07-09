import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))
from fyers_client import FyersClient
import asyncio
from models import Database

async def main():
    creds = Database.get_master_app_credentials()
    if not creds[0]:
        print("No creds")
        return
    client = FyersClient(user_id=1)
    if not client.is_authenticated():
        client.auto_login()
    quotes = client.get_quotes(["NSE:NIFTY50-INDEX"], force_rest=True)
    print(quotes)

if __name__ == "__main__":
    asyncio.run(main())
