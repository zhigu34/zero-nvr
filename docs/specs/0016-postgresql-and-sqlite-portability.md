# Spec 0016 — Production Database Policy and SQLite Portable Index

Status: **accepted**

## Goal

Define the database support policy for zero-nvr and the formal role of SQLite in the first production release.

Core rule:

> PostgreSQL is the only supported production metadata database. SQLite is a first-class portable/offline data format and development/test tool, not a second production database backend.

## Production database policy

zero-nvr has concurrent writers and transactional workflows across camera/device state, RecordingManager, DetectionEvent/EventLog, alert/notification workers, upload/archive workers, retention/purge, audit, backup metadata, and health jobs.

The production model benefits from PostgreSQL semantics and features:

```text
concurrent write handling
transactional row locking
JSONB/provider metadata
rich indexing
timestamptz / UTC semantics
coordination primitives where useful
WAL / PITR backup ecosystem
```

Supporting SQLite as an equal production backend would permanently create duplicate compatibility work for locking, types, indexes, migrations, worker concurrency, and recovery.

Therefore:

```text
Production runtime database
  PostgreSQL only

Development/unit testing
  SQLite allowed for database-portable behavior

Integration/system testing
  PostgreSQL required

Offline portable index/export
  SQLite supported

Recovery/analysis tooling
  SQLite supported
```

The installer/UI does not offer a PostgreSQL-vs-SQLite production selector.

## Deployment experience

Mandatory PostgreSQL must not make standard installation complicated.

Default Docker Compose deployment includes PostgreSQL inside the zero-nvr stack.

```text
docker compose up -d
        ↓
zero-nvr web
zero-nvr api
zero-nvr worker
postgresql
zlmediakit
...
```

Advanced deployments may point zero-nvr at an external PostgreSQL service.

## ORM and migration policy

SQLAlchemy/Alembic target PostgreSQL production semantics first.

Rules:

- do not weaken production schema merely to retain SQLite compatibility;
- PostgreSQL-specific indexes/data types/locking are allowed when product value requires them;
- portable domain logic should remain testable without unnecessary DB coupling;
- PostgreSQL integration tests are mandatory for concurrency, locking, JSONB, timestamps, migrations, and worker coordination.

SQLite unit tests are convenience tests, not proof of production database correctness.

## SQLite Portable Index

The first production release provides a portable SQLite export for offline inspection, migration, recovery, and analysis.

Example:

```text
zero-nvr-index-2026-09-19.sqlite
```

This is a read-oriented/export database and never becomes the live production source of truth.

## Portable index content

Default safe metadata may include:

```text
Camera
CameraGroup
RecordingSession
RecordingSegment
RecordingSessionSegment
StorageObject
DetectionEvent
AlertIncident
AlertIncidentSource
SourceConnectivityIncident
retention summary
export metadata
backup/export manifest metadata
```

Portable export excludes or sanitizes:

```text
password hashes where not needed
SecretRecord ciphertext/key material
camera/storage credentials
SMTP credentials
API/service token verifiers
MFA secret material
RecoveryKit contents
sensitive audit/user data outside selected export profile
```

Portable SQLite is not a credential backup.

## Portable schema

The export uses its own versioned schema.

```text
portable_format_version
source_zero_nvr_version
source_schema_revision
exported_at
instance_id
timezone/display metadata
```

Do not mirror every PostgreSQL implementation detail blindly.

The portable schema is designed for stable offline querying, detached-media inspection, migration tooling, support, and future import compatibility.

## Media references

The SQLite export does not embed all media files.

It records logical references such as:

```text
recording_segment_id
camera_id
started_at
ended_at
availability
storage target/type
object key or detached relative path where safe
checksum / size
completion_reason
```

When exported together with selected media, relative paths can point to the included files.

Metadata-only exports keep descriptive StorageObject references.

## Detached media use

A useful workflow is:

```text
recording disk / exported media
        +
zero-nvr-index.sqlite
        ↓
offline inspection tool
```

This complements the per-camera detached metadata from Spec 0004.

Offline search can cover camera, time range, event type, incident, segment availability, and session relationships.

## Export modes

### Metadata-only

Produces a compact portable SQLite index containing safe selected metadata.

### Selected media package

User selects cameras/time range/event or incident range.

The package contains:

```text
portable SQLite index
selected media files
manifest
checksums
```

This is distinct from normal single-file playback export.

### Support/diagnostic export

