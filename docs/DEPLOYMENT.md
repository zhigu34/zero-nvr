# Deployment Architecture

Status: **V1 Architecture Frozen — implementation and deployment-test hardening in progress**

This document defines the supported deployment model for zero-nvr.

## Primary interface

The normal operator workflow is based on:

```text
deploy.sh
.env
docker compose
Docker Compose profiles
```

The deployment script is part of the product interface, not a temporary bootstrap helper.

## Core stack

Default local NVR without AI:

```text
zero-nvr          # FastAPI + built Vue assets
zero-nvr-worker   # same image, different command
zlmediakit        # independent media service
```

This is:

- 2 images;
- 3 containers.

The shared zero-nvr image includes the small CLI/library toolchain needed by the API/worker:

- FFmpeg / ffprobe
- rclone
- restic
- Apprise
- ONVIF / WS-Discovery client libraries
- auth/OIDC libraries

Only the worker normally invokes long-running or resource-heavy CLI jobs.

## Optional managed services

Add containers only when the user enables a capability that requires an independently running service.

Examples:

```text
AI_MODE=managed-frigate       -> + Frigate
MQTT_MODE=managed             -> + Mosquitto
OPENLIST_MODE=managed         -> + OpenList
DATABASE=postgres
POSTGRES_MODE=managed         -> + PostgreSQL
```

External mode does not add a local container.

## No eager pulls

Disabled features must not cause their images to be pulled or containers to be started.

Compose profiles should map deployment features to their independent services. The core services remain profile-independent.

### Build-source and restricted-network behavior

The Core build follows the same local-first pattern used by camera-recorder:

- `node:22-alpine` and `python:3.12-slim` are the default build bases;
- a matching local base image is reused without an explicit deploy-time pull;
- image builds pin Docker Buildx to the local `default` builder (matching
  camera-recorder), and Compose uses `--builder default` when supported;
- when a base image is missing, `DEPLOY_AUTO_PULL=1` allows an explicit pull;
- `DEPLOY_AUTO_PULL=0` supports offline/preloaded hosts using `docker save` / `docker load`;
- `ZERO_NVR_NODE_BASE_IMAGE` and `ZERO_NVR_PYTHON_BASE_IMAGE` may point at operator-controlled registries;
- on the first interactive install, when `.env` does not yet exist, the
  deployment script asks once which build-source policy to save; Enter accepts
  the recommended `auto` mode, while non-interactive/CI installs use
  `auto` without blocking;
- existing `.env` files are never re-prompted;
- Debian, PyPI and npm package sources support
  `ZERO_NVR_BUILD_SOURCE_MODE=auto|official|cn|custom`;
- `auto` is the deployment default: it probes the official Debian/PyPI/npm
  endpoints first, keeps them when they are healthy, and compares the
  mainland-China mirrors when the official group is unavailable or slow;
- `cn` selects Tsinghua Debian/PyPI plus npmmirror; `official` disables
  automatic switching; `custom` uses `DEBIAN_MIRROR`,
  `DEBIAN_SECURITY_MIRROR`, `PYPI_INDEX_URL` and `NPM_REGISTRY`;
- the Debian override automatically falls back to the image's original
  official sources if the selected mirror cannot be reached;
- the frontend npm install uses the selected registry first, but if a
  non-official registry returns unusable/incomplete package metadata or the
  install fails, the build clears that npm cache and retries once against
  `https://registry.npmjs.org` instead of enabling
  `--legacy-peer-deps`.

This is connectivity-based rather than geolocation-based, so VPNs, proxies,
private lines and overseas hosts are not classified from an IP-country guess.
The Dockerfile itself keeps official upstream defaults so CI and direct
`docker build` remain portable. A forced/custom mainland-China profile may
use the same mirror values proven by camera-recorder:

~~~env
DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
PYPI_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
NPM_REGISTRY=https://registry.npmmirror.com
~~~

