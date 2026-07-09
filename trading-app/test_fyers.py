import requests
import json
from models import Database

creds = await Database.get_master_app_credentials()
user = await Database.get_user_by_id(1)

access_token = user['fyers_access_token']
client_id = creds[0]

headers = {
    "Authorization": f"{client_id}:{access_token}"
}

res = requests.get("https://api-t1.fyers.in/data/quotes?symbols=NSE:NIFTY50-INDEX", headers=headers)
print(res.text)
