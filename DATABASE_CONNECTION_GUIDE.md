# PostgreSQL 数据库连接完全指南

## 📊 数据库服务信息

**服务名称**: Postgres  
**服务 ID**: e382870f-d0f1-4d6a-abf8-f6a09ab71a5e  
**镜像**: PostgreSQL 18.4 (with SSL)  
**区域**: Southeast Asia (sin)  
**副本数**: 1  
**状态**: 🟢 Online  

---

## 🔑 连接凭证和信息

### 环境变量映射

你的 **web** 服务已配置以下环境变量，自动从 Postgres 服务引用：

| 环境变量 | 值 | 说明 |
|---------|-----|------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | **完整数据库连接字符串**（推荐使用） |
| `PGHOST` | `${{Postgres.PGHOST}}` | PostgreSQL 主机地址（私有 DNS） |
| `PGPORT` | `${{Postgres.PGPORT}}` | PostgreSQL 端口号 |
| `PGUSER` | `${{Postgres.PGUSER}}` | PostgreSQL 用户名 |
| `PGDATABASE` | `${{Postgres.PGDATABASE}}` | PostgreSQL 数据库名 |
| `PGPASSWORD` | `${{Postgres.PGPASSWORD}}` | PostgreSQL 密码（加密存储） |

---

## 📡 连接地址类型

### 1️⃣ **内部连接（推荐用于同项目内服务）**

**自动私有 DNS 地址**:
```
postgres.railway.internal
```

- ✅ 安全（私有网络）
- ✅ 无需认证（Railway 内网）
- ✅ 自动负载均衡
- 🏠 仅限 Railway 内部访问

**使用示例**（Python SQLAlchemy）:
```python
DATABASE_URL = "postgresql://username:password@postgres.railway.internal:5432/dbname"
```

---

### 2️⃣ **公共连接（外网访问，如本地开发）**

**TCP 代理公网地址**:
```
tanqiserver.up.railway.app:5432
```

- ✅ 可从任何地方连接（包括本地机器）
- ⚠️ 需要有效凭证
- 🔒 支持 SSL/TLS 加密

**使用示例**（psql 命令行）:
```bash
psql -h tanqiserver.up.railway.app -p 5432 -U username -d dbname
```

---

## 💻 Python 连接示例

### 方式 1: 使用 `DATABASE_URL`（最简洁）

```python
import os
from sqlalchemy import create_engine

# 直接从环境变量获取完整连接字符串
database_url = os.getenv("DATABASE_URL")
engine = create_engine(database_url)

# 测试连接
with engine.connect() as conn:
    result = conn.execute("SELECT 1")
    print("✅ 数据库连接成功！")
```

### 方式 2: 使用单个连接参数

```python
import os
from sqlalchemy import create_engine

# 从环境变量获取各个参数
host = os.getenv("PGHOST")  # postgres.railway.internal (内网)
port = os.getenv("PGPORT")  # 5432
user = os.getenv("PGUSER")  # postgres
password = os.getenv("PGPASSWORD")
database = os.getenv("PGDATABASE")

# 构建连接字符串
database_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
engine = create_engine(database_url)
```

### 方式 3: 使用 psycopg2（低级驱动）

```python
import psycopg2
import os

try:
    conn = psycopg2.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )
    
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    print("✅ PostgreSQL 版本:", cursor.fetchone())
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ 连接失败: {e}")
```

---

## 🔧 FastAPI 中的完整配置

在你的 FastAPI 应用中：

```python
# config.py 或 settings.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 从 Railway 环境变量获取
DATABASE_URL = os.getenv("DATABASE_URL")

# 如果 DATABASE_URL 不可用，手动构建
if not DATABASE_URL:
    DATABASE_URL = f"postgresql://{os.getenv('PGUSER')}:{os.getenv('PGPASSWORD')}@{os.getenv('PGHOST')}:{os.getenv('PGPORT')}/{os.getenv('PGDATABASE')}"

print(f"🔗 连接到: {os.getenv('PGHOST')}:{os.getenv('PGPORT')}/{os.getenv('PGDATABASE')}")

# 创建数据库引擎
engine = create_engine(
    DATABASE_URL,
    echo=False,  # 设为 True 可查看 SQL 语句
    pool_size=20,
    max_overflow=0,
    pool_pre_ping=True  # 检查连接有效性
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 依赖注入
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## 📱 本地开发连接（使用 Railway CLI）

### 1. 安装 Railway CLI

```bash
npm install -g @railway/cli
```

### 2. 链接本地项目

```bash
cd /path/to/your/project
railway link
```

### 3. 在本地获取环境变量

```bash
railway env
```

这会在你的本地环境中注入所有 Railway 变量。

### 4. 本地运行 FastAPI

```bash
railway run uvicorn main:app --reload
```

---

## 🔐 SSL/TLS 连接（可选，用于公网访问）

如果使用公网地址 `tanqiserver.up.railway.app:5432` 连接，建议启用 SSL：

```python
from sqlalchemy import create_engine

DATABASE_URL = os.getenv("DATABASE_URL")

# 添加 SSL 模式
if "postgresql" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://") + "?sslmode=require"

engine = create_engine(DATABASE_URL)
```

---

## ✅ 连接测试清单

在部署前，确保以下检查通过：

- [ ] 环境变量 `DATABASE_URL` / `PGHOST` / `PGPORT` / `PGUSER` / `PGDATABASE` / `PGPASSWORD` 存在
- [ ] Postgres 服务状态为 🟢 Online
- [ ] web 服务配置正确引用了 Postgres 变量（已 ✅ 配置）
- [ ] FastAPI 应用可以导入 SQLAlchemy
- [ ] 数据库初始化脚本已执行（如需要）
- [ ] 查询操作正常运行

---

## 🚨 常见问题排查

### 问题 1: "连接被拒绝"

```
psycopg2.OperationalError: could not connect to server
```

**解决**:
1. 确认 Postgres 服务在线（🟢 Online）
2. 检查环境变量是否正确加载
3. 如果使用公网地址，检查防火墙和 TCP 代理是否启用

### 问题 2: "认证失败"

```
psycopg2.OperationalError: FATAL: password authentication failed
```

**解决**:
1. 检查 `PGUSER` 和 `PGPASSWORD` 环境变量
2. 确保密码没有特殊字符冲突（使用 URL 编码）
3. 检查用户是否存在和有权限

### 问题 3: "找不到数据库"

```
psycopg2.OperationalError: FATAL: database "xxx" does not exist
```

**解决**:
1. 运行初始化脚本创建数据库和表
2. 检查 `PGDATABASE` 环境变量值
3. 使用 `psql` 连接并检查可用数据库

---

## 📚 相关文件

- **DATABASE_SCHEMA_REFERENCE.md** - 数据库表结构和 CRUD 操作
- **DEVELOPER_PROMPT.md** - 完整的开发提示词和实现任务
- **QUICK_DB_INIT.md** - 快速初始化脚本

---

**最后更新**: 2026-08-09  
**创建者**: Railway Agent

