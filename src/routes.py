import os
import time
import uuid
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.config import DEEPSEEK_API_KEY, ADMIN_KEY
from src.database import (
    save_history_to_db, get_history_from_db,
    save_feedback_to_db, save_print_job_to_db, get_print_jobs_from_db, delete_print_job_from_db,
    save_psych_vector, query_psych_vectors
)
from src.utils import (
    process_line_art_image, get_raw_bitmap_hex, get_embedded_bitmap, get_image_metadata
)
from src.services import (
    DeepSeekAPI, DoubaoAPI, ReplicateAPI, IdeogramAPI, generate_image_with_fallback,
    CACHE_FILE, STT_CACHE_FILE, TTS_CACHE_FILE
)

router = APIRouter()

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

class ChatRequest(BaseModel):
    text: str


def similarity_search_vectors(device_token: str, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    import numpy as np
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


async def process_llm_interaction(prompt_input: Any, api_key: str, device_token: str = None) -> Dict[str, Any]:
    start_time = time.time()
    device_token = device_token or "anonymous_device"
    doubao = DoubaoAPI()
    deepseek = DeepSeekAPI()
    
    # Check if Doubao client is configured
    if doubao.client:
        try:
            print(f"[DEBUG] [CORE] Attempting Doubao unified pipeline for token: {device_token}...")
            if isinstance(prompt_input, bytes):
                res_data = doubao.unified_audio_chat(prompt_input)
            else:
                res_data = doubao.unified_text_chat(prompt_input)
                
            if res_data:
                user_text = res_data.get("user_transcript", "")
                text_response = res_data.get("assistant_reply", "")
                requires_drawing = res_data.get("requires_drawing", False) or res_data.get("requires_painting", False)
                drawing_prompt = res_data.get("drawing_prompt", "") or res_data.get("painting_prompt", "")
                psych_metrics = res_data.get("psych_metrics", {})
                
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
                        audio_base64 = deepseek.generate_speech(text_response)
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
            import traceback
            traceback.print_exc()

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
                audio_base64 = deepseek.generate_speech(error_msg)
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
                    
        if not text_response:
            text_response = "我没听清，请再说一遍。"
            
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


@router.post("/api/generate")
async def generate_drawing(req: GenerateRequest):
    replicate_api = ReplicateAPI()
    
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
            if cached_metadata and i < len(cached_metadata) and cached_metadata[i]:
                image_metadata.append(cached_metadata[i])
            else:
                image_metadata.append(get_image_metadata(url))
        else:
            image_metadata.append(None)
            
        if req.apply_line_art:
            processed_images.append(process_line_art_image(url, apply_filter=True))
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

@router.post("/api/feedback")
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

@router.get("/api/history")
async def get_history(limit: int = 50):
    return get_history_from_db(limit)

@router.post("/api/device/v1/chat")
async def handle_chat(req: ChatRequest, request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    print(f"[DEBUG] [CONN] Incoming chat request from UA: {ua}, Token: {token[:5] if token else 'None'}***")
    if not token:
        print("[WARNING] [CONN] Unauthorized chat attempt: missing x-device-token")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    print(f"[DEBUG] [CHAT] Text length: {len(req.text)} chars")
    if not DEEPSEEK_API_KEY:
        print("[ERROR] [CHAT] Internal Server Error: API key missing")
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    res = await process_llm_interaction(req.text, DEEPSEEK_API_KEY, device_token=token)
    print(f"[DEBUG] [CHAT] Response generated: {res.get('text_response')[:50]}...")
    return res

@router.post("/api/device/v1/voice")
async def handle_voice(request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    print(f"[DEBUG] [CONN] Incoming voice request from UA: {ua}, Token: {token[:5] if token else 'None'}***")
    if not token:
        print("[WARNING] [CONN] Unauthorized voice attempt: missing x-device-token")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    body = await request.body()
    if not body:
        print("[WARNING] [VOICE] Bad Request: empty body")
        raise HTTPException(status_code=400, detail="Empty audio body received")
    
    print(f"[DEBUG] [VOICE] Audio binary size: {len(body)} bytes")
    if not DEEPSEEK_API_KEY:
        print("[ERROR] [VOICE] Internal Server Error: API key missing")
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    res = await process_llm_interaction(body, DEEPSEEK_API_KEY, device_token=token)
    print(f"[DEBUG] [VOICE] Response generated: {res.get('text_response')[:50]}...")
    return res

@router.get("/api/device/v1/print-jobs")
async def get_print_jobs(request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    
    if not token:
        print(f"[WARNING] [CONN] Unauthorized polling attempt from UA: {ua}")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    jobs = get_print_jobs_from_db()
    if jobs:
        job = jobs[0]
        print(f"[DEBUG] [PRINT] Job found: {job.get('job_id')} for prompt: '{job.get('prompt')}'")
        return {
            "has_job": True,
            **job
        }
    return {"has_job": False}

@router.post("/api/device/v1/print-jobs/{job_id}/complete")
async def complete_print_job(job_id: str, request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    print(f"[DEBUG] [CONN] Complete job request: {job_id} from UA: {ua}, Token: {token[:5] if token else 'None'}***")
    
    if not token:
        print(f"[WARNING] [CONN] Unauthorized complete job attempt for {job_id}")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    try:
        delete_print_job_from_db(job_id)
        print(f"[DEBUG] [PRINT] Job {job_id} marked as complete and deleted.")
        return {
            "success": True,
            "message": "Print job completed successfully",
            "job_id": job_id,
            "status": "finished"
        }
    except Exception as e:
        print(f"[ERROR] [PRINT] Failed to complete job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete job from database")

@router.post("/api/admin/clear-cache")
async def clear_cache(request: Request):
    admin_key = ADMIN_KEY
    if admin_key:
        auth_header = request.headers.get("Authorization")
        if auth_header != f"Bearer {admin_key}":
            raise HTTPException(status_code=403, detail="Forbidden")
            
    # We can clean import variables or delete files
    from src.services import IMAGE_CACHE, STT_CACHE, TTS_CACHE
    IMAGE_CACHE.clear()
    STT_CACHE.clear()
    TTS_CACHE.clear()
    
    for f_path in [CACHE_FILE, STT_CACHE_FILE, TTS_CACHE_FILE]:
        if os.path.exists(f_path):
            os.remove(f_path)
            
    print("All caches cleared manually.")
    return {"status": "success", "message": "All caches cleared"}

@router.get("/api/admin/reports/{device_token}")
async def get_admin_report(device_token: str):
    data = generate_growths_summary(device_token)
    
    # Render Trend SVG
    trend_svg = ""
    trend_points = data.get("linguistic_trend", [])
    if trend_points:
        svg_width = 600
        svg_height = 200
        padding = 40
        num_points = len(trend_points)
        
        x_step = (svg_width - 2 * padding) / max(1, num_points - 1)
        points_str = []
        dots = []
        for idx, pt in enumerate(trend_points):
            x = padding + idx * x_step
            y = svg_height - padding - (pt["score"] / 100.0) * (svg_height - 2 * padding)
            points_str.append(f"{x},{y}")
            dots.append(f'<circle cx="{x}" cy="{y}" r="5" class="fill-indigo-600 stroke-white stroke-2 hover:r-7 transition-all cursor-pointer" title="{pt["time"]}: {pt["score"]}%"/>')
            
        path_d = f"M {points_str[0]}" + " " + " ".join([f"L {p}" for p in points_str[1:]]) if points_str else ""
        
        grid_lines = []
        for val in [0, 25, 50, 75, 100]:
            y = svg_height - padding - (val / 100.0) * (svg_height - 2 * padding)
            grid_lines.append(f'<line x1="{padding}" y1="{y}" x2="{svg_width-padding}" y2="{y}" stroke="#e5e7eb" stroke-dasharray="4"/>')
            grid_lines.append(f'<text x="{padding-10}" y="{y+4}" font-size="10" fill="#9ca3af" text-anchor="end">{val}%</text>')
            
        for idx, pt in enumerate(trend_points):
            x = padding + idx * x_step
            grid_lines.append(f'<text x="{x}" y="{svg_height - padding + 20}" font-size="10" fill="#9ca3af" text-anchor="middle">{pt["time"]}</text>')
            
        trend_svg = f"""
        <svg viewBox="0 0 {svg_width} {svg_height}" class="w-full h-auto">
            {"".join(grid_lines)}
            <path d="{path_d}" fill="none" stroke="url(#gradient)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
            {"".join(dots)}
            <defs>
                <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#4f46e5" />
                    <stop offset="100%" stop-color="#ec4899" />
                </linearGradient>
            </defs>
        </svg>
        """
    else:
        trend_svg = """
        <div class="flex items-center justify-center h-48 bg-gray-50 rounded-xl border border-dashed border-gray-200">
            <span class="text-gray-400 text-sm">暂无言语丰富度发展走势数据</span>
        </div>
        """
        
    emotion_html = ""
    for emotion, count in data.get("emotions", []):
        color_classes = "bg-indigo-50 text-indigo-700 border-indigo-200"
        if emotion in ["悲伤", "焦虑", "分离焦虑"]:
            color_classes = "bg-rose-50 text-rose-700 border-rose-200"
        elif emotion in ["愤怒"]:
            color_classes = "bg-amber-50 text-amber-700 border-amber-200"
        elif emotion in ["好奇", "快乐"]:
            color_classes = "bg-emerald-50 text-emerald-700 border-emerald-200"
            
        emotion_html += f"""
        <span class="inline-flex items-center px-4 py-2 rounded-full text-sm font-semibold border {color_classes} shadow-sm transition-all hover:scale-105 duration-200">
            {emotion}
            <span class="ml-2 bg-white/60 px-1.5 py-0.5 rounded-full text-xs font-bold">{count}次</span>
        </span>
        """
        
    interest_html = ""
    colors_pool = [
        "bg-pink-50 text-pink-700 border-pink-200",
        "bg-purple-50 text-purple-700 border-purple-200",
        "bg-blue-50 text-blue-700 border-blue-200",
        "bg-teal-50 text-teal-700 border-teal-200",
        "bg-yellow-50 text-yellow-700 border-yellow-200",
        "bg-orange-50 text-orange-700 border-orange-200"
    ]
    for idx, (interest, count) in enumerate(data.get("interests", [])):
        color = colors_pool[idx % len(colors_pool)]
        interest_html += f"""
        <span class="inline-flex items-center px-3.5 py-1.5 rounded-xl text-sm font-semibold border {color} shadow-sm transition-all hover:scale-105 duration-200">
            🔍 {interest} ({count}次)
        </span>
        """
        
    if not emotion_html:
        emotion_html = '<span class="text-gray-400 text-sm">暂无识别的情绪特征</span>'
    if not interest_html:
        interest_html = '<span class="text-gray-400 text-sm">暂无提取的兴趣主题</span>'
        
    drawings_html = ""
    for d in data.get("drawings", []):
        drawings_html += f"""
        <div class="bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-300">
            <div class="aspect-square bg-gray-50 flex items-center justify-center p-2">
                <img src="{d['url']}" class="max-h-full max-w-full object-contain rounded-lg" alt="{d['prompt']}"/>
            </div>
            <div class="p-4">
                <p class="font-semibold text-gray-800 text-sm mb-1 truncate">{d['prompt']}</p>
                <span class="text-xs text-gray-400">{time.strftime('%Y-%m-%d %H:%M', time.localtime(d['timestamp']))}</span>
            </div>
        </div>
        """
        
    if not drawings_html:
        drawings_html = """
        <div class="col-span-full flex flex-col items-center justify-center py-12 bg-gray-50 rounded-2xl border border-dashed border-gray-200 text-gray-400">
            <span class="text-3xl mb-2">🎨</span>
            <span class="text-sm">小朋友还没有使用绘画创作功能哦</span>
        </div>
        """

    alert_banner = ""
    if data.get("requires_attention_count", 0) > 0:
        alert_banner = f"""
        <div class="bg-red-50 border-l-4 border-red-500 p-4 rounded-xl mb-8 shadow-sm">
            <div class="flex items-start">
                <div class="flex-shrink-0 text-red-500 text-xl">⚠️</div>
                <div class="ml-3">
                    <h3 class="text-sm font-bold text-red-800">特别心理成长预警提示</h3>
                    <div class="mt-1 text-sm text-red-700">
                        在近期的交互中，共检测到 <span class="font-extrabold">{data['requires_attention_count']}次</span> 极度消极、焦虑或分离恐惧的情绪，建议家长及老师在日常生活中给予儿童更多的关怀、安全感支持，并耐心倾听其内心世界。
                    </div>
                </div>
            </div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>小探宝儿童成长与行为心理诊断报告</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght=400;600;700&family=Noto+Sans+SC:wght=400;500;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Quicksand', 'Noto Sans SC', sans-serif;
            }}
        </style>
    </head>
    <body class="bg-[#f8fafc] text-gray-800 min-h-screen">
        <div class="max-w-6xl mx-auto px-4 py-8">
            <!-- HEADER -->
            <div class="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-3xl p-8 md:p-12 text-white shadow-xl mb-8 relative overflow-hidden">
                <div class="absolute -right-10 -bottom-10 w-48 h-48 bg-white/10 rounded-full blur-2xl"></div>
                <div class="absolute -left-10 -top-10 w-48 h-48 bg-pink-500/20 rounded-full blur-2xl"></div>
                <div class="relative z-10">
                    <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-white/20 backdrop-blur-md text-white mb-4 border border-white/10">
                        🧸 智能玩偶成长分析报告
                    </span>
                    <h1 class="text-3xl md:text-5xl font-black mb-3 tracking-wide">小探宝成长行为心理诊断</h1>
                    <p class="text-white/80 text-sm md:text-base font-medium flex flex-wrap items-center gap-y-2 gap-x-4">
                        <span>设备令牌: <code class="bg-black/20 px-2 py-0.5 rounded font-mono text-white">{device_token}</code></span>
                        <span class="hidden md:inline">|</span>
                        <span>报告生成日期: {time.strftime('%Y-%m-%d %H:%M:%S')}</span>
                    </p>
                </div>
            </div>

            <!-- PRE_ALERT_BANNER -->
            {alert_banner}

            <!-- STATS COUNTERS -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex items-center space-x-4">
                    <div class="p-4 bg-indigo-50 text-indigo-500 rounded-xl text-2xl">💬</div>
                    <div>
                        <p class="text-xs font-bold text-gray-400 uppercase tracking-wider">对话交互记录</p>
                        <h3 class="text-2xl font-black text-gray-800">{data['total_interactions']} 次</h3>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex items-center space-x-4">
                    <div class="p-4 bg-emerald-50 text-emerald-500 rounded-xl text-2xl">📈</div>
                    <div>
                        <p class="text-xs font-bold text-gray-400 uppercase tracking-wider">言语丰富度均分</p>
                        <h3 class="text-2xl font-black text-gray-800">{data['linguistic_score_avg']}%</h3>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex items-center space-x-4">
                    <div class="p-4 bg-rose-50 text-rose-500 rounded-xl text-2xl">❤️</div>
                    <div>
                        <p class="text-xs font-bold text-gray-400 uppercase tracking-wider">特别关注与情绪预警</p>
                        <h3 class="text-2xl font-black text-gray-800">{data['requires_attention_count']} 次</h3>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
                <!-- CHART & TAGS -->
                <div class="lg:col-span-2 space-y-8">
                    <!-- LANGUAGE SCORE CHART -->
                    <div class="bg-white p-6 md:p-8 rounded-3xl border border-gray-100 shadow-sm">
                        <div class="flex items-center justify-between mb-6">
                            <div>
                                <h2 class="text-xl font-bold text-gray-800">言语发展与句子逻辑性走势</h2>
                                <p class="text-xs text-gray-400">最近十次儿童表达词汇丰富度及语法组织力评分走势</p>
                            </div>
                            <span class="text-xs font-bold bg-indigo-50 text-indigo-600 px-2.5 py-1 rounded-full">发展状态评估</span>
                        </div>
                        {trend_svg}
                    </div>

                    <!-- EMOTIONS & INTERESTS -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div class="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm">
                            <h2 class="text-lg font-bold text-gray-800 mb-4">心理状态特征分类统计</h2>
                            <div class="flex flex-wrap gap-2">
                                {emotion_html}
                            </div>
                        </div>
                        <div class="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm">
                            <h2 class="text-lg font-bold text-gray-800 mb-4">核心趣味探索主题分布</h2>
                            <div class="flex flex-wrap gap-2">
                                {interest_html}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PSYCH REPORT BLOCK -->
                <div class="lg:col-span-1 bg-white p-6 md:p-8 rounded-3xl border border-gray-100 shadow-sm flex flex-col h-full">
                    <div class="flex items-center space-x-3 mb-6">
                        <span class="p-2 bg-purple-50 text-purple-600 rounded-lg">🎓</span>
                        <h2 class="text-xl font-bold text-gray-800">专业测评与诊断意见</h2>
                    </div>
                    <div class="prose prose-sm text-gray-600 leading-relaxed overflow-y-auto max-h-[500px] flex-1 whitespace-pre-line border-t border-gray-100 pt-4">
                        {data['summary']}
                    </div>
                </div>
            </div>

            <!-- DRAWINGS WALL -->
            <div class="bg-white p-6 md:p-8 rounded-3xl border border-gray-100 shadow-sm mb-8">
                <div class="flex items-center justify-between mb-6">
                    <div>
                        <h2 class="text-xl font-bold text-gray-800">儿童数字手绘创作墙 (Seedream 5.0 pro)</h2>
                        <p class="text-xs text-gray-400">儿童通过语音命令让小探宝现场创作的简笔画，已自动通过 1-bit 排包算法推送到硬件端打印</p>
                    </div>
                    <span class="text-xs font-bold bg-pink-50 text-pink-600 px-2.5 py-1 rounded-full">作品展示</span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {drawings_html}
                </div>
            </div>
            
            <!-- FOOTER -->
            <div class="text-center text-gray-400 text-xs py-6">
                <p>© 2026 小探宝智能交互研究实验室. 保留所有权利。</p>
                <p class="mt-1">通过先进多模态大模型及向量数据库，提供科学非介入式的早期成长心理支持</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)
