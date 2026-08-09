# 🤖 AI 修复提示词：解决 PostgreSQL 驱动缺失问题

> 这份提示词针对最近部署失败的 ModuleNotFoundError: psycopg2 问题

---

## 问题描述

**当前状态**: web 服务在 Railway 上部署崩溃 (CRASHED)

**错误日志**:
```
ModuleNotFoundError: No module named 'psycopg2'

Traceback:
  File "/app/src/database.py", line 11, in <module>
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

**根本原因**: `requirements.txt` 中缺少 `psycopg2-binary` 包，但代码需要它来连接 PostgreSQL

---

## 修复任务

### 任务 1: 更新 requirements.txt

**目标**: 添加 PostgreSQL 驱动，确保 Railway 构建时安装所有必需的依赖

**具体步骤**:

1. **找到 requirements.txt 文件**
   - 文件路径: `/requirements.txt` (项目根目录)
   
2. **在 requirements.txt 中找到 `sqlalchemy` 行**
   - 当前内容: `sqlalchemy` (无版本号)
   
3. **在 `sqlalchemy` 下方添加 `psycopg2-binary`**
   
   **修改前**:
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
   redis
   ```
   
   **修改后**:
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
   psycopg2-binary
   redis
   ```

4. **可选: 添加版本号以提高稳定性**
   
   如果要指定版本（推荐）:
   ```txt
   sqlalchemy==2.0.23
   psycopg2-binary==2.9.9
   ```

**为什么选择 psycopg2-binary**:
- ✅ 预编译的二进制包（快速安装）
- ✅ 无需在 Railway 上编译（加快部署）
- ✅ 兼容性好
- ✅ 文件大小合理

---

### 任务 2: 验证其他依赖（可选但推荐）

**目标**: 确保 requirements.txt 中的所有依赖都是必需的，避免构建膨胀

**检查项**:

- [ ] SQLAlchemy: 已有（数据库 ORM）
- [ ] FastAPI: 已有（Web 框架）
- [ ] 是否有过时或未使用的包？（如有可删除以加快构建）
- [ ] 是否有冲突的版本？（通常 pip 会自动处理）

**当前 requirements.txt 分析**:

| 包 | 用途 | 状态 |
|---|------|------|
| fastapi | Web 框架 | ✅ 需要 |
| uvicorn | ASGI 服务器 | ✅ 需要 |
| requests | HTTP 请求 | ✅ 需要 |
| python-dotenv | 环境变量管理 | ✅ 需要 |
| google-genai | Google AI API | ✅ 需要 |
| pillow | 图像处理 | ✅ 需要 |
| numpy | 数值计算 | ✅ 需要 |
| opencv-python-headless | 图像处理（无 GUI） | ✅ 需要 |
| scipy | 科学计算 | ✅ 需要 |
| replicate | Replicate API | ✅ 需要 |
| openai | OpenAI API | ✅ 需要 |
| sqlalchemy | 数据库 ORM | ✅ 需要 |
| redis | 缓存/消息队列 | ✅ 需要 |
| **psycopg2-binary** | **PostgreSQL 驱动** | **❌ 缺失** |

---

### 任务 3: 提交更改

**目标**: 将修复推送到 GitHub，触发 Railway 自动部署

**命令**:

```bash
# 1. 查看修改
git diff requirements.txt

# 2. 暂存修改
git add requirements.txt

# 3. 提交
git commit -m "fix: add psycopg2-binary for PostgreSQL database support

- Fixes ModuleNotFoundError when SQLAlchemy tries to import psycopg2
- Enables PostgreSQL connection in Railway environment
- Railway will automatically rebuild and redeploy"

