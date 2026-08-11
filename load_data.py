import os
from dotenv import load_dotenv
import sqlite3
conn = sqlite3.connect("trailpeak.db")
print(conn.execute("SELECT COUNT(*) FROM customers").fetchone())
conn.close()
from google import genai
load_dotenv(".env.local")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
response = client.models.generate_content(
    model="gemini-flash-latest",
    contents="Say hello in one sentence."
)
print(response.text)