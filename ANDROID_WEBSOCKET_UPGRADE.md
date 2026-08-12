# 📱 Android 端 Volcengine Realtime WebSocket 升级指南 (新版控制台)

## 🔴 问题症状

WebSocket 连接失败,收到以下错误:
- `javax.net.ssl.SSLException: Received fatal alert: handshake_failure`
- `WebSocketException: 401 Unauthorized`
- `HTTP 401` 握手错误

## ✅ 根本原因

后端已从**旧版控制台认证方式** (需要 4 个 Header) 升级到**新版控制台认证方式** (仅需 1 个 Header)。

**旧版** → **新版** 的变化:
| 方面 | 旧版 (已过期) | 新版 (当前) |
|------|------------|----------|
| **控制台** | 火山引擎语音技术控制台 (旧版) | 火山引擎语音技术控制台 (新版) |
| **认证方式** | App ID + Access Token + Resource ID + App Key (4 个 Header) | API Key (1 个 Header) |
| **URL** | `wss://openspeech.bytedance.com/api/v3/realtime/dialogue` | `wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue` |
| **模型版本** | 旧版端到端实时语音 | Seeduplex 全双工端到端实时语音 |

---

## 🎯 Android 端修改步骤

### 第一步: 更新 WebSocket 连接参数

#### ❌ 修改前 (旧版 - 已弃用)
```kotlin
val headers = mapOf(
    "X-Api-App-ID" to appId,                    // ❌ 删除
    "X-Api-Access-Key" to token,                // ❌ 删除
    "X-Api-Resource-Id" to "volc.speech.dialog", // ❌ 删除
    "X-Api-App-Key" to "PlgvMymc7f3tQnJ6"      // ❌ 删除
)
val url = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue" // ❌ 错误 URL
webSocket = WebSocketFactory().createSocket(url, headers)
```

#### ✅ 修改后 (新版)
```kotlin
val headers = mapOf(
    "X-Api-Key" to apiKey // ✅ 仅需这一个 (来自后端 config endpoint)
)
val url = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue" // ✅ 新 URL
webSocket = WebSocketFactory().createSocket(url, headers)
```

---

### 第二步: 从后端获取凭证 (而不是硬编码)

#### 调用后端 Config Endpoint
```kotlin
suspend fun getRealtimeConfig(deviceToken: String): RealtimeConfig {
    val response = httpClient.get("https://your-api.com/api/device/v1/realtime-config") {
        header("x-device-token", deviceToken)
        header("Content-Type", "application/json")
    }
    return response.body<RealtimeConfig>()
}

// 数据类
data class RealtimeConfig(
    val success: Boolean,
    val api_key: String,
    val realtime_api_v3_duplex: DuplexConfig
)

data class DuplexConfig(
    val url: String,        // "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
    val api_key: String,    // API Key
    val model: String       // "1.2.6.1"
)
```

#### 响应示例
```json
{
  "success": true,
  "api_key": "6b1a439e-adc2-4cc8-8300-2be1170fff2e",
  "realtime_api_v3_duplex": {
    "url": "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue",
    "api_key": "6b1a439e-adc2-4cc8-8300-2be1170fff2e",
    "model": "1.2.6.1"
  }
}
```

#### 使用配置连接
```kotlin
val config = getRealtimeConfig(deviceToken)
val headers = mapOf(
    "X-Api-Key" to config.api_key  // ✅ 使用后端返回的 API Key
)
val wsUrl = config.realtime_api_v3_duplex.url  // ✅ 使用后端返回的 URL
webSocket = WebSocketFactory().createSocket(wsUrl, headers)
```

---

### 第三步: 检查并清理代码中的硬编码值

