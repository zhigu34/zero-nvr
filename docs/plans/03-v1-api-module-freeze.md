# Plan 03 — V1 API and Module Boundary Freeze

Status: **accepted / frozen for V1**


Accepted by [ADR 0011 — V1 Architecture Freeze](../adr/0011-v1-architecture-freeze.md). Implementation may refine compatible DTO/internal details; changing the trust/ownership/module boundaries requires an explicit architecture decision.
## Goal

Freeze the public API surface, internal hook boundary, and modular-monolith ownership before broad feature implementation.

This plan does not freeze every response field permanently. It freezes:

- API namespaces and ownership;
- timestamp/error/pagination conventions;
- frontend/backend trust boundary;
- third-party adapter boundary;
- major module dependency direction;
- which operations are runtime/projection calls versus canonical CRUD.

## Global API rules

### Prefix

Public product API:

~~~text
/api/v1
~~~

Internal component callbacks:

~~~text
/internal/hooks
~~~

Frontend never calls ZLMediaKit, Frigate, rclone, OpenList, restic, or camera endpoints directly for product administration.

### Time format

All public API timestamps use timezone-aware ISO 8601 strings.

Examples:

~~~text
2026-09-20T17:30:00Z
2026-09-20T10:30:00-07:00
~~~

The backend persists canonical instants in UTC.

Do not expose one API family in Unix seconds, another in milliseconds, and another as naive datetime strings.

Frontend may convert ISO 8601 to epoch milliseconds internally for timeline rendering.

Schedule APIs additionally carry the schedule timezone where wall-clock intent matters.

### IDs

IDs are opaque strings.

Clients must not infer ordering/time from ID format.

### Error shape

Use HTTP status codes plus a stable error body.

~~~json
{
  "error": {
    "code": "recording_not_found",
    "message": "Recording is not available.",
    "details": {},
    "request_id": "..."
  }
}
~~~

Do not wrap every success response in a legacy `{code: 0, message, data}` envelope.

### Pagination

Growing collections use cursor pagination.

Typical shape:

~~~json
{
  "items": [],
  "next_cursor": null
}
~~~

Use cursor pagination for:

- Events;
- Alerts;
- Audit;
- Exports;
- backup history;
- long recording-segment listings.

Small configuration collections may use normal bounded lists.

### Filtering

Use explicit query parameters rather than a generic filter expression language.

Examples:

~~~text
camera_id=
from=
to=
source=
category=
label=
zone=
severity=
state=
~~~

### Authorization

Every camera-scoped endpoint enforces:

~~~text
required permission
+
effective Camera scope
~~~

Backend authorization is authoritative.

### Idempotency

Create/action endpoints that may be retried across unreliable clients should support an idempotency key where duplicate side effects would be harmful.

At minimum consider it for:

- manual RecordingTrigger;
- Export creation;
- notification test;
- destructive actions;
- integration webhook ingestion where sender retries are expected.

Provider event ingestion additionally uses source/source_event_id uniqueness.

## Auth APIs

~~~text
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
POST   /api/v1/auth/password/change

POST   /api/v1/auth/password-reset/request
POST   /api/v1/auth/password-reset/complete

GET    /api/v1/auth/oidc/providers
GET    /api/v1/auth/oidc/{provider}/login
GET    /api/v1/auth/oidc/{provider}/callback
~~~

OIDC routes exist only when configured.

Host-local break-glass recovery is intentionally not a public API.

## User / RBAC APIs

~~~text
GET/POST       /api/v1/users
GET/PATCH      /api/v1/users/{id}
POST           /api/v1/users/{id}/disable
POST           /api/v1/users/{id}/enable
POST           /api/v1/users/{id}/password-reset

GET/POST       /api/v1/roles
GET/PATCH      /api/v1/roles/{id}

GET/POST       /api/v1/camera-groups
GET/PATCH      /api/v1/camera-groups/{id}

GET            /api/v1/sessions
DELETE         /api/v1/sessions/{id}

GET/POST       /api/v1/api-tokens
DELETE         /api/v1/api-tokens/{id}
~~~

Role/camera-scope mutation may use nested resource endpoints or one atomic role/user update contract. Do not create a generic policy language.

