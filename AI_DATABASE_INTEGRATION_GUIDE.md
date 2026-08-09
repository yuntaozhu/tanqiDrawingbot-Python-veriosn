# 🤖 AI 工程师数据库集成完全指南

> 本文档面向 Claude、ChatGPT 或其他 AI 工具，提供快速集成数据库所需的全部信息

---

## 📋 项目上下文

- **项目名**: tanqi_server (多轮对话绘画应用)
- **框架**: FastAPI + SQLAlchemy + PostgreSQL
- **数据库**: PostgreSQL 18.4 (with SSL)
- **部署平台**: Railway
- **环境**: 生产环境（Southeast Asia 区域）

---

## 🔑 数据库凭证（自动注入）

### Railway 环境变量

web 服务自动引用 Postgres 服务，以下变量在运行时可用：

```python
import os

# 完整连接字符串（推荐使用）
DATABASE_URL = os.getenv("DATABASE_URL")

# 或使用单个参数（用于调试/灵活配置）
PGHOST = os.getenv("PGHOST")           # postgres.railway.internal
PGPORT = os.getenv("PGPORT")           # 5432
PGUSER = os.getenv("PGUSER")           # postgres
PGPASSWORD = os.getenv("PGPASSWORD")   # [加密密码]
PGDATABASE = os.getenv("PGDATABASE")   # [数据库名]
```

### 连接字符串格式

```
postgresql://[username]:[password]@postgres.railway.internal:5432/[database_name]
```

---

## 🏗️ 数据库架构

### 完整表结构

#### 表 1: conversation_contexts

