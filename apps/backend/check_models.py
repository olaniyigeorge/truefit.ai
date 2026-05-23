import asyncio
from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

async def main():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    models = client.models.list()
    for m in models:
        print(m.name)

asyncio.run(main())