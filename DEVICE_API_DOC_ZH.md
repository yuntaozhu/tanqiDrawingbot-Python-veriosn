# Tanqi (探奇) 绘图机器人 - 嵌入式设备接口文档 (v1.0)

本文档旨在为嵌入式开发人员（如 ESP32, Raspberry Pi 等）提供与 Tanqi 绘图机器人后端交互的详细接口说明。

## 1. 通用说明

- **基础 URL**: `http://<server-ip>:3000`
- **认证方式**: 所有设备端接口均需在 Header 中携带 `x-device-token`。
- **数据格式**: 
  - 请求：通常为 `application/json` 或 `audio/wav`。
  - 响应：`application/json`。

---

## 2. 接口定义

### 2.1 语音交互 (Voice Interaction)
将设备采集的语音数据发送至服务器进行识别并触发绘图。

- **URL**: `/api/device/v1/voice`
- **方法**: `POST`
- **Headers**:
  - `x-device-token`: `your-device-token`
  - `Content-Type`: `audio/wav`
- **请求体**: 原始 WAV 音频数据（建议：16kHz, 16-bit, 单声道）。
- **响应示例**:
```json
{
  "text_response": "好的，我这就画一张小兔子。",
  "action": {
    "type": "print",
    "prompt": "小兔子",
    "job_id": "uuid-string",
    "image_url": "data:image/x-ms-bmp;base64,...",
    "bitmap_hex": "00ff00ff..."
  },
  "audio_base64": null
}
```

### 2.2 文本聊天 (Text Chat)
用于调试或无麦克风设备，通过文本与机器人 Tanqi 交互。

- **URL**: `/api/device/v1/chat`
- **方法**: `POST`
- **Headers**:
  - `x-device-token`: `your-device-token`
  - `Content-Type`: `application/json`
- **请求体**:
```json
{
  "text": "画一只红色的赛车"
}
```
- **响应示例**: 同 2.1。

### 2.3 轮询打印任务 (Poll Print Jobs)
设备应定期（如每 2-5 秒）调用此接口，检查是否有新的绘图任务需要打印。

- **URL**: `/api/device/v1/print-jobs`
- **方法**: `GET`
- **Headers**:
  - `x-device-token`: `your-device-token`
- **响应示例 (有任务)**:
```json
{
  "has_job": true,
  "job_id": "uuid-string",
  "image_url": "data:image/x-ms-bmp;base64,...",
  "bitmap_hex": "00ff00ff...",
  "prompt": "小兔子",
  "timestamp": 1708800000.0
}
```
- **响应示例 (无任务)**:
```json
{
  "has_job": false
}
```

### 2.4 完成打印任务 (Complete Print Job)
当设备成功打印完图片后，必须调用此接口以清除服务器上的任务队列。

- **URL**: `/api/device/v1/print-jobs/{job_id}/complete`
- **方法**: `POST`
- **Headers**:
  - `x-device-token`: `your-device-token`
- **响应示例**:
```json
{
  "success": true,
  "message": "Print job completed successfully",
  "job_id": "uuid-string",
  "status": "finished"
}
```

---

## 3. 嵌入式开发建议

1. **图片处理**: `image_url` 返回的是 Base64 编码的 **320x320 1-bit BMP (Bitmap)** 图片。这种格式非常适合资源受限的单片机（如 ESP32），因为它不需要复杂的解码器，可以直接读取像素点阵。
2. **点阵提取**: `bitmap_hex` 字段提供了原始的 1-bit 像素数据（十六进制字符串），每位（bit）代表一个像素点（0为黑，1为白）。对于 320x320 的图像，数据量约为 12.8KB。这比解析 BMP 文件头更简单。
3. **轮询频率**: 建议轮询间隔不低于 2 秒，以减轻服务器压力。
4. **音频采集**: 确保 WAV 格式正确，否则 Gemini API 可能无法识别。

---

## 4. 错误码说明

- `200 OK`: 请求成功。
- `401 Unauthorized`: 缺少或错误的 `x-device-token`。
- `400 Bad Request`: 请求体为空或格式错误。
- `500 Internal Server Error`: 服务器内部错误（如 API Key 失效、绘图引擎故障）。