```python
from sqlalchemy import Column, String, JSON, ARRAY, Text, DateTime
from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ConversationContext(Base):
    __tablename__ = "conversation_contexts"
    
    # 主键：设备唯一标识
    device_token = Column(String(255), primary_key=True)
    
    # 消息历史（JSONB 格式，每条消息包含 role, content, timestamp）
    message_history = Column(JSON, default=list)
    
    # 场景元素数组（存储当前会话中提到的画面元素）
    scene_elements = Column(ARRAY(String), default=list)
    
    # 最后生成的提示词
    last_generated_prompt = Column(Text, nullable=True)
    
    # 最后操作类型（create / add / modify / remove）
    last_operation_type = Column(String(50), nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**关键字段说明**:
- `device_token`: 唯一标识每个用户/设备
- `message_history`: JSONB 格式，示例：
  ```json
  [
    {"role": "user", "content": "绘制一个红色的房子", "timestamp": "2026-08-09T10:30:00Z"},
    {"role": "assistant", "content": "已生成提示词，调用绘画API...", "timestamp": "2026-08-09T10:30:05Z"}
  ]
  ```
- `scene_elements`: 当前场景中的元素，示例：`["red house", "green tree", "blue sky"]`
- `last_operation_type`: 最后的操作类型，用于上下文管理

#### 表 2: drawing_history

```python
class DrawingHistory(Base):
    __tablename__ = "drawing_history"
    
    # 主键：绘画任务 ID
    job_id = Column(String(255), primary_key=True)
    
    # 外键：关联会话上下文
    device_token = Column(String(255), ForeignKey("conversation_contexts.device_token"), nullable=False)
    
    # 操作类型（create / add / modify / remove）
    operation_type = Column(String(50), nullable=True)
    
    # 生成的提示词（用于绘画 API）
    scene_prompt = Column(Text, nullable=True)
    
    # 生成的图片 URL（来自绘画 API 的返回值）
    generated_image_url = Column(Text, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
```

---

## 🔧 SQLAlchemy 配置模板

### 最小化配置

```python
# db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

# 获取连接字符串
DATABASE_URL = os.getenv("DATABASE_URL")

# 创建引擎（带连接池和健康检查）
engine = create_engine(
    DATABASE_URL,
    echo=False,  # 设为 True 可查看 SQL 语句
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # 每次使用连接前检查有效性
    pool_recycle=3600,   # 1 小时后回收连接
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 声明基类（用于 ORM 模型）
Base = declarative_base()

# 依赖注入函数
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### 高级配置（带日志和错误处理）

```python
# db.py
import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "False").lower() == "true",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# 监听连接事件（用于诊断）
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    logger.debug("✅ 新数据库连接已建立")

@event.listens_for(engine, "close")
def receive_close(dbapi_conn, connection_record):
    logger.debug("❌ 数据库连接已关闭")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError as e:
        logger.error(f"❌ 数据库错误: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """创建所有表"""
    from models import Base
    Base.metadata.create_all(bind=engine)
```

---

## 📝 FastAPI 集成示例

### 基础 CRUD 操作

```python
# schemas.py - Pydantic 数据验证
from pydantic import BaseModel
from typing import List, Optional

class ConversationContextCreate(BaseModel):
    device_token: str
    message_history: Optional[List[dict]] = []
    scene_elements: Optional[List[str]] = []

class ConversationContextResponse(ConversationContextCreate):
    created_at: str
    updated_at: str

# crud.py - 数据库操作
from sqlalchemy.orm import Session
from models import ConversationContext, DrawingHistory
from datetime import datetime
import json

def create_context(db: Session, device_token: str):
    """创建新会话上下文"""
    context = ConversationContext(
        device_token=device_token,
        message_history=[],
        scene_elements=[]
    )
    db.add(context)
    db.commit()
    db.refresh(context)
    return context

def get_context(db: Session, device_token: str):
    """获取会话上下文"""
    return db.query(ConversationContext).filter(
        ConversationContext.device_token == device_token
    ).first()

def update_context(db: Session, device_token: str, **kwargs):
    """更新会话上下文"""
    context = get_context(db, device_token)
    if not context:
        return None
    
    for key, value in kwargs.items():
        if hasattr(context, key):
            setattr(context, key, value)
    
    context.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(context)
    return context

def add_message(db: Session, device_token: str, role: str, content: str):
    """添加消息到会话历史"""
    context = get_context(db, device_token)
    if not context:
        context = create_context(db, device_token)
    
    # 确保 message_history 是列表
    if context.message_history is None:
        context.message_history = []
    
    # 添加新消息
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat()
    }
    context.message_history.append(message)
    context.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(context)
    return context

def delete_context(db: Session, device_token: str):
    """删除会话上下文"""
    db.query(ConversationContext).filter(
        ConversationContext.device_token == device_token
    ).delete()
    db.commit()
    return True

def save_drawing(db: Session, job_id: str, device_token: str, operation_type: str, 
                 scene_prompt: str, image_url: str):
    """保存绘画历史"""
    drawing = DrawingHistory(
        job_id=job_id,
        device_token=device_token,
        operation_type=operation_type,
        scene_prompt=scene_prompt,
        generated_image_url=image_url
    )
    db.add(drawing)
    db.commit()
    db.refresh(drawing)
    return drawing

def get_drawing_history(db: Session, device_token: str):
    """获取用户的绘画历史"""
    return db.query(DrawingHistory).filter(
        DrawingHistory.device_token == device_token
    ).all()
```

### FastAPI 路由

```python
# main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from db import SessionLocal, get_db, init_db
from crud import (
    create_context, get_context, update_context, delete_context,
    add_message, save_drawing, get_drawing_history
)

app = FastAPI(title="TanqiBot API")

# 应用启动时初始化数据库
@app.on_event("startup")
def startup():
    init_db()
    print("✅ 数据库初始化完成")

# ==================== 会话管理 API ====================

@app.post("/api/conversation/init")
def init_conversation(device_token: str, db: Session = Depends(get_db)):
    """初始化新会话"""
    existing = get_context(db, device_token)
    if existing:
        return {"status": "exists", "device_token": device_token}
    
    context = create_context(db, device_token)
    return {
        "status": "created",
        "device_token": device_token,
        "message_history": context.message_history
    }

@app.get("/api/conversation/{device_token}")
def get_conversation(device_token: str, db: Session = Depends(get_db)):
    """获取会话信息"""
    context = get_context(db, device_token)
    if not context:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {
        "device_token": context.device_token,
        "message_history": context.message_history,
        "scene_elements": context.scene_elements,
        "last_operation_type": context.last_operation_type,
        "created_at": context.created_at.isoformat(),
        "updated_at": context.updated_at.isoformat()
    }

@app.post("/api/conversation/{device_token}/message")
def add_conversation_message(device_token: str, role: str, content: str, 
                           db: Session = Depends(get_db)):
    """添加消息到会话"""
    context = add_message(db, device_token, role, content)
    return {
        "status": "added",
        "message_count": len(context.message_history),
        "last_message": context.message_history[-1] if context.message_history else None
    }

# ==================== 绘画历史 API ====================

@app.post("/api/drawing/save")
def save_drawing_record(job_id: str, device_token: str, operation_type: str,
                        scene_prompt: str, image_url: str,
                        db: Session = Depends(get_db)):
    """保存绘画记录"""
    drawing = save_drawing(db, job_id, device_token, operation_type, scene_prompt, image_url)
    return {
        "status": "saved",
        "job_id": drawing.job_id,
        "image_url": drawing.generated_image_url
    }

@app.get("/api/drawing/history/{device_token}")
def get_history(device_token: str, db: Session = Depends(get_db)):
    """获取绘画历史"""
    drawings = get_drawing_history(db, device_token)
    return {
        "device_token": device_token,
        "drawings": [
            {
                "job_id": d.job_id,
                "operation_type": d.operation_type,
                "image_url": d.generated_image_url,
                "created_at": d.created_at.isoformat()
            }
            for d in drawings
        ]
    }

# ==================== 健康检查 ====================

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """健康检查（包括数据库连接）"""
    try:
        db.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
```

---

## 📊 数据初始化 SQL

```sql
-- 创建会话上下文表
CREATE TABLE conversation_contexts (
    device_token VARCHAR(255) PRIMARY KEY,
    message_history JSONB DEFAULT '[]'::jsonb,
    scene_elements TEXT[] DEFAULT ARRAY[]::text[],
    last_generated_prompt TEXT,
    last_operation_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建绘画历史表
CREATE TABLE drawing_history (
    job_id VARCHAR(255) PRIMARY KEY,
    device_token VARCHAR(255) NOT NULL REFERENCES conversation_contexts(device_token) ON DELETE CASCADE,
    operation_type VARCHAR(50),
    scene_prompt TEXT,
    generated_image_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引（加速查询）
CREATE INDEX idx_drawing_history_device_token ON drawing_history(device_token);
CREATE INDEX idx_conversation_contexts_created_at ON conversation_contexts(created_at);
```

---

## 🔍 测试和调试

### 连接测试

```python
from sqlalchemy import text

def test_connection(engine):
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()
            print(f"✅ PostgreSQL 版本: {version[0]}")
            return True
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False
```

### 查询调试

```python
# 在应用中启用 SQL 日志
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

---

## 📦 依赖项

在 `requirements.txt` 中添加：

```
fastapi==0.104.1
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
uvicorn==0.24.0
python-dotenv==1.0.0
pydantic==2.5.0
```

---

## 🚀 部署前检查清单

- [ ] 数据库 URL 通过 `DATABASE_URL` 环境变量注入
- [ ] SQLAlchemy 模型定义完整
- [ ] 所有表已创建（通过 `init_db()` 或手动 SQL）
- [ ] CRUD 操作逻辑正确
- [ ] FastAPI 路由已实现
- [ ] 健康检查端点正常
- [ ] 日志记录配置完成
- [ ] 异常处理覆盖完整
- [ ] 连接池参数合理
- [ ] 已测试本地连接

---

**说明**: 此文档包含所有必要信息，用于快速实现数据库集成。将此文档共享给 AI 工程师以加快实现速度。


