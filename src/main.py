from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from src.routes import router
from src.logger import setup_logger
import asyncio
import os
import time

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

# Global startup flag
_startup_completed = False

@app.middleware("http")
async def log_requests(request: Request, call_next):
    import uuid
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

async def _perform_startup_tasks():
    """
    Perform all startup tasks asynchronously in the background.
    This function runs as a background task after the HTTP server is ready.
    """
    global _startup_completed
    
    try:
        # ===== Step 1: Initialize database schema =====
        logger.info("[STARTUP] Initializing database schema...")
        try:
            from src.database import initialize_db_schema
            loop = asyncio.get_running_loop()
            
            await asyncio.wait_for(
                loop.run_in_executor(None, initialize_db_schema),
                timeout=15,
            )
            logger.info("[STARTUP] Database schema initialized.")
        except asyncio.TimeoutError:
            logger.error("[STARTUP] Database schema initialization timed out!")
            raise
        except Exception as db_init_err:
            logger.error(f"[STARTUP] Failed to initialize database schema: {db_init_err}")
            raise

        # ===== Step 2: Start database cleanup task =====
        lock_path = ".db_cleanup.lock"
        should_run = False
        
        try:
            # If the lock file is old (e.g. from a crashed previous run), remove it
            if os.path.exists(lock_path):
                try:
                    mtime = os.path.getmtime(lock_path)
                    if time.time() - mtime > 300:
                        os.remove(lock_path)
                except Exception:
                    pass
                    
            # Exclusive creation mode ('x') ensures only one process succeeds
            with open(lock_path, "x") as f:
                f.write(str(time.time()))
            should_run = True
        except FileExistsError:
            should_run = False
        except Exception as e:
            logger.warning(f"[STARTUP] Error acquiring cleanup lock: {e}. Defaulting to run.")
            should_run = True

        if should_run:
            try:
                from src.crud import cleanup_zero_vectors_in_db
                logger.info("[STARTUP] Starting database cleanup for zero vectors...")
                loop = asyncio.get_running_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, cleanup_zero_vectors_in_db),
                    timeout=10,
                )
                logger.info("[STARTUP] Cleanup completed.")
            except asyncio.TimeoutError:
                logger.warning("[STARTUP] Cleanup timed out; continuing...")
            except Exception as cleanup_err:
                logger.error(f"[STARTUP] Cleanup failed: {cleanup_err}")
            finally:
                try:
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
                except Exception:
                    pass
        else:
            logger.info("[STARTUP] Skipping database cleanup (another process is handling it).")
        
        _startup_completed = True
        logger.info("[STARTUP] All startup tasks completed successfully!")
        
    except Exception as e:
        logger.error(f"[STARTUP] Fatal error in startup tasks: {e}")
        _startup_completed = False


@app.on_event("startup")
async def startup_event():
    """
    Minimal startup event handler.
    Schedules the actual startup tasks to run in the background.
    Returns immediately so the HTTP server can fully initialize.
    """
    logger.info("[STARTUP] FastAPI startup event triggered. Scheduling background startup tasks...")
    asyncio.create_task(_perform_startup_tasks())


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

