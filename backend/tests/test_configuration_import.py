"""Characterisation tests for the configuration import validator.

``config_import.py`` is the largest module in the tree and had no direct test
coverage. Before it can be split, its current behaviour has to be pinned — these
tests record what the validator does today, including the parts that are easy to
break by accident:

* the exact error codes and ``details`` payloads the API surfaces,
* the difference between list-shaped and object-shaped sections,
* the fact that the secret-bearing-field rejection walks the whole document,
* the input key for the exporting version (``application_version``), which does
  not match the dataclass field it populates (``source_application_version``).

``validate`` takes no database session, so these run without fixtures beyond a
minimal ``Settings``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

import pytest

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.system.config_import import (
    ConfigurationImportService,
)
from tests.factories import make_test_app, make_test_database

APP_VERSION = "1.0.0"
FORMAT = "zero-nvr.configuration"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="x" * 32,
        app_version=APP_VERSION,
        environment="test",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
    )


@pytest.fixture()
def database(tmp_path: Path):
    """An initialised database for the ``apply`` cases.

    Only the handful of tests that exercise ``apply`` need this; the validator
    tests run against ``Settings`` alone.
    """
    _, database = make_test_database(tmp_path, app_version=APP_VERSION)
    return database


def bundle(**overrides: Any) -> dict[str, Any]:
    """A well-formed envelope; tests override only the part under test."""
    payload: dict[str, Any] = {
        "format": FORMAT,
        "format_version": 1,
        "secrets_included": False,
        "application_version": APP_VERSION,
        "sections": {},
    }
    payload.update(overrides)
    return payload


def validate(payload: dict[str, Any], settings: Settings):
    return ConfigurationImportService.validate(payload, settings=settings)


def error_of(payload: dict[str, Any], settings: Settings) -> ApiError:
    with pytest.raises(ApiError) as caught:
        validate(payload, settings)
    return caught.value


# --- envelope ---------------------------------------------------------------


def test_empty_bundle_is_valid_and_reports_every_known_section(
    settings: Settings,
) -> None:
    result = validate(bundle(), settings)

    # Every section is reported, including the ones the bundle omits, so the
    # caller can render a full preflight table.
    assert set(result.section_counts) == {
        "general",
        "time",
        "roles",
        "devices",
        "cameras",
        "recording",
        "storage_targets",
        "alert_policies",
        "notification_targets",
        "frigate",
        "backup_policies",
    }
    assert set(result.section_counts.values()) == {0}
    assert result.credentials_required == ()


def test_rejects_an_unknown_format(settings: Settings) -> None:
    error = error_of(bundle(format="something-else"), settings)

    assert error.code == "configuration_import_format_invalid"
    assert error.details == {}


def test_rejects_an_unsupported_format_version(settings: Settings) -> None:
    error = error_of(bundle(format_version=2), settings)

    assert error.code == "configuration_import_version_unsupported"
    # The offending version is echoed back for the operator.
    assert error.details == {"format_version": 2}


@pytest.mark.parametrize("value", [None, True, "false"])
def test_requires_secrets_included_to_be_explicitly_false(
    settings: Settings, value: Any
) -> None:
    payload = bundle()
    if value is None:
        payload.pop("secrets_included")
    else:
        payload["secrets_included"] = value

    error = error_of(payload, settings)

    assert error.code == "configuration_import_secrets_not_allowed"


def test_rejects_an_unknown_section_and_lists_it(settings: Settings) -> None:
    error = error_of(bundle(sections={"bogus": {}}), settings)

    assert error.code == "configuration_import_section_unsupported"
    assert error.details == {"sections": ["bogus"]}


@pytest.mark.parametrize(
    "changes,expected_code",
    [
        ({"format": "other", "format_version": 2}, "configuration_import_format_invalid"),
        ({"format_version": 2, "secrets_included": True}, "configuration_import_version_unsupported"),
        (
            {"secrets_included": True, "sections": {"general": {"password": "x"}}},
            "configuration_import_secrets_not_allowed",
        ),
        (
            {"sections": {"bogus": {"password": "x"}}},
            "configuration_import_secret_field",
        ),
        (
            {"sections": {"bogus": {}, "devices": []}},
            "configuration_import_section_unsupported",
        ),
    ],
)
def test_envelope_error_precedence_is_stable(
    settings: Settings, changes: dict[str, Any], expected_code: str
) -> None:
    assert error_of(bundle(**changes), settings).code == expected_code


def test_rejects_sections_that_are_not_a_mapping(settings: Settings) -> None:
    error = error_of(bundle(sections=[]), settings)

    assert error.code == "configuration_import_invalid"
    assert error.details["path"] == "$.sections"


# --- secret-bearing fields --------------------------------------------------


def test_rejects_a_forbidden_field_anywhere_in_the_document(
    settings: Settings,
) -> None:
    payload = bundle(
        sections={"general": {"system_name": "NVR", "password": "hunter2"}}
    )

    error = error_of(payload, settings)

    assert error.code == "configuration_import_secret_field"
    # The path is a JSON pointer so the UI can highlight the offending field.
    assert error.details == {
        "path": "$.sections.general.password",
        "field": "password",
    }


def test_rejects_a_forbidden_field_nested_in_a_list(settings: Settings) -> None:
    payload = bundle(
        sections={"cameras": {"items": [{"id": "c1", "rtsp_url": "rtsp://x"}]}}
    )

    error = error_of(payload, settings)

    assert error.code == "configuration_import_secret_field"
    assert error.details["path"] == "$.sections.cameras.items[0].rtsp_url"


@pytest.mark.parametrize(
    "field",
    [
        "secret_ref",
        "credential_secret_ref",
        "repository_config_ref",
        "stream_uri_ref",
        "encrypted_payload",
        "token_hash",
        "password_hash",
        "client_secret",
        "rclone_config",
        "rtsp_url",
        "stream_uri",
        "http_bearer_token",
        "http_password",
        "mqtt_password",
        "secret_access_key",
        "access_key_id",
        "password",
    ],
)
def test_every_declared_forbidden_field_is_rejected(
    settings: Settings, field: str
) -> None:
    payload = bundle(sections={"general": {"system_name": "NVR", field: "x"}})

    error = error_of(payload, settings)

    assert error.code == "configuration_import_secret_field"
    assert error.details["field"] == field


def test_allows_a_field_that_merely_mentions_a_secret(
    settings: Settings,
) -> None:
    # Rejection is by exact field name, not by substring: `password` is
    # forbidden but `password_reset` is a legitimate export flag.
    result = validate(
        bundle(sections={"notification_targets": [{"id": "n1", "password_reset": False}]}),
        settings,
    )

    assert result.section_counts["notification_targets"] == 1


# --- section shapes ---------------------------------------------------------


def test_list_shaped_sections_are_counted(settings: Settings) -> None:
    payload = bundle(
        sections={
            "roles": [{"id": "r1", "name": "ops"}],
            "storage_targets": [{"id": "t1", "name": "local"}],
            "alert_policies": [{"id": "a1", "name": "policy"}],
            "notification_targets": [{"id": "n1", "name": "mail"}],
            "backup_policies": [{"id": "b1", "name": "nightly"}],
        }
    )

    result = validate(payload, settings)

    assert result.section_counts["roles"] == 1
    assert result.section_counts["storage_targets"] == 1
    assert result.section_counts["alert_policies"] == 1
    assert result.section_counts["notification_targets"] == 1
    assert result.section_counts["backup_policies"] == 1


@pytest.mark.parametrize("section", ["cameras", "devices"])
def test_device_sections_must_be_an_object(
    settings: Settings, section: str
) -> None:
    # These two are envelopes with an `items` list, unlike the sections above.
    error = error_of(bundle(sections={section: []}), settings)

    assert error.code == "configuration_import_invalid"
    assert error.details["path"] == f"$.sections.{section}"


@pytest.mark.parametrize(
    "section,payload",
    [
        # The device envelopes nest their row lists under a same-named key,
        # which is why the section itself has to be an object.
        ("cameras", {"cameras": [], "stream_profiles": []}),
        ("devices", {"devices": [], "credentials": []}),
    ],
)
def test_device_sections_accept_their_nested_envelope(
    settings: Settings, section: str, payload: dict[str, Any]
) -> None:
    result = validate(bundle(sections={section: payload}), settings)

    assert result.section_counts[section] == 0


@pytest.mark.parametrize(
    "devices,cameras,recording,expected_path",
    [
        (
            {"devices": [None]},
            {"cameras": [None]},
            {"policies": [None]},
            "$.sections.devices.devices[0]",
        ),
        (
            {"devices": []},
            {"stream_profiles": [None], "groups": [None]},
            {"policies": [None]},
            "$.sections.cameras.stream_profiles[0]",
        ),
        (
            {"devices": []},
            {"cameras": []},
            {"policies": [None], "retention_policies": [None]},
            "$.sections.recording.policies[0]",
        ),
    ],
)
def test_nested_section_shape_errors_keep_export_order(
    settings: Settings,
    devices: dict[str, Any],
    cameras: dict[str, Any],
    recording: dict[str, Any],
    expected_path: str,
) -> None:
    error = error_of(
        bundle(sections={"devices": devices, "cameras": cameras, "recording": recording}),
        settings,
    )

    assert error.code == "configuration_import_invalid"
    assert error.details == {"path": expected_path}


def test_object_sections_are_counted_when_present(settings: Settings) -> None:
    payload = bundle(
        sections={
            "general": {"system_name": "Home NVR"},
            "time": {"recording_timezone": "UTC"},
            "frigate": {"enabled": False},
        }
    )

    result = validate(payload, settings)

    assert result.section_counts["general"] == 1
    assert result.section_counts["time"] == 1
    assert result.section_counts["frigate"] == 1


def test_a_list_item_without_an_id_is_rejected(settings: Settings) -> None:
    error = error_of(bundle(sections={"roles": [{"name": "ops"}]}), settings)

    assert error.code == "configuration_import_invalid"
    assert error.details["path"] == "$.sections.roles[0].id"


# --- references -------------------------------------------------------------


def test_a_broken_reference_is_rejected_with_its_path(
    settings: Settings,
) -> None:
    payload = bundle(
        sections={"recording": {"policies": [{"id": "p1", "name": "p"}]}}
    )

    error = error_of(payload, settings)

    assert error.code == "configuration_import_reference_invalid"
    assert error.details["path"] == "$.sections.recording.policies[0].camera_id"
    assert error.details["reference"] is None


@pytest.mark.parametrize(
    "sections,path",
    [
        (
            {"cameras": {"groups": [{"id": "g1", "name": "Lobby", "parent_id": "missing"}]}},
            "$.sections.cameras.groups[0].parent_id",
        ),
        (
            {
                "cameras": {
                    "groups": [{"id": "g1", "name": "Lobby"}],
                    "group_members": [
                        {"camera_group_id": "g1", "camera_id": "missing"}
                    ],
                }
            },
            "$.sections.cameras.group_members[0].camera_id",
        ),
        (
            {
                "roles": [
                    {
                        "id": "r1",
                        "name": "Viewer",
                        "camera_scope": {"camera_ids": ["missing"]},
                    }
                ]
            },
            "$.sections.roles[0].camera_scope.camera_ids[0]",
        ),
    ],
)
def test_group_and_role_camera_references_keep_error_paths(
    settings: Settings, sections: dict[str, Any], path: str
) -> None:
    error = error_of(bundle(sections=sections), settings)

    assert error.code == "configuration_import_reference_invalid"
    assert error.details["path"] == path


# --- credential requirements ------------------------------------------------


def test_reports_credentials_that_must_be_supplied_separately(
    settings: Settings,
) -> None:
    payload = bundle(
        sections={
            "storage_targets": [
                {
                    "id": "t1",
                    "name": "Archive",
                    "credentials_configured": True,
                }
            ],
            "notification_targets": [
                {"id": "n1", "name": "Ops mail", "url_configured": True}
            ],
        }
    )

    result = validate(payload, settings)

    assert [(c.section, c.resource_id, c.name, c.credential) for c in result.credentials_required] == [
        ("storage_targets", "t1", "Archive", "rclone_config"),
        ("notification_targets", "n1", "Ops mail", "apprise_url"),
    ]


def test_credential_requirements_keep_section_order_and_multiple_needs(
    settings: Settings,
) -> None:
    result = validate(
        bundle(
            sections={
                "devices": {
                    "devices": [{"id": "d1", "name": "Device"}],
                    "credentials": [
                        {
                            "id": "dc1",
                            "name": "Device login",
                            "device_id": "d1",
                            "kind": "onvif",
                            "credentials_configured": True,
                        }
                    ],
                },
                "cameras": {
                    "cameras": [{"id": "c1", "name": "Camera"}],
                    "stream_profiles": [
                        {
                            "id": "sp1",
                            "name": "Main",
                            "camera_id": "c1",
                            "stream_uri_configured": True,
                        }
                    ],
                },
                "storage_targets": [
                    {"id": "s1", "name": "Archive", "credentials_configured": True}
                ],
                "notification_targets": [
                    {
                        "id": "n1",
                        "name": "Ops",
                        "url_configured": True,
                        "credentials_configured": True,
                    }
                ],
                "frigate": {"credentials_configured": True},
                "backup_policies": [
                    {
                        "id": "b1",
                        "name": "Nightly",
                        "repository_configured": True,
                        "credentials_configured": True,
                    }
                ],
            }
        ),
        settings,
    )

    assert [(item.section, item.credential) for item in result.credentials_required] == [
        ("devices", "onvif"),
        ("cameras", "stream_uri"),
        ("storage_targets", "rclone_config"),
        ("notification_targets", "apprise_url"),
        ("notification_targets", "smtp_credentials"),
        ("frigate", "integration_credentials"),
        ("backup_policies", "repository"),
        ("backup_policies", "repository_credentials"),
    ]


def test_a_camera_stream_profile_requirement_needs_its_camera_reference(
    settings: Settings,
) -> None:
    # Profiles live beside the camera rows, not inside each camera, and each one
    # must point back at a camera in the same bundle.
    payload = bundle(
        sections={
            "cameras": {
                "cameras": [],
                "stream_profiles": [
                    {
                        "id": "sp1",
                        "name": "main",
                        "stream_uri_configured": True,
                    }
                ],
            }
        }
    )

    error = error_of(payload, settings)

    assert error.code == "configuration_import_reference_invalid"
    assert (
        error.details["path"]
        == "$.sections.cameras.stream_profiles[0].camera_id"
    )


def test_credential_requirements_are_announced_in_the_warnings(
    settings: Settings,
) -> None:
    payload = bundle(
        sections={
            "notification_targets": [
                {"id": "n1", "name": "Ops mail", "url_configured": True}
            ]
        }
    )

    result = validate(payload, settings)

    assert any(
        "must be supplied separately" in warning for warning in result.warnings
    )


# --- warnings and version drift --------------------------------------------


def test_always_reports_what_is_deliberately_not_imported(
    settings: Settings,
) -> None:
    result = validate(bundle(), settings)

    # This guard rail is user-visible copy; pin it so a refactor cannot drop it.
    assert any(
        "intentionally not part of configuration import" in warning
        for warning in result.warnings
    )


def test_warns_when_the_bundle_came_from_another_version(
    settings: Settings,
) -> None:
    result = validate(bundle(application_version="0.9.0"), settings)

    assert result.source_application_version == "0.9.0"
    assert any(
        "exported by zero-nvr 0.9.0" in warning
        and APP_VERSION in warning
        for warning in result.warnings
    )


def test_does_not_warn_when_the_versions_match(settings: Settings) -> None:
    result = validate(bundle(application_version=APP_VERSION), settings)

    assert not any("exported by zero-nvr" in w for w in result.warnings)


def test_the_exporting_version_key_is_application_version(
    settings: Settings,
) -> None:
    # The dataclass field is `source_application_version`, but the input key is
    # `application_version`; the other spelling is silently ignored. Pinning this
    # documents the asymmetry rather than asserting it is a good idea.
    payload = bundle(source_application_version="0.9.0")
    payload.pop("application_version")

    result = validate(payload, settings)

    assert result.source_application_version is None
    assert not any("exported by zero-nvr" in w for w in result.warnings)


# --- apply: malformed ids must not become 500s ------------------------------
#
# `apply` reads resource ids as UUIDs for the sections whose target rows have
# UUID primary keys. `validate` did not check the format, so a bundle carrying a
# hand-written id passed preflight and then raised a bare ValueError inside
# `apply` — which the API surfaces as a 500 rather than a 400. These tests pin
# the corrected behaviour: a clear validation error, and no crash.


@pytest.mark.parametrize(
    "section,payload",
    [
        ("devices", {"devices": [{"id": "local", "name": "d"}], "credentials": []}),
        ("cameras", {"cameras": [{"id": "local", "name": "c"}], "stream_profiles": []}),
        (
            "storage_targets",
            [{"id": "local", "name": "t", "kind": "local", "config": {"path": "/x"}}],
        ),
        ("alert_policies", [{"id": "local", "name": "a"}]),
        ("notification_targets", [{"id": "local", "name": "n"}]),
        ("backup_policies", [{"id": "local", "name": "b"}]),
    ],
)
def test_a_non_uuid_id_is_rejected_instead_of_crashing(
    settings: Settings, database: Any, section: str, payload: Any
) -> None:
    document = bundle(sections={section: payload})

    with database.session() as session:
        with pytest.raises(ApiError) as caught:
            ConfigurationImportService.apply(
                session, settings=settings, bundle=document
            )

    error = caught.value
    assert error.status_code == 400
    assert error.code == "configuration_import_invalid"
    assert error.details == {"id": "local"}


def test_roles_may_still_use_a_non_uuid_source_id(
    settings: Settings, database: Any
) -> None:
    # Roles are matched by their source id, not by UUID, so they must keep
    # accepting arbitrary exporter ids — the fix above must not over-reject.
    document = bundle(
        sections={"roles": [{"id": "ops-role", "name": "ops", "permissions": []}]}
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [item.name for item in result.applied] == ["ops"]


def test_legacy_general_time_fields_merge_with_time_section(
    settings: Settings, database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy fields feed time settings, while explicit time values win."""
    from app.modules.system.settings import (
        SystemSettingsService,
        TimeSystemSettingsService,
    )

    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        SystemSettingsService,
        "update",
        lambda _session, *, settings, changes: calls.append(
            ("general", changes)
        ),
    )
    monkeypatch.setattr(
        TimeSystemSettingsService,
        "update",
        lambda _session, *, changes: calls.append(("time", changes)),
    )
    document = bundle(
        sections={
            "general": {
                "site_name": "Lab",
                "display_timezone": "UTC",
                "camera_ntp_servers": ["ntp.example"],
            },
            "time": {"recording_timezone": "Asia/Shanghai"},
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert calls == [
        ("general", {"site_name": "Lab"}),
        (
            "time",
            {
                "recording_timezone": "Asia/Shanghai",
                "managed_camera_ntp_servers": ["ntp.example"],
                "managed_camera_ntp_mode": "manual",
            },
        ),
    ]
    assert [(item.section, item.action) for item in result.applied] == [
        ("general", "updated"),
        ("time", "updated"),
    ]


def test_frigate_section_is_reported_as_manual_apply(
    settings: Settings, database: Any
) -> None:
    document = bundle(sections={"frigate": {}})

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [(item.section, item.reason) for item in result.skipped] == [
        ("frigate", "runtime_configuration_requires_manual_apply")
    ]


def test_unmatched_device_and_its_endpoint_are_skipped(
    settings: Settings, database: Any
) -> None:
    device_id = str(uuid.uuid4())
    document = bundle(
        sections={
            "devices": {
                "devices": [
                    {"id": device_id, "name": "Lobby", "adapter_type": "onvif"}
                ],
                "endpoints": [
                    {
                        "id": str(uuid.uuid4()),
                        "device_id": device_id,
                        "type": "onvif",
                        "host": "192.0.2.1",
                    }
                ],
            }
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [(item.resource_type, item.reason) for item in result.skipped] == [
        ("device", "credentials_required"),
        ("device_endpoint", "endpoint_address_preserved"),
    ]


def test_device_matches_unique_hardware_id_and_updates_metadata(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.models import Device

    source_id = str(uuid.uuid4())
    with database.session() as session:
        target = Device(
            name="Old name",
            adapter_type="onvif",
            hardware_id="serial-42",
        )
        session.add(target)
        session.flush()
        target_id = target.id

        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "devices": {
                        "devices": [
                            {
                                "id": source_id,
                                "name": "Lobby",
                                "adapter_type": "onvif",
                                "hardware_id": "serial-42",
                                "model": "Camera model",
                            }
                        ]
                    }
                }
            ),
        )
        assert session.get(Device, target_id).name == "Lobby"
        assert session.get(Device, target_id).model == "Camera model"

    assert [(item.resource_type, item.action, item.target_id) for item in result.applied] == [
        ("device", "updated", str(target_id))
    ]


def test_manual_device_matches_existing_endpoint_without_replacing_it(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.models import Device, DeviceEndpoint

    source_id = str(uuid.uuid4())
    with database.session() as session:
        target = Device(name="Old manual camera", adapter_type="manual_rtsp")
        session.add(target)
        session.flush()
        endpoint = DeviceEndpoint(
            device_id=target.id,
            type="rtsp",
            host="192.0.2.42",
            port=554,
        )
        session.add(endpoint)
        session.flush()
        target_id = target.id
        endpoint_id = endpoint.id

        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "devices": {
                        "devices": [
                            {
                                "id": source_id,
                                "name": "Renamed manual camera",
                                "adapter_type": "manual_rtsp",
                            }
                        ],
                        "endpoints": [
                            {
                                "id": str(uuid.uuid4()),
                                "device_id": source_id,
                                "type": "rtsp",
                                "host": "192.0.2.42",
                                "port": 554,
                            }
                        ],
                    }
                }
            ),
        )
        assert session.get(Device, target_id).name == "Renamed manual camera"
        assert session.get(DeviceEndpoint, endpoint_id).host == "192.0.2.42"

    assert ("device", "updated", str(target_id)) in [
        (item.resource_type, item.action, item.target_id) for item in result.applied
    ]
    assert ("device_endpoint", "endpoint_address_preserved") in [
        (item.resource_type, item.reason) for item in result.skipped
    ]


