import os
import uvicorn
from src.main import app

if __name__ == "__main__":
    port = 3000
    print(f"Starting server on port {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_config="log_config.json")
