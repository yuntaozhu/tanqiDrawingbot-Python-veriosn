import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ARK_API_KEY = os.getenv("ARK_API_KEY")
TTS_API_KEY = os.getenv("TTS_API_KEY")
TTS_BASE_URL = os.getenv("TTS_BASE_URL")

print(f"ARK_API_KEY: {ARK_API_KEY}")
print(f"TTS_API_KEY: {TTS_API_KEY}")
print(f"TTS_BASE_URL: {TTS_BASE_URL}")

if ARK_API_KEY:
    try:
        print("\n--- Testing Doubao-VoiceDesign ---")
        client = OpenAI(api_key=ARK_API_KEY, base_url="https://ark.cn-beijing.volces.com/api/v3")
        model_name = "Doubao-Seed-VoiceDesign-1.0"
        voice_name = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
        response = client.audio.speech.create(
            model=model_name,
            voice=voice_name,
            input="宝贝，我是小探宝，我们一起来画画吧！",
            timeout=20
        )
        print(f"Doubao success! Audio content length: {len(response.content)}")
    except Exception as e:
        print(f"Doubao failed: {e}")

if TTS_API_KEY and TTS_BASE_URL:
    try:
        print("\n--- Testing SiliconFlow / Primary TTS ---")
        client = OpenAI(api_key=TTS_API_KEY, base_url=TTS_BASE_URL)
        # Check what model we use for siliconflow
        model_name = "FunAudioLLM/CosyVoice2-0.5B"
        voice_name = "fc_female"
        response = client.audio.speech.create(
            model=model_name,
            voice=voice_name,
            input="宝贝，我是小探宝，我们一起来画画吧！",
            timeout=20
        )
        print(f"SiliconFlow success! Audio content length: {len(response.content)}")
    except Exception as e:
        print(f"SiliconFlow failed: {e}")
