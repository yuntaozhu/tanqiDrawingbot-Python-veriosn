# 豆包 API 优先调用 - 代码修改详解

## 📂 文件位置
`src/business_logic.py`

---

## 修改 1: stream_chat_llm() 函数

### 📍 位置
**约第 230-250 行**

### ❌ 当前代码(错误)
```python
async def stream_chat_llm(user_text: str):
    """Streams chat tokens from DeepSeek or fallback provider."""
    deepseek = DeepSeekAPI.get_instance()
    system_instruction = "你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。请与小朋友进行顺畅好玩的互动聊天，保持简短、充满童趣，控制在 3-5 句话内。"

    if deepseek.client:  # ❌ 错误:优先 DeepSeek
        try:
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

    fallback_text = "宝贝你好呀！我是小探宝，今天你想和我聊什么呢？"
    for char in fallback_text:
        yield char
        await asyncio.sleep(0.02)
```

### ✅ 修改后(正确)
```python
async def stream_chat_llm(user_text: str):
    """Streams chat tokens from Doubao or fallback provider."""
    doubao = DoubaoAPI.get_instance()
    deepseek = DeepSeekAPI.get_instance()
    system_instruction = "你是一位极其温柔、懂得儿童心理学的幼儿园特级教师，名字叫'小探宝'。请与小朋友进行顺畅好玩的互动聊天，保持简短、充满童趣，控制在 3-5 句话内。"

    # ✅ 优先使用豆包
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

## 修改 2: process_llm_interaction() 中的音频处理部分

### 📍 位置
**约第 260-300 行**，在处理 `isinstance(prompt_input, bytes)` 的部分

### ❌ 当前代码(错误)
```python
if isinstance(prompt_input, bytes):
    # High-speed modular pipeline: Transcribe via SiliconFlow first, then send to text model
    print(f"[DEBUG] [FAST_PATH] Transcribing audio with fast STT first...")
    stt_start = time.time()
    user_text = deepseek.transcribe_audio(prompt_input)
    print(f"[DEBUG] [FAST_PATH] STT took {time.time() - stt_start:.2f}s. Result: '{user_text}'")
    
    if not user_text:
        res_data = {
            "user_transcript": "",
            "assistant_reply": "对不起宝贝，我没听清，能不能请你再说一遍呀？",
            "requires_drawing": False,
            "drawing_prompt": "",
            "psych_metrics": {
                "detected_emotions": ["困惑"],
                "linguistic_richness_score": 0.0,
                "cognitive_milestone_ref": "无",
                "attention_span_seconds": 15,
                "key_interests": [],
                "requires_attention": False
            }
        }
    else:
        res_data = None
        if deepseek.client:  # ❌ 错误:优先 DeepSeek
            try:
                print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model...")
                llm_start = time.time()
                res_data = deepseek.unified_text_chat(user_text)
                print(f"[DEBUG] [FAST_PATH] DeepSeek Text-to-JSON took {time.time() - llm_start:.2f}s")
            except Exception as ds_err:
                print(f"[WARNING] [FAST_PATH] DeepSeek text-to-JSON failed: {ds_err}, trying Doubao...")
        
        if not res_data:  # 只有 DeepSeek 失败才用豆包
            print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model...")
            llm_start = time.time()
            res_data = doubao.unified_text_chat(user_text)
            print(f"[DEBUG] [FAST_PATH] Doubao Text-to-JSON took {time.time() - llm_start:.2f}s")
```

### ✅ 修改后(正确)
```python
if isinstance(prompt_input, bytes):
    # High-speed modular pipeline: Transcribe via SiliconFlow first, then send to text model
    print(f"[DEBUG] [FAST_PATH] Transcribing audio with fast STT first...")
    stt_start = time.time()
    user_text = deepseek.transcribe_audio(prompt_input)
    print(f"[DEBUG] [FAST_PATH] STT took {time.time() - stt_start:.2f}s. Result: '{user_text}'")
    
    if not user_text:
        res_data = {
            "user_transcript": "",
            "assistant_reply": "对不起宝贝，我没听清，能不能请你再说一遍呀？",
            "requires_drawing": False,
            "drawing_prompt": "",
            "psych_metrics": {
                "detected_emotions": ["困惑"],
                "linguistic_richness_score": 0.0,
                "cognitive_milestone_ref": "无",
                "attention_span_seconds": 15,
                "key_interests": [],
                "requires_attention": False
            }
        }
    else:
        res_data = None
        
        # ✅ 优先使用豆包
        if doubao.client:
            try:
                print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model...")
                llm_start = time.time()
                res_data = doubao.unified_text_chat(user_text)
                print(f"[DEBUG] [FAST_PATH] Doubao Text-to-JSON took {time.time() - llm_start:.2f}s")
            except Exception as db_err:
                print(f"[WARNING] [FAST_PATH] Doubao text-to-JSON failed: {db_err}, trying DeepSeek...")
                res_data = None
        
        # ⚠️ DeepSeek 作为备用
        if not res_data and deepseek.client:
            try:
                print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model (fallback)...")
                llm_start = time.time()
                res_data = deepseek.unified_text_chat(user_text)
                print(f"[DEBUG] [FAST_PATH] DeepSeek Text-to-JSON took {time.time() - llm_start:.2f}s")
            except Exception as ds_err:
                print(f"[WARNING] [FAST_PATH] DeepSeek text-to-JSON failed: {ds_err}")
                res_data = None
