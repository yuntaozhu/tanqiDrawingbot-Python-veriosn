import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def get_stt_tts_config():
    tts_key = os.getenv("TTS_API_KEY")
    tts_url = os.getenv("TTS_BASE_URL")
    
    if tts_key and tts_url:
        if tts_key.startswith("http") or "api." in tts_key:
            # Swapped!
            tts_key, tts_url = tts_url, tts_key
            
    return tts_key, tts_url

tts_key, tts_url = get_stt_tts_config()

candidate_voices = [
    "FunAudioLLM/CosyVoice2-0.5B:alex",
    "FunAudioLLM/CosyVoice2-0.5B:anna",
    "FunAudioLLM/CosyVoice2-0.5B:bella",
    "FunAudioLLM/CosyVoice2-0.5B:sweet",
    "FunAudioLLM/CosyVoice2-0.5B:yiting",
    "FunAudioLLM/CosyVoice2-0.5B:lovelace",
    "FunAudioLLM/CosyVoice2-0.5B:quin",
]

if tts_key and tts_url:
    client = OpenAI(api_key=tts_key, base_url=tts_url)
    model_name = "FunAudioLLM/CosyVoice2-0.5B"
    
    for voice in candidate_voices:
        try:
            print(f"Trying voice: {voice}...")
            response = client.audio.speech.create(
                model=model_name,
                voice=voice,
                input="宝贝，我是小探宝，我们一起来画画吧！",
                timeout=10
            )
            print(f"-> SUCCESS for voice '{voice}'! Size: {len(response.content)} bytes")
        except Exception as e:
            print(f"-> Failed for voice '{voice}': {e}")
