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

_stt_key = os.getenv("STT_API_KEY")
_stt_url = os.getenv("STT_BASE_URL")
if _stt_key and _stt_url:
    if _stt_key.startswith("http") or "api." in _stt_key:
        _stt_key, _stt_url = _stt_url, _stt_key

STT_API_KEY = _stt_key
STT_BASE_URL = _stt_url
STT_MODEL = os.getenv("STT_MODEL")

_tts_key = os.getenv("TTS_API_KEY")
_tts_url = os.getenv("TTS_BASE_URL")
if _tts_key and _tts_url:
    if _tts_key.startswith("http") or "api." in _tts_key:
        _tts_key, _tts_url = _tts_url, _tts_key

TTS_API_KEY = _tts_key
TTS_BASE_URL = _tts_url

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
SILICONFLOW_STT_MODEL = os.getenv("SILICONFLOW_STT_MODEL", "SYSTRAN/faster-whisper-large-v3")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if REPLICATE_API_TOKEN:
    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

IDEOGRAM_API_KEY = os.getenv("IDEOGRAM_API_KEY")

ARK_API_KEY = os.getenv("ARK_API_KEY", "05a5b825-69f6-40ff-93e9-7493c05e4fb0")
ARK_AUDIO_MODEL = os.getenv("ARK_AUDIO_MODEL", "doubao-seed-2-0-lite-260428")
ARK_DRAW_MODEL = os.getenv("ARK_DRAW_MODEL", "doubao-seedream-5-0-pro-260628")
ARK_TTS_MODEL = os.getenv("ARK_TTS_MODEL", "Doubao-Seed-VoiceDesign-1-0")
EMBEDDING_MODEL_VISION = os.getenv("EMBEDDING_MODEL_VISION", "doubao-embedding-vision-250615")
EMBEDDING_MODEL_TEXT = os.getenv("EMBEDDING_MODEL_TEXT", "doubao-embedding-text-250515")
