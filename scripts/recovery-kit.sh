#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

output="${1:-$ROOT_DIR/recovery-kit}"
policy="${2:-}"

mkdir -p "$output"
chmod 700 "$output"

cp "$ENV_FILE" "$output/zero-nvr.env"
chmod 600 "$output/zero-nvr.env"

tmp="$(mktemp "$output/.recovery.env.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

args=(python -m app.cli recovery-env)
if [[ -n "$policy" ]]; then
  args+=(--policy "$policy")
fi

compose run --rm --no-deps -T zero-nvr "${args[@]}" > "$tmp"

grep -E '^(#|[A-Z][A-Z0-9_]*=)' "$tmp" > "$output/recovery.env"
chmod 600 "$output/recovery.env"

if ! grep -q '^RESTIC_REPOSITORY=' "$output/recovery.env" \
  || ! grep -q '^RESTIC_PASSWORD=' "$output/recovery.env"; then
  echo "error: RecoveryKit restic bootstrap export is incomplete" >&2
  rm -f "$output/recovery.env"
  exit 1
fi

cat > "$output/README.txt" <<'EOF'
zero-nvr RecoveryKit
====================

Keep this directory OFF the zero-nvr host and protect it like a password vault.

Contents:
- zero-nvr.env
  Preserves ZERO_NVR_SECRET_KEY, ZLM secrets, and deployment bootstrap settings.
- recovery.env
  Restic repository/password/backend credentials used to retrieve disaster backups.

Clean-host restore:
1. Clone/check out the intended zero-nvr version.
2. Copy zero-nvr.env to the repo root as .env:
     cp /path/to/RecoveryKit/zero-nvr.env .env
3. Copy recovery.env to deploy/recovery.env:
     cp /path/to/RecoveryKit/recovery.env deploy/recovery.env
4. Inspect available snapshots:
     ./deploy.sh restore list
5. Restore only after selecting the correct snapshot:
     ./deploy.sh restore latest --force

The restore workflow never deletes or replaces /recordings.
EOF
chmod 600 "$output/README.txt"

echo "RecoveryKit exported to: $output"
echo "Store it off-host. It contains the master encryption key and backup credentials."
