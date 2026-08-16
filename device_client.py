import os
import sys
import logging
import requests
import wave
import audioop
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("device_client")

# -----------------------------------------------------------------------------
# Session Management
# -----------------------------------------------------------------------------
# Toggle to False if you encounter SSL EOF errors in constrained environments
VERIFY_SSL = os.getenv("VERIFY_SSL", "True").lower() == "true"

def create_session():
    session = requests.Session()
    # Retry strategy: retry up to 3 times for connection/SSL errors
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.verify = VERIFY_SSL
    return session

session = create_session()

# Soft-pause ready-drawing polls while a voice request is waiting on the server
_voice_busy = False
_voice_request_lock = threading.Lock()

def log(msg, level="INFO"):
    if level == "DEBUG":
        logger.debug(msg)
    elif level == "WARNING":
        logger.warning(msg)
    elif level == "ERROR":
        logger.error(msg)
    else:
        logger.info(msg)

# -----------------------------------------------------------------------------
# MicroPython Compatibility Shim
# -----------------------------------------------------------------------------
try:
    import urequests as requests
    import ujson as json
    import utime as time
    import ustruct as struct
    import ubinascii as binascii
    import machine
    log("Running in MicroPython mode")
    IS_MICROPYTHON = True
except ImportError:
    import requests
    import json
    import time
    import struct
    import binascii
    log("Running in Standard Python mode")
    IS_MICROPYTHON = False

# -----------------------------------------------------------------------------
# Optional Audio Recording
# -----------------------------------------------------------------------------
try:
    import sounddevice as sd
    import numpy as np
    from scipy.io.wavfile import write as write_wav
    HAS_AUDIO_INPUT = True
except ImportError:
    HAS_AUDIO_INPUT = False
    print("Note: Install 'sounddevice', 'numpy', and 'scipy' to enable microphone recording.")

def record_audio(filename="voice_input.wav", duration=5, fs=16000):
    if not HAS_AUDIO_INPUT:
        print("Microphone recording not available. Please install dependencies.")
        return None
        
    print(f"Recording for {duration} seconds... Speak now!")
    try:
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
        sd.wait()  # Wait until recording is finished
        write_wav(filename, fs, recording)
        print(f"Saved recording to {filename}")
        return filename
    except Exception as e:
        print(f"Recording failed: {e}")
        return None

