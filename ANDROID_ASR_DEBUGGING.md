# 🎤 Android 端语音识别 (ASR) 调试指南

## 🔴 问题症状

- ✅ 应用可以连接到后端,获取 WebSocket 配置
- ✅ 文本转语音 (TTS) 正常工作,能听到机器人说话
- ❌ **但说话后没有识别到声音,无法进行对话**
- ❌ **后端日志中看不到任何 WebSocket 音频相关的日志**

---

## 🔍 快速诊断清单

### 第一步: 确认 WebSocket 连接成功

#### ✅ 期望看到的现象
```
1. 调用 /api/device/v1/realtime-config 获取 WebSocket URL 和 API Key
2. 使用返回的凭证连接到 wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue
3. 连接建立后,立即收到 session.created 事件
4. 后端日志应该显示:
   [RealtimeWS] Client connected. App-ID: ...
   [VolcRealtime] WebSocket connection established successfully.
```

#### ❌ 如果看不到这些
**问题可能在**: WebSocket 连接没有真正建立
- [ ] 检查网络连接状态
- [ ] 打印 WebSocket 连接事件日志
- [ ] 确认 Headers 正确 (仅有 `X-Api-Key`)
- [ ] 检查 URL 是否包含 `/duplex/`

---

### 第二步: 确认 Session 初始化

#### ✅ 期望的流程
```
客户端连接 → 服务器发送 session.created → 客户端准备发送音频
```

#### ❌ 调试代码 (Kotlin)
```kotlin
webSocket.setListener(object : WebSocketListener() {
    override fun onMessage(message: String) {
        val event = Json.parseToJsonElement(message).jsonObject
        val eventType = event["type"]?.jsonPrimitive?.content
        
        Log.d("WebSocket", "Received event type: $eventType")
        
        when (eventType) {
            "session.created" -> {
                Log.d("WebSocket", "✅ Session created successfully!")
                // 现在可以开始录制音频
                startAudioRecording()
            }
            "session.updated" -> {
                Log.d("WebSocket", "✅ Session updated")
            }
            else -> {
                Log.d("WebSocket", "Event: $message")
            }
        }
    }
})
```

---

### 第三步: 确认音频录制

#### ✅ 期望的流程
```
1. WebSocket 连接成功
2. 收到 session.created
3. 启动麦克风录制
4. 实时将 PCM 音频块发送到 WebSocket
```

#### 🔴 常见问题

**问题 1: 麦克风权限问题**
```kotlin
// 检查麦克风权限
if (ContextCompat.checkSelfPermission(
    this, 
    Manifest.permission.RECORD_AUDIO
) != PackageManager.PERMISSION_GRANTED) {
    ActivityCompat.requestPermissions(
        this,
        arrayOf(Manifest.permission.RECORD_AUDIO),
        PERMISSION_REQUEST_CODE
    )
    return // 权限未授予,无法录制
}
```

**问题 2: 音频格式不对**
```kotlin
// ✅ 正确的音频格式
val audioRecord = AudioRecord(
    MediaRecorder.AudioSource.MIC,
    16000,                          // ✅ 采样率必须是 16000 Hz
    AudioFormat.CHANNEL_IN_MONO,    // ✅ 单声道
    AudioFormat.ENCODING_PCM_16BIT, // ✅ PCM 16-bit
    bufferSize
)
```

**问题 3: 没有真正发送音频**
```kotlin
// ❌ 错误: 连接后没有发送任何数据
webSocket.connect()
// ... 等待 session.created
// 但之后没有任何 send 操作!

// ✅ 正确: 连接后发送 session.create + 音频
webSocket.connect()
// 收到 session.created 后:
audioRecord.startRecording()
val pcmBuffer = ByteArray(4096)
while (isRecording) {
    val bytesRead = audioRecord.read(pcmBuffer, 0, pcmBuffer.size)
    if (bytesRead > 0) {
        val audioData = pcmBuffer.sliceArray(0 until bytesRead)
        val base64Audio = Base64.getEncoder().encodeToString(audioData)
        
        val event = """
        {
            "type": "input_audio_buffer.append",
            "audio": "$base64Audio"
        }
        """.trimIndent()
        
        webSocket.send(event)
    }
}
```

---

### 第四步: 检查音频发送事件格式

#### ✅ 正确的音频事件格式
```json
{
  "type": "input_audio_buffer.append",
  "audio": "//NExAAiYAP8AAAA..."  // Base64 编码的 PCM 数据
}
```

#### ❌ 常见错误

