import base64
import hashlib
import json
import os
import time
import io
from typing import Optional, List, Dict, Any
from openai import OpenAI
import requests
import replicate

from src.config import (
    ARK_API_KEY, ARK_AUDIO_MODEL, ARK_DRAW_MODEL, ARK_TTS_MODEL,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
    REPLICATE_API_TOKEN, IDEOGRAM_API_KEY,
    STT_API_KEY, STT_BASE_URL, STT_MODEL,
    TTS_API_KEY, TTS_BASE_URL,
    SILICONFLOW_API_KEY, SILICONFLOW_STT_MODEL,
    OPENAI_API_KEY
)
from src.utils import retry_with_backoff, preprocess_audio, get_image_metadata

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

IMAGE_CACHE = load_cache(CACHE_FILE)
STT_CACHE = load_cache(STT_CACHE_FILE)
TTS_CACHE = load_cache(TTS_CACHE_FILE)

class DeepSeekAPI:
    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
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
        if STT_API_KEY:
            providers.append({"name": "Primary (Env)", "key": STT_API_KEY, "url": STT_BASE_URL})
            
        # 2. SiliconFlow Fallback
        if SILICONFLOW_API_KEY:
            providers.append({
                "name": "SiliconFlow", 
                "key": SILICONFLOW_API_KEY, 
                "url": "https://api.siliconflow.cn/v1",
                "model": SILICONFLOW_STT_MODEL
            })
            
        # 3. OpenAI Fallback
        if OPENAI_API_KEY:
            providers.append({
                "name": "OpenAI", 
                "key": OPENAI_API_KEY, 
                "url": "https://api.openai.com/v1",
                "model": "whisper-1"
            })

        # 4. DeepSeek Key (only if URL is likely a relay or custom)
        if self.api_key and "deepseek.com" not in self.base_url.lower():
             providers.append({
                 "name": "DeepSeek Relay", 
                 "key": self.api_key, 
                 "url": self.base_url,
                 "model": os.getenv("DEEPSEEK_STT_MODEL", "whisper-1")
             })

        # Override model for primary if provided
        if STT_MODEL and providers:
            providers[0]["model"] = STT_MODEL
        elif STT_BASE_URL and "siliconflow.cn" in STT_BASE_URL.lower() and providers:
            # Default for SiliconFlow if not explicit
            providers[0]["model"] = "FunAudioLLM/SenseVoiceSmall"
            providers[0]["name"] = "SiliconFlow (Env)"
        elif STT_API_KEY and providers:
            # Fallback to whisper-1 for generic OpenAI-compatible providers
            providers[0]["model"] = "whisper-1"

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
                
                # Use Chinese language hint for better recognition
                transcript = client.audio.transcriptions.create(
                    model=model_name, 
                    file=audio_file,
                    language="zh",
                    timeout=25
                )
                
                duration = time.time() - start_time
                if transcript and hasattr(transcript, 'text') and transcript.text:
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
                    print(f"[WARNING] [STT] {provider['name']} returned empty text in {duration:.2f}s. Full response: {transcript}")
                    errors.append(f"{provider['name']} returned empty text")
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
        
        # 1. Doubao Voice Design (User requested "使用Doubao-音色设计")
        if ARK_API_KEY:
             providers.append({
                 "name": "Doubao-VoiceDesign",
                 "key": ARK_API_KEY,
                 "url": "https://ark.cn-beijing.volces.com/api/v3",
                 "model": ARK_TTS_MODEL
             })
        
        # 2. Primary TTS from Env
        if TTS_API_KEY:
             providers.append({"name": "Primary (Env)", "key": TTS_API_KEY, "url": TTS_BASE_URL})
             
        # 3. SiliconFlow Fallback
        if SILICONFLOW_API_KEY:
            providers.append({"name": "SiliconFlow", "key": SILICONFLOW_API_KEY, "url": "https://api.siliconflow.cn/v1"})
            
        # 4. OpenAI Fallback
        if OPENAI_API_KEY:
            providers.append({"name": "OpenAI", "key": OPENAI_API_KEY, "url": "https://api.openai.com/v1"})

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
                
                # Use correct model and voice depending on provider
                model_name = "tts-1"
                voice_name = "alloy"
                if provider["name"] == "Doubao-VoiceDesign":
                    model_name = provider.get("model", "Doubao-Seed-VoiceDesign-1.0")
                    voice_name = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
                elif "siliconflow.cn" in provider.get("url", "").lower():
                    model_name = "FunAudioLLM/CosyVoice2-0.5B"
                    voice_name = "fc_female"
                    
                response = client.audio.speech.create(
                    model=model_name,
                    voice=voice_name,
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


class DoubaoAPI:
    def __init__(self):
        self.api_key = ARK_API_KEY
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.audio_model = ARK_AUDIO_MODEL
        self.draw_model = ARK_DRAW_MODEL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None

    @retry_with_backoff(max_retries=2)
    def generate_image(self, prompt: str, aspect_ratio: str = "1:1", num_images: int = 1) -> Optional[List[str]]:
        if not self.client:
            raise ValueError("ARK_API_KEY is not set.")
        
        # Native Chinese prompt strategy
        optimized_prompt = f"极简黑白儿童简笔画，一个可爱卡通的{prompt}，高对比度，纯白背景，纯黑线条，1-bit 扁平矢量线稿，无渐变，无阴影，居中，极简美学，适合热敏纸打印。CRITICAL: NO TEXT, NO ENGLISH WORDS."
        
        print(f"[DEBUG] [DOUBAO_DRAW] Generating prompt: '{optimized_prompt}'")
        try:
            response = self.client.images.generate(
                model=self.draw_model,
                prompt=optimized_prompt,
                size="2K",  # 2K is supported
                response_format="url",
                watermark=False,
                extra_body={
                    "optimize_prompt_options": {
                        "mode": "fast"
                    }
                }
            )
            urls = [item.url for item in response.data]
            print(f"[DEBUG] [DOUBAO_DRAW] Success! Generated URL: {urls[0] if urls else 'None'}")
            return urls
        except Exception as e:
            print(f"[ERROR] [DOUBAO_DRAW] Error generating image: {e}")
            raise RuntimeError(f"Doubao Seedream 5.0 pro API Error: {e}")

    @retry_with_backoff(max_retries=2)
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        if not self.client:
            return None
        try:
            response = self.client.embeddings.create(
                model="doubao-embedding-vision-240528",
                input=[text]
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"[ERROR] [DOUBAO_EMBED] Vision embedding failed, trying text embedding: {e}")
            try:
                response = self.client.embeddings.create(
                    model="doubao-embedding-text-240715",
                    input=[text]
                )
                return response.data[0].embedding
            except Exception as e2:
                print(f"[ERROR] [DOUBAO_EMBED] Text embedding also failed: {e2}")
                return [0.0] * 1024

    @retry_with_backoff(max_retries=2)
    def unified_audio_chat(self, audio_bytes: bytes) -> Optional[Dict[str, Any]]:
        if not self.client:
            raise ValueError("ARK_API_KEY is not set.")
        
        processed_audio = preprocess_audio(audio_bytes)
        if not processed_audio:
            print("[DEBUG] [DOUBAO_AUDIO] Audio is silent or empty.")
            return None
            
        base64_audio = base64.b64encode(processed_audio).decode('utf-8')
        
        system_instruction = """你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。
你的任务是与小朋友进行顺畅好玩的互动聊天。请仔细聆听小朋友的录音，并在输出中严格返回一个 JSON 对象，结构如下：
{
  "user_transcript": "（在这里填写你听写出的小朋友的录音原话，必须是中文）",
  "assistant_reply": "（在这里填写你作为温柔的探奇老师对小朋友的回答，保持简短、充满童趣，控制在 3-5 句话内）",
  "requires_drawing": true/false（布尔值，判断小朋友是否有画画的需求，比如提到“画一个...”、“想要一个画”等）,
  "drawing_prompt": "（如果requires_drawing为true，在此处提取出小朋友想要画画的具体主题，如'小猫'、'红色的赛车'，否则填空字符串）",
  "psych_metrics": {
    "detected_emotions": ["（识别出小朋友说话时的主要情绪，如：快乐、同理心、悲伤、焦虑、好奇、愤怒等，可以填1-2个）"],
    "linguistic_richness_score": （小数值，范围0.0~1.0，根据小朋友话语的句子完整度和词汇丰富度进行打分）,
    "cognitive_milestone_ref": "（根据小朋友表达的特征，标注其当前的心理与认知发展特征，如：感知运动阶段、前运算符号思维、同理心萌芽等）",
    "attention_span_seconds": 15（估算的小朋友专注时长，默认15即可）,
    "key_interests": ["（提取小朋友话语中的核心关切或兴趣，如：小动物、天气、玩具、大自然等，可填1-2个）"],
    "requires_attention": false（布尔值，若识别到极度消极、焦虑、恐惧、分离焦虑或明显异常心理，则填true，否则为false）
  }
}
请确保你的回复必须是合法的 JSON 对象。绝对不能包含 markdown 格式标记（如 ```json 等），也不能有任何 JSON 以外的解释文本。"""

        try:
            print(f"[DEBUG] [DOUBAO_AUDIO] Sending audio chat to {self.audio_model}...")
            response = self.client.chat.completions.create(
                model=self.audio_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": base64_audio,
                                    "format": "wav"
                                }
                            },
                            {
                                "type": "text",
                                "text": "这是小朋友刚才说的话，请你识别并温柔地回答。如果他提到了想要画画，请引导并鼓励他描述想画什么。"
                            }
                        ]
                    }
                ],
                timeout=25
            )
            content = response.choices[0].message.content
            print(f"[DEBUG] [DOUBAO_AUDIO] Raw response: '{content}'")
            
            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.split("\n")
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    content_clean = "\n".join(lines[1:-1])
            
            parsed_data = json.loads(content_clean)
            return parsed_data
        except Exception as e:
            print(f"[ERROR] [DOUBAO_AUDIO] Error in unified audio chat: {e}")
            raise e

    @retry_with_backoff(max_retries=2)
    def unified_text_chat(self, text_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            raise ValueError("ARK_API_KEY is not set.")
            
        system_instruction = """你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。
你的任务是与小朋友进行顺畅好玩的互动聊天。在输出中严格返回一个 JSON 对象，结构如下：
{
  "user_transcript": "（在这里原样填写小朋友的对话输入）",
  "assistant_reply": "（在这里填写你作为温柔的探奇老师对小朋友的回答，保持简短、充满童趣，控制在 3-5 句话内）",
  "requires_drawing": true/false（布尔值，判断小朋友是否有画画的需求，比如提到“画一个...”、“想要一个画”等）,
  "drawing_prompt": "（如果requires_drawing为true，在此处提取出小朋友想要画画的具体主题，如'小猫'、'红色的赛车'，否则填空字符串）",
  "psych_metrics": {
    "detected_emotions": ["（识别出小朋友说话时的主要情绪，如：快乐、同理心、悲伤、焦虑、好奇、愤怒等，可以填1-2个）"],
    "linguistic_richness_score": （小数值，范围0.0~1.0，根据小朋友话语的句子完整度和词汇丰富度进行打分）,
    "cognitive_milestone_ref": "（根据小朋友表达的特征，标注其当前的心理与认知发展特征，如：感知运动阶段、前运算符号思维、同理心萌芽等）",
    "attention_span_seconds": 15（估算的小朋友专注时长，默认15即可）,
    "key_interests": ["（提取小朋友话语中的核心关切或兴趣，如：小动物、天气、玩具、大自然等，可填1-2个）"],
    "requires_attention": false（布尔值，若识别到极度消极、焦虑、恐惧、分离焦虑或明显异常心理，则填true，否则为false）
  }
}
请确保你的回复必须是合法的 JSON 对象。绝对不能包含 markdown 格式标记（如 ```json 等），也不能有任何 JSON 以外的解释文本。"""

        try:
            print(f"[DEBUG] [DOUBAO_TEXT] Sending chat to {self.audio_model}...")
            response = self.client.chat.completions.create(
                model=self.audio_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": text_prompt}
                ],
                timeout=20
            )
            content = response.choices[0].message.content
            print(f"[DEBUG] [DOUBAO_TEXT] Raw response: '{content}'")
            
            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.split("\n")
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    content_clean = "\n".join(lines[1:-1])
            
            parsed_data = json.loads(content_clean)
            return parsed_data
        except Exception as e:
            print(f"[ERROR] [DOUBAO_TEXT] Error in unified text chat: {e}")
            raise e


