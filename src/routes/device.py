import asyncio
import json
import time
from fastapi import APIRouter, Request, HTTPException, Response, Query, Body
from fastapi.responses import StreamingResponse
from typing import Optional
from urllib.parse import unquote
from src.schemas import ChatRequest, TTSRequest
from src.config import ARK_API_KEY, VOLC_REALTIME_API_KEY
from src.crud import (
    get_print_jobs_from_db,
    delete_print_job_from_db,
    get_ready_drawings_from_db,
    queue_print_job,
    get_print_job_by_id,
    get_jobs_for_scroll,
    queue_scroll_jobs,
)
from src.services import VoiceInteractionService, DoubaoAPI
from src.business_logic import (
    process_llm_interaction, is_device_drawing, archive_after_print
)
from src.logger import setup_logger
from src.conversation_crud import ConversationManager
from src.utils import is_silent_wav_audio

logger = setup_logger("routes.device")
router = APIRouter()

async def timeout_generator(gen, limit=20.0):
    try:
        start = time.time()
        iterator = gen.__aiter__()
        while True:
            elapsed = time.time() - start
            remaining = limit - elapsed
            if remaining <= 0:
                logger.warning("[CHAT_SSE] Total event generator timeout exceeded!")
                break
            try:
                item = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                yield item
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                logger.warning("[CHAT_SSE] Timeout waiting for next SSE chunk!")
                break
    except Exception as e:
        logger.error(f"[CHAT_SSE] Generator error: {e}")

@router.post("/api/device/v1/chat")
@router.post("/api/v1/chat")
async def handle_chat(req: ChatRequest, request: Request, stream: Optional[bool] = Query(False)):
    token = request.headers.get("x-device-token") or request.headers.get("authorization") or "anonymous_device"
    ua = request.headers.get("user-agent")
    accept_header = request.headers.get("accept", "")
    logger.debug(f"[CONN] Incoming chat request from UA: {ua}, Token: {token[:5] if token else 'None'}***")

    user_text = req.text.strip() if req.text else ""
    if not user_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    res = await process_llm_interaction(user_text, device_token=token)

    want_sse = stream is True or ("text/event-stream" in accept_header and stream is not False)
    if not want_sse:
        return res

    async def event_generator():
        text = (res.get("text_response") or "").replace("\n", " ")
        step = 12
        for i in range(0, max(len(text), 1), step):
            chunk = text[i:i + step] if text else " "
            yield f"data: {chunk}\n\n"
        yield f"data: {json.dumps({'action': res.get('action'), 'draft_prompt': res.get('draft_prompt'), 'requires_drawing': res.get('requires_drawing')}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        timeout_generator(event_generator(), limit=60.0),
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
        
    if not ARK_API_KEY:
        logger.error("[VOICE] Internal Server Error: ARK_API_KEY missing")
        raise HTTPException(status_code=500, detail="ARK_API_KEY is missing")
        
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

        if is_silent_wav_audio(audio_bytes):
            context = ConversationManager.get_conversation_context(token)
            has_history = bool((context or {}).get("message_history"))
            if not has_history:
                logger.info("[VOICE] Silent WAV with no chat yet token=%s", token[:5] + "***")
                raise HTTPException(
                    status_code=422,
                    detail="No audible speech detected. Please record again closer to the microphone.",
                )
            logger.info("[VOICE] Silent WAV → context follow-up token=%s", token[:5] + "***")
            res = await process_llm_interaction(audio_bytes, device_token=token, silent=True)
            return res

        res = await process_llm_interaction(audio_bytes, device_token=token)
        logger.debug(f"[VOICE] Response generated: {res.get('text_response')[:50]}...")
        return res
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VOICE] Server Error during processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/device/v1/drawings/ready")
async def get_ready_drawings(request: Request):
    """
    List drawings generated for this device that are waiting for the user to tap Print.
    Does NOT auto-print. Client should show preview on screen.
    """
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    drawings = get_ready_drawings_from_db(device_token=token)
    context = ConversationManager.get_conversation_context(token)
    return {
        "has_drawing": bool(drawings),
        "generating": is_device_drawing(token),
        "count": len(drawings),
        "drawings": drawings,
        "latest": drawings[-1] if drawings else None,
        "scroll_id": (context or {}).get("current_scroll_id"),
        "seed": (context or {}).get("current_seed"),
    }

@router.get("/api/device/v1/print-jobs")
async def get_print_jobs(request: Request):
    """
    Only returns jobs the user has confirmed via POST .../print (status=queued).
    Ready preview drawings are NOT returned here — use GET /drawings/ready.
    """
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    
    if not token:
        print(f"[WARNING] [CONN] Unauthorized polling attempt from UA: {ua}")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    jobs = get_print_jobs_from_db(device_token=token, status="queued")
    if jobs:
        job = jobs[0]
        print(f"[DEBUG] [PRINT] Queued job for device: {job.get('job_id')} prompt='{job.get('prompt')}'")
        return {
            "has_job": True,
            **job
        }
    return {"has_job": False}

