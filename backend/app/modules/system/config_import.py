"""Public configuration import service.

Validation, application, and common bundle rules live in focused modules; the
facade retains the existing API for system endpoints and other callers.
"""

from .config_import_apply import _ImportApply
from .config_import_support import (
    CredentialRequirement,
    ConfigurationApplyItem,
    ConfigurationApplyResult,
    ConfigurationValidation,
    _ImportSupport,
)
from .config_import_validation import _ImportValidation


class ConfigurationImportService(_ImportSupport, _ImportValidation, _ImportApply):
    """Validate and apply a configuration bundle."""