Produces sanitized metadata for troubleshooting while excluding secrets and unnecessary personal/security data.

## Consistent export snapshot

Portable index generation must represent a transactionally consistent logical view.

For PostgreSQL:

- use a consistent transaction/snapshot;
- do not mix unrelated capture moments without explicitly recording the limitation;
- large exports may stream/chunk while preserving the same logical snapshot where practical.

Media files are separately verified against the export manifest.

## Import role

Portable SQLite is never attached directly as the production database.

Import flow:

```text
portable SQLite
      ↓
Importer
      ↓
schema/version validation
      ↓
mapping and conflict preview
      ↓
PostgreSQL domain writes
```

Imports pass through current validation, authorization, and migration logic.

Never replace PostgreSQL data files with SQLite content.

## Legacy migration role

Portable SQLite may serve as an intermediate format for migration from:

- previous camera-recorder metadata;
- offline recovered metadata;
- supported third-party exports.

Legacy importers normalize into the portable/import model, then current zero-nvr domain services persist canonical PostgreSQL records.

## Recovery tooling

SQLite may be used by offline recovery tools to:

- inspect restored PostgreSQL backup content through a portable catalog;
- reconstruct a browsable index from recording directories/manifests;
- compare metadata with detached media;
- generate reconciliation reports.

This does not make SQLite the production source of truth.

## SQLite concurrency policy

Do not rely on SQLite for production worker coordination or high-write runtime state.

Even if SQLite WAL mode is used in tests/tools, production correctness must not depend on SQLite locking behavior.

No production feature may be declared supported solely because it works against SQLite.

## Database abstraction boundaries

Domain/application code should avoid gratuitous database coupling, while production semantics take priority.

```text
Domain services
     ↓
Repository/query interfaces
     ↓
PostgreSQL implementation
```

SQLite-specific code belongs in portable export/import, offline tools, and test fixtures.

Avoid production branching that weakens semantics just to support two live database engines.

## Backup relationship

Spec 0015 remains authoritative for production backup:

```text
PostgreSQL
   ↓
pgBackRest
   ↓
WAL / PITR / disaster recovery
```

SQLite portable export does not replace PostgreSQL backup, PITR, RecoveryKit, or system disaster recovery.

It is an additional portability artifact.

## Permissions

Initial permissions:

```text
data_export.create
data_export.download
data_import.manage
```

Export scope must also respect camera/resource authorization unless an explicitly privileged full-system export is requested.

Portable export must never become an authorization bypass.

## Audit

Audit at minimum:

```text
data_export.created
data_export.downloaded
data_import.started
data_import.completed
data_import.failed
```

Audit records scope/profile/results without exported secrets.

## UI

System > Data Export / Import:

```text
Export metadata index
  Format: SQLite
  Scope: all / group / selected cameras
  Time range
  Include events/incidents
  Include selected media
  Sanitize user/audit data

Import
  Upload portable index/package
  Validate
  Preview conflicts
  Import
```

Recording/event pages may provide context-specific export shortcuts.

## Acceptance tests

1. production startup requires PostgreSQL and exposes no SQLite production mode;
2. portable domain unit tests may use SQLite only where DB-specific behavior is irrelevant;
3. concurrency/worker/database integration tests run against PostgreSQL;
4. metadata export produces a valid versioned SQLite artifact without recoverable credentials;
5. scoped users cannot export hidden-camera metadata/media;
6. selected-media package references/checksums match included media;
7. portable index can be queried without running zero-nvr/PostgreSQL;
8. import validates schema/version, previews conflicts, and persists through PostgreSQL domain logic;
9. portable export is never reported as PITR/system disaster-recovery protection.

## Invariants

1. PostgreSQL is the only supported production metadata database.
2. SQLite is not exposed as a production runtime option.
3. SQLite remains supported for portable export/import, offline tooling, and selected unit tests.
4. PostgreSQL-specific product features are not weakened merely for SQLite compatibility.
5. PostgreSQL integration tests are mandatory for production database semantics.
6. Portable SQLite schema is explicitly versioned and independent from raw PostgreSQL implementation details.
7. Portable exports exclude secrets and respect authorization/camera scope.
8. SQLite portable export is not a replacement for pgBackRest/PITR/RecoveryKit.
9. Imports flow through validation/domain persistence into PostgreSQL.
10. Non-obvious export/import/snapshot/schema-mapping logic requires comments per Development Guidelines.