## Camera onboarding APIs

~~~text
POST   /api/v1/cameras/discovery
GET    /api/v1/cameras/discovery/{session_id}
POST   /api/v1/cameras/discovery/{session_id}/refresh

POST   /api/v1/cameras/test
POST   /api/v1/cameras

GET    /api/v1/cameras
GET    /api/v1/cameras/{id}
PATCH  /api/v1/cameras/{id}
POST   /api/v1/cameras/{id}/enable
POST   /api/v1/cameras/{id}/disable
POST   /api/v1/cameras/{id}/test
POST   /api/v1/cameras/{id}/refresh-capabilities
~~~

`POST /cameras/test` validates candidate ONVIF/RTSP configuration without creating a Camera.

Discovery produces candidates, never authoritative Cameras by itself.

## Camera stream APIs

~~~text
GET    /api/v1/cameras/{id}/streams
GET    /api/v1/cameras/{id}/stream-bindings
PUT    /api/v1/cameras/{id}/stream-bindings
~~~

Bindings use purposes:

~~~text
RECORD
LIVE_HIGH
LIVE_LOW
AI_DETECT
SNAPSHOT
AUDIO
~~~

Do not expose raw credential-bearing RTSP URLs in normal responses.

## Live media APIs

~~~text
POST   /api/v1/cameras/{id}/live
POST   /api/v1/cameras/{id}/snapshot
~~~

`/live` returns a short-lived playback descriptor:

~~~json
{
  "camera_id": "...",
  "purpose": "LIVE_LOW",
  "transport": "webrtc",
  "url": "...",
  "expires_at": "...",
  "fallbacks": [],
  "audio": false
}
~~~

The exact player URL may be ZLM-derived, but the browser obtains it only after zero-nvr authorization.

### PTZ

~~~text
POST   /api/v1/cameras/{id}/ptz/move
POST   /api/v1/cameras/{id}/ptz/stop
GET    /api/v1/cameras/{id}/ptz/presets
POST   /api/v1/cameras/{id}/ptz/presets/{preset}/goto
~~~

Only expose operations supported by the Camera capability.

Two-way talk endpoints are optional and capability-gated; they do not block V1 core.

## Recording policy APIs

~~~text
GET    /api/v1/cameras/{id}/recording-policy
PUT    /api/v1/cameras/{id}/recording-policy
~~~

The contract represents:

- continuous/scheduled/disabled baseline;
- event recording enabled/disabled;
- pre/post-roll;
- segment target;
- target/retention selection.

Do not expose RecordingIntent/RecordingSession CRUD because they are not canonical V1 entities.

## Manual / external recording trigger APIs

~~~text
POST   /api/v1/cameras/{id}/recording-triggers
GET    /api/v1/cameras/{id}/recording-triggers
POST   /api/v1/recording-triggers/{id}/stop
~~~

A manual trigger may have no planned end until stopped.

Home Assistant/API integrations use the same product path rather than directly commanding ZLM.

## Recording catalog APIs

~~~text
GET    /api/v1/cameras/{id}/recordings
GET    /api/v1/recordings/{segment_id}
GET    /api/v1/recordings/{segment_id}/locations
~~~

These are diagnostic/detail APIs.

The normal playback UI should prefer Timeline instead of loading thousands of raw five-minute segments.

## Timeline API

~~~text
GET /api/v1/cameras/{id}/timeline?from=<ISO8601>&to=<ISO8601>
~~~

Response is a derived read model:

~~~json
{
  "from": "2026-09-20T00:00:00Z",
  "to": "2026-09-21T00:00:00Z",
  "recording_ranges": [
    {
      "start_at": "...",
      "end_at": "...",
      "availability": "local"
    }
  ],
  "gaps": [
    {
      "start_at": "...",
      "end_at": "...",
      "reason": "source_lost"
    }
  ],
  "events": [
    {
      "id": "...",
      "start_at": "...",
      "end_at": "...",
      "category": "object",
      "label": "person"
    }
  ]
}
~~~

`recording_ranges` are merged wall-clock coverage, not a list of every physical segment.

