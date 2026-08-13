"""
Helper module for TTS audio sample rate conversion.
This module provides audio conversion utilities to fix Android AudioTrack underrun issues.
"""
import subprocess
import time
from typing import Optional

def convert_audio_to_target_samplerate(audio_bytes: bytes, target_sr: int = 24000) -> Optional[bytes]:
    """
    Convert MP3 audio to target sample rate using ffmpeg.
    Fixes Android AudioTrack underrun issues by ensuring consistent 24000 Hz playback.
    
    Args:
        audio_bytes: MP3 audio data from TTS API
        target_sr: Target sample rate (default 24000 Hz for Android device)
    
    Returns:
        Converted audio bytes or original if conversion fails/unavailable
    """
    if not audio_bytes or len(audio_bytes) < 100:
        return audio_bytes
    
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=1, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"[WARNING] [TTS_CONVERT] ffmpeg not available, returning original audio")
        return audio_bytes
    
    try:
        print(f"[DEBUG] [TTS_CONVERT] Converting audio to {target_sr} Hz...")
        start_time = time.time()
        
        result = subprocess.run([
            'ffmpeg', '-loglevel', 'error',
            '-i', 'pipe:0',
            '-ar', str(target_sr),
            '-c:a', 'libmp3lame',
            '-q:a', '4',
            '-f', 'mp3',
            'pipe:1'
        ], 
        input=audio_bytes,
        capture_output=True,
        timeout=8
        )
        
        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='ignore')
            print(f"[WARNING] [TTS_CONVERT] ffmpeg failed: {err[:100]}")
            return audio_bytes
        
        converted = result.stdout
        if not converted or len(converted) < 50:
            print(f"[WARNING] [TTS_CONVERT] Empty output, returning original")
            return audio_bytes
        
        duration = time.time() - start_time
        reduction = (1 - len(converted)/len(audio_bytes))*100 if audio_bytes else 0
        print(f"[DEBUG] [TTS_CONVERT] OK: {len(audio_bytes)} → {len(converted)} bytes ({reduction:.0f}% reduction) in {duration:.2f}s @ {target_sr}Hz")
        return converted
        
    except subprocess.TimeoutExpired:
        print(f"[WARNING] [TTS_CONVERT] Timeout, returning original")
        return audio_bytes
    except Exception as e:
        print(f"[WARNING] [TTS_CONVERT] Error: {e}")
        return audio_bytes

