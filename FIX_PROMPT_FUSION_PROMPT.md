# 🤖 AI 修复提示词：解决提示词融合错误

> 这份提示词针对用户对话多轮交互时，提示词融合逻辑失效导致图像生成错误的问题

---

## 问题简述

**现象**: 用户连续两句话：
- 句1: "查理王小猎犬和猫咪在打架"
- 句2: "是的，把画面画出来"

**预期**: 生成 "查理王小猎犬和猫咪打架" 的画面  
**实际**: 生成了与这两句话**无关**的画面

**根本原因**: 
- 句2 中的 "把" 字被误识别为 MODIFY（修改）操作
- 应该是 CREATE（创建）操作
- 导致提示词融合逻辑错误，最终生成的画面不符合用户意图

---

## 问题诊断链

```
用户句1 ✅        用户句2 ❌           操作识别 ❌        提示词融合 ❌      AI 绘画 ❌
"查理王       →   "是的，把    →  识别为 MODIFY  →  融合为修改模式  →  画面无关
小猎犬和        画面画出来"      (因为"把")      而非创建模式       性
猫咪在打架"                                                            
```

### 日志证据

部署日志显示：

```
[DEBUG] [ASYNC_DRAW] Using fused prompt: 基于包含 已有元素 的已有画面，保持整体结构和其他角色不变，进行以下修改：是的，把画面画出来
                                        ↑ 这里是问题！应该是原始用户意图的合成
                                        
[WARNING] [PROMPT_EXPAND] LLM expansion failed (Request timed out.)
          ↑ LLM 无法理解这个奇怪的提示词，因为它是错误的操作类型
```

---

## 修复任务

### 任务 1: 修复操作识别器 (operation_recognizer.py)

**问题**: "把" 关键字过于宽泛，导致所有包含 "把" 的句子都被识别为 MODIFY

**目标**: 改进 MODIFY 关键字列表，减少误判

#### 具体修改

**文件**: `src/operation_recognizer.py`  
**行号**: 42 (modify_keywords 定义)

**修改前**:
```python
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "变", "改一下", "把"]
```

**修改后**:
```python
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
# 移除 "把" 和 "变" 因为：
# - "把" 是中文介词，"把X画出来" 不是修改，而是创建
# - "变" 太模糊，"变黑" 可能表示修改，但 "变成现实" 表示创建
```

**为什么这样修改**:

| 关键字 | 示例 | 操作 | 保留？ |
|-------|------|------|--------|
| "改成" | "把颜色改成蓝色" | MODIFY | ✅ 保留 |
| "修改" | "修改画面布局" | MODIFY | ✅ 保留 |
| "变成" | "变成黄色" | MODIFY | ✅ 保留 |
| "改色" | "改色为绿色" | MODIFY | ✅ 保留 |
| "换成" | "换成大象" | MODIFY | ✅ 保留 |
| "改一下" | "改一下大小" | MODIFY | ✅ 保留 |
| "变" | "变黑色" 或 "变成现实" | 歧义 | ❌ 删除 |
| **"把"** | **"把X画出来" 或 "把X改色"** | **歧义** | **❌ 删除** |

### 任务 2: 改进 MODIFY 置信度校准 (operation_recognizer.py)

**问题**: MODIFY 操作的置信度总是固定的 0.90，没有考虑上下文

**目标**: 当 MODIFY 关键字匹配不完整时，降低置信度

#### 具体修改

**文件**: `src/operation_recognizer.py`  
**行号**: 36-46 (MODIFY 检测块)

**修改前**:
```python
elif operation_type == "modify":
    modify_keywords = [...]
    for kw in modify_keywords:
        if kw in text:
            # ... 
            return {
                "type": "modify",
                "confidence": 0.90,  # 总是 0.90，无条件
                "raw_target": target
            }
```

**修改后**:
```python
# 2. MODIFY operation keywords detection - IMPROVED
modify_keywords = ["改成", "修改", "变成", "改色", "换成", "改一下"]
for kw in modify_keywords:
    if kw in text:
        # 计算置信度: 看是否有明确的修改对象和目标属性
        confidence = 0.90
        
        # 如果文本太短或只有关键字，降低置信度
        if len(text.replace(kw, "").strip()) < 2:
            confidence = 0.60
        
        # 如果包含颜色词，提高置信度
        if "色" in text or "颜色" in text:
            confidence = 0.95
        
        target = text.replace(kw, "").strip()
        return {
            "type": "modify",
            "confidence": confidence,
            "raw_target": target or text
        }
```

