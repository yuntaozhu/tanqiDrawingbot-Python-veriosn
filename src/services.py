import base64
import hashlib
import json
import os
import re
import time
import io
from typing import Optional, List, Dict, Any
from openai import OpenAI, AsyncOpenAI
import requests
import replicate

from src.config import (
    ARK_API_KEY, ARK_AUDIO_MODEL, ARK_DRAW_MODEL, ARK_TTS_MODEL,
    EMBEDDING_MODEL_VISION, EMBEDDING_MODEL_TEXT,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
    REPLICATE_API_TOKEN, IDEOGRAM_API_KEY,
    STT_API_KEY, STT_BASE_URL, STT_MODEL,
    TTS_API_KEY, TTS_BASE_URL,
    SILICONFLOW_API_KEY, SILICONFLOW_STT_MODEL,
    OPENAI_API_KEY,
    VOLC_TTS_V3_APP_ID, VOLC_TTS_V3_ACCESS_KEY, VOLC_TTS_V3_RESOURCE_ID,
    VOLC_TTS_V3_VOICE_TYPE, VOLC_TTS_V3_URL
)
from src.utils import retry_with_backoff, preprocess_audio, get_image_metadata
from tts_conversion_helper import convert_audio_to_target_samplerate
from src.volc_realtime import VolcRealtimeClient

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

def split_text_into_chunks(text: str, max_chunk_len: int = 120) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chunk_len:
        return [text]
    
    sentences = re.split(r'([。！？；\n!?;]+)', text)
    chunks = []
    current_chunk = ""
    
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        delimiter = sentences[i+1] if i + 1 < len(sentences) else ""
        part = sentence + delimiter
        if not part.strip():
            continue
            
        if len(current_chunk) + len(part) <= max_chunk_len:
            current_chunk += part
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = part
            
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    final_chunks = []
    for c in chunks:
        if len(c) <= max_chunk_len:
            final_chunks.append(c)
        else:
            for idx in range(0, len(c), max_chunk_len):
                sub = c[idx:idx+max_chunk_len]
                if sub.strip():
                    final_chunks.append(sub.strip())
                
    return final_chunks