def test_existing_camera_metadata_updates_then_matches_without_reconcile(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.models import Camera

    with database.session() as session:
        camera = Camera(channel_key="main", name="Old name", enabled=True)
        session.add(camera)
        session.flush()
        camera_id = camera.id
        document = bundle(
            sections={
                "cameras": {
                    "cameras": [
                        {
                            "id": str(camera_id),
                            "name": "Lobby",
                            "location": "Ground floor",
                            "storage_label": "entry",
                            "maintenance": True,
                            "time_sync_mode": "ignore",
                            "enabled": False,
                        }
                    ]
                }
            }
        )

        first = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        assert camera.name == "Lobby"
        assert camera.location == "Ground floor"
        assert camera.storage_label == "entry"
        assert camera.maintenance is True
        assert camera.time_sync_mode == "ignore"
        assert camera.enabled is False

        repeated = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [(item.resource_type, item.action) for item in first.applied] == [
        ("camera", "updated")
    ]
    assert first.camera_ids_to_reconcile == (camera_id,)
    assert [(item.resource_type, item.action) for item in repeated.applied] == [
        ("camera", "matched")
    ]
    assert repeated.camera_ids_to_reconcile == ()


def test_camera_matches_mapped_device_and_channel_when_id_differs(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.models import Camera, Device

    source_device_id = str(uuid.uuid4())
    source_camera_id = str(uuid.uuid4())
    with database.session() as session:
        device = Device(
            name="Old device", adapter_type="onvif", hardware_id="serial-42"
        )
        session.add(device)
        session.flush()
        camera = Camera(device_id=device.id, channel_key="main", name="Old camera")
        session.add(camera)
        session.flush()
        device_id = device.id
        camera_id = camera.id

        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "devices": {
                        "devices": [
                            {
                                "id": source_device_id,
                                "name": "Lobby device",
                                "adapter_type": "onvif",
                                "hardware_id": "serial-42",
                            }
                        ]
                    },
                    "cameras": {
                        "cameras": [
                            {
                                "id": source_camera_id,
                                "device_id": source_device_id,
                                "channel_key": "main",
                                "name": "Lobby camera",
                            }
                        ]
                    },
                }
            ),
        )
        assert session.get(Device, device_id).name == "Lobby device"
        assert session.get(Camera, camera_id).name == "Lobby camera"

    assert [(item.resource_type, item.target_id) for item in result.applied] == [
        ("device", str(device_id)),
        ("camera", str(camera_id)),
    ]
    assert result.skipped == ()


