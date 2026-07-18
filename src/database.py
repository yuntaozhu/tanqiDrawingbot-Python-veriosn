from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from src.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# To support backward compatibility for any existing imports from src.database
# we import all models here.
from src.models import (
    GenerationHistoryDB, FeedbackDB, PrintJobDB, PsychVectorDB, DeviceSettingsDB
)

Base.metadata.create_all(bind=engine)