# 4. 推送
git push origin main
```

**预期提交信息**:
```
fix: add psycopg2-binary for PostgreSQL database support
```

---

### 任务 4: 验证部署（修复完成后）

**目标**: 确认应用成功部署并运行

**验证步骤**:

1. **检查 Railway Dashboard**
   - 访问: https://railway.com/project/ef9c7ab2-7b71-4065-9a13-998636031fd1
   - 查看 web 服务状态
   - 应该显示: 🟢 Online (而不是 ❌ Crashed)

2. **查看构建日志**
   - Railway Dashboard → Deployments
   - 查看最新部署的日志
   - 应该包含: `Installing collected packages: ... psycopg2-binary ...`
   - 不应该包含: ModuleNotFoundError

3. **查看运行日志**
   - 点击部署详情
   - 查看 "Deploy Logs" 选项卡
   - 应该看到:
     ```
     ✅ 数据库初始化完成
     或
     [INFO] Database initialized
     或类似的成功消息
     ```

4. **测试应用健康检查**
   - 访问: `https://tanqibot.up.railway.app/health`
   - 应该返回: `{"status": "healthy", "database": "connected"}`

5. **检查数据库连接**
   - 如果应用中有数据库查询端点，测试其功能
   - 应该能正常读写数据库

---

## 为什么会出现这个问题？

### 问题时间线

**2026-08-08**:
- 代码中可能还没有使用 PostgreSQL
- 或者使用了 SQLite（内置驱动）

**2026-08-09 02:56**:
- 新提交添加了 src/database.py
- 该文件尝试连接 PostgreSQL（使用 Railway 的 DATABASE_URL）
- SQLAlchemy 需要 psycopg2 驱动
- 但 requirements.txt 中没有声明这个依赖
- 结果: 应用启动时崩溃

---

## 代码上下文

### database.py 中的关键代码

```python
# src/database.py - 第 11 行
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

当 `DATABASE_URL` 为 `postgresql://...` 时，SQLAlchemy 会自动尝试导入 psycopg2:

```python
# 在 SQLAlchemy 内部
if url.drivername == "postgresql":
    import psycopg2  # ← 这里失败了！
```

### config.py 中的数据库配置

```python
# src/config.py
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app_history.db")
```

Railway 环境中会注入 `DATABASE_URL` 环境变量:
```
postgresql://user:pass@postgres.railway.internal:5432/dbname
```

---

## 检查清单

完成所有项目后，修复就完成了：

- [ ] 打开 requirements.txt
- [ ] 找到 `sqlalchemy` 行
- [ ] 在其下方添加 `psycopg2-binary`
- [ ] 保存文件
- [ ] 运行 `git add requirements.txt`
- [ ] 运行 `git commit -m "fix: add psycopg2-binary for PostgreSQL database support"`
- [ ] 运行 `git push origin main`
- [ ] 等待 2-3 分钟让 Railway 构建和部署
- [ ] 验证 web 服务状态为 🟢 Online
- [ ] 检查部署日志中包含 psycopg2-binary
- [ ] 测试应用的 /health 端点
- [ ] 确认应用运行无错误

---

## 相关文件

- **requirements.txt** - 需要修改（添加 psycopg2-binary）
- **src/database.py** - 引发问题的文件（不需要修改）
- **src/config.py** - 数据库 URL 配置（不需要修改）
- **DEPLOYMENT_CRASH_ANALYSIS.md** - 详细的问题分析

---

## 问题诊断参考

如果修复后仍然出现问题，可以参考以下诊断步骤：

1. **构建阶段失败**
   - 检查 requirements.txt 语法是否正确（每行一个包）
   - 检查包名是否正确拼写
   - 查看 Railway 的 "Build Logs" 是否有 pip 错误

2. **运行阶段失败**
   - 检查 DATABASE_URL 环境变量是否正确设置
   - 查看完整的错误堆栈跟踪
   - 确认 PostgreSQL 服务在线

3. **连接失败**
   - 验证 PostgreSQL 服务状态 (🟢 Online)
   - 检查网络连接（内网 postgres.railway.internal）
   - 验证数据库凭证

---

## 完成标志

✅ **修复成功的标志**:

```
web service status: 🟢 Online
deployment status: ✅ SUCCESS
psycopg2-binary: ✅ Installed
database connection: ✅ Connected
application startup: ✅ Ready
```

---

**优先级**: 🔴 **紧急** - 应用无法运行  
**修复复杂度**: 🟢 **极低** - 1 行代码修改  
**预期修复时间**: ⚡ **2-3 分钟**

