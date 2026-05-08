import os
import time
import base64
import json
import io
import uuid
import sys
import functools
import random
import hashlib
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
from scipy.io import wavfile
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

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
# print_jobs = [] # Replaced by database

# In-memory store for feedback (in a real app, use a database)
# feedback_store = [] # Replaced by database

# In-memory store for generation history
# generation_history = []  # Replaced by database

# --- Database Setup ---
DATABASE_URL = "sqlite:///./app_history.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class GenerationHistoryDB(Base):
    __tablename__ = "generation_history"
    id = Column(Integer, primary_key=True, index=True)
    generation_id = Column(String, unique=True, index=True)
    prompt = Column(Text)
    english_prompt = Column(Text, nullable=True)
    engine = Column(String, nullable=True)
    protagonist = Column(String, nullable=True)
    title = Column(String, nullable=True)
    aspect_ratio = Column(String, nullable=True)
    num_images = Column(Integer, default=1)
    style = Column(String, default="default")
    apply_line_art = Column(Integer, default=1)
    image_urls = Column(Text, nullable=True) # Stored as JSON string
    raw_bitmaps = Column(Text, nullable=True) # Stored as JSON string
    bitmap_data = Column(Text, nullable=True) # Stored as JSON string
    metadata_json = Column(Text, nullable=True) # Stored as JSON string
    timestamp = Column(Float)

class FeedbackDB(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, index=True)
    generation_id = Column(String, index=True)
    rating = Column(Integer)
    liked = Column(Integer, nullable=True)
    comments = Column(Text, nullable=True)
    timestamp = Column(Float)

class PrintJobDB(Base):
    __tablename__ = "print_jobs"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True)
    image_url = Column(Text)
    bitmap_hex = Column(Text, nullable=True)
    prompt = Column(Text)
    timestamp = Column(Float)

Base.metadata.create_all(bind=engine)

def save_history_to_db(entry):
    db = SessionLocal()
    try:
        db_entry = GenerationHistoryDB(
            generation_id=entry["generation_id"],
            prompt=entry["prompt"],
            english_prompt=entry.get("english_prompt"),
            engine=entry.get("engine"),
            protagonist=entry.get("protagonist"),
            title=entry.get("title"),
            aspect_ratio=entry.get("aspect_ratio"),
            num_images=entry.get("num_images", 1),
            style=entry.get("style", "default"),
            apply_line_art=1 if entry.get("apply_line_art", True) else 0,
            image_urls=json.dumps(entry.get("image_urls")),
            raw_bitmaps=json.dumps(entry.get("raw_bitmaps")),
            bitmap_data=json.dumps(entry.get("bitmap_data")),
            metadata_json=json.dumps(entry.get("metadata")),
            timestamp=entry["timestamp"]
        )
        db.add(db_entry)
        db.commit()
    except Exception as e:
        print(f"Error saving history to DB: {e}")
        db.rollback()
    finally:
        db.close()

def get_history_from_db(limit=50):
    db = SessionLocal()
    try:
        entries = db.query(GenerationHistoryDB).order_by(GenerationHistoryDB.timestamp.desc()).limit(limit).all()
        return [
            {
                "generation_id": e.generation_id,
                "prompt": e.prompt,
                "english_prompt": e.english_prompt,
                "engine": e.engine,
                "protagonist": e.protagonist,
                "title": e.title,
                "aspect_ratio": e.aspect_ratio,
                "num_images": e.num_images,
                "style": e.style,
                "apply_line_art": bool(e.apply_line_art),
                "image_urls": json.loads(e.image_urls) if e.image_urls else [],
                "raw_bitmaps": json.loads(e.raw_bitmaps) if e.raw_bitmaps else [],
                "bitmap_data": json.loads(e.bitmap_data) if e.bitmap_data else None,
                "metadata": json.loads(e.metadata_json) if e.metadata_json else None,
                "timestamp": e.timestamp
            }
            for e in entries
        ]
    except Exception as e:
        print(f"Error getting history from DB: {e}")
        return []
    finally:
        db.close()

