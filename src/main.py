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
    try:
        from src.crud import cleanup_zero_vectors_in_db
        print("[INFO] [STARTUP] Starting database cleanup for zero vectors...")
        cleanup_zero_vectors_in_db()
    except Exception as start_err:
        print(f"[ERROR] [STARTUP] Failed during zero-vector cleanup startup phase: {start_err}")

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
