from __future__ import annotations

import os


# app.main intentionally requires a deployment secret at import time. Tests use
# an explicit non-production key rather than weakening the production contract.
os.environ.setdefault(
    "ZERO_NVR_SECRET_KEY",
    "zero-nvr-test-secret-key-32-bytes-minimum",
)
