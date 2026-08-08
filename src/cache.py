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


LLM_CACHE_FILE = "llm_chat_cache.json"

class LLMCacheManager:
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
                print("[INFO] [CACHE] LLMCache connected to Redis successfully.")
            except Exception as e:
                self.redis_client = None

        self.memory_cache: Dict[str, Any] = {}
        self._load_file_cache()

    def _load_file_cache(self):
        if os.path.exists(LLM_CACHE_FILE):
            try:
                with open(LLM_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.memory_cache = json.load(f)
                    print(f"[INFO] [CACHE] Loaded {len(self.memory_cache)} cached LLM replies from file.")
            except Exception as e:
                print(f"[ERROR] [CACHE] Failed loading {LLM_CACHE_FILE}: {e}")

    def _save_file_cache(self):
        try:
            with open(LLM_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] [CACHE] Failed saving {LLM_CACHE_FILE}: {e}")

    def normalize_text(self, text: str) -> str:
        if not text:
            return ""
        t = text.strip().lower()
        # Remove common punctuation and spaces
        t = re.sub(r'[^\w\s\u4e00-\u9fff]', '', t)
        return t.replace(" ", "")

    def get(self, text: str) -> Optional[Dict[str, Any]]:
        norm_key = self.normalize_text(text)
        if not norm_key:
            return None

        if self.redis_client:
            try:
                data = self.redis_client.get(f"llm:{norm_key}")
                if data:
                    print(f"[DEBUG] [CACHE] Redis hit for LLM: '{norm_key}'")
                    return json.loads(data)
            except Exception:
                pass

        if norm_key in self.memory_cache:
            print(f"[DEBUG] [CACHE] Memory hit for LLM: '{norm_key}'")
            return self.memory_cache[norm_key]

        return None

    def set(self, text: str, response_data: Dict[str, Any]):
        norm_key = self.normalize_text(text)
        if not norm_key or not response_data:
            return

        if self.redis_client:
            try:
                self.redis_client.set(f"llm:{norm_key}", json.dumps(response_data, ensure_ascii=False), ex=86400 * 3)
            except Exception:
                pass

        self.memory_cache[norm_key] = response_data
        self._save_file_cache()
        print(f"[INFO] [CACHE] Cached LLM reply for '{norm_key}'")


PROMPT_EXPAND_CACHE_FILE = "prompt_expand_cache.json"

class PromptExpandCacheManager:
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
                print("[INFO] [CACHE] PromptExpandCache connected to Redis successfully.")
            except Exception:
                self.redis_client = None

        self.memory_cache: Dict[str, str] = {}
        self._load_file_cache()

    def _load_file_cache(self):
        if os.path.exists(PROMPT_EXPAND_CACHE_FILE):
            try:
                with open(PROMPT_EXPAND_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.memory_cache = json.load(f)
                    print(f"[INFO] [CACHE] Loaded {len(self.memory_cache)} cached prompt expansions from file.")
            except Exception as e:
                print(f"[ERROR] [CACHE] Failed loading {PROMPT_EXPAND_CACHE_FILE}: {e}")

    def _save_file_cache(self):
        try:
            with open(PROMPT_EXPAND_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] [CACHE] Failed saving {PROMPT_EXPAND_CACHE_FILE}: {e}")

    def normalize_text(self, text: str) -> str:
        if not text:
            return ""
        t = text.strip().lower()
        t = re.sub(r'[^\w\s\u4e00-\u9fff]', '', t)
        return t.replace(" ", "")

    def get(self, text: str) -> Optional[str]:
        norm_key = self.normalize_text(text)
        if not norm_key:
            return None

        if self.redis_client:
            try:
                data = self.redis_client.get(f"prompt_expand:{norm_key}")
                if data:
                    val = data.decode('utf-8') if isinstance(data, bytes) else data
                    print(f"[DEBUG] [CACHE] Redis hit for Prompt Expand: '{norm_key}'")
                    return val
            except Exception:
                pass

        if norm_key in self.memory_cache:
            print(f"[DEBUG] [CACHE] Memory hit for Prompt Expand: '{norm_key}'")
            return self.memory_cache[norm_key]

        return None

    def set(self, text: str, expanded_text: str):
        norm_key = self.normalize_text(text)
        if not norm_key or not expanded_text:
            return

        if self.redis_client:
            try:
                self.redis_client.set(f"prompt_expand:{norm_key}", expanded_text, ex=86400 * 30)
            except Exception:
                pass

        self.memory_cache[norm_key] = expanded_text
        self._save_file_cache()
        print(f"[INFO] [CACHE] Cached prompt expansion for '{norm_key}'")


EMBEDDING_CACHE_FILE = "embedding_cache.json"

class EmbeddingCacheManager:
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
                print("[INFO] [CACHE] EmbeddingCache connected to Redis successfully.")
            except Exception:
                self.redis_client = None

        self.memory_cache: Dict[str, list] = {}
        self._load_file_cache()

    def _load_file_cache(self):
        if os.path.exists(EMBEDDING_CACHE_FILE):
            try:
                with open(EMBEDDING_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.memory_cache = json.load(f)
                    print(f"[INFO] [CACHE] Loaded {len(self.memory_cache)} cached embeddings from file.")
            except Exception as e:
                print(f"[ERROR] [CACHE] Failed loading {EMBEDDING_CACHE_FILE}: {e}")

    def _save_file_cache(self):
        try:
            with open(EMBEDDING_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory_cache, f, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] [CACHE] Failed saving {EMBEDDING_CACHE_FILE}: {e}")

    def normalize_text(self, text: str) -> str:
        if not text:
            return ""
        t = text.strip().lower()
        t = re.sub(r'[^\w\s\u4e00-\u9fff]', '', t)
        return t.replace(" ", "")

    def get(self, text: str) -> Optional[list]:
        norm_key = self.normalize_text(text)
        if not norm_key:
            return None

        if self.redis_client:
            try:
                data = self.redis_client.get(f"embedding:{norm_key}")
                if data:
                    print(f"[DEBUG] [CACHE] Redis hit for Embedding: '{norm_key[:10]}...'")
                    return json.loads(data)
            except Exception:
                pass

        if norm_key in self.memory_cache:
            print(f"[DEBUG] [CACHE] Memory hit for Embedding: '{norm_key[:10]}...'")
            return self.memory_cache[norm_key]

        return None

    def set(self, text: str, vector: list):
        norm_key = self.normalize_text(text)
        if not norm_key or not vector:
            return

        # Do not cache dummy zero vectors!
        if vector == [0.0] * 1024:
            return

        if self.redis_client:
            try:
                self.redis_client.set(f"embedding:{norm_key}", json.dumps(vector), ex=86400 * 30)
            except Exception:
                pass

        self.memory_cache[norm_key] = vector
        self._save_file_cache()
        print(f"[INFO] [CACHE] Cached Embedding vector for '{norm_key[:10]}...'")


PSYCH_PROFILE_CACHE_FILE = "psych_profile_cache.json"

class PsychProfileCacheManager:
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
                print("[INFO] [CACHE] PsychProfileCache connected to Redis successfully.")
            except Exception:
                self.redis_client = None

        self.memory_cache: Dict[str, list] = {}
        self._load_file_cache()

    def _load_file_cache(self):
        if os.path.exists(PSYCH_PROFILE_CACHE_FILE):
            try:
                with open(PSYCH_PROFILE_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.memory_cache = json.load(f)
                    print(f"[INFO] [CACHE] Loaded {len(self.memory_cache)} cached psych profiles from file.")
            except Exception as e:
                print(f"[ERROR] [CACHE] Failed loading {PSYCH_PROFILE_CACHE_FILE}: {e}")

    def _save_file_cache(self):
        try:
            with open(PSYCH_PROFILE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory_cache, f, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] [CACHE] Failed saving {PSYCH_PROFILE_CACHE_FILE}: {e}")

    def get_profiles(self, device_token: str) -> Optional[list]:
        if not device_token:
            return None

        if self.redis_client:
            try:
                data = self.redis_client.get(f"psych_profile:{device_token}")
                if data:
                    print(f"[DEBUG] [CACHE] Redis hit for Psych Profile: '{device_token[:5]}***'")
                    return json.loads(data)
            except Exception:
                pass

        if device_token in self.memory_cache:
            print(f"[DEBUG] [CACHE] Memory hit for Psych Profile: '{device_token[:5]}***'")
            return self.memory_cache[device_token]

        return None

    def set_profiles(self, device_token: str, profiles: list):
        if not device_token or profiles is None:
            return

        if self.redis_client:
            try:
                self.redis_client.set(f"psych_profile:{device_token}", json.dumps(profiles, ensure_ascii=False), ex=600)
            except Exception:
                pass

        self.memory_cache[device_token] = profiles
        self._save_file_cache()
        print(f"[INFO] [CACHE] Cached {len(profiles)} psych profiles for '{device_token[:5]}***'")

    def invalidate(self, device_token: str):
        if not device_token:
            return

        if self.redis_client:
            try:
                self.redis_client.delete(f"psych_profile:{device_token}")
            except Exception:
                pass

        if device_token in self.memory_cache:
            del self.memory_cache[device_token]
            self._save_file_cache()
            print(f"[INFO] [CACHE] Invalidated psych profile cache for '{device_token[:5]}***'")


