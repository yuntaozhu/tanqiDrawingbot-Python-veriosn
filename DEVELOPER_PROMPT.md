# 🎯 完整开发提示词 - 会话上下文管理系统集成

**项目**: tanqiDrawingbot 多轮对话绘画应用  
**任务**: 服务器端数据库相关代码开发与集成  
**工作量**: 2-4 小时  
**难度**: 中等  

---

## 📚 背景信息

### 项目概述
这是一个儿童绘画交互应用,用户通过多轮对话逐步修改画面。当前已完成:
- ✅ 数据库架构设计(PostgreSQL 表、索引、函数)
- ✅ 业务逻辑模块(操作识别、Prompt 融合)
- ✅ CRUD 操作接口

**现在需要**: 在 FastAPI 路由层集成这些模块,实现完整的多轮对话支持

### 核心需求
实现**多轮对话上下文管理**,使得:
```
用户请求 1: "画查理王小猎犬奔跑"
  → 系统识别: CREATE 操作
  → 生成画面: [小猎犬]

用户请求 2: "在小兔子旁边增加一个小狗"
  → 系统识别: ADD 操作
  → 融合 Prompt: "基于已有画面(...),在小兔子旁边增加小狗"
  → 生成画面: [小猎犬 + 小兔子 + 小狗] ✅ 保持一致!
```

### 已有资源
```
src/
├── conversation_models.py      # ✅ ORM 数据模型(ready)
├── conversation_crud.py         # ✅ CRUD 操作接口(ready)
├── operation_recognizer.py      # ✅ 操作识别引擎(ready)
├── prompt_fusion.py             # ✅ Prompt 融合引擎(ready)
├── database.py                  # ✅ 数据库连接(已更新)
├── routes/
│   └── device.py                # ⏳ 需要修改
└── main.py                      # ⏳ 需要修改(后台任务)
```

---

## 📋 需要完成的 4 个任务

### 任务 1: 修改 `src/routes/device.py` - 核心集成(最重要)

#### 1.1 修改 `handle_chat()` 函数

**当前问题**:
- 每个请求都孤立处理
- 完全忽视用户历史和场景信息
- 无法实现多轮对话

**目标**:
- 加载用户的会话上下文
- 识别用户的操作意图
- 融合历史 Prompt
- 保存更新后的上下文

**具体改造流程**:

```
当前流程:
HTTP 请求 → 提取用户文本 → LLM 生成回复 → 绘图 → 返回响应

新流程:
HTTP 请求 
  ↓ [新增] 加载会话上下文
  ↓ [新增] 识别操作类型(create/add/modify/remove)
  ↓ [新增] 融合 Prompt(与历史融合)
  ↓ 使用融合 Prompt 进行绘图(改用融合结果)
  ↓ [新增] 更新会话上下文
  ↓ [新增] 保存到数据库
  ↓ 返回响应
```

**详细实现步骤**:

##### Step 1: 添加导入语句

在 `src/routes/device.py` 顶部添加:
```python
from src.conversation_crud import ConversationManager
from src.operation_recognizer import OperationRecognizer
from src.prompt_fusion import PromptFusionEngine, ConversationContextManager
import time  # 如果还未导入
```

##### Step 2: 修改 `handle_chat()` 函数逻辑

找到函数中的这一部分(大约在获取 token 和 user_text 之后):
```python
token = request.headers.get("x-device-token") or request.headers.get("authorization") or "anonymous_device"
user_text = req.text.strip() if req.text else ""
```

在这之后、进入 `event_generator()` 之前,添加以下代码:

```python
# [新增] 第一步:加载或创建会话上下文
logger.debug(f"[INTEGRATION] Loading context for token: {token}")
context = ConversationManager.get_conversation_context(token)
if context is None:
    # 创建新上下文
    context = {
        "device_token": token,
        "message_history": [],
        "current_image_url": None,
        "current_image_bitmap_hex": None,
        "scene_elements": [],
        "last_generated_prompt": None,
        "last_operation_type": None,
        "last_operation_detail": {},
        "created_at": None,
        "updated_at": None
    }
    logger.debug(f"[INTEGRATION] Created new context for token: {token}")
else:
    logger.debug(f"[INTEGRATION] Loaded existing context for token: {token}")
    logger.debug(f"[INTEGRATION] Current scene elements: {context.get('scene_elements', [])}")
    logger.debug(f"[INTEGRATION] Message history count: {len(context.get('message_history', []))}")
```

