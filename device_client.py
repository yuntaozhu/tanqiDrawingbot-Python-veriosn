import os
import sys
import logging

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("device_client")

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
    Robust, cross-platform audio playback module.
    Attempts to play MP3 or WAV audio using common command-line utility fallbacks.
    """
    if IS_MICROPYTHON:
         log("Audio playback not natively supported on raw MicroPython core without hardware DAC.", "WARNING")
         return False
         
    if not os.path.exists(filepath):
        log(f"Audio file not found: {filepath}", "ERROR")
        return False
        
    log(f"播放探奇老师语音中 ({os.path.basename(filepath)})...", "DEBUG")
    
    # 1. Play on Windows via PowerShell
    if sys.platform == "win32":
        try:
            import subprocess
            cmd = ["powershell", "-c", f"(New-Object Media.SoundPlayer '{filepath}').PlaySync()"]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            pass
            
    # 2. Play on macOS via afplay
    if sys.platform == "darwin":
        try:
            import subprocess
            subprocess.run(["afplay", filepath], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            pass
            
    # 3. Generic Linux / Unix command-line utility fallbacks
    players = ['ffplay', 'mpg123', 'mpv', 'aplay', 'paplay']
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
            
    # 4. Try using standard python libraries if installed
    try:
        import sounddevice as sd
        import soundfile as sf
        data, fs = sf.read(filepath)
        sd.play(data, fs)
        sd.wait()
        return True
    except ImportError:
        pass
    except Exception as e:
        log(f"Standard library sound playback failed: {e}", "DEBUG")
        
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
        res = requests.get(url, headers=get_headers(), timeout=15, allow_redirects=True)
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
        res = requests.post(url, data=audio_data, headers=headers)
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
                save_audio(audio_b64, "voice_response.mp3")
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
    Polls for new print jobs from the queue.
    """
    url = f"{BASE_URL}/api/device/v1/print-jobs"
    headers = get_headers()
    
    try:
        res = requests.get(url, headers=headers, allow_redirects=False)
        if res.status_code == 200:
            job = res.json()
            res.close()
            if job.get('has_job'):
                log(f">>> NEW PRINT JOB RECEIVED: {job.get('job_id')}")
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

def complete_print_job(job_id):
    """
    Marks a print job as successfully processed/completed.
    """
    url = f"{BASE_URL}/api/device/v1/print-jobs/{job_id}/complete"
    
    try:
        res = requests.post(url, headers=get_headers())
        if res.status_code == 200:
            log(f"Job {job_id} marked complete.")
        else:
            log(f"Failed to complete job {job_id}: {res.status_code}")
        res.close()
    except Exception as e:
        log(f"Exception completing job: {e}")

def send_chat_command(text, silent=False):
    """
    Sends text to the chat endpoint.
    """
    url = f"{BASE_URL}/api/device/v1/chat"
    
    if not silent:
        log(f"Sending text: {text}", "DEBUG")
    headers = get_headers()
    
    try:
        res = requests.post(url, json={"text": text}, headers=headers, allow_redirects=False)
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
                save_audio(audio_b64, "chat_response.mp3")
                play_audio("response_chat_response.mp3")
                
            action = data.get('action')
            if action:
                log(f"🎨 [绘画创作中] 探奇老师正在为你创作简笔画: {action.get('prompt')}")
                image_url = action.get('image_url')
                if image_url and image_url.startswith('data:image'):
                    save_image(image_url, action.get('job_id'))
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
        filename = "response_" + original_filename
        if not filename.endswith(".mp3") and not filename.endswith(".wav"):
             filename += ".mp3"
        with open(filename, "wb") as f:
            f.write(data)
    except Exception as e:
        log(f"Failed to save audio: {e}", "ERROR")

