from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.errors import ApiError


class PrebufferMountService:
    @staticmethod
    def _filesystem_type(
        path: Path,
        *,
        mountinfo: Path = Path("/proc/self/mountinfo"),
    ) -> str | None:
        resolved = path.resolve(strict=False)
        best_mount: Path | None = None
        best_type: str | None = None

        try:
            lines = mountinfo.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return None

        for line in lines:
            # mountinfo format:
            # id parent major:minor root mountpoint options ... - fstype source superopts
            if " - " not in line:
                continue
            before, after = line.split(" - ", 1)
            fields = before.split()
            tail = after.split()
            if len(fields) < 5 or not tail:
                continue

            raw_mount = (
                fields[4]
                .replace("\\040", " ")
                .replace("\\011", "\t")
                .replace("\\012", "\n")
                .replace("\\134", "\\")
            )
            mount = Path(raw_mount).resolve(strict=False)
            try:
                resolved.relative_to(mount)
            except ValueError:
                continue

            if (
                best_mount is None
                or len(mount.parts) > len(best_mount.parts)
            ):
                best_mount = mount
                best_type = tail[0]

        return best_type

    @classmethod
    def ensure_available(
        cls,
        settings: Settings,
    ) -> Path:
        root = settings.prebuffer_dir.resolve(strict=False)
        if not root.is_dir():
            raise ApiError(
                status_code=503,
                code="prebuffer_mount_unavailable",
                message="EVENT_ONLY prebuffer mount is unavailable.",
            )

        if settings.prebuffer_require_tmpfs:
            fs_type = cls._filesystem_type(root)
            if fs_type != "tmpfs":
                raise ApiError(
                    status_code=503,
                    code="prebuffer_mount_not_tmpfs",
                    message="EVENT_ONLY prebuffer must use the configured bounded tmpfs mount.",
                    details={
                        "filesystem_type": (
                            fs_type or "unknown"
                        )
                    },
                )

        probe = root / ".zero-nvr-prebuffer-write-test"
        try:
            with probe.open("wb") as handle:
                handle.write(b"zero-nvr")
                handle.flush()
            probe.unlink(missing_ok=True)
        except OSError as exc:
            probe.unlink(missing_ok=True)
            raise ApiError(
                status_code=503,
                code="prebuffer_mount_not_writable",
                message="EVENT_ONLY prebuffer mount is not writable.",
            ) from exc

        return root