### 任务 3: 改进提示词融合逻辑 (prompt_fusion.py)

**问题**: MODIFY 融合模式假设总是有已有画面，但第一次绘画时没有

**目标**: 检查是否有已有画面，如果没有就降级到 CREATE

#### 具体修改

**文件**: `src/prompt_fusion.py`  
**行号**: 47-50 (MODIFY 融合块)

**修改前**:
```python
elif operation_type == "modify":
    # Modify existing element attributes (elements list remains identical or updated)
    elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
    fused_prompt = f"基于包含 {elements_str} 的已有画面，保持整体结构和其他角色不变，进行以下修改：{current_user_text}。"
```

**修改后**:
```python
elif operation_type == "modify":
    # Check if we have previous context for modification
    has_previous_context = previous_prompt is not None or (scene_elements and len(scene_elements) > 0)
    
    if not has_previous_context:
        # No previous picture to modify, treat as CREATE instead
        fused_prompt = current_user_text
        # Do NOT change operation_type here, let the caller handle it
    else:
        # Modify existing element attributes
        elements_str = ", ".join(scene_elements) if scene_elements else "已有元素"
        fused_prompt = f"基于包含 {elements_str} 的已有画面，保持整体结构和其他角色不变，进行以下修改：{current_user_text}。"
```

### 任务 4: 改进路由层的操作识别处理 (routes/device.py)

**问题**: 低置信度的操作识别结果没有被合理处理

**目标**: 当置信度低于阈值时，考虑上下文进行降级

#### 具体修改

**文件**: `src/routes/device.py`  
**行号**: 120-140 (操作识别和融合部分)

**修改前**:
```python
if should_draw:
    logger.debug(f"[INTEGRATION] Preparing fusion for prompt: {user_text}")
    fusion_inputs = ConversationContextManager.prepare_fusion_inputs(user_text, context)
    operation = fusion_inputs["operation"]
    logger.debug(f"[INTEGRATION] Recognized operation: {operation['type']} (confidence: {operation['confidence']})")
    
    # If confidence is low (< 0.5), we downgrade to create or fallback to simple subject extraction
    if operation.get("confidence", 0.0) < 0.5:
        operation["type"] = "create"
```

**修改后**:
```python
if should_draw:
    logger.debug(f"[INTEGRATION] Preparing fusion for prompt: {user_text}")
    fusion_inputs = ConversationContextManager.prepare_fusion_inputs(user_text, context)
    operation = fusion_inputs["operation"]
    logger.debug(f"[INTEGRATION] Recognized operation: {operation['type']} (confidence: {operation['confidence']})")
    
    # Confidence-based operation adjustment
    confidence = operation.get("confidence", 0.0)
    
    if confidence < 0.5:
        # Very low confidence: downgrade to create
        operation["type"] = "create"
        logger.debug(f"[OPERATION] Very low confidence ({confidence}), downgrading to CREATE")
    
    elif confidence < 0.7 and operation["type"] in ["modify", "add"]:
        # Moderate confidence: check context
        last_op = context.get("last_operation_type")
        if last_op == "create" or not context.get("scene_elements"):
            # If last operation was create or no context, downgrade to create
            operation["type"] = "create"
            logger.debug(f"[OPERATION] Low confidence ({confidence}) + no previous context, downgrading to CREATE")
```

---

## 修改顺序（按优先级）

1. **第一步**: 修改 operation_recognizer.py (移除 "把" 关键字)
   - 时间: 2 分钟
   - 风险: 低
   - 效果: 最直接的修复

2. **第二步**: 改进 prompt_fusion.py (添加已有画面检查)
   - 时间: 3 分钟
   - 风险: 低
   - 效果: 防御性修复，避免假设

3. **第三步**: 改进 operation_recognizer.py 中的置信度逻辑
   - 时间: 5 分钟
   - 风险: 低
   - 效果: 增强鲁棒性

4. **第四步**: 改进 routes/device.py 的上下文处理
   - 时间: 5 分钟
   - 风险: 低
   - 效果: 整体鲁棒性提升

---

## 测试用例

完成修改后，需要测试以下场景：

### 测试 1: 基础场景（当前问题）

```
输入1: "查理王小猎犬和猫咪在打架"
预期操作: CREATE
预期结果: 生成相关画面

输入2: "是的，把画面画出来"
预期操作: CREATE (被降级)
预期结果: 确认/增强之前的画面
```

### 测试 2: 真正的修改

