from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from src.routes import router

app = FastAPI(title="Toddler Drawing Dreamer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