def save_feedback_to_db(entry):
    db = SessionLocal()
    try:
        db_entry = FeedbackDB(
            generation_id=entry["generation_id"],
            rating=entry["rating"],
            liked=1 if entry.get("liked") else 0 if entry.get("liked") is False else None,
            comments=entry.get("comments"),
            timestamp=entry["timestamp"]
        )
        db.add(db_entry)
        db.commit()
    except Exception as e:
        print(f"Error saving feedback to DB: {e}")
        db.rollback()
    finally:
        db.close()

def save_print_job_to_db(job):
    db = SessionLocal()
    try:
        db_job = PrintJobDB(
            job_id=job["job_id"],
            image_url=job["image_url"],
            bitmap_hex=job.get("bitmap_hex"),
            prompt=job["prompt"],
            timestamp=job["timestamp"]
        )
        db.add(db_job)
        db.commit()
    except Exception as e:
        print(f"Error saving print job to DB: {e}")
        db.rollback()
    finally:
        db.close()

def get_print_jobs_from_db():
    db = SessionLocal()
    try:
        jobs = db.query(PrintJobDB).order_by(PrintJobDB.timestamp.asc()).all()
        return [
            {
                "job_id": j.job_id,
                "image_url": j.image_url,
                "bitmap_hex": j.bitmap_hex,
                "prompt": j.prompt,
                "timestamp": j.timestamp
            }
            for j in jobs
        ]
    except Exception as e:
        print(f"Error getting print jobs from DB: {e}")
        return []
    finally:
        db.close()

def delete_print_job_from_db(job_id):
    db = SessionLocal()
    try:
        db.query(PrintJobDB).filter(PrintJobDB.job_id == job_id).delete()
        db.commit()
    except Exception as e:
        print(f"Error deleting print job from DB: {e}")
        db.rollback()
    finally:
        db.close()

# --- Helper Functions ---

def retry_with_backoff(max_retries=3, initial_delay=1, backoff_factor=2, jitter=True):
    """Decorator for retrying functions with exponential backoff and robust error handling."""
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
                    error_str = str(e).lower()
                    
                    # Categorize the error for specific logging
                    error_type = "Unknown Error"
                    if any(x in error_str for x in ["429", "too many requests", "rate limit"]):
                        error_type = "Rate Limit Error"
                    elif any(x in error_str for x in ["unauthorized", "invalid api key", "401", "403", "authentication"]):
                        error_type = "Authentication Error"
                    elif any(x in error_str for x in ["500", "502", "503", "504", "server error", "bad gateway"]):
                        error_type = "Server Error"
                    elif any(x in error_str for x in ["timeout", "timed out"]):
                        error_type = "Timeout Error"
                        
                    print(f"[{error_type}] in {func.__name__}: {e}")
                    
                    # Don't retry on certain fatal errors (e.g., auth, validation)
                    if error_type == "Authentication Error" or any(x in error_str for x in ["422", "validation"]):
                        print(f"Fatal error in {func.__name__}, aborting retries.")
                        raise e
                        
                    if i == max_retries:
                        print(f"Max retries ({max_retries}) reached for {func.__name__}.")
                        break
                    
                    # Exponential backoff
                    sleep_time = delay * (backoff_factor ** i)
                    if jitter:
                        sleep_time += random.uniform(0, 0.1 * sleep_time)
                    
                    print(f"Retrying {func.__name__} in {sleep_time:.2f}s (Attempt {i+1}/{max_retries})...")
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

