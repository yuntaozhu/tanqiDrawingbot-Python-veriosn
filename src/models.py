from sqlalchemy import Column, Integer, String, Float, Text
from src.database import Base

class GenerationHistoryDB(Base):
    __tablename__ = "generation_history"
    id = Column(Integer, primary_key=True, index=True)
    generation_id = Column(String, unique=True, index=True)
    prompt = Column(Text)
    english_prompt = Column(Text, nullable=True)
    engine = Column(String, nullable=True)
    protagonist = Column(String, nullable=True)
    title = Column(String, nullable=True)
    aspect_ratio = Column(String, nullable=True)
    num_images = Column(Integer, default=1)
    style = Column(String, default="default")
    apply_line_art = Column(Integer, default=1)
    image_urls = Column(Text, nullable=True) # Stored as JSON string
    raw_bitmaps = Column(Text, nullable=True) # Stored as JSON string
    bitmap_data = Column(Text, nullable=True) # Stored as JSON string
    metadata_json = Column(Text, nullable=True) # Stored as JSON string
    timestamp = Column(Float)

class FeedbackDB(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, index=True)
    generation_id = Column(String, index=True)
    rating = Column(Integer)
    liked = Column(Integer, nullable=True)
    comments = Column(Text, nullable=True)
    timestamp = Column(Float)

class PrintJobDB(Base):
    __tablename__ = "print_jobs"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True)
    device_token = Column(String, index=True, nullable=True)
    # ready = generated for screen preview; queued = user tapped Print; printed = done
    status = Column(String, default="ready", index=True)
    image_url = Column(Text)
    bitmap_hex = Column(Text, nullable=True)
    prompt = Column(Text)
    timestamp = Column(Float)
    scroll_id = Column(String, index=True, nullable=True)
    seed = Column(Integer, nullable=True)
    seq = Column(Integer, nullable=True)

class PsychVectorDB(Base):
    __tablename__ = "psych_vectors"
    id = Column(String, primary_key=True, index=True)
    device_token = Column(String, index=True)
    child_text = Column(Text)
    ai_response = Column(Text)
    embedding_json = Column(Text) # JSON serialized float list
    metadata_json = Column(Text) # JSON serialized dict
    timestamp = Column(Float)

class DeviceSettingsDB(Base):
    __tablename__ = "device_settings"
    device_token = Column(String, primary_key=True, index=True)
    voice_name = Column(String, default="FunAudioLLM/CosyVoice2-0.5B:anna")
    timestamp = Column(Float)