##### Step 3: 在绘图逻辑中融合 Prompt

找到这部分代码(在 `event_generator()` 内部,where `should_draw` is determined):
```python
if should_draw:
    subject = extract_drawing_subject(user_text)
    # ... 缓存检查 ...
    # drawing_task = asyncio.create_task(async_generate_drawing(subject, token))
```

**替换为**:
```python
if should_draw:
    # [新增] 第二步:准备融合输入
    logger.debug(f"[INTEGRATION] Preparing fusion for prompt: {user_text}")
    fusion_inputs = ConversationContextManager.prepare_fusion_inputs(user_text, context)
    
    # [新增] 第三步:融合 Prompt
    operation = fusion_inputs["operation"]
    logger.debug(f"[INTEGRATION] Recognized operation: {operation['type']} (confidence: {operation['confidence']})")
    
    fusion_result = PromptFusionEngine.fuse_drawing_prompt(
        current_user_text=user_text,
        operation_type=operation["type"],
        previous_prompt=fusion_inputs["previous_prompt"],
        scene_elements=fusion_inputs["scene_elements"]
    )
    
    logger.debug(f"[INTEGRATION] Fusion complete:")
    logger.debug(f"  - Fused Prompt: {fusion_result.get('fused_prompt', '')[:100]}...")
    logger.debug(f"  - Target Element: {fusion_result.get('target_element')}")
    logger.debug(f"  - New Elements: {fusion_result.get('new_elements', [])}")
    logger.debug(f"  - All Elements After: {fusion_result.get('all_elements_after', [])}")
    
    # [修改] 使用融合后的 Prompt 而不是原始 user_text
    drawing_prompt = fusion_result.get("fused_prompt", user_text)
    subject = fusion_result.get("target_element") or extract_drawing_subject(user_text)
    
    # [修改] 检查缓存(使用融合后的 Prompt)
    cache_mgr = DrawingCacheManager.get_instance()
    cached_action = cache_mgr.get(subject)  # 仍使用 subject 作为缓存 key
    
    if cached_action:
        logger.debug(f"[INTEGRATION] Cache hit for subject: {subject}")
        # ... 缓存处理逻辑保持不变 ...
    else:
        logger.debug(f"[INTEGRATION] Cache miss, launching async draw task")
        # [修改] 传递融合结果给绘图函数
        drawing_task = asyncio.create_task(
            async_generate_drawing_with_fusion(drawing_prompt, token, fusion_result)
        )
```

##### Step 4: 创建新的绘图函数(支持融合结果)

在 `src/business_logic.py` 中,修改或新增 `async_generate_drawing()`:

```python
async def async_generate_drawing_with_fusion(
    fused_prompt: str, 
    device_token: str, 
    fusion_result: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    使用融合后的 Prompt 生成绘图
    """
    # 大部分逻辑与原 async_generate_drawing() 相同
    # 主要区别: 使用 fused_prompt 而不是 subject
    # 并在返回时包含 fusion_result 信息
    
    print(f"[DEBUG] [ASYNC_DRAW] Using fused prompt: {fused_prompt[:100]}...")
    
    # ... 原有的绘图逻辑(使用 fused_prompt) ...
    # ... 代码实现 ...
    
    # 返回时包含融合信息
    return {
        "type": "draw",
        "prompt": fusion_result.get("target_element"),
        "fused_prompt": fused_prompt,
        "operation": fusion_result.get("operation"),
        "scene_elements": fusion_result.get("all_elements_after"),
        "job_id": job_id,
        "image_url": processed_image,
        "bitmap_hex": bitmap_hex
    }
```

##### Step 5: 在 StreamingResponse 返回前保存上下文

找到 `event_generator()` 末尾,在返回最终响应前:

