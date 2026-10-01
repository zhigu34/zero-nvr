"""Validate the configuration envelope before reading section shapes."""

from __future__ import annotations

from typing import Any

from .config_import_support import _KNOWN_SECTIONS


def read_envelope_sections(
    service: type,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    if bundle.get("format") != (
        "zero-nvr.configuration"
    ):
        raise service._error(
            "configuration_import_format_invalid",
            "Configuration import format is not supported.",
        )
    if bundle.get("format_version") != 1:
        raise service._error(
            "configuration_import_version_unsupported",
            "Configuration import version is not supported.",
            details={
                "format_version": (
                    bundle.get("format_version")
                )
            },
        )
    if bundle.get("secrets_included") is not False:
        raise service._error(
            "configuration_import_secrets_not_allowed",
            "Configuration import must not contain secret material.",
        )

    service._reject_secret_fields(bundle)

    sections = service._mapping(
        bundle.get("sections"),
        path="$.sections",
    )
    unknown = set(sections) - _KNOWN_SECTIONS
    if unknown:
        raise service._error(
            "configuration_import_section_unsupported",
            "Configuration import contains unsupported sections.",
            details={
                "sections": sorted(
                    str(item)
                    for item in unknown
                )
            },
        )

    return sections
