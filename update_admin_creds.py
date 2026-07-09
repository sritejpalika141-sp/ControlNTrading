import sys
import os

sys.path.append(os.path.join(os.getcwd(), "trading-app"))
os.chdir("trading-app")

from models import Database

def update_creds():
    user = Database.get_user_by_username("admin")
    if user:
        user_id = user["id"]
        client_id = "SENTD5B9M0-200"
        secret = "JrjthZkbHu8f6LLU"
        Database.update_fyers_creds(user_id, client_id, secret)
        print(f"✅ Successfully updated Fyers credentials for admin (ID: {user_id})")
    else:
        print("❌ Admin user not found")

if __name__ == "__main__":
    update_creds()
