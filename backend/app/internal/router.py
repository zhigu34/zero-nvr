from fastapi import APIRouter

from .zlm_hooks import router as zlm_hooks_router


router = APIRouter(prefix="/internal")
router.include_router(
    zlm_hooks_router,
    prefix="/hooks/zlm",
    tags=["internal-zlm"],
)
