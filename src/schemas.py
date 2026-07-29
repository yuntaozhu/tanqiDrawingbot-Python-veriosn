from typing import Optional, List
from pydantic import BaseModel, Field

class GenerateRequest(BaseModel):
    prompt: str
    engine: str = "replicate"
    protagonist: Optional[str] = None
    anchorImageBase64: Optional[str] = None
    seed: Optional[int] = None
    aspect_ratio: str = "1:1"
    num_images: int = 1
    style: str = "default"
    apply_line_art: bool = True
    include_metadata: bool = False

class FeedbackRequest(BaseModel):
    generation_id: str
    rating: int  # e.g., 1 to 5
    liked: Optional[bool] = None
    comments: Optional[str] = None

class ChatRequest(BaseModel):
    text: str

class TTSRequest(BaseModel):
    text: str = Field(..., description="待朗读的中文文本", example="小朋友们大家好！")
    voice: Optional[str] = Field("default", description="音色选择")
    speed: Optional[float] = Field(1.0, description="语速，范围 0.5-2.0")