@router.post("/api/device/v1/print-jobs/{job_id}/print")
async def confirm_print_job(job_id: str, request: Request):
    """
    User tapped the Print button on screen.
    Marks the ready drawing as queued and returns payload for the device printer.
    """
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    job = queue_print_job(job_id, device_token=token)
    if not job:
        raise HTTPException(status_code=404, detail="Drawing job not found or not owned by this device")

    logger.info(f"[PRINT] User confirmed print for job {job_id} token={token[:5]}***")
    return {
        "success": True,
        "has_job": True,
        "message": "Print confirmed. Device may now print this drawing.",
        **job
    }

@router.post("/api/device/v1/print-jobs/{job_id}/complete")
async def complete_print_job(job_id: str, request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    print(f"[DEBUG] [CONN] Complete job request: {job_id} from UA: {ua}, Token: {token[:5] if token else 'None'}***")
    
    if not token:
        print(f"[WARNING] [CONN] Unauthorized complete job attempt for {job_id}")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    try:
        job = get_print_job_by_id(job_id)
        delete_print_job_from_db(job_id)
        print(f"[DEBUG] [PRINT] Job {job_id} marked as complete and deleted.")
        asyncio.create_task(archive_after_print(token, job))
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
    
    doubao = DoubaoAPI.get_instance()
    
    voice_config = req.voice
    if req.voice == "child_friendly" or not req.voice or req.voice == "default":
        voice_config = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
    elif req.voice == "teacher_female":
        voice_config = "一位温柔、知性、亲切的幼儿园女老师"
        
    try:
        audio_bytes = doubao.generate_speech_bytes(text, voice_name=voice_config)
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
        
    doubao = DoubaoAPI.get_instance()
    
    voice_config = voice
    if voice == "child_friendly" or not voice or voice == "default":
        voice_config = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
    elif voice == "teacher_female":
        voice_config = "一位温柔、知性、亲切的幼儿园女老师"

    try:
        audio_bytes = doubao.generate_speech_bytes(decoded_text, voice_name=voice_config)
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


@router.get("/api/device/v1/conversation-history")
@router.get("/api/v1/conversation-history")
async def get_conversation_history(
    request: Request,
    limit: int = Query(20, ge=1, le=100)
):
    token = request.headers.get("x-device-token") or request.headers.get("authorization") or "anonymous_device"
    logger.debug(f"[API] Loading history for token: {token}")
    
    context = ConversationManager.get_conversation_context(token)
    if not context:
        return {
            "device_token": token,
            "scene_elements": [],
            "messages": []
        }
        
    messages = context.get("message_history", [])
    if limit:
        messages = messages[-limit:]
        
    return {
        "device_token": token,
        "scene_elements": context.get("scene_elements", []),
        "messages": messages
    }


@router.post("/api/device/v1/conversation-reset")
@router.post("/api/v1/conversation-reset")
async def reset_conversation(request: Request):
    token = request.headers.get("x-device-token") or request.headers.get("authorization") or "anonymous_device"
    logger.debug(f"[API] Resetting conversation for token: {token}")
    
    success = ConversationManager.delete_conversation_context(token, soft_delete=True)
    if success:
        return {
            "success": True,
            "message": "Conversation reset successfully",
            "device_token": token
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to reset conversation context")


@router.get("/api/device/v1/realtime-config")
@router.get("/api/v1/realtime-config")
async def get_realtime_config(request: Request):
    token = request.headers.get("x-device-token") or request.headers.get("authorization")
    if not token:
        raise HTTPException(status_code=401, detail="x-device-token header is required")
    
    # NEW CONSOLE (API Key method) - Seeduplex full-duplex realtime dialogue
    return {
        "success": True,
        "api_key": VOLC_REALTIME_API_KEY,
        "realtime_api_v3_duplex": {
            "url": "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue",
            "api_key": VOLC_REALTIME_API_KEY,
            "model": "1.2.6.1"
        }
    }


@router.post("/api/device/v1/scrolls/new")
async def start_new_scroll(request: Request):
    """Open a new related-image scroll (shared seed). Does not reset conversation."""
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = ConversationManager.start_new_scroll(token)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to start a new scroll")
    logger.info(f"[SCROLL] New scroll {result.get('scroll_id')} seed={result.get('seed')} token={token[:5]}***")
    return result


@router.get("/api/device/v1/scrolls/current")
async def get_current_scroll(request: Request):
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    scroll_id, seed = ConversationManager.ensure_scroll(token)
    images = get_jobs_for_scroll(scroll_id, device_token=token)
    return {
        "success": True,
        "scroll_id": scroll_id,
        "seed": seed,
        "images": images,
        "generating": is_device_drawing(token),
    }


@router.post("/api/device/v1/scrolls/{scroll_id}/print")
async def print_scroll(scroll_id: str, request: Request):
    """Queue every ready drawing on this scroll for thermal print, in seq order. No auto-print."""
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    queued = queue_scroll_jobs(scroll_id, token)
    if not queued:
        raise HTTPException(status_code=404, detail="No ready drawings on this scroll")
    logger.info(f"[SCROLL] Queued {len(queued)} drawings for print scroll={scroll_id} token={token[:5]}***")
    return {
        "success": True,
        "scroll_id": scroll_id,
        "count": len(queued),
        "jobs": queued,
        "message": "Scroll print confirmed. Device may now print these drawings in order.",
    }

