from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.modules.backups.recovery_kit import (
    RecoveryKitService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.recovery_kit_cli"
    )
    parser.add_argument(
        "--kit",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--force",
        action="store_true",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    passphrase = sys.stdin.readline().rstrip(
        "\r\n"
    )
    if not passphrase:
        print(
            "error: RecoveryKit passphrase is required on stdin",
            file=sys.stderr,
        )
        return 2

    try:
        content = args.kit.read_bytes()
        written = RecoveryKitService.extract(
            content,
            passphrase=passphrase,
            destination=args.output,
            overwrite=args.force,
        )
    except Exception as exc:
        print(
            f"error: {exc}",
            file=sys.stderr,
        )
        return 1

    for path in written:
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