def send_voice_file(filepath, silent=False):
    """
    Sends an audio file to the voice endpoint and plays back the reply.
    """
    url = f"{BASE_URL}/api/device/v1/voice"
    
    try:
        with open(filepath, "rb") as f:
            audio_data = f.read()
            
        if not silent:
            log(f"Sending audio file: {filepath} ({len(audio_data)} bytes)", "DEBUG")
        
        headers = get_headers('audio/wav')
        res = requests.post(url, data=audio_data, headers=headers, allow_redirects=False)
        
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
                log(f"🎨 [绘画创作中] 探奇老师触发了绘画简笔画: {action.get('prompt')}")
                image_url = action.get('image_url')
                if image_url and image_url.startswith('data:image'):
                    save_image(image_url, action.get('job_id'))
            
            audio_b64 = data.get('audio_base64')
            if audio_b64:
                import os
                base_name = os.path.basename(filepath)
                save_audio(audio_b64, base_name)
                play_audio("response_" + base_name)
                
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
        log(f"Exception sending voice file: {e}", "ERROR")
        return None

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
    print("      如果你要画画（例如：“画一只可爱小兔子”），")
    print("      探奇会自动为你生成1-bit黑白简笔画，推送到你的打印机！")
    print("="*50)
    print(f"当前在线设备令牌: {DEVICE_TOKEN}")
    print(f"服务器端连接地址: {BASE_URL}")
    print("-"*50)
    
    if not check_server_health():
        print("无法连接到服务器。请检查网络或服务器地址。退出中...")
        return
    
    if HAS_AUDIO_INPUT:
        print("[状态] 🎤 麦克风硬件就绪！我们将默认采用【语音对话】通话模式。")
    else:
        print("[状态] ⚠️ 未检测到麦克风库。我们将默认采用【文本输入 + 语音合成外放】通话模式。")
        
    print("正在连接并问候探奇老师...")
    # Initial greeting via silent text command
    send_chat_command("你好，我们开始聊天吧！", silent=True)
    
    try:
        while True:
            if HAS_AUDIO_INPUT:
                print("\n选择交互方式：[1] 🎤 语音对话 | [2] ⌨️ 文本对话 | 输入 'exit' 挂断电话")
                choice = safe_input("请选择 (默认1): ").strip()
                if choice.lower() == 'exit':
                    break
                
                if choice == "2":
                    text = safe_input("\n你（打字）: ").strip()
                    if text.lower() == 'exit':
                        break
                    if text:
                        send_chat_command(text)
                else:
                    # Dynamic voice recorder
                    filename = record_audio_dynamic()
                    if filename:
                        send_voice_file(filename)
            else:
                text = safe_input("\n你（输入）: ").strip()
                if text.lower() == 'exit':
                    break
                if text:
                    send_chat_command(text)
                    
            # Brief check for print jobs in background during dialog
            job = check_print_jobs()
            if job:
                log(f">>> 🤖 打印机打印任务自动触发! 正在输出简笔画: '{job.get('prompt')}'")
                image_url = job.get('image_url')
                if image_url and image_url.startswith('data:image'):
                     save_image(image_url, job.get('job_id'))
                time.sleep(1.5)
                complete_print_job(job['job_id'])
                
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
    print("4. 🖨️ 打印队列后台消费轮询 (Poll & Print jobs loop)")
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
        log(f"正在启动打印机循环轮询消费队列... (间隔: {POLL_INTERVAL}s)")
        log("按下 Ctrl+C 可停止。")
        try:
            while True:
                job = check_print_jobs()
                if job:
                    log(f"正在渲染并打印简笔画: {job.get('job_id')}")
                    image_url = job.get('image_url')
                    if image_url and image_url.startswith('data:image'):
                         save_image(image_url, job.get('job_id'))
                    time.sleep(3)
                    complete_print_job(job['job_id'])
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("轮询已停止。")
            
    elif mode == "5":
        log("正在模拟发送单次无声测试语音包...")
        send_voice_command()

if __name__ == '__main__':
    main()