def test_stream_profile_matches_by_camera_and_key_then_applies_binding(
    settings: Settings, database: Any
) -> None:
    from app.modules.auth.models import SecretRecord
    from app.modules.cameras.models import Camera, CameraStreamProfile

    with database.session() as session:
        camera = Camera(channel_key="main", name="Lobby")
        session.add(camera)
        session.flush()
        secret = SecretRecord(
            kind="camera_stream_uri",
            owner_type="camera",
            owner_id=camera.id,
            key_id="test",
            encrypted_payload=b"opaque",
        )
        session.add(secret)
        session.flush()
        profile = CameraStreamProfile(
            camera_id=camera.id,
            adapter_profile_key="main",
            name="Main",
            stream_uri_ref=secret.id,
        )
        session.add(profile)
        session.flush()
        camera_id = camera.id
        profile_id = profile.id
        source_profile_id = str(uuid.uuid4())
        document = bundle(
            sections={
                "cameras": {
                    "cameras": [{"id": str(camera_id), "name": "Lobby"}],
                    "stream_profiles": [
                        {
                            "id": source_profile_id,
                            "camera_id": str(camera_id),
                            "adapter_profile_key": "main",
                            "name": "Main",
                        }
                    ],
                    "stream_bindings": [
                        {
                            "id": str(uuid.uuid4()),
                            "camera_id": str(camera_id),
                            "stream_profile_id": source_profile_id,
                            "purpose": "RECORD",
                            "selection_mode": "auto",
                        }
                    ],
                }
            }
        )

        first = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        session.commit()

    with database.session() as session:
        repeated = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    first_items = [
        (item.resource_type, item.action, item.target_id) for item in first.applied
    ]
    assert ("camera_stream_profile", "matched", str(profile_id)) in first_items
    assert ("camera_stream_binding", "updated", str(camera_id)) in first_items
    assert ("camera_stream_binding", "matched", str(camera_id)) in [
        (item.resource_type, item.action, item.target_id)
        for item in repeated.applied
    ]
    assert first.camera_ids_to_reconcile == (camera_id,)
    assert repeated.camera_ids_to_reconcile == ()


