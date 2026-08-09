# 🔴 部署崩溃分析与解决方案

## 问题诊断

**部署时间**: 2026-08-09 02:56:04 UTC  
**部署状态**: ❌ CRASHED  
**错误类型**: ModuleNotFoundError  
**影响**: 应用启动失败，web 服务无法运行

---

## 根本原因

### 错误日志分析

```
ModuleNotFoundError: No module named 'psycopg2'

Traceback (most recent call last):
  File "/app/src/database.py", line 11, in <module>
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
  ...
  File ".../sqlalchemy/dialects/postgresql/psycopg2.py", line 697, in import_dbapi
    import psycopg2
```

### 问题根源

✅ **SQLAlchemy 已安装** - requirements.txt 中有 sqlalchemy  
❌ **psycopg2 缺失** - requirements.txt 中没有 psycopg2-binary  

**链条**:
1. Railway 部署时读取 `requirements.txt`
2. 安装 SQLAlchemy 但没有安装 PostgreSQL 驱动（psycopg2）
3. FastAPI 应用启动时导入 `database.py`
4. SQLAlchemy 尝试创建 PostgreSQL 连接
5. 需要 psycopg2 模块，但找不到
6. 应用崩溃

---

## 解决方案

### 问题代码

**文件**: `requirements.txt`

```txt
fastapi
uvicorn
requests
python-dotenv
google-genai
pillow
numpy
opencv-python-headless
scipy
replicate
openai
sqlalchemy          ❌ 有 SQLAlchemy
redis
                    ❌ 缺少 psycopg2-binary!
```

### 修复方案

#### 方案 1: 添加 psycopg2-binary（推荐）

```txt
fastapi
uvicorn
requests
python-dotenv
google-genai
pillow
numpy
opencv-python-headless
scipy
replicate
openai
sqlalchemy
psycopg2-binary     ✅ 添加这一行
redis
```

**优点**:
- ✅ 预编译的二进制包（快速安装）
- ✅ 无需编译依赖
- ✅ Railway 构建时间短

**缺点**:
- 包体积稍大

#### 方案 2: 添加 psycopg2（替代方案，需要编译）

```txt
psycopg2             # 需要构建工具
```

**优点**:
- 更精简

**缺点**:
- 需要编译，需要 build-essential（Dockerfile 已有）
- 构建时间更长

#### 方案 3: 更新 requirements.txt（完整版本控制）

```txt
# Web Framework
fastapi==0.104.1
uvicorn==0.24.0

# Database
sqlalchemy==2.0.23
psycopg2-binary==2.9.9

# Utilities
requests==2.31.0
python-dotenv==1.0.0

# AI/ML
google-genai==0.3.0
pillow==10.1.0
numpy==1.24.3
opencv-python-headless==4.8.1.78
scipy==1.11.4
replicate==0.20.0
openai==1.3.0

# Cache
redis==5.0.1
```

**优点**:
- ✅ 完全的版本控制
- ✅ 可重复部署
- ✅ 避免版本冲突

---

## 为什么现在才出现这个问题?

### 时间线

1. **之前的部署** (2026-08-08 及之前)
   - 可能使用 SQLite 数据库（不需要 psycopg2）
   - 或者 requirements.txt 中已经有 psycopg2-binary

2. **新提交** (2026-08-09 02:56:04)
   - 添加了数据库代码（src/database.py）
   - 导入 PostgreSQL 相关模块
   - 部署时 SQLAlchemy 尝试创建 PostgreSQL 连接
   - **但 psycopg2 未安装** → 崩溃

### 代码变化分析

**新增文件**: `src/database.py`

```python
# 第 11 行 - 这里触发了错误
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

当 `DATABASE_URL` 为 PostgreSQL 格式时（railway 环境变量自动注入）：

```
postgresql://user:password@postgres.railway.internal:5432/dbname
```

SQLAlchemy 会尝试导入 `psycopg2` 作为 PostgreSQL 驱动，但由于 requirements.txt 中没有这个包，导致 ModuleNotFoundError。

---

## 快速修复步骤

### 1️⃣ 编辑 requirements.txt

```bash
# 在现有文件基础上添加
echo "psycopg2-binary==2.9.9" >> requirements.txt
```

或手动编辑：在 `sqlalchemy` 下一行添加 `psycopg2-binary`

### 2️⃣ 提交变更

```bash
git add requirements.txt
git commit -m "fix: add psycopg2-binary for PostgreSQL support"
git push origin main
```

### 3️⃣ Railway 自动部署

提交后 Railway 会自动检测变更，重新构建并部署。

---

## 预期结果

### 修复前 ❌

```
❌ ModuleNotFoundError: No module named 'psycopg2'
❌ Deployment Crashed
❌ 无法启动应用
```

### 修复后 ✅

```
✅ psycopg2-binary 成功安装
✅ SQLAlchemy 成功创建 PostgreSQL 连接
✅ 数据库表成功初始化 (Base.metadata.create_all)
✅ FastAPI 应用成功启动
✅ Deployment Status: SUCCESS
```

---

## 验证修复

### 部署后检查清单

- [ ] Railway Dashboard 显示 web 服务状态为 🟢 Online
- [ ] 部署日志没有 "ModuleNotFoundError" 错误
- [ ] 部署日志包含 "Installing collected packages: psycopg2-binary"
- [ ] 应用日志显示 "✅ 数据库初始化完成" 或类似成功消息
- [ ] 可以访问应用的健康检查端点 (/health)
- [ ] 数据库表已创建（可通过 psql 连接验证）

---

## 防止类似问题

### 最佳实践

1. **明确声明所有依赖**
   ```txt
   # requirements.txt 应包含：
   # - 框架 (fastapi, uvicorn)
   # - 数据库驱动 (psycopg2-binary for PostgreSQL, mysqlclient for MySQL)
   # - ORM (sqlalchemy)
   # - 其他库
   ```

2. **使用版本锁定**
   ```txt
   fastapi==0.104.1
   sqlalchemy==2.0.23
   psycopg2-binary==2.9.9
   ```

3. **分离不同数据库的配置**
   ```txt
   # 如果支持多个数据库：
   sqlalchemy==2.0.23
   psycopg2-binary==2.9.9  # PostgreSQL
   # mysqlclient==2.2.0   # MySQL (如需要)
   # sqlite 内置，无需额外包
   ```

4. **在开发时测试实际部署**
   ```bash
   # 本地测试与生产相同的环境
   pip install -r requirements.txt
   python app.py
   ```

5. **CI/CD 检查**
   在推送前验证所有导入都能成功：
   ```bash
   python -c "from src.database import SessionLocal; print('✅ Import OK')"
   ```

---

## 相关文件

- **requirements.txt** - Python 依赖文件（需要修改）
- **src/database.py** - 数据库连接配置（新增）
- **src/config.py** - 应用配置
- **src/conversation_models.py** - 新增的数据库模型

---

## 参考资源

### SQLAlchemy + PostgreSQL 最小依赖

```
sqlalchemy>=2.0
psycopg2-binary>=2.9
```

### Railway 部署最佳实践

1. 确保所有依赖都在 requirements.txt 中
2. 依赖应该是特定版本（避免兼容性问题）
3. 使用 -binary 后缀的包在 Railway 构建时更快（预编译）

---

**修复优先级**: 🔴 **高** - 应用完全无法运行  
**修复难度**: 🟢 **极低** - 只需添加一行依赖  
**预期修复时间**: ⚡ **2-3 分钟**

