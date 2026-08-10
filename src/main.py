from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from src.routes import router
from src.logger import setup_logger

logger = setup_logger("main")

app = FastAPI(
    title="Toddler Drawing Dreamer API",
    description="API for managing toddler drawing and interaction experiences.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    servers=[
        {"url": "https://tanqibot.up.railway.app", "description": "Production Server"}
    ]
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    import uuid
    import time
    from src.logger import set_trace_id

    # Extract existing Trace-ID or generate a new one
    trace_id = request.headers.get("X-Request-ID") or request.headers.get("X-Trace-ID") or uuid.uuid4().hex[:8]
    set_trace_id(trace_id)

    path = request.url.path
    is_polling = path in ["/api/device/v1/print-jobs", "/health", "/favicon.ico"]

    if not is_polling:
        logger.info(f"Incoming Request: {request.method} {path}")
        logger.debug(f"Request Headers for {path}: {dict(request.headers)}")

    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    if not is_polling:
        logger.info(f"Request completed: {request.method} {path} - Status: {response.status_code} - Duration: {duration:.3f}s")

    response.headers["X-Trace-ID"] = trace_id
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    import os
    import asyncio
    
    # Run all startup tasks in a non-blocking background task.
    # This prevents blocking Uvicorn's startup sequence and ensures
    # the server binds to port 3000 and starts accepting requests immediately.
    async def run_startup_tasks_background():
        import os
        import time
        import logging
        
        logger = logging.getLogger("uvicorn")
        lock_path = ".startup.lock"
        my_pid = os.getpid()
        
        # 1. Acquire process-safe lock with active PID checking
        acquired_lock = False
        try:
            if os.path.exists(lock_path):
                try:
                    with open(lock_path, "r") as f:
                        content = f.read().strip()
                    if content:
                        existing_pid = int(content)
                        # Check if the process holding the lock is still alive
                        try:
                            os.kill(existing_pid, 0)
                            is_alive = True
                        except OSError:
                            is_alive = False
                        
                        if is_alive:
                            logger.info(f"[STARTUP] [PID {my_pid}] Startup tasks already being handled by active worker PID {existing_pid}. Skipping.")
                            return
                        else:
                            logger.warning(f"[STARTUP] [PID {my_pid}] Found stale startup lock from dead PID {existing_pid}. Removing stale lock.")
                            try:
                                os.remove(lock_path)
                            except Exception:
                                pass
                except Exception as check_err:
                    logger.warning(f"[STARTUP] [PID {my_pid}] Error checking existing lock file: {check_err}")
            
            # Atomic creation of the lock file
            with open(lock_path, "x") as f:
                f.write(str(my_pid))
            acquired_lock = True
        except FileExistsError:
            logger.info(f"[STARTUP] [PID {my_pid}] Another worker process acquired the lock. Skipping.")
            return
        except Exception as e:
            logger.error(f"[STARTUP] [PID {my_pid}] Error acquiring startup lock: {e}. Defaulting to run to ensure startup happens.")
            acquired_lock = True # Fallback to run if there is some weird filesystem error
            
        if acquired_lock:
            logger.info(f"[STARTUP] [PID {my_pid}] Acquired exclusive startup lock. Running tasks...")
            try:
                # 2. Initialize database schema (MUST SUCCEED)
                logger.info(f"[STARTUP] [PID {my_pid}] Initializing database schema...")
                from src.database import initialize_db_schema
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, initialize_db_schema)
                logger.info(f"[STARTUP] [PID {my_pid}] Database schema initialized successfully.")
                
                # 3. Start cleanup task
                from src.crud import cleanup_zero_vectors_in_db
                logger.info(f"[STARTUP] [PID {my_pid}] Starting database cleanup for zero vectors...")
                await loop.run_in_executor(None, cleanup_zero_vectors_in_db)
                logger.info(f"[STARTUP] [PID {my_pid}] Database cleanup completed.")
                
            except Exception as task_err:
                logger.error(f"[STARTUP] [PID {my_pid}] Failed during background startup tasks: {task_err}")
            finally:
                # Release the lock file so future startups can acquire it
                try:
                    if os.path.exists(lock_path):
                        # Ensure we only delete our own lock file
                        with open(lock_path, "r") as f:
                            lock_pid = f.read().strip()
                        if lock_pid == str(my_pid):
                            os.remove(lock_path)
                            logger.info(f"[STARTUP] [PID {my_pid}] Released startup lock.")
                except Exception as release_err:
                    logger.warning(f"[STARTUP] [PID {my_pid}] Failed to release startup lock: {release_err}")

    # Create the non-blocking task on the running event loop
    asyncio.create_task(run_startup_tasks_background())
    logger.info("[STARTUP] Non-blocking background startup tasks initiated. Server is ready to accept requests.")

@app.get("/")
async def root():
    return {"status": "ok", "message": "Toddler Drawing Dreamer API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

# Include the routers
app.include_router(router)
