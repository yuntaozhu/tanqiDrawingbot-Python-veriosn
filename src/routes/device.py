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
    process_llm_interaction, stream_chat_llm, async_generate_drawing, extract_drawing_subject, async_generate_drawing_with_fusion
)
from src.cache import DrawingCacheManager
from src.logger import setup_logger
from src.conversation_crud import ConversationManager
from src.operation_recognizer import OperationRecognizer
from src.prompt_fusion import PromptFusionEngine, ConversationContextManager

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
        # Load or create conversation context
        logger.debug(f"[INTEGRATION] Loading context for token: {token}")
        context = ConversationManager.get_conversation_context(token)
        if context is None:
            context = {
                "device_token": token,
                "message_history": [],
                "current_image_url": None,
                "current_image_bitmap_hex": None,
                "scene_elements": [],
                "last_generated_prompt": None,
                "last_operation_type": None,
                "last_operation_detail": {},
                "created_at": None,
                "updated_at": None
            }
            logger.debug(f"[INTEGRATION] Created new context for token: {token}")
        else:
            logger.debug(f"[INTEGRATION] Loaded existing context for token: {token}")
            logger.debug(f"[INTEGRATION] Current scene elements: {context.get('scene_elements', [])}")
            logger.debug(f"[INTEGRATION] Message history count: {len(context.get('message_history', []))}")

        drawing_keywords = [
            "画", "画画", "画一个", "画一只", "画一架", "画辆", "画朵", "画条", "画张", "画一幅", 
            "画个", "画出", "画一画", "想要画", "帮我画", "可以画", 
            "增加", "加一个", "加个", "添一个", "多一个", "再画", "旁边加", "添加", "加上", 
            "去掉", "擦掉", "删除", "不要", "变成", "改色"
        ]
        user_text_lower = user_text.lower()
        should_draw = any(kw in user_text_lower for kw in drawing_keywords)

        drawing_task = None
        action_result = None
        fusion_result = {}
        operation = {"type": "create", "confidence": 1.0}

        if should_draw:
            logger.debug(f"[INTEGRATION] Preparing fusion for prompt: {user_text}")
            fusion_inputs = ConversationContextManager.prepare_fusion_inputs(user_text, context)
            operation = fusion_inputs["operation"]
            logger.debug(f"[INTEGRATION] Recognized operation: {operation['type']} (confidence: {operation['confidence']})")
            
            # If confidence is low (< 0.5), we downgrade to create or fallback to simple subject extraction
            if operation.get("confidence", 0.0) < 0.5:
                operation["type"] = "create"

            fusion_result = PromptFusionEngine.fuse_drawing_prompt(
                current_user_text=user_text,
                operation_type=operation["type"],
                previous_prompt=fusion_inputs["previous_prompt"],
                scene_elements=fusion_inputs["scene_elements"]
            )
            
            # Sync the final operation type (in case it was downgraded/adjusted by the fusion engine)
            operation["type"] = fusion_result.get("operation", operation["type"])

            logger.debug(f"[INTEGRATION] Fusion complete:")
            logger.debug(f"  - Fused Prompt: {fusion_result.get('fused_prompt', '')[:100]}...")
            logger.debug(f"  - Target Element: {fusion_result.get('target_element')}")
            logger.debug(f"  - All Elements After: {fusion_result.get('all_elements_after', [])}")

            drawing_prompt = fusion_result.get("fused_prompt", user_text)
            subject = fusion_result.get("target_element") or extract_drawing_subject(user_text) or "可爱"
            
            # Check Cache (using fused_prompt as cache key)
            cache_mgr = DrawingCacheManager.get_instance()
            cached_action = cache_mgr.get(drawing_prompt)
            if cached_action:
                logger.debug(f"[INTEGRATION] Cache hit for fused prompt: {drawing_prompt[:100]}")
                job_id = str(uuid.uuid4())
                action_result = {
                    "type": "draw",
                    "prompt": subject,
                    "fused_prompt": drawing_prompt,
                    "operation": operation["type"],
                    "scene_elements": fusion_result.get("all_elements_after"),
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
                # Save to DrawingHistory in DB
                ConversationManager.save_drawing_record(
                    job_id=job_id,
                    device_token=token,
                    operation_type=operation["type"],
                    scene_prompt=drawing_prompt,
                    image_url=cached_action.get("image_url")
                )
            else:
                logger.debug(f"[INTEGRATION] Cache miss, launching async draw task")
                drawing_task = asyncio.create_task(
                    async_generate_drawing_with_fusion(drawing_prompt, token, fusion_result)
                )

        # Stream LLM text output token-by-token
        ai_response_text = ""
        try:
            async for chunk in stream_chat_llm(user_text):
                safe_chunk = chunk.replace("\n", " ")
                ai_response_text += chunk
                yield f"data: {safe_chunk}\n\n"
        except Exception as stream_err:
            logger.error(f"[CHAT_SSE] Text streaming error: {stream_err}")

        # Wait for parallel drawing generation if triggered
        if drawing_task:
            try:
                while not drawing_task.done():
                    try:
                        action_result = await asyncio.wait_for(asyncio.shield(drawing_task), timeout=1.0)
                        break
                    except asyncio.TimeoutError:
                        # Yield an SSE comment heartbeat to keep connection alive and reset idle proxies
                        yield ": heartbeat\n\n"
                if drawing_task.done():
                    action_result = drawing_task.result()
            except Exception as task_err:
                logger.error(f"[CHAT_SSE] Async drawing task error: {task_err}")
                action_result = None

        # Update and save context
        img_url = action_result.get("image_url") if action_result else None
        bmp_hex = action_result.get("bitmap_hex") if action_result else None

        # Deepcopy or update context local var
        updated_ctx = dict(context)
        if should_draw and fusion_result:
            updated_ctx = ConversationContextManager.update_context_after_fusion(
                updated_ctx,
                fusion_result,
                image_url=img_url,
                bitmap_hex=bmp_hex
            )

        # Append to message history list
        message = {
            "timestamp": time.time(),
            "user_text": user_text,
            "ai_response": ai_response_text,
            "drawing_triggered": should_draw,
            "drawing_config": fusion_result if should_draw else None,
            "operation_type": operation["type"] if should_draw else None,
            "metadata": {
                "recognition_confidence": operation.get("confidence", 0),
                "scene_elements_after": updated_ctx.get("scene_elements", [])
            }
        }
        
        # Ensure we don't modify a shared default list
        history_list = list(updated_ctx.get("message_history", []))
        history_list.append(message)
        updated_ctx["message_history"] = history_list

        # Save context to DB
        success = ConversationManager.create_or_update_conversation_context(token, updated_ctx)
        if success:
            logger.info(f"[INTEGRATION] ✅ Saved updated context in database")
        else:
            logger.error(f"[INTEGRATION] ❌ Failed to save context in database")

        # Yield final action payload in the last SSE data frame
        final_payload = {
            "action": action_result,
            "context": {
                "scene_elements": updated_ctx.get("scene_elements", []),
                "message_count": len(updated_ctx.get("message_history", []))
            }
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


