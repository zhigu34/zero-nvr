# Plan 04 — V1 Resource Budget

Status: **required non-functional release gate**

## Goal

Keep zero-nvr lightweight in real deployment, not only in architecture diagrams.

The V1 default non-AI product must remain practical on a small single-host/NAS installation.

Core deployment:

~~~text
Image: zero-nvr
  ├─ zero-nvr-api
  └─ zero-nvr-worker

Image: ZLMediaKit
  └─ zlmediakit
~~~

Therefore:

~~~text
2 unique images
3 running containers
~~~

The API and worker share the same zero-nvr image. Their common image layers are stored once.

Normal remote archive does **not** add a permanent rclone container.

## Resource accounting

Resource discussions must separate four categories.

### A — Core static product footprint

Count:

- unique Docker image/layer storage required by the three Core containers;
- Core container writable layers after normal startup;
- initial zero-nvr configuration/database state;
- generated adapter configuration;
- bounded baseline logs required for normal operation.

Do not double-count the same zero-nvr image because API and worker run it with different commands.

### B — Product database growth

Count and report separately.

SQLite growth depends on:

- RecordingSegment history;
- Event/Alert history;
- AuditEvent history;
- user/configuration state.

This is product metadata growth, not static program size.

### C — Disposable cache / derived assets

Examples:

- remote playback cache;
- exports;
- thumbnails;
- temporary FFmpeg output;
- tmpfs EVENT_ONLY prebuffer.

These must have explicit quotas/retention and are reported separately.

A configured 5 GB playback cache does **not** mean “zero-nvr requires 5 GB of program disk.”

### D — Canonical recording media

~~~text
/recordings
~~~

Recording storage is capacity-planned from camera bitrate, retention, and archive policy.

TB-scale recording data is never included in the zero-nvr application-footprint number.

## Optional services are excluded from Core

The following are measured only when enabled:

- Frigate;
- Mosquitto;
- OpenList;
- PostgreSQL;
- coturn;
- Prometheus/Grafana or other optional observability components.

A disabled feature must not pull or retain its managed-service image as part of a clean Core install.

## V1 disk targets

### Hard Core gate

On a clean Docker host, after pulling/starting only non-AI Core:

~~~text
unique Core image/layer storage
+ normal Core writable layers
+ initial product state
< 2 GB
~~~

This is the hard V1 release target already reflected in PROJECT_BASELINE.

### Engineering target

Prefer:

~~~text
~1.0–1.2 GB or less
~~~

for the unique Core image/layer footprint where practical.

The target is not achieved by moving required runtime tools into hidden sidecars; total unique pulled bytes still count.

### Runtime-state target

Fresh install, before meaningful camera/event history:

- SQLite/config/generated configuration should remain small;
- baseline logs must be rotation-bounded;
- no unbounded debug/log/cache directory is allowed.

Do not set an artificial minimum system-disk recommendation such as 10 GB merely because Docker can consume that much. Deployment documentation may recommend extra operational headroom, but must distinguish **recommended host free space** from **actual Core footprint**.

## Image construction rules

The production zero-nvr image should use multi-stage builds.

Required direction:

~~~text
Node build stage
  -> build Vue
  -> copy only dist/

Python/runtime build stage
  -> install wheels/runtime dependencies

final runtime image
  -> Python runtime
  -> zero-nvr backend
  -> built Vue assets
  -> FFmpeg/ffprobe
  -> rclone
  -> restic
  -> required shared libraries
~~~

Do not keep in final image merely for build convenience:

- npm cache;
- node_modules from build stage;
- TypeScript compiler;
- gcc/g++;
- build-essential;
- Python compiler headers;
- package-manager caches;
- test fixtures;
- source maps unless intentionally shipped.

Apprise/ONVIF/Authlib/Huey and similar Python libraries remain normal dependencies rather than separate images.

## API / worker image policy

Preferred V1 default:

~~~text
one zero-nvr image
two commands
~~~

Reasons:

- shared layers stored once;
- fewer release artifacts;
- no dependency skew;
- simpler deploy.sh rollback;
- small CLI tools do not deserve separate containers.

