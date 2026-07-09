import os
import time
import requests
import pyotp
import base64
from urllib.parse import urlparse, parse_qs

def auto_login(fy_id, app_id_client, app_secret, redirect_uri, pin, totp_secret):
    session = requests.Session()
    
    # 1. Send OTP Request
    print("Step 1: Send OTP Request")
    payload1 = {"fy_id": base64.b64encode(fy_id.encode()).decode(), "app_id": 0}
    res1 = session.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2", json=payload1)
    if res1.status_code != 200:
        return {"error": f"Failed to send OTP: {res1.text}"}
    data1 = res1.json()
    request_key = data1.get("request_key")
    if not request_key:
        return {"error": f"No request key in response: {data1}"}
        
    # 2. Verify OTP
    print("Step 2: Verify OTP")
    totp = pyotp.TOTP(totp_secret).now()
    payload2 = {"request_key": request_key, "otp": totp}
    res2 = session.post("https://api-t2.fyers.in/vagator/v2/verify_otp", json=payload2)
    data2 = res2.json()
    request_key = data2.get("request_key")
    if not request_key:
        return {"error": f"Failed to verify OTP: {data2}"}
        
    # 3. Verify PIN
    print("Step 3: Verify PIN")
    payload3 = {"request_key": request_key, "identity_type": "pin", "identifier": base64.b64encode(pin.encode()).decode()}
    res3 = session.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2", json=payload3)
    data3 = res3.json()
    access_token = data3.get("data", {}).get("access_token")
    if not access_token:
        return {"error": f"Failed to verify PIN: {data3}"}
        
    # 4. Get Auth Code
    print("Step 4: Get Auth Code")
    session.headers.update({"Authorization": f"Bearer {access_token}"})
    payload4 = {
        "fyers_id": fy_id,
        "app_id": app_id_client[:-4], # Sometimes it needs the client id without the -100 suffix
        "redirect_uri": redirect_uri,
        "appType": "100",
        "code_challenge": "",
        "state": "None",
        "scope": "",
        "nonce": "",
        "response_type": "code",
        "create_cookie": True
    }
    # Actually wait, app_id in this payload is typically the full app_id like XXXX-100
    payload4["app_id"] = app_id_client
    
    res4 = session.post("https://api-t1.fyers.in/api/v3/token", json=payload4)
    data4 = res4.json()
    
    url = data4.get("Url") or data4.get("url")
    if not url:
        return {"error": f"Failed to get redirect URL: {data4}"}
        
    parsed = urlparse(url)
    auth_code = parse_qs(parsed.query).get('auth_code', [None])[0]
    
    if not auth_code:
        return {"error": f"No auth code in URL: {url}"}
        
    return {"success": True, "auth_code": auth_code}

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    FYERS_USER_ID = os.getenv("FYERS_USER_ID")
    FYERS_PIN = os.getenv("FYERS_PIN")
    FYERS_TOTP_SECRET = os.getenv("FYERS_TOTP_SECRET")
    FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
    FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY")
    FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")
    
    if not all([FYERS_USER_ID, FYERS_PIN, FYERS_TOTP_SECRET, FYERS_CLIENT_ID]):
        print("Missing credentials in .env")
    else:
        res = auto_login(FYERS_USER_ID, FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_REDIRECT_URI, FYERS_PIN, FYERS_TOTP_SECRET)
        print(res)
