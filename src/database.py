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

def _migrate_print_jobs_columns():
    """Add device_token/status to print_jobs if missing (Postgres/SQLite).

    Each ALTER runs in its own transaction so a 'column already exists' error
    on Postgres does not abort the whole batch (InFailedSqlTransaction).
    """
    from sqlalchemy import text, inspect

    def _has_column(table: str, column: str) -> bool:
        try:
            cols = {c["name"] for c in inspect(engine).get_columns(table)}
            return column in cols
        except Exception:
            return False

    migrations = [
        ("device_token", "ALTER TABLE print_jobs ADD COLUMN device_token VARCHAR"),
        ("status", "ALTER TABLE print_jobs ADD COLUMN status VARCHAR DEFAULT 'ready'"),
    ]
    for col, stmt in migrations:
        if _has_column("print_jobs", col):
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            print(f"[INFO] [DB] Migration applied: {stmt}")
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "already exists" in msg or "exists" in msg:
                pass
            else:
                print(f"[DEBUG] [DB] Migration skip/fail ({stmt}): {e}")

    if _has_column("print_jobs", "status"):
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE print_jobs SET status = 'ready' "
                        "WHERE status IS NULL OR status = '' OR status = 'pending'"
                    )
                )
        except Exception as e:
            print(f"[DEBUG] [DB] status backfill skip: {e}")

def _ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        try:
            Base.metadata.create_all(bind=engine)
            _migrate_print_jobs_columns()
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
            _migrate_print_jobs_columns()
            print("[INFO] Database recreated successfully.")
        try:
            from src.crud import clear_legacy_auto_print_queue
            clear_legacy_auto_print_queue()
        except Exception as e:
            print(f"[DEBUG] [DB] clear_legacy_auto_print_queue skip: {e}")
        _db_initialized = True

def initialize_db_schema():
    _ensure_db_initialized()