The repository does not hard-code an untrusted public Docker Hub proxy. If
Docker Hub authentication is unreachable, either point the configurable base
image variables at a trusted registry or preload the exact images and set
`DEPLOY_AUTO_PULL=0`.

## Configuration responsibility

```text
.env / deploy.sh / Compose profile
    -> whether a deployment capability exists

zero-nvr UI + database
    -> whether the product feature is configured/enabled
```

Examples:

- External Frigate can be configured entirely in the UI once connectivity exists.
- Managed Frigate requires the deployment feature to be enabled first.
- SMTP, OIDC, external MQTT, external OpenList, retention, alerts, and camera policies do not require new containers.

For managed ZLMediaKit, zero-nvr generates the small owned configuration overlay from product/deployment settings rather than asking users to hand-edit the container. The V1 generated baseline explicitly includes:

~~~ini
[record]
enableFmp4=1
~~~

together with the zero-nvr API/hook secret and required hook URLs. The image's remaining upstream defaults are preserved unless zero-nvr owns a documented setting.

## Docker security boundary

The web/API container does not require unrestricted access to `/var/run/docker.sock`.

If the user enables a missing managed feature, the UI should show an actionable command such as:

```bash
./deploy.sh feature enable frigate
```

The deployment script performs the Compose operation. Supported managed deployment profiles are:

```text
frigate   -> Frigate 0.18.0
mqtt      -> Eclipse Mosquitto 2.1.2
openlist  -> OpenList 4.2.6
postgres  -> PostgreSQL 17.11
```

Image references are configurable through `.env`, but the shipped defaults are version-pinned. Disabled profiles are not started or pulled by normal core install/update flows.

## Expected deploy.sh surface

The command grammar may evolve, but the product needs these workflows:

```text
install
update
rollback [version]
status
doctor
benchmark <8|16>
soak <8|16>
feature list
feature enable <name>
feature disable <name>
feature restart <name>
admin reset-password
secret rotate
backup
restore
```

### master secret bootstrap and rotation

The product encryption master key is deployment state and must remain stable
across container recreation and upgrades. Configure exactly one of:

```text
ZERO_NVR_SECRET_KEY=<stable secret>
ZERO_NVR_SECRET_KEY_FILE=/path/visible/inside/container
```

For the default Compose deployment, a protected file can live below the
persisted `ZERO_NVR_DATA_PATH` host directory and be referenced by its
container path below `/var/lib/zero-nvr`. The file should be readable only by
the deployment/runtime account. The application strips only the final CR/LF;
other key bytes are preserved. Missing, empty, conflicting, or shorter-than-32
byte master-key input fails explicitly rather than generating a replacement at
application startup.

A simple rotation keeps the old key readable while making the new key primary:

```bash
# 1. Take and verify the normal production backup first.
# 2. Put the new value in ZERO_NVR_SECRET_KEY (or its *_FILE).
# 3. Keep the old value temporarily in the JSON keyring:
ZERO_NVR_SECRET_KEY_PREVIOUS='["<old-key>"]'

./deploy.sh secret rotate
```

The command quiesces the API/worker, verifies every `SecretRecord` is
decryptable with the configured keyring, re-encrypts only records not already
on the primary key, verifies the rewritten records, commits atomically, then
force-recreates API/worker and runs the deployment health check. If any record
cannot be decrypted, the transaction is not committed. After a successful
rotation and a verified post-rotation backup, remove keys that are no longer
referenced from `ZERO_NVR_SECRET_KEY_PREVIOUS` and restart the Core services.

### protected external-service bootstrap secrets

Deployment/bootstrap credentials support the same direct-value or protected-file
pattern where they are consumed outside the product SecretStore:

```text
ZERO_NVR_ZLM_API_SECRET / ZERO_NVR_ZLM_API_SECRET_FILE
ZERO_NVR_ZLM_HOOK_SECRET / ZERO_NVR_ZLM_HOOK_SECRET_FILE
ZERO_NVR_TURN_SHARED_SECRET / ZERO_NVR_TURN_SHARED_SECRET_FILE
ZERO_NVR_MQTT_PASSWORD / ZERO_NVR_MQTT_PASSWORD_FILE
ZERO_NVR_POSTGRES_PASSWORD / ZERO_NVR_POSTGRES_PASSWORD_FILE
```

Configure at most one member of each pair. When both are blank, supported
managed services keep their existing deployment behavior and generate a stable
direct value into the protected `.env`. When a `*_FILE` value is configured,
zero-nvr reads the file and does not write a duplicate plaintext value back to
`.env`.

The recommended layout is a host directory below
`ZERO_NVR_DATA_PATH/bootstrap-secrets`, mode-restricted to the deployment
account, with container-visible paths written as
`/var/lib/zero-nvr/bootstrap-secrets/<name>`. Host-side deployment helpers
map that container path back to `ZERO_NVR_DATA_PATH`; API/worker already see
the same persistent data mount. Managed PostgreSQL mounts only this
`bootstrap-secrets` subdirectory read-only and therefore requires its password
file to use that container path prefix.

Camera credentials, OIDC client secrets, rclone credentials, Frigate provider
credentials, notification URLs, and other product-managed credentials are not
bootstrap environment secrets. They remain encrypted behind `SecretStore`
rather than gaining parallel `*_FILE` configuration.

RecoveryKit export resolves configured bootstrap `*_FILE` sources into direct
values inside its protected `zero-nvr.env` and clears the corresponding file
references in the kit copy. The live deployment `.env` is not modified. This
keeps clean-host disaster recovery self-contained even when the normal host
uses protected files.

### install

Current implemented behavior:

- validates Docker, Docker Compose, and Docker daemon availability;
- creates `.env` automatically from `.env.example` when it does not exist;
- sets `.env` permissions to `0600`;
- accepts either `ZERO_NVR_SECRET_KEY` or `ZERO_NVR_SECRET_KEY_FILE`
  for the product master secret and refuses ambiguous dual configuration;
- generates `ZERO_NVR_SECRET_KEY` only when neither master-key input is
  configured, so container recreation never creates a replacement key;
- generates `ZERO_NVR_ZLM_API_SECRET` and `ZERO_NVR_ZLM_HOOK_SECRET`
  when absent;
- creates configured host data/cache/recording directories;
- renders the managed ZLMediaKit configuration;
- builds the zero-nvr image;
- runs schema migration;
- starts the Core stack with Compose health waiting;
- runs the post-start deployment check;
- records the installed Git revision when available.

Implemented deployment-test hardening:

- Core publishes only the browser-facing ports by default: zero-nvr Web/API
  uses `8000/tcp`, including same-origin HLS/fMP4 under `/zlm`, and
  ZLMediaKit WebRTC uses `8001/tcp+udp`;
- ZLMediaKit HTTP/RTSP/RTMP stay on the Docker network and are not published
  as host ports;
- install validates configured host-published Core ports before image
  pull/build/start;
- enabled optional profiles are included in install-time port preflight;
- `feature enable` / `feature restart` validate the relevant optional
  service ports, including the TURN UDP relay range;
- when an interactive TTY is available and a requested port is occupied,
  deploy.sh explains the conflict, suggests an available port, accepts
  operator input, validates it, and persists the selected value into `.env`;
- when no interactive TTY is available, conflicts fail fast with the exact
  environment key/value and a suggested replacement rather than blocking;
- host-port probing covers TCP and UDP, preferring Python socket bind probes
  with an `ss` fallback;
- the rendered Compose model is validated before install pull/build/start and
  before enabling a managed feature;
- a successful install prints the Web UI address, the same-origin `/zlm`
  media path, and the effective WebRTC port.

