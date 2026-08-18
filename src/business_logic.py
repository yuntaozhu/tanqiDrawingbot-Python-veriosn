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
    query_psych_vectors, get_device_settings,
    get_ready_drawings_from_db, queue_print_job, allocate_scroll_seq,
)
from src.utils import (
    process_line_art_image, get_raw_bitmap_hex, get_embedded_bitmap, get_image_metadata,
    process_line_art_and_bitmap
)
from src.services import (
    DeepSeekAPI, DoubaoAPI, ReplicateAPI, generate_image_with_fallback,
    VoiceInteractionService
)
from src.prompt_fusion import ConversationContextManager
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
    """Only true for clear AI promises that drawing has started (not invitations)."""
    if not text:
        return False
    text_lower = text.lower()
    # Invitation questions must NOT trigger drawing.
    if any(q in text_lower for q in [
        "你想画", "你要画", "画什么", "要不要画", "想不想画", "画出来呀", "画出来吗", "画出来不"
    ]):
        return False
    direct_triggers = [
        "我们一起来画", "我为你画", "我画了", "为你画了", "开始画",
        "这就画", "这就给你画", "正在画", "准备画", "开始为你画",
        "画好啦", "画好了", "马上画", "马上为你画", "马上帮你画", "帮宝贝画"
    ]
    return any(trig in text_lower for trig in direct_triggers)


def _is_preview_lookback_request(user_text: str) -> bool:
    """Child is asking where the previous drawing is — not a new draw command."""
    if not user_text:
        return False
    lookback = [
        "没看到", "看不到", "看不见", "哪里的画", "画呢", "画在哪",
        "刚才的画", "刚刚的画", "画好了吗", "画好了没", "图片呢", "画出来了吗"
    ]
    return any(k in user_text for k in lookback)


def _is_short_affirmation(user_text: str) -> bool:
    """True only for short yes-answers, not greetings like 你好."""
    if not user_text:
        return False
    trimmed = user_text.strip("。，！？.!? ～~、 ")
    exact = {
        "好", "好的", "好呀", "好啊", "好哦", "好嘞", "行", "行啊", "行呀",
        "要", "要的", "要呀", "要啊", "想", "想画", "想要", "可以", "可以呀",
        "嗯", "嗯嗯", "对", "对呀", "对啊", "是", "是的", "画吧", "画呀",
        "画出来", "画一个", "画", "来吧", "喜欢"
    }
    if trimmed in exact:
        return True
    # Allow "好的呀" / "要画" style short replies (≤6 chars)
    if len(trimmed) <= 6 and any(
        trimmed.startswith(p) for p in ("好", "要", "想", "行", "对", "嗯", "画", "可以")
    ):
        return True
    return False


EXPLICIT_DRAW_KEYWORDS = [
    "画画", "画一个", "画一只", "画一条", "画一张", "画一幅", "画一画",
    "画一朵", "画一辆", "画一座", "画一只小",
    "画只", "画张", "画条", "画个", "画出",
    "想要画", "帮我画", "可以画", "想画", "给我画", "开始画",
    "画出来", "画出来吧", "把它画出来", "再画",
    "画小猫", "画小狗", "画小兔", "画小鱼", "画只小", "画条鱼", "画鱼", "一条小鱼",
]

COMPLETE_DRAW_PHRASES = {
    "画出来", "画出来吧", "把它画出来", "开始画", "给我画", "帮我画",
    "画画", "画一张", "画一幅", "画一画",
}

THINKING_TOKENS = {
    "嗯", "啊", "呃", "额", "那个", "嗯嗯", "啊啊", "然后", "就是", "这个", "唔",
}


def _has_explicit_draw_intent(user_text: str) -> bool:
    if not user_text:
        return False
    return any(kw in user_text for kw in EXPLICIT_DRAW_KEYWORDS)


def _is_complete_draw_command(user_text: str) -> bool:
    """True when the child wants to render the accumulated draft, with no new subject."""
    if not user_text:
        return False
    trimmed = user_text.strip("。，！？.!? ～~、 ")
    return trimmed in COMPLETE_DRAW_PHRASES


