import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv("../fyers-mcp-server/.env")
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

prompt = """
What is the Trend of NSE:NIFTY50-INDEX today?
OUTPUT FORMAT (JSON only, no other text):
{
    "trend": "BULLISH" | "BEARISH" | "NEUTRAL",
    "strength": 70,
    "rationale": "explain"
}
"""
try:
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )
    )
    print("Success:")
    print(response.text)
except Exception as e:
    print("Error:", e)
