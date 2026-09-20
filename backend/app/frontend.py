from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Serve a Vite SPA without masking zero-nvr API 404 responses."""

    _reserved_prefixes = ("api/", "internal/")

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (
                exc.status_code != 404
                or scope.get("method") not in {"GET", "HEAD"}
                or path.startswith(self._reserved_prefixes)
            ):
                raise
            return await super().get_response("index.html", scope)


def packaged_frontend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend"


def mount_frontend(
    app: FastAPI,
    *,
    directory: Path | None = None,
) -> bool:
    target = directory or packaged_frontend_dir()
    if not (target / "index.html").is_file():
        return False

    app.mount(
        "/",
        SpaStaticFiles(directory=target, html=True),
        name="frontend",
    )
    return True
