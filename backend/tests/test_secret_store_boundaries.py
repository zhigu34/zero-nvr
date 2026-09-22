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
    record_imports: list[str] = []
    crypto_bypasses: list[str] = []
    in_place_replacements: list[str] = []
    crypto_methods = {
        "encrypt_bytes",
        "decrypt_bytes",
        "encrypt_json",
        "decrypt_json",
        "rotate",
    }

    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(APP_ROOT)
        if relative in ALLOWED:
            continue

        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and any(
                    alias.name == "SecretRecord"
                    for alias in node.names
                )
            ):
                record_imports.append(str(relative))
                break

        if any(
            isinstance(node, ast.Attribute)
            and node.attr in crypto_methods
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "secret_store"
            for node in ast.walk(tree)
        ):
            crypto_bypasses.append(str(relative))

        if any(
            isinstance(node, ast.Attribute)
            and node.attr == "replace_json"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "secret_store"
            for node in ast.walk(tree)
        ):
            in_place_replacements.append(str(relative))

    assert record_imports == [], (
        "Application code must use the SecretStore persistence "
        "boundary instead of importing SecretRecord directly: "
        + ", ".join(sorted(record_imports))
    )
    assert crypto_bypasses == [], (
        "Application code must use SecretStore CRUD instead of "
        "calling its crypto primitives directly: "
        + ", ".join(sorted(crypto_bypasses))
    )
    assert in_place_replacements == [], (
        "Recoverable business credentials must switch secret_ref "
        "to a staged SecretRecord instead of mutating the current "
        "record in place: "
        + ", ".join(sorted(in_place_replacements))
    )
