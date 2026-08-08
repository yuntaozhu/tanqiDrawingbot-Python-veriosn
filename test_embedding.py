import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("ARK_API_KEY")
base_url = "https://ark.cn-beijing.volces.com/api/v3"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

print(f"Testing with API Key: {api_key[:10]}...{api_key[-5:] if api_key else ''}")

# 1. Test doubao-embedding-vision-251215
payload_vision = {
    "model": "doubao-embedding-vision-251215",
    "input": [
        {
            "type": "text",
            "text": "天很蓝，海很深"
        }
    ]
}

print("\n--- Testing doubao-embedding-vision-251215 ---")
try:
    resp = requests.post(f"{base_url}/embeddings/multimodal", json=payload_vision, headers=headers, timeout=10)
    print("Status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print("Error:", e)

# 2. Test doubao-embedding-large-text-250515
payload_text_large = {
    "model": "doubao-embedding-large-text-250515",
    "input": ["天很蓝，海很深"]
}
print("\n--- Testing doubao-embedding-large-text-250515 ---")
try:
    resp = requests.post(f"{base_url}/embeddings", json=payload_text_large, headers=headers, timeout=10)
    print("Status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print("Error:", e)

# 3. Test other text embedding names (like doubao-embedding-text-240715, doubao-embedding, Skylark-embedding-vision etc.)
for model_name in ["doubao-embedding-text-240715", "doubao-embedding", "doubao-embedding-large", "doubao-embedding-text-240515"]:
    payload = {
        "model": model_name,
        "input": ["天很蓝，海很深"]
    }
    print(f"\n--- Testing {model_name} ---")
    try:
        resp = requests.post(f"{base_url}/embeddings", json=payload, headers=headers, timeout=10)
        print("Status:", resp.status_code)
        print("Response:", resp.text[:200])
    except Exception as e:
        print("Error:", e)
