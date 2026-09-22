from __future__ import annotations

import ast
from pathlib import Path


MODULE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
)


def test_business_modules_do_not_import_secret_record_directly() -> None:
    offenders: list[str] = []

    for path in MODULE_ROOT.rglob("*.py"):
        if path == MODULE_ROOT / "auth" / "models.py":
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
                    str(path.relative_to(MODULE_ROOT))
                )
                break

    assert offenders == [], (
        "Business modules must use the SecretStore persistence "
        "boundary instead of importing SecretRecord directly: "
        + ", ".join(sorted(offenders))
    )