#### 搜索和替换清单
| 搜索关键字 | 操作 | 原因 |
|-----------|------|------|
| `X-Api-App-ID` | ❌ 删除所有使用 | 新版本不需要 |
| `X-Api-Access-Key` | ❌ 删除所有使用 | 新版本不需要 |
| `X-Api-Resource-Id` | ❌ 删除所有使用 | 新版本不需要 |
| `X-Api-App-Key` | ❌ 删除所有使用 | 新版本不需要 |
| `PlgvMymc7f3tQnJ6` | ❌ 删除所有硬编码 | 旧版固定值,新版不用 |
| `api/v3/realtime/dialogue` | ✅ 改为 `api/v3/duplex/realtime/dialogue` | 升级到全双工版本 |
| 硬编码的 appId/token | ✅ 改为从后端 `/api/device/v1/realtime-config` 获取 | 提高安全性,便于更新 |

---

### 第四步: WebSocket 事件处理

新版本事件格式完全兼容,但需要注意以下几点:

#### ✅ Session 创建事件 - 改用 `session.create`
```json
{
  "type": "session.create",
  "session": {
    "model": "1.2.6.1",
    "instructions": "你是一个友好的儿童绘画助手",
    "audio": {
      "input": {
        "format": {
          "sample_rate": 16000,
          "encoding": "pcm"
        }
      },
      "output": {
        "format": {
          "sample_rate": 24000,
          "encoding": "pcm_s16le"
        }
      },
      "voice": "zh_male_tiancaitongsheng_uranus_bigtts"
    }
  }
}
```

#### ✅ 音频输入 - 保持不变
```json
{
  "type": "input_audio_buffer.append",
  "audio": "<base64_encoded_pcm_audio>"
}
```

#### ✅ 音频提交 - 新增可选事件 (用于标记用户输入结束)
```json
{
  "type": "input_audio_buffer.commit"
}
```

#### ✅ 下行事件类型 (来自服务器)
```
Session Events:
  - session.created      : 会话已创建
  - session.updated      : 会话已更新
  - session.closed       : 会话已关闭

ASR Events (语音识别):
  - conversation.item.input_audio_transcription.started   : 检测到用户说话开始
  - conversation.item.input_audio_transcription.delta     : 识别中间结果
  - conversation.item.input_audio_transcription.completed : 识别完成

Chat Events (文本生成):
  - response.output_text.delta : 模型回复文本片段
  - response.output_text.done  : 模型回复文本完成

TTS Events (语音合成):
  - response.output_audio.started : 合成音频开始
  - response.output_audio.delta   : 音频片段 (Base64)
  - response.output_audio.done    : 音频合成完成

Usage Events:
  - response.done : 一轮交互完成

Error Events:
  - error : 错误事件
```

---

### 第五步: 快速检查清单

- [ ] 所有 Header 改为仅使用 `X-Api-Key`
- [ ] WebSocket URL 改为 `.../api/v3/duplex/realtime/dialogue` (注意 `duplex`)
- [ ] 从后端 `/api/device/v1/realtime-config` 获取凭证 (不硬编码)
- [ ] 删除所有硬编码的 appId/token/resourceId
- [ ] 删除所有 `X-Api-App-ID`, `X-Api-Access-Key`, `X-Api-Resource-Id`, `X-Api-App-Key`
- [ ] 更新 session 创建事件为 `session.create` 格式
- [ ] 测试连接,确保不再收到 401 错误
- [ ] 验证音频双向通信正常工作 (用户说话 → ASR 识别 → 模型回复 → TTS 合成)
- [ ] 验证文本完整性 (不缺少字符或事件)

---

## 🔧 常见错误排查

### 错误 1: Still Getting HTTP 401
```
错误信息: WebSocketException: 401 Unauthorized
```
**原因**: 仍在使用旧的多 Header 方式,或 API Key 错误

**修复**:
1. 确保仅传递 `X-Api-Key` Header,删除其他所有 `X-Api-*` Header
2. 验证从后端 config endpoint 获取的 API Key 是否正确
3. 检查是否硬编码了过期的 token

### 错误 2: WebSocket URL 不对
```
错误信息: Connection refused 或 404
```
**原因**: 使用了旧的 `/api/v3/realtime/dialogue` URL

**修复**: 改为 `/api/v3/duplex/realtime/dialogue` (注意多了 `duplex`)

