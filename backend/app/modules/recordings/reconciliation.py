from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.db.types import utc_now
from app.modules.cameras.models import (
    CameraStreamProfile,
)
from app.modules.system.models import SystemSetting
from app.modules.storage.models import (
    RecordingLocation,
    StorageTarget,
)

from .catalog import RecordingCatalogService
from .models import RecordingSegment


_RECONCILIATION_NAMESPACE = (
    "recording.reconciliation"
)
_FILENAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-"
    r"(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})"
    r"(?:-\d+)?\.mp4$"
)
_STREAM = re.compile(
    r"^profile-(?P<profile>[0-9a-fA-F]{32})$"
)


@dataclass(frozen=True, slots=True)
class RecoveredMediaProbe:
    duration_ms: int
    codec: str | None


@dataclass(frozen=True, slots=True)
class RecordingReconciliationResult:
    started_at: datetime
    completed_at: datetime
    full: bool
    scanned_files: int
    recovered: int
    relinked: int
    missing: int
    ambiguous: int
    errors: int
    skipped_unsettled: int

    @property
    def changes(self) -> int:
        return (
            self.recovered
            + self.relinked
            + self.missing
        )


@dataclass(frozen=True, slots=True)
class _RecoveredIdentity:
    profile_id: uuid.UUID
    started_at: datetime
    stream: str


