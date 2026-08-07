import asyncio
import json
import uuid
import time
from fastapi import APIRouter, Request, HTTPException, Response, Query, Body
from fastapi.responses import StreamingResponse
from typing import Optional
from urllib.parse import unquote
from src.schemas import ChatRequest, TTSRequest
from src.config import DEEPSEEK_API_KEY
from src.crud import get_print_jobs_from_db, delete_print_job_from_db, save_print_job_to_db
from src.services import VoiceInteractionService, DeepSeekAPI
from src.business_logic import (
    process_llm_interaction, stream_chat_llm, async_generate_drawing, extract_drawing_subject
)
from src.cache import DrawingCacheManager
from src.logger import setup_logger

logger = setup_logger("routes.device")
router = APIRouter()

@router.post("/api/device/v1/chat")
@router.post("/api/v1/chat")
async def handle_chat(req: ChatRequest, request: Request, stream: Optional[bool] = Query(True)):
    token = request.headers.get("x-device-token") or request.headers.get("authorization") or "anonymous_device"
    ua = request.headers.get("user-agent")
    accept_header = request.headers.get("accept", "")
    logger.debug(f"[CONN] Incoming chat request from UA: {ua}, Token: {token[:5] if token else 'None'}***")

    # If stream parameter is explicitly false or Accept header is JSON-only
    if stream is False or ("application/json" in accept_header and "text/event-stream" not in accept_header):
        res = await process_llm_interaction(req.text, DEEPSEEK_API_KEY, device_token=token)
        return res

    user_text = req.text.strip() if req.text else ""
    if not user_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    async def event_generator():
        drawing_keywords = ["画", "画画", "画一个", "画一只", "画一架", "画辆", "画朵", "画条", "画张", "画一幅", "画个", "画出", "画一画", "想要画", "帮我画", "可以画"]
        user_text_lower = user_text.lower()
        should_draw = any(kw in user_text_lower for kw in drawing_keywords)

        drawing_task = None
        action_result = None

        if should_draw:
            subject = extract_drawing_subject(user_text)
            if not subject or subject in ["画", "画画", "画图", "一幅画", "一幅", "画个"]:
                subject = "小猫"

            logger.debug(f"[CHAT_SSE] Drawing request detected for prompt: '{subject}'")
            # 0ms Redis / Memory Cache Check
            cache_mgr = DrawingCacheManager.get_instance()
            cached_action = cache_mgr.get(subject)
            if cached_action:
                logger.debug(f"[CHAT_SSE] 0ms Cache Hit for prompt: '{subject}'")
                job_id = str(uuid.uuid4())
                action_result = {
                    "type": "draw",
                    "prompt": subject,
                    "job_id": job_id,
                    "image_url": cached_action.get("image_url"),
                    "bitmap_hex": cached_action.get("bitmap_hex")
                }
                save_print_job_to_db({
                    "job_id": job_id,
                    "image_url": cached_action.get("image_url"),
                    "bitmap_hex": cached_action.get("bitmap_hex"),
                    "prompt": subject,
                    "timestamp": time.time()
                })
            else:
                logger.debug(f"[CHAT_SSE] Launching async parallel drawing task for prompt: '{subject}'")
                drawing_task = asyncio.create_task(async_generate_drawing(subject, token))

        # Stream LLM text output token-by-token
        try:
            async for chunk in stream_chat_llm(user_text):
                safe_chunk = chunk.replace("\n", " ")
                yield f"data: {safe_chunk}\n\n"
        except Exception as stream_err:
            logger.error(f"[CHAT_SSE] Text streaming error: {stream_err}")

        # Wait for parallel drawing generation if triggered
        if drawing_task:
            try:
                action_result = await drawing_task
            except Exception as task_err:
                logger.error(f"[CHAT_SSE] Async drawing task error: {task_err}")
                action_result = None

        # Yield final action payload in the last SSE data frame
        final_payload = {
            "action": action_result
        }
        yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        }
    )