Gap rows are projections and are not persisted as canonical tables.

## Playback resolve API

~~~text
POST /api/v1/cameras/{id}/playback/resolve
~~~

Request:

~~~json
{
  "at": "2026-09-20T12:34:56Z"
}
~~~

Playable response may include:

~~~json
{
  "status": "playable",
  "segment_id": "...",
  "segment_start_at": "...",
  "offset_ms": 12345,
  "transport": "mp4",
  "url": "...",
  "expires_at": "..."
}
~~~

Gap response:

~~~json
{
  "status": "gap",
  "reason": "source_lost",
  "previous_at": "...",
  "next_at": "..."
}
~~~

PlaybackResolver owns:

- RecordingLocation selection;
- local vs remote decision;
- remote restore/prefetch state;
- ZLM VOD descriptor generation.

Frontend does not implement storage selection.

## Multi-camera playback

Initial API may either:

- call each camera Timeline/Resolve endpoint independently; or
- provide a bounded batch endpoint.

If batching is required:

~~~text
POST /api/v1/playback/timeline
POST /api/v1/playback/resolve
~~~

The contract remains absolute-time based.

Do not persist a multi-camera playback session merely to synchronize UI clocks.

## Event APIs

~~~text
GET    /api/v1/events
GET    /api/v1/events/{id}
~~~

Filters include:

- camera;
- date range;
- source;
- category;
- label;
- zone;
- confidence;
- severity.

Events are provider-neutral.

Provider raw message APIs are internal integration concerns.

## Alert APIs

~~~text
GET/POST       /api/v1/alert-policies
GET/PATCH      /api/v1/alert-policies/{id}

GET            /api/v1/alerts
GET            /api/v1/alerts/{id}
POST           /api/v1/alerts/{id}/acknowledge
POST           /api/v1/alerts/{id}/resolve
~~~

AlertPolicy stays NVR-specific.

Do not expose generic expression/action-flow APIs.

## Notification APIs

~~~text
GET/POST       /api/v1/notification-targets
GET/PATCH      /api/v1/notification-targets/{id}
DELETE         /api/v1/notification-targets/{id}
POST           /api/v1/notification-targets/{id}/test
GET            /api/v1/notification-deliveries
~~~

SMTP is one NotificationTarget type and can also be selected as the system email/password-reset target.

## Recording protection APIs

~~~text
GET/POST       /api/v1/recording-protections
GET/PATCH      /api/v1/recording-protections/{id}
DELETE         /api/v1/recording-protections/{id}
~~~

Input is camera + wall-clock range + reason/optional expiry.

Protection never copies video to a second directory by itself.

## Export APIs

~~~text
POST   /api/v1/exports
GET    /api/v1/exports
GET    /api/v1/exports/{id}
DELETE /api/v1/exports/{id}
GET    /api/v1/exports/{id}/download
~~~

Export creation takes:

- camera;
- start/end ISO 8601;
- format;
- codec mode.

It returns a durable Export product record while Huey/FFmpeg does derived-media work.

## Storage APIs

~~~text
GET/POST       /api/v1/storage/targets
GET/PATCH      /api/v1/storage/targets/{id}
DELETE         /api/v1/storage/targets/{id}
POST           /api/v1/storage/targets/{id}/test

GET/POST       /api/v1/storage/retention-policies
GET/PATCH      /api/v1/storage/retention-policies/{id}
DELETE         /api/v1/storage/retention-policies/{id}

GET            /api/v1/storage/status
~~~

StorageTarget types:

~~~text
local
rclone
~~~

Normal users should not need to understand low-level rclone command flags.

OpenList-backed cloud drives appear through a configured rclone WebDAV remote.

## AI / Frigate APIs

~~~text
GET/POST       /api/v1/ai/providers
GET/PATCH      /api/v1/ai/providers/{id}
DELETE         /api/v1/ai/providers/{id}
POST           /api/v1/ai/providers/{id}/test
GET/PUT        /api/v1/ai/providers/{id}/camera-bindings
~~~

Managed mode may expose common zero-nvr-owned settings.

Advanced provider-specific configuration should prefer a bounded raw/advanced override rather than reproducing the full Frigate UI.

