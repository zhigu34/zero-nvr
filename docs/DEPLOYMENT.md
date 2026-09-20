# Deployment Architecture

Status: **V1 Design Freeze Candidate**

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
feature list
feature enable <name>
feature disable <name>
feature restart <name>
admin reset-password
backup
restore
```

### install

- validate Docker/Compose and filesystem prerequisites;
- create or validate .env;
- select enabled profiles;
- create required directories/permissions;
- pull only enabled images;
- start stack;
- perform health checks.

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

Managed PostgreSQL startup does not silently switch an existing SQLite deployment to PostgreSQL. Database-engine migration remains a separate, explicit workflow.

Managed MQTT generates a random broker password when none exists. The broker requires authentication and is bound to loopback by default. Frigate and OpenList management ports are also loopback-bound by default; operators may deliberately widen the bind address when required.

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