Deployment CI also runs `scripts/test-clean-install.sh` in an isolated
temporary deployment tree with no pre-existing `.env`. The harness uses a
fake Docker CLI so it can exercise first-install orchestration deterministically
without starting real containers. It verifies env/secret creation, host-path
creation, port/Compose preflight, ZLM rendering, migration/start/check ordering,
and the final access summary. This automated smoke does not replace the
remaining real clean-host installation and real-camera acceptance test.

A second `clean-install` Deployment CI job runs after the static/deployment
validation job on a fresh Ubuntu runner and invokes the real `./deploy.sh
install` against Docker. It verifies the generated `.env`, bootstrap secrets,
default WebRTC port, running API/worker/ZLMediaKit services, API health, schema
compatibility, and install summary, then tears the stack and volumes down.
The real Docker clean-install job has passed and is now part of the required
Deployment CI path. It proves the Core three-container first-install path on a
fresh Ubuntu host class. The only remaining Deployment-test gate is the
target-host real-camera lifecycle: live view, persistent recording, finalized
hook/catalog entry, timeline/playback, then control/media restart and
reconciliation without recreating the Camera.

The CI host is not a substitute for that final target-hardware and real-camera
acceptance run.

The intended install sequence for the deployment-test gate is therefore:

~~~text
Docker/Compose preflight
-> create/validate .env and bootstrap secrets
-> validate host paths
-> validate/resolve published ports
-> validate Compose model
-> pull/build
-> migrate
-> compose up --wait
-> health/readiness check
-> print effective access addresses
~~~

After first deployment on the intended host, the remaining real-camera
acceptance run is deliberately operator-observed rather than simulated:

~~~text
1. add/validate one real ONVIF or RTSP camera;
2. confirm Live produces video in the browser without exposing source credentials;
3. set a persistent recording policy and wait for at least one finalized segment;
4. confirm RecordingSegment + AVAILABLE local RecordingLocation are cataloged;
5. confirm the same interval appears on the timeline and plays back;
6. restart ZLMediaKit, zero-nvr API, and worker through the supported deployment path;
7. confirm the same Camera identity remains, media reconnects, recording resumes,
   and reconciliation does not duplicate or lose the finalized segment.
~~~

The supported evidence helper turns the same flow into a two-phase host test
without replacing the required visual checks:

~~~bash
./deploy.sh camera-acceptance prepare <camera-id>
# Confirm browser Live and timeline playback for the baseline finalized segment.
./deploy.sh camera-acceptance restart <camera-id>
# Wait for the next normal recording segment to finalize.
./deploy.sh camera-acceptance verify <camera-id> \
  --live-confirmed --playback-confirmed
~~~

`prepare` requires the exact Camera to be enabled, non-retired, in persistent
recording mode, RECORD-online, MP4-recording, and to already have a non-empty
FINAL local segment produced by the normal hook path
(`NEXT_SEGMENT_BOUNDARY` or `EXPLICIT_STOP`, never `RECOVERY`). It stores
the baseline segment/location identity under
`<ZERO_NVR_DATA_PATH>/release-validation/real-camera-<camera-id>.json`.

`restart` first requires that baseline evidence, restarts ZLMediaKit and both
zero-nvr control containers, waits for Core health, and records the completed
restart time. `verify` then requires explicit operator confirmation of browser
Live and timeline playback, rechecks the same Camera identity and active
persistent recorder, proves the baseline segment/location still exists without
a duplicate source/timestamp identity, and requires a new FINAL local
hook-produced segment created after the restart.

Do not mark the Deployment-test gate complete from synthetic sources alone; the
last item exists specifically to expose real camera/network/codec/filesystem
behavior that CI cannot reproduce.

### update

Supported forms are:

~~~bash
./deploy.sh update
./deploy.sh update <version-or-ref>
./deploy.sh update <version-or-ref> --backup-policy <id-or-name>
~~~

