import os
import time
import base64
import json
import io
import uuid
import sys
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import requests
from google import genai
from google.genai import types
from PIL import Image
import numpy as np
import cv2

load_dotenv()

app = FastAPI(title="Toddler Drawing Dreamer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for print jobs
print_jobs = []

# --- Helper Functions ---

def process_line_art_image(image_url: str, size: int = 448) -> str:
    try:
        if image_url.startswith("data:image"):
            # Already base64
            header, encoded = image_url.split(",", 1)
            data = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(data)).convert('RGB')
        else:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            img = Image.open(io.BytesIO(response.content)).convert('RGB')
        
        img = img.resize((size, size))
        img_np = np.array(img)
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
        processed_img = Image.fromarray(thresh)
        
        buffered = io.BytesIO()
        processed_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print(f"Error processing image: {e}")
        return image_url

# --- External APIs ---

class ReplicateAPI:
    def __init__(self):
        self.api_key = os.getenv("REPLICATE_API_TOKEN")
        self.base_url = "https://api.replicate.com/v1"

    def generate_text(self, prompt: str, max_tokens: int = 100) -> str:
        if not self.api_key:
            return ""
        url = f"{self.base_url}/models/meta/meta-llama-3-8b-instruct/predictions"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "input": {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "top_p": 0.9
            }
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 201:
            return ""
        
        prediction = response.json()
        poll_url = prediction["urls"]["get"]
        
        for _ in range(60):
            time.sleep(1)
            poll_resp = requests.get(poll_url, headers=headers)
            if poll_resp.status_code == 200:
                result = poll_resp.json()
                if result["status"] == "succeeded":
                    return "".join(result["output"]).strip()
                elif result["status"] in ["failed", "canceled"]:
                    break
        return ""

    def generate_image(self, prompt: str, seed: int = None, protagonist: str = None, ref_image: str = None) -> str:
        if not self.api_key:
            return None
            
        char_context = f"Main character: {protagonist}. " if protagonist else ""
        ref_context = "Maintain visual style of previous drawings. " if ref_image else ""
        full_prompt = f"{char_context}{ref_context}Scenario: {prompt}. Simple black and white line art, 1-bit color style, binary image, no gray, high contrast, sharp edges, pure white background, centered, vector line style. CRITICAL: NO TEXT, NO ENGLISH WORDS."
        
        url = f"{self.base_url}/models/black-forest-labs/flux-schnell/predictions"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "input": {
                "prompt": full_prompt,
                "aspect_ratio": "1:1",
                "go_fast": True,
                "megapixels": "1"
            }
        }
        if seed is not None:
            data["input"]["seed"] = seed
            
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 201:
            return None
            
        prediction = response.json()
        poll_url = prediction["urls"]["get"]
        
        for _ in range(60):
            time.sleep(1)
            poll_resp = requests.get(poll_url, headers=headers)
            if poll_resp.status_code == 200:
                result = poll_resp.json()
                if result["status"] == "succeeded":
                    output = result["output"]
                    return output[0] if isinstance(output, list) else output
                elif result["status"] in ["failed", "canceled"]:
                    break
        return None

class IdeogramAPI:
    def __init__(self):
        self.api_key = os.getenv("IDEOGRAM_API_KEY")
        self.base_url = "https://api.ideogram.ai/v1"

    def generate_image(self, prompt: str, seed: int = None, protagonist: str = None, ref_image: str = None) -> str:
        if not self.api_key:
            return None
            
        char_context = f"Main character: {protagonist}. " if protagonist else ""
        style_keywords = "Line art artistic cartoon work, black and white, coloring book style."
        constraints = "CRITICAL: NO TEXT, NO ENGLISH WORDS, white background."
        full_prompt = f"{style_keywords} {char_context} Scenario: {prompt}. {constraints}"
        
        url = f"{self.base_url}/ideogram-v3/generate"
        headers = {
            "Api-Key": self.api_key
        }
        
        # Using multipart/form-data
        files = {}
        data = {
            "prompt": full_prompt,
            "aspect_ratio": "1x1",
            "rendering_speed": "FLASH",
            "style_type": "AUTO",
            "magic_prompt": "ON"
        }
        if seed is not None:
            data["seed"] = str(seed)
            
        if ref_image:
            try:
                if ref_image.startswith("data:image"):
                    header, encoded = ref_image.split(",", 1)
                    img_data = base64.b64decode(encoded)
                    files["style_reference_images"] = ("reference.png", img_data, "image/png")
                else:
                    res = requests.get(ref_image)
                    files["style_reference_images"] = ("reference.png", res.content, "image/png")
            except Exception as e:
                print(f"Failed to attach reference image: {e}")
                
        response = requests.post(url, headers=headers, data=data, files=files if files else None)
        if response.status_code == 200:
            result = response.json()
            if result.get("data") and len(result["data"]) > 0:
                return result["data"][0]["url"]
        else:
            print(f"Ideogram API Error: {response.status_code} {response.text}")
        return None

