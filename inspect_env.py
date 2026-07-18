import os
from dotenv import load_dotenv

load_dotenv()

print("TTS_API_KEY from env:", os.environ.get("TTS_API_KEY"))
print("TTS_BASE_URL from env:", os.environ.get("TTS_BASE_URL"))
