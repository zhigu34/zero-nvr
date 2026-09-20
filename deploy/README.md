# Deployment

zero-nvr uses:

~~~text
deploy.sh + .env + Docker Compose Profiles
~~~

The deployment script is a supported product interface, not a temporary bootstrap helper.

## Core

Default non-AI stack:

~~~text
zero-nvr-api       # zero-nvr image
zero-nvr-worker    # same zero-nvr image, different command
zlmediakit         # independent media service
~~~

Core target:

- 2 images;
- 3 containers;
- SQLite embedded/default;
- no Redis;
- no PostgreSQL requirement;
- no Docker socket in the web/API container.

The zero-nvr image may include:

- FFmpeg / ffprobe;
- rclone;
- restic;
- Apprise;
- ONVIF / WS-Discovery libraries;
- auth/OIDC libraries.

## Optional managed services

Started only when enabled by a Compose profile:

~~~text
Frigate
Mosquitto
OpenList
PostgreSQL
coturn
~~~

External mode should be supported where practical so an existing service does not need to be duplicated.

## Deployment responsibilities

~~~text
.env / deploy.sh / Compose profile
  -> whether a runtime capability/service exists

zero-nvr DB / UI
  -> product configuration and enablement
~~~

Examples:

- external Frigate: configure connection in UI;
- managed Frigate: enable the deployment feature first;
- SMTP: no extra container;
- rclone remote archive: no extra container;
- PostgreSQL: optional managed/external mode.

## Expected command surface

~~~text
./deploy.sh install
./deploy.sh update [version]
./deploy.sh status
./deploy.sh doctor
./deploy.sh feature enable <name>
./deploy.sh feature disable <name>
./deploy.sh backup
./deploy.sh restore
./deploy.sh rollback [version]
./deploy.sh admin reset-password
~~~

Host mutation remains outside normal browser APIs.

See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) and [ADR 0005](../docs/adr/0005-deploy-sh-upgrade-authority.md).


## Worker process

The worker uses the **same zero-nvr image** as the API. It is a Huey
consumer, not a custom queue daemon or a separate application image.

Conceptual command:

~~~text
huey_consumer.py app.worker.consumer.huey
~~~

The default queue backend is Huey's SQLite backend at:

~~~text
ZERO_NVR_HUEY_DB_PATH=/var/lib/zero-nvr/huey.db
~~~

The API and worker must share the zero-nvr data volume containing this
queue database.

Huey owns queueing, delayed execution, retries, and scheduled tasks.
zero-nvr must not add a parallel custom job/lease/retry table.

## EVENT_ONLY prebuffer mount

EVENT_ONLY recording uses one normal ZLMediaKit MP4 recorder writing
short finalized fragments into a bounded tmpfs-backed shared mount.

Required invariant:

~~~text
ZLMediaKit /prebuffer
        =
worker /prebuffer
        =
API /prebuffer
~~~

These paths must refer to the **same shared backing filesystem**.

A separate per-container Docker `tmpfs:` mount is not sufficient:
the worker would not see fragments written by ZLMediaKit. Deployment
must provide one shareable tmpfs-backed volume/mount and mount it at the
same path in the relevant containers.

Default bootstrap settings:

~~~text
ZERO_NVR_PREBUFFER_DIR=/prebuffer
ZERO_NVR_PREBUFFER_FRAGMENT_SECONDS=5
ZERO_NVR_PREBUFFER_BUFFER_SECONDS=35
ZERO_NVR_PREBUFFER_REQUIRE_TMPFS=true
~~~

The 5 s fragment target and 35 s buffer window come from the accepted
POC baseline and remain configurable. The mount itself must have an
explicit hard size limit; zero-nvr does not silently create an unbounded
ordinary-disk fallback.