Without a version/ref, update preserves the existing source-checkout workflow. With a version/ref, zero-nvr resolves the locally available Git ref to an immutable commit before any deployment mutation. It does not automatically fetch from a remote.

For a version-pinned update it:

- requires a clean tracked Git worktree;
- resolves the requested ref to an immutable commit;
- stages that commit in a temporary Git worktree;
- validates the target Compose model;
- stage-builds the target zero-nvr image before touching the running control plane;
- creates the local and, in production, verified restic pre-upgrade safety points;
- records the pending target/previous revision/snapshot;
- switches the source checkout to the immutable target commit;
- applies the staged image and target deployment configuration;
- runs explicit schema migration;
- restarts affected services and verifies health;
- records the deployed and rollback revisions.

The requested ref must already exist in the local clone. When a deployed revision is recorded, the pinned target must be that revision or one of its Git descendants; arbitrary non-fast-forward downgrades are rejected and must use the recorded `rollback` path. Operators may fetch release tags/branches first, but `deploy.sh update` itself does not silently change remote Git state.

Do not treat mutable `latest` as the production upgrade contract.

### rollback

A successful install records the immutable Git revision that produced the running control plane. A successful update records:

- the newly deployed revision;
- the immediately previous deployed revision;
- the verified local pre-upgrade database safety snapshot.

The supported command is:

~~~bash
./deploy.sh rollback
./deploy.sh rollback <recorded-previous-revision-or-ref>
~~~

The optional version/ref must resolve to the exact recorded previous deployment revision. Arbitrary historical downgrades are intentionally rejected because zero-nvr cannot assume an unrelated schema/config rollback path is safe.

Rollback sequencing is:

1. require a clean tracked source worktree and the recorded rollback state;
2. stage-build the recorded previous revision before mutating the running installation;
3. preserve the current zero-nvr image under a temporary recovery tag;
4. create a fresh pre-rollback database safety snapshot;
5. stop only zero-nvr API/worker; ZLMediaKit is left running;
6. restore the recorded pre-upgrade database safety snapshot;
7. switch to the recorded previous source revision and staged image;
8. start API/worker and run health checks;
9. on failure, attempt to restore the pre-rollback revision/image/database.

Recording media is never modified by this rollback path.

If an update exits after its rollback point has been recorded but before health validation succeeds, deployment state remains marked pending. `./deploy.sh rollback` recognizes that state and restores the pre-update revision/database.

Automatic version rollback becomes available only after deployment-state support has recorded a known previous revision. An installation upgraded from an older release with no deployment state may require one successful state-aware install/update before version rollback can be automated.

Local safety snapshots live under the zero-nvr data directory and are restored only through the host-local CLI. The restore command rejects paths outside `safety-backups`, takes another rollback-of-rollback database snapshot first, and never touches `/recordings`.

### feature

Managed service lifecycle is explicit:

```bash
./deploy.sh feature list
./deploy.sh feature enable frigate
./deploy.sh feature enable mqtt
./deploy.sh feature enable openlist
./deploy.sh feature enable postgres
./deploy.sh feature restart frigate
./deploy.sh feature disable mqtt
```

The command edits only `COMPOSE_PROFILES` plus feature-specific bootstrap secrets/configuration, then targets that service. Disabling a feature removes its container but retains persistent data.

Managed PostgreSQL startup does not silently switch an existing SQLite deployment to PostgreSQL. Database-engine migration remains a separate, explicit workflow. When the active `ZERO_NVR_DATABASE_URL` points at the managed Compose `postgres` service, `feature disable postgres` refuses to stop that service until the active database is switched away, preventing an operator action from disconnecting the running control plane from its database.

### database engine migration

SQLite -> PostgreSQL remains an explicit guarded operation:

```bash
./deploy.sh database migrate postgres
```

PostgreSQL -> SQLite is intentionally stricter:

```bash
./deploy.sh database migrate sqlite
./deploy.sh database migrate sqlite --confirm-sqlite-workload
```

