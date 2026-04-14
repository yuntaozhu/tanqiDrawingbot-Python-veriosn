# Toddler Drawing Dreamer API (Python Version)

This is the Python API version of the Toddler Drawing Dreamer project. It provides endpoints for generating drawings and handling voice commands.

## Requirements

- Python 3.8+
- API Keys for Gemini, Replicate, and Ideogram (set in `.env` file)

## Setup

1. Install the dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the root directory and add your API keys:
```env
GEMINI_API_KEY=your_gemini_api_key
REPLICATE_API_TOKEN=your_replicate_api_token
IDEOGRAM_API_KEY=your_ideogram_api_key
```

## Running the Server

Start the FastAPI server:
```bash
python app.py
```
The server will run on `http://0.0.0.0:3000`.

## API Endpoints

### 1. Generate Drawing
`POST /api/generate`

Generates a line art drawing based on a text prompt.

**Request Body:**
```json
{
  "prompt": "一只可爱的小猫",
  "engine": "ideogram", // Optional: "ideogram", "replicate"
  "aspect_ratio": "1:1", // Optional: "1:1", "16:9", "9:16", etc.
  "num_images": 1, // Optional: number of images to generate
  "style": "default", // Optional: "default", "cartoon", "realistic", "watercolor"
  "apply_line_art": true // Optional: Apply black and white line art filter (default: true)
}
```

### 2. Submit Feedback
`POST /api/feedback`

Submit user feedback (rating or like/dislike) for a generated image.

**Request Body:**
```json
{
  "generation_id": "uuid-returned-from-generate",
  "rating": 5, // Integer rating (e.g., 1-5)
  "liked": true, // Optional boolean
  "comments": "Great drawing!" // Optional text
}
```

### 3. Get Generation History
`GET /api/history`

Retrieve the history of generated images.

**Query Parameters:**
- `limit`: Optional integer to limit the number of results (default: 50)

**Response:**
Returns an array of generation objects, sorted by timestamp descending.

### 4. Voice Command (Device API)
`POST /api/device/v1/voice`

Handles voice commands from the device. Transcribes audio, processes with LLM, and returns text response + TTS audio.

**Headers:**
- `x-device-token`: Your device token
- `Content-Type`: `audio/wav`

**Request Body:**
Raw audio data (WAV format)

**Response:**
```json
{
  "text_response": "好的，我这就画一张小兔子。",
  "action": { ... },
  "audio_base64": "base64-encoded-audio-data"
}
```

### 5. Check Print Jobs (Device API)
`GET /api/device/v1/print-jobs`

Checks for pending print jobs.

**Headers:**
- `x-device-token`: Your device token

### 6. Complete Print Job (Device API)
`POST /api/device/v1/print-jobs/{job_id}/complete`

Marks a print job as complete.

**Headers:**
- `x-device-token`: Your device token

## Testing with Device Client

You can test the device APIs using the included `device_client.py` script:
```bash
python device_client.py
```
