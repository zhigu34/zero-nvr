from fastapi import APIRouter

from app.modules.auth.admin_api import router as auth_admin_router
from app.modules.auth.api import router as auth_router
from app.modules.cameras.api import router as cameras_router
from app.modules.events.api import router as events_router
from app.modules.recordings.api import router as recordings_router
from app.modules.system.api import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router, tags=["auth"])
router.include_router(auth_admin_router, tags=["users"])
router.include_router(cameras_router, tags=["cameras"])
router.include_router(events_router, tags=["events"])
router.include_router(recordings_router, tags=["recordings"])
router.include_router(system_router, prefix="/system", tags=["system"])
