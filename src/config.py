import os
from dotenv import load_dotenv

load_dotenv()

# App configuration
PORT = int(os.getenv("PORT", "3000"))
ADMIN_KEY = os.getenv("ADMIN_KEY")

# DB URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app_history.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

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
SILICONFLOW_STT_MODEL = os.getenv("SILICONFLOW_STT_MODEL", "FunAudioLLM/SenseVoiceSmall")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
if REPLICATE_API_TOKEN:
    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

IDEOGRAM_API_KEY = os.getenv("IDEOGRAM_API_KEY")

ARK_API_KEY = os.getenv("ARK_API_KEY")
ARK_AUDIO_MODEL = os.getenv("ARK_AUDIO_MODEL", "doubao-seed-2-0-lite-260428")
ARK_CHAT_MODEL = os.getenv("ARK_CHAT_MODEL", "doubao-seed-2-0-mini-260428")
ARK_DRAW_MODEL = os.getenv("ARK_DRAW_MODEL", "doubao-seedream-5-0-pro-260628")
ARK_TTS_MODEL = os.getenv("ARK_TTS_MODEL", "Doubao-Seed-VoiceDesign-1-0")
EMBEDDING_MODEL_VISION = os.getenv("EMBEDDING_MODEL_VISION", "doubao-embedding-vision-251215")
EMBEDDING_MODEL_TEXT = os.getenv("EMBEDDING_MODEL_TEXT", "doubao-embedding-large-text-250515")

# Volcengine Realtime Voice API config - New Console (API Key method)
# CRITICAL: Must be set via Railway environment variables
# New console uses unified API Key authentication
VOLC_REALTIME_API_KEY = os.getenv("VOLC_REALTIME_API_KEY")

if not VOLC_REALTIME_API_KEY:
    raise ValueError(
        "Volcengine Realtime API Key must be set via environment variable:\n"
        "  - VOLC_REALTIME_API_KEY (from 火山引擎 Speech Console > API Key Management)"
    )

# Doubao TTS 2.0 V3 API config (天才童声 官方音色)
# Now uses the unified VOLC_REALTIME_API_KEY for auth
VOLC_TTS_V3_APP_ID = os.getenv("VOLC_TTS_V3_APP_ID")
VOLC_TTS_V3_ACCESS_KEY = os.getenv("VOLC_TTS_V3_ACCESS_KEY", VOLC_REALTIME_API_KEY)
VOLC_TTS_V3_RESOURCE_ID = os.getenv("VOLC_TTS_V3_RESOURCE_ID", "seed-tts-2.0")
VOLC_TTS_V3_VOICE_TYPE = os.getenv("VOLC_TTS_V3_VOICE_TYPE", "zh_male_tiancaitongsheng_uranus_bigtts")
VOLC_TTS_V3_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"