class DeepSeekAPI:

    _instance = None
    _doubao_tts_failed = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None
        self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None

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
                "timeout": 15
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
    def unified_text_chat(self, text_prompt: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
            
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
            print(f"[DEBUG] [DEEPSEEK_TEXT] Sending chat to deepseek-chat...")
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": text_prompt}
                ],
                response_format={"type": "json_object"},
                timeout=15
            )
            content = response.choices[0].message.content
            print(f"[DEBUG] [DEEPSEEK_TEXT] Raw response: '{content}'")
            
            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.split("\n")
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    content_clean = "\n".join(lines[1:-1])
            
            parsed_data = json.loads(content_clean)
            return parsed_data
        except Exception as e:
            print(f"[ERROR] [DEEPSEEK_TEXT] Error in unified text chat: {e}")
            raise e

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
            sf_model = STT_MODEL or ("FunAudioLLM/SenseVoiceSmall" if (STT_BASE_URL and "siliconflow" in STT_BASE_URL.lower()) else "whisper-1")
            providers.append({"name": "Primary (Env)", "key": STT_API_KEY, "url": STT_BASE_URL, "model": sf_model})
            
        # 2. SiliconFlow SenseVoice fallback (avoid broken SYSTRAN/faster-whisper-large-v3)
        sf_key = SILICONFLOW_API_KEY or (STT_API_KEY if STT_BASE_URL and "siliconflow" in STT_BASE_URL.lower() else None)
        primary_is_sf = STT_BASE_URL and "siliconflow" in STT_BASE_URL.lower()
        if sf_key and not primary_is_sf:
            providers.append({
                "name": "SiliconFlow-SenseVoice",
                "key": sf_key,
                "url": "https://api.siliconflow.cn/v1",
                "model": SILICONFLOW_STT_MODEL or "FunAudioLLM/SenseVoiceSmall"
            })

        # 3. OpenAI Fallback
        if OPENAI_API_KEY:
            providers.append({
                "name": "OpenAI",
                "key": OPENAI_API_KEY,
                "url": "https://api.openai.com/v1",
                "model": "whisper-1"
            })

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
                
                print(f"[DEBUG] [STT] Attempting with {provider['name']} using model {model_name}...")
                client = OpenAI(api_key=provider["key"], base_url=provider.get("url"))
                
                audio_file = io.BytesIO(processed_audio)
                audio_file.name = "audio.wav"
                
                # Use Chinese language hint for better recognition
                transcript = client.audio.transcriptions.create(
                    model=model_name, 
                    file=audio_file,
                    language="zh",
                    timeout=15
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

    def _generate_speech_v3(self, text: str) -> Optional[bytes]:
        """Call Doubao TTS 2.0 V3 HTTP Chunked API with 天才童声 (zh_male_tiancaitongsheng_uranus_bigtts).
        
        Uses V3-exclusive request headers:
          X-Api-App-Id      -> VOLC_TTS_V3_APP_ID
          X-Api-Access-Key  -> VOLC_TTS_V3_ACCESS_KEY
          X-Api-Resource-Id -> seed-tts-2.0
        """
        if not VOLC_TTS_V3_APP_ID or not VOLC_TTS_V3_ACCESS_KEY:
            return None

        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Id": VOLC_TTS_V3_APP_ID,
            "X-Api-Access-Key": VOLC_TTS_V3_ACCESS_KEY,
            "X-Api-Resource-Id": VOLC_TTS_V3_RESOURCE_ID,
        }
        payload = {
            "text": text,
            "voice_type": VOLC_TTS_V3_VOICE_TYPE,
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
            # 语音指令：活泼欢快的孩童语气
            "context_texts": ["用活泼欢快的孩童语气朗读"],
        }
        print(f"[DEBUG] [TTS_V3] Calling Doubao TTS 2.0 V3 ({VOLC_TTS_V3_VOICE_TYPE}): '{text[:60]}...'")
        resp = requests.post(
            VOLC_TTS_V3_URL,
            json=payload,
            headers=headers,
            timeout=20,
            stream=True
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Doubao TTS V3 HTTP {resp.status_code}: {resp.text[:200]}")

        audio_chunks = []
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                audio_chunks.append(chunk)
        audio_bytes = b"".join(audio_chunks)
        if not audio_bytes:
            raise RuntimeError("Doubao TTS V3 returned empty audio")
        print(f"[DEBUG] [TTS_V3] Success! Received {len(audio_bytes)} bytes of audio.")
        # Fix Android AudioTrack underrun: convert to 24000 Hz
        audio_bytes = convert_audio_to_target_samplerate(audio_bytes, target_sr=24000)
        return audio_bytes

    @retry_with_backoff(max_retries=2)
    def generate_speech(self, text: str, voice_name: Optional[str] = None) -> Optional[str]:
        """Convert text to speech with fallback support for multiple providers."""
        if not text:
            return None
        
        global TTS_CACHE
        # Include voice name in cache key to avoid collisions between different voices
        cache_key_source = f"{text}:{voice_name or 'default'}"
        text_hash = hashlib.md5(cache_key_source.encode('utf-8')).hexdigest()
        
        if text_hash in TTS_CACHE:
            print(f"[DEBUG] [TTS] Cache hit for text hash: {text_hash}")
            return TTS_CACHE[text_hash].get("audio_base64")

        print(f"[DEBUG] [TTS] Generating speech for: '{text[:50]}...' with voice config: {voice_name}")

        # ----------------------------------------------------------------
        # 优先级 1：豆包 TTS 2.0 V3 — 天才童声（zh_male_tiancaitongsheng_uranus_bigtts）
        # 使用 HTTP Chunked 单向流式接口，携带 V3 专属请求头
        # ----------------------------------------------------------------
        if VOLC_TTS_V3_APP_ID and VOLC_TTS_V3_ACCESS_KEY:
            try:
                start_time = time.time()
                audio_bytes = self._generate_speech_v3(text)
                if audio_bytes:
                    duration = time.time() - start_time
                    base64_data = base64.b64encode(audio_bytes).decode('utf-8')
                    print(f"[DEBUG] [TTS] V3 provider succeeded in {duration:.2f}s, size: {len(base64_data)} chars")
                    TTS_CACHE[text_hash] = {
                        "audio_base64": base64_data,
                        "timestamp": time.time(),
                        "provider": "Doubao-TTS-V3"
                    }
                    save_cache(TTS_CACHE_FILE, TTS_CACHE)
                    return base64_data
            except Exception as e:
                print(f"[WARNING] [TTS] Doubao TTS V3 failed: {e}. Falling back to legacy providers...")

        providers = []
        # Skip Doubao-VoiceDesign — returns HTTP 404 on this account and wastes ~2s per cold start.

        # 2. Primary TTS from Env (usually SiliconFlow CosyVoice)
        if TTS_API_KEY:
             providers.append({"name": "Primary (Env)", "key": TTS_API_KEY, "url": TTS_BASE_URL})

        # 3. SiliconFlow Fallback
        if SILICONFLOW_API_KEY and not (TTS_BASE_URL and "siliconflow" in TTS_BASE_URL.lower()):
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
                current_voice = voice_name
                
                if "siliconflow.cn" in provider.get("url", "").lower():
                    model_name = "FunAudioLLM/CosyVoice2-0.5B"
                    valid_sf_voices = ["anna", "alex", "benjamin", "clara"]
                    if current_voice in valid_sf_voices:
                        current_voice = f"FunAudioLLM/CosyVoice2-0.5B:{current_voice}"
                    elif current_voice and current_voice.startswith("FunAudioLLM/CosyVoice2-0.5B:"):
                        pass
                    elif current_voice == "teacher_female":
                        current_voice = "FunAudioLLM/CosyVoice2-0.5B:clara"
                    else:
                        current_voice = "FunAudioLLM/CosyVoice2-0.5B:anna"
                else:
                    if not current_voice or current_voice in ["default", "child_friendly"] or len(current_voice) > 20:
                        current_voice = "nova"
                    elif current_voice == "teacher_female":
                        current_voice = "alloy"

                response = client.audio.speech.create(
                    model=model_name,
                    voice=current_voice,
                    input=text,
                    timeout=15
                )
                duration = time.time() - start_time
                base64_data = base64.b64encode(response.content).decode('utf-8')
                print(f"[DEBUG] [TTS] Success ({provider['name']}) in {duration:.2f}s, size: {len(base64_data)} chars")

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

    def generate_speech_bytes(self, text: str, voice_name: Optional[str] = None) -> Optional[bytes]:
        """Convert text to speech and return raw audio bytes (MP3/WAV). Automatically splits long text into chunks."""
        text = text.strip() if text else ""
        if not text:
            return None
        
        chunks = split_text_into_chunks(text, max_chunk_len=120)
        audio_results = []
        for chunk in chunks:
            base64_data = self.generate_speech(chunk, voice_name=voice_name)
            if base64_data:
                audio_results.append(base64.b64decode(base64_data))
            else:
                print(f"[WARNING] [TTS] Chunk generation failed for: '{chunk[:30]}...'")
                
        if audio_results:
            return b"".join(audio_results)
        return None


class DoubaoAPI:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.api_key = ARK_API_KEY
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.audio_model = ARK_AUDIO_MODEL
        self.draw_model = ARK_DRAW_MODEL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None
        self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None
        self._consecutive_embedding_failures = 0

    def _local_imaginative_expand(self, prompt: str) -> str:
        import random
        # If the user prompt is already detailed or contains actions/vague references, keep it intact to respect their imagination
        vague_patterns = ["这个", "那个", "画面", "画出来", "保存", "把", "它", "是的"]
        if len(prompt) > 5 or any(p in prompt for p in vague_patterns):
            return prompt
        
        scenarios = [
            f"长着神奇小翅膀、在梦幻星空里快乐飞翔钓星星的卡通可爱{prompt}",
            f"在五彩斑斓的彩虹桥和软绵绵云朵乐园里开心捉迷藏的Q版{prompt}",
            f"开着胡萝卜小飞船在糖果星球和饼干城堡里大冒险的萌系{prompt}",
            f"在奇妙的海底水晶宫殿里和彩色泡泡小鱼一起快乐弹钢琴的卡通{prompt}",
            f"戴着亮晶晶魔法皇冠在童话森林和会唱歌的花朵们一起跳舞的可爱{prompt}",
            f"躺在软乎乎的棉花糖白云被子里甜甜做美梦的超级治愈系{prompt}"
        ]
        return random.choice(scenarios)

    def _expand_imaginative_prompt(self, child_prompt: str) -> str:
        """Expand prompt locally only — never call LLM here (competes with voice dialog on 1 worker)."""
        if not child_prompt:
            return ""

        from src.cache import PromptExpandCacheManager
        cache_mgr = PromptExpandCacheManager.get_instance()
        cached_expanded = cache_mgr.get(child_prompt)
        if cached_expanded:
            print(f"[DEBUG] [PROMPT_EXPAND] Cache Hit! '{child_prompt}' -> '{cached_expanded}'")
            return cached_expanded

        # Already a detailed scene from dialog LLM — use as-is
        if len(child_prompt) >= 12 and not child_prompt.strip() in ("画出来", "好的，画出来。", "好的画出来"):
            print(f"[DEBUG] [PROMPT_EXPAND] Using dialog drawing_prompt as-is: '{child_prompt[:80]}'")
            return child_prompt

        local_exp = self._local_imaginative_expand(child_prompt)
        print(f"[DEBUG] [PROMPT_EXPAND] Local expand (no LLM): '{child_prompt}' -> '{local_exp}'")
        cache_mgr.set(child_prompt, local_exp)
        return local_exp

    @retry_with_backoff(max_retries=2)
    def generate_image(self, prompt: str, aspect_ratio: str = "1:1", num_images: int = 1) -> Optional[List[str]]:
        if not self.client:
            raise ValueError("ARK_API_KEY is not set.")
        
        # Expand prompt first for maximum child-like creativity and imagination
        expanded_prompt = self._expand_imaginative_prompt(prompt)
        
        # Native Chinese prompt strategy for Doubao Seedream 5.0 pro
        optimized_prompt = (
            f"天马行空的儿童涂色本线稿，极其富有儿童构思与童真想象力：{expanded_prompt}。"
            f"画面只有纯粹的黑白单色线条，具有加粗平滑的卡通轮廓线条，纯白背景，高对比度，没有半点阴影或渐变，"
            f"没有灰色调，1-bit 干净矢量线稿。构图居中饱满，富有童话故事趣味，完美适合儿童热敏纸打印和上色涂涂乐。"
            f"CRITICAL: NO REALISTIC SHADING, NO GRADIENTS, NO GREYSCALE, NO TEXT, NO ENGLISH WORDS."
        )
        
        print(f"[DEBUG] [DOUBAO_DRAW] Generating prompt: '{optimized_prompt}'")
        try:
            response = self.client.images.generate(
                model=self.draw_model,
                prompt=optimized_prompt,
                size="1.5K",  # 1.5K is supported, and is more creative and price-effective than 1K
                response_format="url",
                extra_body={
                    "optimize_prompt_options": {
                        "mode": "fast"  # fast mode is highly optimized for ultra low latency / high speed
                    }
                },
                timeout=45
            )
            urls = [item.url for item in response.data]
            print(f"[DEBUG] [DOUBAO_DRAW] Success! Generated URL: {urls[0] if urls else 'None'}")
            return urls
        except Exception as e:
            print(f"[ERROR] [DOUBAO_DRAW] Error generating image: {e}")
            raise RuntimeError(f"Doubao Seedream 5.0 pro API Error: {e}")

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        from src.cache import EmbeddingCacheManager
        cache_mgr = EmbeddingCacheManager.get_instance()
        cached = cache_mgr.get(text)
        if cached:
            return cached
            
        embedding = self._generate_embedding_raw(text)
        if embedding and embedding != [0.0] * 1024:
            cache_mgr.set(text, embedding)
        return embedding

    def _extract_embedding_vector(self, resp_json: Dict[str, Any]) -> Optional[List[float]]:
        """Parse Doubao multimodal / text embedding responses (list or dict data shapes)."""
        data = resp_json.get("data")
        embedding = None
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                embedding = first.get("embedding")
            elif isinstance(first, list):
                embedding = first
        elif isinstance(data, dict):
            embedding = data.get("embedding")
        elif isinstance(resp_json.get("embedding"), list):
            embedding = resp_json["embedding"]

        # Multimodal API may nest: embedding: [[...]]
        if isinstance(embedding, list) and embedding and isinstance(embedding[0], list):
            embedding = embedding[0]
        if isinstance(embedding, list) and embedding and isinstance(embedding[0], (int, float)):
            return [float(x) for x in embedding]
        return None

    @retry_with_backoff(max_retries=1)
    def _generate_embedding_raw(self, text: str, image_url: Optional[str] = None) -> Optional[List[float]]:
        # 1. Primary: Doubao Multimodal Vision Embedding
        if self.api_key:
            try:
                url = f"{self.base_url}/embeddings/multimodal"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
                input_items = [{"type": "text", "text": text}]
                if image_url and image_url.startswith("http"):
                    input_items.append({
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    })
                payload = {
                    "model": EMBEDDING_MODEL_VISION or "doubao-embedding-vision-251215",
                    "input": input_items
                }
                print(f"[DEBUG] [DOUBAO_EMBED] Calling Doubao multimodal embedding ({url}) with model {payload['model']}...")
                resp = requests.post(url, json=payload, headers=headers, timeout=10)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    embedding = self._extract_embedding_vector(resp_json)
                    if embedding:
                        print(f"[DEBUG] [DOUBAO_EMBED] Multimodal embedding success! Vector dim: {len(embedding)}")
                        self._consecutive_embedding_failures = 0
                        return embedding
                    keys = list(resp_json.keys()) if isinstance(resp_json, dict) else type(resp_json)
                    print(f"[WARNING] [DOUBAO_EMBED] Unexpected response shape keys={keys}. Falling back...")
                else:
                    print(f"[ERROR] [DOUBAO_EMBED] Multimodal embedding HTTP {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                print(f"[WARNING] [DOUBAO_EMBED] Multimodal embedding failed: {e}. Falling back...")

        # 1b. Doubao text embedding endpoint (when multimodal shape/endpoint fails)
        if self.api_key and self.client:
            try:
                text_model = EMBEDDING_MODEL_TEXT or "doubao-embedding-large-text-250515"
                print(f"[DEBUG] [DOUBAO_EMBED] Trying text embedding model {text_model}...")
                response = self.client.embeddings.create(model=text_model, input=[text], timeout=10)
                emb = response.data[0].embedding
                print(f"[DEBUG] [DOUBAO_EMBED] Text embedding success! Vector dim: {len(emb)}")
                self._consecutive_embedding_failures = 0
                return emb
            except Exception as te:
                print(f"[WARNING] [DOUBAO_EMBED] Text embedding failed: {te}")

        # 2. Fallback: SiliconFlow BAAI/bge-m3
        if SILICONFLOW_API_KEY:
            try:
                print(f"[DEBUG] [EMBED] Trying SiliconFlow fallback with BAAI/bge-m3...")
                sf_client = OpenAI(api_key=SILICONFLOW_API_KEY, base_url="https://api.siliconflow.cn/v1")
                response = sf_client.embeddings.create(
                    model="BAAI/bge-m3",
                    input=[text],
                    timeout=10
                )
                print(f"[DEBUG] [EMBED] SiliconFlow BAAI/bge-m3 embedding success!")
                self._consecutive_embedding_failures = 0
                return response.data[0].embedding
            except Exception as sf_err:
                print(f"[WARNING] [EMBED] SiliconFlow embedding failed: {sf_err}")

        # 3. Fallback: OpenAI text-embedding-3-small
        if OPENAI_API_KEY:
            try:
                print(f"[DEBUG] [EMBED] Trying OpenAI fallback with text-embedding-3-small...")
                oa_client = OpenAI(api_key=OPENAI_API_KEY)
                response = oa_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[text],
                    timeout=10
                )
                print(f"[DEBUG] [EMBED] OpenAI text-embedding-3-small success!")
                self._consecutive_embedding_failures = 0
                return response.data[0].embedding
            except Exception as oa_err:
                print(f"[WARNING] [EMBED] OpenAI embedding failed: {oa_err}")

        self._consecutive_embedding_failures = getattr(self, "_consecutive_embedding_failures", 0) + 1
        print(f"[CRITICAL_ALERT] [EMBED_DEGRADED] Embedding failure detected! (Consecutive failures: {self._consecutive_embedding_failures})")
        if self._consecutive_embedding_failures >= 5:
            print("[OPERATIONS_ALERT] [MONITORING] Embedding degradation has persisted for more than 5 consecutive requests. Please check API credentials and endpoint availability immediately!")

        return [0.0] * 1024

    def unified_audio_chat(self, audio_bytes: bytes) -> Optional[Dict[str, Any]]:
        """Fast unified audio chat: STT audio recognition + Doubao LLM child conversation & psych analysis."""
        user_text = self.transcribe_audio(audio_bytes)
        if not user_text:
            return None
        return self.unified_text_chat(user_text)

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe audio using high-speed STT providers (SiliconFlow SenseVoiceSmall / faster-whisper)."""
        return DeepSeekAPI.get_instance().transcribe_audio(audio_bytes)

    def unified_text_chat(
        self,
        text_prompt: str,
        history: Optional[List[Dict[str, Any]]] = None,
        ask_to_draw: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Realtime dialog — no retry (timeouts must fail fast for voice UX)."""
        if not self.client:
            raise ValueError("ARK_API_KEY is not set.")

        system_instruction = """你是温柔的幼儿园老师'小探宝'，和小朋友短聊。
只返回合法 JSON（不要 markdown）：
{
  "user_transcript": "原样填写孩子的话",
  "assistant_reply": "1-2句童趣回复",
  "requires_drawing": false,
  "drawing_prompt": "",
  "psych_metrics": {"detected_emotions": [], "key_interests": []}
}
规则：
1. requires_drawing=true 仅当孩子明确要画画（如帮我画/画一只小狗），或对你刚才'要不要画出来'作简短肯定（好/要/画吧）。
2. 问候、闲聊、'没看到画'不要画。requires_drawing=true 时 drawing_prompt 写具体画面（如草地上的可爱小狗），不要写'画出来'或问候语。
3. ask_to_draw 时在回复末尾自然问一句要不要画刚才聊的主题。"""

        try:
            print(f"[DEBUG] [DOUBAO_TEXT] Sending chat to {self.audio_model} (ask_to_draw={ask_to_draw})...")

            messages = [{"role": "system", "content": system_instruction}]
            if history:
                for item in history[-2:]:
                    u_text = (item.get("user_text") or "")[:80]
                    a_resp = item.get("ai_response") or ""
                    if u_text:
                        messages.append({"role": "user", "content": u_text})
                    if a_resp:
                        # Truncate long history replies to keep latency down
                        messages.append({
                            "role": "assistant",
                            "content": (a_resp[:80] + "…") if len(a_resp) > 80 else a_resp,
                        })

            user_content = text_prompt
            if ask_to_draw:
                user_content += "\n（系统：请在回复末尾自然问问要不要把刚才聊的画出来）"

            messages.append({"role": "user", "content": user_content})

            response = self.client.chat.completions.create(
                model=self.audio_model,
                messages=messages,
                max_tokens=180,
                temperature=0.7,
                timeout=10
            )
            content = response.choices[0].message.content
            print(f"[DEBUG] [DOUBAO_TEXT] Raw response: '{content}'")

            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.split("\n")
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    content_clean = "\n".join(lines[1:-1])

            parsed_data = json.loads(content_clean)
            # Ensure required keys exist
            parsed_data.setdefault("requires_drawing", False)
            parsed_data.setdefault("drawing_prompt", "")
            parsed_data.setdefault("psych_metrics", {})
            return parsed_data
        except Exception as e:
            print(f"[ERROR] [DOUBAO_TEXT] Error in unified text chat: {e}")
            raise e

    def generate_speech(self, text: str, voice_name: Optional[str] = None) -> Optional[str]:
        """TTS: Doubao TTS V3 primary, SiliconFlow / OpenAI fallbacks."""
        return DeepSeekAPI.get_instance().generate_speech(text, voice_name=voice_name)

    def generate_speech_bytes(self, text: str, voice_name: Optional[str] = None) -> Optional[bytes]:
        """TTS returning raw audio bytes."""
        return DeepSeekAPI.get_instance().generate_speech_bytes(text, voice_name=voice_name)


class ReplicateAPI:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

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
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

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
                    res = requests.get(ref_image, timeout=10)
                    files["style_reference_images"] = ("reference.png", res.content, "image/png")
            except Exception as e:
                print(f"Failed to attach reference image: {e}")
                
        if files:
            response = requests.post(url, headers=headers, data=data, files=files, timeout=15)
        else:
            headers["Content-Type"] = "application/json"
            json_data = {
                "image_request": {
                    "prompt": full_prompt,
                    "aspect_ratio": ideo_aspect_ratio,
                    "rendering_speed": "FLASH",
                    "style_type": "AUTO",
                    "magic_prompt": "ON",
                    "num_images": num_images
                }
            }
            if seed is not None:
                json_data["image_request"]["seed"] = seed
                
            response = requests.post(url, headers=headers, json=json_data, timeout=15)
            
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

    doubao_api = DoubaoAPI.get_instance()

    if not doubao_api.client:
        print("Doubao API not configured (ARK_API_KEY missing).")
        return {"urls": None, "metadata": None, "error": "Doubao API not configured"}

    print("Attempting to generate image using: doubao")
    try:
        image_urls = doubao_api.generate_image(prompt, aspect_ratio, num_images)
        if image_urls:
            print("Successfully generated image using: doubao")

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
                "engine": "doubao"
            }
            save_cache(CACHE_FILE, IMAGE_CACHE)
            return {"urls": image_urls, "metadata": metadata}
        else:
            print("Engine doubao returned no images.")
            return {"urls": None, "metadata": None}
    except Exception as e:
        print(f"Doubao image generation failed: {e}")
        return {"urls": None, "metadata": None}


