import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_stt_tts_config():
    tts_key = os.getenv("TTS_API_KEY")
    tts_url = os.getenv("TTS_BASE_URL")
    
    if tts_key and tts_url:
        if tts_key.startswith("http") or "api." in tts_key:
            tts_key, tts_url = tts_url, tts_key
            
    return tts_key, tts_url

tts_key, tts_url = get_stt_tts_config()
print(f"Key: {tts_key}")
print(f"URL: {tts_url}")

if tts_key and tts_url:
    headers = {
        "Authorization": f"Bearer {tts_key}"
    }
    # List all models
    response = requests.get(f"{tts_url}/models?sub_type=text-to-speech", headers=headers)
    print("Status code:", response.status_code)
    try:
        data = response.json()
        print("\n=== TTS Models ===")
        for model in data.get("data", []):
            print(f"- {model.get('id')}")
    except Exception as e:
        print("Failed to decode json:", e)
        print("Raw text:", response.text[:1000])
        
    # Also query without sub_type to search for cosy
    response_all = requests.get(f"{tts_url}/models", headers=headers)
    try:
        data_all = response_all.json()
        print("\n=== All Models containing 'cosy' or 'speech' or 'voice' ===")
        for model in data_all.get("data", []):
            model_id = model.get("id", "").lower()
            if "cosy" in model_id or "speech" in model_id or "voice" in model_id:
                print(f"- {model.get('id')}")
    except Exception as e:
        pass
