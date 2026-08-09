# 📊 数据库架构参考手册

用于 AI 辅助开发,提供完整的数据库结构信息

---

## 🗄️ 数据库概览

### 项目
- **项目名称**: tanqiDrawingbot
- **数据库类型**: PostgreSQL (Railway)
- **表数量**: 2 个主表
- **应用框架**: FastAPI (Python)
- **ORM**: SQLAlchemy 2.0+

### 连接方式
```
DATABASE_URL=postgresql://user:password@host:port/database
# 从 Railway 自动配置,通过环境变量传递
```

---

## 📋 表 1: conversation_contexts (会话上下文表)

### 用途
存储每个用户(device_token)的完整会话状态,包括对话历史、当前画面、场景元素等

### 表名
```
conversation_contexts
```

### 字段详情

| 字段名 | 数据类型 | 约束 | 说明 | 示例 |
|-------|---------|------|------|------|
| **device_token** | TEXT | PRIMARY KEY | 用户唯一标识(客户端生成) | `"device_abc123xyz"` |
| **message_history** | JSONB | DEFAULT '[]' | 对话消息历史数组 | 见下方示例 |
| **current_image_url** | TEXT | NULL | 当前画面的图片 URL | `"https://...image.jpg"` |
| **current_image_bitmap_hex** | TEXT | NULL | 当前画面的 bitmap 十六进制 | `"89504e47..."` |
| **scene_elements** | TEXT[] | DEFAULT '{}' | 当前画面的所有元素列表 | `["小猎犬", "小兔子", "小狗"]` |
| **last_generated_prompt** | TEXT | NULL | 最后一次有效的完整 Prompt | `"查理王小猎犬在草地上..."` |
| **last_operation_type** | VARCHAR(20) | NULL | 最后操作类型 | `'create'`, `'add'`, `'modify'`, `'remove'` |
| **last_operation_detail** | JSONB | NULL | 最后操作的详细信息 | `{"type": "add", "target": "小狗", "position": "旁边"}` |
| **created_at** | TIMESTAMP | DEFAULT NOW() | 会话创建时间 | `2026-08-08 10:30:45.123456` |
| **updated_at** | TIMESTAMP | DEFAULT NOW() | 最后更新时间(自动更新) | `2026-08-08 15:45:30.654321` |
| **is_deleted** | BOOLEAN | DEFAULT FALSE | 逻辑删除标志 | `false` |

### 主键与索引
```sql
PRIMARY KEY: device_token

-- 创建的索引
CREATE INDEX idx_context_token ON conversation_contexts(device_token);
CREATE INDEX idx_context_updated ON conversation_contexts(updated_at);
CREATE INDEX idx_context_deleted ON conversation_contexts(is_deleted) WHERE is_deleted = FALSE;
```

### JSONB 数据结构示例

#### message_history 字段结构
```json
[
  {
    "timestamp": 1691485845.123,
    "user_text": "画查理王小猎犬奔跑",
    "ai_response": "我为你画一只可爱的查理王小猎犬在草地上奔跑的样子",
    "drawing_triggered": true,
    "drawing_config": {
      "operation": "create",
      "fused_prompt": "查理王小猎犬在撒满碎星光的棉花糖云坡上奔跑...",
      "target_element": "查理王小猎犬",
      "all_elements_after": ["查理王小猎犬"],
      "instructions": "这是一个全新的画面创建请求..."
    },
    "operation_type": "create",
    "metadata": {
      "recognition_confidence": 0.95,
      "scene_elements_after": ["查理王小猎犬"]
    }
  },
  {
    "timestamp": 1691485900.456,
    "user_text": "在小兔子旁边增加一个小狗",
    "ai_response": "我在小兔子旁边给你加了一只小狗",
    "drawing_triggered": true,
    "drawing_config": {
      "operation": "add",
      "fused_prompt": "基于已有的画面(查理王小猎犬在草地上奔跑),在小兔子旁边增加一个小狗。保持整体风格和谐...",
      "target_element": "小狗",
      "position": "side",
      "all_elements_after": ["查理王小猎犬", "小兔子", "小狗"],
      "instructions": "这是一个增量修改操作,确保新增元素不会遮挡..."
    },
    "operation_type": "add",
    "metadata": {
      "recognition_confidence": 0.88,
      "scene_elements_after": ["查理王小猎犬", "小兔子", "小狗"]
    }
  }
]
```