class RecordingCatalogReconciliationService:
    recent_overlap = timedelta(minutes=10)
    initial_lookback = timedelta(hours=24)
    settle_seconds = 30

    def __init__(
        self,
        settings: Settings,
        *,
        probe: Callable[
            [Path],
            RecoveredMediaProbe,
        ] | None = None,
        now: Callable[[], datetime] = utc_now,
        mutation_hook: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self._probe = (
            probe
            if probe is not None
            else self._ffprobe
        )
        self._now = now
        self._mutation_hook = mutation_hook

    @staticmethod
    def _ffprobe(
        path: Path,
    ) -> RecoveredMediaProbe:
        try:
            completed = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(
                completed.stdout
            )
            duration = float(
                (
                    payload.get("format")
                    or {}
                ).get("duration")
                or 0
            )
            streams = payload.get(
                "streams"
            )
            codec = None
            if (
                isinstance(streams, list)
                and streams
                and isinstance(
                    streams[0],
                    dict,
                )
            ):
                raw_codec = streams[0].get(
                    "codec_name"
                )
                if isinstance(
                    raw_codec,
                    str,
                ):
                    codec = (
                        raw_codec.strip().lower()
                        or None
                    )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise RuntimeError(
                "recording recovery ffprobe failed"
            ) from exc

        duration_ms = int(
            round(duration * 1000)
        )
        if duration_ms <= 0:
            raise RuntimeError(
                "recording recovery duration is invalid"
            )
        return RecoveredMediaProbe(
            duration_ms=duration_ms,
            codec=codec,
        )

    @staticmethod
    def _target_root(
        target: StorageTarget,
    ) -> Path | None:
        raw = target.config_json.get(
            "path"
        )
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        if not value:
            return None
        return Path(value).expanduser().resolve()

    @classmethod
    def _targets(
        cls,
        session: Session,
    ) -> list[
        tuple[uuid.UUID, Path]
    ]:
        result: list[
            tuple[uuid.UUID, Path]
        ] = []
        for target in session.scalars(
            select(StorageTarget)
            .where(
                StorageTarget.enabled.is_(
                    True
                ),
                StorageTarget.type
                == "local",
                StorageTarget.role
                == "recording",
            )
            .order_by(
                StorageTarget.name,
                StorageTarget.id,
            )
        ):
            root = cls._target_root(
                target
            )
            if root is not None:
                result.append(
                    (
                        target.id,
                        root,
                    )
                )
        return result

    @staticmethod
    def _safe_file(
        root: Path,
        object_path: str,
    ) -> Path | None:
        try:
            candidate = (
                root
                / Path(object_path)
            ).resolve(
                strict=False
            )
            candidate.relative_to(
                root
            )
        except (OSError, ValueError):
            return None
        return candidate

    @staticmethod
    def _parse_time(
        match: re.Match[str],
    ) -> datetime | None:
        try:
            return datetime(
                int(
                    match.group(
                        "date"
                    )[0:4]
                ),
                int(
                    match.group(
                        "date"
                    )[5:7]
                ),
                int(
                    match.group(
                        "date"
                    )[8:10]
                ),
                int(match.group("h")),
                int(match.group("m")),
                int(match.group("s")),
                tzinfo=UTC,
            )
        except ValueError:
            return None

    @classmethod
    def _identity(
        cls,
        *,
        root: Path,
        path: Path,
    ) -> _RecoveredIdentity | None:
        try:
            relative = (
                path.resolve()
                .relative_to(root)
            )
        except (OSError, ValueError):
            return None

        parts = relative.parts
        if (
            len(parts) != 5
            or parts[0] != "record"
            or parts[1] != "zero-nvr"
        ):
            return None

        stream_match = (
            _STREAM.fullmatch(
                parts[2]
            )
        )
        file_match = (
            _FILENAME.fullmatch(
                parts[4]
            )
        )
        if (
            stream_match is None
            or file_match is None
            or parts[3]
            != file_match.group(
                "date"
            )
        ):
            return None

        started_at = cls._parse_time(
            file_match
        )
        if started_at is None:
            return None

        try:
            profile_id = uuid.UUID(
                hex=stream_match.group(
                    "profile"
                )
            )
        except ValueError:
            return None

        return _RecoveredIdentity(
            profile_id=profile_id,
            started_at=started_at,
            stream=parts[2],
        )

    @staticmethod
    def _state(
        session: Session,
    ) -> SystemSetting | None:
        return session.get(
            SystemSetting,
            _RECONCILIATION_NAMESPACE,
        )

    @staticmethod
    def _parse_state_time(
        value: object,
    ) -> datetime | None:
        if not isinstance(
            value,
            str,
        ):
            return None
        try:
            parsed = (
                datetime.fromisoformat(
                    value.replace(
                        "Z",
                        "+00:00",
                    )
                )
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(
            UTC
        )

    def _recent_since(
        self,
        session: Session,
        *,
        now: datetime,
    ) -> datetime:
        state = self._state(session)
        if state is None:
            return (
                now
                - self.initial_lookback
            )
        completed = (
            self._parse_state_time(
                (
                    state.value_json
                    or {}
                ).get(
                    "last_completed_at"
                )
            )
        )
        if completed is None:
            return (
                now
                - self.initial_lookback
            )
        return (
            completed
            - self.recent_overlap
        )

    @staticmethod
    def _known_locations(
        session: Session,
        *,
        target_id: uuid.UUID,
    ) -> dict[
        str,
        RecordingLocation,
    ]:
        return {
            item.object_path: item
            for item in session.scalars(
                select(
                    RecordingLocation
                ).where(
                    RecordingLocation.storage_target_id
                    == target_id
                )
            )
        }

    def _mutation_committed(
        self,
    ) -> None:
        if (
            self._mutation_hook
            is not None
        ):
            self._mutation_hook()

    def _mark_missing(
        self,
        database: Database,
        *,
        targets: list[
            tuple[uuid.UUID, Path]
        ],
        now: datetime,
    ) -> tuple[int, int]:
        missing = 0
        errors = 0

        for target_id, root in targets:
            with database.session() as session:
                locations = list(
                    session.scalars(
                        select(
                            RecordingLocation
                        ).where(
                            RecordingLocation.storage_target_id
                            == target_id,
                            RecordingLocation.state
                            == "AVAILABLE",
                        )
                    )
                )
                session.expunge_all()
                session.commit()

            for location in locations:
                file_path = (
                    self._safe_file(
                        root,
                        location.object_path,
                    )
                )
                if file_path is None:
                    errors += 1
                    continue
                if file_path.is_file():
                    continue

                with database.session() as session:
                    current = session.get(
                        RecordingLocation,
                        location.id,
                    )
                    if (
                        current is None
                        or current.state
                        != "AVAILABLE"
                    ):
                        session.commit()
                        continue
                    current.state = (
                        "MISSING"
                    )
                    current.last_attempt_at = now
                    current.last_error = (
                        "recording_file_missing"
                    )
                    session.commit()
                missing += 1
                self._mutation_committed()

        return missing, errors

    def _recover_file(
        self,
        database: Database,
        *,
        target_id: uuid.UUID,
        root: Path,
        path: Path,
        object_path: str,
        now: datetime,
    ) -> tuple[str, bool]:
        with database.session() as session:
            existing = session.scalar(
                select(
                    RecordingLocation
                ).where(
                    RecordingLocation.storage_target_id
                    == target_id,
                    RecordingLocation.object_path
                    == object_path,
                )
            )
            if existing is not None:
                if (
                    existing.state
                    == "MISSING"
                ):
                    size_bytes = (
                        path.stat().st_size
                    )
                    if (
                        size_bytes <= 0
                        or (
                            existing.size_bytes
                            > 0
                            and existing.size_bytes
                            != size_bytes
                        )
                    ):
                        session.commit()
                        return (
                            "error",
                            False,
                        )
                    existing.state = (
                        "AVAILABLE"
                    )
                    existing.size_bytes = (
                        size_bytes
                    )
                    existing.last_attempt_at = (
                        now
                    )
                    existing.last_error = None
                    session.commit()
                    self._mutation_committed()
                    return (
                        "relinked",
                        True,
                    )
                session.commit()
                return (
                    "known",
                    False,
                )

            identity = self._identity(
                root=root,
                path=path,
            )
            if identity is None:
                session.commit()
                return (
                    "ambiguous",
                    False,
                )

            profile = session.get(
                CameraStreamProfile,
                identity.profile_id,
            )
            if profile is None:
                session.commit()
                return (
                    "ambiguous",
                    False,
                )

            try:
                probe = self._probe(
                    path
                )
                size_bytes = (
                    path.stat().st_size
                )
            except (
                OSError,
                RuntimeError,
            ):
                session.commit()
                return (
                    "error",
                    False,
                )

            if size_bytes <= 0:
                session.commit()
                return (
                    "error",
                    False,
                )

            ended_at = (
                identity.started_at
                + timedelta(
                    milliseconds=(
                        probe.duration_ms
                    )
                )
            )
            reasons = (
                RecordingCatalogService
                .recording_reasons(
                    session,
                    camera_id=(
                        profile.camera_id
                    ),
                    started_at=(
                        identity.started_at
                    ),
                    ended_at=ended_at,
                )
            )
            segment = RecordingSegment(
                camera_id=(
                    profile.camera_id
                ),
                stream_profile_id=(
                    profile.id
                ),
                started_at=(
                    identity.started_at
                ),
                ended_at=ended_at,
                duration_ms=(
                    probe.duration_ms
                ),
                timing_status="FINAL",
                timing_source="RECOVERY",
                recording_reasons_json=(
                    reasons
                ),
                size_bytes=size_bytes,
                codec=(
                    probe.codec
                    or profile.codec
                ),
                container="fmp4",
                source_media_server_id=(
                    "default"
                ),
                source_app="zero-nvr",
                source_stream=(
                    identity.stream
                ),
                integrity_status="OK",
                completion_reason=(
                    "RECOVERY"
                ),
                created_at=now,
            )
            session.add(segment)
            session.flush()
            session.add(
                RecordingLocation(
                    recording_segment_id=(
                        segment.id
                    ),
                    storage_target_id=(
                        target_id
                    ),
                    object_path=(
                        object_path
                    ),
                    state="AVAILABLE",
                    size_bytes=(
                        size_bytes
                    ),
                    verified_at=now,
                    last_attempt_at=now,
                    last_error=None,
                )
            )
            session.commit()

        self._mutation_committed()
        return (
            "recovered",
            True,
        )

    def _record_state(
        self,
        database: Database,
        *,
        result: RecordingReconciliationResult,
    ) -> None:
        payload = {
            "last_completed_at": (
                result.completed_at
                .isoformat()
            ),
            "last_full_at": None,
            "last_result": {
                "full": result.full,
                "scanned_files": (
                    result.scanned_files
                ),
                "recovered": (
                    result.recovered
                ),
                "relinked": (
                    result.relinked
                ),
                "missing": (
                    result.missing
                ),
                "ambiguous": (
                    result.ambiguous
                ),
                "errors": (
                    result.errors
                ),
                "skipped_unsettled": (
                    result.skipped_unsettled
                ),
            },
        }

        with database.session() as session:
            state = self._state(
                session
            )
            previous = (
                dict(
                    state.value_json
                    or {}
                )
                if state is not None
                else {}
            )
            if not result.full:
                payload[
                    "last_full_at"
                ] = previous.get(
                    "last_full_at"
                )
            else:
                payload[
                    "last_full_at"
                ] = (
                    result.completed_at
                    .isoformat()
                )

            if state is None:
                session.add(
                    SystemSetting(
                        namespace=(
                            _RECONCILIATION_NAMESPACE
                        ),
                        value_json=payload,
                    )
                )
            else:
                state.value_json = (
                    payload
                )
            session.commit()

    def reconcile(
        self,
        database: Database,
        *,
        full: bool = False,
    ) -> RecordingReconciliationResult:
        started_at = (
            self._now()
            .astimezone(UTC)
        )
        with database.session() as session:
            targets = self._targets(
                session
            )
            since = (
                None
                if full
                else self._recent_since(
                    session,
                    now=started_at,
                )
            )
            session.commit()

        missing = 0
        errors = 0
        if full:
            (
                missing,
                missing_errors,
            ) = self._mark_missing(
                database,
                targets=targets,
                now=started_at,
            )
            errors += (
                missing_errors
            )

        scanned = 0
        recovered = 0
        relinked = 0
        ambiguous = 0
        unsettled = 0
        settle_before = (
            started_at.timestamp()
            - self.settle_seconds
        )

        for target_id, root in targets:
            if not root.is_dir():
                continue

            for path in root.rglob(
                "*.mp4"
            ):
                try:
                    if (
                        not path.is_file()
                        or path.name.startswith(
                            "."
                        )
                    ):
                        continue
                    resolved = (
                        path.resolve()
                    )
                    resolved.relative_to(
                        root
                    )
                    stat = (
                        resolved.stat()
                    )
                except (
                    OSError,
                    ValueError,
                ):
                    errors += 1
                    continue

                if (
                    since is not None
                    and stat.st_mtime
                    < since.timestamp()
                ):
                    continue
                if (
                    stat.st_mtime
                    > settle_before
                ):
                    unsettled += 1
                    continue

                scanned += 1
                object_path = (
                    resolved.relative_to(
                        root
                    ).as_posix()
                )
                outcome, changed = (
                    self._recover_file(
                        database,
                        target_id=target_id,
                        root=root,
                        path=resolved,
                        object_path=(
                            object_path
                        ),
                        now=started_at,
                    )
                )
                if outcome == "recovered":
                    recovered += 1
                elif outcome == "relinked":
                    relinked += 1
                elif outcome == "ambiguous":
                    ambiguous += 1
                elif outcome == "error":
                    errors += 1

        completed_at = (
            self._now()
            .astimezone(UTC)
        )
        result = (
            RecordingReconciliationResult(
                started_at=started_at,
                completed_at=(
                    completed_at
                ),
                full=full,
                scanned_files=(
                    scanned
                ),
                recovered=recovered,
                relinked=relinked,
                missing=missing,
                ambiguous=ambiguous,
                errors=errors,
                skipped_unsettled=(
                    unsettled
                ),
            )
        )
        self._record_state(
            database,
            result=result,
        )
        return result