@router.post("/api/device/v1/voice")
async def handle_voice(request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    logger.debug(f"[CONN] Incoming voice request from UA: {ua}, Token: {token[:5] if token else 'None'}***")
    if not token:
        logger.warning("[CONN] Unauthorized voice attempt: missing x-device-token")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    if not DEEPSEEK_API_KEY:
        logger.error("[VOICE] Internal Server Error: API key missing")
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    voice_service = VoiceInteractionService.get_instance()
    voice_service.clear_buffer(token)
    
    try:
        # Stream the incoming audio chunks in real-time to minimize transport latency
        async for chunk in request.stream():
            if chunk:
                voice_service.append_chunk(token, chunk)
                
        audio_bytes = voice_service.get_full_audio(token)
        logger.debug(f"[VOICE] Streaming buffer complete. Total size: {len(audio_bytes)} bytes")
        
        if not audio_bytes or len(audio_bytes) < 10:
            logger.warning("[VOICE] Bad Request: empty or extremely small body")
            raise HTTPException(status_code=400, detail="Empty audio body received")
            
        res = await process_llm_interaction(audio_bytes, DEEPSEEK_API_KEY, device_token=token)
        logger.debug(f"[VOICE] Response generated: {res.get('text_response')[:50]}...")
        return res
    except Exception as e:
        logger.error(f"[VOICE] Server Error during processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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


@router.post("/api/v1/tts", summary="云端 TTS 语音合成 (POST 方式)")
@router.post("/api/device/v1/tts", summary="云端 TTS 语音合成 (POST 方式)")
async def tts_post_endpoint(req: TTSRequest, request: Request):
    ua = request.headers.get("user-agent")
    token = request.headers.get("x-device-token") or request.headers.get("authorization")
    logger.debug(f"[TTS POST] Request from UA: {ua}, Token present: {bool(token)}")
    
    text = req.text.strip() if req.text else ""
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    deepseek = DeepSeekAPI.get_instance()
    
    voice_config = req.voice
    if req.voice == "child_friendly" or not req.voice or req.voice == "default":
        voice_config = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
    elif req.voice == "teacher_female":
        voice_config = "一位温柔、知性、亲切的幼儿园女老师"
        
    try:
        audio_bytes = deepseek.generate_speech_bytes(text, voice_name=voice_config)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS generation returned empty audio")

        logger.debug(f"[TTS POST] Successfully generated audio, size: {len(audio_bytes)} bytes")
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=tts.mp3",
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TTS POST] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"TTS Engine Error: {str(e)}")


@router.get("/api/v1/tts", summary="云端 TTS 语音合成 (GET 容错方式)")
@router.get("/api/device/v1/tts", summary="云端 TTS 语音合成 (GET 容错方式)")
async def tts_get_endpoint(
    request: Request,
    text: str = Query(..., description="待朗读的中文文本"),
    voice: str = Query("default", description="音色选择"),
    speed: float = Query(1.0, description="语速，范围 0.5-2.0")
):
    ua = request.headers.get("user-agent")
    token = request.headers.get("x-device-token") or request.headers.get("authorization")
    logger.debug(f"[TTS GET] Request from UA: {ua}, Token present: {bool(token)}")
    
    decoded_text = unquote(text).strip()
    if not decoded_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
        
    # 对 GET 超长文本进行安全截断 (防止引发上游引擎崩溃)
    if len(decoded_text) > 150:
        decoded_text = decoded_text[:150]
        
    deepseek = DeepSeekAPI.get_instance()
    
    voice_config = voice
    if voice == "child_friendly" or not voice or voice == "default":
        voice_config = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
    elif voice == "teacher_female":
        voice_config = "一位温柔、知性、亲切的幼儿园女老师"

    try:
        audio_bytes = deepseek.generate_speech_bytes(decoded_text, voice_name=voice_config)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS GET Error: returned empty audio")

        logger.debug(f"[TTS GET] Successfully generated audio, size: {len(audio_bytes)} bytes")
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=tts.mp3",
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TTS GET] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"TTS GET Error: {str(e)}")


