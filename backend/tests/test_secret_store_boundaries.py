from __future__ import annotations

import ast
from pathlib import Path


APP_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
)
ALLOWED = {
    Path("modules/auth/models.py"),
    Path("core/security/secret_store.py"),
}


def test_application_uses_secret_store_persistence_boundary() -> None:
    offenders: list[str] = []

    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(APP_ROOT)
        if relative in ALLOWED:
            continue

        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "app.modules.auth.models":
                continue
            if any(
                alias.name == "SecretRecord"
                for alias in node.names
            ):
                offenders.append(
                    str(relative)
                )
                break

    assert offenders == [], (
        "Application code must use the SecretStore persistence "
        "boundary instead of importing SecretRecord directly: "
        + ", ".join(sorted(offenders))
    )
