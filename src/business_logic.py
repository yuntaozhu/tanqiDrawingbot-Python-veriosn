import time
import uuid
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
import numpy as np

from src.config import DEEPSEEK_API_KEY, ADMIN_KEY
from src.cache import DrawingCacheManager
from src.crud import (
    save_history_to_db, save_print_job_to_db, save_psych_vector, 
    query_psych_vectors, get_device_settings
)
from src.utils import (
    process_line_art_image, get_raw_bitmap_hex, get_embedded_bitmap, get_image_metadata
)
from src.services import (
    DeepSeekAPI, DoubaoAPI, ReplicateAPI, generate_image_with_fallback,
    VoiceInteractionService
)

def similarity_search_vectors(device_token: str, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    all_entries = query_psych_vectors(device_token)
    if not all_entries or not query_embedding:
        return []
        
    query_vec = np.array(query_embedding)
    query_norm = np.linalg.norm(query_vec)
    if query_norm < 1e-10:
        return []
        
    scored_entries = []
    for entry in all_entries:
        entry_embedding = entry.get("embedding")
        if not entry_embedding or len(entry_embedding) != len(query_embedding):
            continue
        entry_vec = np.array(entry_embedding)
        entry_norm = np.linalg.norm(entry_vec)
        if entry_norm < 1e-10:
            continue
            
        similarity = np.dot(query_vec, entry_vec) / (query_norm * entry_norm)
        scored_entries.append((similarity, entry))
        
    scored_entries.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored_entries[:top_k]]


def generate_growths_summary(device_token: str) -> Dict[str, Any]:
    vectors = query_psych_vectors(device_token)
    if not vectors:
        return {
            "summary": "暂无足够数据，快让小朋友和小探宝开始聊天吧！",
            "emotions": [],
            "interests": [],
            "linguistic_score_avg": 0,
            "requires_attention_count": 0,
            "linguistic_trend": [],
            "drawings": [],
            "total_interactions": 0
        }
        
    emotions = {}
    interests = {}
    total_ling = 0.0
    attention_count = 0
    drawings = []
    text_logs = []
    
    vectors_chrono = sorted(vectors, key=lambda x: x["timestamp"])
    linguistic_trend = []
    
    for v in vectors_chrono:
        metadata = v.get("metadata", {})
        pm = metadata.get("psych_metrics", {})
        
        for e in pm.get("detected_emotions", []):
            emotions[e] = emotions.get(e, 0) + 1
            
        for i in pm.get("key_interests", []):
            interests[i] = interests.get(i, 0) + 1
            
        ling_score = pm.get("linguistic_richness_score", 0.5)
        total_ling += ling_score
        
        date_str = time.strftime("%m/%d %H:%M", time.localtime(v["timestamp"]))
        linguistic_trend.append({"time": date_str, "score": int(ling_score * 100)})
        
        if metadata.get("drawing_url"):
            drawings.append({
                "prompt": metadata.get("drawing_prompt", v["child_text"]),
                "url": metadata.get("drawing_url"),
                "timestamp": v["timestamp"]
            })
            
        if pm.get("requires_attention", False):
            attention_count += 1
            
        text_logs.append(f"儿童: {v['child_text']}\n小探宝: {v['ai_response']}\n[情绪: {', '.join(pm.get('detected_emotions', []))}]")

    avg_ling = total_ling / len(vectors) if vectors else 0.0
    
    deepseek = DeepSeekAPI()
    doubao = DoubaoAPI()
    
    logs_joined = "\n---\n".join(text_logs[:15])
    analysis_prompt = f"""
    请根据以下小朋友与智能陪伴玩偶“小探宝”的聊天及绘画记录，撰写一份专业的“儿童成长与行为心理分析报告”。
    记录条数：{len(vectors)}
    聊天记录摘录：
    {logs_joined}
    
    报告要求：
    1. 语气必须专业、温和、充满关怀。
    2. 包含三个部分：
       - 儿童心理与情绪分析（分析小朋友当下的心理底色、性格倾向，如是否有焦虑、充满安全感等）
       - 语言与认知能力发展评估（根据其表达能力、逻辑性，判断其当前的成长里程碑）
       - 启发式家园共育具体指导意见（提供3条切实可行的家庭互动 and 引导建议）
    3. 语言为中文。
    """
    
    summary_text = ""
    try:
        if doubao.client:
            res = doubao.client.chat.completions.create(
                model=doubao.audio_model,
                messages=[
                    {"role": "system", "content": "你是一位拥有儿童心理学硕士及十年幼教经验的儿童行为发展评估专家。"},
                    {"role": "user", "content": analysis_prompt}
                ],
                timeout=20
            )
            summary_text = res.choices[0].message.content
        else:
            raise ValueError()
    except Exception:
        try:
            res = deepseek.generate_text(analysis_prompt, system_instruction="你是一位拥有儿童心理学及十年幼教经验的行为发展评估专家。")
            summary_text = res.get("text", "")
        except Exception as e:
            summary_text = f"分析报告生成失败，请稍后重试。错误信息: {e}"
            
    sorted_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)
    sorted_interests = sorted(interests.items(), key=lambda x: x[1], reverse=True)
    
    return {
        "summary": summary_text,
        "emotions": sorted_emotions[:5],
        "interests": sorted_interests[:6],
        "linguistic_score_avg": int(avg_ling * 100),
        "requires_attention_count": attention_count,
        "linguistic_trend": linguistic_trend[-10:],
        "drawings": drawings[:12],
        "total_interactions": len(vectors)
    }


def parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower().strip() in ("true", "1", "yes", "y", "requires_drawing", "requires_painting")
    if isinstance(val, (int, float)):
        return bool(val)
    return False


def check_assistant_drawing_trigger(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    
    # 1. Direct explicit drawing initiation phrases
    direct_triggers = [
        "我们一起来画", "我为你画", "我画了", "为你画了", "开始画", 
        "画一个", "画个", "画一只", "画一幅", "画画", "画张", "画条",
        "这就画", "这就给你画", "画给你", "正在画", "准备画", "开始为你画",
        "画好啦", "画好哈", "画好喽", "画了编", "画好了", "画出来", "把...画", "给你画", "帮宝贝画"
    ]
    if any(trig in text_lower for trig in direct_triggers):
        return True
        
    # 2. Semantic action cues when "画" is mentioned
    if "画" in text_lower:
        # If it's a question asking the child what/how to draw, don't trigger.
        is_question = any(q in text_lower for q in [
            "你想画", "你要画", "你想画个", "画什么", "画哪个", "画几", 
            "要不要画", "想不想画", "会画什么", "喜欢画"
        ])
        if not is_question:
            # Declarations/promises to draw
            declarations = [
                "变成", "变出", "变一幅", "变一个", "变一只",
                "我这就", "老师这就", "我来给", "我为你", "帮宝贝", "帮你想", 
                "这就画", "我画了", "开始画", "准备画", "正在画", "画好啦", "画好了", 
                "马上把", "马上画", "马上为", "马上给", "马上", "现在就", "等下就能看到", 
                "等一下就能看到", "把这个", "魔法", "呈现"
            ]
            if any(dec in text_lower for dec in declarations):
                return True
                
    return False


def extract_drawing_subject(text: str) -> str:
    if not text:
        return ""
    # Remove common prefixes
    prefixes = [
        "我想画一个", "我想画一幅", "我想画一只", "我想画一条", "我想画一张", "我想画个", "我想画只", "我想画张", "我想画条", "我想画些", "我想画", 
        "帮我画一个", "帮我画一幅", "帮我画一只", "帮我画一条", "帮我画一张", "帮我画个", "帮 me 画只", "帮我画条", "帮我画",
        "可以画一个", "可以画一幅", "可以画一只", "可以画一条", "可以画一张", "可以画个", "可以画",
        "画一个", "画一幅", "画一只", "画一条", "画一张", "画只", "画张", "画条", "画画", "画个", "画出", "画一画", "画",
        "我想要画一个", "我想要画一只", "我想要画条", "我想要画", "想要画一个", "想要画", "我要画一个", "我要画",
        "是一个", "是一幅", "是一只", "是一条", "是一张", "是个", "是只", "是条", "是张", "我的是", "是"
    ]
    subject = text.strip()
    for p in prefixes:
        if subject.startswith(p):
            subject = subject[len(p):]
            break
    # Remove common suffixes/punctuation recursively
    subject = subject.strip("。，！？.!? ")
    while True:
        changed = False
        for suffix in ["吧", "呀", "呗", "呢", "吗", "哈", "啦", "了", "的", "不"]:
            if subject.endswith(suffix):
                subject = subject[:-len(suffix)].strip()
                changed = True
        if not changed:
            break
    return subject.strip()


def extract_drawing_subject_advanced(user_text: str, assistant_reply: str) -> str:
    # 1. Try to extract from user_text using prefixes
    subject = extract_drawing_subject(user_text)
    if subject and len(subject) > 0 and subject not in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
        return subject
        
    # 2. Try to extract from assistant_reply using regex patterns
    import re
    if assistant_reply:
        # Pattern 1: 你想画([^呀！，。？\s]+)[呀！，。？]
        m = re.search(r"你想画([^呀！，。？\s]+)", assistant_reply)
        if m:
            sub = extract_drawing_subject(m.group(1).strip())
            if sub and len(sub) > 0 and sub not in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
                return sub
        # Pattern 2: 我们一起来画([^吧！，。？\s]+)
        m = re.search(r"我们一起来画([^吧！，。？\s]+)", assistant_reply)
        if m:
            sub = extract_drawing_subject(m.group(1).strip())
            if sub and len(sub) > 0 and sub not in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
                return sub
        # Pattern 3: 画一个([^！，。？\s]+)
        m = re.search(r"画一个([^！，。？\s]+)", assistant_reply)
        if m:
            sub = extract_drawing_subject(m.group(1).strip())
            if sub and len(sub) > 0 and sub not in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
                return sub
        # Pattern 4: 画幅([^！，。？\s]+)
        m = re.search(r"画幅([^！，。？\s]+)", assistant_reply)
        if m:
            sub = extract_drawing_subject(m.group(1).strip())
            if sub and len(sub) > 0 and sub not in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
                return sub
        # Pattern 5: 画只([^！，。？\s]+)
        m = re.search(r"画只([^！，。？\s]+)", assistant_reply)
        if m:
            sub = extract_drawing_subject(m.group(1).strip())
            if sub and len(sub) > 0 and sub not in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
                return sub
                
    return subject


async def async_generate_drawing(subject: str, device_token: str = None) -> Optional[Dict[str, Any]]:
    """Generates drawing line art asynchronously in parallel with text generation, leveraging Redis/memory cache."""
    cache_mgr = DrawingCacheManager.get_instance()
    cached = cache_mgr.get(subject)
    if cached:
        print(f"[DEBUG] [ASYNC_DRAW] 0ms Cache Hit for prompt: '{subject}'")
        job_id = str(uuid.uuid4())
        action = {
            "type": "draw",
            "prompt": subject,
            "job_id": job_id,
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex")
        }
        save_print_job_to_db({
            "job_id": job_id,
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex"),
            "prompt": subject,
            "timestamp": time.time()
        })
        return action

    print(f"[DEBUG] [ASYNC_DRAW] Starting background image generation for prompt: '{subject}'...")
    start_time = time.time()

    def _generate_sync():
        try:
            doubao = DoubaoAPI.get_instance()
            if doubao.client:
                try:
                    urls = doubao.generate_image(subject)
                    if urls:
                        processed_image = process_line_art_image(urls[0])
                        bitmap_hex = get_raw_bitmap_hex(urls[0])
                        return processed_image, bitmap_hex, subject
                except Exception as e:
                    print(f"[WARNING] [ASYNC_DRAW] Doubao draw failed: {e}")

            result = generate_image_with_fallback(subject)
            urls = result.get("urls")
            if urls:
                processed_image = process_line_art_image(urls[0])
                bitmap_hex = get_raw_bitmap_hex(urls[0])
                return processed_image, bitmap_hex, subject
        except Exception as e:
            print(f"[ERROR] [ASYNC_DRAW] Image generation failed: {e}")
        return None, None, subject

    processed_image, bitmap_hex, prompt = await asyncio.to_thread(_generate_sync)

    if processed_image:
        job_id = str(uuid.uuid4())
        job_data = {
            "job_id": job_id,
            "image_url": processed_image,
            "bitmap_hex": bitmap_hex,
            "prompt": prompt,
            "timestamp": time.time()
        }
        save_print_job_to_db(job_data)

        action = {
            "type": "draw",
            "prompt": prompt,
            "job_id": job_id,
            "image_url": processed_image,
            "bitmap_hex": bitmap_hex
        }

        # Cache asset for instant future requests
        cache_mgr.set(prompt, action)

        duration = time.time() - start_time
        print(f"[DEBUG] [ASYNC_DRAW] Image generated and cached in {duration:.2f}s, job_id: {job_id}")
        return action

    return None


async def stream_chat_llm(user_text: str):
    """Streams chat tokens from Doubao or fallback provider."""
    doubao = DoubaoAPI.get_instance()
    deepseek = DeepSeekAPI.get_instance()
    system_instruction = "你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。请与小朋友进行顺畅好玩的互动聊天，保持简短、充满童趣，控制在 3-5 句话内。"

    if doubao.client:
        try:
            print(f"[DEBUG] [STREAM_LLM] Attempting stream with Doubao: '{user_text}'")
            stream = doubao.client.chat.completions.create(
                model=doubao.audio_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_text}
                ],
                stream=True,
                timeout=30
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    await asyncio.sleep(0.005)
            return
        except Exception as e:
            print(f"[ERROR] [STREAM_LLM] Doubao stream error: {e}, falling back to DeepSeek...")

    if deepseek.client:
        try:
            print(f"[DEBUG] [STREAM_LLM] Attempting stream with DeepSeek: '{user_text}'")
            stream = deepseek.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_text}
                ],
                stream=True,
                timeout=30
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    await asyncio.sleep(0.005)
            return
        except Exception as e:
            print(f"[ERROR] [STREAM_LLM] DeepSeek stream error: {e}")

    fallback_text = "宝贝你好呀！我是小探宝，今天你想和我聊什么呢？"
    for char in fallback_text:
        yield char
        await asyncio.sleep(0.02)


