import datetime
from sqlalchemy import Column, String, JSON, Text, DateTime, ForeignKey, Integer
from src.database import Base
from src.config import DATABASE_URL

# Check if we are running on PostgreSQL
is_postgres = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")

if is_postgres:
    from sqlalchemy.dialects.postgresql import ARRAY
    SceneElementsType = ARRAY(String)
else:
    SceneElementsType = JSON

class ConversationContext(Base):
    __tablename__ = "conversation_contexts"
    
    device_token = Column(String(255), primary_key=True, index=True)
    message_history = Column(JSON, default=list)
    scene_elements = Column(SceneElementsType, default=list)
    last_generated_prompt = Column(Text, nullable=True)
    last_operation_type = Column(String(50), nullable=True)
    current_scroll_id = Column(String(255), nullable=True, index=True)
    current_seed = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class DrawingHistory(Base):
    __tablename__ = "drawing_history"
    
    job_id = Column(String(255), primary_key=True, index=True)
    device_token = Column(String(255), ForeignKey("conversation_contexts.device_token", ondelete="CASCADE"), nullable=False)
    operation_type = Column(String(50), nullable=True)
    scene_prompt = Column(Text, nullable=True)
    generated_image_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
