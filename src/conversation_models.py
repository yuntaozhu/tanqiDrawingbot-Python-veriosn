"""
会话上下文数据模型 - 用于多轮对话的上下文管理
"""
from sqlalchemy import Column, String, TIMESTAMP, JSON, ARRAY, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from src.database import Base


class ConversationContextDB(Base):
    """
    会话上下文表 - 存储每个用户(device_token)的完整会话状态
    """
    __tablename__ = "conversation_contexts"

    # Primary key: device token (用户唯一标识)
    device_token = Column(String(255), primary_key=True, index=True)
    
    # 消息历史 - JSON 数组,存储所有消息
    # 结构: [
    #   {
    #     "timestamp": 1628...,
    #     "user_text": "画查理王小猎犬奔跑",
    #     "ai_response": "我为你画...",
    #     "drawing_triggered": true,
    #     "drawing_config": { ... },
    #     "metadata": { ... }
    #   },
    #   ...
    # ]
    message_history = Column(JSON, default=list, nullable=False)
    
    # 当前画面信息
    current_image_url = Column(String, nullable=True)
    current_image_bitmap_hex = Column(String, nullable=True)
    
    # 场景元素列表 - 当前画面包含的所有元素
    # 例: ["小猎犬", "小兔子", "草地"]
    scene_elements = Column(ARRAY(String), default=list, nullable=False)
    
    # 最后一次有效的完整 Prompt
    last_generated_prompt = Column(String, nullable=True)
    
    # 最后一次操作的类型: 'create', 'add', 'modify', 'remove'
    last_operation_type = Column(String(20), nullable=True)
    
    # 最后一次操作的详细信息
    # 结构: {"type": "add", "target": "小狗", "position": "小兔子旁边", ...}
    last_operation_detail = Column(JSON, nullable=True)
    
    # 时间戳
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 逻辑删除标志
    is_deleted = Column(Boolean, default=False, nullable=False)


class DrawingHistoryDB(Base):
    """
    绘画历史表 - 记录每一次绘画生成
    """
    __tablename__ = "drawing_history"
    
    # Primary key
    job_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Foreign key to conversation_contexts
    device_token = Column(String(255), index=True, nullable=False)
    
    # 用户原始输入 Prompt
    user_prompt = Column(String, nullable=True)
    
    # LLM 扩展后的 Prompt
    expanded_prompt = Column(String, nullable=True)
    
    # 生成的图片 URL
    image_url = Column(String, nullable=True)
    
    # Bitmap 十六进制
    bitmap_hex = Column(String, nullable=True)
    
    # 画面中的元素列表
    scene_elements = Column(ARRAY(String), default=list, nullable=False)
    
    # 操作类型: 'create', 'add', 'modify', 'remove'
    operation_type = Column(String(20), nullable=True)
    
    # 时间戳
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    
    # 索引
    __table_args__ = (
        Column('device_token', String(255), index=True),
        Column('created_at', TIMESTAMP, index=True),
    )