def test_stream_bindings_skip_entire_camera_when_one_profile_is_unmapped(
    settings: Settings, database: Any
) -> None:
    from app.modules.auth.models import SecretRecord
    from app.modules.cameras.models import Camera, CameraStreamProfile

    with database.session() as session:
        camera = Camera(channel_key="main", name="Lobby")
        session.add(camera)
        session.flush()
        secret = SecretRecord(
            kind="camera_stream_uri",
            owner_type="camera",
            owner_id=camera.id,
            key_id="test",
            encrypted_payload=b"opaque",
        )
        session.add(secret)
        session.flush()
        session.add(
            CameraStreamProfile(
                camera_id=camera.id,
                adapter_profile_key="main",
                name="Main",
                stream_uri_ref=secret.id,
            )
        )
        session.flush()
        camera_id = camera.id
        source_profiles = [str(uuid.uuid4()), str(uuid.uuid4())]
        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "cameras": {
                        "cameras": [{"id": str(camera_id), "name": "Lobby"}],
                        "stream_profiles": [
                            {
                                "id": source_id,
                                "camera_id": str(camera_id),
                                "adapter_profile_key": key,
                                "name": key,
                            }
                            for source_id, key in zip(source_profiles, ("main", "missing"))
                        ],
                        "stream_bindings": [
                            {
                                "id": str(uuid.uuid4()),
                                "camera_id": str(camera_id),
                                "stream_profile_id": source_id,
                                "purpose": purpose,
                                "selection_mode": "auto",
                            }
                            for source_id, purpose in zip(
                                source_profiles, ("RECORD", "LIVE")
                            )
                        ],
                    }
                }
            ),
        )
        assert camera.stream_bindings == []

    assert [(item.resource_type, item.reason) for item in result.skipped] == [
        ("camera_stream_profile", "credential_required"),
        ("camera_stream_binding", "stream_profile_unmapped"),
        ("camera_stream_binding", "stream_profile_unmapped"),
    ]
    assert result.camera_ids_to_reconcile == ()


