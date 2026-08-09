# 🚀 数据库连接快速参考（给 AI 的）

## 关键事实

✅ **PostgreSQL 已部署**: postgres.railway.internal  
✅ **环境变量已配置**: web 服务已自动引用 Postgres 服务  
✅ **连接方式**: 内网私有 DNS（安全、快速）  
✅ **SSL 支持**: PostgreSQL 18.4 with SSL  

---

## 使用数据库的 4 个步骤

### 1️⃣ 获取连接字符串

```python
import os

# 方式 A：使用完整 URL（推荐）
db_url = os.getenv("DATABASE_URL")

# 方式 B：手动构建
db_url = f"""postgresql://{os.getenv('PGUSER')}:{os.getenv('PGPASSWORD')}@{os.getenv('PGHOST')}:{os.getenv('PGPORT')}/{os.getenv('PGDATABASE')}"""
```

### 2️⃣ 创建 SQLAlchemy 引擎

```python
from sqlalchemy import create_engine

engine = create_engine(db_url, pool_pre_ping=True)
```

### 3️⃣ 创建会话工厂

```python
from sqlalchemy.orm import sessionmaker

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### 4️⃣ 在 FastAPI 中使用

```python
from fastapi import FastAPI, Depends

app = FastAPI()

@app.get("/test")
def test_db(db: Session = Depends(get_db)):
    result = db.query(YourModel).first()
    return {"status": "connected"}
```

---

## 环境变量速查表

| 变量 | 值类型 | 用途 |
|-----|--------|------|
| `DATABASE_URL` | String | 完整连接字符串 |
| `PGHOST` | String | 数据库主机（postgres.railway.internal） |
| `PGPORT` | Int | 端口（5432） |
| `PGUSER` | String | 用户名 |
| `PGDATABASE` | String | 数据库名 |
| `PGPASSWORD` | String | 密码（加密存储） |

---

## 数据库架构概览

### 表 1: conversation_contexts（会话上下文）

```sql
CREATE TABLE conversation_contexts (
    device_token VARCHAR(255) PRIMARY KEY,
    message_history JSONB,
    scene_elements TEXT[],
    last_generated_prompt TEXT,
    last_operation_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 表 2: drawing_history（绘画历史）

```sql
CREATE TABLE drawing_history (
    job_id VARCHAR(255) PRIMARY KEY,
    device_token VARCHAR(255) NOT NULL REFERENCES conversation_contexts(device_token),
    operation_type VARCHAR(50),
    scene_prompt TEXT,
    generated_image_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 常用 CRUD 操作

### 创建会话记录

```python
from sqlalchemy import insert
from models import ConversationContext

def create_context(db: Session, device_token: str):
    new_context = ConversationContext(
        device_token=device_token,
        message_history=[],
        scene_elements=[]
    )
    db.add(new_context)
    db.commit()
    return new_context
```

### 读取会话记录

```python
def get_context(db: Session, device_token: str):
    return db.query(ConversationContext).filter(
        ConversationContext.device_token == device_token
    ).first()
```

### 更新会话记录

```python
def update_context(db: Session, device_token: str, message_history: list):
    context = db.query(ConversationContext).filter(
        ConversationContext.device_token == device_token
    ).first()
    
    if context:
        context.message_history = message_history
        context.updated_at = datetime.utcnow()
        db.commit()
    return context
```

### 删除会话记录

```python
def delete_context(db: Session, device_token: str):
    db.query(ConversationContext).filter(
        ConversationContext.device_token == device_token
    ).delete()
    db.commit()
```

---

## 健康检查脚本

```python
from sqlalchemy import text

def check_db_health(engine):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            print("✅ 数据库连接成功")
            return True
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False

# 在应用启动时调用
if __name__ == "__main__":
    check_db_health(engine)
```

---

## 部署检查清单

- [ ] Postgres 服务运行中（railway.com 看板）
- [ ] web 服务变量包含 DATABASE_URL
- [ ] FastAPI 导入必要的库：sqlalchemy, psycopg2-binary
- [ ] 数据库初始化脚本已执行
- [ ] 表已创建
- [ ] 应用启动时能连接数据库

---

**注**: 所有环境变量由 Railway 自动注入，无需手动配置。