**错误 1: 音频没有 Base64 编码**
```kotlin
// ❌ 错误: 直接发送二进制数据
val event = """
{
    "type": "input_audio_buffer.append",
    "audio": $binaryData  // ❌ 不能在 JSON 中直接放二进制
}
"""

// ✅ 正确: Base64 编码
val base64Audio = Base64.getEncoder().encodeToString(binaryData)
val event = """
{
    "type": "input_audio_buffer.append",
    "audio": "$base64Audio"  // ✅ Base64 字符串
}
"""
```

**错误 2: 事件格式不是 JSON text frame**
```kotlin
// ❌ 错误: 发送二进制帧
webSocket.send(byteArrayOf(...))

// ✅ 正确: 发送 JSON text frame
webSocket.send(jsonEventString)
```

**错误 3: 音频块太小或太大**
```kotlin
// ✅ 推荐的音频块大小
val recommendedChunkSize = 16000 / 10  // ~1600 bytes for 100ms chunks
val pcmBuffer = ByteArray(recommendedChunkSize)

while (isRecording) {
    val bytesRead = audioRecord.read(pcmBuffer, 0, pcmBuffer.size)
    if (bytesRead > 0) {
        // 发送这个 bytesRead 长度的音频
        sendAudioChunk(pcmBuffer.sliceArray(0 until bytesRead))
    }
}
```

---

### 第五步: 检查下行事件处理

#### ✅ 期望接收的事件序列
```
1. session.created (连接后)
2. conversation.item.input_audio_transcription.started (检测到说话)
3. conversation.item.input_audio_transcription.delta (识别中间结果)
4. conversation.item.input_audio_transcription.completed (识别完成)
5. response.output_text.delta (模型回复文本流)
6. response.output_audio.started (合成音频开始)
7. response.output_audio.delta (音频数据块)
8. response.output_audio.done (合成完成)
```

#### ❌ 如果没有收到第 2-4 个事件
**问题可能在**:
- [ ] 音频根本没有发送到服务器
- [ ] 音频格式不对 (采样率/编码不对)
- [ ] 麦克风没有录制到任何声音
- [ ] WebSocket 连接中断或丢失

---

## 🛠️ 完整的调试代码模板