def test_unmatched_notification_target_requires_credentials(
    settings: Settings, database: Any
) -> None:
    document = bundle(
        sections={
            "notification_targets": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "Operations",
                    "kind": "apprise",
                    "enabled": True,
                    "url_configured": True,
                }
            ]
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [(item.resource_type, item.reason) for item in result.skipped] == [
        ("notification_target", "credential_required")
    ]


def test_unmatched_backup_policy_requires_local_repository(
    settings: Settings, database: Any
) -> None:
    document = bundle(
        sections={
            "backup_policies": [
                {"id": str(uuid.uuid4()), "name": "Nightly"}
            ]
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [(item.resource_type, item.reason) for item in result.skipped] == [
        ("backup_policy", "credential_required")
    ]


def test_alert_with_unmapped_camera_dependency_is_skipped(
    settings: Settings, database: Any
) -> None:
    camera_id = str(uuid.uuid4())
    document = bundle(
        sections={
            "cameras": {
                "cameras": [{"id": camera_id, "name": "Entrance"}],
            },
            "alert_policies": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "Entrance offline",
                    "match": {"camera_ids": [camera_id]},
                    "action": {},
                }
            ],
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert ("alert_policy", "alert_dependency_unmapped") in [
        (item.resource_type, item.reason) for item in result.skipped
    ]


def test_alert_policy_maps_existing_camera_and_notification_target(
    settings: Settings, database: Any
) -> None:
    from app.modules.alerts.models import AlertPolicy
    from app.modules.cameras.models import Camera
    from app.modules.notifications.models import NotificationTarget

    source_notification_id = str(uuid.uuid4())
    with database.session() as session:
        camera = Camera(channel_key="main", name="Door")
        notification = NotificationTarget(name="Ops", kind="apprise", config_json={})
        session.add_all([camera, notification])
        session.flush()
        camera_id = camera.id
        notification_id = notification.id

        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "cameras": {
                        "cameras": [{"id": str(camera_id), "name": "Door"}]
                    },
                    "notification_targets": [
                        {
                            "id": source_notification_id,
                            "name": "Ops",
                            "kind": "apprise",
                            "enabled": True,
                            "config": {},
                        }
                    ],
                    "alert_policies": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "Door offline",
                            "enabled": True,
                            "severity": "warning",
                            "match": {"camera_ids": [str(camera_id)]},
                            "action": {
                                "notification_target_ids": [source_notification_id]
                            },
                            "cooldown_seconds": 60,
                        }
                    ],
                }
            ),
        )
        policy = session.query(AlertPolicy).filter_by(name="Door offline").one()
        assert policy.match_json["camera_ids"] == [str(camera_id)]
        assert policy.action_json["notification_target_ids"] == [
            str(notification_id)
        ]
        policy_id = policy.id

    assert ("alert_policy", "created", str(policy_id)) in [
        (item.resource_type, item.action, item.target_id)
        for item in result.applied
    ]
    assert result.skipped == ()