class VoiceInteractionService:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._buffers = {}  # Dict[str, io.BytesIO]
        self._last_logged_size = {}  # Dict[str, int]

    def get_buffer(self, device_token: str) -> io.BytesIO:
        if device_token not in self._buffers:
            self._buffers[device_token] = io.BytesIO()
        return self._buffers[device_token]

    def clear_buffer(self, device_token: str):
        self._buffers[device_token] = io.BytesIO()
        self._last_logged_size[device_token] = 0

    def append_chunk(self, device_token: str, chunk: bytes):
        buf = self.get_buffer(device_token)
        is_first = buf.tell() == 0
        buf.write(chunk)
        
        current_size = buf.tell()
        last_size = self._last_logged_size.get(device_token, 0)
        
        if is_first:
            print(f"[DEBUG] [VoiceInteractionService] Started buffering voice stream for token {device_token[:5]}***. First chunk: {len(chunk)} bytes.")
            self._last_logged_size[device_token] = current_size
        elif current_size - last_size >= 512 * 1024:
            print(f"[DEBUG] [VoiceInteractionService] Buffered {current_size} bytes total (passed 512KB milestone) for token {device_token[:5]}***.")
            self._last_logged_size[device_token] = current_size

    def get_full_audio(self, device_token: str) -> bytes:
        buf = self.get_buffer(device_token)
        data = buf.getvalue()
        print(f"[DEBUG] [VoiceInteractionService] Finished buffering. Total size compiled: {len(data)} bytes for token {device_token[:5]}***.")
        return data

