import datetime
import random
import uuid
from typing import List, Dict, Any, Optional, Tuple
from src.database import SessionLocal
from src.conversation_models import ConversationContext, DrawingHistory

class ConversationManager:
    @staticmethod
    def get_conversation_context(device_token: str) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            record = db.query(ConversationContext).filter(ConversationContext.device_token == device_token).first()
            if not record:
                return None
            
            # Reconstruct context dict
            current_image_url = None
            latest_drawing = db.query(DrawingHistory).filter(DrawingHistory.device_token == device_token).order_by(DrawingHistory.created_at.desc()).first()
            if latest_drawing:
                current_image_url = latest_drawing.generated_image_url

            # Try to get current_image_bitmap_hex from message history
            current_image_bitmap_hex = None
            message_history = record.message_history or []
            for msg in reversed(message_history):
                if msg.get("drawing_triggered") and msg.get("drawing_config"):
                    cfg = msg.get("drawing_config", {})
                    current_image_bitmap_hex = cfg.get("bitmap_hex") or cfg.get("current_image_bitmap_hex")
                    if current_image_bitmap_hex:
                        break

            return {
                "device_token": record.device_token,
                "message_history": message_history,
                "current_image_url": current_image_url,
                "current_image_bitmap_hex": current_image_bitmap_hex,
                "scene_elements": record.scene_elements or [],
                "last_generated_prompt": record.last_generated_prompt,
                "last_operation_type": record.last_operation_type,
                "last_operation_detail": {},
                "current_scroll_id": getattr(record, "current_scroll_id", None),
                "current_seed": getattr(record, "current_seed", None),
                "created_at": record.created_at,
                "updated_at": record.updated_at
            }
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] get_conversation_context failed: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def create_or_update_conversation_context(device_token: str, context_data: Dict[str, Any]) -> bool:
        db = SessionLocal()
        try:
            record = db.query(ConversationContext).filter(ConversationContext.device_token == device_token).first()
            
            message_history = context_data.get("message_history", [])
            scene_elements = context_data.get("scene_elements", [])
            last_generated_prompt = context_data.get("last_generated_prompt")
            last_operation_type = context_data.get("last_operation_type")
            
            if record:
                record.message_history = message_history
                record.scene_elements = scene_elements
                record.last_generated_prompt = last_generated_prompt
                record.last_operation_type = last_operation_type
                record.updated_at = datetime.datetime.utcnow()
            else:
                record = ConversationContext(
                    device_token=device_token,
                    message_history=message_history,
                    scene_elements=scene_elements,
                    last_generated_prompt=last_generated_prompt,
                    last_operation_type=last_operation_type,
                    created_at=datetime.datetime.utcnow(),
                    updated_at=datetime.datetime.utcnow()
                )
                db.add(record)
            
            db.commit()
            return True
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] create_or_update_conversation_context failed: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def _new_seed() -> int:
        return random.randint(1, 2147483647)

    @staticmethod
    def ensure_scroll(device_token: str) -> Tuple[str, int]:
        """Return the device's current scroll_id and seed, creating them if missing."""
        db = SessionLocal()
        try:
            record = db.query(ConversationContext).filter(ConversationContext.device_token == device_token).first()
            if record and getattr(record, "current_scroll_id", None) and getattr(record, "current_seed", None) is not None:
                return record.current_scroll_id, int(record.current_seed)

            scroll_id = str(uuid.uuid4())
            seed = ConversationManager._new_seed()
            now = datetime.datetime.utcnow()
            if record:
                record.current_scroll_id = scroll_id
                record.current_seed = seed
                record.updated_at = now
            else:
                record = ConversationContext(
                    device_token=device_token,
                    message_history=[],
                    scene_elements=[],
                    current_scroll_id=scroll_id,
                    current_seed=seed,
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
            db.commit()
            print(f"[INFO] [SCROLL] Ensured scroll {scroll_id} seed={seed} token={device_token[:8]}***")
            return scroll_id, seed
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] ensure_scroll failed: {e}")
            db.rollback()
            return str(uuid.uuid4()), ConversationManager._new_seed()
        finally:
            db.close()

    @staticmethod
    def start_new_scroll(device_token: str) -> Dict[str, Any]:
        """Open a new related-image scroll: new seed, empty scene. Does not reset chat history."""
        db = SessionLocal()
        try:
            scroll_id = str(uuid.uuid4())
            seed = ConversationManager._new_seed()
            now = datetime.datetime.utcnow()
            record = db.query(ConversationContext).filter(ConversationContext.device_token == device_token).first()
            if record:
                record.current_scroll_id = scroll_id
                record.current_seed = seed
                record.scene_elements = []
                record.last_generated_prompt = None
                record.last_operation_type = None
                record.updated_at = now
            else:
                record = ConversationContext(
                    device_token=device_token,
                    message_history=[],
                    scene_elements=[],
                    last_generated_prompt=None,
                    last_operation_type=None,
                    current_scroll_id=scroll_id,
                    current_seed=seed,
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
            db.commit()
            from src.crud import reset_scroll_seq_cursor
            reset_scroll_seq_cursor(scroll_id)
            print(f"[INFO] [SCROLL] New scroll {scroll_id} seed={seed} token={device_token[:8]}***")
            return {
                "success": True,
                "scroll_id": scroll_id,
                "seed": seed,
                "images": [],
            }
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] start_new_scroll failed: {e}")
            db.rollback()
            return {"success": False, "scroll_id": None, "seed": None, "images": []}
        finally:
            db.close()

    @staticmethod
    def get_drawing_history(device_token: str, limit: int = 20) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            drawings = db.query(DrawingHistory).filter(DrawingHistory.device_token == device_token).order_by(DrawingHistory.created_at.desc()).limit(limit).all()
            return [
                {
                    "job_id": d.job_id,
                    "device_token": d.device_token,
                    "operation_type": d.operation_type,
                    "scene_prompt": d.scene_prompt,
                    "generated_image_url": d.generated_image_url,
                    "created_at": d.created_at.isoformat() if d.created_at else None
                }
                for d in drawings
            ]
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] get_drawing_history failed: {e}")
            return []
        finally:
            db.close()

    @staticmethod
    def delete_conversation_context(device_token: str, soft_delete: bool = True) -> bool:
        db = SessionLocal()
        try:
            if soft_delete:
                record = db.query(ConversationContext).filter(ConversationContext.device_token == device_token).first()
                if record:
                    record.message_history = []
                    record.scene_elements = []
                    record.last_generated_prompt = None
                    record.last_operation_type = None
                    record.updated_at = datetime.datetime.utcnow()
                    db.commit()
                else:
                    record = ConversationContext(
                        device_token=device_token,
                        message_history=[],
                        scene_elements=[],
                        last_generated_prompt=None,
                        last_operation_type=None,
                        created_at=datetime.datetime.utcnow(),
                        updated_at=datetime.datetime.utcnow()
                    )
                    db.add(record)
                    db.commit()
            else:
                db.query(ConversationContext).filter(ConversationContext.device_token == device_token).delete()
                db.commit()
            return True
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] delete_conversation_context failed: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    @staticmethod
    def cleanup_expired_contexts(hours: int = 24) -> int:
        db = SessionLocal()
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
            deleted_count = db.query(ConversationContext).filter(ConversationContext.updated_at < cutoff).delete()
            db.commit()
            return deleted_count
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] cleanup_expired_contexts failed: {e}")
            db.rollback()
            return 0
        finally:
            db.close()

    @staticmethod
    def save_drawing_record(job_id: str, device_token: str, operation_type: str, scene_prompt: str, image_url: str):
        db = SessionLocal()
        try:
            ctx = db.query(ConversationContext).filter(ConversationContext.device_token == device_token).first()
            if not ctx:
                ctx = ConversationContext(
                    device_token=device_token,
                    message_history=[],
                    scene_elements=[],
                    created_at=datetime.datetime.utcnow(),
                    updated_at=datetime.datetime.utcnow()
                )
                db.add(ctx)
                db.commit()
                
            drawing = DrawingHistory(
                job_id=job_id,
                device_token=device_token,
                operation_type=operation_type,
                scene_prompt=scene_prompt,
                generated_image_url=image_url,
                created_at=datetime.datetime.utcnow()
            )
            db.add(drawing)
            db.commit()
            print(f"[INFO] [CONV_CRUD] Saved drawing record for job: {job_id}")
            return True
        except Exception as e:
            print(f"[ERROR] [CONV_CRUD] save_drawing_record failed: {e}")
            db.rollback()
            return False
        finally:
            db.close()