# --- API Models ---

class GenerateRequest(BaseModel):
    prompt: str
    engine: str = "ideogram"
    protagonist: Optional[str] = None
    anchorImageBase64: Optional[str] = None
    seed: Optional[int] = None

# --- API Endpoints ---

@app.post("/api/generate")
async def generate_drawing(req: GenerateRequest):
    replicate_api = ReplicateAPI()
    ideogram_api = IdeogramAPI()
    
    # 1. Translate prompt
    english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {req.prompt}")
    if not english_prompt:
        english_prompt = req.prompt
        
    # 2. Extract protagonist if not provided
    protagonist = req.protagonist
    if not protagonist:
        sys_prompt = f"从以下描述中提取主角。要求：1. 必须是纯中文词汇。2. 必须是幼儿易懂的极简词汇（如：小兔子、红赛车、大恐龙）。3. 严禁包含任何英文字符或拼音。描述：{req.prompt}"
        protagonist = replicate_api.generate_text(sys_prompt)
        
    # 3. Summarize prompt
    title_prompt = f"请将绘画描述总结为一个幼儿标题。要求：1. 必须是2-5个字的极简中文词汇，适合3岁幼儿（如：漂亮小鱼、开心小熊）。2. 严禁出现任何英文单词、字母或拼音。3. 在标题开头或结尾增加一个匹配的表情符号(Emoji)。描述内容：{req.prompt}"
    title = replicate_api.generate_text(title_prompt) or "🎨 奇妙画作"
    
    # Translate protagonist
    english_protagonist = protagonist
    if protagonist and any('\u4e00' <= char <= '\u9fa5' for char in protagonist):
        translated = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {protagonist}")
        if translated:
            english_protagonist = translated

    # 4. Generate Image
    image_url = None
    if req.engine == "ideogram":
        image_url = ideogram_api.generate_image(english_prompt, req.seed, english_protagonist, req.anchorImageBase64)
    elif req.engine == "replicate":
        image_url = replicate_api.generate_image(english_prompt, req.seed, english_protagonist, req.anchorImageBase64)
        
    if not image_url and req.engine != "ideogram":
        print("Fallback to Ideogram")
        image_url = ideogram_api.generate_image(english_prompt, req.seed, english_protagonist, req.anchorImageBase64)
        
    if not image_url:
        raise HTTPException(status_code=500, detail="Image generation failed")
        
    # 5. Process Image
    processed_image = process_line_art_image(image_url)
    
    return {
        "imageUrl": processed_image,
        "protagonist": protagonist,
        "title": title,
        "prompt": req.prompt
    }

@app.post("/api/device/v1/voice")
async def handle_voice(request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty audio body received")
        
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY or API_KEY is missing")
        
    client = genai.Client(api_key=api_key)
    
    generate_drawing_tool = types.FunctionDeclaration(
        name="generate_drawing",
        description="Generate a black and white line art drawing for kids based on the prompt.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "prompt": types.Schema(
                    type=types.Type.STRING,
                    description="Visual description of the drawing for children."
                )
            },
            required=["prompt"]
        )
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(data=body, mime_type='audio/wav')
            ],
            config=types.GenerateContentConfig(
                system_instruction="You are a gentle kindergarten teacher named 'Xiao Yi'. Speak in Chinese. If the child asks to draw something, call the generate_drawing function. Keep responses short and sweet.",
                tools=[types.Tool(function_declarations=[generate_drawing_tool])]
            )
        )
        
        text_response = response.text or ""
        action = None
        
        if response.function_calls:
            call = response.function_calls[0]
            if call.name == "generate_drawing":
                prompt = call.args.get("prompt")
                mock_image_url = "https://images.weserv.nl/?url=raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png"
                
                job_id = str(uuid.uuid4())
                print_jobs.append({
                    "job_id": job_id,
                    "image_url": mock_image_url,
                    "prompt": prompt,
                    "timestamp": time.time()
                })
                
                action = {"type": "print", "prompt": prompt, "job_id": job_id}
                if not text_response:
                    text_response = f"好的，我这就画一张{prompt}。"
                    
        if not text_response:
            text_response = "我没听清，请再说一遍。"
            
        return {
            "text_response": text_response,
            "action": action,
            "audio_base64": None
        }
    except Exception as e:
        print(f"Voice Handler Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/device/v1/print-jobs")
async def get_print_jobs(request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    if print_jobs:
        job = print_jobs[0]
        return {
            "has_job": True,
            **job
        }
    return {"has_job": False}

@app.post("/api/device/v1/print-jobs/{job_id}/complete")
async def complete_print_job(job_id: str, request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    global print_jobs
    print_jobs = [job for job in print_jobs if job["job_id"] != job_id]
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