def test_alert_policy_matches_existing_name_when_source_id_differs(
    settings: Settings, database: Any
) -> None:
    from app.modules.alerts.models import AlertPolicy

    with database.session() as session:
        existing = AlertPolicy(
            name="Door offline",
            enabled=False,
            severity="info",
            match_json={},
            action_json={},
            cooldown_seconds=0,
        )
        session.add(existing)
        session.flush()
        target_id = existing.id
        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "alert_policies": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "Door offline",
                            "enabled": True,
                            "severity": "critical",
                            "match": {},
                            "action": {},
                            "cooldown_seconds": 120,
                        }
                    ]
                }
            ),
        )
        assert existing.enabled is True
        assert existing.severity == "critical"
        assert existing.cooldown_seconds == 120
        assert session.query(AlertPolicy).count() == 1

    assert ("alert_policy", "updated", str(target_id)) in [
        (item.resource_type, item.action, item.target_id)
        for item in result.applied
    ]


def test_unmatched_rclone_target_is_skipped_without_creating_credentials(
    settings: Settings, database: Any
) -> None:
    document = bundle(
        sections={
            "storage_targets": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "Remote archive",
                    "type": "rclone",
                    "role": "archive",
                    "enabled": True,
                    "config": {},
                }
            ]
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [(item.resource_type, item.reason) for item in result.skipped] == [
        ("storage_target", "credential_required")
    ]


