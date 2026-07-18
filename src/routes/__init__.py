from fastapi import APIRouter
from src.routes.device import router as device_router
from src.routes.admin import router as admin_router
from src.routes.general import router as general_router

router = APIRouter()

# Include all sub-routers to create a single aggregated APIRouter package
router.include_router(device_router)
router.include_router(admin_router)
router.include_router(general_router)
