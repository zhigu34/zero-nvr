# Plan 00 — Platform Bootstrap

Status: **ready after design-freeze gate / safe foundation work may begin**

## Goal

Create the minimum project foundation that does not depend on unresolved media POCs.

## Backend layout

Suggested modular-monolith structure:

```text
backend/
  app/
    api/
      v1/
      internal/
    core/
      config/
      db/
      security/
      errors/
      time/
    modules/
      auth/
      cameras/
      media/
      recording/
      playback/
      events/
      alerts/
      notifications/
      storage/
      exports/
      backup/
      system/
      audit/
    integrations/
      zlm/
      onvif/
      frigate/
      rclone/
      apprise/
      restic/
      oidc/
      mqtt/
    jobs/
      archive/
      export/
      notification/
      backup/
      retention/
      reconciliation/
    main.py
  alembic/
  tests/
```

Boundaries matter more than exact folder names.

## Frontend layout

```text
frontend/
  src/
    api/
    components/
    layouts/
    pages/
    stores/
    router/
    players/
    types/
```

Vue is built in a multi-stage image and the final static assets are served through the zero-nvr application/reverse-proxy path. Node/npm build tooling does not remain in the production runtime image.

## Task 1 — Configuration/bootstrap

Implement:

- settings/config loading;
- `.env` bootstrap contract;
- `ZERO_NVR_SECRET_KEY` or equivalent protected secret bootstrap;
- data/config/cache/recording path settings;
- selected database URL;
- internal ZLM endpoint configuration;
- deployment feature availability model.

Do not place product-level user settings into .env when they belong in the database/UI.

## Task 2 — Persistence

Default:

```text
SQLite
```

Optional:

```text
PostgreSQL
```

Use:

- SQLAlchemy 2.x;
- Alembic;
- one logical domain/schema contract;
- SQLite WAL/busy-timeout configuration appropriate to the workload;
- portability tests for both backends.

Do not make Redis or PostgreSQL mandatory just to run Core.

## Task 3 — Application skeleton

Create:

- FastAPI application;
- `/api/v1` router root;
- health/readiness endpoints;
- structured logging;
- dependency injection/service boundaries;
- error response conventions;
- UTC/timezone helpers.

Frontend calls only zero-nvr APIs.

## Task 4 — Security foundation

Create:

- local User model;
- password hashing;
- session/auth primitives;
- SecretStore abstraction;
- AuditEvent foundation;
- first-run administrator state.

Do not implement a custom IdP. OIDC is an integration boundary.

## Task 5 — Background jobs

Use Huey.

SQLite deployment uses SQLite-backed Huey mode where appropriate; PostgreSQL mode may use its supported backend.

Initial job shell only:

- notification;
- archive;
- export;
- backup;
- cleanup;
- reconciliation.

Do not introduce Celery/Redis/RabbitMQ as mandatory infrastructure.

## Task 6 — Adapter contracts

Define thin contracts before integrations:

- MediaPlane / ZlmAdapter;
- DeviceAdapter / ONVIF adapter;
- AIProvider;
- StorageTransfer adapter around rclone;
- Notification adapter around Apprise;
- Backup service around database-native backup + restic.

Do not add a generic RecorderBackend that implies FFmpeg and ZLM are interchangeable normal recorders. Normal recording authority is fixed to ZLM.

## Task 7 — Runtime image

Target one zero-nvr image used by two commands:

```text
zero-nvr-api
zero-nvr-worker
```

Runtime image may include:

- Python runtime;
- built Vue assets;
- FFmpeg/ffprobe;
- rclone;
- restic;
- required Python libraries.

Core deployment plus ZLM is:

```text
2 images
3 containers
```

## Task 8 — Test foundation

Add:

- SQLite integration tests;
- PostgreSQL portability tests;
- API test harness;
- migration tests;
- SecretStore round-trip tests;
- Huey job test mode;
- adapter fakes.

Media-specific assumptions remain behind the design-freeze POCs.

## Acceptance

Bootstrap is complete when:

- API starts with SQLite and no optional services;
- worker starts from the same image;
- schema migration works from an empty DB;
- first-run state is detectable;
- secrets can be encrypted/decrypted with the configured master/bootstrap key;
- health endpoints distinguish API/DB/worker dependency state;
- frontend build is served;
- no ZLM/Frigate/OpenList/PostgreSQL/Redis dependency is required merely to open Core;
- architecture-specific media logic remains behind adapters.
