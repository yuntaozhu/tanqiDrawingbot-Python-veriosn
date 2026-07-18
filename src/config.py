import os
from dotenv import load_dotenv

load_dotenv()

# App configuration
PORT = int(os.getenv("PORT", "3000"))
ADMIN_KEY = os.getenv("ADMIN_KEY")

# DB URL
DATABASE_URL = "sqlite:///./app_history.db"

# API Keys and endpoints
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

STT_API_KEY = os.getenv("STT_API_KEY")
STT_BASE_URL = os.getenv("STT_BASE_URL")
STT_MODEL = os.getenv("STT_MODEL")

TTS_API_KEY = os.getenv("TTS_API_KEY")
TTS_BASE_URL = os.getenv("TTS_BASE_URL")

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
SILICONFLOW_STT_MODEL = os.getenv("SILICONFLOW_STT_MODEL", "SYSTRAN/faster-whisper-large-v3")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if REPLICATE_API_TOKEN:
    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

IDEOGRAM_API_KEY = os.getenv("IDEOGRAM_API_KEY")

ARK_API_KEY = os.getenv("ARK_API_KEY", "05a5b825-69f6-40ff-93e9-7493c05e4fb0")
ARK_AUDIO_MODEL = os.getenv("ARK_AUDIO_MODEL", "doubao-seed-2.0-lite-260428")
ARK_DRAW_MODEL = os.getenv("ARK_DRAW_MODEL", "doubao-seedream-5.0-pro-260628")
ARK_TTS_MODEL = os.getenv("ARK_TTS_MODEL", "Doubao-Seed-VoiceDesign-1.0")
