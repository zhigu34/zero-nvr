# Plan 00 — Platform Bootstrap

Status: **draft implementation plan**

## Objective

Create the smallest clean zero-nvr foundation that can support later media/device/event/storage adapters without carrying V1 compatibility code.

## Task 1 — Backend scaffold

Create:

```text
backend/
  app/
    api/
    core/
    domain/
    models/
    schemas/
    services/
    adapters/
  migrations/
  tests/
  pyproject.toml
```

Initial capabilities:

- FastAPI app;
- settings/config;
- PostgreSQL connection;
- Alembic;
- health/readiness;
- structured logging.

Do not add ONVIF, ZLM or FFmpeg logic yet.

## Task 2 — Frontend scaffold

Create Vue 3 + TypeScript application.

Initial routes:

```text
/devices
/live
/recordings
/events
/alerts
/storage
/system
```

Only Device Center needs initial behavior.

## Task 3 — Core domain

Implement initial:

- Camera;
- CameraConnection;
- MediaStream.

Requirements:

- Camera ID stable;
- public read models contain no secret;
- connection revision available for runtime reconciliation;
- adapter-specific config isolated from generic Camera fields.

## Task 4 — Adapter contracts

Define interfaces/protocols for:

- DeviceAdapter;
- MediaPlane;
- RecorderBackend;
- DetectionProvider;
- StorageBackend;
- NotificationBackend.

Provide fake/test adapters before real integrations.

## Task 5 — Runtime intent/reconciliation

Define how persistent desired state becomes external runtime state.

At minimum:

```text
Camera enabled
   ↓
Runtime coordinator
   ↓
MediaPlane.ensure_stream()
```

Restarting runtime services must reconstruct state from PostgreSQL.

## Task 6 — Docker Compose baseline

Services:

- api;
- web;
- postgres.

ZLMediaKit can be introduced in Plan 01 rather than hidden inside bootstrap.

## Task 7 — CI baseline

Require:

- backend lint;
- backend tests;
- migration test from empty DB;
- frontend lint;
- frontend tests;
- frontend build;
- Compose configuration validation.

## Exit criteria

- repository is clone-and-run for development;
- migrations build an empty database;
- Device Center can CRUD a Camera without protocol-specific logic;
- secrets are excluded from read contracts;
- adapter contracts have fake implementations/tests;
- no V1 compatibility layer exists.
