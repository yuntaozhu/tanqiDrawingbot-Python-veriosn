# Railway PostgreSQL 数据库初始化指南

## 快速开始 - 3 步执行初始化

### 第一步:获取 PostgreSQL 连接信息

1. 打开 Railway 控制面板: https://railway.com/dashboard
2. 找到你的项目 **tanqi_server**
3. 点击 **Postgres** 服务
4. 点击 **Variables** 标签
5. 复制 **DATABASE_URL** 的值(长这样: `postgresql://user:password@host:port/database`)

### 第二步:连接到数据库(选择一种方法)

#### 方法 A: 使用 Railway CLI(推荐,最简单)

```bash
# 1. 安装 Railway CLI(如果未安装)
npm install -g @railway/cli

# 2. 登录 Railway
railway login

# 3. 链接到项目
cd /path/to/your/project
railway link
# 选择 tanqi_server 项目

# 4. 打开 PostgreSQL 交互式 Shell
railway psql
```

#### 方法 B: 使用本地 psql 客户端

```bash
# 使用你复制的 DATABASE_URL
psql postgresql://user:password@host:port/database

# 或者分别指定参数
psql -h <host> -p <port> -U <user> -d <database>
# 输入密码时会提示
```

#### 方法 C: 使用 pgAdmin(图形界面,适合新手)

1. 访问 pgAdmin: https://www.pgadmin.org/
2. 创建新连接,使用你的 DATABASE_URL 中的连接参数
3. 右键数据库 → Query Tool

### 第三步:执行初始化脚本

连接成功后,复制以下整个 SQL 脚本到 psql 交互式 Shell 或 pgAdmin Query Tool 中,然后执行:

```sql
-- ============================================================
-- 会话上下文表创建脚本
-- ============================================================

-- 创建会话上下文表
CREATE TABLE IF NOT EXISTS conversation_contexts (
 device_token TEXT PRIMARY KEY,
 message_history JSONB DEFAULT '[]'::jsonb,
 current_image_url TEXT,
 current_image_bitmap_hex TEXT,
 scene_elements TEXT[] DEFAULT '{}',
 last_generated_prompt TEXT,
 last_operation_type VARCHAR(20),
 last_operation_detail JSONB,
 created_at TIMESTAMP DEFAULT NOW(),
 updated_at TIMESTAMP DEFAULT NOW(),
 is_deleted BOOLEAN DEFAULT FALSE,
 CONSTRAINT valid_operation_type CHECK (
 last_operation_type IN ('create', 'add', 'modify', 'remove')
 OR last_operation_type IS NULL
 )
);

-- 创建索引以加速查询
CREATE INDEX IF NOT EXISTS idx_context_token ON conversation_contexts(device_token);
CREATE INDEX IF NOT EXISTS idx_context_updated ON conversation_contexts(updated_at);
CREATE INDEX IF NOT EXISTS idx_context_deleted ON conversation_contexts(is_deleted) 
 WHERE is_deleted = FALSE;

-- 创建触发器自动更新 updated_at
CREATE OR REPLACE FUNCTION update_conversation_context_timestamp()
RETURNS TRIGGER AS $$
BEGIN
 NEW.updated_at = NOW();
 RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 删除旧触发器(如果存在)
DROP TRIGGER IF EXISTS update_conversation_context_timestamp_trigger ON conversation_contexts;

-- 创建新触发器
CREATE TRIGGER update_conversation_context_timestamp_trigger
BEFORE UPDATE ON conversation_contexts
FOR EACH ROW
EXECUTE FUNCTION update_conversation_context_timestamp();

-- 创建绘画历史表
CREATE TABLE IF NOT EXISTS drawing_history (
 job_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
 device_token TEXT NOT NULL,
 user_prompt TEXT,
 expanded_prompt TEXT,
 image_url TEXT,
 bitmap_hex TEXT,
 scene_elements TEXT[] DEFAULT '{}',
 operation_type VARCHAR(20),
 created_at TIMESTAMP DEFAULT NOW(),
 CONSTRAINT valid_operation_type_drawing CHECK (
 operation_type IN ('create', 'add', 'modify', 'remove')
 OR operation_type IS NULL
 )
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_drawing_token ON drawing_history(device_token);
CREATE INDEX IF NOT EXISTS idx_drawing_created ON drawing_history(created_at);

-- 创建清理过期会话的函数
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

-- ============================================================
-- 验证创建成功
-- ============================================================
SELECT 'Conversation context tables created successfully!' as status;

-- 查看创建的表
\dt conversation_contexts
\dt drawing_history

-- 查看创建的函数
\df cleanup_expired_contexts
\df update_conversation_context_timestamp
```

