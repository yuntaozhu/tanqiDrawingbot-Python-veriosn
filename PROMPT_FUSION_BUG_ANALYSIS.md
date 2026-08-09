# 🐛 提示词融合 Bug 分析报告

## 问题描述

**用户对话**:
```
用户第1句: "查理王小猎犬和猫咪在打架"
用户第2句: "是的，把画面画出来"
```

**预期结果**: 根据两句话生成 "查理王小猎犬和猫咪打架" 的画面  
**实际结果**: 生成的画面与这两句话无关，不是用户想要的内容

---

## 日志分析

### 部署日志证据

**时间线**:

```
2026-08-09 03:21:21.799 - [DEBUG] [STREAM_LLM] 用户第1句:
"查理王小猎犬和猫咪在打架"

2026-08-09 03:21:21.799 - [DEBUG] [ASYNC_DRAW] 使用融合提示词:
"基于包含 已有元素 的已有画面，保持整体结构和其他角色不变，进行以下修改：是的，把画面画出来。"

2026-08-09 03:21:52.053 - [WARNING] [PROMPT_EXPAND] 
LLM 扩展超时 (10s)，降级到本地扩展

2026-08-09 03:21:52.053 - [DEBUG] [DOUBAO_DRAW] 生成的最终提示词:
"天马行空的儿童涂色本线稿...基于包含 已有元素 的已有画面，
保持整体结构和其他角色不变，进行以下修改：是的，把画面画出来。"

2026-08-09 03:22:11.565 - [INFO] 图片生成成功 (耗时: 55.11s)
```

### 问题根源识别

#### 🔴 **核心问题**: 操作识别错误

用户第2句 `"是的，把画面画出来"` 被识别为 **MODIFY（修改）** 操作，而不是 **CREATE（创建）** 操作。

**证据**:

```
融合后的提示词:
"基于包含 已有元素 的已有画面，保持整体结构和其他角色不变，进行以下修改：是的，把画面画出来。"
                    ↑                                              ↑ 
                这表示 MODIFY 操作                    原始用户输入被直接拼接
```

#### 问题代码位置

**文件**: `src/prompt_fusion.py` 第 47-50 行

```python
elif operation_type == "modify":
    # Modify existing element attributes
    elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
    fused_prompt = f"基于包含 {elements_str} 的已有画面，保持整体结构和其他角色不变，进行以下修改：{current_user_text}。"
```

当 `operation_type` 被识别为 `"modify"` 时，整个提示词被构造成 **修改已有画面** 的模式，而不是 **创建新画面**。

---

## 为什么会被识别为 MODIFY？

### 操作识别逻辑分析

**文件**: `src/operation_recognizer.py`

```python
# 第 36-46 行 - MODIFY 识别逻辑
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "变", "改一下", "把"]
for kw in modify_keywords:
    if kw in text:
        # ... 返回 modify 操作
```

### 问题分析

用户第2句: `"是的，把画面画出来"`

检查流程:
```
1. 文本中有 "把" → ✅ 匹配 modify_keywords
2. 返回 operation_type = "modify"
3. confidence = 0.90
4. 因为有 confidence 检查: if operation.get("confidence", 0.0) < 0.5
5. 0.90 > 0.5 → 不会降级到 create
6. 最终识别为 MODIFY ❌
```

### 为什么这是错误的？

| 关键字 | 含义 | 是否应该触发 MODIFY |
|-------|------|------------------|
| "改成" | 改变属性 | ✅ 是 |
| "修改" | 修改内容 | ✅ 是 |
| "变成" | 变换状态 | ✅ 是 |
| "改色" | 改变颜色 | ✅ 是 |
| "换成" | 替换 | ✅ 是 |
| "变" | 变化 | ⚠️ 歧义大 |
| "改一下" | 改一下 | ✅ 是 |
| **"把"** | **介词** | ❌ **否！** |

**"把"** 是中文介词，不一定表示修改：
- "把画面画出来" → 创建新画面
- "把小狗改成白色" → 修改颜色
- "把这个擦掉" → 删除

