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
