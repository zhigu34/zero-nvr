from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.cameras.models import (
    Camera,
    CameraGroup,
    CameraStreamBinding,
    CameraStreamProfile,
    Device,
    DeviceCredential,
    DeviceEndpoint,
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

def _column_names(model) -> set[str]:
    return {
        column.key
        for column in inspect(model).columns
    }


def _foreign_key_ondelete(
    model,
    column_name: str,
) -> str | None:
    column = inspect(model).columns[column_name]
    foreign_key = next(iter(column.foreign_keys))
    return foreign_key.ondelete


def test_camera_inventory_matches_v1_schema_freeze() -> None:
    assert Device.__tablename__ == "devices"
    assert DeviceEndpoint.__tablename__ == "device_endpoints"
    assert DeviceCredential.__tablename__ == "device_credentials"
    assert Camera.__tablename__ == "cameras"
    assert (
        CameraStreamProfile.__tablename__
        == "camera_stream_profiles"
    )
    assert (
        CameraStreamBinding.__tablename__
        == "camera_stream_bindings"
    )

    assert {
        "id",
        "name",
        "manufacturer",
        "model",
        "serial_number",
        "hardware_id",
        "adapter_type",
        "enabled",
        "capabilities_json",
        "capabilities_updated_at",
        "created_at",
        "updated_at",
    } <= _column_names(Device)

    assert {
        "id",
        "device_id",
        "type",
        "host",
        "port",
        "scheme",
        "path",
        "priority",
        "enabled",
        "last_verified_at",
        "metadata_json",
        "created_at",
        "updated_at",
    } <= _column_names(DeviceEndpoint)

    credential_columns = _column_names(
        DeviceCredential
    )
    assert {
        "id",
        "device_id",
        "endpoint_id",
        "kind",
        "secret_ref",
        "created_at",
        "updated_at",
    } <= credential_columns
    assert {
        "username",
        "password",
        "token",
        "credential",
        "secret",
    }.isdisjoint(credential_columns)

    assert {
        "id",
        "device_id",
        "channel_key",
        "name",
        "enabled",
        "location",
        "storage_label",
        "created_at",
        "updated_at",
    } <= _column_names(Camera)

    profile_columns = _column_names(
        CameraStreamProfile
    )
    assert {
        "id",
        "camera_id",
        "adapter_profile_key",
        "video_source_key",
        "name",
        "codec",
        "width",
        "height",
        "fps",
        "bitrate_kbps",
        "gop_seconds",
        "audio_codec",
        "has_audio",
        "stream_uri_ref",
        "status",
        "last_verified_at",
        "metadata_json",
    } <= profile_columns
    assert {
        "stream_uri",
        "rtsp_url",
        "username",
        "password",
    }.isdisjoint(profile_columns)

    assert {
        "id",
        "camera_id",
        "purpose",
        "stream_profile_id",
        "selection_mode",
        "updated_at",
    } <= _column_names(CameraStreamBinding)

    assert (
        _foreign_key_ondelete(
            DeviceCredential,
            "secret_ref",
        )
        == "RESTRICT"
    )
    assert (
        _foreign_key_ondelete(
            CameraStreamProfile,
            "stream_uri_ref",
        )
        == "RESTRICT"
    )
    assert (
        _foreign_key_ondelete(
            Camera,
            "device_id",
        )
        == "RESTRICT"
    )
    assert (
        _foreign_key_ondelete(
            CameraStreamBinding,
            "stream_profile_id",
        )
        == "RESTRICT"
    )

