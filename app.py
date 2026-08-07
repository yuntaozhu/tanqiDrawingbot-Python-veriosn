import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import uvicorn
from src.main import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    print(f"Starting server on port {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_config=None)


