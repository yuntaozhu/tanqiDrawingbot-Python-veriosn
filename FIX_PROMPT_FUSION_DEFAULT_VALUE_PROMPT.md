# 🤖 AI 修复提示词：解决提示词融合默认值问题

## 问题简述

**现象**: 用户句2 "把这个画面画出来" 导致生成彩虹桥而非查理士王小猎犬

**根本原因**:
1. 句2 被识别为 MODIFY (Bug #1)
2. 融合结果仍为模糊的 "把这个画面画出来..." (Bug #3)
3. LLM 扩展超时,本地扩展生成随机内容
4. 错误内容被缓存 (Bug #2)

**部署日志证据**:
```
[ASYNC_DRAW] Using fused prompt: 把这个画面画出来...
[PROMPT_EXPAND] LLM expansion failed (timeout)
Falling back to: '在五彩斑斓的彩虹桥...把这个画面画出来'
```

---

## 修复任务

### 任务 1: 改进操作识别 (2 分钟) ⭐

**文件**: `src/operation_recognizer.py` 第 42 行

```python
# 修改前
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "变", "改一下", "把"]

# 修改后
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
# ↑ 删除 "把" (中文介词,易误判)
```

### 任务 2: 检测和处理模糊输入 (10 分钟) ⭐⭐

**文件**: `src/prompt_fusion.py`

```python
def _is_vague_input(text: str) -> bool:
    """检测输入是否太模糊"""
    vague_patterns = ["把这个", "把那个", "这个", "那个", "它", "就是"]
    return any(p in text for p in vague_patterns)

# 在 MODIFY 融合块 (第 47-50 行) 中修改:
elif operation_type == "modify":
    # 检测是否是模糊的修改指令
    if _is_vague_input(current_user_text):
        # 模糊输入,保持前一张图
        if previous_prompt:
            fused_prompt = previous_prompt
        else:
            fused_prompt = "重新绘制之前描述的内容"
        logger.warning(f"[FUSION] Vague input detected, using previous prompt")
    else:
        # 具体的修改指令
        elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
        fused_prompt = f"基于包含 {elements_str} 的已有画面...进行修改:{current_user_text}。"
```

### 任务 3: 改进 LLM 扩展降级策略 (5 分钟)

**查找包含 `local_expand` 或 `fallback` 的代码** (可能在 business_logic.py)

```python
# 修改前
try:
    expanded_prompt = await llm_expand_prompt(prompt, timeout=10)
except TimeoutError:
    # ❌ 超时时调用本地扩展,生成随机内容!
    expanded_prompt = local_imaginative_expand(prompt)

# 修改后
try:
    expanded_prompt = await llm_expand_prompt(prompt, timeout=10)
except TimeoutError:
    # ✅ 超时时保持原提示词,不添加随机内容
    logger.warning(f"[PROMPT_EXPAND] LLM timeout, using original prompt")
    expanded_prompt = prompt  # 关键修复!
```

### 任务 4: 改进缓存判断逻辑 (5 分钟)

**文件**: `src/routes/device.py` (缓存调用处)

```python
def _should_cache_prompt(prompt: str) -> bool:
    """检查提示词是否值得缓存"""
    # 太短的不缓存
    if len(prompt) < 8:
        return False
    
    # 包含模糊指代的不缓存
    vague_patterns = ["这个", "那个", "它", "把这个", "把那个"]
    if any(p in prompt for p in vague_patterns):
        return False
    
    # 看起来像随机扩展的不缓存
    if "彩虹" in prompt and "把这个" in prompt:
        return False
    
    return True

# 在缓存调用前添加检查:
if should_cache and _should_cache_prompt(drawing_prompt):
    ConversationManager.save_drawing_record(
        job_id=job_id,
        device_token=token,
        operation_type=operation["type"],
        scene_prompt=drawing_prompt,
        image_url=action_result.get("image_url")
    )
```

---

## 修改顺序

1. **任务 1** (2 min): 改进操作识别 - 根本解决
2. **任务 2** (10 min): 检测模糊输入 - 防御性修复
3. **任务 3** (5 min): 改进扩展降级 - 防止随机内容
4. **任务 4** (5 min): 改进缓存判断 - 避免缓存坏数据

---

## 测试用例

```
测试 1: 原问题
输入1: "查理士王小猎犬躺在床边" → ✅ 生成小猎犬图像
输入2: "把这个画面画出来"
修复前: ❌ 生成彩虹桥
修复后: ✅ 生成查理士王小猎犬躺在床边

测试 2: 真正的修改应该仍然工作
输入1: "画一个红色小狗" → ✅ 生成红色小狗
输入2: "把小狗改成蓝色" → ✅ 生成蓝色小狗

测试 3: 缓存检查
缓存中应有: "查理士王小猎犬躺在床边" ✅
缓存中不应有: "把这个画面画出来" ✅
```

---

## 检查清单

- [ ] 任务 1: 修改 operation_recognizer.py
- [ ] 任务 2: 修改 prompt_fusion.py  
- [ ] 任务 3: 修改 business_logic.py (或相关文件)
- [ ] 任务 4: 修改 routes/device.py
- [ ] 运行所有测试用例
- [ ] 部署日志中没有 "彩虹桥" 随机内容
- [ ] 缓存中没有模糊提示词

---

**修复优先级**: 🔴 **高** - 影响多轮对话  
**修复时间**: 22 分钟代码 + 15 分钟测试  
**风险**: 🟢 **低** - 改进启发式规则

