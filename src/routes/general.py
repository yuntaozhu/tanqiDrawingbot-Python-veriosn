import uuid
import time
from fastapi import APIRouter, HTTPException
from src.schemas import GenerateRequest, FeedbackRequest
from src.crud import save_history_to_db, save_feedback_to_db, get_history_from_db
from src.services import ReplicateAPI, generate_image_with_fallback
from src.utils import process_line_art_image, get_raw_bitmap_hex, get_embedded_bitmap, get_image_metadata

router = APIRouter()

@router.post("/api/generate")
async def generate_drawing(req: GenerateRequest):
    replicate_api = ReplicateAPI()
    
    # 1. Translate prompt
    try:
        english_prompt = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {req.prompt}")
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"Translation failed: {e}")
        english_prompt = req.prompt
        
    # 2. Extract protagonist if not provided
    protagonist = req.protagonist
    if not protagonist:
        sys_prompt = f"从以下描述中提取主角。要求：1. 必须是纯中文词汇。2. 必须是幼儿易懂的极简词汇（如：小兔子、红赛车、大恐龙）。3. 严禁包含任何英文字符或拼音。描述：{req.prompt}"
        try:
            protagonist = replicate_api.generate_text(sys_prompt)
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            print(f"Protagonist extraction failed: {e}")
            protagonist = None
        
    # 3. Summarize prompt
    title_prompt = f"请将绘画描述总结为一个幼儿标题。要求：1. 必须是2-5个字的极简中文词汇，适合3岁幼儿（如：漂亮小鱼、开心小熊）。2. 严禁出现任何英文单词、字母或拼音。3. 在标题开头或结尾增加一个匹配的表情符号(Emoji)。描述内容：{req.prompt}"
    try:
        title = replicate_api.generate_text(title_prompt) or "🎨 奇妙画作"
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print(f"Title generation failed: {e}")
        title = "🎨 奇妙画作"
    
    # Translate protagonist
    english_protagonist = protagonist
    if protagonist and any('\u4e00' <= char <= '\u9fa5' for char in protagonist):
        try:
            translated = replicate_api.generate_text(f"Translate the following text into English. Output ONLY the English translation, no other text. Text: {protagonist}")
            if translated:
                english_protagonist = translated
        except PermissionError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            print(f"Protagonist translation failed: {e}")

    # 4. Generate Image
    result = generate_image_with_fallback(
        english_prompt, 
        req.seed, 
        english_protagonist, 
        req.anchorImageBase64, 
        req.aspect_ratio, 
        req.num_images, 
        req.style, 
        preferred_engine=req.engine
    )
    image_urls = result["urls"]
    cached_metadata = result["metadata"]

    if not image_urls:
        raise HTTPException(status_code=500, detail="Image generation failed with all available engines.")
        
    # 5. Process Image
    processed_images = []
    raw_bitmaps = []
    embedded_bitmaps = []
    image_metadata = []
    
    for i, url in enumerate(image_urls):
        if req.include_metadata:
            if cached_metadata and i < len(cached_metadata) and cached_metadata[i]:
                image_metadata.append(cached_metadata[i])
            else:
                image_metadata.append(get_image_metadata(url))
        else:
            image_metadata.append(None)
            
        if req.apply_line_art:
            processed_images.append(process_line_art_image(url, apply_filter=True))
            eb = get_embedded_bitmap(url)
            embedded_bitmaps.append(eb)
            raw_bitmaps.append(eb["data_hex"] if eb else None)
        else:
            processed_images.append(url)
            raw_bitmaps.append(None)
            embedded_bitmaps.append(None)
    
    generation_id = str(uuid.uuid4())
    
    # Save to history
    history_entry = {
        "generation_id": generation_id,
        "prompt": req.prompt,
        "english_prompt": english_prompt,
        "engine": req.engine,
        "protagonist": protagonist,
        "title": title,
        "aspect_ratio": req.aspect_ratio,
        "num_images": req.num_images,
        "style": req.style,
        "apply_line_art": req.apply_line_art,
        "image_urls": processed_images,
        "raw_bitmaps": raw_bitmaps if req.apply_line_art else None,
        "bitmap_data": embedded_bitmaps if req.apply_line_art else None,
        "metadata": image_metadata if req.include_metadata else None,
        "timestamp": time.time()
    }
    save_history_to_db(history_entry)
    
    return {
        "generationId": generation_id,
        "imageUrl": processed_images[0] if processed_images else None,
        "imageUrls": processed_images,
        "bitmaps": raw_bitmaps if req.apply_line_art else None,
        "bitmapData": embedded_bitmaps if req.apply_line_art else None,
        "metadata": image_metadata if req.include_metadata else None,
        "protagonist": protagonist,
        "title": title,
        "prompt": req.prompt
    }

@router.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest):
    feedback_entry = {
        "generation_id": req.generation_id,
        "rating": req.rating,
        "liked": req.liked,
        "comments": req.comments,
        "timestamp": time.time()
    }
    save_feedback_to_db(feedback_entry)
    return {"success": True, "message": "Feedback received"}

@router.get("/api/history")
async def get_history(limit: int = 50):
    return get_history_from_db(limit)
