"""
会话上下文 CRUD 操作 - 数据库读写
"""
import json
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from src.database import SessionLocal
from src.conversation_models import ConversationContextDB, DrawingHistoryDB


class ConversationManager:
    """会话上下文管理器"""
    
    @staticmethod
    def get_conversation_context(device_token: str) -> Optional[Dict[str, Any]]:
        """获取用户的会话上下文"""
        db = SessionLocal()
        try:
            context = db.query(ConversationContextDB).filter(
                ConversationContextDB.device_token == device_token,
                ConversationContextDB.is_deleted == False
            ).first()
            
            if not context:
                print(f"[DB] No context found for token: {device_token}")
                return None
            
            return {
                "device_token": context.device_token,
                "message_history": context.message_history or [],
                "current_image_url": context.current_image_url,
                "current_image_bitmap_hex": context.current_image_bitmap_hex,
                "scene_elements": context.scene_elements or [],
                "last_generated_prompt": context.last_generated_prompt,
                "last_operation_type": context.last_operation_type,
                "last_operation_detail": context.last_operation_detail or {},
                "created_at": context.created_at.isoformat() if context.created_at else None,
                "updated_at": context.updated_at.isoformat() if context.updated_at else None
            }
        except SQLAlchemyError as e:
            print(f"[DB] Error fetching context: {e}")
            return None
        finally:
            db.close()
    
    @staticmethod
    def create_or_update_conversation_context(device_token: str, context_data: Dict[str, Any]) -> bool:
        """创建或更新会话上下文"""
        db = SessionLocal()
        try:
            # Check if context exists
            existing = db.query(ConversationContextDB).filter(
                ConversationContextDB.device_token == device_token
            ).first()
            
            if existing:
                # Update existing
                existing.message_history = context_data.get("message_history", [])
                existing.current_image_url = context_data.get("current_image_url")
                existing.current_image_bitmap_hex = context_data.get("current_image_bitmap_hex")
                existing.scene_elements = context_data.get("scene_elements", [])
                existing.last_generated_prompt = context_data.get("last_generated_prompt")
                existing.last_operation_type = context_data.get("last_operation_type")
                existing.last_operation_detail = context_data.get("last_operation_detail")
                existing.is_deleted = False
                print(f"[DB] Updated context for token: {device_token}")
            else:
                # Create new
                new_context = ConversationContextDB(
                    device_token=device_token,
                    message_history=context_data.get("message_history", []),
                    current_image_url=context_data.get("current_image_url"),
                    current_image_bitmap_hex=context_data.get("current_image_bitmap_hex"),
                    scene_elements=context_data.get("scene_elements", []),
                    last_generated_prompt=context_data.get("last_generated_prompt"),
                    last_operation_type=context_data.get("last_operation_type"),
                    last_operation_detail=context_data.get("last_operation_detail")
                )
                db.add(new_context)
                print(f"[DB] Created new context for token: {device_token}")
            
            db.commit()
            return True
        except SQLAlchemyError as e:
            print(f"[DB] Error saving context: {e}")
            db.rollback()
            return False
        finally:
            db.close()
    
    @staticmethod
    def delete_conversation_context(device_token: str, soft_delete: bool = True) -> bool:
        """删除(逻辑或物理)会话上下文"""
        db = SessionLocal()
        try:
            context = db.query(ConversationContextDB).filter(
                ConversationContextDB.device_token == device_token
            ).first()
            
            if not context:
                print(f"[DB] Context not found for token: {device_token}")
                return False
            
            if soft_delete:
                # Logical delete
                context.is_deleted = True
                db.commit()
                print(f"[DB] Soft-deleted context for token: {device_token}")
            else:
                # Physical delete
                db.delete(context)
                db.commit()
                print(f"[DB] Hard-deleted context for token: {device_token}")
            
            return True
        except SQLAlchemyError as e:
            print(f"[DB] Error deleting context: {e}")
            db.rollback()
            return False
        finally:
            db.close()
    
    @staticmethod
    def append_message_to_context(device_token: str, message: Dict[str, Any]) -> bool:
        """向会话历史中添加一条消息"""
        db = SessionLocal()
        try:
            context = db.query(ConversationContextDB).filter(
                ConversationContextDB.device_token == device_token
            ).first()
            
            if not context:
                print(f"[DB] Context not found for token: {device_token}")
                return False
            
            # Ensure message_history is a list
            if not context.message_history:
                context.message_history = []
            
            # Append new message
            context.message_history.append(message)
            db.commit()
            print(f"[DB] Appended message to context for token: {device_token}")
            return True
        except SQLAlchemyError as e:
            print(f"[DB] Error appending message: {e}")
            db.rollback()
            return False
        finally:
            db.close()
    
    @staticmethod
    def save_drawing_history(device_token: str, drawing_data: Dict[str, Any]) -> bool:
        """保存绘画历史记录"""
        db = SessionLocal()
        try:
            drawing_record = DrawingHistoryDB(
                job_id=drawing_data.get("job_id", str(time.time())),
                device_token=device_token,
                user_prompt=drawing_data.get("user_prompt"),
                expanded_prompt=drawing_data.get("expanded_prompt"),
                image_url=drawing_data.get("image_url"),
                bitmap_hex=drawing_data.get("bitmap_hex"),
                scene_elements=drawing_data.get("scene_elements", []),
                operation_type=drawing_data.get("operation_type")
            )
            db.add(drawing_record)
            db.commit()
            print(f"[DB] Saved drawing history for token: {device_token}")
            return True
        except SQLAlchemyError as e:
            print(f"[DB] Error saving drawing history: {e}")
            db.rollback()
            return False
        finally:
            db.close()
    
    @staticmethod
    def get_drawing_history(device_token: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取用户的绘画历史"""
        db = SessionLocal()
        try:
            drawings = db.query(DrawingHistoryDB).filter(
                DrawingHistoryDB.device_token == device_token
            ).order_by(DrawingHistoryDB.created_at.desc()).limit(limit).all()
            
            return [
                {
                    "job_id": d.job_id,
                    "user_prompt": d.user_prompt,
                    "expanded_prompt": d.expanded_prompt,
                    "image_url": d.image_url,
                    "bitmap_hex": d.bitmap_hex,
                    "scene_elements": d.scene_elements or [],
                    "operation_type": d.operation_type,
                    "created_at": d.created_at.isoformat() if d.created_at else None
                }
                for d in drawings
            ]
        except SQLAlchemyError as e:
            print(f"[DB] Error fetching drawing history: {e}")
            return []
        finally:
            db.close()
    
    @staticmethod
    def cleanup_expired_contexts(hours: int = 24) -> int:
        """清理过期的会话上下文(支持可配置的过期时间)"""
        db = SessionLocal()
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # Delete old soft-deleted contexts
            result = db.query(ConversationContextDB).filter(
                ConversationContextDB.is_deleted == True,
                ConversationContextDB.updated_at < cutoff_time
            ).delete()
            
            db.commit()
            deleted_count = result
            print(f"[DB] 🧹 Cleaned up {deleted_count} expired contexts (older than {hours} hours)")
            return deleted_count
        except SQLAlchemyError as e:
            print(f"[DB] Error cleaning up expired contexts: {e}")
            db.rollback()
            return 0
        finally:
            db.close()
    
    @staticmethod
    def get_all_active_tokens() -> List[str]:
        """获取所有活跃用户的 device_token"""
        db = SessionLocal()
        try:
            contexts = db.query(ConversationContextDB.device_token).filter(
                ConversationContextDB.is_deleted == False
            ).all()
            return [c[0] for c in contexts]
        except SQLAlchemyError as e:
            print(f"[DB] Error fetching active tokens: {e}")
            return []
        finally:
            db.close()
    
    @staticmethod
    def get_context_statistics() -> Dict[str, Any]:
        """获取会话上下文的统计信息"""
        db = SessionLocal()
        try:
            total_contexts = db.query(ConversationContextDB).count()
            active_contexts = db.query(ConversationContextDB).filter(
                ConversationContextDB.is_deleted == False
            ).count()
            total_drawings = db.query(DrawingHistoryDB).count()
            
            return {
                "total_contexts": total_contexts,
                "active_contexts": active_contexts,
                "deleted_contexts": total_contexts - active_contexts,
                "total_drawings": total_drawings
            }
        except SQLAlchemyError as e:
            print(f"[DB] Error fetching statistics: {e}")
            return {}
        finally:
            db.close()

