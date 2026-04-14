import os
import time
import base64
import json
import io
import uuid
import sys
import functools
import random
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import requests
import replicate
from openai import OpenAI
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

# In-memory store for feedback (in a real app, use a database)
feedback_store = []

# In-memory store for generation history
generation_history = []

# --- Helper Functions ---

def retry_with_backoff(max_retries=3, initial_delay=1, backoff_factor=2, jitter=True):
    """Decorator for retrying functions with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for i in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    # Don't retry on certain errors (e.g., auth, validation)
                    error_str = str(e).lower()
                    if any(x in error_str for x in ["unauthorized", "invalid api key", "401", "403", "422"]):
                        raise e
                        
                    if i == max_retries:
                        break
                    
                    # Exponential backoff
                    sleep_time = delay * (backoff_factor ** i)
                    if jitter:
                        sleep_time += random.uniform(0, 0.1 * sleep_time)
                    
                    print(f"Retrying {func.__name__} in {sleep_time:.2f}s (Attempt {i+1}/{max_retries}) due to: {e}")
                    time.sleep(sleep_time)
            
            raise last_exception
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3)
def load_image(image_url: str) -> Image.Image:
    if image_url.startswith("data:image"):
        header, encoded = image_url.split(",", 1)
        data = base64.b64decode(encoded)
        return Image.open(io.BytesIO(data)).convert('RGB')
    else:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert('RGB')

def apply_line_art_filter(img: Image.Image, size: int = 320) -> Image.Image:
    img = img.resize((size, size))
    img_np = np.array(img)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    return Image.fromarray(thresh).convert('1')

def encode_image_to_base64(img: Image.Image, format: str = "BMP") -> str:
    buffered = io.BytesIO()
    img.save(buffered, format=format)
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    mime_type = format.lower()
    if mime_type == "bmp":
        mime_type = "x-ms-bmp"
    return f"data:image/{mime_type};base64,{img_str}"

def process_line_art_image(image_url: str, size: int = 320, apply_filter: bool = True) -> str:
    if not apply_filter:
        return image_url
    try:
        img = load_image(image_url)
        img = apply_line_art_filter(img, size)
        return encode_image_to_base64(img)
    except Exception as e:
        print(f"Error processing image: {e}")
        return image_url

def get_raw_bitmap_hex(image_url: str, size: int = 320) -> Optional[str]:
    try:
        img = load_image(image_url)
        img = apply_line_art_filter(img, size)
        # img is in '1' mode, tobytes() returns packed bits
        return img.tobytes().hex()
    except Exception as e:
        print(f"Error extracting raw bitmap: {e}")
        return None

def get_embedded_bitmap(image_url: str, size: int = 320) -> Optional[Dict[str, Any]]:
    """Extract a 1-bit bitmap suitable for embedded devices (packed bits)."""
    try:
        img = load_image(image_url)
        img = apply_line_art_filter(img, size)
        # img is in '1' mode, tobytes() returns packed bits (8 pixels per byte)
        raw_bytes = img.tobytes()
        return {
            "data_hex": raw_bytes.hex(),
            "data_b64": base64.b64encode(raw_bytes).decode("utf-8"),
            "width": size,
            "height": size,
            "bits_per_pixel": 1,
            "byte_size": len(raw_bytes)
        }
    except Exception as e:
        print(f"Error extracting embedded bitmap: {e}")
        return None

def get_dhash(img: Image.Image) -> str:
    """Compute a 64-bit difference hash (dHash) for the image."""
    try:
        # Resize to 9x8 and convert to grayscale
        img_resized = img.resize((9, 8), Image.LANCZOS).convert('L')
        pixels = np.array(img_resized)
        # Compare adjacent pixels in each row
        diff = pixels[:, 1:] > pixels[:, :-1]
        # Convert the 64 boolean values to a hex string
        decimal_value = 0
        for index, value in enumerate(diff.flatten()):
            if value:
                decimal_value += 2**(63 - index)
        return hex(decimal_value)[2:].zfill(16)
    except Exception as e:
        print(f"Error computing dHash: {e}")
        return "0" * 16

@retry_with_backoff(max_retries=3)
def get_image_metadata(image_url: str) -> Dict[str, Any]:
    """Extract dimensions, color space, and perceptual hash from an image."""
    try:
        # Load without forced conversion to get original mode if possible
        if image_url.startswith("data:image"):
            header, encoded = image_url.split(",", 1)
            data = base64.b64decode(encoded)
            img = Image.open(io.BytesIO(data))
        else:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            img = Image.open(io.BytesIO(response.content))
            
        width, height = img.size
        color_space = img.mode
        phash = get_dhash(img)
        
        return {
            "width": width,
            "height": height,
            "color_space": color_space,
            "phash": phash
        }
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return {
            "width": 0,
            "height": 0,
            "color_space": "unknown",
            "phash": "0" * 16
        }

# --- External APIs ---

class ReplicateAPI:
    def __init__(self):
        self.api_key = os.getenv("REPLICATE_API_TOKEN")
        if self.api_key:
            os.environ["REPLICATE_API_TOKEN"] = self.api_key

    @retry_with_backoff(max_retries=3)
    def generate_text(self, prompt: str, max_tokens: int = 100) -> str:
        # Try DeepSeek first if available, as it's more reliable in China
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            try:
                ds = DeepSeekAPI()
                res = ds.generate_text(prompt)
                return res.get("text", "").strip()
            except Exception as e:
                print(f"DeepSeek translation fallback error: {e}")

        if not self.api_key:
            raise ValueError("REPLICATE_API_TOKEN is not set.")
        
        try:
            output = replicate.run(
                "meta/meta-llama-3-8b-instruct",
                input={
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                    "top_p": 0.9
                }
            )
            return "".join(output).strip()
        except Exception as e:
            raise RuntimeError(f"Replicate API Error (Text Gen): {e}")

    @retry_with_backoff(max_retries=3)
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
        
        try:
            input_data = {
                "prompt": full_prompt,
                "aspect_ratio": aspect_ratio,
            }
            if seed is not None:
                input_data["seed"] = seed
                
            # Using bytedance/seedream-4 as requested
            output = replicate.run(
                "bytedance/seedream-4",
                input=input_data
            )
            
            # The output for seedream-4 is typically a list of File objects or URLs
            if isinstance(output, list):
                return [str(item) for item in output]
            return [str(output)]
        except Exception as e:
            raise RuntimeError(f"Replicate API Error (Image Gen): {e}")

class IdeogramAPI:
    def __init__(self):
        self.api_key = os.getenv("IDEOGRAM_API_KEY")
        self.base_url = "https://api.ideogram.ai/v1"

    @retry_with_backoff(max_retries=3)
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

def generate_image_with_fallback(prompt: str, seed: Optional[int] = None, protagonist: Optional[str] = None, ref_image: Optional[str] = None, aspect_ratio: str = "1:1", num_images: int = 1, style: str = "default", preferred_engine: Optional[str] = None) -> Optional[List[str]]:
    replicate_api = ReplicateAPI()
    ideogram_api = IdeogramAPI()
    
    # Define available engines and their generation methods
    # Prioritize replicate as requested
    engines = [
        ("replicate", lambda: replicate_api.generate_image(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style)),
        ("ideogram", lambda: ideogram_api.generate_image(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style))
    ]
    
    # If a preferred engine is specified, try to move it to the front
    if preferred_engine:
        preferred = next((e for e in engines if e[0] == preferred_engine), None)
        if preferred:
            engines.remove(preferred)
            engines.insert(0, preferred)
            
    for name, generate_func in engines:
        print(f"Attempting to generate image using: {name}")
        try:
            image_urls = generate_func()
            if image_urls:
                print(f"Successfully generated image using: {name}")
                return image_urls
            else:
                print(f"Engine {name} returned no images.")
        except Exception as e:
            print(f"Engine {name} failed with error: {e}")
            
    return None

# --- API Models ---

class GenerateRequest(BaseModel):
    prompt: str
    engine: str = "replicate"
    protagonist: Optional[str] = None
    anchorImageBase64: Optional[str] = None
    seed: Optional[int] = None
    aspect_ratio: str = "1:1"
    num_images: int = 1
    style: str = "default"
    apply_line_art: bool = True
    include_metadata: bool = False

class FeedbackRequest(BaseModel):
    generation_id: str
    rating: int  # e.g., 1 to 5
    liked: Optional[bool] = None
    comments: Optional[str] = None

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
    image_urls = generate_image_with_fallback(
        english_prompt, 
        req.seed, 
        english_protagonist, 
        req.anchorImageBase64, 
        req.aspect_ratio, 
        req.num_images, 
        req.style, 
        preferred_engine=req.engine
    )

    if not image_urls:
        raise HTTPException(status_code=500, detail="Image generation failed with all available engines.")
        
    # 5. Process Image
    processed_images = []
    raw_bitmaps = []
    embedded_bitmaps = []
    image_metadata = []
    
    for url in image_urls:
        if req.include_metadata:
            image_metadata.append(get_image_metadata(url))
        else:
            image_metadata.append(None)
            
        if req.apply_line_art:
            processed_images.append(process_line_art_image(url, apply_filter=True))
            # Extract structured bitmap data for embedded devices
            eb = get_embedded_bitmap(url)
            embedded_bitmaps.append(eb)
            raw_bitmaps.append(eb["data_hex"] if eb else None)
        else:
            processed_images.append(url)
            raw_bitmaps.append(None)
            embedded_bitmaps.append(None)
    
    generation_id = str(uuid.uuid4())
    
    # Save to history
    history_entry = {
        "generation_id": generation_id,
        "prompt": req.prompt,
        "english_prompt": english_prompt,
        "engine": req.engine,
        "protagonist": protagonist,
        "title": title,
        "aspect_ratio": req.aspect_ratio,
        "num_images": req.num_images,
        "style": req.style,
        "apply_line_art": req.apply_line_art,
        "image_urls": processed_images,
        "raw_bitmaps": raw_bitmaps if req.apply_line_art else None,
        "bitmap_data": embedded_bitmaps if req.apply_line_art else None,
        "metadata": image_metadata if req.include_metadata else None,
        "timestamp": time.time()
    }
    generation_history.append(history_entry)
    
    return {
        "generationId": generation_id,
        "imageUrl": processed_images[0] if processed_images else None,
        "imageUrls": processed_images,
        "bitmaps": raw_bitmaps if req.apply_line_art else None,
        "bitmapData": embedded_bitmaps if req.apply_line_art else None,
        "metadata": image_metadata if req.include_metadata else None,
        "protagonist": protagonist,
        "title": title,
        "prompt": req.prompt
    }

@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest):
    feedback_entry = {
        "generation_id": req.generation_id,
        "rating": req.rating,
        "liked": req.liked,
        "comments": req.comments,
        "timestamp": time.time()
    }
    feedback_store.append(feedback_entry)
    
    # In a real application, you would save this to a database
    # and use it to fine-tune models or adjust prompts.
    
    return {"success": True, "message": "Feedback received"}

@app.get("/api/history")
async def get_history(limit: int = 50):
    # Return history sorted by timestamp descending
    sorted_history = sorted(generation_history, key=lambda x: x["timestamp"], reverse=True)
    return sorted_history[:limit]

class DeepSeekAPI:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None

    @retry_with_backoff(max_retries=3)
    def generate_text(self, prompt: str, system_instruction: str = "You are a helpful assistant.", tools: List[Dict] = None) -> Dict[str, Any]:
        if not self.client:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt}
        ]
        
        try:
            kwargs = {
                "model": "deepseek-chat",
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            
            return {
                "text": message.content,
                "tool_calls": message.tool_calls
            }
        except Exception as e:
            raise RuntimeError(f"DeepSeek API Error: {e}")

    @retry_with_backoff(max_retries=3)
    def transcribe_audio(self, audio_bytes: bytes) -> str:
        # Using OpenAI Whisper compatible API for STT
        # Many China-based relays provide this, or use a dedicated provider
        stt_api_key = os.getenv("STT_API_KEY") or self.api_key
        stt_base_url = os.getenv("STT_BASE_URL") or self.base_url
        stt_client = OpenAI(api_key=stt_api_key, base_url=stt_base_url)
        
        try:
            # Create a file-like object from bytes
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.wav"
            
            transcript = stt_client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
            return transcript.text
        except Exception as e:
            print(f"STT Error: {e}")
            return ""

    @retry_with_backoff(max_retries=3)
    def generate_speech(self, text: str) -> Optional[str]:
        """Convert text to speech and return as base64 encoded string."""
        if not text:
            return None
            
        tts_api_key = os.getenv("TTS_API_KEY") or self.api_key
        tts_base_url = os.getenv("TTS_BASE_URL") or self.base_url
        
        # If no TTS config, skip
        if not tts_api_key:
            return None
            
        try:
            tts_client = OpenAI(api_key=tts_api_key, base_url=tts_base_url)
            response = tts_client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=text
            )
            # Return as base64 string
            return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            print(f"TTS Error: {e}")
            return None

async def process_llm_interaction(prompt_input: Any, api_key: str) -> Dict[str, Any]:
    deepseek = DeepSeekAPI()
    
    # Handle audio input if prompt_input is bytes
    user_text = prompt_input
    if isinstance(prompt_input, bytes):
        user_text = deepseek.transcribe_audio(prompt_input)
        if not user_text:
            error_msg = "我没听清，请再说一遍。"
            return {
                "text_response": error_msg,
                "action": None,
                "audio_base64": deepseek.generate_speech(error_msg)
            }

    system_instruction = "You are a gentle kindergarten teacher named 'Tanqi' (探奇). Speak in Chinese. If the child asks to draw something, call the generate_drawing function. Keep responses short and sweet."
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "generate_drawing",
                "description": "Generate a black and white line art drawing for kids based on the prompt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Visual description of the drawing for children."
                        }
                    },
                    "required": ["prompt"]
                }
            }
        }
    ]
    
    try:
        res = deepseek.generate_text(user_text, system_instruction=system_instruction, tools=tools)
        text_response = res.get("text") or ""
        tool_calls = res.get("tool_calls")
        
        action = None
        
        if tool_calls:
            call = tool_calls[0]
            if call.function.name == "generate_drawing":
                args = json.loads(call.function.arguments)
                prompt = args.get("prompt")
                
                # Actually generate the drawing
                try:
                    # Translate prompt to English for the image generator
                    replicate_api = ReplicateAPI()
                    english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {prompt}")
                    
                    # Generate image using fallback mechanism
                    image_urls = generate_image_with_fallback(english_prompt)
                    
                    if image_urls:
                        # Process the image for printing
                        processed_image = process_line_art_image(image_urls[0])
                        bitmap_hex = get_raw_bitmap_hex(image_urls[0])
                        
                        job_id = str(uuid.uuid4())
                        print_jobs.append({
                            "job_id": job_id,
                            "image_url": processed_image,
                            "bitmap_hex": bitmap_hex,
                            "prompt": prompt,
                            "timestamp": time.time()
                        })
                        
                        action = {"type": "print", "prompt": prompt, "job_id": job_id, "image_url": processed_image, "bitmap_hex": bitmap_hex}
                        
                        # Save to history
                        generation_id = str(uuid.uuid4())
                        history_entry = {
                            "generation_id": generation_id,
                            "prompt": prompt,
                            "english_prompt": english_prompt,
                            "engine": "voice/chat",
                            "protagonist": None,
                            "title": f"🎨 {prompt}",
                            "aspect_ratio": "1:1",
                            "num_images": 1,
                            "style": "default",
                            "apply_line_art": True,
                            "image_urls": [processed_image],
                            "raw_bitmaps": [bitmap_hex],
                            "timestamp": time.time()
                        }
                        generation_history.append(history_entry)
                        
                        if not text_response:
                            text_response = f"好的，我这就画一张{prompt}。"
                    else:
                        text_response = "抱歉，我画不出来这个。"
                except Exception as e:
                    print(f"Error generating drawing from voice: {e}")
                    text_response = "抱歉，画画的时候出错了。"
                    
        if not text_response:
            text_response = "我没听清，请再说一遍。"
            
        # Generate TTS if text_response is available
        audio_base64 = None
        if text_response:
            audio_base64 = deepseek.generate_speech(text_response)
            
        return {
            "text_response": text_response,
            "action": action,
            "audio_base64": audio_base64
        }
    except Exception as e:
        print(f"LLM Handler Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ChatRequest(BaseModel):
    text: str

@app.post("/api/device/v1/chat")
async def handle_chat(req: ChatRequest, request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    return await process_llm_interaction(req.text, api_key)

@app.post("/api/device/v1/voice")
async def handle_voice(request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty audio body received")
        
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    return await process_llm_interaction(body, api_key)

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
    return {
        "success": True,
        "message": "Print job completed successfully",
        "job_id": job_id,
        "status": "finished"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
