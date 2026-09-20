# ADR 0008 — Persist Product Facts, Derive Runtime/Projection State

Status: **accepted**

## Context

Earlier architecture drafts accumulated many tables for state that is either:

- directly owned by another mature component;
- cheaply derived from durable facts;
- short-lived runtime state;
- query/read-model projection;
- task-execution detail already owned by Huey.

Examples included:

- RecordingIntent;
- RecordingSession;
- PrebufferFragment metadata as mandatory business state;
- RetentionClaim;
- StorageObject + UploadJob;
- DetectionObservation;
- EventFusionGroup;
- HealthSample;
- SourceConnectivityIncident;
- EventLog;
- AlertIncident / EscalationPolicy / ActionSet / per-attempt delivery tables;
- UpgradePlan.

Keeping all of these as first-class V1 entities would increase write amplification, schema complexity, SQLite pressure, recovery complexity, and duplicate ownership.

## Decision

V1 persists **product facts** and derives runtime/projection state whenever practical.

Canonical durable recording/event/storage facts include:

~~~text
Camera
CameraStreamProfile / Binding
RecordingPolicy
RecordingTrigger
RecordingSegment
RecordingLocation
RetentionPolicy
RecordingProtection
Event
AlertPolicy
Alert
NotificationTarget
NotificationDelivery
User / Role / CameraScope
AuditEvent
StorageTarget
Backup metadata
~~~

Examples of derived/runtime state:

~~~text
should_record
current active recording reasons
current camera/media health
Timeline
Gap
merged recording ranges
current provider connectivity
current ZLM stream/recorder state
archive worker execution lease/retry scheduling
playback cache
thumbnail cache
live transcode process state
~~~

### Recording

The current recorder requirement is derived from:

~~~text
RecordingPolicy
+ current schedule time
+ active RecordingTriggers
+ observed ZLM recorder/media state
~~~

V1 does not require persisted RecordingIntent or RecordingSession tables.

### Timeline

Timeline and Gap are projections over:

~~~text
RecordingSegment coverage
+ Event markers
+ retention/location availability
+ known policy/system-event context
~~~

They are not authoritative tables.

### Health

Current health is obtained from adapters/services and may live in memory.

Meaningful state transitions are persisted as canonical system Events when product history/alerting needs them.

Do not write periodic HealthSample rows into SQLite merely to power the dashboard.

### Archive

Huey owns job execution/retry scheduling.

RecordingLocation owns product-visible archive-copy state.

Do not duplicate Huey with a generic UploadJob business table.

### AI events

Provider messages normalize into canonical Event.

V1 does not require raw DetectionObservation history or generic cross-provider fusion tables unless a concrete product need later proves they are necessary.

### Alerts

V1 persists Alert and NotificationDelivery product state.

Do not build enterprise incident/escalation/action-set schemas unless real product requirements appear.

## Consequences

Positive:

- smaller SQLite write volume;
- smaller schema/migration surface;
- fewer contradictory sources of truth;
- easier restart/reconciliation;
- clearer ownership boundaries;
- simpler backup/restore;
- lower implementation cost.

Trade-off:

- some runtime state must be recomputed after restart;
- diagnostics rely on canonical Events/logs rather than exhaustive internal-state history;
- future features may justify promoting a derived concept into a persisted entity.

## Promotion rule

A derived/runtime concept becomes a V1+ persisted entity only when all are true:

1. a user-visible product workflow requires historical identity/state that cannot be reconstructed reliably;
2. the existing canonical facts are insufficient;
3. persistence materially improves correctness rather than merely convenience;
4. the new entity has one clear owner;
5. write/storage cost is acceptable for SQLite;
6. an ADR/schema change documents the reason.

Do not add a table simply because a concept appears in a sequence diagram.

## Invariants

1. Business database stores durable product facts, not every runtime transition.
2. Mature external component runtime is observed through adapters, not duplicated in product tables.
3. Query projections are rebuilt from canonical facts.
4. High-frequency telemetry is not stored in the business SQLite database.
5. Background queue internals are not re-modeled as product job tables without a user-visible state requirement.
6. Any new persistent runtime/projection entity requires demonstrated product value after architecture freeze.
