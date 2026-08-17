import json
import time
from typing import List, Dict, Any, Optional
from sqlalchemy import func
from src.database import SessionLocal
from src.models import (
    GenerationHistoryDB, FeedbackDB, PrintJobDB, PsychVectorDB, DeviceSettingsDB
)

_scroll_seq_cursor = {}

def save_history_to_db(entry: Dict[str, Any]):
    db = SessionLocal()
    try:
        db_entry = GenerationHistoryDB(
            generation_id=entry["generation_id"],
            prompt=entry["prompt"],
            english_prompt=entry.get("english_prompt"),
            engine=entry.get("engine"),
            protagonist=entry.get("protagonist"),
            title=entry.get("title"),
            aspect_ratio=entry.get("aspect_ratio"),
            num_images=entry.get("num_images", 1),
            style=entry.get("style", "default"),
            apply_line_art=1 if entry.get("apply_line_art", True) else 0,
            image_urls=json.dumps(entry.get("image_urls")),
            raw_bitmaps=json.dumps(entry.get("raw_bitmaps")),
            bitmap_data=json.dumps(entry.get("bitmap_data")),
            metadata_json=json.dumps(entry.get("metadata")),
            timestamp=entry["timestamp"]
        )
        db.add(db_entry)
        db.commit()
    except Exception as e:
        print(f"Error saving history to DB: {e}")
        db.rollback()
    finally:
        db.close()

def get_history_from_db(limit: int = 50) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        entries = db.query(GenerationHistoryDB).order_by(GenerationHistoryDB.timestamp.desc()).limit(limit).all()
        return [
            {
                "generation_id": e.generation_id,
                "prompt": e.prompt,
                "english_prompt": e.english_prompt,
                "engine": e.engine,
                "protagonist": e.protagonist,
                "title": e.title,
                "aspect_ratio": e.aspect_ratio,
                "num_images": e.num_images,
                "style": e.style,
                "apply_line_art": bool(e.apply_line_art),
                "image_urls": json.loads(e.image_urls) if e.image_urls else [],
                "raw_bitmaps": json.loads(e.raw_bitmaps) if e.raw_bitmaps else [],
                "bitmap_data": json.loads(e.bitmap_data) if e.bitmap_data else None,
                "metadata": json.loads(e.metadata_json) if e.metadata_json else None,
                "timestamp": e.timestamp
            }
            for e in entries
        ]
    except Exception as e:
        print(f"Error getting history from DB: {e}")
        return []
    finally:
        db.close()

def save_feedback_to_db(entry: Dict[str, Any]):
    db = SessionLocal()
    try:
        db_entry = FeedbackDB(
            generation_id=entry["generation_id"],
            rating=entry["rating"],
            liked=1 if entry.get("liked") else 0 if entry.get("liked") is False else None,
            comments=entry.get("comments"),
            timestamp=entry["timestamp"]
        )
        db.add(db_entry)
        db.commit()
    except Exception as e:
        print(f"Error saving feedback to DB: {e}")
        db.rollback()
    finally:
        db.close()

def save_print_job_to_db(job: Dict[str, Any]):
    """
    Save a generated drawing. Default status is 'ready' (screen preview only).
    Status 'queued' means the user tapped Print and the device may consume it.
    """
    db = SessionLocal()
    try:
        db_job = PrintJobDB(
            job_id=job["job_id"],
            device_token=job.get("device_token"),
            status=job.get("status") or "ready",
            image_url=job["image_url"],
            bitmap_hex=job.get("bitmap_hex"),
            prompt=job["prompt"],
            timestamp=job["timestamp"],
            scroll_id=job.get("scroll_id"),
            seed=job.get("seed"),
            seq=job.get("seq"),
        )
        db.add(db_job)
        db.commit()
        print(f"[DEBUG] [DB] Saved drawing job {job['job_id']} status={job.get('status') or 'ready'} token={job.get('device_token')}")
    except Exception as e:
        print(f"Error saving print job to DB: {e}")
        db.rollback()
    finally:
        db.close()

def _job_to_dict(j: PrintJobDB) -> Dict[str, Any]:
    return {
        "job_id": j.job_id,
        "device_token": getattr(j, "device_token", None),
        "status": getattr(j, "status", None) or "ready",
        "image_url": j.image_url,
        "bitmap_hex": j.bitmap_hex,
        "prompt": j.prompt,
        "timestamp": j.timestamp,
        "scroll_id": getattr(j, "scroll_id", None),
        "seed": getattr(j, "seed", None),
        "seq": getattr(j, "seq", None),
    }


def allocate_scroll_seq(scroll_id: str) -> int:
    """Monotonic seq for images on one scroll, including in-flight jobs not yet saved."""
    db = SessionLocal()
    db_next = 0
    try:
        max_seq = db.query(func.max(PrintJobDB.seq)).filter(PrintJobDB.scroll_id == scroll_id).scalar()
        db_next = (max_seq if max_seq is not None else -1) + 1
    except Exception as e:
        print(f"[DEBUG] [DB] allocate_scroll_seq fallback: {e}")
        db_next = 0
    finally:
        db.close()
    mem = _scroll_seq_cursor.get(scroll_id, db_next)
    seq = max(db_next, mem)
    _scroll_seq_cursor[scroll_id] = seq + 1
    return seq


