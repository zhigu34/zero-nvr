from fastapi import APIRouter

from app.modules.alerts.api import router as alerts_router
from app.modules.audit.api import router as audit_router
from app.modules.auth.admin_api import router as auth_admin_router
from app.modules.auth.api import router as auth_router
from app.modules.backups.api import router as backups_router
from app.modules.cameras.api import router as cameras_router
from app.modules.events.api import router as events_router
from app.modules.exports.api import router as exports_router
from app.modules.notifications.api import router as notifications_router
from app.modules.recordings.api import router as recordings_router
from app.modules.storage.api import router as storage_router
from app.modules.system.api import router as system_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router, tags=["auth"])
router.include_router(audit_router, prefix="/audit", tags=["audit"])
router.include_router(backups_router, prefix="/backups", tags=["backups"])
router.include_router(alerts_router, tags=["alerts"])
router.include_router(auth_admin_router, tags=["users"])
router.include_router(cameras_router, tags=["cameras"])
router.include_router(events_router, tags=["events"])
router.include_router(exports_router, tags=["exports"])
router.include_router(notifications_router, tags=["notifications"])
router.include_router(recordings_router, tags=["recordings"])
router.include_router(storage_router, prefix="/storage", tags=["storage"])
router.include_router(system_router, prefix="/system", tags=["system"])