#### last_operation_detail 字段结构
```json
{
  "type": "add",
  "target": "小狗",
  "position": "side",
  "confidence": 0.88,
  "raw_text": "在小兔子旁边增加一个小狗"
}
```

### 约束条件
```sql
-- 检查 last_operation_type 的有效值
CONSTRAINT valid_operation_type CHECK (
  last_operation_type IN ('create', 'add', 'modify', 'remove') 
  OR last_operation_type IS NULL
)
```

### 触发器
```sql
-- 自动更新 updated_at 时间戳
CREATE TRIGGER update_conversation_context_timestamp_trigger
BEFORE UPDATE ON conversation_contexts
FOR EACH ROW
EXECUTE FUNCTION update_conversation_context_timestamp();
```

---

## 📋 表 2: drawing_history (绘画历史表)

### 用途
记录每一次的绘画生成,用于历史追踪和数据分析

### 表名
```
drawing_history
```

### 字段详情

| 字段名 | 数据类型 | 约束 | 说明 | 示例 |
|-------|---------|------|------|------|
| **job_id** | VARCHAR(36) | PRIMARY KEY | 绘画任务唯一 ID | `"550e8400-e29b-41d4-a716-446655440000"` |
| **device_token** | TEXT | NOT NULL | 用户标识(外键) | `"device_abc123xyz"` |
| **user_prompt** | TEXT | NULL | 用户原始输入 Prompt | `"在小兔子旁边增加一个小狗"` |
| **expanded_prompt** | TEXT | NULL | LLM 扩展后的 Prompt | `"基于已有的画面(...),在小兔子旁边增加一个小狗..."` |
| **image_url** | TEXT | NULL | 生成的图片 URL | `"https://...generated_image.jpg"` |
| **bitmap_hex** | TEXT | NULL | Bitmap 十六进制编码 | `"89504e47..."` |
| **scene_elements** | TEXT[] | DEFAULT '{}' | 画面中的元素列表 | `["查理王小猎犬", "小兔子", "小狗"]` |
| **operation_type** | VARCHAR(20) | NULL | 操作类型 | `'create'`, `'add'`, `'modify'`, `'remove'` |
| **created_at** | TIMESTAMP | DEFAULT NOW() | 生成时间 | `2026-08-08 15:45:30.654321` |

### 主键与索引
```sql
PRIMARY KEY: job_id

-- 创建的索引
CREATE INDEX idx_drawing_token ON drawing_history(device_token);
CREATE INDEX idx_drawing_created ON drawing_history(created_at);
```

### 约束条件
```sql
CONSTRAINT valid_operation_type_drawing CHECK (
  operation_type IN ('create', 'add', 'modify', 'remove')
  OR operation_type IS NULL
)
```

---

## 🔄 表关系

### 关系图
```
conversation_contexts (主表)
    ↓ (一对多)
drawing_history (详情表)

外键关系(逻辑):
drawing_history.device_token → conversation_contexts.device_token
```

### 查询关系示例
```sql
-- 获取某用户的所有绘画历史
SELECT dh.* 
FROM drawing_history dh
JOIN conversation_contexts cc ON dh.device_token = cc.device_token
WHERE cc.device_token = 'device_abc123xyz'
ORDER BY dh.created_at DESC;
```

---

## 🔑 操作类型说明

| 操作类型 | 说明 | scene_elements 变化 | Prompt 融合方式 |
|---------|------|------------------|-----------------|
| **create** | 创建全新画面 | 清空并设置新元素 | 忽略历史,直接使用用户输入 |
| **add** | 添加新元素到现有画面 | 追加新元素到列表 | "基于已有画面(...),在[位置]增加[元素]" |
| **modify** | 修改现有元素的属性 | 保持不变 | "保持现有...,修改[元素]的[属性]" |
| **remove** | 删除现有元素 | 移除目标元素 | "移除[元素],保持整体协调..." |

