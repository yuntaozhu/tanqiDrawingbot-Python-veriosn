import os
from dotenv import load_dotenv

load_dotenv()

for k, v in os.environ.items():
    if any(k.startswith(prefix) for prefix in ["ARK_", "TTS_", "STT_", "DEEPSEEK_"]):
        print(f"{k}: {v}")
