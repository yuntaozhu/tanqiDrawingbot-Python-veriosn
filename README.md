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
  "num_images": 1 // Optional: number of images to generate
}
```

### 2. Voice Command (Device API)
`POST /api/device/v1/voice`

Handles voice commands from the device.

**Headers:**
- `x-device-token`: Your device token

**Request Body:**
Raw audio data (WAV format)

### 3. Check Print Jobs (Device API)
`GET /api/device/v1/print-jobs`

Checks for pending print jobs.

**Headers:**
- `x-device-token`: Your device token

### 4. Complete Print Job (Device API)
`POST /api/device/v1/print-jobs/{job_id}/complete`

Marks a print job as complete.

**Headers:**
- `x-device-token`: Your device token

## Testing with Device Client

You can test the device APIs using the included `device_client.py` script:
```bash
python device_client.py
```