The first command runs the reverse-migration preflight and refuses cutover until workload suitability is explicitly confirmed. The preflight reports the active Alembic schema heads, missing canonical or unexpected unmanaged tables, actual PostgreSQL database size, free/required space on the zero-nvr data filesystem, and the previous hour of representative high-write database activity (recording segments, events, alerts, and audit events). Hard blockers such as schema drift or insufficient target disk space cannot be bypassed by workload confirmation.

`--confirm-sqlite-workload` means the operator has reviewed those measured results and representative SQLite benchmark/soak evidence for the intended host. zero-nvr does not reject the reverse migration from a guessed camera-count limit. After preflight passes, the normal verified backup -> quiesce -> consistent source snapshot -> transfer -> cutover -> health-check workflow applies, and the previous PostgreSQL URL remains recorded for the rollback grace period.

Managed MQTT generates a random broker password when none exists. The broker requires authentication and is bound to loopback by default. Frigate and OpenList management ports are also loopback-bound by default; operators may deliberately widen the bind address when required.

### resource bounds

Validate runtime bounds that keep disposable state from consuming the host:

~~~bash
./deploy.sh resource-bounds-check
~~~

The check is read-only and verifies:

- every currently running Compose container uses bounded Docker `json-file`
  logging with positive `max-size` / `max-file` settings;
- current remote-playback `*.mp4` cache usage is at or below the effective
  RuntimeTuningSettings byte quota; the playback restore path already prunes by
  TTL and byte quota before and after copy;
- API, worker, and ZLMediaKit share the same prebuffer Docker volume;
- that volume uses the local tmpfs driver with the configured
  `ZERO_NVR_PREBUFFER_SIZE`;
- the application actually sees `/prebuffer` as tmpfs and its observed
  capacity does not exceed the configured bound.

The real clean-install CI executes this check on the running Core stack. Compose
CI separately verifies logging bounds for optional-profile services too.

### resource baseline

Plan 04 R1 clean-Core/no-camera measurement is host-operated:

~~~bash
./deploy.sh resource-baseline
~~~

Run it after a clean Core install before configuring cameras or optional
Compose profiles. It waits for idle stabilization, then records conservative
Core image bytes, container writable layers, initial product/config/log bytes,
Docker/cgroup memory and CPU, host RAM/CPU, and excluded cache/recording usage.
The report is stored under
<ZERO_NVR_DATA_PATH>/release-validation/latest-resource-baseline.json.
The command exits non-zero when the static footprint is at least 2 GiB, peak
three-container idle memory is at least 1 GiB, optional services are active, or
the camera inventory is not clean.

After collecting R1 evidence, independently validate the static-footprint gate:

~~~bash
./deploy.sh resource-check static
./deploy.sh resource-check static --max-age-hours 24
~~~

The validator rechecks the fixed <2 GiB threshold, recomputes the component
sum, requires clean-Core/zero-camera evidence, rejects stale evidence, and
requires the recorded API/worker/ZLM image IDs to match the currently running
Core containers. Therefore an old R1 report cannot remain valid after an image
change.

Validate the idle-memory half of the same R1 evidence separately:

~~~bash
./deploy.sh resource-check idle
./deploy.sh resource-check idle --max-age-hours 24
~~~

The idle validator applies the fixed <1 GiB three-Core-container peak-memory
limit and the documented methodology: clean Core, zero cameras, at least
60 seconds settling time, at least five Docker/cgroup samples, and a positive
sample interval. It also rejects stale evidence and image-identity changes.

### benchmark

Release-gate validation is host-operated:

```bash
./deploy.sh benchmark 8
./deploy.sh benchmark 16
./deploy.sh benchmark 8 --samples 10 --interval 2
```

The command does not generate synthetic RTSP sources. It validates the real
configured workload and should be run on the intended deployment host while
the target cameras and recording policies are active.

