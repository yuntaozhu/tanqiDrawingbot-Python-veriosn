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

def load_image(image_url: str) -> Image.Image:
    if image_url.startswith("data:image"):
        header, encoded = image_url.split(",", 1)
        data = base64.b64decode(encoded)
        return Image.open(io.BytesIO(data)).convert('RGB')
    else:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert('RGB')

def apply_line_art_filter(img: Image.Image, size: int = 448) -> Image.Image:
    img = img.resize((size, size))
    img_np = np.array(img)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    return Image.fromarray(thresh)

def encode_image_to_base64(img: Image.Image, format: str = "PNG") -> str:
    buffered = io.BytesIO()
    img.save(buffered, format=format)
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    mime_type = format.lower()
    return f"data:image/{mime_type};base64,{img_str}"

def process_line_art_image(image_url: str, size: int = 448, apply_filter: bool = True) -> str:
    try:
        img = load_image(image_url)
        if apply_filter:
            img = apply_line_art_filter(img, size)
        return encode_image_to_base64(img)
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
            raise ValueError("REPLICATE_API_TOKEN is not set.")
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
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 401:
                raise PermissionError("Replicate API Error: Unauthorized. Check your REPLICATE_API_TOKEN.")
            elif response.status_code == 422:
                raise ValueError(f"Replicate API Error: Unprocessable Entity. Invalid input data. Response: {response.text}")
            elif response.status_code != 201:
                raise RuntimeError(f"Replicate API Error (Text Gen): Status {response.status_code}, Response: {response.text}")
            
            prediction = response.json()
            poll_url = prediction.get("urls", {}).get("get")
            if not poll_url:
                raise RuntimeError("Replicate API Error: No polling URL returned.")
            
            for _ in range(60):
                time.sleep(1)
                poll_resp = requests.get(poll_url, headers=headers, timeout=10)
                if poll_resp.status_code == 200:
                    result = poll_resp.json()
                    if result.get("status") == "succeeded":
                        return "".join(result.get("output", [])).strip()
                    elif result.get("status") in ["failed", "canceled"]:
                        raise RuntimeError(f"Replicate API Error: Prediction {result.get('status')}. Details: {result.get('error')}")
                else:
                    print(f"Replicate API Polling Error: Status {poll_resp.status_code}")
            raise TimeoutError("Replicate API Error: Polling timed out after 60 seconds.")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Replicate API Network Error (Text Gen): {e}")

    def generate_image(self, prompt: str, seed: Optional[int] = None, protagonist: Optional[str] = None, ref_image: Optional[str] = None, aspect_ratio: str = "1:1", num_images: int = 1, style: str = "default") -> Optional[List[str]]:
        if not self.api_key:
            raise ValueError("REPLICATE_API_TOKEN is not set.")
            
        char_context = f"Main character: {protagonist}. " if protagonist else ""
        ref_context = "Maintain visual style of previous drawings. " if ref_image else ""
        
        style_prompts = {
            "cartoon": "Line art artistic cartoon work, coloring book style",
            "realistic": "Realistic highly detailed sketch, pencil sketch style",
            "watercolor": "Watercolor style line art, ink wash, expressive brush strokes",
            "default": "Simple black and white line art, 1-bit color style, vector line style"
        }
        style_prompt = style_prompts.get(style.lower(), style_prompts["default"])
        
        full_prompt = f"{char_context}{ref_context}Scenario: {prompt}. {style_prompt}, binary image, no gray, high contrast, sharp edges, pure white background, centered. CRITICAL: NO TEXT, NO ENGLISH WORDS."
        
        url = f"{self.base_url}/models/black-forest-labs/flux-schnell/predictions"
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "input": {
                "prompt": full_prompt,
                "aspect_ratio": aspect_ratio,
                "num_outputs": num_images,
                "go_fast": True,
                "megapixels": "1"
            }
        }
        if seed is not None:
            data["input"]["seed"] = seed
            
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 401:
                raise PermissionError("Replicate API Error: Unauthorized. Check your REPLICATE_API_TOKEN.")
            elif response.status_code == 422:
                raise ValueError(f"Replicate API Error: Unprocessable Entity. Invalid input data. Response: {response.text}")
            elif response.status_code != 201:
                raise RuntimeError(f"Replicate API Error (Image Gen): Status {response.status_code}, Response: {response.text}")
                
            prediction = response.json()
            poll_url = prediction.get("urls", {}).get("get")
            if not poll_url:
                raise RuntimeError("Replicate API Error: No polling URL returned.")
            
            for _ in range(60):
                time.sleep(1)
                poll_resp = requests.get(poll_url, headers=headers, timeout=10)
                if poll_resp.status_code == 200:
                    result = poll_resp.json()
                    if result.get("status") == "succeeded":
                        output = result.get("output")
                        return output if isinstance(output, list) else [output]
                    elif result.get("status") in ["failed", "canceled"]:
                        raise RuntimeError(f"Replicate API Error: Prediction {result.get('status')}. Details: {result.get('error')}")
                else:
                    print(f"Replicate API Polling Error: Status {poll_resp.status_code}")
            raise TimeoutError("Replicate API Error: Polling timed out after 60 seconds.")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Replicate API Network Error (Image Gen): {e}")

