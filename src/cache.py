import json
import os
import re
from typing import Optional, Dict, Any

try:
    import redis
except ImportError:
    redis = None

CACHE_FILE = "asset_drawing_cache.json"

class DrawingCacheManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.redis_client = None
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        if redis:
            try:
                r = redis.Redis.from_url(redis_url, socket_timeout=1)
                r.ping()
                self.redis_client = r
                print("[INFO] [CACHE] Connected to Redis successfully.")
            except Exception as e:
                print(f"[INFO] [CACHE] Redis unavailable ({e}), using in-memory dict + file cache.")
                self.redis_client = None

        self.memory_cache: Dict[str, Any] = {}
        self._load_file_cache()

    def _load_file_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self.memory_cache = json.load(f)
                    print(f"[INFO] [CACHE] Loaded {len(self.memory_cache)} cached drawing assets from file.")
            except Exception as e:
                print(f"[ERROR] [CACHE] Failed loading {CACHE_FILE}: {e}")

    def _save_file_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] [CACHE] Failed saving {CACHE_FILE}: {e}")

    def normalize_prompt(self, prompt: str) -> str:
        if not prompt:
            return ""
        p = prompt.strip()
        p = re.sub(r'^(请|帮我|想要|可以|给我|你能|画一个|画一只|画一架|画辆|画朵|画条|画张|画一幅|画个|画一画|画)', '', p)
        p = re.sub(r'(的简笔画|的线稿|图|图片|画|吧|吗|呀|哦|啦)$', '', p)
        return p.strip() or prompt.strip()

    def get(self, prompt: str) -> Optional[Dict[str, Any]]:
        norm_key = self.normalize_prompt(prompt)
        if not norm_key:
            return None

        # 1. Redis lookup
        if self.redis_client:
            try:
                data = self.redis_client.get(f"drawing:{norm_key}")
                if data:
                    print(f"[DEBUG] [CACHE] Redis hit for drawing: '{norm_key}'")
                    return json.loads(data)
            except Exception as e:
                print(f"[WARNING] [CACHE] Redis get error: {e}")

        # 2. Memory cache exact match
        if norm_key in self.memory_cache:
            print(f"[DEBUG] [CACHE] Memory exact hit for drawing: '{norm_key}'")
            return self.memory_cache[norm_key]

        # 3. Memory cache partial match
        for k, val in self.memory_cache.items():
            if k in norm_key or norm_key in k:
                print(f"[DEBUG] [CACHE] Memory partial hit for drawing: '{norm_key}' -> '{k}'")
                return val

        return None

    def set(self, prompt: str, data: Dict[str, Any]):
        norm_key = self.normalize_prompt(prompt)
        if not norm_key or not data:
            return

        if self.redis_client:
            try:
                self.redis_client.set(f"drawing:{norm_key}", json.dumps(data, ensure_ascii=False))
            except Exception as e:
                print(f"[WARNING] [CACHE] Redis set error: {e}")

        self.memory_cache[norm_key] = data
        self._save_file_cache()
        print(f"[INFO] [CACHE] Cached drawing asset for '{norm_key}'")
