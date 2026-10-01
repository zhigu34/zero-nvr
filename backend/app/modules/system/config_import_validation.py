"""Orchestrate import preflight without accessing the database.

The public service combines this mixin with the application flow so callers
retain ``ConfigurationImportService.validate`` and ``apply``.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings

from .config_import_support import ConfigurationValidation
from .config_import_document import parse_bundle
from .config_import_references import validate_references
from .config_import_summary import summarize_bundle


class _ImportValidation:
    """Preflight: what a bundle contains and whether it can be applied."""

    @classmethod
    def validate(
        cls,
        bundle: dict[str, Any],
        *,
        settings: Settings,
    ) -> ConfigurationValidation:
        parsed = parse_bundle(cls, bundle, settings=settings)
        validate_references(cls, parsed)

        return summarize_bundle(cls, parsed, bundle, settings=settings)