---

## 📐 位置类型说明

用于 ADD 操作时指定新元素的相对位置:

| 位置代码 | 中文说明 | 融合 Prompt 示例 |
|---------|---------|-----------------|
| `top` | 上面 | "在上面增加" |
| `bottom` | 下面 | "在下面增加" |
| `left` | 左边 | "在左边增加" |
| `right` | 右边 | "在右边增加" |
| `center` | 中间 | "在中间增加" |
| `side` | 旁边 | "在旁边增加" |
| `front` | 前面 | "在前面增加" |
| `back` | 后面 | "在后面增加" |

---

## 💾 数据库函数

### 1. update_conversation_context_timestamp()
```sql
CREATE OR REPLACE FUNCTION update_conversation_context_timestamp()
RETURNS TRIGGER AS $$
BEGIN
 NEW.updated_at = NOW();
 RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```
**说明**: 在每次更新 conversation_contexts 表时,自动更新 updated_at 字段

### 2. cleanup_expired_contexts(p_hours)
```sql
CREATE OR REPLACE FUNCTION cleanup_expired_contexts(p_hours INT DEFAULT 24)
RETURNS TABLE(deleted_count INT) AS $$
DECLARE
 v_deleted_count INT;
BEGIN
 DELETE FROM conversation_contexts
 WHERE is_deleted = FALSE 
 AND updated_at < NOW() - (p_hours || ' hours')::INTERVAL;
 
 GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
 RETURN QUERY SELECT v_deleted_count;
END;
$$ LANGUAGE plpgsql;
```
**说明**: 清理超过指定小时数(默认24小时)无更新的会话记录

**使用示例**:
```sql
-- 查看删除数量
SELECT * FROM cleanup_expired_contexts(24);

-- 或直接在 Python 中调用
ConversationManager.cleanup_expired_contexts(hours=24)
```

---

## 🐍 Python SQLAlchemy 模型

### ConversationContextDB 模型
```python
from sqlalchemy import Column, String, TIMESTAMP, JSON, ARRAY, Boolean, func
from src.database import Base

class ConversationContextDB(Base):
    __tablename__ = "conversation_contexts"
    
    device_token = Column(String(255), primary_key=True, index=True)
    message_history = Column(JSON, default=list, nullable=False)
    current_image_url = Column(String, nullable=True)
    current_image_bitmap_hex = Column(String, nullable=True)
    scene_elements = Column(ARRAY(String), default=list, nullable=False)
    last_generated_prompt = Column(String, nullable=True)
    last_operation_type = Column(String(20), nullable=True)
    last_operation_detail = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
```

### DrawingHistoryDB 模型
```python
class DrawingHistoryDB(Base):
    __tablename__ = "drawing_history"
    
    job_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_token = Column(String(255), index=True, nullable=False)
    user_prompt = Column(String, nullable=True)
    expanded_prompt = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    bitmap_hex = Column(String, nullable=True)
    scene_elements = Column(ARRAY(String), default=list, nullable=False)
    operation_type = Column(String(20), nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
```

---

## 🔐 常用查询 SQL

### 加载用户会话上下文
```sql
SELECT * FROM conversation_contexts
WHERE device_token = 'device_abc123xyz'
AND is_deleted = FALSE;
```

### 获取用户的最新消息(前 5 条)
```sql
SELECT message_history -> 0 AS latest_message
FROM conversation_contexts
WHERE device_token = 'device_abc123xyz'
AND is_deleted = FALSE;
```

### 获取用户的所有绘画历史
```sql
SELECT * FROM drawing_history
WHERE device_token = 'device_abc123xyz'
ORDER BY created_at DESC;
```

### 清理 24 小时未更新的会话
```sql
DELETE FROM conversation_contexts
WHERE is_deleted = FALSE
AND updated_at < NOW() - INTERVAL '24 hours';
```

### 获取统计信息
```sql
SELECT 
  COUNT(*) as total_contexts,
  COUNT(CASE WHEN is_deleted = FALSE THEN 1 END) as active_contexts,
  COUNT(CASE WHEN is_deleted = TRUE THEN 1 END) as deleted_contexts
FROM conversation_contexts;
```

