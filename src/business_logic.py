import time
import uuid
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
import numpy as np

from src.logger import setup_logger
logger = setup_logger("business_logic")

from src.config import ARK_API_KEY, ADMIN_KEY
from src.cache import DrawingCacheManager, LLMCacheManager
from src.crud import (
    save_history_to_db, save_print_job_to_db, save_psych_vector, 
    query_psych_vectors, get_device_settings
)
from src.utils import (
    process_line_art_image, get_raw_bitmap_hex, get_embedded_bitmap, get_image_metadata,
    process_line_art_and_bitmap
)
from src.services import (
    DeepSeekAPI, DoubaoAPI, ReplicateAPI, generate_image_with_fallback,
    VoiceInteractionService
)
from src.prompt_fusion import PromptFusionEngine, ConversationContextManager
from src.conversation_crud import ConversationManager

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


def extract_drawing_subject(text: str, conversation_context: Optional[Dict] = None) -> str:
    if not text:
        return ""

    vague_commands = ["画出来", "画一下", "画画", "给我画"]

    # When the user issues a vague command, look back at the conversation
    # history to find the actual drawing subject mentioned earlier.
    if text.strip() in vague_commands and conversation_context:
        message_history = conversation_context.get("message_history", []) or []
        for msg in reversed(message_history[-5:]):
            user_text = (msg or {}).get("user_text", "")
            if user_text and "画" not in user_text:
                recovered_subject = user_text.strip()
                print(f"[DEBUG] [DRAWING] Vague command '{text.strip()}' resolved to subject from history: '{recovered_subject}'")
                return recovered_subject

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


def extract_drawing_subject_advanced(user_text: str, assistant_reply: str, conversation_context: Optional[Dict] = None) -> str:
    # 1. Try to extract from user_text using prefixes (and conversation history for vague commands)
    subject = extract_drawing_subject(user_text, conversation_context)
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
    print(f"[DRAWING] Final prompt: {subject}")
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
                        processed_image, bitmap_hex = process_line_art_and_bitmap(urls[0])
                        return processed_image, bitmap_hex, subject
                except Exception as e:
                    print(f"[WARNING] [ASYNC_DRAW] Doubao draw failed: {e}")

            result = generate_image_with_fallback(subject)
            urls = result.get("urls")
            if urls:
                processed_image, bitmap_hex = process_line_art_and_bitmap(urls[0])
                return processed_image, bitmap_hex, subject
        except Exception as e:
            print(f"[ERROR] [ASYNC_DRAW] Image generation failed: {e}")
        return None, None, subject

    try:
        processed_image, bitmap_hex, prompt = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync),
            timeout=60.0
        )
    except asyncio.TimeoutError:
        print(f"[ERROR] [ASYNC_DRAW] Image generation timed out after 45s")
        processed_image, bitmap_hex, prompt = None, None, subject

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