A future split API/worker image is justified only if measured image/runtime savings are material enough to outweigh another release artifact.

Do not split merely to make one image-size number look smaller.

## Log budget

Docker/container logs must be rotation-bounded in deployment configuration.

Example policy class:

~~~text
max-size
max-file
~~~

Exact defaults may vary by deployment platform, but an unattended Core install must not allow stdout/stderr logs to consume the entire system disk.

Application business history belongs in Event/Audit/other canonical tables, not duplicated indefinitely in logs.

## Cache budget

All disposable caches require:

- configurable maximum bytes;
- deterministic eviction;
- current usage visible in UI/system status;
- no ability to delete canonical RecordingLocations;
- safe behavior when the cache is full.

Recommended path separation:

~~~text
/config
/cache
/recordings
~~~

The cache quota is user/deployment configuration and is reported separately from static Core footprint.

## EVENT_ONLY tmpfs budget

POC-03 validated the rolling tmpfs design. Prebuffer memory is explicitly budgeted by bitrate and configured buffer duration.

Approximation:

~~~text
bytes_per_camera
≈ bitrate_bits_per_second / 8 * buffer_seconds
~~~

Example only:

~~~text
4 Mbit/s * 40 s ≈ 20 MB / stream
~~~

The product must calculate/display expected prebuffer memory before enabling a large camera count.

tmpfs must be bounded.

### POC-03 measured reference

The design-freeze POC used:

~~~text
segment target = 5 s
pre-roll = 10 s
post-roll = 10 s
buffer window = 35 s
tmpfs hard cap = 256 MiB
~~~

Observed per-test-group peaks with one EVENT_ONLY stream were:

~~~text
H.264 / ~2 s GOP   ≈ 7.60 MB
H.264 / ~5 s GOP   ≈ 3.61 MB
H.265 / ~2 s GOP   ≈ 3.33 MB
~~~

These are reference measurements for the synthetic bitrates used by the POC, **not fixed per-camera memory promises**.

Production sizing continues to use configured/observed bitrate × buffer duration plus a safety margin. The UI/deploy preflight should report the aggregate expected tmpfs reservation/pressure for all enabled EVENT_ONLY cameras.

## V1 RAM targets

### Core idle

Steady-state non-AI Core target:

~~~text
< 1 GB
~~~

for the three Core containers under the documented idle measurement method.

Record both:

- Docker/cgroup memory;
- process/container CPU.

Do not hide large permanent caches to meet the number.

### Small-host acceptance

A representative no-AI deployment with:

~~~text
2–4 cameras
main + sub streams where configured
continuous ZLM recording
SQLite
no transcode/export job
no remote restore in progress
~~~

must be tested on or constrained to a host class around:

~~~text
2 GB RAM
2 CPU cores
~~~

Acceptance is not “uses all 2 GB without OOM.”

The result must leave enough headroom for the operating system and normal temporary spikes.

Record:

- steady-state container memory;
- peak memory over the soak window;
- CPU average/peak;
- ZLM stream count;
- recording bitrate;
- SQLite WAL size;
- dropped/restarted containers;
- host available memory.

If four cameras cannot run safely within this class, document the measured minimum instead of silently increasing the recommendation.

## Resource benchmark phases

### R1 — first runnable Core image

As soon as the production Dockerfile exists:

1. build/pull clean Core;
2. measure unique image/layer storage;
3. start no-camera Core;
4. wait for steady state;
5. measure memory/CPU;
6. record writable-layer/config/log size.

Supported collector:

~~~text
./deploy.sh resource-baseline
./deploy.sh resource-baseline --settle 120 --samples 10 --interval 2
~~~

It refuses optional Compose profiles, requires exactly API/worker/ZLM, and
requires zero configured cameras. The default waits 60 seconds for steady state
and samples all three Core containers five times. The report is stored at
<ZERO_NVR_DATA_PATH>/release-validation/latest-resource-baseline.json.

