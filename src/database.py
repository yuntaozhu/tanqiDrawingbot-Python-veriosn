from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DatabaseError
from sqlalchemy.pool import NullPool
import os
from src.config import DATABASE_URL

# Check if using PostgreSQL (Railway) or SQLite
is_postgresql = DATABASE_URL and "postgresql" in DATABASE_URL.lower()

if is_postgresql:
    # Use NullPool for PostgreSQL on Railway (Railway manages connections)
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args={"connect_timeout": 10},
        echo=False
    )
    print("[DB] Using PostgreSQL via Railway")
else:
    # Use SQLite for local development
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False
    )
    print("[DB] Using SQLite for local development")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Import all models
from src.models import (
    GenerationHistoryDB, FeedbackDB, PrintJobDB, PsychVectorDB, DeviceSettingsDB
)

def init_db():
    """Initialize database - create all tables"""
    try:
        Base.metadata.create_all(bind=engine)
        print("[DB] ✅ Database initialization successful")
        return True
    except Exception as e:
        print(f"[DB] ❌ Database initialization error: {e}")
        engine.dispose()
        
        # Retry for SQLite
        if not is_postgresql and DATABASE_URL.startswith("sqlite:///"):
            db_path = DATABASE_URL.replace("sqlite:///", "")
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                    print(f"[DB] Removed corrupted SQLite file: {db_path}")
                    Base.metadata.create_all(bind=engine)
                    print("[DB] Database recreated successfully")
                    return True
                except Exception as rm_err:
                    print(f"[DB] Failed to recover: {rm_err}")
                    return False
        return False

def test_db_connection():
    """Test database connection"""
    try:
        with engine.connect() as connection:
            result = connection.execute("SELECT 1")
            print("[DB] ✅ Database connection successful")
            return True
    except Exception as e:
        print(f"[DB] ❌ Database connection failed: {e}")
        return False

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Initialize database on import
try:
    init_db()
except Exception as e:
    print(f"[DB] Warning: Could not initialize database on startup: {e}")