```python
# [新增] 第四步:更新会话上下文
logger.debug(f"[INTEGRATION] Updating context after interaction")

# 更新上下文
context = ConversationContextManager.update_context_after_fusion(
    context,
    fusion_result,
    image_url=action_result.get("image_url") if action_result else None,
    bitmap_hex=action_result.get("bitmap_hex") if action_result else None
)

# 添加消息到历史
message = {
    "timestamp": time.time(),
    "user_text": user_text,
    "ai_response": ai_response_text,  # 来自 LLM 流输出
    "drawing_triggered": should_draw,
    "drawing_config": fusion_result if should_draw else None,
    "operation_type": operation["type"] if should_draw else None,
    "metadata": {
        "recognition_confidence": operation.get("confidence", 0),
        "scene_elements_after": fusion_result.get("all_elements_after", []) if should_draw else context["scene_elements"]
    }
}
context["message_history"].append(message)

logger.debug(f"[INTEGRATION] Appended message to history. Total messages: {len(context['message_history'])}")

# [新增] 第五步:保存到数据库
success = ConversationManager.create_or_update_conversation_context(token, context)
if success:
    logger.info(f"[INTEGRATION] ✅ Context saved for token: {token}")
else:
    logger.error(f"[INTEGRATION] ❌ Failed to save context for token: {token}")

# 返回最终响应
final_payload = {
    "action": action_result,
    "context": {
        "scene_elements": context.get("scene_elements", []),
        "message_count": len(context.get("message_history", []))
    }
}
yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
```

#### 1.2 处理不需要绘图的情况

对于 `should_draw=False` 的情况,仍需要更新上下文:

```python
# 在 event_generator() 中,处理完 LLM 流输出后,regardless of should_draw:

# [新增] 更新消息历史(即使不画图)
message = {
    "timestamp": time.time(),
    "user_text": user_text,
    "ai_response": ai_response_text,
    "drawing_triggered": False,
    "drawing_config": None,
    "operation_type": None
}
context["message_history"].append(message)

# [新增] 保存上下文
ConversationManager.create_or_update_conversation_context(token, context)
```

---

### 任务 2: 新增 `/api/device/v1/conversation-history` API

#### 目标
用户可以查询自己的对话历史和当前场景信息

#### 实现指南

在 `src/routes/device.py` 末尾添加:

```python
@router.get("/api/device/v1/conversation-history")
@router.get("/api/v1/conversation-history")
async def get_conversation_history(
    request: Request,
    limit: int = Query(20, ge=1, le=100)
):
    """
    获取用户的对话历史和当前场景信息
    
    参数:
    - limit: 返回的消息数量(默认 20,最多 100)
    
    认证: 需要 x-device-token 头
    """
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing x-device-token")
    
    # 加载会话上下文
    context = ConversationManager.get_conversation_context(token)
    
    if not context:
        return {
            "device_token": token,
            "message_history": [],
            "current_scene": None,
            "statistics": {
                "total_messages": 0,
                "total_drawings": 0
            }
        }
    
    # 获取绘画历史
    drawing_history = ConversationManager.get_drawing_history(token, limit)
    
    # 计算统计信息
    drawing_count = len([m for m in context.get("message_history", []) if m.get("drawing_triggered")])
    
    return {
        "device_token": token,
        "message_history": context.get("message_history", [])[-limit:],  # 返回最近 N 条消息
        "current_scene": {
            "image_url": context.get("current_image_url"),
            "bitmap_hex": context.get("current_image_bitmap_hex"),
            "elements": context.get("scene_elements", [])
        },
        "drawing_history": drawing_history,
        "statistics": {
            "total_messages": len(context.get("message_history", [])),
            "total_drawings": drawing_count,
            "last_interaction": context.get("updated_at")
        }
    }
```

---

### 任务 3: 新增 `/api/device/v1/conversation-reset` API

#### 目标
用户可以清空自己的会话历史,开始新对话

#### 实现指南

在 `src/routes/device.py` 末尾添加:

```python
@router.post("/api/device/v1/conversation-reset")
@router.post("/api/v1/conversation-reset")
async def reset_conversation(request: Request):
    """
    重置用户的会话上下文,清空所有历史
    
    认证: 需要 x-device-token 头
    """
    token = request.headers.get("x-device-token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing x-device-token")
    
    # 逻辑删除会话上下文
    success = ConversationManager.delete_conversation_context(token, soft_delete=True)
    
    if success:
        logger.info(f"[API] Conversation reset for token: {token}")
        return {
            "status": "success",
            "message": "Conversation reset successfully",
            "device_token": token
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to reset conversation")
```

---

### 任务 4: 创建后台任务清理过期会话

#### 4.1 创建新文件 `src/background_tasks.py`

