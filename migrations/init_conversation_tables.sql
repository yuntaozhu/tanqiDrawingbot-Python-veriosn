-- 数据库初始化脚本 - 创建会话上下文表
-- 在 Railway PostgreSQL 中执行此脚本

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

-- 显示创建结果
SELECT 'Conversation context tables created successfully!' as status;