def preprocess_audio(audio_bytes: bytes) -> bytes:
    """Preprocess audio to reduce noise and normalize volume."""
    try:
        import io
        import numpy as np
        
        # Log raw input info
        print(f"[DEBUG] [AUDIO_PROC] Processing raw bytes: {len(audio_bytes)} bytes")
        
        try:
            fs, data = wavfile.read(io.BytesIO(audio_bytes))
        except Exception as read_err:
            print(f"[ERROR] [AUDIO_PROC] Failed to read WAV format: {read_err}")
            # Try to see if it's a raw stream or header-less (though client sends WAV)
            return audio_bytes

        duration = len(data) / fs
        print(f"[DEBUG] [AUDIO_PROC] Format: {data.dtype}, Channels: {1 if len(data.shape) == 1 else data.shape[1]}, FS: {fs}, Duration: {duration:.2f}s")
        
        # Convert to float32 normalized [-1, 1]
        if data.dtype == np.int16:
            audio_float = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            audio_float = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            audio_float = (data.astype(np.float32) - 128.0) / 128.0
        else:
            audio_float = data.astype(np.float32)
            
        # Ensure mono
        if len(audio_float.shape) > 1:
            audio_float = np.mean(audio_float, axis=1)
            
        # Log signal stats
        rms = np.sqrt(np.mean(audio_float**2))
        max_amp = np.max(np.abs(audio_float))
        print(f"[DEBUG] [AUDIO_PROC] Signal Stats: Max Amp={max_amp:.4f}, RMS={rms:.4f}")
        
        # If extremely silent, we don't need to process further or send to STT
        if max_amp < 0.00001:
            print("[WARNING] [AUDIO_PROC] Silence detected.")
            return b"" 

        # 1. Simple Noise Reduction (Moving Average)
        window_size = 3
        if len(audio_float) > window_size:
            audio_float = np.convolve(audio_float, np.ones(window_size)/window_size, mode='same')
            
        # 2. Peak Normalization
        if max_amp > 0.0001: 
            audio_float = audio_float / max_amp * 0.90
            
        # Convert back to int16 PCM
        data_int16 = (audio_float * 32767).astype(np.int16)
        
        # Write back to bytes
        output = io.BytesIO()
        wavfile.write(output, fs, data_int16)
        processed_bytes = output.getvalue()
        
        print(f"[DEBUG] [AUDIO_PROC] Preprocessing complete: {len(audio_bytes)} -> {len(processed_bytes)} bytes")
        return processed_bytes
        
    except Exception as e:
        print(f"[ERROR] [AUDIO_PROC] Preprocessing critical failure: {e}")
        import traceback
        traceback.print_exc()
        return audio_bytes

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
            return None
        else:
            error_msg = f"Ideogram API Error: {response.status_code} {response.text}"
            print(error_msg)
            raise RuntimeError(error_msg)

CACHE_FILE = "image_cache.json"
STT_CACHE_FILE = "stt_cache.json"
TTS_CACHE_FILE = "tts_cache.json"
MAX_CACHE_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 days

