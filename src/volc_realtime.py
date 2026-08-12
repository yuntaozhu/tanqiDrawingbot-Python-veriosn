import asyncio
import json
import os
import logging
import websockets
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger("volc_realtime")

class VolcRealtimeClient:
    """
    Volcengine Realtime S2S v3 Duplex client (Seeduplex) for low-latency voice interaction.
    Connects to wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue
    with headers:
      - X-Api-App-ID
      - X-Api-Key
      - X-Api-Resource-Id
    """
    def __init__(
        self,
        app_id: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        resource_id: Optional[str] = None,
        uri: str = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
    ):
        raw_app_id = app_id or os.getenv("VOLC_REALTIME_APP_ID", "6665813986")
        # Normalize legacy numeric app_id → actual API app_id (same mapping as get_realtime_config)
        self.app_id = "PlgvMymc7f3tQnJ6" if str(raw_app_id).strip() == "6665813986" else str(raw_app_id).strip()
        self.access_key = access_key or os.getenv("VOLC_REALTIME_ACCESS_KEY") or os.getenv("ARK_API_KEY", "05a5b825-69f6-40ff-93e9-7493c05e4fb0")
        self.secret_key = secret_key or os.getenv("VOLC_REALTIME_SECRET_KEY", "JNsFZNNM4rx3io7dP6JF0t5F0hlilxfr")
        self.resource_id = resource_id or os.getenv("VOLC_REALTIME_RESOURCE_ID", "volc.speech.dialog")
        self.uri = uri
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None

    def _get_headers(self) -> Dict[str, str]:
        # Volcengine v3 duplex realtime API requires:
        #   X-Api-App-ID     — the numeric/string App ID
        #   X-Api-Access-Key — the access key (may be UUID format from console)
        #   X-Api-Resource-Id — the resource/product id (e.g. "volc.speech.dialog")
        access_key = (self.access_key or self.secret_key or "").strip()
        app_id_stripped = str(self.app_id).strip()
        resource_id_stripped = str(self.resource_id).strip()

        return {
            "X-Api-App-ID": app_id_stripped,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id_stripped,
        }

    async def connect(self):
        """Establish WebSocket connection with required handshake headers."""
        headers = self._get_headers()
        logger.info(f"[VolcRealtime] Connecting to {self.uri} | App-ID: {self.app_id} | Resource-ID: {self.resource_id} | Access-Key: {(self.access_key or '')[:8]}...")
        try:
            self.websocket = await websockets.connect(
                self.uri,
                additional_headers=headers
            )
            logger.info("[VolcRealtime] WebSocket connection established successfully.")
        except Exception as e:
            logger.error(f"[VolcRealtime] Failed to connect: {e}")
            raise RuntimeError(f"Volcengine Realtime connection error: {e}")

    async def send_event(self, event_data: Dict[str, Any]):
        """Send a JSON text frame event uplink."""
        if not self.websocket:
            raise RuntimeError("WebSocket is not connected. Call connect() first.")
        payload = json.dumps(event_data, ensure_ascii=False)
        logger.debug(f"[VolcRealtime] Sending event: {event_data.get('type')}")
        await self.websocket.send(payload)

    async def session_update(self, session_config: Dict[str, Any]):
        """
        Send session.update event to configure session parameters
        (modalities, instructions, voice, formats, turn_detection, etc.).
        """
        event = {
            "type": "session.update",
            "session": session_config
        }
        await self.send_event(event)

    async def append_audio_buffer(self, audio_base64: str):
        """
        Send input_audio_buffer.append event with base64 encoded PCM audio chunk.
        """
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_base64
        }
        await self.send_event(event)

    async def cancel_response(self):
        """
        Send response.cancel event to interrupt assistant speech (barge-in).
        """
        event = {
            "type": "response.cancel"
        }
        await self.send_event(event)

    async def receive_events(self):
        """
        Async generator yielding downlink JSON events from the server
        (e.g., session.created, response.audio.delta, response.text.delta, etc.).
        """
        if not self.websocket:
            raise RuntimeError("WebSocket is not connected.")
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    yield data
                except json.JSONDecodeError:
                    logger.warning(f"[VolcRealtime] Received non-JSON message: {message[:100]}")
                    yield {"type": "raw", "content": message}
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"[VolcRealtime] Connection closed: {e}")
        except Exception as e:
            logger.error(f"[VolcRealtime] Error receiving events: {e}")
            raise

    async def close(self):
        """Gracefully close the WebSocket connection."""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            logger.info("[VolcRealtime] WebSocket connection closed.")
