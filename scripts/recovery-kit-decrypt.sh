#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

kit="${1:-}"
output="${2:-$ROOT_DIR/recovery-kit-restored}"

if [[ -z "$kit" ]]; then
  echo "error: RecoveryKit .znrk path is required" >&2
  exit 2
fi
if [[ ! -f "$kit" ]]; then
  echo "error: RecoveryKit file not found: $kit" >&2
  exit 1
fi

require_command docker
docker info >/dev/null

kit_dir="$(CDPATH= cd -- "$(dirname -- "$kit")" && pwd)"
kit_name="$(basename -- "$kit")"
mkdir -p "$output"
chmod 700 "$output"
output_dir="$(CDPATH= cd -- "$output" && pwd)"

image="zero-nvr-recovery-kit:local"
echo "Building zero-nvr RecoveryKit helper image..."
docker build   --file "$ROOT_DIR/backend/Dockerfile"   --tag "$image"   "$ROOT_DIR"

if ! exec 3<>/dev/tty 2>/dev/null; then
  echo "error: RecoveryKit decryption requires an interactive terminal" >&2
  exit 1
fi

passphrase=""
confirmation=""
IFS= read -r -s -p "RecoveryKit passphrase: " passphrase <&3
printf '\n' >&3
IFS= read -r -s -p "Confirm passphrase: " confirmation <&3
printf '\n' >&3
exec 3>&-

if [[ -z "$passphrase" ]]; then
  echo "error: RecoveryKit passphrase is required" >&2
  exit 1
fi
if [[ "$passphrase" != "$confirmation" ]]; then
  echo "error: RecoveryKit passphrases do not match" >&2
  exit 1
fi

printf '%s\n' "$passphrase" | docker run --rm -i   --mount "type=bind,src=$kit_dir,dst=/recovery-input,readonly"   --mount "type=bind,src=$output_dir,dst=/recovery-output"   "$image"   python -m app.recovery_kit_cli     --kit "/recovery-input/$kit_name"     --output /recovery-output

unset passphrase confirmation

echo "RecoveryKit decrypted to: $output_dir"
echo "Review the files, then on a clean host:"
echo "  cp '$output_dir/zero-nvr.env' '$ROOT_DIR/.env'"
echo "  cp '$output_dir/recovery.env' '$ROOT_DIR/deploy/recovery.env'"
echo "  chmod 600 '$ROOT_DIR/.env' '$ROOT_DIR/deploy/recovery.env'"
echo "  ./deploy.sh restore list"