## Integration APIs

~~~text
GET            /api/v1/integrations
~~~

Specific integrations may add explicit bounded endpoints under:

~~~text
/api/v1/integrations/home-assistant
/api/v1/integrations/mqtt
~~~

Do not create an unrestricted generic command execution endpoint.

## Backup APIs

~~~text
GET/POST       /api/v1/backups/policies
GET/PATCH      /api/v1/backups/policies/{id}
GET            /api/v1/backups
POST           /api/v1/backups/run
POST           /api/v1/backups/{id}/verify
~~~

Normal UI may initiate a backup.

Clean-host disaster restore remains primarily a `deploy.sh restore` workflow because the web app may not be healthy.

A browser restore endpoint is not a V1 requirement.

## System APIs

~~~text
GET    /api/v1/system/info
GET    /api/v1/system/health
GET    /api/v1/system/settings
PATCH  /api/v1/system/settings
GET    /api/v1/system/update-info
~~~

Health returns current capability state, not historical telemetry samples.

Update-info is read-only guidance in V1; host mutation remains deploy.sh authority.

## Audit API

~~~text
GET /api/v1/audit
~~~

Cursor-paginated, filterable by:

- actor;
- action;
- resource;
- camera;
- date range;
- result.

Audit records are not editable through normal product APIs.

## Server-Sent Events

Use SSE for one-way live product state when it materially improves the UI.

Suggested endpoint:

~~~text
GET /api/v1/system/events/stream
~~~

Possible event classes:

- camera health change;
- recording state change;
- Alert created/resolved;
- Event created/updated;
- archive/Export progress;
- storage pressure;
- optional provider health.

SSE carries product state hints, not video media.

Clients must still re-fetch canonical resources after reconnect when correctness matters.

Do not introduce application WebSocket infrastructure unless a concrete bidirectional use case requires it.

## Internal ZLM hooks

Internal-only namespace:

~~~text
POST /internal/hooks/zlm/record-mp4
POST /internal/hooks/zlm/stream-changed
POST /internal/hooks/zlm/server-started
~~~

Only implement hooks actually supported/needed by the selected ZLM version.

Requirements:

- internal network exposure only where practical;
- shared secret/signature/token validation;
- idempotent handlers;
- fast acknowledgement;
- enqueue non-trivial work;
- no browser access;
- no assumption that a hook is guaranteed exactly once.

Lost hooks must be recoverable through reconciliation.

## Provider ingress

Frigate/MQTT/ONVIF integration runs through adapter consumers, not public raw-event endpoints.

If a webhook ingress is required:

~~~text
POST /internal/hooks/integrations/{provider}
~~~

with provider authentication and source-event idempotency.

## Backend modular-monolith layout

Recommended shape:

~~~text
backend/app/
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
~~~

Exact folder names may evolve; ownership/dependency direction should not.

## Module ownership

### auth

Owns:

- User/session;
- Role/permission/camera scope;
- password reset;
- Personal API Tokens;
- OIDC identity mapping;
- authorization dependencies.

Does not own Camera business state.

### cameras

Owns:

- Device;
- Camera;
- endpoint/credential references;
- discovery/onboarding;
- CameraStreamProfile/Binding;
- capability refresh;
- camera configuration.

### media

Thin ZLM-facing product service.

Owns no canonical media database.

Responsibilities:

- map Camera/binding -> ZLM runtime;
- live descriptor;
- snapshot;
- recorder adapter call;
- VOD descriptor;
- ZLM health/hooks/reconciliation helpers.

ZLM adapter implementation lives under integrations/zlm.

### recording

Owns:

- RecordingPolicy;
- RecordingTrigger;
- recording arbiter;
- RecordingSegment catalog;
- RecordingProtection;
- recording reconciliation entrypoints.

Does not own RTSP reconnect, MP4 writing, or archive file transfer.

### playback

Owns derived:

- Timeline;
- Gap;
- PlaybackResolver;
- wall-clock -> segment offset;
- remote playback-cache orchestration.

It reads RecordingSegment/RecordingLocation/Event and calls media/storage adapters.

It owns no Timeline/Gap table.

