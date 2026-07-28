from fastapi import APIRouter, Request, HTTPException, Response, Query, Body
from typing import Optional
from src.schemas import ChatRequest, TTSRequest
from src.config import DEEPSEEK_API_KEY
from src.crud import get_print_jobs_from_db, delete_print_job_from_db
from src.services import VoiceInteractionService, DeepSeekAPI
from src.business_logic import process_llm_interaction
from src.logger import setup_logger

logger = setup_logger("routes.device")
router = APIRouter()

@router.post("/api/device/v1/chat")
async def handle_chat(req: ChatRequest, request: Request):
    token = request.headers.get("x-device-token")
    ua = request.headers.get("user-agent")
    logger.debug(f"[CONN] Incoming chat request from UA: {ua}, Token: {token[:5] if token else 'None'}***")
    if not token:
        logger.warning("[CONN] Unauthorized chat attempt: missing x-device-token")
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    logger.debug(f"[CHAT] Text length: {len(req.text)} chars")
    if not DEEPSEEK_API_KEY:
        logger.error("[CHAT] Internal Server Error: API key missing")
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY or API_KEY is missing")
        
    res = await process_llm_interaction(req.text, DEEPSEEK_API_KEY, device_token=token)
    logger.debug(f"[CHAT] Response generated: {res.get('text_response')[:50]}...")
    return res

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


@router.get("/api/v1/tts")
@router.post("/api/v1/tts")
@router.get("/api/device/v1/tts")
@router.post("/api/device/v1/tts")
async def courseware_tts_stream(
    request: Request,
    text: Optional[str] = Query(None, description="待朗读的中文文本"),
    voice: Optional[str] = Query(None, description="发音人类型"),
    speed: Optional[float] = Query(1.0, description="语速"),
    body: Optional[TTSRequest] = None
):
    ua = request.headers.get("user-agent")
    token = request.headers.get("x-device-token") or request.headers.get("authorization")
    logger.debug(f"[TTS] Incoming TTS request from UA: {ua}, Token present: {bool(token)}")
    
    req_text = text
    req_voice = voice
    req_speed = speed
    
    if not req_text and body:
        req_text = body.text
        if body.voice:
            req_voice = body.voice
        if body.speed is not None:
            req_speed = body.speed
            
    if not req_text:
        raise HTTPException(status_code=400, detail="Missing required 'text' parameter or body field.")
        
    deepseek = DeepSeekAPI.get_instance()
    
    voice_config = req_voice
    if req_voice == "child_friendly" or not req_voice:
        voice_config = "一个极其温柔、友好、可爱的5岁小朋友，用稚嫩温和的语气说话"
    elif req_voice == "teacher_female":
        voice_config = "一位温柔、知性、亲切的幼儿园女老师"
        
    try:
        audio_bytes = deepseek.generate_speech_bytes(req_text, voice_name=voice_config)
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS generation failed or returned empty audio.")
            
        logger.debug(f"[TTS] Successfully generated audio stream, size: {len(audio_bytes)} bytes")
        return Response(content=audio_bytes, media_type="audio/mpeg", headers={
            "Content-Disposition": "inline; filename=tts.mp3",
            "Cache-Control": "public, max-age=86400"
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[TTS] Error generating TTS stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))