---

## 🔗 CRUD 操作方法

### 已实现的 Python 接口

#### 1. ConversationManager.get_conversation_context()
```python
def get_conversation_context(device_token: str) -> Optional[Dict[str, Any]]:
    """加载用户会话上下文"""
```
**返回**: 会话数据字典或 None

#### 2. ConversationManager.create_or_update_conversation_context()
```python
def create_or_update_conversation_context(
    device_token: str, 
    context_data: Dict[str, Any]
) -> bool:
    """创建或更新会话上下文(UPSERT)"""
```
**返回**: 成功 True,失败 False

#### 3. ConversationManager.append_message_to_context()
```python
def append_message_to_context(
    device_token: str, 
    message: Dict[str, Any]
) -> bool:
    """向会话历史追加新消息"""
```

#### 4. ConversationManager.save_drawing_history()
```python
def save_drawing_history(
    device_token: str, 
    drawing_data: Dict[str, Any]
) -> bool:
    """保存绘画历史记录"""
```

#### 5. ConversationManager.get_drawing_history()
```python
def get_drawing_history(
    device_token: str, 
    limit: int = 20
) -> List[Dict[str, Any]]:
    """获取用户的绘画历史(最近 N 条)"""
```

#### 6. ConversationManager.delete_conversation_context()
```python
def delete_conversation_context(
    device_token: str, 
    soft_delete: bool = True
) -> bool:
    """删除会话上下文(逻辑或物理删除)"""
```

#### 7. ConversationManager.cleanup_expired_contexts()
```python
def cleanup_expired_contexts(hours: int = 24) -> int:
    """清理过期会话"""
```
**返回**: 删除的行数

---

## 📊 数据流示例

### 完整的多轮对话数据流

#### 请求 1: 创建新画面
```
用户输入: "画查理王小猎犬奔跑"
    ↓
[1] ConversationManager.get_conversation_context('device_token')
    返回: None (新用户)
    ↓
[2] 创建新的空上下文
    ↓
[3] OperationRecognizer.recognize_operation('画查理王小猎犬奔跑')
    返回: {"type": "create", "confidence": 0.95, ...}
    ↓
[4] PromptFusionEngine.fuse_drawing_prompt(...)
    返回: {
      "operation": "create",
      "fused_prompt": "查理王小猎犬在...",
      "all_elements_after": ["查理王小猎犬"]
    }
    ↓
[5] 生成画面 → 获得 image_url, bitmap_hex
    ↓
[6] ConversationManager.create_or_update_conversation_context(
      device_token,
      {
        "message_history": [{"timestamp": ..., "user_text": "...", ...}],
        "scene_elements": ["查理王小猎犬"],
        "current_image_url": "...",
        "last_generated_prompt": "查理王小猎犬在...",
        "last_operation_type": "create"
      }
    )
    ↓
[7] ConversationManager.save_drawing_history(device_token, {...})
    ↓
HTTP 响应: {"action": {...}, "context": {"scene_elements": ["查理王小猎犬"]}}
```

#### 请求 2: 添加新元素
```
用户输入: "在小兔子旁边增加一个小狗"
    ↓
[1] ConversationManager.get_conversation_context('device_token')
    返回: {
      "scene_elements": ["查理王小猎犬"],
      "last_generated_prompt": "查理王小猎犬在...",
      "last_operation_type": "create"
    }
    ↓
[2] OperationRecognizer.recognize_operation(
      "在小兔子旁边增加一个小狗",
      last_operation_type="create"
    )
    返回: {"type": "add", "confidence": 0.88, "position": "side"}
    ↓
[3] PromptFusionEngine.fuse_drawing_prompt(
      current_user_text="在小兔子旁边增加一个小狗",
      operation_type="add",
      previous_prompt="查理王小猎犬在...",
      scene_elements=["查理王小猎犬"]
    )
    返回: {
      "operation": "add",
      "fused_prompt": "基于已有的画面(...),在旁边增加小狗",
      "all_elements_after": ["查理王小猎犬", "小兔子", "小狗"]
    }
    ↓
[4] 生成画面
    ↓
[5] 更新上下文:
    context["scene_elements"] = ["查理王小猎犬", "小兔子", "小狗"]
    context["current_image_url"] = new_url
    context["last_generated_prompt"] = fused_prompt
    context["last_operation_type"] = "add"
    context["message_history"].append({...})
    ↓
[6] ConversationManager.create_or_update_conversation_context(...)
    ↓
HTTP 响应: {"action": {...}, "context": {"scene_elements": ["查理王小猎犬", "小兔子", "小狗"]}}
```