def test_recording_resources_wait_for_their_camera_mapping(
    settings: Settings, database: Any
) -> None:
    camera_id = str(uuid.uuid4())
    document = bundle(
        sections={
            "cameras": {"cameras": [{"id": camera_id, "name": "Entrance"}]},
            "recording": {
                "retention_policies": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Entrance retention",
                        "scope_type": "CAMERA",
                        "scope_id": camera_id,
                    }
                ],
                "policies": [
                    {"id": str(uuid.uuid4()), "camera_id": camera_id}
                ],
            },
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert [
        (item.resource_type, item.reason)
        for item in result.skipped
        if item.resource_type in {"retention_policy", "recording_policy"}
    ] == [
        ("retention_policy", "scope_dependency_unmapped"),
        ("recording_policy", "camera_unmapped"),
    ]


def test_retention_policy_matches_existing_scope_when_id_and_name_differ(
    settings: Settings, database: Any
) -> None:
    from sqlalchemy import select

    from app.modules.recordings.models import RetentionPolicy
    from app.modules.storage.retention_admin import RetentionPolicyAdminService

    source_id = str(uuid.uuid4())
    with database.session() as session:
        existing = RetentionPolicyAdminService.create(
            session,
            name="Local retention",
            scope_type="GLOBAL",
            scope_id=None,
            ordinary_keep_days=7,
            event_keep_days=14,
            manual_keep_days=21,
            mode="BEST_EFFORT",
            require_archive_before_delete=False,
            enabled=True,
        )
        target_id = existing.id
        document = bundle(
            sections={
                "recording": {
                    "retention_policies": [
                        {
                            "id": source_id,
                            "name": "Imported retention",
                            "scope_type": "GLOBAL",
                            "scope_id": None,
                            "ordinary_keep_days": 30,
                            "event_keep_days": 45,
                            "manual_keep_days": 60,
                            "mode": "HARD",
                            "require_archive_before_delete": True,
                            "enabled": False,
                        }
                    ]
                }
            }
        )

        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        session.commit()

    with database.session() as session:
        policies = list(session.scalars(select(RetentionPolicy)))

    assert [(item.resource_type, item.action, item.target_id) for item in result.applied] == [
        ("retention_policy", "updated", str(target_id))
    ]
    assert len(policies) == 1
    assert policies[0].id == target_id
    assert policies[0].name == "Imported retention"
    assert (policies[0].ordinary_keep_days, policies[0].mode, policies[0].enabled) == (
        30, "HARD", False
    )


