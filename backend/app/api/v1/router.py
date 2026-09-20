from fastapi import APIRouter

from app.modules.system.api import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(system_router, prefix="/system", tags=["system"])
