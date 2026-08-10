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
    import asyncio
    import logging
    
    logger = logging.getLogger("uvicorn")
    
    async def run_startup_tasks_background():
        try:
            logger.info("[STARTUP] Starting background database initialization...")
            from src.database import initialize_db_schema
            loop = asyncio.get_running_loop()
            
            # 1. Run database schema initialization with 5s timeout
            await asyncio.wait_for(
                loop.run_in_executor(None, initialize_db_schema),
                timeout=5.0
            )
            logger.info("[STARTUP] Database schema initialized successfully.")
            
            # 2. Run zero-vector cleanup with 5s timeout
            logger.info("[STARTUP] Starting database zero-vector cleanup...")
            from src.crud import cleanup_zero_vectors_in_db
            await asyncio.wait_for(
                loop.run_in_executor(None, cleanup_zero_vectors_in_db),
                timeout=5.0
            )
            logger.info("[STARTUP] Database cleanup completed.")
            
        except asyncio.TimeoutError:
            logger.warning("[STARTUP] Background startup task timed out!")
        except Exception as task_err:
            logger.error(f"[STARTUP] Error during background startup tasks: {task_err}")

    # Create the non-blocking task on the running event loop
    asyncio.create_task(run_startup_tasks_background())
    logger.info("[STARTUP] Non-blocking background startup tasks initiated. Server is ready.")

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
