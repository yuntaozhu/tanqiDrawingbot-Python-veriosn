
import sys

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
    print("Running in MicroPython mode")
    IS_MICROPYTHON = True
except ImportError:
    import requests
    import json
    import time
    import struct
    import binascii
    print("Running in Standard Python mode")
    IS_MICROPYTHON = False

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_URL = 'http://localhost:3000' 
DEVICE_TOKEN = 'test-token-123'
POLL_INTERVAL = 2.0  # Seconds

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def create_dummy_wav(duration_sec=1):
    """
    Generates a valid 16-bit PCM, 16kHz Mono WAV header + silence/noise.
    """
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

def log(msg):
    t = time.localtime()
    ts = "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])
    print(f"[{ts}] {msg}")

# -----------------------------------------------------------------------------
# API Interactions
# -----------------------------------------------------------------------------

def get_headers(content_type='application/json'):
    return {
        'x-device-token': DEVICE_TOKEN,
        'Content-Type': content_type,
        'User-Agent': 'SuperEgoDevice/1.0'
    }

def send_voice_command():
    """
    Sends audio to the voice endpoint.
    """
    url = f"{BASE_URL}/api/device/v1/voice"
    
    log(f"Recording audio (simulated)...")
    audio_data = create_dummy_wav(1.0)
    
    log(f"POST {url} ({len(audio_data)} bytes)...")
    
    try:
        res = requests.post(url, data=audio_data, headers=get_headers('audio/wav'))
        
        if res.status_code == 200:
            data = res.json()
            log("--- Voice Response ---")
            log(f"Text: {data.get('text_response')}")
            log(f"Action: {data.get('action')}")
            audio_b64 = data.get('audio_base64')
            if audio_b64:
                log(f"Received Audio: {len(audio_b64)} bytes")
            res.close()
            return data
        else:
            log(f"Error {res.status_code} in Voice: {res.text[:100]}")
            res.close()
            return None
    except Exception as e:
        log(f"Exception in voice request: {e}")
        return None

def check_print_jobs():
    """
    Polls for new print jobs.
    """
    url = f"{BASE_URL}/api/device/v1/print-jobs"
    
    try:
        res = requests.get(url, headers=get_headers())
        if res.status_code == 200:
            job = res.json()
            res.close()
            if job.get('has_job'):
                log(f">>> NEW PRINT JOB: {job.get('job_id')}")
                return job
            return None
        elif res.status_code >= 500:
            log(f"Server Error {res.status_code}. Retrying later...")
            res.close()
            return None
        else:
            log(f"Poll Error {res.status_code}: {res.text[:100]}")
            res.close()
            return None
    except Exception as e:
        log(f"Exception in poll: {e}")
        return None

def complete_print_job(job_id):
    """
    Marks a job as complete.
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

def send_chat_command(text):
    """
    Sends text to the chat endpoint.
    """
    url = f"{BASE_URL}/api/device/v1/chat"
    
    log(f"Sending text: {text}")
    
    try:
        res = requests.post(url, json={"text": text}, headers=get_headers())
        
        if res.status_code == 200:
            data = res.json()
            log("--- Chat Response ---")
            log(f"Text: {data.get('text_response')}")
            action = data.get('action')
            if action:
                log(f"Action: {action.get('type')} - {action.get('prompt')}")
                image_url = action.get('image_url')
                if image_url and image_url.startswith('data:image'):
                    save_image(image_url, action.get('job_id'))
            res.close()
            return data
        else:
            log(f"Error {res.status_code} in Chat: {res.text[:100]}")
            res.close()
            return None
    except Exception as e:
        log(f"Exception in chat request: {e}")
        return None

def save_image(data_uri, job_id):
    try:
        header, encoded = data_uri.split(",", 1)
        data = binascii.a2b_base64(encoded)
        filename = f"drawing_{job_id}.png"
        with open(filename, "wb") as f:
            f.write(data)
        log(f"Saved image to {filename}")
    except Exception as e:
        log(f"Failed to save image: {e}")

def send_voice_file(filepath):
    """
    Sends a WAV file to the voice endpoint.
    """
    url = f"{BASE_URL}/api/device/v1/voice"
    
    try:
        with open(filepath, "rb") as f:
            audio_data = f.read()
            
        log(f"Sending voice file: {filepath} ({len(audio_data)} bytes)...")
        
        res = requests.post(url, data=audio_data, headers=get_headers('audio/wav'))
        
        if res.status_code == 200:
            data = res.json()
            log("--- Voice Response ---")
            log(f"Text: {data.get('text_response')}")
            action = data.get('action')
            if action:
                log(f"Action: {action.get('type')} - {action.get('prompt')}")
                image_url = action.get('image_url')
                if image_url and image_url.startswith('data:image'):
                    save_image(image_url, action.get('job_id'))
            res.close()
            return data
        else:
            log(f"Error {res.status_code} in Voice: {res.text[:100]}")
            res.close()
            return None
    except Exception as e:
        log(f"Exception sending voice file: {e}")
        return None

# -----------------------------------------------------------------------------
# Main Test Loop
# -----------------------------------------------------------------------------

def main():
    log("=======================================")
    log("   SuperEgo Device Client Test")
    log(f"   Target: {BASE_URL}")
    log("=======================================")
    
    print("\nSelect Mode:")
    print("1. Interactive Chat (Type commands)")
    print("2. Automated Voice Test (Sends dummy audio)")
    print("3. Send Voice File (WAV)")
    print("4. Poll Only")
    
    mode = input("Enter mode (1/2/3/4): ").strip()
    
    if mode == "1":
        log("Entering Interactive Chat Mode. Type 'exit' to quit.")
        while True:
            text = input("\nYou: ").strip()
            if text.lower() == 'exit':
                break
            if text:
                send_chat_command(text)
                
    elif mode == "2":
        # 1. Test Voice
        log("1. Testing Voice Interaction...")
        send_voice_command()
        
        # 2. Start Polling
        log(f"2. Starting Polling Loop (Interval: {POLL_INTERVAL}s)")
        log("   Press Ctrl+C to stop.")
        
        try:
            while True:
                job = check_print_jobs()
                
                if job:
                    log(f"Processing Image Job: {job.get('job_id')}")
                    image_url = job.get('image_url')
                    if image_url and image_url.startswith('data:image'):
                         save_image(image_url, job.get('job_id'))
                    
                    log("Simulating print delay (3s)...")
                    time.sleep(3)
                    complete_print_job(job['job_id'])
                
                time.sleep(POLL_INTERVAL)
                
        except KeyboardInterrupt:
            log("Test stopped by user.")

    elif mode == "3":
        filepath = input("Enter path to WAV file: ").strip()
        if filepath:
            send_voice_file(filepath)
            
    elif mode == "4":
        log(f"Starting Polling Loop (Interval: {POLL_INTERVAL}s)")
        try:
            while True:
                job = check_print_jobs()
                if job:
                    log(f"Processing Image Job: {job.get('job_id')}")
                    image_url = job.get('image_url')
                    if image_url and image_url.startswith('data:image'):
                         save_image(image_url, job.get('job_id'))
                    time.sleep(3)
                    complete_print_job(job['job_id'])
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("Stopped.")

if __name__ == '__main__':
    main()