class IdeogramAPI:
    def __init__(self):
        self.api_key = os.getenv("IDEOGRAM_API_KEY")
        self.base_url = "https://api.ideogram.ai/v1"

    def generate_image(self, prompt: str, seed: Optional[int] = None, protagonist: Optional[str] = None, ref_image: Optional[str] = None, aspect_ratio: str = "1:1", num_images: int = 1, style: str = "default") -> Optional[List[str]]:
        if not self.api_key:
            return None
            
        char_context = f"Main character: {protagonist}. " if protagonist else ""
        
        style_prompts = {
            "cartoon": "Line art artistic cartoon work, black and white, coloring book style.",
            "realistic": "Realistic sketch, highly detailed line art, black and white, pencil sketch style.",
            "watercolor": "Watercolor style line art, black and white ink wash, expressive brush strokes.",
            "default": "Simple black and white line art, 1-bit color style, binary image."
        }
        style_keywords = style_prompts.get(style.lower(), style_prompts["default"])
        
        constraints = "CRITICAL: NO TEXT, NO ENGLISH WORDS, white background."
        full_prompt = f"{style_keywords} {char_context} Scenario: {prompt}. {constraints}"
        
        url = f"{self.base_url}/ideogram-v3/generate"
        headers = {
            "Api-Key": self.api_key
        }
        
        ideo_aspect_ratio = f"ASPECT_{aspect_ratio.replace(':', '_')}" if ":" in aspect_ratio else "ASPECT_1_1"
        
        # Using multipart/form-data
        files = {}
        data = {
            "prompt": full_prompt,
            "aspect_ratio": ideo_aspect_ratio,
            "rendering_speed": "FLASH",
            "style_type": "AUTO",
            "magic_prompt": "ON",
            "num_images": str(num_images)
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
                return [item["url"] for item in result["data"]]
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
    aspect_ratio: str = "1:1"
    num_images: int = 1
    style: str = "default"
    apply_line_art: bool = True

# --- API Endpoints ---

@app.get("/")
async def root():
    return {"message": "Toddler Drawing Dreamer API is running. See /docs for API documentation."}

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.post("/api/generate")
async def generate_drawing(req: GenerateRequest):
    replicate_api = ReplicateAPI()
    ideogram_api = IdeogramAPI()
    
    # 1. Translate prompt
    try:
        english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {req.prompt}")
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"Translation failed: {e}")
        english_prompt = req.prompt
        
    # 2. Extract protagonist if not provided
    protagonist = req.protagonist
    if not protagonist:
        sys_prompt = f"从以下描述中提取主角。要求：1. 必须是纯中文词汇。2. 必须是幼儿易懂的极简词汇（如：小兔子、红赛车、大恐龙）。3. 严禁包含任何英文字符或拼音。描述：{req.prompt}"
        try:
            protagonist = replicate_api.generate_text(sys_prompt)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            print(f"Protagonist extraction failed: {e}")
            protagonist = None
        
    # 3. Summarize prompt
    title_prompt = f"请将绘画描述总结为一个幼儿标题。要求：1. 必须是2-5个字的极简中文词汇，适合3岁幼儿（如：漂亮小鱼、开心小熊）。2. 严禁出现任何英文单词、字母或拼音。3. 在标题开头或结尾增加一个匹配的表情符号(Emoji)。描述内容：{req.prompt}"
    try:
        title = replicate_api.generate_text(title_prompt) or "🎨 奇妙画作"
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"Title generation failed: {e}")
        title = "🎨 奇妙画作"
    
    # Translate protagonist
    english_protagonist = protagonist
    if protagonist and any('\u4e00' <= char <= '\u9fa5' for char in protagonist):
        try:
            translated = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {protagonist}")
            if translated:
                english_protagonist = translated
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            print(f"Protagonist translation failed: {e}")

    # 4. Generate Image
    image_urls = None
    error_detail = None
    if req.engine == "ideogram":
        image_urls = ideogram_api.generate_image(english_prompt, req.seed, english_protagonist, req.anchorImageBase64, req.aspect_ratio, req.num_images, req.style)
    elif req.engine == "replicate":
        try:
            image_urls = replicate_api.generate_image(english_prompt, req.seed, english_protagonist, req.anchorImageBase64, req.aspect_ratio, req.num_images, req.style)
        except PermissionError as e:
            print(f"Replicate Auth Error: {e}")
            error_detail = str(e)
            image_urls = None
        except ValueError as e:
            print(f"Replicate Validation Error: {e}")
            error_detail = str(e)
            image_urls = None
        except Exception as e:
            print(f"Replicate image generation failed: {e}")
            error_detail = str(e)
            image_urls = None
        
    if not image_urls and req.engine != "ideogram" and not error_detail:
        print("Fallback to Ideogram")
        image_urls = ideogram_api.generate_image(english_prompt, req.seed, english_protagonist, req.anchorImageBase64, req.aspect_ratio, req.num_images, req.style)
        
    if not image_urls:
        raise HTTPException(status_code=500, detail=error_detail or "Image generation failed")
        
    # 5. Process Image
    processed_images = [process_line_art_image(url, apply_filter=req.apply_line_art) for url in image_urls]
    
    return {
        "imageUrl": processed_images[0] if processed_images else None,
        "imageUrls": processed_images,
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
                
                # Actually generate the drawing
                try:
                    # Translate prompt to English for the image generator
                    replicate_api = ReplicateAPI()
                    english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {prompt}")
                    
                    # Generate image using Ideogram (or Replicate as fallback)
                    ideogram_api = IdeogramAPI()
                    image_urls = ideogram_api.generate_image(english_prompt)
                    
                    if not image_urls:
                        image_urls = replicate_api.generate_image(english_prompt)
                        
                    if image_urls:
                        # Process the image for printing
                        processed_image = process_line_art_image(image_urls[0])
                        
                        job_id = str(uuid.uuid4())
                        print_jobs.append({
                            "job_id": job_id,
                            "image_url": processed_image,
                            "prompt": prompt,
                            "timestamp": time.time()
                        })
                        
                        action = {"type": "print", "prompt": prompt, "job_id": job_id}
                        if not text_response:
                            text_response = f"好的，我这就画一张{prompt}。"
                    else:
                        text_response = "抱歉，我画不出来这个。"
                except Exception as e:
                    print(f"Error generating drawing from voice: {e}")
                    text_response = "抱歉，画画的时候出错了。"
                    
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