The runtime gate requires at least the selected number of enabled,
non-retired cameras to have an active recording mode, an online RECORD stream
in ZLMediaKit, and an active ZLMediaKit MP4 recorder.

The host-side resource report records:

- the conservative sum of unique zero-nvr and ZLMediaKit Docker image virtual
  sizes, gated below 2 GiB;
- API + worker Docker memory average/peak, gated below 1 GiB;
- ZLMediaKit memory separately because media buffers and page cache vary with
  workload;
- combined Core memory as informational context.

The 8-camera command is the V1 baseline benchmark. The 16-camera command is the
extended-target benchmark and writes profile `16-camera-extended`. The command
emits one JSON report suitable for release validation evidence and exits
non-zero when a gate fails.

The 16-camera evidence path is intentionally benchmark-only:

```bash
./deploy.sh benchmark 16
./deploy.sh release-check 16
```

It does not require a 16-camera soak or recent backup, because the V1
long-duration/recovery release gate remains the 8-camera baseline. A real
16-camera benchmark result is still required before the extended-target ROADMAP
item can be accepted.

### soak

The same soak engine supports both release-scale and small-host validation.

Plan 04 R2/R3 small-host acceptance:

```bash
./deploy.sh small-host-soak 2 --duration 3600 --interval 30
./deploy.sh small-host-soak 4 --duration 3600 --interval 30
```

The 2/4-camera modes are strict acceptance runs: they require SQLite, exactly
the requested number of active persistent-recording cameras, at least one hour,
no Core container restart, and an observed host class of no more than 2 CPU
cores / 2.5 GiB RAM. They record Core RAM/CPU history, host available RAM,
SQLite WAL peak, RECORD stream count, measured recording write bitrate, and
restart deltas. Results are stored as `latest-small-host-2.json` and
`latest-small-host-4.json`, so they do not overwrite the 8-camera release
soak evidence.

Longer release validation is host-operated:

```bash
./deploy.sh soak 8
./deploy.sh soak 16
./deploy.sh soak 8 --duration 1800 --interval 30
```

The default run is 10 minutes with a 30-second sample interval. That default is
a diagnostic soak, not sufficient evidence for the V1 8-camera long-duration
baseline. Release acceptance requires at least one hour:

```bash
./deploy.sh benchmark 8
./deploy.sh soak 8 --duration 3600 --interval 30
./deploy.sh release-check 8
```

`release-check 8` rejects an otherwise-passing soak report whose
`duration_seconds` is below 3600. Every sample requires the selected camera
workload to keep its recording streams/recorders healthy and also requires the
database, worker heartbeat, ZLMediaKit, and recording storage health components
to remain OK. A transient failed sample is retained in the final failure counts
even when the final sample later recovers.

At the final sample, every camera that is currently in persistent recording
mode must also have produced at least one non-empty `RecordingSegment` with
an AVAILABLE local recording location since the soak began. EVENT_ONLY
prebuffer cameras are not required to create a canonical segment when no event
occurred; their stream and recorder still participate in every runtime sample.

The command emits one JSON report. Short custom durations are useful for
diagnostics, but a run shorter than the configured segment target may
legitimately fail the persistent media-progress gate.

### doctor

Checks should include, as applicable:

- Docker/Compose availability;
- expected writable paths;
- recording-volume free space;
- database access;
- ZLM reachability;
- configured optional service reachability;
- host time synchronization state;
- version compatibility.

## Feature examples

### Local recording only

3 containers:

```text
zero-nvr
zero-nvr-worker
zlmediakit
```

### Remote archive to S3/WebDAV/SFTP/OneDrive/etc.

Still 3 containers. The worker invokes rclone directly.

### Managed OpenList

4 containers:

```text
zero-nvr
zero-nvr-worker
zlmediakit
openlist
```

### Managed Frigate with external MQTT

4 containers:

```text
zero-nvr
zero-nvr-worker
zlmediakit
frigate
```

### Managed Frigate + managed MQTT

5 containers:

```text
zero-nvr
zero-nvr-worker
zlmediakit
frigate
mosquitto
```

## Volumes

Keep configuration/runtime data, cache, and recordings separate.

Conceptually:

```text
/config      product configuration / SQLite / generated adapter config
/cache       disposable playback/export/thumbnail cache with quota
/recordings  local hot recording storage
```

Remote-playback cache must be bounded and automatically cleaned. It is not part of the disaster backup.

## Host-managed recording storage

zero-nvr treats a local `StorageTarget` as an already-prepared host path. It
does not create or administer RAID arrays, ZFS pools, Btrfs filesystems, LVM
volume groups/logical volumes, mergerfs unions, NAS mounts, parity layouts, or
filesystem redundancy.

Prepare storage on the host first, then expose one stable mount point to
zero-nvr as the local recording target. Typical supported host layouts include:

- a plain ext4/XFS filesystem on one disk;
- an mdadm/RAID volume mounted at a stable path;
- a ZFS dataset from a host-managed pool;
- a Btrfs filesystem/subvolume;
- an LVM logical volume with a host-managed filesystem;
- a mergerfs mount assembled and monitored by the host;
- an NFS/SMB NAS share mounted by the host.

The supported ownership boundary is:

~~~text
disks / HBA / RAID / ZFS / Btrfs / LVM / mergerfs / NFS / SMB
    -> host operating system owns assembly, mount, redundancy, scrub,
       replacement, degraded-state handling, and recovery

stable writable mount point
    -> zero-nvr StorageTarget owns recording placement, capacity thresholds,
       retention, RecordingLocation identity, archive policy, and playback
~~~

For production recording targets:

- use a stable absolute mount point and keep it unchanged after the
  `StorageTarget` is created; move future writes with the supported target
  switch workflow instead of editing the path in place;
- ensure the mount is present and writable before starting zero-nvr;
- configure host boot/mount dependencies so zero-nvr does not start recording
  until required local/NAS storage is mounted;
- do not rely on a bare mount-point directory remaining writable when the real
  filesystem or NAS is absent, because that can redirect recordings onto the
  host root filesystem;
- monitor array/pool/NAS health with the host's native tooling in addition to
  zero-nvr's per-target free-space/availability health;
- keep application data/database and disposable cache separate from hot
  recording storage unless the operator has deliberately designed the host
  filesystem otherwise.

zero-nvr intentionally does not expose disk formatting, pool creation, device
replacement, resilver/rebuild, scrub, SMART administration, or mount/unmount
controls in the Web UI. Those remain host/NAS responsibilities.

## Log and cache bounds

The default Compose deployment must configure bounded container logging rather than relying on unlimited Docker json-file growth.

Use an appropriate platform-supported rotation policy such as:

~~~text
max-size
max-file
~~~

Exact defaults may be tuned, but unattended logs must not be able to consume the system disk.

Disposable cache is also byte-bounded:

~~~text
/cache/playback
/cache/exports
/cache/thumbnails
~~~

Cache quota is deployment/product configuration and is **not** counted as static application footprint.

See [Plan 04 — V1 Resource Budget](plans/04-v1-resource-budget.md).

## Remote playback baseline

V1 does not require FUSE.

```text
remote-only segment
-> worker rclone copyto/restore
-> /cache/playback
-> ZLM VOD
-> browser
```

Prefetch of the next segment is allowed as an optimization.

## Upgrade and rollback

The deployment entry point owns operational sequencing, while database/media semantics remain in the application and mature tools.

Minimum sequence:

1. preflight;
2. backup/safety point;
3. pull version-pinned images;
4. migration;
5. start/restart;
6. health validation;
7. record immutable deployed/rollback state.

Migration/startup/health failure must not silently leave a half-upgraded stack. Once a pre-upgrade rollback point is recorded, the operator can run `./deploy.sh rollback` to restore the previous source revision and matching database safety point.