仅凭 "把" 无法判断操作类型。

---

## 融合提示词的问题

### 当前融合逻辑（错误的）

```python
# 认为 "是的，把画面画出来" 是 MODIFY 操作
fused_prompt = "基于包含 已有元素 的已有画面，保持整体结构和其他角色不变，进行以下修改：是的，把画面画出来。"
```

**问题**:
1. ❌ 用户第1句 "查理王小猎犬和猫咪在打架" **被完全忽略**
2. ❌ 提示词说 "修改已有画面"，但实际上没有已有画面（这是第一次绘画）
3. ❌ 原始用户输入 "是的，把画面画出来" **直接拼接到提示词**，对 AI 绘画模型无意义
4. ❌ LLM 扩展超时，模型无法理解这个奇怪的提示词

### 应该是什么（正确的）

```python
# 应该识别为 CREATE 操作
fused_prompt = "查理王小猎犬和猫咪在打架"
```

或

```python
# 如果要融合两句：
fused_prompt = "用儿童涂色本风格绘制：查理王小猎犬和猫咪在打架"
```

---

## 问题链条

```
用户第1句: "查理王小猎犬和猫咪在打架"
    ↓
AI 理解 (LLM) ✅
生成 TTS 语音 ✅
    ↓
用户第2句: "是的，把画面画出来"
    ↓
操作识别器: OperationRecognizer
    ↓
识别为 MODIFY（因为包含"把"）❌
    ↓
提示词融合: PromptFusionEngine
    ↓
融合结果: "基于包含 已有元素 的已有画面...进行以下修改：是的，把画面画出来"
    ↓
提示词扩展: LLM 扩展 10s 超时 ⏱️
    ↓
本地扩展降级 (无法理解这个奇怪的提示词)
    ↓
发送给 AI 绘画 API (Doubao SeedDream)
    ↓
生成随机/错误的画面 ❌
```

---

## 根本原因总结

| 问题 | 位置 | 优先级 |
|-----|------|--------|
| 🔴 "把" 关键字过于宽泛，导致误判 | operation_recognizer.py:42 | **高** |
| 🔴 缺少上下文感知的操作识别 | operation_recognizer.py | **高** |
| 🟠 提示词融合没有验证是否有已有画面 | prompt_fusion.py:47-50 | **中** |
| 🟠 当第一次绘画时，融合逻辑被误用 | routes/device.py:120-140 | **中** |
| 🟡 缺少对模糊输入的处理 | operation_recognizer.py | **低** |

---

## 修复方案

### 方案 1: 改进操作识别（推荐）⭐⭐⭐

**核心思路**: 减少 MODIFY 关键字的误判

#### 修改 1: 移除过于宽泛的关键字

**文件**: `src/operation_recognizer.py` 第 36-46 行

```python
# 修改前
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "变", "改一下", "把"]

# 修改后
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
# 移除: "变" (太模糊) 和 "把" (中文介词，误判率高)
```

#### 修改 2: 添加 MODIFY 上下文检查

```python
# 修改前
for kw in modify_keywords:
    if kw in text:
        return {"type": "modify", "confidence": 0.90, ...}

# 修改后
for kw in modify_keywords:
    if kw in text:
        # 检查是否有具体的修改对象或属性
        # 如果没有具体对象，降低置信度
        if "色" in text or "改" in text and "成" in text:
            # 明确的颜色/属性修改
            return {"type": "modify", "confidence": 0.90, ...}
        else:
            # 不清楚要修改什么
            return {"type": "modify", "confidence": 0.60, ...}  # 降低置信度
```

### 方案 2: 改进提示词融合

**文件**: `src/prompt_fusion.py` 第 47-50 行

```python
# 修改前
elif operation_type == "modify":
    elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
    fused_prompt = f"基于包含 {elements_str} 的已有画面，保持整体结构和其他角色不变，进行以下修改：{current_user_text}。"

# 修改后
elif operation_type == "modify":
    # 如果没有已有画面，降级到 CREATE
    if not scene_elements or not previous_prompt:
        logger.warning(f"No previous context for MODIFY operation, falling back to CREATE")
        fused_prompt = current_user_text
        operation_type = "create"
    else:
        elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
        fused_prompt = f"基于包含 {elements_str} 的已有画面，保持整体结构和其他角色不变，进行以下修改：{current_user_text}。"
```