```python
"""
后台任务 - 定期清理过期会话
"""
import asyncio
import time
from src.logger import setup_logger
from src.conversation_crud import ConversationManager

logger = setup_logger("background_tasks")


async def cleanup_expired_contexts_task(hours: int = 24):
    """
    定期清理过期的会话上下文(24小时无交互自动删除)
    
    此函数在后台持续运行,每 1 小时执行一次清理
    """
    logger.info(f"[BACKGROUND] Cleanup task started (will run every 3600 seconds)")
    
    while True:
        try:
            # 等待 1 小时
            await asyncio.sleep(3600)
            
            # 执行清理
            deleted_count = ConversationManager.cleanup_expired_contexts(hours)
            
            if deleted_count > 0:
                logger.info(f"[BACKGROUND] ✅ Cleaned up {deleted_count} expired contexts")
            else:
                logger.debug(f"[BACKGROUND] No expired contexts to clean")
                
        except Exception as e:
            logger.error(f"[BACKGROUND] ❌ Error during cleanup: {e}")
            # 继续运行,不退出
            await asyncio.sleep(60)  # 错误后等 1 分钟再试


async def start_cleanup_task():
    """
    启动后台清理任务(在应用启动时调用)
    """
    logger.info("[BACKGROUND] Starting conversation context cleanup task")
    await cleanup_expired_contexts_task()
```

#### 4.2 在 `src/main.py` 中启动后台任务

找到 `@app.on_event("startup")` 函数,在末尾添加:

```python
@app.on_event("startup")
async def startup_event():
    # ... 现有的启动代码 ...
    
    # [新增] 启动后台清理任务
    try:
        from src.background_tasks import start_cleanup_task
        logger.info("[STARTUP] Scheduling background cleanup task")
        asyncio.create_task(start_cleanup_task())
    except Exception as e:
        logger.warning(f"[STARTUP] Failed to start cleanup task: {e}")
```

---

## ✅ 完整的集成清单

### 修改项目

- [ ] **src/routes/device.py**
  - [ ] 添加导入语句(conversation_crud, operation_recognizer, prompt_fusion)
  - [ ] 修改 `handle_chat()` 加载会话上下文(Step 1)
  - [ ] 修改 `handle_chat()` 融合 Prompt(Step 2-3)
  - [ ] 修改 `handle_chat()` 更新保存上下文(Step 4-5)
  - [ ] 修改不需要绘图的情况,仍保存上下文
  - [ ] 新增 `/api/device/v1/conversation-history` 端点
  - [ ] 新增 `/api/device/v1/conversation-reset` 端点

- [ ] **src/business_logic.py**
  - [ ] 新增或修改 `async_generate_drawing_with_fusion()` 函数
  - [ ] 支持接收融合结果参数
  - [ ] 返回包含融合信息的响应

- [ ] **src/background_tasks.py**(新建)
  - [ ] 创建 `cleanup_expired_contexts_task()` 异步函数
  - [ ] 创建 `start_cleanup_task()` 启动函数

- [ ] **src/main.py**
  - [ ] 在 `startup_event()` 中启动后台清理任务

### 测试项目

- [ ] 测试 CREATE 操作
  ```
  用户: "画查理王小猎犬奔跑"
  预期: 创建新会话,返回小猎犬的画
  验证: scene_elements = ["查理王小猎犬"]
  ```

- [ ] 测试 ADD 操作
  ```
  用户: "在小兔子旁边增加一个小狗"
  预期: 融合 Prompt,返回包含三个元素的画
  验证: scene_elements = ["查理王小猎犬", "小兔子", "小狗"]
  ```

- [ ] 测试 MODIFY 操作
  ```
  用户: "把小狗的颜色改成白色"
  预期: 修改元素属性,元素列表不变
  验证: scene_elements 保持不变
  ```

- [ ] 测试 REMOVE 操作
  ```
  用户: "去掉小兔子"
  预期: 移除元素,元素列表更新
  验证: scene_elements = ["查理王小猎犬", "小狗"]
  ```

- [ ] 测试历史查询 API
  ```
  GET /api/device/v1/conversation-history
  预期: 返回完整的消息历史和当前场景
  ```

- [ ] 测试重置 API
  ```
  POST /api/device/v1/conversation-reset
  预期: 清空会话,返回成功
  ```

- [ ] 测试后台清理
  ```
  验证: ConversationManager.cleanup_expired_contexts() 能正确删除过期数据
  ```

---

## 🔍 关键实现细节

### 1. 操作识别的置信度
- 关键词精确匹配: 0.85-0.95
- 上下文推断: 0.6-0.75
- 如果 < 0.5,降级为 CREATE

### 2. Prompt 融合的规则
- **CREATE**: 忽略历史,创建全新画面
  ```
  Prompt = user_text
  scene_elements = []
  ```