### 错误 3: Connection Refused / Timeout
```
错误信息: java.net.ConnectException: Connection refused
```
**原因**: 后端 config endpoint 返回的 URL 被忽略,使用了硬编码 URL

**修复**: 
1. 总是从后端 config endpoint 获取 `url` 和 `api_key`
2. 不要硬编码 WebSocket URL
3. 验证后端 `/api/device/v1/realtime-config` 是否正常返回数据

### 错误 4: 收不到音频或文本
```
现象: 连接成功,但没有下行事件或事件不完整
```
**原因**: 新版本事件格式与旧版本不同

**修复**:
1. 确保监听所有新的事件类型 (如 `conversation.item.input_audio_transcription.*`)
2. 检查 session 创建事件是否使用了 `session.create` (而不是旧的 `session.start`)
3. 确保正确处理 Base64 编码的音频数据

---

## 📚 API 参考

### 后端提供的 Config Endpoint

```
GET /api/device/v1/realtime-config

请求头:
  x-device-token: <your-device-token>
  Content-Type: application/json

响应状态码: 200

响应体:
{
  "success": true,
  "api_key": "6b1a439e-adc2-4cc8-8300-2be1170fff2e",
  "realtime_api_v3_duplex": {
    "url": "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue",
    "api_key": "6b1a439e-adc2-4cc8-8300-2be1170fff2e",
    "model": "1.2.6.1"
  }
}
```

### WebSocket 连接参数

```
URL: wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue

请求头 (Header):
  X-Api-Key: <api_key_from_config_endpoint>

示例:
  X-Api-Key: 6b1a439e-adc2-4cc8-8300-2be1170fff2e
```

---

## ⏱️ 预期结果

修改完成后,应该看到以下现象:

- ✅ WebSocket 连接成功 (不再收到 401 错误)
- ✅ 立即收到 `session.created` 事件
- ✅ 发送音频后,收到 `conversation.item.input_audio_transcription.*` 事件
- ✅ 模型回复文本通过 `response.output_text.delta` 事件流式返回
- ✅ 模型回复音频通过 `response.output_audio.delta` 事件流式返回 (Base64 编码的 PCM)
- ✅ 整个对话流程流畅,无缺失或重复事件

---

## 👥 如有问题

如果修改后仍然遇到问题:

### 调试步骤
1. **抓包检查**: 使用 Charles 或 Wireshark 抓包,检查实际发送的 WebSocket Header
   - 确认仅有 `X-Api-Key` Header
   - 确认 API Key 值正确
   - 确认 URL 是 `/duplex/realtime/dialogue`

2. **验证后端配置**:
   - 调用 `GET /api/device/v1/realtime-config` 获取配置
   - 检查返回的 `api_key` 和 `url` 是否正确
   - 确保后端部署了最新代码 (PR #18, #19)

3. **查看后端日志**:
   - 后端应该有 `[VolcRealtime] WebSocket connection established successfully.` 日志
   - 如果仍有 401,后端日志会显示 `[VolcRealtime] Failed to connect: HTTP 401`

4. **验证事件处理**:
   - 确保所有事件类型都有对应的处理函数
   - 检查是否正确解析 JSON 事件
   - 验证音频 Base64 解码是否正确

### 联系支持
如果以上步骤都无法解决,请提供:
- [ ] 抓包文件 (WebSocket Header 部分)
- [ ] 后端日志 (特别是 `[VolcRealtime]` 部分)
- [ ] Android 端接收到的错误栈跟踪
- [ ] 调用的后端 config endpoint 返回的完整 JSON

---

## 📋 变更历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-12 | 1.0 | 初始版本,文档化从旧版到新版的升级指南 |

---

## 📖 参考资源

- [Volcengine 新版控制台文档](https://console.volcengine.com/speech/new)
- [Volcengine Realtime API 文档](https://www.volcengine.com/docs/6561/2534847?lang=zh)
- [API Key 管理](https://console.volcengine.com/speech/new/setting/apikeys)

