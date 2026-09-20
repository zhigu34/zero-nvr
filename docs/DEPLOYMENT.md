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
./deploy.sh feature enable ai
```

The deployment script performs the Compose operation.

## Expected deploy.sh surface

The command grammar may evolve, but the product needs these workflows:

```text
install
update
status
doctor
feature enable <name>
feature disable <name>
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

- preflight configuration and free space;
- create a verified safety backup when required;
- pull version-pinned images;
- run schema migration;
- restart affected services;
- verify health;
- preserve rollback information.

Do not treat mutable `latest` as the production upgrade contract.

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
6. health validation.

Migration failure must not silently leave a half-upgraded stack.
