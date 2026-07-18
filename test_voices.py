import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

tts_key = os.getenv("TTS_API_KEY")
tts_url = os.getenv("TTS_BASE_URL")

client = OpenAI(api_key=tts_key, base_url=tts_url)
model_name = "FunAudioLLM/CosyVoice2-0.5B"

voices_to_test = [
    "FunAudioLLM/CosyVoice2-0.5B:fc_female",
    "FunAudioLLM/CosyVoice2-0.5B:fc_male",
    "FunAudioLLM/CosyVoice2-0.5B:mia",
    "FunAudioLLM/CosyVoice2-0.5B:anna",
    "FunAudioLLM/CosyVoice2-0.5B:bella",
    "FunAudioLLM/CosyVoice2-0.5B:sophia",
]

for voice in voices_to_test:
    try:
        print(f"Testing {voice}...")
        response = client.audio.speech.create(
            model=model_name,
            voice=voice,
            input="你好宝贝，我是你的好朋友小探宝。今天你想画画吗？",
            timeout=10
        )
        print(f"-> SUCCESS for {voice}! Size: {len(response.content)} bytes")
    except Exception as e:
        print(f"-> Failed for {voice}: {e}")