async def async_generate_drawing_with_fusion(
    fused_prompt: str, 
    device_token: str, 
    fusion_result: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Generates drawing line art asynchronously using fused_prompt and persists history.
    """
    print(f"[DEBUG] [ASYNC_DRAW] Using fused prompt: {fused_prompt[:100]}...")
    print(f"[DRAWING] Final prompt: {fused_prompt}")
    start_time = time.time()
    
    cache_mgr = DrawingCacheManager.get_instance()
    cached = cache_mgr.get(fused_prompt)
    if cached:
        print(f"[DEBUG] [ASYNC_DRAW] Cache Hit for fused prompt: '{fused_prompt}'")
        job_id = str(uuid.uuid4())
        save_print_job_to_db({
            "job_id": job_id,
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex"),
            "prompt": fusion_result.get("target_element") or fused_prompt,
            "timestamp": time.time()
        })
        
        from src.conversation_crud import ConversationManager
        ConversationManager.save_drawing_record(
            job_id=job_id,
            device_token=device_token,
            operation_type=fusion_result.get("operation"),
            scene_prompt=fused_prompt,
            image_url=cached.get("image_url")
        )
        
        return {
            "type": "draw",
            "prompt": fusion_result.get("target_element"),
            "fused_prompt": fused_prompt,
            "operation": fusion_result.get("operation"),
            "scene_elements": fusion_result.get("all_elements_after"),
            "job_id": job_id,
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex")
        }

    def _generate_sync():
        try:
            doubao = DoubaoAPI.get_instance()
            if doubao.client:
                try:
                    urls = doubao.generate_image(fused_prompt)
                    if urls:
                        processed_image, bitmap_hex = process_line_art_and_bitmap(urls[0])
                        return processed_image, bitmap_hex
                except Exception as e:
                    print(f"[WARNING] [ASYNC_DRAW] Doubao Seedream image generation failed: {e}")

            result = generate_image_with_fallback(fused_prompt)
            urls = result.get("urls")
            if urls:
                processed_image, bitmap_hex = process_line_art_and_bitmap(urls[0])
                return processed_image, bitmap_hex
        except Exception as e:
            print(f"[ERROR] [ASYNC_DRAW] Image generation with fusion failed: {e}")
        return None, None

    try:
        processed_image, bitmap_hex = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync),
            timeout=60.0
        )
    except asyncio.TimeoutError:
        print(f"[ERROR] [ASYNC_DRAW] Image generation with fusion timed out after 45s")
        processed_image, bitmap_hex = None, None

    if processed_image and isinstance(processed_image, str) and len(processed_image.strip()) > 0:
        job_id = str(uuid.uuid4())
        logger.info(f"[ASYNC_DRAW] ✅ Image generation successful, saving to PrintJob... URL length: {len(processed_image)}")
        
        try:
            save_print_job_to_db({
                "job_id": job_id,
                "image_url": processed_image,
                "bitmap_hex": bitmap_hex,
                "prompt": fusion_result.get("target_element") or fused_prompt,
                "timestamp": time.time()
            })
        except Exception as db_err:
            logger.error(f"[ASYNC_DRAW] Failed to save PrintJob: {db_err}")

        from src.conversation_crud import ConversationManager
        try:
            ConversationManager.save_drawing_record(
                job_id=job_id,
                device_token=device_token,
                operation_type=fusion_result.get("operation"),
                scene_prompt=fused_prompt,
                image_url=processed_image
            )
        except Exception as history_err:
            logger.error(f"[ASYNC_DRAW] Failed to save DrawingHistory: {history_err}")

        action = {
            "type": "draw",
            "prompt": fusion_result.get("target_element"),
            "fused_prompt": fused_prompt,
            "operation": fusion_result.get("operation"),
            "scene_elements": fusion_result.get("all_elements_after"),
            "job_id": job_id,
            "image_url": processed_image,
            "bitmap_hex": bitmap_hex
        }

        cache_mgr.set(fused_prompt, action)

        duration = time.time() - start_time
        print(f"[DEBUG] [ASYNC_DRAW] Image generated with fusion and cached in {duration:.2f}s, job_id: {job_id}")
        return action
    else:
        logger.error(f"[ASYNC_DRAW] ❌ Image generation failed or returned empty result")
        logger.error(f"[ASYNC_DRAW] processed_image type: {type(processed_image)}, value: {processed_image}")
        logger.error(f"[ASYNC_DRAW] Attempted prompt: {fused_prompt[:100]}")
        return None


async def stream_chat_llm(user_text: str):
    """Streams chat tokens from Doubao or fallback provider using async client."""
    doubao = DoubaoAPI.get_instance()
    deepseek = DeepSeekAPI.get_instance()
    system_instruction = "你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。请与小朋友进行顺畅好玩的互动聊天，保持简短、充满童趣，控制在 3-5 句话内。"

    if doubao.async_client:
        try:
            print(f"[DEBUG] [STREAM_LLM] Attempting stream with Doubao (Async): '{user_text}'")
            stream = await doubao.async_client.chat.completions.create(
                model=doubao.audio_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_text}
                ],
                stream=True,
                timeout=15
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    await asyncio.sleep(0.005)
            return
        except Exception as e:
            print(f"[ERROR] [STREAM_LLM] Doubao stream error: {e}, falling back to DeepSeek...")

    if deepseek.async_client:
        try:
            print(f"[DEBUG] [STREAM_LLM] Attempting stream with DeepSeek (Async): '{user_text}'")
            stream = await deepseek.async_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_text}
                ],
                stream=True,
                timeout=15
            )
            async for chunk in stream:
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


def _default_conversation_context(device_token: str) -> Dict[str, Any]:
    return {
        "device_token": device_token,
        "message_history": [],
        "current_image_url": None,
        "current_image_bitmap_hex": None,
        "scene_elements": [],
        "last_generated_prompt": None,
        "last_operation_type": None,
        "last_operation_detail": {},
    }


def _empty_audio_response() -> Dict[str, Any]:
    return {
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
            "requires_attention": False,
        },
    }


def _apply_drawing_heuristics(
    user_text: str,
    text_response: str,
    requires_drawing: bool,
    drawing_prompt: str,
    psych_metrics: Dict[str, Any],
    device_token: str,
) -> tuple:
    user_text_lower = user_text.lower() if user_text else ""
    drawing_keywords = [
        "画画", "画一个", "画只", "画张", "画条", "画一幅", "画一画",
        "想要画", "帮我画", "可以画", "画个", "画出", "画", "帮我画",
        "想画", "想要一个画", "想要一张画", "画它", "画出来", "画出来吧"
    ]

    agreement_keywords = [
        "好", "好的", "好呀", "好啊", "想", "想画", "要", "要画", "对", "对呀",
        "画一个", "画出来", "可以", "行", "嗯", "嗯嗯", "喜欢", "要的", "画吧", "画呀"
    ]

    # 1. Direct explicit drawing keywords from user
    if user_text_lower and any(kw in user_text_lower for kw in drawing_keywords) and not requires_drawing:
        logger.debug(f"[HEURISTIC] Forcing requires_drawing=True from user text: '{user_text}'")
        requires_drawing = True

    # 2. Check if previous AI message asked to draw and user answered in agreement
    conv_context = ConversationManager.get_conversation_context(device_token)
    if conv_context and not requires_drawing:
        history = conv_context.get("message_history", [])
        if history:
            last_ai_msg = history[-1].get("ai_response", "")
            if any(ask_kw in last_ai_msg for ask_kw in ["画出来", "要不要画", "想不想画", "为你画", "画一张", "画一幅", "画成画"]):
                trimmed = user_text_lower.strip("。，！？.!? ")
                if any(agree_kw == trimmed or agree_kw in trimmed for agree_kw in agreement_keywords):
                    logger.debug(f"[HEURISTIC] User agreed to previous drawing invitation! user: '{user_text}'")
                    requires_drawing = True

    # 3. Check assistant drawing trigger phrases in current response
    if check_assistant_drawing_trigger(text_response) and not requires_drawing:
        logger.debug("[HEURISTIC] Forcing requires_drawing=True from assistant reply")
        requires_drawing = True

    if drawing_prompt.strip() and not requires_drawing:
        requires_drawing = True

    # 4. Recover drawing_prompt if empty but drawing was triggered
    if requires_drawing and not drawing_prompt.strip():
        extracted = extract_drawing_subject_advanced(user_text, text_response, conv_context)
        if extracted:
            drawing_prompt = extracted

    if requires_drawing and not drawing_prompt.strip():
        interests = psych_metrics.get("key_interests", [])
        if interests:
            drawing_prompt = f"可爱的{interests[0]}"
        elif conv_context and conv_context.get("scene_elements"):
            elements = conv_context.get("scene_elements")
            drawing_prompt = f"可爱的{elements[-1]}"
        else:
            drawing_prompt = "可爱的小动物"

    return requires_drawing, drawing_prompt


async def _background_drawing_and_record(
    fusion_input: str,
    device_token: str,
    text_response: str,
    drawing_prompt: str
):
    """Background task to generate Seedream image, convert to 1-bit line art, and put into PrintJob queue."""
    draw_start = time.time()
    try:
        logger.info(f"[ASYNC_DRAW_BG] 🎨 Background drawing started for: '{fusion_input}' (token: {device_token})")
        action = await _execute_drawing_with_fusion(fusion_input, device_token, text_response)
        draw_duration = time.time() - draw_start
        if action:
            logger.info(f"[ASYNC_DRAW_BG] ✅ Print job {action.get('job_id')} created in {draw_duration:.2f}s!")
        else:
            logger.warning(f"[ASYNC_DRAW_BG] ⚠️ Drawing finished with no action returned ({draw_duration:.2f}s)")
    except Exception as e:
        logger.error(f"[ASYNC_DRAW_BG] ❌ Drawing generation failed in background: {e}")


async def _background_save_psych_vector(
    device_token: str,
    child_text: str,
    ai_response: str,
    psych_metrics: Dict[str, Any],
    drawing_prompt: Optional[str] = None
):
    """Background execution for multimodal embedding and saving psychological vector record."""
    try:
        doubao = DoubaoAPI.get_instance()
        combined_text = f"儿童原句: {child_text}\nAI回复: {ai_response}"
        embedding_vector = await asyncio.to_thread(doubao.generate_embedding, combined_text)
        if not embedding_vector or embedding_vector == [0.0] * 1024:
            embedding_vector = [0.0] * 1024
            embedding_available = False
        else:
            embedding_available = True

        vector_metadata = {
            "psych_metrics": psych_metrics,
            "drawing_prompt": drawing_prompt,
            "drawing_url": None,
            "timestamp": time.time(),
            "embedding_valid": embedding_available,
            "embedding_available": embedding_available,
        }
        await asyncio.to_thread(
            save_psych_vector,
            device_token=device_token,
            child_text=child_text,
            ai_response=ai_response,
            embedding=embedding_vector,
            metadata=vector_metadata,
        )
        logger.debug(f"[BACKGROUND_PSYCH] Psych vector saved successfully for {device_token}")
    except Exception as e:
        logger.error(f"[BACKGROUND_PSYCH] Error saving psych vector: {e}")


async def _execute_drawing_with_fusion(
    user_text: str,
    device_token: str,
    ai_response: str = "",
) -> Optional[Dict[str, Any]]:
    """Same PromptFusion drawing pipeline as SSE text chat."""
    context = ConversationManager.get_conversation_context(device_token)
    if context is None:
        context = _default_conversation_context(device_token)

    fusion_inputs = ConversationContextManager.prepare_fusion_inputs(user_text, context)
    operation = fusion_inputs["operation"]
    if operation.get("confidence", 0.0) < 0.5:
        operation["type"] = "create"

    fusion_result = PromptFusionEngine.fuse_drawing_prompt(
        current_user_text=user_text,
        operation_type=operation["type"],
        previous_prompt=fusion_inputs["previous_prompt"],
        scene_elements=fusion_inputs["scene_elements"],
    )
    fused_prompt = fusion_result.get("fused_prompt") or user_text
    logger.info(f"[DRAWING] Fusion prompt: '{fused_prompt}' (op={operation['type']})")

    action = await async_generate_drawing_with_fusion(fused_prompt, device_token, fusion_result)
    if not action:
        return None

    updated_ctx = ConversationContextManager.update_context_after_fusion(
        dict(context),
        fusion_result,
        image_url=action.get("image_url"),
        bitmap_hex=action.get("bitmap_hex"),
    )
    ConversationManager.create_or_update_conversation_context(device_token, updated_ctx)
    return action


async def _resolve_doubao_dialog(
    prompt_input: Any, 
    llm_cache: LLMCacheManager,
    history: Optional[List[Dict[str, Any]]] = None,
    ask_to_draw: bool = False
) -> tuple:
    """
    Resolve user dialog via Doubao:
    - bytes: fast STT (~0.3s) → Doubao unified_text_chat (~0.8s)
    - str: Doubao unified_text_chat (~0.8s)
    Returns (res_data, stt_duration, llm_duration).
    """
    doubao = DoubaoAPI.get_instance()
    stt_duration = 0.0
    llm_duration = 0.0
    res_data = None

    if isinstance(prompt_input, bytes):
        stt_start = time.time()
        user_text = doubao.transcribe_audio(prompt_input)
        stt_duration = time.time() - stt_start
        logger.info(f"[STT] Audio transcribed in {stt_duration:.2f}s. Result: '{user_text}'")

        if user_text:
            llm_start = time.time()
            try:
                res_data = doubao.unified_text_chat(user_text, history=history, ask_to_draw=ask_to_draw)
            except Exception as text_err:
                logger.warning(f"[DOUBAO] unified_text_chat after STT failed: {text_err}")
            llm_duration = time.time() - llm_start

        if not res_data:
            res_data = _empty_audio_response()
    else:
        llm_start = time.time()
        try:
            res_data = doubao.unified_text_chat(prompt_input, history=history, ask_to_draw=ask_to_draw)
        except Exception as text_err:
            logger.warning(f"[DOUBAO] unified_text_chat failed: {text_err}")
        llm_duration = time.time() - llm_start

    return res_data, stt_duration, llm_duration


async def process_llm_interaction(prompt_input: Any, api_key: str = None, device_token: str = None) -> Dict[str, Any]:
    start_time = time.time()
    stt_duration = 0.0
    llm_duration = 0.0
    tts_duration = 0.0

    device_token = device_token or "anonymous_device"
    doubao = DoubaoAPI.get_instance()
    llm_cache = LLMCacheManager.get_instance()

    if not doubao.client:
        raise HTTPException(status_code=500, detail="ARK_API_KEY is not configured")

    # Load context and check turn count
    context = ConversationManager.get_conversation_context(device_token)
    if context is None:
        context = _default_conversation_context(device_token)

    message_history = list(context.get("message_history", []))
    turn_count = len(message_history) + 1

    # Check if we should actively guide and ask the child to draw (every 3 conversation turns)
    ask_to_draw = (turn_count % 3 == 0)

    try:
        logger.info(f"[CORE] Doubao pipeline for token: {device_token} (Turn: {turn_count}, ask_to_draw: {ask_to_draw})...")
        dialog_result = await _resolve_doubao_dialog(prompt_input, llm_cache, history=message_history, ask_to_draw=ask_to_draw)
        res_data, stt_duration, llm_duration = dialog_result

        if res_data:
            user_text = res_data.get("user_transcript", "")
            text_response = res_data.get("assistant_reply", "")
            requires_drawing = parse_bool(res_data.get("requires_drawing", False)) or parse_bool(res_data.get("requires_painting", False))
            drawing_prompt = res_data.get("drawing_prompt", "") or res_data.get("painting_prompt", "")
            psych_metrics = res_data.get("psych_metrics", {})

            requires_drawing, drawing_prompt = _apply_drawing_heuristics(
                user_text, text_response, requires_drawing, drawing_prompt,
                psych_metrics, device_token,
            )

            logger.info(
                f"[DOUBAO] Pipeline OK. Transcript: '{user_text}', "
                f"Reply: '{text_response}', Drawing: {requires_drawing} ({drawing_prompt})"
            )

            voice_config = get_device_settings(device_token)

            # 1. Start TTS Generation (Fast audio synthesis)
            tts_task = None
            tts_start = time.time()
            if text_response:
                tts_task = asyncio.create_task(
                    asyncio.to_thread(doubao.generate_speech, text_response, voice_config)
                )

            # 2. If drawing is requested, launch drawing as an independent background task (DO NOT block the HTTP response!)
            action_preview = None
            if requires_drawing and (user_text or drawing_prompt):
                fusion_input = user_text or drawing_prompt
                asyncio.create_task(
                    _background_drawing_and_record(fusion_input, device_token, text_response, drawing_prompt)
                )
                action_preview = {
                    "type": "draw",
                    "status": "generating_in_background",
                    "prompt": drawing_prompt or fusion_input
                }

            # 3. Update and persist message history to conversation context
            new_msg = {
                "timestamp": time.time(),
                "user_text": user_text,
                "ai_response": text_response,
                "drawing_triggered": requires_drawing,
                "drawing_prompt": drawing_prompt if requires_drawing else None,
            }
            message_history.append(new_msg)
            context["message_history"] = message_history
            ConversationManager.create_or_update_conversation_context(device_token, context)

            # 4. Launch psych vector & embedding save as an independent background task
            asyncio.create_task(
                _background_save_psych_vector(
                    device_token=device_token,
                    child_text=user_text,
                    ai_response=text_response,
                    psych_metrics=psych_metrics,
                    drawing_prompt=drawing_prompt if requires_drawing else None
                )
            )

            # 5. Await only TTS audio for instant response (typically ~0.5s)
            audio_base64 = None
            if tts_task:
                try:
                    audio_base64 = await tts_task
                    tts_duration = time.time() - tts_start
                    logger.info(f"[DOUBAO] TTS took {tts_duration:.2f}s")
                except Exception as tts_err:
                    tts_duration = time.time() - tts_start
                    logger.error(f"[DOUBAO] Speech gen failed: {tts_err}")

            total_duration = time.time() - start_time
            logger.info(
                f"\n=================== REAL-TIME PERFORMANCE METRICS ===================\n"
                f"  [ASR / STT]      : {stt_duration:.2f}s\n"
                f"  [LLM / DIALOG]   : {llm_duration:.2f}s\n"
                f"  [TTS / AUDIO]    : {tts_duration:.2f}s\n"
                f"  [DRAWING BG TASK]: {'Active (Background)' if requires_drawing else 'None'}\n"
                f"  [TOTAL LATENCY]  : {total_duration:.2f}s (Ultra-Fast Response!)\n"
                f"====================================================================="
            )

            return_payload = {
                "text_response": text_response,
                "action": action_preview,
                "audio_base64": audio_base64,
                "stt_empty": False if user_text else True,
                "requires_drawing": requires_drawing,
                "device_token": device_token,
                "turn_count": turn_count
            }
            return return_payload

    except Exception as pipeline_err:
        logger.error(f"[DOUBAO] Pipeline failed: {pipeline_err}")
        raise HTTPException(status_code=500, detail=f"Voice/chat processing failed: {pipeline_err}")