async def process_llm_interaction(prompt_input: Any, api_key: str, device_token: str = None) -> Dict[str, Any]:
    start_time = time.time()
    device_token = device_token or "anonymous_device"
    doubao = DoubaoAPI.get_instance()
    deepseek = DeepSeekAPI.get_instance()
    
    # Check if Doubao client is configured
    if doubao.client:
        try:
            print(f"[DEBUG] [CORE] Attempting Doubao unified pipeline for token: {device_token}...")
            if isinstance(prompt_input, bytes):
                # High-speed modular pipeline: Transcribe via SiliconFlow first, then send to text model
                print(f"[DEBUG] [FAST_PATH] Transcribing audio with fast STT first...")
                stt_start = time.time()
                user_text = deepseek.transcribe_audio(prompt_input)
                print(f"[DEBUG] [FAST_PATH] STT took {time.time() - stt_start:.2f}s. Result: '{user_text}'")
                
                if not user_text:
                    res_data = {
                        "user_transcript": "",
                        "assistant_reply": "对不起宝贝，我没听清，能不能请你再说一遍呀？",
                        "requires_drawing": False,
                        "drawing_prompt": "",
                        "psych_metrics": {
                            "detected_emotions": ["困惑"],
                            "linguistic_richness_score": 0.0,
                            "cognitive_milestone_ref": "无",
                            "attention_span_seconds": 15,
                            "key_interests": [],
                            "requires_attention": False
                        }
                    }
                else:
                    res_data = None
                    if doubao.client:
                        try:
                            print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model...")
                            llm_start = time.time()
                            res_data = doubao.unified_text_chat(user_text)
                            print(f"[DEBUG] [FAST_PATH] Doubao Text-to-JSON took {time.time() - llm_start:.2f}s")
                        except Exception as db_err:
                            print(f"[WARNING] [FAST_PATH] Doubao text-to-JSON failed: {db_err}, trying DeepSeek...")
                    
                    if not res_data and deepseek.client:
                        try:
                            print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model...")
                            llm_start = time.time()
                            res_data = deepseek.unified_text_chat(user_text)
                            print(f"[DEBUG] [FAST_PATH] DeepSeek Text-to-JSON took {time.time() - llm_start:.2f}s")
                        except Exception as ds_err:
                            print(f"[WARNING] [FAST_PATH] DeepSeek text-to-JSON failed: {ds_err}")
            else:
                res_data = None
                if doubao.client:
                    try:
                        print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model (text input)...")
                        res_data = doubao.unified_text_chat(prompt_input)
                    except Exception as db_err:
                        print(f"[WARNING] [CORE] Doubao text chat failed: {db_err}, trying DeepSeek...")
                if not res_data and deepseek.client:
                    try:
                        print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model (text input)...")
                        res_data = deepseek.unified_text_chat(prompt_input)
                    except Exception as ds_err:
                        print(f"[WARNING] [CORE] DeepSeek text chat failed: {ds_err}")
                
            if res_data:
                user_text = res_data.get("user_transcript", "")
                text_response = res_data.get("assistant_reply", "")
                requires_drawing = parse_bool(res_data.get("requires_drawing", False)) or parse_bool(res_data.get("requires_painting", False))
                drawing_prompt = res_data.get("drawing_prompt", "") or res_data.get("painting_prompt", "")
                psych_metrics = res_data.get("psych_metrics", {})
                
                # Apply robust checks/heuristics
                user_text_lower = user_text.lower() if user_text else ""
                drawing_keywords = ["画画", "画一个", "画只", "画张", "画条", "画一幅", "画一画", "想要画", "帮我画", "可以画", "画个", "画出", "画一画", "画"]
                
                # 1. If user transcript explicitly asks to draw, but the LLM boolean was False
                if user_text_lower and any(kw in user_text_lower for kw in drawing_keywords) and not requires_drawing:
                    print(f"[DEBUG] [HEURISTIC] Forcing requires_drawing=True due to drawing keywords in user transcript: '{user_text}'")
                    requires_drawing = True
                    
                # 1.5 If teacher response explicitly confirms drawing, force requires_drawing to True
                if check_assistant_drawing_trigger(text_response) and not requires_drawing:
                    print(f"[DEBUG] [HEURISTIC] Forcing requires_drawing=True due to drawing triggers in assistant reply: '{text_response}'")
                    requires_drawing = True
 
                # 2. If drawing_prompt is provided but requires_drawing is False, force it to True
                if drawing_prompt.strip() and not requires_drawing:
                    print(f"[DEBUG] [HEURISTIC] Forcing requires_drawing=True because drawing_prompt is present: '{drawing_prompt}'")
                    requires_drawing = True
                    
                # 3. If requires_drawing is True but drawing_prompt is empty, extract from user transcript or assistant reply
                if requires_drawing and not drawing_prompt.strip():
                    extracted = extract_drawing_subject_advanced(user_text, text_response)
                    if extracted:
                        print(f"[DEBUG] [HEURISTIC] Extracted drawing prompt '{extracted}' from transcript/reply.")
                        drawing_prompt = extracted
                        
                # 3.5 If requires_drawing is True but drawing_prompt is still empty, use fallback
                if requires_drawing and not drawing_prompt.strip():
                    interests = psych_metrics.get("key_interests", [])
                    if interests:
                        drawing_prompt = f"可爱的{interests[0]}"
                        print(f"[DEBUG] [HEURISTIC] No prompt extracted, using fallback from interest: '{drawing_prompt}'")
                    else:
                        drawing_prompt = "可爱的小兔子"
                        print(f"[DEBUG] [HEURISTIC] No prompt extracted, using default fallback: '{drawing_prompt}'")
                
                print(f"[DEBUG] [DOUBAO] Unified pipeline success. Transcript: '{user_text}', Reply: '{text_response}', Drawing: {requires_drawing} ({drawing_prompt})")
                
                action = None
                image_url_result = None
                
                if requires_drawing and drawing_prompt:
                    print(f"[DEBUG] [DOUBAO] Triggering Doubao Seedream image generation for prompt: '{drawing_prompt}'")
                    try:
                        image_urls = doubao.generate_image(drawing_prompt)
                        if image_urls:
                            image_url_result = image_urls[0]
                            processed_image = process_line_art_image(image_url_result, apply_filter=True)
                            bitmap_hex = get_raw_bitmap_hex(image_url_result)
                            
                            job_id = str(uuid.uuid4())
                            save_print_job_to_db({
                                "job_id": job_id,
                                "image_url": processed_image,
                                "bitmap_hex": bitmap_hex,
                                "prompt": drawing_prompt,
                                "timestamp": time.time()
                            })
                            
                            action = {
                                "type": "print",
                                "prompt": drawing_prompt,
                                "job_id": job_id,
                                "image_url": processed_image,
                                "bitmap_hex": bitmap_hex
                            }
                            print(f"[DEBUG] [DOUBAO] Drawing print job created successfully: {job_id}")
                            
                            generation_id = str(uuid.uuid4())
                            save_history_to_db({
                                "generation_id": generation_id,
                                "prompt": drawing_prompt,
                                "english_prompt": drawing_prompt,
                                "engine": "doubao-seedream",
                                "protagonist": None,
                                "title": f"🎨 {drawing_prompt}",
                                "aspect_ratio": "1:1",
                                "num_images": 1,
                                "style": "default",
                                "apply_line_art": True,
                                "image_urls": [processed_image],
                                "raw_bitmaps": [bitmap_hex],
                                "timestamp": time.time()
                            })
                        else:
                            raise ValueError("Seedream returned no URLs")
                    except Exception as draw_err:
                        print(f"[WARNING] [DOUBAO] Seedream failed, falling back to legacy fallback generator: {draw_err}")
                        try:
                            fallback_res = generate_image_with_fallback(drawing_prompt)
                            if fallback_res["urls"]:
                                image_url_result = fallback_res["urls"][0]
                                processed_image = process_line_art_image(image_url_result, apply_filter=True)
                                bitmap_hex = get_raw_bitmap_hex(image_url_result)
                                job_id = str(uuid.uuid4())
                                save_print_job_to_db({
                                    "job_id": job_id,
                                    "image_url": processed_image,
                                    "bitmap_hex": bitmap_hex,
                                    "prompt": drawing_prompt,
                                    "timestamp": time.time()
                                })
                                action = {
                                    "type": "print",
                                    "prompt": drawing_prompt,
                                    "job_id": job_id,
                                    "image_url": processed_image,
                                    "bitmap_hex": bitmap_hex
                                }
                        except Exception as fb_err:
                            print(f"[ERROR] [DOUBAO] Fallback generator also failed: {fb_err}")
                
                try:
                    combined_text = f"儿童原句: {user_text}\nAI回复: {text_response}"
                    embedding_vector = doubao.generate_embedding(combined_text)
                    if not embedding_vector:
                        embedding_vector = [0.0] * 1024
                        
                    vector_metadata = {
                        "psych_metrics": psych_metrics,
                        "drawing_prompt": drawing_prompt if requires_drawing else None,
                        "drawing_url": image_url_result if image_url_result else None,
                        "timestamp": time.time()
                    }
                    save_psych_vector(
                        device_token=device_token,
                        child_text=user_text,
                        ai_response=text_response,
                        embedding=embedding_vector,
                        metadata=vector_metadata
                    )
                except Exception as vector_err:
                    print(f"[ERROR] [DOUBAO_VECTOR] Embedding/Vector DB write failed: {vector_err}")
                
                audio_base64 = None
                if text_response:
                    try:
                        voice_config = get_device_settings(device_token)
                        audio_base64 = deepseek.generate_speech(text_response, voice_name=voice_config)
                    except Exception as tts_err:
                        print(f"[ERROR] [DOUBAO] Speech gen failed: {tts_err}")
                        
                total_duration = time.time() - start_time
                print(f"[DEBUG] [DOUBAO] Total processing finished in {total_duration:.2f}s")
                return {
                    "text_response": text_response,
                    "action": action,
                    "audio_base64": audio_base64,
                    "stt_empty": False if user_text else True
                }
        except Exception as unified_err:
            print(f"[WARNING] [DOUBAO] Unified pipeline crashed, falling back to standard pipeline: {unified_err}")
 
    # Standard Fallback Pipeline
    user_text = prompt_input
    if isinstance(prompt_input, bytes):
        input_len = len(prompt_input)
        print(f"[DEBUG] [CORE] Received voice input: {input_len} bytes")
        
        try:
            start_stt = time.time()
            user_text = deepseek.transcribe_audio(prompt_input)
            stt_duration = time.time() - start_stt
            print(f"[DEBUG] [CORE] STT took {stt_duration:.2f}s. Result: '{user_text}'")
        except Exception as e:
            print(f"[ERROR] [CORE] Failed to transcribe audio after retries: {e}")
            user_text = ""
            
        if not user_text:
            print("[DEBUG] [CORE] STT returned empty text. Returning fallback message.")
            error_msg = "对不起，我没听清，能不能请你再说一遍？" 
            try:
                voice_config = get_device_settings(device_token)
                audio_base64 = deepseek.generate_speech(error_msg, voice_name=voice_config)
            except Exception as e:
                print(f"[ERROR] [CORE] Failed to generate fallback speech: {e}")
                audio_base64 = None
                
            return {
                "text_response": error_msg,
                "action": None,
                "audio_base64": audio_base64,
                "stt_empty": True,
                "raw_len": input_len
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
                
                try:
                    replicate_api = ReplicateAPI()
                    print(f"[DEBUG] [CORE] Translating logic to English...")
                    english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {prompt}")
                    print(f"[DEBUG] [CORE] English Prompt: '{english_prompt}'")
                    
                    result = generate_image_with_fallback(english_prompt)
                    image_urls = result["urls"]
                    
                    if image_urls:
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
                    
        # Backup heuristic for DeepSeek pipeline when no drawing was generated via tool calls
        if not action:
            user_text_lower = user_text.lower() if user_text else ""
            drawing_keywords = ["画画", "画一个", "画只", "画张", "画条", "画一幅", "画一画", "想要画", "帮我画", "可以画", "画个", "画出", "画一画", "画"]
            
            should_draw = False
            if user_text_lower and any(kw in user_text_lower for kw in drawing_keywords):
                should_draw = True
            elif check_assistant_drawing_trigger(text_response):
                should_draw = True
                
            if should_draw:
                prompt = extract_drawing_subject_advanced(user_text, text_response)
                if not prompt or prompt.strip() == "":
                    prompt = "可爱的小兔子"
                
                print(f"[DEBUG] [CORE] Backup drawing triggered for prompt: '{prompt}'")
                try:
                    replicate_api = ReplicateAPI()
                    print(f"[DEBUG] [CORE] Translating logic to English...")
                    english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {prompt}")
                    print(f"[DEBUG] [CORE] English Prompt: '{english_prompt}'")
                    
                    result = generate_image_with_fallback(english_prompt)
                    image_urls = result["urls"]
                    
                    if image_urls:
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
                        print(f"[DEBUG] [CORE] Drawing job created via backup: {job_id}")
                        
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
                        
                        if not text_response or text_response == "我没听清，请再说一遍。":
                            text_response = f"好的，我这就画一张{prompt}。"
                except Exception as e:
                    print(f"[ERROR] [CORE] Backup drawing generation failed: {e}")
                    
        if not text_response:
            text_response = "我没听清，请再说一遍。"
            
        audio_base64 = None
        if text_response:
            try:
                voice_config = get_device_settings(device_token)
                audio_base64 = deepseek.generate_speech(text_response, voice_name=voice_config)
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