```kotlin
class RealtimeAudioDebug {
    private var audioRecord: AudioRecord? = null
    private var webSocket: WebSocket? = null
    private var isRecording = false
    
    companion object {
        private const val TAG = "RealtimeAudio"
        private const val SAMPLE_RATE = 16000
        private const val CHUNK_SIZE = 4096
    }
    
    // 第一步: 获取配置
    suspend fun getRealtimeConfig(deviceToken: String): String {
        val response = httpClient.get("$API_BASE/api/device/v1/realtime-config") {
            header("x-device-token", deviceToken)
        }
        val config = response.body<RealtimeConfig>()
        Log.d(TAG, "✅ Config received: ${config.realtime_api_v3_duplex.url}")
        return config.realtime_api_v3_duplex.url
    }
    
    // 第二步: 连接 WebSocket
    fun connectWebSocket(wsUrl: String, apiKey: String) {
        val headers = mapOf("X-Api-Key" to apiKey)
        
        webSocket = WebSocketFactory()
            .createSocket(wsUrl, headers)
            .apply {
                setListener(object : WebSocketListener() {
                    override fun onConnected(headers: Map<String, List<String>>?) {
                        Log.d(TAG, "✅ WebSocket connected")
                    }
                    
                    override fun onMessage(message: String?) {
                        handleWebSocketMessage(message)
                    }
                    
                    override fun onError(cause: WebSocketException?) {
                        Log.e(TAG, "❌ WebSocket error: ${cause?.message}")
                    }
                    
                    override fun onDisconnected() {
                        Log.d(TAG, "❌ WebSocket disconnected")
                    }
                })
            }
    }
    
    // 第三步: 处理下行事件
    private fun handleWebSocketMessage(message: String?) {
        if (message == null) return
        
        Log.d(TAG, "📨 Received: $message")
        
        val event = Json.parseToJsonElement(message).jsonObject
        val eventType = event["type"]?.jsonPrimitive?.content ?: return
        
        when (eventType) {
            "session.created" -> {
                Log.d(TAG, "✅ Session created - Ready to send audio")
                startAudioRecording()
            }
            
            "conversation.item.input_audio_transcription.started" -> {
                Log.d(TAG, "✅ ASR Started - Detecting speech")
            }
            
            "conversation.item.input_audio_transcription.delta" -> {
                val delta = event["delta"]?.jsonPrimitive?.contentOrNull
                Log.d(TAG, "🎤 ASR interim: $delta")
            }
            
            "conversation.item.input_audio_transcription.completed" -> {
                val text = event["transcript"]?.jsonPrimitive?.contentOrNull
                Log.d(TAG, "✅ ASR Complete: $text")
            }
            
            "response.output_text.delta" -> {
                val delta = event["delta"]?.jsonPrimitive?.contentOrNull
                Log.d(TAG, "💬 AI Response: $delta")
            }
            
            "response.output_audio.delta" -> {
                Log.d(TAG, "🔊 Audio chunk received")
            }
            
            "response.output_audio.done" -> {
                Log.d(TAG, "✅ Audio done")
            }
            
            "error" -> {
                val errorMsg = event["error"]?.jsonObject?.get("message")?.jsonPrimitive?.contentOrNull
                Log.e(TAG, "❌ Error from server: $errorMsg")
            }
            
            else -> {
                Log.d(TAG, "📨 Other event: $eventType")
            }
        }
    }
    
    // 第四步: 录制和发送音频
    private fun startAudioRecording() {
        if (!checkPermission(Manifest.permission.RECORD_AUDIO)) {
            Log.e(TAG, "❌ Microphone permission denied")
            return
        }
        
        val bufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        
        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize
        ).apply {
            startRecording()
        }
        
        isRecording = true
        
        // 在后台线程中不断读取和发送音频
        lifecycleScope.launch(Dispatchers.Default) {
            val pcmBuffer = ByteArray(CHUNK_SIZE)
            
            while (isRecording) {
                val bytesRead = audioRecord?.read(pcmBuffer, 0, pcmBuffer.size) ?: 0
                
                if (bytesRead > 0) {
                    Log.d(TAG, "🎙️ Read $bytesRead bytes from microphone")
                    
                    val audioData = pcmBuffer.sliceArray(0 until bytesRead)
                    val base64Audio = Base64.getEncoder().encodeToString(audioData)
                    
                    val event = """
                    {
                        "type": "input_audio_buffer.append",
                        "audio": "$base64Audio"
                    }
                    """.trimIndent()
                    
                    webSocket?.send(event)
                    Log.d(TAG, "📤 Sent audio chunk")
                } else if (bytesRead == AudioRecord.ERROR_INVALID_OPERATION) {
                    Log.e(TAG, "❌ AudioRecord ERROR_INVALID_OPERATION")
                    break
                } else if (bytesRead == AudioRecord.ERROR_BAD_VALUE) {
                    Log.e(TAG, "❌ AudioRecord ERROR_BAD_VALUE")
                    break
                }
            }
        }
    }
    
    // 停止录制
    fun stopAudioRecording() {
        isRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
        Log.d(TAG, "⏹️ Audio recording stopped")
    }
}
```

---

## 🔧 常见问题排查表

| 症状 | 原因 | 解决方案 |
|------|------|--------|
| 连接后立即收到 401 | 还在用旧的 Header | 升级到新版 (参考 ANDROID_WEBSOCKET_UPGRADE.md) |
| 连接成功但收不到 `session.created` | 没有真正连接,或连接被立即断开 | 检查网络,打印连接日志 |
| 收到 `session.created` 但没有 `input_audio_transcription.*` | 音频没有发送,或格式错误 | 检查麦克风权限、采样率、Base64 编码 |
| 后端日志看不到 `[RealtimeWS]` | WebSocket 连接没有到达后端 | 检查 URL、Header、代理设置 |
| 音频发送了但后端没看到 | 可能在某个中间层丢失 | 抓包检查实际发送的数据 |
| 说话但听不到模型回复 | 模型没有生成或 TTS 失败 | 查看后端 TTS 日志,检查 LLM 回复 |

---

## 📊 调试信息收集清单

遇到问题时,请收集以下信息:

- [ ] **后端日志**:
  ```
  - [VolcRealtime] 相关日志 ✓ / ✗
  - [RealtimeWS] 相关日志 ✓ / ✗
  - 是否看到 "connection established" ✓ / ✗
  ```

- [ ] **Android 日志**:
  ```
  - WebSocket 连接事件 (Connected/Disconnected)
  - 发送的事件类型 (session.create, input_audio_buffer.append)
  - 接收的事件类型 (session.created, transcription.*)
  - 任何错误消息
  ```

- [ ] **网络抓包**:
  ```
  - WebSocket 握手的实际 Header
  - 是否只有 X-Api-Key
  - 连接后发送的第一条消息内容
  ```

- [ ] **设备状态**:
  ```
  - 麦克风权限是否授予
  - 麦克风是否被其他应用占用
  - 网络是否正常 (Ping / DNS)
  ```

---

## 👥 如需帮助

请提供上述调试信息清单中的全部项目,这样可以快速定位问题!