def test_recording_policy_uses_mapped_retention_id(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.models import Camera
    from app.modules.recordings.models import RecordingPolicy
    from app.modules.storage.retention_admin import RetentionPolicyAdminService

    source_retention_id = str(uuid.uuid4())
    with database.session() as session:
        camera = Camera(channel_key="main", name="Door")
        session.add(camera)
        session.flush()
        local_retention = RetentionPolicyAdminService.create(
            session,
            name="Local retention",
            scope_type="GLOBAL",
            scope_id=None,
            ordinary_keep_days=7,
            event_keep_days=14,
            manual_keep_days=21,
            mode="BEST_EFFORT",
            require_archive_before_delete=False,
            enabled=True,
        )
        camera_id = camera.id
        local_retention_id = local_retention.id
        document = bundle(
            sections={
                "cameras": {"cameras": [{"id": str(camera_id), "name": "Door"}]},
                "recording": {
                    "retention_policies": [
                        {
                            "id": source_retention_id,
                            "name": "Imported retention",
                            "scope_type": "GLOBAL",
                            "scope_id": None,
                            "ordinary_keep_days": 30,
                            "event_keep_days": 45,
                            "manual_keep_days": 60,
                            "mode": "HARD",
                            "require_archive_before_delete": True,
                            "enabled": True,
                        }
                    ],
                    "policies": [
                        {
                            "id": str(uuid.uuid4()),
                            "camera_id": str(camera_id),
                            "baseline_mode": "continuous",
                            "schedule": {},
                            "schedule_timezone": None,
                            "event_recording_enabled": True,
                            "event_filter": {},
                            "segment_target_seconds": 300,
                            "pre_roll_seconds": 10,
                            "post_roll_seconds": 20,
                            "storage_target_id": None,
                            "retention_policy_id": source_retention_id,
                            "enabled": True,
                        }
                    ],
                },
            }
        )

        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        session.commit()

    with database.session() as session:
        policy = session.query(RecordingPolicy).filter_by(camera_id=camera_id).one()

    assert policy.retention_policy_id == local_retention_id
    assert ("retention_policy", "updated") in [
        (item.resource_type, item.action) for item in result.applied
    ]
    assert ("recording_policy", "updated") in [
        (item.resource_type, item.action) for item in result.applied
    ]
    assert result.camera_ids_to_reconcile == (camera_id,)


def test_recording_policy_creates_matches_and_reconciles_field_changes(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.models import Camera
    from app.modules.recordings.models import RecordingPolicy

    with database.session() as session:
        camera = Camera(channel_key="main", name="Door")
        session.add(camera)
        session.flush()
        camera_id = camera.id
        document = bundle(
            sections={
                "cameras": {"cameras": [{"id": str(camera_id), "name": "Door"}]},
                "recording": {
                    "policies": [
                        {
                            "id": str(uuid.uuid4()),
                            "camera_id": str(camera_id),
                            "baseline_mode": "continuous",
                            "schedule": {},
                            "schedule_timezone": None,
                            "event_recording_enabled": True,
                            "event_filter": {},
                            "segment_target_seconds": 300,
                            "pre_roll_seconds": 10,
                            "post_roll_seconds": 20,
                            "storage_target_id": None,
                            "retention_policy_id": None,
                            "enabled": True,
                        }
                    ]
                },
            }
        )
        first = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        session.commit()

    with database.session() as session:
        policy = session.query(RecordingPolicy).filter_by(camera_id=camera_id).one()
        assert policy.event_recording_enabled is True
        assert (policy.pre_roll_seconds, policy.post_roll_seconds) == (10, 20)
        repeated = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        session.commit()

    document["sections"]["recording"]["policies"][0]["pre_roll_seconds"] = 15
    with database.session() as session:
        changed = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )
        session.commit()

    with database.session() as session:
        policy = session.query(RecordingPolicy).filter_by(camera_id=camera_id).one()

    assert ("recording_policy", "updated") in [
        (item.resource_type, item.action) for item in first.applied
    ]
    assert first.camera_ids_to_reconcile == (camera_id,)
    assert ("recording_policy", "matched") in [
        (item.resource_type, item.action) for item in repeated.applied
    ]
    assert repeated.camera_ids_to_reconcile == ()
    assert policy.pre_roll_seconds == 15
    assert ("recording_policy", "updated") in [
        (item.resource_type, item.action) for item in changed.applied
    ]
    assert changed.camera_ids_to_reconcile == (camera_id,)


def test_role_camera_scope_waits_for_camera_mapping(
    settings: Settings, database: Any
) -> None:
    camera_id = str(uuid.uuid4())
    document = bundle(
        sections={
            "roles": [
                {
                    "id": "operator-role",
                    "name": "Operator",
                    "permissions": [],
                    "camera_scope": {
                        "mode": "selected",
                        "camera_ids": [camera_id],
                    },
                }
            ],
            "cameras": {"cameras": [{"id": camera_id, "name": "Door"}]},
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert ("role_camera_scope", "camera_scope_dependency_unmapped") in [
        (item.resource_type, item.reason) for item in result.skipped
    ]


def test_camera_group_waits_for_member_mapping(
    settings: Settings, database: Any
) -> None:
    camera_id = str(uuid.uuid4())
    group_id = str(uuid.uuid4())
    document = bundle(
        sections={
            "cameras": {
                "cameras": [{"id": camera_id, "name": "Door"}],
                "groups": [{"id": group_id, "name": "Lobby"}],
                "group_members": [
                    {"camera_group_id": group_id, "camera_id": camera_id}
                ],
            }
        }
    )

    with database.session() as session:
        result = ConfigurationImportService.apply(
            session, settings=settings, bundle=document
        )

    assert ("camera_group", "camera_or_parent_unmapped") in [
        (item.resource_type, item.reason) for item in result.skipped
    ]


def test_camera_group_maps_parent_before_child_and_preserves_members(
    settings: Settings, database: Any
) -> None:
    from app.modules.cameras.groups import CameraGroupService
    from app.modules.cameras.models import Camera, CameraGroup

    source_parent_id = str(uuid.uuid4())
    source_child_id = str(uuid.uuid4())
    with database.session() as session:
        camera = Camera(channel_key="main", name="Door")
        parent = CameraGroup(name="Exterior", description="Old")
        session.add_all([camera, parent])
        session.flush()
        camera_id = camera.id
        parent_id = parent.id

        result = ConfigurationImportService.apply(
            session,
            settings=settings,
            bundle=bundle(
                sections={
                    "cameras": {
                        "cameras": [{"id": str(camera_id), "name": "Door"}],
                        "groups": [
                            {
                                "id": source_child_id,
                                "name": "Entry",
                                "parent_id": source_parent_id,
                            },
                            {
                                "id": source_parent_id,
                                "name": "Exterior",
                                "description": "Updated",
                            },
                        ],
                        "group_members": [
                            {
                                "camera_group_id": source_child_id,
                                "camera_id": str(camera_id),
                            }
                        ],
                    }
                }
            ),
        )
        child = session.query(CameraGroup).filter_by(name="Entry").one()
        assert child.parent_id == parent_id
        assert CameraGroupService.camera_ids(session, child.id) == [camera_id]
        assert parent.description == "Updated"
        child_id = child.id

    assert [
        (item.action, item.target_id)
        for item in result.applied
        if item.resource_type == "camera_group"
    ] == [("updated", str(parent_id)), ("created", str(child_id))]
    assert result.skipped == ()


# --- apply over HTTP --------------------------------------------------------


ADMIN_PASSWORD = "correct-horse-battery-staple"


def test_the_apply_endpoint_answers_400_not_500_for_a_malformed_id(
    tmp_path: Path,
) -> None:
    """The user-visible claim: a bad id is a validation error, not a server fault.

    Before the fix this request produced a 500, because the ValueError raised
    while parsing the id escaped the handler.
    """
    app = make_test_app(
        tmp_path,
        secret_key="configuration-import-test-secret-key-32-bytes",
        database_url=f"sqlite:///{tmp_path / 'config-import.db'}",
    )

    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/setup/administrator",
                json={
                    "username": "admin",
                    "display_name": "Administrator",
                    "email": "admin@example.com",
                    "password": ADMIN_PASSWORD,
                },
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": ADMIN_PASSWORD},
            ).status_code
            == 200
        )

        response = client.post(
            "/api/v1/system/configuration/import/apply",
            json={
                "bundle": bundle(
                    sections={
                        "storage_targets": [
                            {
                                "id": "local",
                                "name": "Archive",
                                "kind": "local",
                                "config": {"path": "/srv/x"},
                            }
                        ]
                    }
                )
            },
        )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"]["code"] == "configuration_import_invalid"
    assert body["error"]["details"] == {"id": "local"}