```

---

## 修改 3: process_llm_interaction() 中的文本处理部分

### 📍 位置
**约第 300-330 行**，在 `else:` (处理非 bytes 输入) 的部分

### ❌ 当前代码(错误)
```python
else:
    res_data = None
    if deepseek.client:  # ❌ 错误:优先 DeepSeek
        try:
            print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model (text input)...")
            res_data = deepseek.unified_text_chat(prompt_input)
        except Exception as ds_err:
            print(f"[WARNING] [CORE] DeepSeek text chat failed: {ds_err}")
    if not res_data:  # 只有 DeepSeek 失败才用豆包
        print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model (text input)...")
        res_data = doubao.unified_text_chat(prompt_input)
```

### ✅ 修改后(正确)
```python
else:
    res_data = None
    
    # ✅ 优先使用豆包
    if doubao.client:
        try:
            print(f"[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model (text input)...")
            res_data = doubao.unified_text_chat(prompt_input)
        except Exception as db_err:
            print(f"[WARNING] [CORE] Doubao text chat failed: {db_err}, trying DeepSeek...")
            res_data = None
    
    # ⚠️ DeepSeek 作为备用
    if not res_data and deepseek.client:
        try:
            print(f"[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model (text input, fallback)...")
            res_data = deepseek.unified_text_chat(prompt_input)
        except Exception as ds_err:
            print(f"[WARNING] [CORE] DeepSeek text chat failed: {ds_err}")
            res_data = None
```

---

## 修改 4: generate_growths_summary() - 已正确,无需修改

✅ 这个函数已经是豆包优先了:

```python
if doubao.client:
    res = doubao.client.chat.completions.create(...)  # ✅ 豆包优先
else:
    res = deepseek.generate_text(...)  # ✅ DeepSeek 备用
```

---

## 修改 5: async_generate_drawing() - 已正确,无需修改

✅ 这个函数已经是豆包优先了:

```python
doubao = DoubaoAPI.get_instance()
if doubao.client:
    urls = doubao.generate_image(subject)  # ✅ 豆包优先
    
result = generate_image_with_fallback(subject)  # ✅ 备用
```

---

## 📊 修改汇总

| 函数 | 修改前 | 修改后 | 状态 |
|------|--------|--------|------|
| `stream_chat_llm()` | DeepSeek 优先 | **豆包优先** ⭐ | 需要修改 |
| `process_llm_interaction()` - 音频 | DeepSeek 优先 | **豆包优先** ⭐ | 需要修改 |
| `process_llm_interaction()` - 文本 | DeepSeek 优先 | **豆包优先** ⭐ | 需要修改 |
| `generate_growths_summary()` | 豆包优先 | 豆包优先 | ✅ 已正确 |
| `async_generate_drawing()` | 豆包优先 | 豆包优先 | ✅ 已正确 |

---

## 🔑 关键改动点

### 改动原则
1. **将豆包(`doubao.client`)检查移到最前面**
2. **只有豆包失败时才检查 DeepSeek**
3. **添加清晰的日志标记**:
   - `[DEBUG]` - 表示豆包优先
   - `[WARNING]` - 表示豆包失败,降级到 DeepSeek
   - `(fallback)` - 表示这是备用方案

### 日志输出示例

**正常情况**(豆包成功):
```
[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model...
[DEBUG] [FAST_PATH] Doubao Text-to-JSON took 0.45s
```

**豆包失败,降级到 DeepSeek**:
```
[DEBUG] [FAST_PATH] Querying Doubao text-to-JSON model...
[WARNING] [FAST_PATH] Doubao text-to-JSON failed: ..., trying DeepSeek...
[DEBUG] [FAST_PATH] Querying DeepSeek text-to-JSON model (fallback)...
[DEBUG] [FAST_PATH] DeepSeek Text-to-JSON took 0.38s
```

---

## ✅ 部署清单

- [ ] 复制本文件给 AI
- [ ] AI 修改 src/business_logic.py 的 3 个位置
- [ ] 验证修改无语法错误
- [ ] 提交到 GitHub: `git commit -m "feat: prioritize Doubao API over DeepSeek"`
- [ ] 等待 Railway 自动部署
- [ ] 查看日志,验证豆包被优先调用
- [ ] 检查 DNS 日志:应该主要是 `api.doubao.com`,很少或没有 `api.deepseek.com`


