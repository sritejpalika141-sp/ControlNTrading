import requests
import base64
session = requests.Session()
payload = {"fy_id": base64.b64encode(b"XS50009").decode(), "app_id": 0}
res = session.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2", json=payload, timeout=15)
print("app_id=0", res.status_code, res.text)
