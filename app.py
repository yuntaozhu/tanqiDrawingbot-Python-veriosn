import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import uvicorn
from src.main import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    workers = int(os.getenv("CONCURRENCY_WORKERS", "1"))
    print(f"Starting server on port {port} with {workers} workers...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, workers=workers, log_config=None, timeout_keep_alive=30)


