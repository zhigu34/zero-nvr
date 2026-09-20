# zero-nvr

**zero-nvr** is a lightweight but complete self-hosted NVR control plane.

The project follows one rule:

> Mature components own commodity media/protocol/infrastructure work. zero-nvr owns the product model, policy, integration, UI/API, reconciliation, and user workflow.

## Product target

V1 targets:

- home / personal NVR;
- NAS and home-server deployments;
- small office;
- small-to-medium camera counts;
- single-host deployment by default;
- SQLite by default, PostgreSQL optional.

A complete V1 means the supported lifecycle works end to end:

~~~text
install
-> initialize
-> add cameras
-> live view
-> record
-> timeline/playback
-> events/alerts
-> retention/archive
-> export/protect
-> backup/restore
-> health
-> upgrade
~~~

It does **not** mean every surveillance protocol or enterprise platform feature must ship in V1.

## Capability ownership

| Capability | Owner |
|---|---|
| camera pull / media routing / reconnect | ZLMediaKit |
| normal MP4/fMP4 recording | ZLMediaKit |
| live protocols / VOD / snapshot | ZLMediaKit |
| AI detection / tracking / zones | optional Frigate |
| clip / remux / transcode / frame extraction | FFmpeg / ffprobe |
| remote copy / verify / delete / restore | rclone |
| special cloud-drive gateway | optional OpenList -> WebDAV -> rclone |
| background tasks | Huey |
| notification delivery | Apprise |
| system/disaster backup repository | restic |
| ONVIF / WS-Discovery protocol | mature client libraries |
| host deployment / upgrade | deploy.sh + Docker Compose |

zero-nvr must not introduce a second RTSP reconnect engine, permanent FFmpeg recorder, RAID/JBOD manager, generic job queue, generic rule engine, or monitoring TSDB.

## Recording path

~~~text
Camera main/sub
      ↓
ZLMediaKit
  ├─ live
  ├─ normal recording
  ├─ VOD
  └─ AI_DETECT stream -> optional Frigate

ZLM finalized MP4
      ↓
on_record_mp4
      ↓
RecordingSegment
      ↓
RecordingLocation(s)
~~~

A `RecordingSegment` is the finalized time/media fact.

A `RecordingLocation` is one physical copy on local or archived storage.

The database is not in the live media write path. Missed hooks are repaired by reconciliation.

## Storage path

~~~text
local RecordingLocation AVAILABLE
      ↓
Huey -> rclone copy/copyto
      ↓
verify
      ↓
remote RecordingLocation AVAILABLE
      ↓
retention may delete local copy
~~~

Remote archive failure never stops healthy local recording.

The product does not use `rclone move` or whole-tree sync as the default archive semantic.

## Database

Default:

~~~text
SQLite + WAL
~~~

Optional scale-up:

~~~text
PostgreSQL
~~~

Both share one SQLAlchemy/Alembic logical model.

SQLite remains first-class until measured load proves a deployment should move to PostgreSQL.

## Core deployment

Default non-AI Core:

~~~text
Image: zero-nvr
  ├─ zero-nvr-api
  └─ zero-nvr-worker

Image: ZLMediaKit
  └─ zlmediakit
~~~

That is **2 images / 3 containers**.

FFmpeg, rclone, restic, Apprise, ONVIF/auth libraries are included in the zero-nvr image where practical rather than receiving one container each.

Optional independently running services such as Frigate, Mosquitto, OpenList, and PostgreSQL are started only when enabled.

## Deployment interface

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

The web/API container does not require unrestricted Docker-socket access.

## Repository layout

~~~text
backend/       FastAPI modular-monolith control plane
frontend/      Vue 3 management/playback UI
deploy/        deploy.sh / Compose deployment definitions
poc/           disposable design-freeze validation harnesses
docs/          architecture, ADRs, specs and freeze plans
~~~

## Current status

~~~text
V1 Design Freeze Candidate
~~~

The architecture ownership, persistence boundary, and API/module boundary are now documented.

Before declaring `V1 Architecture Frozen`, the media/storage/database POCs in the design-freeze plan must produce real evidence.

Start here:

- [Project Baseline](docs/PROJECT_BASELINE.md)
- [Documentation Index](docs/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Domain Model](docs/DOMAIN_MODEL.md)
- [Technology Stack](docs/TECH_STACK.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/ROADMAP.md)
- [V1 Design-Freeze POCs](docs/plans/01-design-freeze-poc.md)
- [V1 Schema Freeze](docs/plans/02-v1-schema-freeze.md)
- [V1 API / Module Freeze](docs/plans/03-v1-api-module-freeze.md)

## Design-freeze POC suite

The committed harnesses cover every architecture-freeze POC.

~~~bash
cd poc/zlm-recording
cp .env.example .env

# POC-01 + POC-08
sh ./scripts/run.sh

# POC-02
sh ./scripts/run-fmp4-crash.sh

# POC-03 + POC-04
sh ./scripts/run-event-preroll.sh

# POC-05 + POC-06
sh ./scripts/run-timeline-playback.sh

# POC-07
sh ./scripts/run-remote-restore.sh

# POC-10
sh ./scripts/run-reconciliation.sh
~~~

SQLite load is separate:

~~~bash
cd poc/sqlite-load
sh ./run.sh
~~~

That covers POC-09.

A committed harness is not a passing result. Every document under `docs/poc-results/` remains `NOT RUN` until the corresponding command produces real evidence on a Docker host.
