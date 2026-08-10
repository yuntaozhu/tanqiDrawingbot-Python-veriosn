from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DatabaseError
import os
from src.config import DATABASE_URL

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# To support backward compatibility for any existing imports from src.database
# we import all models here.
from src.models import (
    GenerationHistoryDB, FeedbackDB, PrintJobDB, PsychVectorDB, DeviceSettingsDB
)
from src.conversation_models import ConversationContext, DrawingHistory

import threading
import time

_db_initialized = False
_db_init_lock = threading.Lock()

def _ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        try:
            Base.metadata.create_all(bind=engine)
        except Exception as e:
            print(f"[WARNING] Database initialization encountered error: {e}. Attempting to recreate database...")
            engine.dispose()
            if DATABASE_URL.startswith("sqlite:///"):
                db_path = DATABASE_URL.replace("sqlite:///", "")
                if os.path.exists(db_path):
                    try:
                        os.remove(db_path)
                        print(f"[INFO] Removed corrupted database file: {db_path}")
                    except Exception as rm_err:
                        print(f"[ERROR] Failed to remove db file: {rm_err}")
            Base.metadata.create_all(bind=engine)
            print("[INFO] Database recreated successfully.")
        _db_initialized = True

def initialize_db_schema():
    _ensure_db_initialized()


