#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

repo_dir="$tmp/repo"
fake_bin="$tmp/bin"
docker_log="$tmp/docker.log"
mkdir -p "$repo_dir/scripts" "$fake_bin"

cp "$ROOT_DIR/scripts/lib.sh" "$repo_dir/scripts/lib.sh"
cp "$ROOT_DIR/scripts/deployment-state.sh" "$repo_dir/scripts/deployment-state.sh"
cp "$ROOT_DIR/scripts/artifact-pins.sh" "$repo_dir/scripts/artifact-pins.sh"

cat > "$repo_dir/.env" <<EOF
ZERO_NVR_DATA_PATH=$repo_dir/data
ZERO_NVR_IMAGE=zero-nvr:test
COMPOSE_PROFILES=
EOF
cat > "$repo_dir/docker-compose.yml" <<'EOF'
services:
  zero-nvr:
    image: zero-nvr:test
EOF

git -C "$repo_dir" init -q
git -C "$repo_dir" config user.email "artifact-pin@example.invalid"
git -C "$repo_dir" config user.name "artifact pin test"
printf 'one\n' > "$repo_dir/file.txt"
git -C "$repo_dir" add file.txt
git -C "$repo_dir" commit -qm one
rev_one="$(git -C "$repo_dir" rev-parse HEAD)"
printf 'two\n' >> "$repo_dir/file.txt"
git -C "$repo_dir" commit -qam two

cat > "$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${FAKE_DOCKER_LOG:?}"
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
args="$*"
case "$args" in
  *" ps -q zero-nvr")
    printf '%s\n' "container-zero-nvr"
    ;;
  "container inspect container-zero-nvr --format {{.Image}}")
    printf 'sha256:%064d\n' 1
    ;;
  "image inspect "*)
    exit 0
    ;;
  "tag "*|"image rm "*)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
chmod +x "$fake_bin/docker"

export PATH="$fake_bin:$PATH"
export FAKE_DOCKER_LOG="$docker_log"
export ZERO_NVR_ENV_FILE="$repo_dir/.env"

(
  cd "$repo_dir"
  . "$repo_dir/scripts/lib.sh"
  . "$repo_dir/scripts/deployment-state.sh"
  . "$repo_dir/scripts/artifact-pins.sh"

  pin_git_revision pending "$rev_one"
  [[ "$(git rev-parse refs/zero-nvr/pins/pending)" == "$rev_one" ]]

  image_ref="$(pin_active_core_image pending "$rev_one")"
  expected="zero-nvr:pin-pending-$(printf '%s' "$rev_one" | cut -c1-12)"
  [[ "$image_ref" == "$expected" ]]
  artifact_image_exists "$image_ref"

  rollback_ref="$(pin_image_source rollback "$rev_one" "$image_ref")"
  [[ "$rollback_ref" == "zero-nvr:pin-rollback-$(printf '%s' "$rev_one" | cut -c1-12)" ]]
  pin_git_revision rollback "$rev_one"
  [[ "$(git rev-parse refs/zero-nvr/pins/rollback)" == "$rev_one" ]]

  remove_artifact_image "$image_ref"
  clear_git_pin pending
  if git show-ref --verify --quiet refs/zero-nvr/pins/pending; then
    echo "pending Git pin was not cleared" >&2
    exit 1
  fi
)

grep -Fq "tag sha256:" "$docker_log"
grep -Fq "zero-nvr:pin-pending-" "$docker_log"
grep -Fq "zero-nvr:pin-rollback-" "$docker_log"

echo "artifact pins: ok"
