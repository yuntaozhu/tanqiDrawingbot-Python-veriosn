# 【豆包 API 优先调用方案】开发提示词

## 📋 问题诊断

### 现状
- DNS 日志显示所有请求都发往 `api.deepseek.com`
- 代码中同时集成了 DeepSeek 和豆包(Doubao)API
- 当前逻辑:DeepSeek 优先,豆包作为备用

### 目标
**将豆包 API 设为优先级最高,所有 LLM 调用优先使用豆包,DeepSeek 仅作备用**

---

## 🔍 代码分析

### 当前调用流程(错误)
在 `src/business_logic.py` 的 `process_llm_interaction()` 函数:

```python
# 第 ~250 行开始
if deepseek.client:  # ❌ 优先检查 DeepSeek
    try:
        res_data = deepseek.unified_text_chat(user_text)
    except Exception as ds_err:
        print(f"DeepSeek failed, trying Doubao...")

if not res_data:  # 仅当 DeepSeek 失败时才用豆包
    res_data = doubao.unified_text_chat(prompt_input)
```

### 应该改成的流程(正确)
```python
# 优先检查豆包
if doubao.client:
    try:
        res_data = doubao.unified_text_chat(user_text)
    except Exception as db_err:
        print(f"Doubao failed, trying DeepSeek...")

if not res_data and deepseek.client:  # 仅当豆包失败时才用 DeepSeek
    res_data = deepseek.unified_text_chat(user_text)
```

---

## 🎯 修改要求

### 1. 主函数:process_llm_interaction()
**文件**: `src/business_logic.py`
**函数**: `process_llm_interaction(prompt_input: Any, api_key: str, device_token: str = None)`
**行号**: 约 240-300 行

#### 修改前(当前)
```python
if deepseek.client:
    try:
        # ... DeepSeek 调用
        res_data = deepseek.unified_text_chat(user_text)
    except Exception as ds_err:
        print(f"[WARNING] [FAST_PATH] DeepSeek text-to-JSON failed: {ds_err}, trying Doubao...")

if not res_data:
    print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model...")
    res_data = doubao.unified_text_chat(user_text)
```

#### 修改后(正确)
```python
# ✅ 优先使用豆包
if doubao.client:
    try:
        print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model (audio path)...")
        res_data = doubao.unified_text_chat(user_text)
        print(f"[DEBUG] [FAST_PATH] Doubao succeeded")
    except Exception as db_err:
        print(f"[WARNING] [FAST_PATH] Doubao text-to-JSON failed: {db_err}, trying DeepSeek...")
        res_data = None

# ⚠️ 仅作为备用
if not res_data and deepseek.client:
    try:
        print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model (fallback)...")
        res_data = deepseek.unified_text_chat(user_text)
        print(f"[DEBUG] [FAST_PATH] DeepSeek succeeded")
    except Exception as ds_err:
        print(f"[WARNING] [FAST_PATH] DeepSeek text-to-JSON failed: {ds_err}")
        res_data = None
```

### 2. 其他调用点
在 `src/business_logic.py` 中还有其他地方同时使用两个 API,都需要改成豆包优先:

#### 位置 1: 生成成长总结(generate_growths_summary)
**当前代码** (约 110 行):
```python
if doubao.client:
    res = doubao.client.chat.completions.create(...)
else:
    res = deepseek.generate_text(analysis_prompt, ...)
```
✅ **这里已经是豆包优先了,无需修改**

#### 位置 2: 异步绘画生成(async_generate_drawing)
**当前代码** (约 190 行):
```python
doubao = DoubaoAPI.get_instance()
if doubao.client:
    try:
        urls = doubao.generate_image(subject)
    except Exception as e:
        print(f"Doubao draw failed: {e}")

result = generate_image_with_fallback(subject)  # 备用
```
✅ **这里已经是豆包优先了,无需修改**

#### 位置 3: 流式聊天(stream_chat_llm)
**当前代码** (约 230 行):
```python
if deepseek.client:  # ❌ 这里仍然是 DeepSeek 优先
    try:
        stream = deepseek.client.chat.completions.create(...)
    except Exception as e:
        print(f"DeepSeek stream error: {e}")

fallback_text = "..."  # 完全备用,没有豆包
```