def record_audio_dynamic(filename="voice_input.wav", fs=16000):
    """
    Records audio using a queue until the user presses Enter to stop.
    This provides a natural, comfortable conversational experience.
    """
    if not HAS_AUDIO_INPUT:
        print("Microphone recording not available. Please install 'sounddevice' and 'numpy'.")
        return None
        
    import queue
    q = queue.Queue()
    
    def callback(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        q.put(indata.copy())
        
    print("\n[实时通话] 按回车键【Enter】开始说话...")
    safe_input()
    
    print("▶ 【正在录音】 探奇正在听... 说完后请按回车键【Enter】发送给探奇 ◀")
    
    try:
        # Start recording stream
        stream = sd.InputStream(samplerate=fs, channels=1, dtype='int16', callback=callback)
        with stream:
            safe_input()  # Block until the user presses Enter again
    except Exception as e:
        print(f"Recording stream error: {e}")
        return None
        
    print("■ 录音结束，正在发送给探奇老师进行分析...")
    
    # Gather all audio chunks from queue
    audio_chunks = []
    while not q.empty():
        audio_chunks.append(q.get())
        
    if not audio_chunks:
        print("No audio detected.")
        return None
        
    audio_np = np.concatenate(audio_chunks, axis=0)
    write_wav(filename, fs, audio_np)
    return filename

def record_audio_auto_vad(filename="voice_input.wav", fs=16000, silence_timeout=1.2, threshold=500):
    """
    Continuous Voice Activity Detection (Auto-VAD) recording.
    Listens to the microphone continuously. Automatically starts recording when
    user speaks, and automatically stops and saves when user stays silent for silence_timeout.
    """
    if not HAS_AUDIO_INPUT:
        print("Microphone recording not available. Please install 'sounddevice' and 'numpy'.")
        return None

    import queue
    q = queue.Queue()
    
    # States
    # 0 = waiting for speech, 1 = speaking/recording
    state = {"status": 0, "last_active": time.time(), "speech_started": False, "chunks": []}
    
    def callback(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
            
        # Calculate peak amplitude
        amp = np.max(np.abs(indata))
        now = time.time()
        
        if state["status"] == 0:
            # Waiting for speech
            if amp > threshold:
                state["status"] = 1
                state["last_active"] = now
                state["speech_started"] = True
                print("\n🎙️ [检测到声音] 小探宝正在听你倾诉... 🗣️")
                state["chunks"].append(indata.copy())
        elif state["status"] == 1:
            # Recording speech
            state["chunks"].append(indata.copy())
            if amp > threshold:
                state["last_active"] = now
            else:
                # Silence detected in this chunk. Check if timeout reached
                if now - state["last_active"] > silence_timeout:
                    state["status"] = 2 # Finished
                    print("🤫 [检测到静音] 正在发送给小探宝进行分析...\n")
                    raise sd.CallbackStop()

    print("\n🎧 [全自动免提通话模式] 小探宝正在静静地听... 请直接说话 (按 Ctrl+C 可退出)...")
    
    try:
        # Create input stream with a small blocksize for real-time responsiveness
        stream = sd.InputStream(samplerate=fs, channels=1, dtype='int16', callback=callback, blocksize=2048)
        with stream:
            while state["status"] < 2:
                time.sleep(0.1)
    except sd.CallbackStop:
        pass
    except KeyboardInterrupt:
        print("\n[退出全自动录音]")
        raise
    except Exception as e:
        print(f"Auto-VAD Recording error: {e}")
        return None
        
    if not state["speech_started"] or not state["chunks"]:
        return None
        
    audio_np = np.concatenate(state["chunks"], axis=0)
    write_wav(filename, fs, audio_np)
    return filename


def validate_voice_wav(filepath, min_duration_seconds=0.25, min_peak=250):
    """Reject silent, clipped, or non-16 kHz mono recordings before upload."""
    try:
        with wave.open(filepath, "rb") as wav:
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            frame_count = wav.getnframes()
            audio_frames = wav.readframes(frame_count)

        duration = frame_count / float(sample_rate) if sample_rate else 0.0
        if sample_rate != 16000 or channels != 1 or sample_width != 2:
            log(
                f"录音格式不正确：需要 16 kHz 单声道 16-bit WAV，实际为 "
                f"{sample_rate} Hz / {channels} 声道 / {sample_width * 8}-bit",
                "ERROR",
            )
            return False
        if duration < min_duration_seconds:
            log(f"录音太短（{duration:.2f}s），请说完后再发送。", "WARNING")
            return False

        peak = audioop.max(audio_frames, sample_width)
        if peak < min_peak:
            log("没有检测到可用的人声，请靠近麦克风后重试。", "WARNING")
            return False
        if peak >= 32760:
            log("录音发生削波，请降低麦克风音量或稍微远离麦克风后重试。", "WARNING")
            return False
        return True
    except (OSError, wave.Error, audioop.error) as error:
        log(f"无法读取 WAV 录音：{error}", "ERROR")
        return False

# -----------------------------------------------------------------------------
# Configuration & Dynamic Overrides
# -----------------------------------------------------------------------------
# Default to localhost if running inside AI Studio development environment, otherwise fallback to live URL
DEFAULT_BASE_URL = os.getenv("BASE_URL", "https://tanqibot.up.railway.app")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "test-token-123")
POLL_INTERVAL = 2.0  # Seconds

# Parse potential command line arguments for quick overrides
# Usage: python device_client.py [BASE_URL] [DEVICE_TOKEN]
BASE_URL = DEFAULT_BASE_URL
if len(sys.argv) > 1:
    BASE_URL = sys.argv[1]
if len(sys.argv) > 2:
    DEVICE_TOKEN = sys.argv[2]

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def create_dummy_wav(duration_sec=1):
    """
    Generates a valid 16-bit PCM, 16kHz Mono WAV header + silence/noise.
    """
    duration_sec = int(duration_sec)
    sample_rate = 16000
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    
    # Ensure all sizes are integers
    data_size = int(sample_rate * duration_sec * block_align)
    chunk_size = int(36 + data_size)
    
    # WAV Header
    header = b'RIFF'
    header += struct.pack('<I', chunk_size)     # ChunkSize
    header += b'WAVEfmt '
    header += struct.pack('<I', 16)             # Subchunk1Size (16 for PCM)
    header += struct.pack('<H', 1)              # AudioFormat (1 for PCM)
    header += struct.pack('<H', num_channels)   # NumChannels
    header += struct.pack('<I', int(sample_rate)) # SampleRate
    header += struct.pack('<I', int(byte_rate))   # ByteRate
    header += struct.pack('<H', int(block_align)) # BlockAlign
    header += struct.pack('<H', int(bits_per_sample)) # BitsPerSample
    header += b'data'
    header += struct.pack('<I', data_size)      # Subchunk2Size
    
    # Dummy Data (Silence)
    data = b'\x00' * data_size
    
    return header + data

def log(msg, level="INFO"):
    t = time.localtime()
    ts = "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])
    print(f"[{ts}] [{level}] {msg}")

def play_audio(filepath):
    """
    Robust, fast cross-platform audio playback module.
    Attempts to play MP3 or WAV audio using native Python audio engines first,
    falling back to Windows Media / PowerShell / Command-line utilities.
    """
    if IS_MICROPYTHON:
         log("Audio playback not natively supported on raw MicroPython core without hardware DAC.", "WARNING")
         return False
         
    if not os.path.exists(filepath):
        log(f"Audio file not found: {filepath}", "ERROR")
        return False
        
    log(f"播放探奇老师语音中 ({os.path.basename(filepath)})...", "DEBUG")
    
    # 1. Direct WAV playback via Windows winsound
    if sys.platform == "win32" and filepath.lower().endswith(".wav"):
        try:
            import winsound
            winsound.PlaySound(filepath, winsound.SND_FILENAME)
            return True
        except Exception:
            pass

    # 2. Try python sound libraries (pygame / sounddevice+soundfile)
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(filepath)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.quit()
        return True
    except (ImportError, Exception):
        pass

    try:
        import sounddevice as sd
        import soundfile as sf
        data, fs = sf.read(filepath)
        sd.play(data, fs)
        sd.wait()
        return True
    except (ImportError, Exception):
        pass

    # 3. Windows Native PowerShell Media Player (Supports MP3 & WAV)
    if sys.platform == "win32":
        try:
            import subprocess
            abs_path = os.path.abspath(filepath)
            # Use Windows Media Player COM with accurate state check
            ps_script = (
                f"$wmp = New-Object -ComObject WMPlayer.OCX; "
                f"$m = $wmp.newMedia('{abs_path}'); "
                f"$wmp.currentPlaylist.appendItem($m); "
                f"$wmp.controls.play(); "
                f"Start-Sleep -Milliseconds 400; "
                f"while ($wmp.playState -eq 3 -or $wmp.playState -eq 6 -or $wmp.playState -eq 9) {{ Start-Sleep -Milliseconds 50 }}"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            try:
                # Fallback to presentationCore MediaPlayer
                ps_script2 = (
                    f"Add-Type -AssemblyName presentationCore; "
                    f"$p = New-Object System.Windows.Media.MediaPlayer; "
                    f"$p.Open('{abs_path}'); "
                    f"Start-Sleep -Milliseconds 300; "
                    f"$p.Play(); "
                    f"while ($p.NaturalDuration.HasTimeSpan -eq $false) {{ Start-Sleep -Milliseconds 50 }}; "
                    f"Start-Sleep -Seconds ([Math]::Ceiling($p.NaturalDuration.TimeSpan.TotalSeconds)); "
                    f"$p.Close()"
                )
                cmd2 = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script2]
                subprocess.run(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except:
                pass

    # 4. macOS Native afplay
    if sys.platform == "darwin":
        try:
            import subprocess
            subprocess.run(["afplay", filepath], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            pass
            
    # 5. Linux / Cross-platform CLI players
    players = ['ffplay', 'mpv', 'mpg123', 'aplay']
    for player in players:
        try:
            import subprocess
            if player == 'ffplay':
                cmd = [player, '-nodisp', '-autoexit', '-loglevel', 'quiet', filepath]
            elif player == 'aplay':
                if not filepath.endswith('.wav'):
                    continue
                cmd = [player, '-q', filepath]
            else:
                cmd = [player, filepath]
                
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
        
    log(f"语音响应已保存至: {filepath} (未检测到系统扬声器/播放工具，请直接在本地播放该文件)", "WARNING")
    return False

# -----------------------------------------------------------------------------
# Connection Health Check
# -----------------------------------------------------------------------------

def check_server_health():
    """
    Validates the connection to the server before starting.
    """
    url = f"{BASE_URL}/health"
    log(f"Checking server connection at {url}...", "INFO")
    try:
        # Allow redirects to follow through to the actual endpoint if needed.
        res = session.get(url, headers=get_headers(), timeout=15, allow_redirects=True)
        if res.status_code == 200 and "/health" in res.url:
            log("Server connection successful!", "INFO")
            res.close()
            return True
        else:
            log(f"Server connection failed. Status code: {res.status_code}, URL: {res.url}", "ERROR")
            res.close()
            return False
    except Exception as e:
        log(f"Could not connect to server: {e}", "ERROR")
        return False

# -----------------------------------------------------------------------------
# API Interactions
# -----------------------------------------------------------------------------

def get_headers(content_type='application/json'):
    return {
        'x-device-token': DEVICE_TOKEN,
        'Authorization': f'Bearer {DEVICE_TOKEN}',
        'Content-Type': content_type,
        'Accept': 'application/json',
        'User-Agent': 'SuperEgoDevice/1.1'
    }

def send_voice_command():
    """
    Sends a brief dummy voice chunk to verify endpoint connectivity.
    """
    url = f"{BASE_URL}/api/device/v1/voice"
    log("Recording audio (simulated)...", "DEBUG")
    audio_data = create_dummy_wav(1.0)
    
    headers = get_headers('audio/wav')
    log(f"POST {url}", "DEBUG")
    log(f"Payload Size: {len(audio_data)} bytes", "DEBUG")
    
    start_time = time.time()
    try:
        res = session.post(url, data=audio_data, headers=headers)
        elapsed = time.time() - start_time
        log(f"Response Status: {res.status_code} (took {elapsed:.2f}s)", "DEBUG")
        
        if res.status_code == 200:
            data = res.json()
            log("--- Voice Response ---")
            log(f"Text Response: {data.get('text_response')}")
            log(f"Action: {data.get('action')}")
            audio_b64 = data.get('audio_base64')
            if audio_b64:
                log(f"Received Audio: {len(audio_b64)} characters (base64)", "DEBUG")
                saved_path = save_audio(audio_b64, "voice_response.mp3")
                if saved_path:
                    play_audio(saved_path)
            res.close()
            return data
        else:
            log(f"Error {res.status_code} in Voice: {res.text}", "ERROR")
            res.close()
            return None
    except Exception as e:
        log(f"Exception in voice request: {e}", "ERROR")
        return None

def check_print_jobs():
    """
    Polls for user-confirmed print jobs only (status=queued).
    Ready preview drawings are NOT returned here.
    """
    url = f"{BASE_URL}/api/device/v1/print-jobs"
    headers = get_headers()
    
    try:
        res = session.get(url, headers=headers, allow_redirects=False)
        if res.status_code == 200:
            job = res.json()
            res.close()
            if job.get('has_job'):
                log(f">>> USER-CONFIRMED PRINT JOB: {job.get('job_id')}")
                log(f"    Prompt: {job.get('prompt')}", "DEBUG")
                return job
            return None
        elif res.status_code in [301, 302, 303, 307]:
            log(f"Redirected to: {res.headers.get('Location')}. Check if authentication is needed.", "ERROR")
            res.close()
            return None
        elif res.status_code >= 500:
            res.close()
            return None
        else:
            res.close()
            return None
    except Exception as e:
        log(f"Exception in poll: {e}", "ERROR")
        return None

def check_ready_drawings():
    """Poll for generated drawings waiting for the user to tap Print (preview only)."""
    url = f"{BASE_URL}/api/device/v1/drawings/ready"
    headers = get_headers()
    try:
        # Short timeout so preview polls never starve voice/chat responses
        res = session.get(url, headers=headers, allow_redirects=False, timeout=5)
        if res.status_code == 200:
            data = res.json()
            res.close()
            return data
        res.close()
        return None
    except requests.exceptions.Timeout:
        # Expected under load — voice path holds the server briefly
        return None
    except Exception as e:
        log(f"Exception polling ready drawings: {e}", "DEBUG")
        return None

def confirm_and_print_job(job_id):
    """Simulate user tapping the Print button, then download preview and complete."""
    url = f"{BASE_URL}/api/device/v1/print-jobs/{job_id}/print"
    try:
        res = session.post(url, headers=get_headers(), timeout=20)
        if res.status_code != 200:
            log(f"Confirm print failed {res.status_code}: {res.text[:200]}", "ERROR")
            res.close()
            return None
        job = res.json()
        res.close()
        log(f"🖨️ 已确认打印: '{job.get('prompt')}' (job={job_id})")
        image_url = job.get('image_url')
        if image_url and image_url.startswith('data:image'):
            save_image(image_url, job.get('job_id'))
        complete_print_job(job_id)
        return job
    except Exception as e:
        log(f"Exception confirming print: {e}", "ERROR")
        return None

def complete_print_job(job_id):
    """
    Marks a print job as successfully processed/completed.
    """
    url = f"{BASE_URL}/api/device/v1/print-jobs/{job_id}/complete"
    
    try:
        res = session.post(url, headers=get_headers())
        if res.status_code == 200:
            log(f"Job {job_id} marked complete.")
        else:
            log(f"Failed to complete job {job_id}: {res.status_code}")
        res.close()
    except Exception as e:
        log(f"Exception completing job: {e}")

_seen_ready_jobs = set()

def preview_ready_drawings_once():
    """Download newly ready drawings for screen preview; do NOT auto-print."""
    data = check_ready_drawings()
    if not data or not data.get("has_drawing"):
        return
    for drawing in data.get("drawings") or []:
        job_id = drawing.get("job_id")
        if not job_id or job_id in _seen_ready_jobs:
            continue
        _seen_ready_jobs.add(job_id)
        prompt_text = drawing.get("prompt") or "简笔画"
        log(f"🖼️ 画作已生成（待屏幕点击打印）: '{prompt_text}' job={job_id}")
        image_url = drawing.get("image_url")
        if image_url and image_url.startswith("data:image"):
            save_image(image_url, job_id)

def send_chat_command(text, silent=False):
    """
    Sends text to the chat endpoint.
    """
    global _voice_busy
    url = f"{BASE_URL}/api/device/v1/chat?stream=false"
    
    if not silent:
        log(f"Sending text: {text}", "DEBUG")
    headers = get_headers()
    
    try:
        _voice_busy = True
        try:
            res = session.post(
                url, json={"text": text}, headers=headers, allow_redirects=False, timeout=45
            )
        finally:
            _voice_busy = False
        if res.status_code == 200:
            try:
                data = res.json()
            except Exception as e:
                log(f"Failed to parse JSON response: {res.text[:200]}", "ERROR")
                res.close()
                return None

            if not silent:
                log("--- Chat Response ---")
                log(f"探奇老师: {data.get('text_response')}")
            
            # Save and play sound if returned
            audio_b64 = data.get('audio_base64')
            if audio_b64:
                saved_path = save_audio(audio_b64, "chat_response.mp3")
                if saved_path:
                    play_audio(saved_path)
            else:
                text_response = data.get('text_response')
                if text_response and not silent:
                    if fetch_fallback_tts(text_response, "response_chat_response.mp3"):
                        play_audio("response_chat_response.mp3")
                
            action = data.get('action')
            if action:
                status = action.get('status') or 'ready'
                log(f"🎨 [绘画] status={status} prompt={action.get('prompt')}")
                if status == 'generating':
                    log("   画作后台生成中，完成后会出现在屏幕预览；需点击打印才会出纸")
                image_url = action.get('image_url')
                if image_url and image_url.startswith('data:image'):
                    save_image(image_url, action.get('job_id'))
                    log("   已保存预览图（未自动打印）")
            res.close()
            return data
        elif res.status_code in [301, 302, 303, 307]:
            log(f"Redirected to: {res.headers.get('Location')}. Check if authentication is needed.", "ERROR")
            res.close()
            return None
        else:
            log(f"Error {res.status_code} in Chat: {res.text}", "ERROR")
            res.close()
            return None
    except Exception as e:
        _voice_busy = False
        log(f"Exception in chat request: {e}", "ERROR")
        return None

def save_image(data_uri, job_id):
    try:
        header, encoded = data_uri.split(",", 1)
        data = binascii.a2b_base64(encoded)
        filename = f"drawing_{job_id}.png"
        with open(filename, "wb") as f:
            f.write(data)
        log(f"绘画图片已下载并成功保存至: {filename}")
    except Exception as e:
        log(f"Failed to save image: {e}")

def save_audio(b64_data, original_filename):
    try:
        data = binascii.a2b_base64(b64_data)
        # Auto-detect audio format: RIFF header is WAV, otherwise MP3
        if data.startswith(b"RIFF"):
            ext = ".wav"
        else:
            ext = ".mp3"
        base = os.path.splitext(os.path.basename(original_filename))[0]
        if base.startswith("response_"):
            filename = f"{base}{ext}"
        else:
            filename = f"response_{base}{ext}"
        with open(filename, "wb") as f:
            f.write(data)
        return filename
    except Exception as e:
        log(f"Failed to save audio: {e}", "ERROR")
        return None

def fetch_fallback_tts(text, filename):
    """
    Fetches high-quality TTS from Google Translate public API when server-side TTS fails/is unavailable.
    """
    try:
        import urllib.parse
        quoted_text = urllib.parse.quote(text)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=zh-CN&client=tw-ob&q={quoted_text}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        log(f"正在从备用通道合成探奇老师的语音...", "DEBUG")
        res = session.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            with open(filename, "wb") as f:
                f.write(res.content)
            return True
    except Exception as e:
        log(f"备用语音生成失败: {e}", "WARNING")
    return False

def send_voice_file(filepath, silent=False):
    """
    Sends an audio file to the voice endpoint and plays back the reply.
    """
    global _voice_busy
    url = f"{BASE_URL}/api/device/v1/voice"
    
    try:
        if not validate_voice_wav(filepath):
            return None

        with open(filepath, "rb") as f:
            audio_data = f.read()
            
        if not silent:
            log(f"Sending audio file: {filepath} ({len(audio_data)} bytes)", "DEBUG")
        
        headers = get_headers('audio/wav')
        if not _voice_request_lock.acquire(blocking=False):
            log("上一段语音仍在处理，请等待老师回复后再说。", "WARNING")
            return None
        try:
            _voice_busy = True
            # Voice pipeline (STT+LLM+TTS) can need tens of seconds, but only
            # one request is permitted at a time to avoid transcript mixing.
            res = session.post(
                url, data=audio_data, headers=headers, allow_redirects=False, timeout=60
            )
        finally:
            _voice_busy = False
            _voice_request_lock.release()
        
        if res.status_code == 200:
            try:
                data = res.json()
            except Exception as e:
                log(f"Failed to parse JSON response: {res.text[:200]}", "ERROR")
                res.close()
                return None

            if not silent:
                log("--- Voice Response ---")
                log(f"探奇老师: {data.get('text_response')}")
                
            action = data.get('action')
            if action:
                status = action.get('status') or 'ready'
                log(f"🎨 [绘画] status={status} prompt={action.get('prompt')}")
                if status == 'generating':
                    log("   画作后台生成中，完成后会出现在屏幕预览；需点击打印才会出纸")
                image_url = action.get('image_url')
                if image_url and image_url.startswith('data:image'):
                    save_image(image_url, action.get('job_id'))
                    log("   已保存预览图（未自动打印）")
            
            audio_b64 = data.get('audio_base64')
            if audio_b64:
                saved_audio_path = save_audio(audio_b64, filepath)
                if saved_audio_path:
                    play_audio(saved_audio_path)
            else:
                text_response = data.get('text_response')
                if text_response and not silent:
                    fallback_file = "response_" + os.path.splitext(os.path.basename(filepath))[0] + ".mp3"
                    if fetch_fallback_tts(text_response, fallback_file):
                        play_audio(fallback_file)
                
            res.close()
            return data
        elif res.status_code in [301, 302, 303, 307]:
            log(f"Redirected to: {res.headers.get('Location')}. Check if authentication is needed.", "ERROR")
            res.close()
            return None
        else:
            log(f"Error {res.status_code} in Voice Response: {res.text}", "ERROR")
            res.close()
            return None
    except Exception as e:
        _voice_busy = False
        log(f"Exception sending voice file: {e}", "ERROR")
        return None

def background_preview_worker():
    """Poll for ready drawings and save local previews. Does NOT auto-print."""
    while True:
        try:
            if _voice_busy:
                # Avoid competing with the in-flight voice HTTP request
                time.sleep(5.0)
                continue
            preview_ready_drawings_once()
        except Exception:
            pass
        time.sleep(5.0)

# -----------------------------------------------------------------------------
# Main Call / Dialogue Service
# -----------------------------------------------------------------------------

def start_realtime_call_service():
    """
    Starts a beautifully designed, conversational voice/text call service.
    Acts as a continuous open microphone or typing session where the child or user can interact in real-time.
    """
    print("\n" + "="*50)
    print("   🧸 探奇智能玩偶（小探宝） 实时通话服务已启动 🧸   ")
    print("      在通话过程中，你可以直接对探奇倾诉或输入对话。")
    print("      探奇会聆听你的诉求，用温柔的语音回答你。")
    print("      画作生成后仅在屏幕预览；点击「打印」按钮后才会出纸。")
    print("="*50)
    print(f"当前在线设备令牌: {DEVICE_TOKEN}")
    print(f"服务器端连接地址: {BASE_URL}")
    print("-"*50)
    
    if not check_server_health():
        print("无法连接到服务器。请检查网络或服务器地址。退出中...")
        return

    # Preview-only worker (no auto print)
    import threading
    t = threading.Thread(target=background_preview_worker, daemon=True)
    t.start()
    log("已启动画作预览监听（生成后只下载预览，不会自动打印）", "DEBUG")
    
    # Select dialogue mode
    dialog_mode = "1" # Default to Auto-VAD
    if HAS_AUDIO_INPUT:
        print("\n请选择通话交互模式：")
        print(" [1] 🎤 全自动免提通话 (推荐：说停即发，完全实时语音对话，不需触碰键盘)")
        print(" [2] ⌨️ 手动按键语音通话 (手动按回车键开始/结束录音)")
        print(" [3] 💬 纯打字文本通话 (打字输入，语音合成外放)")
        dialog_mode = safe_input("请选择 (默认1): ").strip()
        if dialog_mode not in ["1", "2", "3", ""]:
            dialog_mode = "1"
        if dialog_mode == "":
            dialog_mode = "1"
    else:
        print("[状态] ⚠️ 未检测到麦克风库。我们将默认采用【文本输入 + 语音合成外放】通话模式。")
        dialog_mode = "3"
        
    print("正在连接并问候探奇老师...")
    # Initial greeting via silent text command
    send_chat_command("你好，我们开始聊天吧！", silent=True)
    
    try:
        while True:
            if dialog_mode == "1":
                # Continuous Auto-VAD call mode
                filename = record_audio_auto_vad()
                if filename:
                    send_voice_file(filename)
                else:
                    # Brief break if user stays completely silent
                    time.sleep(0.5)
            elif dialog_mode == "2":
                # Manual press to talk mode
                filename = record_audio_dynamic()
                if filename:
                    send_voice_file(filename)
            else:
                # Text dialog mode
                text = safe_input("\n你（打字）: ").strip()
                if text.lower() == 'exit':
                    break
                if text.lower() in ('p', 'print', '打印'):
                    data = check_ready_drawings()
                    latest = (data or {}).get("latest")
                    if latest and latest.get("job_id"):
                        confirm_and_print_job(latest["job_id"])
                    else:
                        log("当前没有待打印的画作预览。")
                    continue
                if text:
                    send_chat_command(text)
                    
            # Preview only — never auto-print
            preview_ready_drawings_once()
                
    except KeyboardInterrupt:
        pass
    
    print("\n☎️ 实时通话已挂断。谢谢使用，再见！")

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------

def safe_input(prompt=""):
    """Safely handle input with potential encoding issues."""
    try:
        return input(prompt).strip()
    except UnicodeDecodeError:
        try:
            import sys
            sys.stdout.write(prompt)
            sys.stdout.flush()
            line = sys.stdin.readline()
            return line.strip()
        except:
            return ""
    except EOFError:
        return "exit"
    except Exception as e:
        print(f"\n[DEBUG] Input Error: {e}")
        return ""

def main():
    log("=======================================")
    log("   SuperEgo Device Client v1.2 (Real-time Call)")
    log(f"   Target URL: {BASE_URL}")
    log(f"   Device Token: {DEVICE_TOKEN}")
    log("=======================================")
    
    print("\n选择要运行的功能：")
    print("1. 📞 启动 实时多模态通话服务 (Real-time Voice & Text Dialogue Loop)")
    print("2. 💬 发送单次文本对话 (Single Chat Command)")
    print("3. 🎤 录制并发送单次语音 (Microphone Voice Command)")
    print("4. 🖼️ 查看待打印画作 / 手动确认打印 (Preview & Confirm Print)")
    print("5. 🧪 模拟发送测试语音包 (Send dummy silent audio)")
    
    mode = safe_input("\n请输入选择 (1/2/3/4/5): ")
    
    if mode == "1" or mode == "":
        start_realtime_call_service()
        
    elif mode == "2":
        text = safe_input("请输入发送给探奇的内容: ")
        if text:
            send_chat_command(text)
            
    elif mode == "3":
        if not HAS_AUDIO_INPUT:
             print("错误: 本机未检测到麦克风录音环境。请先安装 dependencies (sounddevice, numpy, scipy)。")
        else:
             filename = record_audio()
             if filename:
                 send_voice_file(filename)
                 
    elif mode == "4":
        log("拉取待打印画作预览（不会自动出纸）...")
        data = check_ready_drawings()
        drawings = (data or {}).get("drawings") or []
        if not drawings:
            log("当前没有 status=ready 的画作。")
        else:
            for i, d in enumerate(drawings, 1):
                log(f"  [{i}] {d.get('job_id')}  prompt='{d.get('prompt')}'")
                if d.get("image_url") and d["image_url"].startswith("data:image"):
                    save_image(d["image_url"], d.get("job_id"))
            choice = safe_input("输入序号确认打印（回车取消）: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(drawings):
                confirm_and_print_job(drawings[int(choice) - 1]["job_id"])
            
    elif mode == "5":
        log("正在模拟发送单次无声测试语音包...")
        send_voice_command()

if __name__ == '__main__':
    main()