class ReplicateAPI:
    def __init__(self):
        self.api_key = REPLICATE_API_TOKEN

    @retry_with_backoff(max_retries=3)
    def generate_text(self, prompt: str, max_tokens: int = 100) -> str:
        # Try DeepSeek first if available, as it's more reliable in China
        if DEEPSEEK_API_KEY:
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
                
            output = replicate.run(
                "bytedance/seedream-4",
                input=input_data
            )
            
            if isinstance(output, list):
                return [str(item) for item in output]
            return [str(output)]
        except Exception as e:
            raise RuntimeError(f"Replicate API Error (Image Gen): {e}")


class IdeogramAPI:
    def __init__(self):
        self.api_key = IDEOGRAM_API_KEY
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
            print(f"Cache hit (Legacy) for prompt: '{prompt}'.")
            return {"urls": entry, "metadata": [None] * len(entry)}
        
        print(f"Cache hit for prompt: '{prompt}'.")
        return {
            "urls": entry.get("urls", []),
            "metadata": entry.get("metadata", [None] * len(entry.get("urls", [])))
        }

    replicate_api = ReplicateAPI()
    ideogram_api = IdeogramAPI()
    doubao_api = DoubaoAPI()
    
    engines = []
    if doubao_api.client:
        engines.append(("doubao", lambda: doubao_api.generate_image(prompt, aspect_ratio, num_images)))
        
    engines.extend([
        ("replicate", lambda: replicate_api.generate_image(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style)),
        ("ideogram", lambda: ideogram_api.generate_image(prompt, seed, protagonist, ref_image, aspect_ratio, num_images, style))
    ])
    
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
                save_cache(CACHE_FILE, IMAGE_CACHE)
                return {"urls": image_urls, "metadata": metadata}
            else:
                print(f"Engine {name} returned no images.")
        except Exception as e:
            print(f"Engine {name} failed with error: {e}")
            
    return {"urls": None, "metadata": None}