## 执行后的验证

如果执行成功,你应该看到类似的输出:

```
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE OR REPLACE FUNCTION
DROP TRIGGER
CREATE TRIGGER
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE OR REPLACE FUNCTION
 status
────────────────────────────────────────────────
 Conversation context tables created successfully!
(1 row)
```

### 验证表的结构

执行以下命令查看表是否正确创建:

```sql
-- 查看 conversation_contexts 表的列
\d conversation_contexts

-- 查看 drawing_history 表的列
\d drawing_history

-- 查看索引
SELECT * FROM pg_indexes WHERE tablename IN ('conversation_contexts', 'drawing_history');

-- 查看函数
SELECT * FROM information_schema.routines WHERE routine_schema = 'public';
```

## 如果遇到错误

### 错误 1: 无法连接到数据库

```
psql: error: FATAL: Ident authentication failed for user "xxx"
```

**解决:**
- 检查 DATABASE_URL 是否正确复制
- 确保密码中的特殊字符已正确转义(如 @ 可能需要 %40)
- 尝试用 Railway CLI: `railway psql`

### 错误 2: 权限不足

```
ERROR: permission denied for schema public
```

**解决:**
- 确保使用的用户是数据库所有者
- 或者使用 Railway CLI 自动处理权限

### 错误 3: 表已存在

```
ERROR: relation "conversation_contexts" already exists
```

**这不是错误!** 脚本使用了 `IF NOT EXISTS`,所以重复运行是安全的。

## 下一步

初始化完成后:

1. **提交代码到 Git**
   ```bash
   git add -A
   git commit -m "Add database initialization schema for conversation contexts"
   git push origin main
   ```

2. **Railway 会自动部署新版本**
   - 监控 Railway Dashboard 的部署进度
   - 检查 Deploy logs 确认数据库初始化成功

3. **准备代码集成**
   - 使用其他 AI 工具(如 Claude/ChatGPT)完成 Python 代码集成
   - 集成会话上下文管理到 routes/device.py
   - 添加新的 API 端点

## 文件位置

- SQL 初始化脚本: `/repo/migrations/init_conversation_tables.sql`
- Python 初始化脚本: `/repo/init_db_railway.py`(自动方式,如果 Python 环境可用)
- 数据模型: `/repo/src/conversation_models.py`
- 数据库操作: `/repo/src/conversation_crud.py`
- 操作识别引擎: `/repo/src/operation_recognizer.py`
- Prompt 融合引擎: `/repo/src/prompt_fusion.py`

## 常见问题

**Q: 可以重复运行脚本吗?**
A: 是的,完全安全。脚本使用了 `IF NOT EXISTS`,重复运行不会导致错误。

**Q: 数据会丢失吗?**
A: 不会。`IF NOT EXISTS` 确保只在表不存在时创建,现有数据不会被删除。

**Q: 多久需要清理一次过期会话?**
A: 24 小时无交互的会话会被自动删除。在 Python 代码中可以配置此时间。

**Q: 可以看到所有的表和数据吗?**
A: 当然可以。使用 `\dt` 查看表列表,使用 `SELECT * FROM table_name` 查看数据。

