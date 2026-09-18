# Technology Stack Baseline

Status: **recommended defaults, subject to implementation validation**

## Control plane

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL

Responsibilities:

- domain APIs;
- orchestration;
- policy;
- authorization;
- adapters;
- metadata persistence.

### Frontend

- Vue 3
- TypeScript
- Vite
- Element Plus initially unless a later UI-system decision replaces it

Responsibilities:

- Device Center;
- Live Monitor;
- Recording Timeline;
- Events;
- Alerts;
- Storage;
- System Health.

## Media plane

### ZLMediaKit

Default media engine for:

- RTSP ingest/proxy;
- stream reconnect;
- WebRTC;
- HTTP-fMP4;
- HLS;
- media runtime state;
- media webhooks.

### FFmpeg / ffprobe

Retained for:

- reliable recording backend during early V2;
- export;
- remux/transcode;
- media inspection;
- repair/compatibility tasks.

The goal is not to remove FFmpeg. The goal is to stop using FastAPI as a media server.

## Device plane

### ONVIF

Use a maintained ONVIF client library for SOAP/WSDL/WS-Security.

zero-nvr implements:

- adapter mapping;
- canonical device/profile/capability DTOs;
- event normalization;
- business policy.

zero-nvr does not implement a general ONVIF SOAP stack.

### HIK

Use the official/vendor SDK behind an isolated bridge process.

### GB28181

Future optional integration:

- WVP for SIP/device protocol;
- ZLMediaKit for media.

## Event / AI plane

Priority:

1. camera-native events;
2. vendor-native smart events;
3. optional external AI provider;
4. local lightweight detection where appropriate.

Optional AI provider:

- Frigate via integration boundary, not as the zero-nvr system of record.

Event bus/integration protocol may use MQTT where it meaningfully decouples external providers. MQTT is not mandatory for internal business calls.

## Integration plane

Home Assistant is a first-class optional integration target.

Loading model:

```text
Core zero-nvr
  → no HA dependency
  → no MQTT dependency

Enable HA REST integration
  → authenticated external-trigger API only

Enable HA deep integration
  → optional MQTT broker
  → MQTT Discovery/state/commands

Future HA Custom Integration
  → consumes stable zero-nvr API
```

The core deployment must remain fully functional when Home Assistant and MQTT are absent.

Home Assistant automations should send canonical external events/recording triggers. They must not directly control FFmpeg subprocesses or ZLMediaKit internals.

## Notification plane

Preferred generic notification integration:

- Apprise

Native adapters may still exist for channels that require zero-nvr-specific behavior.

## Storage plane

First-class:

- Local
- S3-compatible

Generic integrations:

- rclone
- OpenList

Storage adapters must expose verification semantics; upload success alone is insufficient for local purge eligibility.

## Database

### Production

PostgreSQL.

Reasons:

- multiple runtime/worker writers;
- strong relational integrity;
- richer indexing;
- JSONB for provider metadata;
- better growth path than SQLite for the target architecture.

### Development/testing

SQLite may be used selectively for lightweight unit tests if the affected behavior is database-portable.

PostgreSQL integration tests are required for PostgreSQL-specific behavior.

## Jobs

Worker implementation is intentionally not locked yet.

Candidate patterns:

- DB-backed durable job queue for a small deployment;
- Redis-backed worker when concurrency/throughput justifies it.

Job categories:

- upload;
- export;
- thumbnail/snapshot;
- notification;
- storage verification;
- retention;
- background media processing.

Long-running camera/media runtimes are not ordinary queue jobs.

## Observability

Initial:

- structured application logs;
- health/readiness endpoints;
- runtime state APIs.

Later:

- Prometheus-compatible metrics;
- OpenTelemetry tracing where useful;
- Grafana optional.

## Deployment

Initial:

- Docker Compose on Linux.

Do not make Kubernetes a V2 prerequisite.

## Deliberately deferred choices

The following should be validated before being locked:

- final recording container/segment format;
- exact task queue implementation;
- exact live-player protocol priority under all browsers;
- ZLM-native recorder vs FFmpeg recorder;
- cache implementation for remote playback;
- multi-node media topology.