- **ADD**: 保留历史,增加新元素
  ```
  Prompt = "基于已有画面(...),在[位置]增加[元素]"
  scene_elements = [...previous..., new_element]
  ```

- **MODIFY**: 保留元素,修改属性
  ```
  Prompt = "保持现有...,修改[元素]的[属性]"
  scene_elements = [...unchanged...]
  ```

- **REMOVE**: 删除元素,保持协调
  ```
  Prompt = "移除[元素],保持整体..."
  scene_elements = [...removed target...]
  ```

### 3. 上下文更新顺序
1. 加载现有上下文(或创建新的)
2. 识别操作
3. 融合 Prompt
4. 执行绘图(使用融合后的 Prompt)
5. 获取绘图结果(URL 和 bitmap)
6. 更新上下文中的 scene_elements 和 image_url
7. 添加消息到历史
8. 保存回数据库

### 4. 错误处理
- 数据库操作失败: 记录错误但不中断请求
- Prompt 融合失败: 使用原始用户输入作为 fallback
- 上下文加载失败: 创建新的空上下文,继续处理

---

## 📚 参考文档和代码

### 已有模块的使用示例

```python
# 1. 加载上下文
from src.conversation_crud import ConversationManager
context = ConversationManager.get_conversation_context(device_token)

# 2. 识别操作
from src.operation_recognizer import OperationRecognizer
operation = OperationRecognizer.recognize_operation(
    user_text=user_text,
    last_operation_type=context.get("last_operation_type")
)
# 返回: {"type": "add", "confidence": 0.9, "raw_target": "小狗", ...}

# 3. 融合 Prompt
from src.prompt_fusion import PromptFusionEngine
fusion_result = PromptFusionEngine.fuse_drawing_prompt(
    current_user_text=user_text,
    operation_type=operation["type"],
    previous_prompt=context.get("last_generated_prompt"),
    scene_elements=context.get("scene_elements", [])
)
# 返回: {
#   "operation": "add",
#   "fused_prompt": "基于已有画面...",
#   "target_element": "小狗",
#   "all_elements_after": ["小猎犬", "小兔子", "小狗"]
# }

# 4. 更新上下文
from src.prompt_fusion import ConversationContextManager
context = ConversationContextManager.update_context_after_fusion(
    context=context,
    fusion_result=fusion_result,
    image_url=image_url,
    bitmap_hex=bitmap_hex
)

# 5. 保存到数据库
ConversationManager.create_or_update_conversation_context(
    device_token=device_token,
    context_data=context
)

# 6. 获取历史
history = ConversationManager.get_drawing_history(device_token, limit=20)

# 7. 删除上下文(重置)
ConversationManager.delete_conversation_context(device_token, soft_delete=True)

# 8. 清理过期
deleted = ConversationManager.cleanup_expired_contexts(hours=24)
```

---

## 🚀 完成标准

代码集成完成后应该满足:

1. ✅ **代码质量**
   - 遵循项目的代码风格和命名规范
   - 添加详细的日志记录(使用 logger)
   - 包含错误处理和异常捕获
   - 代码注释清晰

2. ✅ **功能完整性**
   - 四个任务全部完成
   - 所有 API 端点可访问
   - 后台任务成功启动
   - 没有遗漏的集成点

3. ✅ **数据一致性**
   - 上下文加载、更新、保存的流程完整
   - 消息历史正确记录
   - 场景元素正确更新
   - 每个操作类型都正确处理

4. ✅ **测试通过**
   - 多轮对话场景正常工作
   - 历史查询返回完整数据
   - 重置功能有效
   - 无内存泄漏或数据库错误

---

## 💡 实现建议

1. **分步实现**: 先完成任务 1,测试通过后再做任务 2-4
2. **频繁提交**: 每个小任务完成后提交一次 Git
3. **日志调试**: 使用详细的 DEBUG 日志追踪执行流程
4. **数据验证**: 在数据库中验证数据是否正确保存
5. **单元测试**: 考虑为新函数编写单元测试

---

## 📞 如遇问题

参考:
- `IMPLEMENTATION_STATUS.md` - 项目进度和常见问题
- `src/conversation_crud.py` - CRUD 方法的详细注释
- `src/operation_recognizer.py` - 操作识别的具体实现
- `src/prompt_fusion.py` - Prompt 融合的具体实现

---

**准备好开始了吗? 祝你实现顺利! 🚀**

这个完整的开发提示词可以直接复制给 Claude/ChatGPT 进行代码开发。

