import base64
import functools
import hashlib
import io
import os
import random
import time
from typing import Optional, Dict, Any
from PIL import Image
import numpy as np
import cv2
import requests
from scipy.io import wavfile

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

def process_line_art_and_bitmap(image_url: str, size: int = 320) -> tuple[str, str]:
    """Downloads an image exactly once and extracts both processed base64 line-art and raw packed binary hex."""
    try:
        img = load_image(image_url)
        img_filtered = apply_line_art_filter(img, size)
        processed_image = encode_image_to_base64(img_filtered)
        bitmap_hex = img_filtered.tobytes().hex()
        return processed_image, bitmap_hex
    except Exception as e:
        print(f"[ERROR] Combined line art and bitmap processing failed: {e}")
        return image_url, ""

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

def preprocess_audio(audio_bytes: bytes) -> bytes:
    """Preprocess audio to reduce noise and normalize volume using advanced techniques."""
    try:
        import io
        import numpy as np
        from scipy.signal import butter, lfilter
        
        # Log raw input info
        print(f"[DEBUG] [AUDIO_PROC] Processing raw bytes: {len(audio_bytes)} bytes")
        
        try:
            fs, data = wavfile.read(io.BytesIO(audio_bytes))
        except Exception as read_err:
            print(f"[ERROR] [AUDIO_PROC] Failed to read WAV format: {read_err}")
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
        max_amp = np.max(np.abs(audio_float))
        print(f"[DEBUG] [AUDIO_PROC] Signal Stats: Max Amp={max_amp:.6f}")
        
        if max_amp < 0.00001:
            print("[WARNING] [AUDIO_PROC] Silence detected (max_amp < 1e-5).")
            return b"" 

        # 1. Bandpass Filter (Speech range approx 80Hz - 8kHz)
        def bandpass_filter(data, lowcut, highcut, fs, order=2):
            nyq = 0.5 * fs
            low = lowcut / nyq
            high = highcut / nyq
            # Clip if fs is too low
            high = min(high, 0.99)
            b, a = butter(order, [low, high], btype='band')
            return lfilter(b, a, data)

        try:
            # Gentler filter
            audio_float = bandpass_filter(audio_float, 80, min(7000, fs/2 - 100), fs)
        except Exception as filter_err:
            print(f"[WARNING] [AUDIO_PROC] Bandpass filter failed: {filter_err}")

        # 3. Peak Normalization (Target -1dB)
        final_max = np.max(np.abs(audio_float))
        if final_max > 0.0001: 
            audio_float = audio_float / final_max * 0.90 
        else:
            print(f"[WARNING] [AUDIO_PROC] final_max too low after filtering: {final_max:.8f}")
            
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
