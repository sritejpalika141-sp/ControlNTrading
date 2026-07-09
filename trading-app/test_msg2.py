import requests
import json

url = "https://api.telegram.org/bot8944665641:AAE6IzDyGFnsP8y-VI00KzOD3YwB4F2XD1k/sendMessage?chat_id=717373310&text="

payload = {
    "text": "*System Test*\nThis is a test message via JSON payload.",
    "parse_mode": "Markdown"
}

resp = requests.post(url, json=payload)
print("Status:", resp.status_code)
print("Response:", resp.text)
