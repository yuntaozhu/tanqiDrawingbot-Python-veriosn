import sys
import os
for path in ["/usr/local/lib/python3.10/dist-packages", "/usr/local/lib/python3/dist-packages"]:
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

import uvicorn
from src.main import app

if __name__ == "__main__":
    port = 3000
    print(f"Starting server on port {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_config="log_config.json")

