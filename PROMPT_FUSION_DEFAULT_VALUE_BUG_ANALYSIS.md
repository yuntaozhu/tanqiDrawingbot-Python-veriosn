# 🐛 提示词融合默认值 Bug 分析报告

## 问题描述

**用户对话**:
```
用户句1: "查理士王小猎犬躺在床边"
用户句2: "把这个画面画出来"
```

**预期结果**: 生成 "查理士王小猎犬躺在床边" 的画面  
**实际结果**: 生成了 "彩虹桥和云朵乐园" 的画面,与用户意图完全无关

---

## 部署日志证据

```
[DEBUG] [ASYNC_DRAW] Using fused prompt: 把这个画面画出来...
[WARNING] [PROMPT_EXPAND] LLM expansion failed (Request timed out.)
Falling back to: '在五彩斑斓的彩虹桥和软绵绵云朵乐园里开心捉迷藏的Q版把这个画面画出来'
[DEBUG] [DOUBAO_DRAW] Generating prompt: '...在五彩斑斓的彩虹桥...把这个画面画出来'
```

---

## 根本原因分析

### 问题链条

```
Bug #1 (操作识别误判)
  "把这个画面画出来" → 识别为 MODIFY
      ↓
Bug #3 (融合默认值) - 本次发现
  融合结果: "把这个画面画出来..." (仍然模糊)
      ↓
LLM 扩展失败 (10s 超时)
  原因: 提示词太模糊
      ↓
本地扩展生成随机内容 ❌
  生成: "在彩虹桥...云朵乐园..."
      ↓
AI 绘画收到错误提示词
  生成: 彩虹桥图像 ❌
      ↓
Bug #2 (缓存误存)
  缓存: "把这个画面画出来" → 彩虹桥 ❌
```

### 三个关键问题

1. **融合逻辑处理模糊输入不当**
   - 用户句 "把这个画面画出来" 被融合后仍为模糊的形式
   - 应该从上下文恢复完整内容

2. **LLM 扩展失败处理不当**
   - 超时时调用本地扩展生成随机内容 ❌
   - 应该保持原提示词或返回错误

3. **错误内容被缓存**
   - "把这个画面画出来" 这样的模糊提示词不应被缓存
   - 导致后续使用时返回错误结果

---

## 修复方案 (4 步骤)

### 1. 改进操作识别 (2 min) - Bug #1 的修复
**文件**: operation_recognizer.py 第 42 行
```python
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
# ↑ 删除 "把" 和 "变"
```

### 2. 检测模糊输入 (10 min) - Bug #3 的直接修复
**文件**: prompt_fusion.py
```python
def _is_vague_input(text: str) -> bool:
    vague_patterns = ["把这个", "把那个", "这个", "那个"]
    return any(p in text for p in vague_patterns)

# 在 MODIFY 融合时:
if _is_vague_input(current_user_text):
    fused_prompt = previous_prompt  # 保持前一张图
```

### 3. 改进扩展降级 (5 min)
**原因**: LLM 扩展超时时不应生成随机内容
```python
# 修改前: 生成随机内容
expanded_prompt = local_imaginative_expand(prompt)

# 修改后: 保持原提示词
expanded_prompt = prompt
```

### 4. 改进缓存判断 (5 min) - 结合 Bug #2
```python
def _should_cache_prompt(prompt: str) -> bool:
    if len(prompt) < 8:
        return False
    if "这个" in prompt or "那个" in prompt:
        return False
    return True

# 只缓存高质量提示词
if _should_cache_prompt(drawing_prompt):
    cache_save(...)
```

---

## 修复后的预期结果

✅ 生成正确的查理士王小猎犬躺在床边的图像
✅ 不生成彩虹桥
✅ 不缓存模糊提示词
✅ 多轮对话质量显著提高

---

**优先级**: 🔴 **高**  
**修复时间**: 22 分钟代码 + 15 分钟测试  
**风险**: 🟢 **低**