### events

Owns canonical Event normalization/query.

Provider adapters call this module.

It does not implement Frigate inference or ONVIF protocol mechanics.

### alerts

Owns AlertPolicy and Alert state.

Reads Event/system Events.

May request RecordingProtection through recording service.

Does not directly send SMTP/Telegram/etc.

### notifications

Owns NotificationTarget/NotificationDelivery.

Uses Apprise/provider adapters and Huey execution.

Password-reset mail can reuse notification delivery primitives without becoming a fake Alert.

### storage

Owns:

- StorageTarget;
- RecordingLocation copy lifecycle;
- retention decision service;
- local filesystem capacity projection;
- rclone archive/restore adapter orchestration.

It does not own RAID/ZFS/Btrfs/LVM or rclone internals.

### exports

Owns Export product state.

Uses PlaybackResolver and FFmpeg worker jobs.

Export output is derived asset, not RecordingLocation.

### backup

Owns BackupPolicy/BackupSet product state and orchestration.

Uses SQLite Online Backup/pg_dump + restic.

Clean-host restore remains deploy.sh accessible.

### system

Owns:

- product settings;
- health aggregation;
- system info/version;
- optional SSE aggregation.

It does not become Prometheus, Docker orchestrator, or NTP server.

### audit

Owns append-only AuditEvent write/query helpers.

Business modules call audit service for actor-driven sensitive changes.

## Dependency direction

Preferred direction:

~~~text
API router
  -> application/module service
      -> repository
      -> adapter interface
          -> integration implementation
~~~

Forbidden:

~~~text
Vue -> ZLM admin API
Vue -> Frigate admin API
domain model -> requests/httpx subprocess calls
repository -> camera network calls
integration adapter -> import API router
ZLM hook handler -> large synchronous archive/transcode work
~~~

## Cross-module calls

Use direct Python service calls inside the modular monolith.

Do not introduce:

- internal HTTP microservices;
- Kafka;
- RabbitMQ;
- service mesh;
- generic event bus

for V1 module-to-module communication.

Huey is used only when work is appropriately asynchronous/retryable.

## Transaction boundaries

Rules:

- keep DB transactions short;
- never hold a transaction across RTSP/ONVIF/ZLM/rclone/restic/FFmpeg/SMTP network/process work;
- reserve/create product state, commit, perform external work, then persist result;
- make external-operation completion idempotent.

This is especially important for SQLite.

## Adapter interfaces to freeze

V1 should have thin interfaces around:

~~~text
ZlmAdapter
OnvifAdapter
AIProvider / FrigateAdapter
RcloneAdapter
NotificationAdapter / Apprise
BackupRepository / Restic
OidcProvider
~~~

FFmpeg is normally invoked through focused export/media utility jobs rather than a giant generic adapter.

Do not build a universal plugin framework before these concrete boundaries work.

## Frontend module boundary

Frontend only talks to `/api/v1`.

Recommended top-level routes:

~~~text
/dashboard
/live
/playback
/events
/cameras
/storage
/system
~~~

Alerts appear in the global bell/drawer and dedicated filtered view where needed.

Work-context tabs are frontend/UI state and are not server tables.

Pinia should hold:

- auth/session summary;
- UI preferences;
- work tabs;
- live-grid state;
- small cached settings.

Do not mirror the entire backend database into one global store.

## Freeze acceptance

API/module design is ready when:

- all V1 UI workflows have a public zero-nvr API owner;
- no frontend workflow requires direct third-party API credentials;
- Timeline/Playback hide physical segment/storage mechanics;
- camera stream purpose binding is explicit;
- RecordingIntent/Session CRUD does not exist;
- Event/Alert/Notification concepts are not conflated;
- all remote file movement routes through storage/rclone adapter;
- normal recording routes through ZLM;
- background jobs route through Huey;
- clean-host restore and host mutation remain possible without the web UI;
- module-to-module calls stay in-process;
- public timestamps are consistently ISO 8601;
- internal hooks are idempotent/reconcilable.

Acceptance and POC completion are satisfied. The project is `V1 Architecture Frozen`; implementation must preserve these public/internal ownership contracts.