def _is_thinking_utterance(user_text: str) -> bool:
    if not user_text:
        return True
    trimmed = user_text.strip("。，！？.!? ～~、 ")
    if not trimmed:
        return True
    return trimmed in THINKING_TOKENS or (len(trimmed) <= 2 and trimmed in THINKING_TOKENS)


def _draft_subject(draft_prompt: str) -> str:
    text = (draft_prompt or "").strip()
    if not text:
        return "它"
    return text[:8]


def _followup_question(draft_prompt: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
    """Ask one concrete question from the current draft — no extra LLM call."""
    draft = (draft_prompt or "").strip()
    color_marks = ("红", "黄", "蓝", "绿", "橙", "粉", "白", "黑", "紫", "彩色", "橘色", "金色")
    place_marks = ("公园", "家里", "天上", "海里", "森林", "草地", "学校", "河边", "花园")
    if draft:
        subject = _draft_subject(draft)
        if not any(c in draft for c in color_marks):
            return f"{subject}是什么颜色的呀？"
        if not any(p in draft for p in place_marks):
            return f"{subject}在哪里玩呀？"
        return f"那{subject}在干什么呢？想好了也可以说画出来。"
    last_user = ""
    for msg in reversed(history or []):
        last_user = ((msg or {}).get("user_text") or "").strip()
        if last_user:
            break
    if last_user:
        snippet = last_user[:10]
        return f"你刚说的「{snippet}」，再给小探宝讲一点好不好？"
    return "想好了跟小探宝说呀，我们慢慢聊。"


def _merge_draft_prompt(existing: str, incoming: str) -> str:
    incoming = (incoming or "").strip()
    existing = (existing or "").strip()
    vague = {"", "画", "画画", "画出来", "好的", "好的画出来", "画出来吧"}
    compact = incoming.replace("，", "").replace("。", "").replace(" ", "")
    if incoming and compact not in vague:
        return incoming[:80]
    return existing


def _is_print_intent(user_text: str) -> bool:
    """Voice/text confirmation to print the latest ready drawing. Not a new draw."""
    if not user_text:
        return False
    trimmed = user_text.strip("。，！？.!? ～~、 ")
    if any(n in trimmed for n in ("不要打印", "别打印", "先不打印", "不用打印")):
        return False
    if "画" in trimmed and "打印" in trimmed:
        return False
    exact = {
        "打印", "打印出来", "打印吧", "打印呀", "打印啊", "帮我打印", "打印这张",
        "请打印", "出纸", "打出来", "印出来", "印一下", "我要打印",
    }
    if trimmed in exact:
        return True
    if any(k in trimmed for k in ("打印出来", "帮我打印", "打印这张", "打印一下")):
        return True
    if trimmed.endswith("打印") and len(trimmed) <= 8:
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
            "status": "ready",
            "prompt": subject,
            "job_id": job_id,
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex")
        }
        save_print_job_to_db({
            "job_id": job_id,
            "device_token": device_token,
            "status": "ready",
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
            "device_token": device_token,
            "status": "ready",
            "image_url": processed_image,
            "bitmap_hex": bitmap_hex,
            "prompt": prompt,
            "timestamp": time.time()
        }
        save_print_job_to_db(job_data)

        action = {
            "type": "draw",
            "status": "ready",
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
    fusion_result: Dict[str, Any],
    seed: Optional[int] = None,
    scroll_id: Optional[str] = None,
    seq: Optional[int] = None,
    epoch: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    Generates drawing line art asynchronously using fused_prompt and persists history.
    """
    print(f"[DEBUG] [ASYNC_DRAW] Using fused prompt: {fused_prompt[:100]}...")
    print(f"[DRAWING] Final prompt: {fused_prompt}")
    start_time = time.time()

    if not scroll_id or seed is None:
        meta = _scroll_meta_for_device(device_token)
        scroll_id = scroll_id or meta["scroll_id"]
        seed = seed if seed is not None else meta["seed"]
        seq = seq if seq is not None else meta["seq"]
    
    cache_mgr = DrawingCacheManager.get_instance()
    operation = (fusion_result or {}).get("operation") or "create"
    use_drawing_cache = operation == "create" and seed is None
    cached = cache_mgr.get(fused_prompt) if use_drawing_cache else None
    if cached:
        if not await _is_current_draw_epoch(device_token, epoch):
            logger.info(f"[ASYNC_DRAW] Discard stale cache-hit epoch={epoch}")
            return None
        print(f"[DEBUG] [ASYNC_DRAW] Cache Hit for fused prompt: '{fused_prompt}'")
        job_id = str(uuid.uuid4())
        save_print_job_to_db({
            "job_id": job_id,
            "device_token": device_token,
            "status": "ready",
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex"),
            "prompt": fusion_result.get("target_element") or fused_prompt,
            "timestamp": time.time(),
            "scroll_id": scroll_id,
            "seed": seed,
            "seq": seq,
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
            "status": "ready",
            "prompt": fusion_result.get("target_element"),
            "fused_prompt": fused_prompt,
            "operation": fusion_result.get("operation"),
            "scene_elements": fusion_result.get("all_elements_after"),
            "job_id": job_id,
            "image_url": cached.get("image_url"),
            "bitmap_hex": cached.get("bitmap_hex"),
            "scroll_id": scroll_id,
            "seed": seed,
            "seq": seq,
        }

    def _generate_sync():
        try:
            result = generate_image_with_fallback(
                fused_prompt, seed=seed, skip_cache=operation != "create"
            )
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
            timeout=50.0
        )
    except asyncio.TimeoutError:
        print(f"[ERROR] [ASYNC_DRAW] Image generation with fusion timed out after 50s")
        processed_image, bitmap_hex = None, None

    if processed_image and isinstance(processed_image, str) and len(processed_image.strip()) > 0:
        if not await _is_current_draw_epoch(device_token, epoch):
            logger.info(f"[ASYNC_DRAW] Discard stale generated image epoch={epoch}")
            return None
        job_id = str(uuid.uuid4())
        logger.info(f"[ASYNC_DRAW] ✅ Image ready for preview (manual print). URL length: {len(processed_image)}")
        
        try:
            save_print_job_to_db({
                "job_id": job_id,
                "device_token": device_token,
                "status": "ready",
                "image_url": processed_image,
                "bitmap_hex": bitmap_hex,
                "prompt": fusion_result.get("target_element") or fused_prompt,
                "timestamp": time.time(),
                "scroll_id": scroll_id,
                "seed": seed,
                "seq": seq,
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
            "status": "ready",
            "prompt": fusion_result.get("target_element"),
            "fused_prompt": fused_prompt,
            "operation": fusion_result.get("operation"),
            "scene_elements": fusion_result.get("all_elements_after"),
            "job_id": job_id,
            "image_url": processed_image,
            "bitmap_hex": bitmap_hex,
            "scroll_id": scroll_id,
            "seed": seed,
            "seq": seq,
        }

        if use_drawing_cache:
            cache_mgr.set(fused_prompt, action)

        duration = time.time() - start_time
        print(f"[DEBUG] [ASYNC_DRAW] Image generated with fusion in {duration:.2f}s, job_id: {job_id}, op={operation}, cached={use_drawing_cache}")
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
                model=doubao.chat_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_text}
                ],
                stream=True,
                extra_body={"service_tier": "fast"},
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
        "current_scroll_id": None,
        "current_seed": None,
        "draft_prompt": "",
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


def _dialog_unavailable_response(user_text: str) -> Dict[str, Any]:
    """Keep recognized speech usable when the dialog model is temporarily unavailable."""
    wants_draw = _has_explicit_draw_intent(user_text)
    if wants_draw:
        reply = "好呀，我马上画给你！画好了看屏幕，点打印就能出纸。"
    else:
        reply = "我听到你说的话啦。我们先继续玩，马上再和你聊！"
    return {
        "user_transcript": user_text,
        "assistant_reply": reply,
        "requires_drawing": wants_draw,
        "drawing_prompt": user_text if wants_draw else "",
        "psych_metrics": {
            "detected_emotions": [],
            "linguistic_richness_score": 0.0,
            "cognitive_milestone_ref": "暂未分析",
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
    user_text = user_text or ""
    drawing_prompt = (drawing_prompt or "").strip()

    # Never treat "where's my drawing" as a new draw request
    if _is_preview_lookback_request(user_text):
        logger.info(f"[HEURISTIC] Preview lookback — skip drawing. user='{user_text}'")
        return False, drawing_prompt

    conv_context = ConversationManager.get_conversation_context(device_token)
    draft = ((conv_context or {}).get("draft_prompt") or "").strip()

    # Command words / invite-affirmation only. Ignore LLM requires_drawing on idle chat
    # so Seedream never blocks a child's conversation turn.
    llm_wants_draw = bool(requires_drawing)
    requires_drawing = False
    if _has_explicit_draw_intent(user_text):
        requires_drawing = True
        logger.debug(f"[HEURISTIC] Explicit draw command: '{user_text}'")
    elif conv_context:
        history = conv_context.get("message_history", [])
        if history:
            last_ai_msg = history[-1].get("ai_response", "") or ""
            invited = any(ask_kw in last_ai_msg for ask_kw in [
                "画出来", "要不要画", "想不想画", "画一张", "画一幅", "帮你画"
            ])
            if invited and _is_short_affirmation(user_text):
                requires_drawing = True
                logger.debug(f"[HEURISTIC] Short affirmation after invite: '{user_text}'")
    if llm_wants_draw and not requires_drawing:
        logger.info(f"[HEURISTIC] LLM wanted draw but no command word — keep chatting. user='{user_text}'")

    if not requires_drawing:
        return False, drawing_prompt

    # Recover a concrete subject when prompt is empty / vague
    vague = {"", "画", "画画", "画出来", "好的", "好的画出来", "画出来吧", "开始画", "给我画", "帮我画"}
    if _is_complete_draw_command(user_text) and draft:
        drawing_prompt = draft
    elif not drawing_prompt or drawing_prompt.replace("，", "").replace("。", "").replace(" ", "") in vague:
        extracted = extract_drawing_subject_advanced(user_text, text_response, conv_context)
        if extracted and extracted not in vague:
            drawing_prompt = extracted
        elif draft:
            drawing_prompt = draft
        elif conv_context:
            # Prefer last successful drawing subject from history
            for msg in reversed(conv_context.get("message_history", []) or []):
                prev = (msg or {}).get("drawing_prompt")
                if prev and str(prev).strip() and str(prev).strip() not in vague:
                    drawing_prompt = str(prev).strip()
                    break
            if not drawing_prompt and conv_context.get("scene_elements"):
                drawing_prompt = f"可爱的{conv_context['scene_elements'][-1]}"
            elif not drawing_prompt and conv_context.get("last_generated_prompt"):
                drawing_prompt = conv_context["last_generated_prompt"]

    if requires_drawing and not drawing_prompt.strip():
        interests = (psych_metrics or {}).get("key_interests", [])
        drawing_prompt = f"可爱的{interests[0]}" if interests else "可爱的小动物"

    # Never use greeting / lookback text as the image prompt
    bad_subjects = ["你好", "开始聊天", "没看到", "看不到"]
    if any(b in drawing_prompt for b in bad_subjects) and len(drawing_prompt) < 20:
        drawing_prompt = "可爱的小动物"

    return requires_drawing, drawing_prompt


# One Seedream job at a time (single Railway worker — concurrent draws starve voice LLM)
_DRAWING_SEMAPHORE = asyncio.Semaphore(1)
_active_drawing_devices: set = set()
_pending_drawings: Dict[str, list] = {}
_drawing_workers: set = set()
_drawing_meta_lock = asyncio.Lock()
_draw_epoch: Dict[str, int] = {}


async def _is_current_draw_epoch(device_token: str, epoch: int) -> bool:
    if not epoch:
        return True
    async with _drawing_meta_lock:
        return _draw_epoch.get(device_token) == epoch


def is_device_drawing(device_token: str) -> bool:
    if not device_token:
        return False
    if device_token in _drawing_workers or device_token in _active_drawing_devices:
        return True
    return bool(_pending_drawings.get(device_token))


def _scroll_meta_for_device(device_token: str) -> Dict[str, Any]:
    scroll_id, seed = ConversationManager.ensure_scroll(device_token)
    seq = allocate_scroll_seq(scroll_id)
    return {"scroll_id": scroll_id, "seed": seed, "seq": seq}


def _handle_voice_print(device_token: str) -> Dict[str, Any]:
    jobs = get_ready_drawings_from_db(device_token)
    if not jobs:
        if is_device_drawing(device_token):
            return {
                "type": "print",
                "status": "waiting",
                "success": False,
                "message": "还在画，画好了再说打印呀。",
            }
        return {
            "type": "print",
            "status": "none",
            "success": False,
            "message": "现在没有可以打印的画，先画一张吧。",
        }
    latest = jobs[-1]
    queued = queue_print_job(latest["job_id"], device_token)
    if not queued:
        return {
            "type": "print",
            "status": "error",
            "success": False,
            "message": "这张还不能打印，我们再试一次。",
        }
    return {
        "type": "print",
        "status": "queued",
        "success": True,
        "message": "好的，这就打印出来！",
        **queued,
    }


async def _enqueue_background_drawing(
    fusion_input: str,
    device_token: str,
    text_response: str,
    drawing_prompt: str,
):
    """Keep only the latest requested square image; older pending jobs are replaced."""
    subject = (drawing_prompt or "").strip() or (fusion_input or "").strip()
    if not subject:
        logger.warning("[ASYNC_DRAW_BG] Empty subject, skip drawing")
        return

    scroll_meta = _scroll_meta_for_device(device_token)
    start_worker = False
    async with _drawing_meta_lock:
        epoch = _draw_epoch.get(device_token, 0) + 1
        _draw_epoch[device_token] = epoch
        item = (fusion_input, text_response, drawing_prompt, scroll_meta, epoch)
        _pending_drawings[device_token] = [item]
        _active_drawing_devices.add(device_token)
        if device_token not in _drawing_workers:
            _drawing_workers.add(device_token)
            start_worker = True
    logger.info(
        f"[ASYNC_DRAW_BG] Latest-only queue '{subject}' epoch={epoch} "
        f"scroll={scroll_meta.get('scroll_id')} seq={scroll_meta.get('seq')}"
    )
    if start_worker:
        asyncio.create_task(_process_device_drawing_queue(device_token))


async def _process_device_drawing_queue(device_token: str):
    try:
        while True:
            async with _drawing_meta_lock:
                pending = _pending_drawings.get(device_token) or []
                if not pending:
                    break
                fusion_input, text_response, drawing_prompt, scroll_meta, epoch = pending.pop(0)
            await _run_one_background_drawing(
                fusion_input, device_token, text_response, drawing_prompt, scroll_meta, epoch
            )
    finally:
        restart = False
        async with _drawing_meta_lock:
            if _pending_drawings.get(device_token):
                restart = True
            else:
                _drawing_workers.discard(device_token)
                _active_drawing_devices.discard(device_token)
                _pending_drawings.pop(device_token, None)
        if restart:
            asyncio.create_task(_process_device_drawing_queue(device_token))


async def _run_one_background_drawing(
    fusion_input: str,
    device_token: str,
    text_response: str,
    drawing_prompt: str,
    scroll_meta: Optional[Dict[str, Any]] = None,
    epoch: int = 0,
):
    subject = (drawing_prompt or "").strip() or (fusion_input or "").strip()
    draw_start = time.time()
    try:
        async with _DRAWING_SEMAPHORE:
            async with _drawing_meta_lock:
                if _draw_epoch.get(device_token) != epoch:
                    logger.info(f"[ASYNC_DRAW_BG] Skip stale epoch={epoch} for '{subject}'")
                    return
            logger.info(f"[ASYNC_DRAW_BG] 🎨 Background drawing started for: '{subject}' (token: {device_token})")
            action = await _execute_drawing_with_fusion(
                subject, device_token, text_response, scroll_meta=scroll_meta, epoch=epoch
            )
            draw_duration = time.time() - draw_start
            if action:
                logger.info(f"[ASYNC_DRAW_BG] ✅ Drawing {action.get('job_id')} ready for screen preview in {draw_duration:.2f}s (await user Print button)")
            else:
                logger.warning(f"[ASYNC_DRAW_BG] ⚠️ Drawing finished with no action returned ({draw_duration:.2f}s)")
    except Exception as e:
        logger.error(f"[ASYNC_DRAW_BG] ❌ Drawing generation failed in background: {e}")


async def _background_drawing_and_record(
    fusion_input: str,
    device_token: str,
    text_response: str,
    drawing_prompt: str
):
    """Background task: generate Seedream line art and save as status=ready (screen preview). Does NOT auto-print."""
    await _enqueue_background_drawing(fusion_input, device_token, text_response, drawing_prompt)


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
    scroll_meta: Optional[Dict[str, Any]] = None,
    epoch: int = 0,
) -> Optional[Dict[str, Any]]:
    """One square create-image from the accumulated draft. New draw replaces the previous ready job."""
    context = ConversationManager.get_conversation_context(device_token)
    if context is None:
        context = _default_conversation_context(device_token)

    fused_prompt = (user_text or "").strip()
    fusion_result = {
        "fused_prompt": fused_prompt,
        "operation": "create",
        "target_element": fused_prompt,
        "all_elements_after": [fused_prompt] if fused_prompt else [],
    }
    logger.info(f"[DRAWING] Square create prompt: '{fused_prompt}'")

    meta = scroll_meta or _scroll_meta_for_device(device_token)
    action = await async_generate_drawing_with_fusion(
        fused_prompt,
        device_token,
        fusion_result,
        seed=meta.get("seed"),
        scroll_id=meta.get("scroll_id"),
        seq=meta.get("seq"),
        epoch=epoch,
    )
    if not action:
        return None

    latest = ConversationManager.get_conversation_context(device_token) or dict(context)
    updated_ctx = ConversationContextManager.update_context_after_fusion(
        dict(latest),
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
    ask_to_draw: bool = False,
    draft_prompt: str = "",
) -> tuple:
    """
    Resolve user dialog via Doubao:
    - bytes: STT → unified_text_chat
    - str: unified_text_chat
    Sync SDK calls run in asyncio.to_thread so /drawings/ready etc. stay responsive.
    Returns (res_data, stt_duration, llm_duration).
    """
    doubao = DoubaoAPI.get_instance()
    stt_duration = 0.0
    llm_duration = 0.0
    res_data = None

    if isinstance(prompt_input, bytes):
        stt_start = time.time()
        user_text = await asyncio.to_thread(doubao.transcribe_audio, prompt_input)
        stt_duration = time.time() - stt_start
        logger.info(f"[STT] Audio transcribed in {stt_duration:.2f}s. Result: '{user_text}'")

        if user_text:
            llm_start = time.time()
            try:
                res_data = await asyncio.to_thread(
                    doubao.unified_text_chat, user_text, history, ask_to_draw, draft_prompt
                )
            except Exception as text_err:
                logger.warning(f"[DOUBAO] unified_text_chat after STT failed: {text_err}")
            llm_duration = time.time() - llm_start

        if not res_data:
            res_data = (
                _dialog_unavailable_response(user_text)
                if user_text
                else _empty_audio_response()
            )
    else:
        llm_start = time.time()
        try:
            res_data = await asyncio.to_thread(
                doubao.unified_text_chat, prompt_input, history, ask_to_draw, draft_prompt
            )
        except Exception as text_err:
            logger.warning(f"[DOUBAO] unified_text_chat failed: {text_err}")
        llm_duration = time.time() - llm_start
        if not res_data:
            res_data = _dialog_unavailable_response(str(prompt_input or ""))

    return res_data, stt_duration, llm_duration


def _local_followup_payload(draft_prompt: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    follow = _followup_question(draft_prompt, history)
    return {
        "user_transcript": "",
        "assistant_reply": follow,
        "requires_drawing": False,
        "drawing_prompt": draft_prompt or "",
        "psych_metrics": {},
    }


async def process_llm_interaction(
    prompt_input: Any,
    api_key: str = None,
    device_token: str = None,
    silent: bool = False,
) -> Dict[str, Any]:
    start_time = time.time()
    stt_duration = 0.0
    llm_duration = 0.0
    tts_duration = 0.0

    device_token = device_token or "anonymous_device"
    doubao = DoubaoAPI.get_instance()
    llm_cache = LLMCacheManager.get_instance()

    if not doubao.client:
        raise HTTPException(status_code=500, detail="ARK_API_KEY is not configured")

    context = ConversationManager.get_conversation_context(device_token)
    if context is None:
        context = _default_conversation_context(device_token)

    message_history = list(context.get("message_history", []))
    turn_count = len(message_history) + 1
    draft_prompt = (context.get("draft_prompt") or "").strip()
    last_ai = ((message_history[-1].get("ai_response") if message_history else "") or "")
    invited_to_draw = any(k in last_ai for k in ("画出来", "要不要画", "想不想画", "帮你画"))

    try:
        logger.info(
            f"[CORE] Doubao pipeline token={device_token} turn={turn_count} "
            f"silent={silent} draft='{draft_prompt[:40]}'"
        )

        res_data = None
        if silent:
            if message_history:
                res_data = _local_followup_payload(draft_prompt, message_history)
                logger.info("[CORE] Silent turn → context follow-up (no LLM)")
            else:
                res_data = _empty_audio_response()
        else:
            spoken = prompt_input if isinstance(prompt_input, str) else ""
            if isinstance(prompt_input, bytes):
                stt_start = time.time()
                spoken = await asyncio.to_thread(doubao.transcribe_audio, prompt_input)
                stt_duration = time.time() - stt_start
                logger.info(f"[STT] Audio transcribed in {stt_duration:.2f}s. Result: '{spoken}'")

            skip_llm = (
                bool(message_history)
                and _is_thinking_utterance(spoken)
                and not invited_to_draw
                and not _has_explicit_draw_intent(spoken)
                and not _is_print_intent(spoken)
            )
            if skip_llm:
                res_data = _local_followup_payload(draft_prompt, message_history)
                res_data["user_transcript"] = spoken or ""
                logger.info(f"[CORE] Thinking utterance '{spoken}' → follow-up (no LLM)")
            elif not spoken and isinstance(prompt_input, bytes):
                res_data = (
                    _local_followup_payload(draft_prompt, message_history)
                    if message_history
                    else _empty_audio_response()
                )
            else:
                dialog_result = await _resolve_doubao_dialog(
                    spoken or prompt_input, llm_cache,
                    history=message_history,
                    ask_to_draw=bool(draft_prompt) and turn_count >= 4 and turn_count % 4 == 0,
                    draft_prompt=draft_prompt,
                )
                res_data, _stt, llm_duration = dialog_result
                if not res_data.get("user_transcript"):
                    res_data["user_transcript"] = spoken

        if res_data:
            user_text = res_data.get("user_transcript", "") or (
                prompt_input if isinstance(prompt_input, str) else ""
            )
            if silent:
                user_text = ""

            text_response = res_data.get("assistant_reply", "")
            requires_drawing = parse_bool(res_data.get("requires_drawing", False)) or parse_bool(res_data.get("requires_painting", False))
            drawing_prompt = res_data.get("drawing_prompt", "") or res_data.get("painting_prompt", "")
            psych_metrics = res_data.get("psych_metrics", {}) or {}

            requires_drawing, drawing_prompt = _apply_drawing_heuristics(
                user_text, text_response, requires_drawing, drawing_prompt,
                psych_metrics, device_token,
            )

            print_action = None
            if _is_print_intent(user_text):
                requires_drawing = False
                print_action = _handle_voice_print(device_token)
                text_response = print_action.get("message") or text_response
            elif requires_drawing:
                if _is_complete_draw_command(user_text) and draft_prompt:
                    drawing_prompt = draft_prompt
                drawing_prompt = _merge_draft_prompt(draft_prompt, drawing_prompt) or drawing_prompt
                if text_response and "打印" not in text_response:
                    text_response = text_response.rstrip("。！!? ") + "。画好了看屏幕，点打印就能出纸。"
            else:
                drawing_prompt = _merge_draft_prompt(draft_prompt, drawing_prompt)

            draft_prompt = drawing_prompt or draft_prompt

            logger.info(
                f"[DOUBAO] Transcript='{user_text}' Reply='{text_response}' "
                f"Draw={requires_drawing} draft='{draft_prompt}'"
            )

            voice_config = get_device_settings(device_token)

            tts_task = None
            tts_start = time.time()
            if text_response:
                tts_task = asyncio.create_task(
                    asyncio.to_thread(doubao.generate_speech, text_response, voice_config)
                )

            action_preview = print_action
            if requires_drawing and (drawing_prompt or user_text):
                fusion_input = drawing_prompt or user_text
                asyncio.create_task(
                    _enqueue_background_drawing(fusion_input, device_token, text_response, drawing_prompt)
                )
                scroll_id, seed = ConversationManager.ensure_scroll(device_token)
                action_preview = {
                    "type": "draw",
                    "status": "generating",
                    "prompt": drawing_prompt or fusion_input,
                    "message": "画作生成中，完成后请在屏幕点击打印按钮出纸",
                    "scroll_id": scroll_id,
                    "seed": seed,
                }

            new_msg = {
                "timestamp": time.time(),
                "user_text": user_text,
                "ai_response": text_response,
                "drawing_triggered": requires_drawing,
                "drawing_prompt": drawing_prompt or None,
            }
            message_history.append(new_msg)
            context["message_history"] = message_history[-20:]
            context["draft_prompt"] = draft_prompt
            ConversationManager.create_or_update_conversation_context(device_token, context)

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

            return {
                "text_response": text_response,
                "action": action_preview,
                "audio_base64": audio_base64,
                "stt_empty": False if user_text else True,
                "requires_drawing": requires_drawing,
                "device_token": device_token,
                "turn_count": turn_count,
                "draft_prompt": draft_prompt,
            }

    except Exception as pipeline_err:
        logger.error(f"[DOUBAO] Pipeline failed: {pipeline_err}")
        raise HTTPException(status_code=500, detail=f"Voice/chat processing failed: {pipeline_err}")


async def archive_after_print(device_token: str, job: Optional[Dict[str, Any]] = None):
    """Run embedding / psych archive only after the child finished printing."""
    if not device_token:
        return
    context = ConversationManager.get_conversation_context(device_token) or {}
    history = context.get("message_history") or []
    parts = []
    for msg in history[-12:]:
        u = (msg or {}).get("user_text") or ""
        a = (msg or {}).get("ai_response") or ""
        if u:
            parts.append(f"孩子: {u}")
        if a:
            parts.append(f"探奇: {a}")
    prompt = (job or {}).get("prompt") or context.get("draft_prompt") or ""
    if prompt:
        parts.append(f"画作: {prompt}")
    child_text = "\n".join(parts) or (job or {}).get("prompt") or "一次绘画对话"
    await _background_save_psych_vector(
        device_token=device_token,
        child_text=child_text[:2000],
        ai_response="打印完成，本轮对话归档",
        psych_metrics={"archive": "after_print"},
        drawing_prompt=prompt or None,
    )

