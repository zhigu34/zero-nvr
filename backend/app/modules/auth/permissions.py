from __future__ import annotations

ALL_PERMISSIONS = frozenset(
    {
        "camera.view",
        "camera.control",
        "camera.configure",
        "recording.view",
        "recording.export",
        "recording.protect",
        "recording.delete",
        "event.view",
        "alert.acknowledge",
        "alert.manage",
        "storage.manage",
        "system.view",
        "system.manage",
        "user.manage",
        "integration.manage",
        "audit.view",
    }
)

BUILTIN_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "Administrator": ALL_PERMISSIONS,
    "Operator": frozenset(
        {
            "camera.view",
            "camera.control",
            "recording.view",
            "recording.export",
            "recording.protect",
            "event.view",
            "alert.acknowledge",
            "system.view",
        }
    ),
    "Viewer": frozenset(
        {
            "camera.view",
            "recording.view",
            "event.view",
            "system.view",
        }
    ),
}