---

## ⚡ 性能建议

### 索引使用
```python
# 快速查询单个用户会话
SELECT * FROM conversation_contexts 
WHERE device_token = 'XXX';  # 使用 idx_context_token

# 查找需要清理的过期会话
SELECT * FROM conversation_contexts
WHERE is_deleted = FALSE 
AND updated_at < NOW() - INTERVAL '24 hours';  # 使用 idx_context_updated + idx_context_deleted
```

### 大数据处理建议
- message_history 超过 100 条时考虑分页加载
- drawing_history 定期归档(按月分表)
- 定期执行 VACUUM ANALYZE 清理和优化

---

## 🔐 数据验证规则

### device_token
- 类型: TEXT
- 长度: 1-255 字符
- 可选值: 任何非空字符串

### operation_type
- 有效值: `'create'`, `'add'`, `'modify'`, `'remove'`, NULL
- 其他值会被数据库约束拒绝

### message_history
- 类型: JSONB 数组
- 每条消息必须包含: timestamp, user_text, ai_response
- 可选字段: drawing_triggered, drawing_config, operation_type, metadata

### scene_elements
- 类型: TEXT[] 数组
- 示例: `["小猎犬", "小兔子", "小狗"]`
- 空值: `{}` 或 `[]`

---

## 📝 初始化 SQL 脚本

完整的表创建脚本已保存在:
```
migrations/init_conversation_tables.sql
```

包含:
- 表创建 (WITH IF NOT EXISTS)
- 索引创建
- 触发器设置
- 函数定义
- 约束条件

**安全特性**:
- 所有创建语句都使用 `IF NOT EXISTS`
- 支持安全的重复执行
- 逻辑删除而非物理删除(可恢复)

---

## 🎯 对 AI 开发的建议

### 当修改 src/routes/device.py 时

**需要知道的事**:
1. device_token 来自 HTTP 请求头 `x-device-token`
2. 在每个请求前,先加载会话上下文
3. 在每个请求后,先更新上下文,再保存到数据库
4. message_history 是 JSONB 数组,可以直接追加
5. scene_elements 是数组,使用 Python list 操作

**关键代码位置**:
```python
# 在 handle_chat() 函数中
token = request.headers.get("x-device-token")
context = ConversationManager.get_conversation_context(token)

# 在融合 Prompt 后
fusion_result = PromptFusionEngine.fuse_drawing_prompt(...)

# 在生成画面后
context["scene_elements"] = fusion_result.get("all_elements_after", [])
ConversationManager.create_or_update_conversation_context(token, context)
```

### 当编写 API 端点时

**历史查询端点** (`/api/device/v1/conversation-history`):
```python
context = ConversationManager.get_conversation_context(token)
history = ConversationManager.get_drawing_history(token, limit)
# 返回: message_history[-limit:] 和 drawing_history
```

**重置端点** (`/api/device/v1/conversation-reset`):
```python
ConversationManager.delete_conversation_context(token, soft_delete=True)
# 后续请求会自动创建新的空上下文
```

### 当创建后台任务时

**清理任务**:
```python
async def cleanup_expired_contexts_task():
    while True:
        await asyncio.sleep(3600)  # 每小时运行一次
        deleted = ConversationManager.cleanup_expired_contexts(hours=24)
        logger.info(f"Cleaned {deleted} contexts")
```

---

**这份参考手册应该包含了 AI 进行代码开发所需的所有数据库信息! 🚀**

