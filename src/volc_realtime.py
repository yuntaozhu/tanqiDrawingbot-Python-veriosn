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
    Uses NEW CONSOLE API Key authentication (not old App ID/Access Token).
    
    Connects to wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue
    with header:
      - X-Api-Key (from 火山引擎 Speech Console > API Key Management)
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        uri: str = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
    ):
        # Get API Key from parameter or environment variable
        # CRITICAL: No hardcoded defaults - credentials must come from Railway env vars
        self.api_key = api_key or os.getenv("VOLC_REALTIME_API_KEY")
        self.uri = uri
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        
        # Validate required credentials
        if not self.api_key:
            raise ValueError(
                "VOLC_REALTIME_API_KEY must be provided or set in environment. "
                "Get it from: 火山引擎 Speech Console > API Key Management"
            )

    def _get_headers(self) -> Dict[str, str]:
        """
        Build WebSocket handshake headers for new console API Key authentication.
        
        NEW CONSOLE (Seeduplex):
          X-Api-Key — the unified API Key from console API Key management
          
        Reference: https://www.volcengine.com/docs/6561/2534847?lang=zh
        """
        api_key_stripped = (self.api_key or "").strip()
        
        if not api_key_stripped:
            raise ValueError("API Key cannot be empty")

        return {
            "X-Api-Key": api_key_stripped,
        }

    async def connect(self):
        """Establish WebSocket connection with required handshake headers."""
        headers = self._get_headers()
        logger.info(f"[VolcRealtime] Connecting to {self.uri} | API-Key: {(self.api_key or '')[:8]}...")
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

    async def session_create(self, session_config: Dict[str, Any]):
        """
        Send session.create event to initialize session with model parameters.
        """
        event = {
            "type": "session.create",
            "session": session_config
        }
        await self.send_event(event)

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

    async def commit_audio_buffer(self):
        """
        Send input_audio_buffer.commit event to signal end of audio input.
        """
        event = {
            "type": "input_audio_buffer.commit"
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

