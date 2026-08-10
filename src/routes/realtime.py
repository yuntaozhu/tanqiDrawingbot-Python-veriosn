import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.volc_realtime import VolcRealtimeClient

logger = setup_logger if "setup_logger" in globals() else lambda name: logging.getLogger(name)
logger = logging.getLogger("routes.realtime")

router = APIRouter()

@router.websocket("/api/v3/duplex/realtime/dialogue")
@router.websocket("/ws/v3/duplex/realtime/dialogue")
async def volc_realtime_websocket(websocket: WebSocket):
    await websocket.accept()
    
    # Extract headers from WebSocket handshake request
    headers = websocket.headers
    app_id = headers.get("x-api-app-id") or headers.get("X-Api-App-ID")
    api_key = headers.get("x-api-key") or headers.get("X-Api-Key")
    resource_id = headers.get("x-api-resource-id") or headers.get("X-Api-Resource-Id")
    
    # Also check query parameters as fallback
    query_params = websocket.query_params
    if not app_id:
        app_id = query_params.get("app_id") or query_params.get("X-Api-App-ID")
    if not api_key:
        api_key = query_params.get("api_key") or query_params.get("X-Api-Key")
    if not resource_id:
        resource_id = query_params.get("resource_id") or query_params.get("X-Api-Resource-Id")

    logger.info(f"[RealtimeWS] Client connected. App-ID: {app_id or 'default'}, Resource-ID: {resource_id or 'default'}")

    client = VolcRealtimeClient(
        app_id=app_id,
        access_key=api_key,
        resource_id=resource_id
    )

    try:
        # Connect to upstream Volcengine S2S v3 endpoint
        await client.connect()
    except Exception as e:
        logger.error(f"[RealtimeWS] Failed to connect upstream to Volcengine: {e}")
        error_event = {
            "type": "error",
            "error": {
                "code": 45000000,
                "message": f"Failed to connect to Volcengine S2S endpoint: {str(e)}"
            }
        }
        try:
            await websocket.send_text(json.dumps(error_event, ensure_ascii=False))
        except Exception:
            pass
        await websocket.close(code=1011, reason="Upstream connection failed")
        return

    # Define relay tasks
    async def client_to_volc():
        try:
            while True:
                message = await websocket.receive_text()
                try:
                    event_data = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning(f"[RealtimeWS] Received non-JSON text frame from client: {message[:100]}")
                    # Send syntax error event back to client
                    err_resp = {
                        "type": "error",
                        "error": {
                            "code": 45000000,
                            "message": "Syntax error: expected valid JSON text frame"
                        }
                    }
                    await websocket.send_text(json.dumps(err_resp, ensure_ascii=False))
                    continue

                event_type = event_data.get("type")
                logger.debug(f"[RealtimeWS] Uplink event from client: {event_type}")

                if event_type == "session.update":
                    session_config = event_data.get("session", {})
                    await client.session_update(session_config)
                elif event_type == "input_audio_buffer.append":
                    audio_b64 = event_data.get("audio", "")
                    await client.append_audio_buffer(audio_b64)
                elif event_type == "response.cancel":
                    await client.cancel_response()
                else:
                    # Forward any other valid JSON event directly
                    await client.send_event(event_data)

        except WebSocketDisconnect:
            logger.info("[RealtimeWS] Client disconnected.")
        except Exception as e:
            logger.error(f"[RealtimeWS] Error in client_to_volc relay: {e}")

    async def volc_to_client():
        try:
            async for downlink_event in client.receive_events():
                # Forward downlink event as JSON text frame to client
                if isinstance(downlink_event, dict):
                    payload = json.dumps(downlink_event, ensure_ascii=False)
                else:
                    payload = str(downlink_event)
                await websocket.send_text(payload)
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"[RealtimeWS] Volcengine upstream connection closed: {e}")
        except Exception as e:
            logger.error(f"[RealtimeWS] Error in volc_to_client relay: {e}")

    # Run both relay directions concurrently
    task1 = asyncio.create_task(client_to_volc())
    task2 = asyncio.create_task(volc_to_client())

    try:
        done, pending = await asyncio.wait(
            [task1, task2],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except Exception as e:
        logger.error(f"[RealtimeWS] Error during relay execution: {e}")
    finally:
        await client.close()
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("[RealtimeWS] Session cleaned up.")