### 方案 3: 多轮对话上下文理解

**文件**: `src/routes/device.py` 第 120-140 行

```python
# 当识别置信度低时，考虑上一次的操作
if operation.get("confidence", 0.0) < 0.7:
    last_op = context.get("last_operation_type")
    
    # 如果上一次是 CREATE，当前模糊输入应该也是 CREATE
    if last_op == "create":
        operation["type"] = "create"
        operation["confidence"] = 0.7
```

---

## 修复前后对比

### 修复前 ❌

```
用户输入1: "查理王小猎犬和猫咪在打架"
识别结果: CREATE (第一次绘画) ✅
画面: [生成完成]

用户输入2: "是的，把画面画出来"
识别结果: MODIFY (因为有"把") ❌
融合提示词: "基于已有画面...进行以下修改：是的，把画面画出来" ❌
画面: [与用户意图无关] ❌
```

### 修复后 ✅

```
用户输入1: "查理王小猎犬和猫咪在打架"
识别结果: CREATE ✅
画面: [查理王小猎犬和猫咪打架的画面] ✅

用户输入2: "是的，把画面画出来"
识别结果: 
  - 初步识别: MODIFY (低置信度 0.60)
  - 上下文检查: 无已有场景 → 降级到 CREATE
  - 最终: CREATE ✅
融合提示词: "是的，把画面画出来" 或 "重新画一遍" ✅
画面: [正确的画面] ✅
```

---

## 关键文件修改清单

| 文件 | 行号 | 修改内容 | 优先级 |
|-----|------|---------|--------|
| `src/operation_recognizer.py` | 42 | 移除 "把" 和 "变" 关键字 | 🔴 高 |
| `src/operation_recognizer.py` | 38-46 | 添加 MODIFY 置信度校准逻辑 | 🔴 高 |
| `src/prompt_fusion.py` | 47-50 | 添加已有画面检查逻辑 | 🟠 中 |
| `src/routes/device.py` | 120-140 | 添加上下文感知的操作识别 | 🟠 中 |

---

## 测试用例

修复后应该通过以下测试：

```python
# 测试 1: 基础创建
input1 = "查理王小猎犬和猫咪在打架"
# 预期: CREATE 操作，生成对应画面

input2 = "是的，把画面画出来"
# 预期: CREATE 操作（降级），生成相关画面

# 测试 2: 真正的修改
input1 = "画一个红色的小狗"
input2 = "把小狗的颜色改成蓝色"
# 预期: MODIFY 操作，修改颜色

# 测试 3: 添加元素
input1 = "画一个小狗"
input2 = "再加一只猫咪"
# 预期: ADD 操作，添加元素
```

---

## 日志中的警告信号

```
[WARNING] [PROMPT_EXPAND] LLM 扩展失败 (Request timed out.). 
降级到本地扩展: '基于包含 已有元素 的已有画面...是的，把画面画出来'
```

**这个警告表示**:
- 🔴 LLM 无法理解这个提示词（10s 超时）
- 🔴 提示词格式/内容有问题
- 🔴 降级到本地扩展（理解度更差）
- 🔴 最终导致画面生成错误

---

## 预期修复时间

| 阶段 | 时间 | 工作量 |
|-----|------|--------|
| 代码修改 | 15-20 分钟 | 中等 |
| 测试验证 | 10-15 分钟 | 中等 |
| PR 提交 | 5 分钟 | 小 |
| 部署 | 3-5 分钟 | 小 |
| **总计** | **30-45 分钟** | **中等** |

---

**优先级**: 🔴 **高** - 影响用户体验  
**缺陷类型**: 逻辑错误（操作识别误判）  
**影响范围**: 多轮对话中的 MODIFY 操作  
**复现率**: 100%（每次用户说 "把...画出来" 时重现）