def reset_scroll_seq_cursor(scroll_id: str):
    _scroll_seq_cursor[scroll_id] = 0


def get_jobs_for_scroll(scroll_id: str, device_token: str = None, status: str = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(PrintJobDB).filter(PrintJobDB.scroll_id == scroll_id)
        if device_token:
            q = q.filter(PrintJobDB.device_token == device_token)
        if status:
            q = q.filter(PrintJobDB.status == status)
        jobs = q.order_by(PrintJobDB.timestamp.asc()).all()
        jobs.sort(key=lambda j: (
            j.seq if getattr(j, "seq", None) is not None else 10 ** 9,
            j.timestamp or 0,
        ))
        return [_job_to_dict(j) for j in jobs]
    except Exception as e:
        print(f"Error getting scroll jobs: {e}")
        return []
    finally:
        db.close()


def queue_scroll_jobs(scroll_id: str, device_token: str) -> List[Dict[str, Any]]:
    """Mark every ready drawing on this scroll as queued, in seq order."""
    ready = get_jobs_for_scroll(scroll_id, device_token=device_token, status="ready")
    queued = []
    for job in ready:
        result = queue_print_job(job["job_id"], device_token=device_token)
        if result:
            queued.append(result)
    return queued

def get_print_jobs_from_db(device_token: str = None, status: str = "queued") -> List[Dict[str, Any]]:
    """
    By default only returns jobs the user confirmed for printing (status=queued).
    Ready (preview) jobs are NOT returned here — use get_ready_drawings_from_db.
    """
    db = SessionLocal()
    try:
        q = db.query(PrintJobDB)
        if status:
            q = q.filter(PrintJobDB.status == status)
        if device_token:
            q = q.filter(PrintJobDB.device_token == device_token)
        jobs = q.order_by(PrintJobDB.timestamp.asc()).all()
        return [_job_to_dict(j) for j in jobs]
    except Exception as e:
        print(f"Error getting print jobs from DB: {e}")
        return []
    finally:
        db.close()

def get_ready_drawings_from_db(device_token: str = None) -> List[Dict[str, Any]]:
    """Return generated drawings waiting for user to tap Print (status=ready)."""
    return get_print_jobs_from_db(device_token=device_token, status="ready")

def get_print_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        j = db.query(PrintJobDB).filter(PrintJobDB.job_id == job_id).first()
        return _job_to_dict(j) if j else None
    except Exception as e:
        print(f"Error getting print job {job_id}: {e}")
        return None
    finally:
        db.close()

def queue_print_job(job_id: str, device_token: str = None) -> Optional[Dict[str, Any]]:
    """User tapped Print: mark ready → queued and return job payload for the device."""
    db = SessionLocal()
    try:
        j = db.query(PrintJobDB).filter(PrintJobDB.job_id == job_id).first()
        if not j:
            return None
        if device_token and getattr(j, "device_token", None) and j.device_token != device_token:
            print(f"[WARNING] [DB] queue_print_job token mismatch for {job_id}")
            return None
        j.status = "queued"
        if device_token and not getattr(j, "device_token", None):
            j.device_token = device_token
        db.commit()
        db.refresh(j)
        print(f"[DEBUG] [DB] Job {job_id} queued for printing")
        return _job_to_dict(j)
    except Exception as e:
        print(f"Error queueing print job {job_id}: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def delete_print_job_from_db(job_id: str):
    db = SessionLocal()
    try:
        db.query(PrintJobDB).filter(PrintJobDB.job_id == job_id).delete()
        db.commit()
    except Exception as e:
        print(f"Error deleting print job from DB: {e}")
        db.rollback()
    finally:
        db.close()

def clear_legacy_auto_print_queue():
    """Mark all existing jobs as ready so old auto-poll clients stop draining them as print jobs."""
    db = SessionLocal()
    try:
        updated = 0
        for j in db.query(PrintJobDB).all():
            status = getattr(j, "status", None)
            if status in (None, "", "queued", "pending"):
                j.status = "ready"
                updated += 1
        if updated:
            db.commit()
            print(f"[INFO] [DB] Reset {updated} print_jobs to status=ready (manual print only)")
    except Exception as e:
        print(f"[WARNING] [DB] clear_legacy_auto_print_queue failed: {e}")
        db.rollback()
    finally:
        db.close()

def save_psych_vector(device_token: str, child_text: str, ai_response: str, embedding: List[float], metadata: Dict[str, Any]):
    db = SessionLocal()
    try:
        import uuid
        db_entry = PsychVectorDB(
            id=str(uuid.uuid4()),
            device_token=device_token,
            child_text=child_text,
            ai_response=ai_response,
            embedding_json=json.dumps(embedding),
            metadata_json=json.dumps(metadata),
            timestamp=time.time()
        )
        db.add(db_entry)
        db.commit()
        print(f"[DEBUG] [DB] Successfully saved psych vector for token: {device_token}")
        
        # Invalidate cached psych profiles for this token to guarantee freshness
        from src.cache import PsychProfileCacheManager
        PsychProfileCacheManager.get_instance().invalidate(device_token)
    except Exception as e:
        print(f"[ERROR] [DB] Failed to save psych vector: {e}")
        db.rollback()
    finally:
        db.close()

def query_psych_vectors(device_token: str) -> List[Dict[str, Any]]:
    from src.cache import PsychProfileCacheManager
    cache_mgr = PsychProfileCacheManager.get_instance()
    cached = cache_mgr.get_profiles(device_token)
    if cached is not None:
        return cached

    db = SessionLocal()
    try:
        entries = db.query(PsychVectorDB).filter(PsychVectorDB.device_token == device_token).order_by(PsychVectorDB.timestamp.desc()).all()
        results = [
            {
                "id": e.id,
                "device_token": e.device_token,
                "child_text": e.child_text,
                "ai_response": e.ai_response,
                "embedding": json.loads(e.embedding_json) if e.embedding_json else [],
                "metadata": json.loads(e.metadata_json) if e.metadata_json else {},
                "timestamp": e.timestamp
            }
            for e in entries
        ]
        # Cache retrieved results
        cache_mgr.set_profiles(device_token, results)
        return results
    except Exception as e:
        print(f"[ERROR] [DB] Failed to query psych vectors: {e}")
        return []
    finally:
        db.close()

def save_device_settings(device_token: str, voice_name: str):
    db = SessionLocal()
    try:
        db_settings = db.query(DeviceSettingsDB).filter(DeviceSettingsDB.device_token == device_token).first()
        if db_settings:
            db_settings.voice_name = voice_name
            db_settings.timestamp = time.time()
        else:
            db_settings = DeviceSettingsDB(
                device_token=device_token,
                voice_name=voice_name,
                timestamp=time.time()
            )
            db.add(db_settings)
        db.commit()
        print(f"[DEBUG] [DB] Saved settings for {device_token}: {voice_name}")
    except Exception as e:
        print(f"[ERROR] [DB] Failed to save device settings: {e}")
        db.rollback()
    finally:
        db.close()

def get_device_settings(device_token: str) -> str:
    db = SessionLocal()
    try:
        # We default to anna as the highly-polished child storyteller voice
        if not device_token:
            return "FunAudioLLM/CosyVoice2-0.5B:anna"
        settings = db.query(DeviceSettingsDB).filter(DeviceSettingsDB.device_token == device_token).first()
        if settings and settings.voice_name:
            return settings.voice_name
        return "FunAudioLLM/CosyVoice2-0.5B:anna"
    except Exception as e:
        print(f"[ERROR] [DB] Failed to get device settings: {e}")
        return "FunAudioLLM/CosyVoice2-0.5B:anna"
    finally:
        db.close()

def cleanup_zero_vectors_in_db(batch_size: int = 1000):
    import time
    db = SessionLocal()
    start_time = time.time()
    total_updated = 0
    total_scanned = 0
    
    try:
        total_rows = db.query(PsychVectorDB).count()
        print(f"[INFO] Starting cleanup for {total_rows} rows...")
        
        offset = 0
        while True:
            entries = (
                db.query(PsychVectorDB)
                .order_by(PsychVectorDB.id)
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            
            if not entries:
                break
                
            batch_updated = 0
            for e in entries:
                try:
                    embedding = json.loads(e.embedding_json) if e.embedding_json else []
                    # Check if it is a dummy vector (all elements are zero or empty)
                    is_zero = len(embedding) == 0 or all(x == 0.0 for x in embedding)
                    
                    metadata = json.loads(e.metadata_json) if e.metadata_json else {}
                    changed = False
                    
                    if is_zero:
                        if metadata.get("embedding_valid") is not False:
                            metadata["embedding_valid"] = False
                            metadata["embedding_available"] = False
                            changed = True
                    else:
                        if metadata.get("embedding_valid") is not True:
                            metadata["embedding_valid"] = True
                            metadata["embedding_available"] = True
                            changed = True
                    
                    if changed:
                        e.metadata_json = json.dumps(metadata)
                        batch_updated += 1
                except Exception as entry_err:
                    print(f"[WARNING] Failed to process entry during cleanup: {entry_err}")
                    
            try:
                if batch_updated > 0:
                    db.commit()
                else:
                    db.rollback()
            except Exception as commit_err:
                print(f"[ERROR] Commit failed at offset {offset}: {commit_err}")
                db.rollback()
                
            total_updated += batch_updated
            total_scanned += len(entries)
            print(f"[INFO] Batch offset={offset} size={len(entries)} updated={batch_updated} "
                  f"(scanned {total_scanned}/{total_rows} so far)")
                  
            offset += batch_size
            
        duration = time.time() - start_time
        print(f"[INFO] Finished: scanned {total_scanned} rows, updated {total_updated} in {duration:.2f}s")
        
    except Exception as e:
        print(f"[ERROR] [DB_CLEANUP] Failed to cleanup zero vectors: {e}")
        try:
            db.rollback()
        except:
            pass
    finally:
        db.close()