def load_cache(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading cache {filename}: {e}")
    return {}

def save_cache(filename, cache_data):
    try:
        # Maintenance: Remove old entries before saving
        now = time.time()
        to_delete = []
        for key, entry in cache_data.items():
            if isinstance(entry, dict) and "timestamp" in entry:
                if now - entry["timestamp"] > MAX_CACHE_AGE_SECONDS:
                    to_delete.append(key)
        
        for key in to_delete:
            del cache_data[key]
            
        with open(filename, "w") as f:
            json.dump(cache_data, f)
    except Exception as e:
        print(f"Error saving cache {filename}: {e}")

def load_image_cache():
    return load_cache(CACHE_FILE)

def save_image_cache(cache_data):
    save_cache(CACHE_FILE, cache_data)

IMAGE_CACHE = load_image_cache()
STT_CACHE = load_cache(STT_CACHE_FILE)
TTS_CACHE = load_cache(TTS_CACHE_FILE)

def get_image_cache_key(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style, preferred_engine):
    key_parts = [
        str(prompt),
        str(seed),
        str(protagonist),
        str(aspect_ratio),
        str(num_images),
        str(style),
        str(preferred_engine)
    ]
    if ref_image:
        key_parts.append(hashlib.md5(ref_image.encode('utf-8')).hexdigest())
    
    key_str = "|".join(key_parts)
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

def generate_image_with_fallback(prompt: str, seed: Optional[int] = None, protagonist: Optional[str] = None, ref_image: Optional[str] = None, aspect_ratio: str = "1:1", num_images: int = 1, style: str = "default", preferred_engine: Optional[str] = None) -> Dict[str, Any]:
    global IMAGE_CACHE
    cache_key = get_image_cache_key(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style, preferred_engine)
    
    if cache_key in IMAGE_CACHE:
        entry = IMAGE_CACHE[cache_key]
        if isinstance(entry, list):
            # Old format, migrate it
            print(f"Cache hit (Legacy) for prompt: '{prompt}'.")
            return {"urls": entry, "metadata": [None] * len(entry)}
        
        print(f"Cache hit for prompt: '{prompt}'.")
        return {
            "urls": entry.get("urls", []),
            "metadata": entry.get("metadata", [None] * len(entry.get("urls", [])))
        }

    replicate_api = ReplicateAPI()
    ideogram_api = IdeogramAPI()
    
    # Define available engines and their generation methods
    engines = [
        ("replicate", lambda: replicate_api.generate_image(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style)),
        ("ideogram", lambda: ideogram_api.generate_image(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style))
    ]
    
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
                
                # Fetch metadata for the new images
                metadata = []
                for url in image_urls:
                    try:
                        metadata.append(get_image_metadata(url))
                    except Exception as me:
                        print(f"Failed to fetch metadata for {url}: {me}")
                        metadata.append(None)
                
                IMAGE_CACHE[cache_key] = {
                    "urls": image_urls,
                    "metadata": metadata,
                    "timestamp": time.time(),
                    "engine": name
                }
                save_image_cache(IMAGE_CACHE)
                return {"urls": image_urls, "metadata": metadata}
            else:
                print(f"Engine {name} returned no images.")
        except Exception as e:
            print(f"Engine {name} failed with error: {e}")
            
    return {"urls": None, "metadata": None}

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
    result = generate_image_with_fallback(
        english_prompt, 
        req.seed, 
        english_protagonist, 
        req.anchorImageBase64, 
        req.aspect_ratio, 
        req.num_images, 
        req.style, 
        preferred_engine=req.engine
    )
    image_urls = result["urls"]
    cached_metadata = result["metadata"]

    if not image_urls:
        raise HTTPException(status_code=500, detail="Image generation failed with all available engines.")
        
    # 5. Process Image
    processed_images = []
    raw_bitmaps = []
    embedded_bitmaps = []
    image_metadata = []
    
    for i, url in enumerate(image_urls):
        if req.include_metadata:
            # Use cached metadata if available, otherwise fetch it
            if cached_metadata and i < len(cached_metadata) and cached_metadata[i]:
                image_metadata.append(cached_metadata[i])
            else:
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
    save_history_to_db(history_entry)
    
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
    save_feedback_to_db(feedback_entry)
    return {"success": True, "message": "Feedback received"}

@app.get("/api/history")
async def get_history(limit: int = 50):
    # Return history sorted by timestamp descending from database
    return get_history_from_db(limit)

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
        
        print(f"DeepSeek: System='{system_instruction[:50]}...', User='{prompt}'")
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
            print(f"DeepSeek response: '{message.content[:100]}...' {'(has tool calls)' if message.tool_calls else ''}")
            
            return {
                "text": message.content,
                "tool_calls": message.tool_calls
            }
        except Exception as e:
            print(f"DeepSeek chat error: {e}")
            raise RuntimeError(f"DeepSeek API Error: {e}")

    @retry_with_backoff(max_retries=2)
    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe audio with fallback support for multiple providers."""
        global STT_CACHE
        
        if not audio_bytes or len(audio_bytes) < 100:
            print("[DEBUG] [STT] Audio too short or empty, skipping.")
            return ""

        # 1. Preprocess the audio for better recognition
        processed_audio = preprocess_audio(audio_bytes)
        if not processed_audio:
            print("[DEBUG] [STT] Preprocessing returned empty (likely silent), skipping.")
            return ""
            
        audio_hash = hashlib.md5(processed_audio).hexdigest()
        
        if audio_hash in STT_CACHE:
            print(f"[DEBUG] [STT] Cache hit for audio hash: {audio_hash}")
            return STT_CACHE[audio_hash].get("text", "")

        input_size_kb = len(processed_audio) / 1024
        print(f"[DEBUG] [STT] Starting transcription for {input_size_kb:.2f} KB audio (Hash: {audio_hash})")
        providers = []
        
        # 1. Primary STT from Env
        stt_key = os.getenv("STT_API_KEY")
        stt_url = os.getenv("STT_BASE_URL")
        if stt_key:
            providers.append({"name": "Primary (Env)", "key": stt_key, "url": stt_url})
            
        # 2. SiliconFlow Fallback
        sf_key = os.getenv("SILICONFLOW_API_KEY")
        if sf_key:
            providers.append({
                "name": "SiliconFlow", 
                "key": sf_key, 
                "url": "https://api.siliconflow.cn/v1",
                "model": os.getenv("SILICONFLOW_STT_MODEL", "SYSTRAN/faster-whisper-large-v3")
            })
            
        # 3. OpenAI Fallback
        oa_key = os.getenv("OPENAI_API_KEY")
        if oa_key:
            providers.append({
                "name": "OpenAI", 
                "key": oa_key, 
                "url": "https://api.openai.com/v1",
                "model": "whisper-1"
            })

        # 4. DeepSeek Key (only if URL is likely a relay or custom)
        ds_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if self.api_key and "deepseek.com" not in ds_url.lower():
             providers.append({
                 "name": "DeepSeek Relay", 
                 "key": self.api_key, 
                 "url": ds_url,
                 "model": os.getenv("DEEPSEEK_STT_MODEL", "whisper-1")
             })

        # Override model for primary if provided
        primary_model = os.getenv("STT_MODEL", "whisper-1")
        if stt_key and providers:
            providers[0]["model"] = primary_model

        if not providers:
            print("[ERROR] [STT] No valid STT providers configured in environment variables.")
            return ""

        errors = []
        for provider in providers:
            try:
                # Skip if key is missing (fallback safety)
                if not provider["key"]: continue
                
                start_time = time.time()
                model_name = provider.get("model", "whisper-1")
                
                # SiliconFlow default STT model correction
                if provider["name"] == "SiliconFlow" and model_name == "Pro/OpenGVLab/InternVL2-8B":
                     model_name = "SYSTRAN/faster-whisper-large-v3" # Popular on SiliconFlow
                
                print(f"[DEBUG] [STT] Attempting with {provider['name']} using model {model_name}...")
                client = OpenAI(api_key=provider["key"], base_url=provider.get("url"))
                
                audio_file = io.BytesIO(processed_audio)
                audio_file.name = "audio.wav"
                
                transcript = client.audio.transcriptions.create(
                    model=model_name, 
                    file=audio_file,
                    timeout=25
                )
                
                duration = time.time() - start_time
                if transcript.text:
                    print(f"[DEBUG] [STT] Success ({provider['name']}) in {duration:.2f}s: '{transcript.text}'")
                    
                    # Update cache
                    STT_CACHE[audio_hash] = {
                        "text": transcript.text,
                        "timestamp": time.time(),
                        "provider": provider["name"]
                    }
                    save_cache(STT_CACHE_FILE, STT_CACHE)
                    
                    return transcript.text
                else:
                    print(f"[WARNING] [STT] Provider {provider['name']} returned empty text in {duration:.2f}s")
            except Exception as e:
                err_msg = f"STT Provider {provider['name']} failed: {str(e)}"
                print(f"[ERROR] [STT] {err_msg}")
                errors.append(err_msg)
                continue
        
        print(f"[ERROR] [STT] All STT providers failed: {'; '.join(errors)}")
        return ""

    @retry_with_backoff(max_retries=2)
    def generate_speech(self, text: str) -> Optional[str]:
        """Convert text to speech with fallback support for multiple providers."""
        if not text:
            return None
        
        global TTS_CACHE
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        
        if text_hash in TTS_CACHE:
            print(f"[DEBUG] [TTS] Cache hit for text hash: {text_hash}")
            return TTS_CACHE[text_hash].get("audio_base64")

        print(f"[DEBUG] [TTS] Generating speech for: '{text[:50]}...'")
        providers = []
        
        # 1. Primary TTS from Env
        tts_key = os.getenv("TTS_API_KEY")
        tts_url = os.getenv("TTS_BASE_URL")
        if tts_key:
             providers.append({"name": "Primary (Env)", "key": tts_key, "url": tts_url})
             
        # 2. SiliconFlow Fallback
        sf_key = os.getenv("SILICONFLOW_API_KEY")
        if sf_key:
            providers.append({"name": "SiliconFlow", "key": sf_key, "url": "https://api.siliconflow.cn/v1"})
            
        # 3. OpenAI Fallback
        oa_key = os.getenv("OPENAI_API_KEY")
        if oa_key:
            providers.append({"name": "OpenAI", "key": oa_key, "url": "https://api.openai.com/v1"})

        if not providers:
            print("[WARNING] [TTS] No valid TTS providers configured.")
            return None

        for provider in providers:
            try:
                # Skip if key is missing
                if not provider["key"]: continue
                
                start_time = time.time()
                print(f"[DEBUG] [TTS] Attempting with {provider['name']} at {provider.get('url', 'default')}...")
                client = OpenAI(api_key=provider["key"], base_url=provider.get("url"))
                response = client.audio.speech.create(
                    model="tts-1",
                    voice="alloy",
                    input=text,
                    timeout=20
                )
                duration = time.time() - start_time
                base64_data = base64.b64encode(response.content).decode('utf-8')
                print(f"[DEBUG] [TTS] Success ({provider['name']}) in {duration:.2f}s, size: {len(base64_data)} chars")
                
                # Update cache
                TTS_CACHE[text_hash] = {
                    "audio_base64": base64_data,
                    "timestamp": time.time(),
                    "provider": provider["name"]
                }
                save_cache(TTS_CACHE_FILE, TTS_CACHE)
                
                return base64_data
            except Exception as e:
                print(f"[ERROR] [TTS] Provider {provider['name']} failed: {e}")
                continue
        
        print("[ERROR] [TTS] All TTS providers failed.")
        return None

async def process_llm_interaction(prompt_input: Any, api_key: str) -> Dict[str, Any]:
    start_time = time.time()
    deepseek = DeepSeekAPI()
    
    # Handle audio input if prompt_input is bytes
    user_text = prompt_input
    if isinstance(prompt_input, bytes):
        print(f"[DEBUG] [CORE] Received voice input: {len(prompt_input)} bytes")
        try:
            user_text = deepseek.transcribe_audio(prompt_input)
        except Exception as e:
            print(f"[ERROR] [CORE] Failed to transcribe audio after retries: {e}")
            user_text = ""
            
        if not user_text:
            print("[DEBUG] [CORE] STT returned empty text. Returning fallback message.")
            error_msg = "我没听清，请再说一遍。"
            try:
                audio_base64 = deepseek.generate_speech(error_msg)
            except Exception as e:
                print(f"[ERROR] [CORE] Failed to generate fallback speech: {e}")
                audio_base64 = None
                
            return {
                "text_response": error_msg,
                "action": None,
                "audio_base64": audio_base64
            }
        print(f"[DEBUG] [CORE] Transcribed Text: '{user_text}'")
    else:
        print(f"[DEBUG] [CORE] Received chat input: '{user_text}'")

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
        print(f"[DEBUG] [CORE] Sending text to LLM (DeepSeek)...")
        res = deepseek.generate_text(user_text, system_instruction=system_instruction, tools=tools)
        text_response = res.get("text") or ""
        tool_calls = res.get("tool_calls")
        
        print(f"[DEBUG] [CORE] LLM Response: '{text_response[:100]}...' | Tool calls: {len(tool_calls) if tool_calls else 0}")
        
        action = None
        
        if tool_calls:
            call = tool_calls[0]
            if call.function.name == "generate_drawing":
                args = json.loads(call.function.arguments)
                prompt = args.get("prompt")
                print(f"[DEBUG] [CORE] LLM requested drawing: '{prompt}'")
                
                # Actually generate the drawing
                try:
                    # Translate prompt to English for the image generator
                    replicate_api = ReplicateAPI()
                    print(f"[DEBUG] [CORE] Translating logic to English...")
                    english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {prompt}")
                    print(f"[DEBUG] [CORE] English Prompt: '{english_prompt}'")
                    
                    # Generate image using fallback mechanism
                    result = generate_image_with_fallback(english_prompt)
                    image_urls = result["urls"]
                    
                    if image_urls:
                        # Process the image for printing
                        print(f"[DEBUG] [CORE] Image generated, processing for line art...")
                        processed_image = process_line_art_image(image_urls[0])
                        bitmap_hex = get_raw_bitmap_hex(image_urls[0])
                        
                        job_id = str(uuid.uuid4())
                        job_data = {
                            "job_id": job_id,
                            "image_url": processed_image,
                            "bitmap_hex": bitmap_hex,
                            "prompt": prompt,
                            "timestamp": time.time()
                        }
                        save_print_job_to_db(job_data)
                        
                        action = {"type": "print", "prompt": prompt, "job_id": job_id, "image_url": processed_image, "bitmap_hex": bitmap_hex}
                        print(f"[DEBUG] [CORE] Drawing job created: {job_id}")
                        
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
                        save_history_to_db(history_entry)
                        
                        if not text_response:
                            text_response = f"好的，我这就画一张{prompt}。"
                    else:
                        print("[ERROR] [CORE] Image generation returned no URLs.")
                        text_response = "抱歉，我画不出来这个。"
                except Exception as e:
                    print(f"[ERROR] [CORE] Error generating drawing from voice: {e}")
                    text_response = "抱歉，画画的时候出错了。"
                    
        if not text_response:
            text_response = "我没听清，请再说一遍。"
            
        # Generate TTS if text_response is available
        audio_base64 = None
        if text_response:
            try:
                audio_base64 = deepseek.generate_speech(text_response)
            except Exception as e:
                print(f"[ERROR] [CORE] Failed to generate final response speech: {e}")
                audio_base64 = None
        
        total_duration = time.time() - start_time
        print(f"[DEBUG] [CORE] total processing completed in {total_duration:.2f}s")
            
        return {
            "text_response": text_response,
            "action": action,
            "audio_base64": audio_base64
        }
    except Exception as e:
        print(f"[ERROR] [CORE] LLM Handler Error: {e}")
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
    ua = request.headers.get("user-agent")
    print(f"[DEBUG] [CONN] Incoming voice request from UA: {ua}, Token: {token[:5]}***")
    if not token:
        print("Unauthorized: missing x-device-token")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    body = await request.body()
    if not body:
        print("Bad Request: empty body")
        raise HTTPException(status_code=400, detail="Empty audio body received")
    
    print(f"Voice body size: {len(body)} bytes")
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        print("Internal Server Error: API key missing")
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    return await process_llm_interaction(body, api_key)

@app.get("/api/device/v1/print-jobs")
async def get_print_jobs(request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    jobs = get_print_jobs_from_db()
    if jobs:
        job = jobs[0]
        return {
            "has_job": True,
            **job
        }
    return {"has_job": False}

@app.get("/")
async def root():
    return {"status": "ok", "message": "Toddler Drawing Dreamer API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/api/device/v1/print-jobs/{job_id}/complete")
async def complete_print_job(job_id: str, request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    delete_print_job_from_db(job_id)
    return {
        "success": True,
        "message": "Print job completed successfully",
        "job_id": job_id,
        "status": "finished"
    }

@app.post("/api/admin/clear-cache")
async def clear_cache(request: Request):
    """Admin endpoint to clear the image cache."""
    # Simple check for a secret if provided, otherwise allow
    admin_key = os.getenv("ADMIN_KEY")
    if admin_key:
        auth_header = request.headers.get("Authorization")
        if auth_header != f"Bearer {admin_key}":
            raise HTTPException(status_code=403, detail="Forbidden")
            
    global IMAGE_CACHE, STT_CACHE, TTS_CACHE
    IMAGE_CACHE = {}
    STT_CACHE = {}
    TTS_CACHE = {}
    
    for f_path in [CACHE_FILE, STT_CACHE_FILE, TTS_CACHE_FILE]:
        if os.path.exists(f_path):
            os.remove(f_path)
            
    print("All caches cleared manually.")
    return {"status": "success", "message": "All caches cleared"}




