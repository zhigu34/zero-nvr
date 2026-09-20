from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import (
    Camera,
    CameraGroup,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    PrincipalCameraScope,
    PrincipalCameraScopeEntry,
)


def make_database(tmp_path: Path) -> Database:
    settings = Settings(
        secret_key="camera-model-test-secret-key-32-bytes-minimum",
        database_url=f"sqlite:///{tmp_path / 'camera-models.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return database


def test_camera_profile_binding_and_scope_constraints(tmp_path: Path) -> None:
    database = make_database(tmp_path)

    try:
        with database.session() as session:
            device = Device(
                name="Front Door Device",
                adapter_type="onvif",
                enabled=True,
            )
            camera = Camera(
                device_id=None,
                channel_key="channel-1",
                name="Front Door",
                enabled=True,
            )
            session.add_all([device, camera])
            session.flush()

            profile = CameraStreamProfile(
                camera_id=camera.id,
                adapter_profile_key="profile-main",
                name="Main",
                codec="h264",
                width=1920,
                height=1080,
                fps=25,
                status="available",
            )
            session.add(profile)
            session.flush()

            binding = CameraStreamBinding(
                camera_id=camera.id,
                purpose="RECORD",
                stream_profile_id=profile.id,
                selection_mode="auto",
            )
            session.add(binding)

            group = CameraGroup(name="Exterior")
            session.add(group)
            session.flush()

            scope = PrincipalCameraScope(
                principal_type="user",
                principal_id=uuid.uuid4(),
                scope_mode="selected",
            )
            session.add(scope)
            session.flush()

            session.add(
                PrincipalCameraScopeEntry(
                    scope_id=scope.id,
                    camera_id=camera.id,
                )
            )
            session.commit()

        with database.session() as session:
            camera = session.query(Camera).filter_by(name="Front Door").one()
            profile = session.query(CameraStreamProfile).filter_by(
                camera_id=camera.id
            ).one()

            session.add(
                CameraStreamBinding(
                    camera_id=camera.id,
                    purpose="RECORD",
                    stream_profile_id=profile.id,
                    selection_mode="manual",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        with database.session() as session:
            scope = session.query(PrincipalCameraScope).filter_by(
                scope_mode="selected"
            ).one()
            camera = session.query(Camera).filter_by(name="Front Door").one()
            session.add(
                PrincipalCameraScopeEntry(
                    scope_id=scope.id,
                    camera_id=camera.id,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
    finally:
        database.close()