#### 修改为:
```python
# ✅ 优先使用豆包
doubao = DoubaoAPI.get_instance()
if doubao.client:
    try:
        print(f"[DEBUG] [STREAM_LLM] Using Doubao for streaming...")
        stream = doubao.client.chat.completions.create(
            model=doubao.audio_model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text}
            ],
            stream=True,
            timeout=30
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                await asyncio.sleep(0.005)
        return
    except Exception as db_err:
        print(f"[WARNING] [STREAM_LLM] Doubao stream error: {db_err}, trying DeepSeek...")

# ⚠️ DeepSeek 作为备用
deepseek = DeepSeekAPI.get_instance()
if deepseek.client:
    try:
        print(f"[DEBUG] [STREAM_LLM] Using DeepSeek for streaming (fallback)...")
        stream = deepseek.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text}
            ],
            stream=True,
            timeout=30
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                await asyncio.sleep(0.005)
        return
    except Exception as e:
        print(f"[ERROR] [STREAM_LLM] DeepSeek stream error: {e}")

# 完全备用
fallback_text = "宝贝你好呀！我是小探宝，今天你想和我聊什么呢？"
for char in fallback_text:
    yield char
    await asyncio.sleep(0.02)
```

---

## 📝 总结:需要修改的位置

| 函数名 | 文件 | 现状 | 修改 | 优先级 |
|------|------|------|------|--------|
| `process_llm_interaction()` | src/business_logic.py | DeepSeek 优先 | ⭐⭐⭐ 改为豆包优先 | 高 |
| `stream_chat_llm()` | src/business_logic.py | DeepSeek 优先 | ⭐⭐⭐ 改为豆包优先 | 高 |
| `generate_growths_summary()` | src/business_logic.py | 豆包优先 | ✅ 无需修改 | - |
| `async_generate_drawing()` | src/business_logic.py | 豆包优先 | ✅ 无需修改 | - |

---

## 🔄 具体修改步骤

### Step 1: 打开 src/business_logic.py

### Step 2: 找到 stream_chat_llm() 函数(约 230 行)
搜索: `async def stream_chat_llm(user_text: str):`

替换整个函数为下面的代码

### Step 3: 找到 process_llm_interaction() 函数中的音频处理部分(约 250-290 行)
搜索: `if deepseek.client:` (在音频转录后)

替换该部分的 if 块为豆包优先逻辑

### Step 4: 同样处理文本输入的部分(约 290-310 行)
搜索: `else:` (处理非 bytes 的 prompt_input)

替换为豆包优先逻辑

---

## ✅ 验证修改完成

修改后，DNS 日志应该显示:
- ✅ `api.doubao.com` 的请求(豆包)
- ❌ 不再出现 `api.deepseek.com` 的正常请求
- ⚠️ 仅在豆包故障时才会出现 `api.deepseek.com`(作为备用)

---

## 📋 环境变量确认

确保这些变量已设置在 Railway:
```
ARK_API_KEY=05a5b825-69f6-40ff-93e9-7493c05e4fb0  ✅ 豆包 API Key
ARK_AUDIO_MODEL=doubao-seed-2.0-lite-260428  ✅ 豆包音频模型
ARK_DRAW_MODEL=doubao-seedream-5.0-pro-260628  ✅ 豆包绘画模型

DEEPSEEK_API_KEY=xxx  (可选,仅作备用)
```

如果豆包 API Key 未设置,DoubaoAPI 的 client 会为 None,自动降级到 DeepSeek。

---

## 🚀 部署步骤

1. **复制本提示词给 AI,让它修改代码**
2. **AI 生成完整的修改后 src/business_logic.py**
3. **替换项目中的 src/business_logic.py**
4. **提交并推送到 GitHub**
5. **等待 Railway 自动部署**
6. **查看日志,验证现在优先调用豆包 API**

---

## 🎓 补充:为什么要这样改?

**豆包的优势**:
- 响应更快(国内服务器)
- 成本更低
- 支持中文本地化更好
- 模型更新快

**DeepSeek 作为备用**:
- 提供冗余,提高可用性
- 如果豆包故障,服务仍可用