The static gate deliberately uses a conservative image figure: API/worker shared
image is counted once and ZLM once, while cross-image shared layers are not
subtracted. Writable layers, initial data, environment file, generated ZLM
configuration, and current Docker log streams are added. Recording/cache bytes
are reported separately and excluded. Idle RAM sums API + worker + ZLM
Docker/cgroup memory and requires peak sampled usage below 1 GiB.

R1 remains incomplete until this command is executed on the intended clean
deployment host and the resulting evidence is reviewed. CI validates the
collector contract but is not production measurement.

### R2 — 2-camera soak

Run:

~~~text
2 cameras
main + sub
continuous recording
SQLite
~~~

for at least one hour.

Record resource history and failure count.

### R3 — 4-camera soak

Repeat with four cameras.

### 16-camera extended target

The 16-camera target is measured as an extended workload benchmark rather than a
second V1 long-duration soak gate:

~~~text
./deploy.sh benchmark 16
./deploy.sh release-check 16
~~~

The benchmark must report profile `16-camera-extended` and requires sixteen
enabled cameras with active recording streams/recorders. It keeps the same hard
Core image/control-plane memory gates so the extended workload cannot hide a
regression in the lightweight Core targets. The result must come from a real
deployment host; CI does not synthesize sixteen RTSP sources.

### 8-camera V1 baseline acceptance

The 8-camera release baseline is a real-host acceptance gate, not a synthetic CI
workload. The intended host must have at least eight enabled cameras actively
recording through ZLMediaKit. Evidence consists of:

~~~text
./deploy.sh benchmark 8
./deploy.sh soak 8 --duration 3600 --interval 30
./deploy.sh release-check 8
~~~

The long-duration soak must be at least one hour. Shorter soak runs remain useful
for diagnostics but do not satisfy the V1 baseline release gate. The final
release check also requires the matching benchmark evidence and a recent
verified system backup.

### R4 — background-work spike

From the same 4-camera baseline, separately test:

- one Export/remux;
- one remote archive transfer;
- one backup;
- one remote playback restore.

These are transient workloads. Measure peak memory/CPU without making them permanent idle cost.

### R5 — optional AI profile

Measured separately and never folded into the no-AI Core requirement.

## Measurement output

Create a machine-readable artifact once the production image exists, for example:

~~~text
runtime/resource-budget.json
~~~

Fields should include:

~~~text
application_version
image digests
unique image bytes
container writable bytes
config/db/log bytes

host cpu count
host memory
container memory current/peak
container cpu
camera/stream count
bitrate
test duration

cache quota/usage
recording bytes excluded
optional services enabled

result
constraints
~~~

A future helper such as:

~~~text
./deploy.sh doctor resources
~~~

or a dedicated measurement script may automate collection.

Do not implement the collector before the production runtime image exists merely to satisfy this document.

## Release decisions

### PASS

- static Core < 2 GB;
- no-camera idle < 1 GB;
- small-host camera soak completes without OOM/restart/resource runaway;
- logs/caches/tmpfs are bounded;
- disabled optional services are not pulled/run.

### PASS WITH DOCUMENTED HARDWARE REQUIREMENT

Allowed only when:

- the hard static/idle Core targets still hold;
- a specific camera/bitrate workload requires a larger host;
- the requirement is backed by measured evidence and documented clearly.

### FAIL

Examples:

- non-AI Core static footprint >= 2 GB without an accepted ADR/change;
- unbounded cache/log/tmpfs growth;
- optional AI/database/storage service images pulled by default;
- rclone/FFmpeg/restic split into permanent containers without a measured reason;
- 2–4 camera small-host target OOMs/restarts under ordinary recording and no explicit product constraint exists.

## Invariants

1. Recording capacity is not application footprint.
2. Configured cache capacity is not application footprint.
3. API and worker share one image unless measurement proves a split is better.
4. rclone/FFmpeg/restic remain in-process/CLI dependencies, not permanent Core services.
5. Optional service images are excluded when disabled.
6. Core static footprint is measured from unique Docker storage, not per-container double counting.
7. Logs, playback cache, export cache, and EVENT_ONLY tmpfs are all bounded.
8. Lightweight claims must be backed by measured release artifacts once production images exist.