```
输入1: "画一个红色的小狗"
预期操作: CREATE
预期结果: 生成红色小狗

输入2: "把小狗改成蓝色"
预期操作: MODIFY
预期结果: 修改小狗颜色为蓝色
```

### 测试 3: 添加元素

```
输入1: "画一个小狗"
预期操作: CREATE
预期结果: 生成小狗

输入2: "再加一只猫咪"
预期操作: ADD
预期结果: 在画面中添加猫咪
```

### 测试 4: 删除操作

```
输入1: "画一个小狗和猫咪"
预期操作: CREATE
预期结果: 生成小狗和猫咪

输入2: "去掉猫咪"
预期操作: REMOVE
预期结果: 删除猫咪，只保留小狗
```

---

## 检查清单

完成以下所有步骤：

### 代码修改
- [ ] 修改 operation_recognizer.py 第 42 行（移除 "把"）
- [ ] 修改 operation_recognizer.py 第 36-46 行（改进置信度）
- [ ] 修改 prompt_fusion.py 第 47-50 行（添加已有画面检查）
- [ ] 修改 routes/device.py 第 120-140 行（改进上下文处理）

### 测试
- [ ] 运行测试用例 1（当前问题场景）
- [ ] 运行测试用例 2（真正的修改）
- [ ] 运行测试用例 3（添加元素）
- [ ] 运行测试用例 4（删除操作）
- [ ] 验证日志中没有误判警告

### 提交
- [ ] 所有代码修改
- [ ] 提交信息: "fix: improve prompt fusion and operation recognition logic"
- [ ] 部署到 Railway

### 验证
- [ ] Railway 部署成功
- [ ] Web 服务状态 🟢 Online
- [ ] 测试与用户原问题相同的对话流程
- [ ] 确认画面生成正确

---

## 预期修复结果

### 修复前 ❌

```
用户: "查理王小猎犬和猫咪在打架"
AI: "好的，我为你绘制一个小猎犬和猫咪打架的画面～"
画面: [✅ 正确]

用户: "是的，把画面画出来"
识别: MODIFY 操作
融合: "基于已有画面...进行以下修改：是的，把画面画出来"
画面: [❌ 错误，与用户意图无关]
```

### 修复后 ✅

```
用户: "查理王小猎犬和猫咪在打架"
AI: "好的，我为你绘制一个小猎犬和猫咪打架的画面～"
画面: [✅ 正确]

用户: "是的，把画面画出来"
识别: MODIFY 操作 (0.85 置信度)
上下文检查: 识别置信度较低 → 降级为 CREATE
融合: "是的，把画面画出来" 或 "查理王小猎犬和猫咪在打架"
画面: [✅ 正确，与用户意图一致]
```

---

## 可能的边界情况

修复过程中需要考虑：

1. **边界情况**: 用户直接说 "把这个改了"（不指定改成什么）
   - 解决: 降低置信度，可能降级到 CREATE
   
2. **边界情况**: 用户说 "把画面保存下来"（"把"但不是修改）
   - 解决: 这句话不在 drawing_keywords 中，不会触发绘画
   
3. **边界情况**: 用户说 "把之前的画面改成另一种风格"
   - 解决: 包含 "改成" 关键字，会被正确识别为 MODIFY

---

## 相关文件

- `PROMPT_FUSION_BUG_ANALYSIS.md` - 详细的问题分析
- `src/operation_recognizer.py` - 操作识别逻辑（主要修改）
- `src/prompt_fusion.py` - 提示词融合逻辑（次要修改）
- `src/routes/device.py` - 路由和集成层（防御性修改）

---

## 修复优先级和时间

| 优先级 | 修改 | 时间 | 效果 |
|--------|------|------|------|
| 🔴 高 | operation_recognizer.py (移除"把") | 2 min | 直接解决问题 |
| 🟠 中 | prompt_fusion.py (添加检查) | 3 min | 防御性修复 |
| 🟠 中 | operation_recognizer.py (置信度) | 5 min | 增强鲁棒性 |
| 🟡 低 | routes/device.py (上下文) | 5 min | 整体健壮性 |

**总修复时间**: 15 分钟代码修改 + 10 分钟测试 = **25 分钟**

---

**缺陷优先级**: 🔴 **高** - 影响核心功能（多轮对话）  
**复现难度**: 🟢 **极易** - 100% 复现率  
**修复复杂度**: 🟢 **低** - 逻辑调整，无新算法  
**风险等级**: 🟢 **低** - 改进现有逻辑，不影响其他功能

