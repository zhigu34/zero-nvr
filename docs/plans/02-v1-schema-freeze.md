# Plan 02 — V1 Schema Freeze

Status: **accepted / frozen for V1**


Accepted by [ADR 0011 — V1 Architecture Freeze](../adr/0011-v1-architecture-freeze.md). Post-freeze additions to canonical V1 tables follow the change-control and ADR 0008 promotion rules below.
## Goal

Freeze the V1 persistence boundary before backend model/Alembic implementation begins.

This document applies ADR 0008:

> Persist durable product facts. Derive runtime/projection/task state whenever practical.

It does **not** freeze every column forever. It freezes entity ownership and the set of concepts that are allowed to become canonical V1 tables.

Any new V1 table added after this freeze must answer:

1. what durable user-visible fact does it preserve?
2. why can that fact not be derived from existing canonical rows?
3. who owns it?
4. what is its SQLite write/storage cost?
5. does it duplicate a mature component runtime?

## Naming conventions

Database table names use snake_case plural names.

Python domain/model names remain singular PascalCase.

Examples:

~~~text
CameraStreamProfile -> camera_stream_profiles
RecordingLocation   -> recording_locations
NotificationDelivery -> notification_deliveries
~~~

## ID strategy

Use application-generated opaque IDs so SQLite/PostgreSQL migration never depends on backend autoincrement semantics.

Recommended implementation:

- UUID/UUIDv7-compatible application IDs;
- SQLAlchemy type abstraction may use native PostgreSQL UUID and SQLite text representation;
- API treats IDs as opaque strings.

Do not expose sequential database row numbers as durable product identity.

## Time strategy

Canonical timestamps:

- stored in UTC;
- represented by timezone-aware application datetime values;
- API emits ISO 8601 with timezone;
- SQLite representation must round-trip the same instant as PostgreSQL.

Wall-clock schedules also store an explicit timezone where user intent depends on local time.

## JSON strategy

Use JSON only for:

- bounded provider metadata;
- configuration whose schema is owned by an adapter;
- sanitized diagnostic details.

Do not hide core relations, permissions, time ranges, state, or searchable first-class fields inside JSON merely to avoid schema design.

## Core tables

### Identity and authorization

#### users

Required.

Key facts:

~~~text
id
username UNIQUE
display_name
email
password_hash
enabled
last_login_at
created_at
updated_at
~~~

Email verification fields may be added if self-service recovery policy requires them.

#### roles

~~~text
id
name UNIQUE
description
built_in
~~~

#### role_permissions

~~~text
role_id
permission
PRIMARY KEY(role_id, permission)
~~~

#### user_roles

~~~text
user_id
role_id
PRIMARY KEY(user_id, role_id)
~~~

#### camera_groups

~~~text
id
name
description
parent_id nullable
~~~

Hierarchy is optional; do not require recursive group complexity if flat groups satisfy V1.

#### camera_group_members

~~~text
camera_group_id
camera_id
PRIMARY KEY(camera_group_id, camera_id)
~~~

#### principal_camera_scopes

Represents whether one principal has all/selected/none camera access.

~~~text
id
principal_type
principal_id
scope_mode
~~~

#### principal_camera_scope_entries

Only for selected groups/cameras.

~~~text
scope_id
camera_id nullable
camera_group_id nullable
~~~

Constraint: exactly one target kind per row.

#### user_sessions

Required for revocation.

~~~text
id
user_id
created_at
last_seen_at
expires_at
revoked_at
client_info
~~~

#### password_reset_tokens

Verifier-only.

~~~text
id
user_id
token_hash UNIQUE
requested_at
expires_at
used_at
request_metadata
created_by nullable
~~~

#### personal_api_tokens

~~~text
id
user_id
name
token_hash UNIQUE
permission_scope
created_at
expires_at nullable
last_used_at nullable
revoked_at nullable
~~~

#### secret_records

Recoverable encrypted credentials.

~~~text
id
kind
owner_type
owner_id
key_id
encrypted_payload
version
created_at
updated_at
~~~

The product master/keyring secret is not stored in this table.

### Device and camera inventory

#### devices

Represents a physical/network device that may expose multiple Camera channels.

~~~text
id
name
manufacturer
model
serial_number
hardware_id
adapter_type
enabled
capabilities_json
capabilities_updated_at
created_at
updated_at
~~~

Unique stable identity constraints are adapter/evidence dependent; do not use IP address as primary identity.

#### device_endpoints

~~~text
id
device_id
type
host
port
scheme
path
priority
enabled
last_verified_at
metadata
~~~

#### device_credentials

Maps a device/endpoint purpose to a SecretRecord.

~~~text
id
device_id
endpoint_id nullable
kind
secret_ref
created_at
updated_at
~~~

#### discovery_sessions

Short-lived but useful persisted onboarding workflow state.

~~~text
id
method
started_at
completed_at
status
created_by
~~~

Retention may purge old discovery sessions.

#### discovery_candidates

~~~text
id
discovery_session_id
candidate_key
host
device_identity
display_info
state
metadata
~~~

Discovery candidates are not Cameras until explicitly validated/onboarded.

#### cameras

Stable monitoring/channel identity.

~~~text
id
device_id nullable
channel_key
name
enabled
location
storage_label
created_at
updated_at
~~~

Suggested uniqueness:

~~~text
(device_id, channel_key)
~~~

when device_id is present.

#### camera_stream_profiles

Source capabilities/profiles.

~~~text
id
camera_id
adapter_profile_key
video_source_key
name
codec
width
height
fps
bitrate_kbps
gop_seconds
audio_codec
has_audio
stream_uri_ref
status
last_verified_at
metadata
~~~

Suggested unique identity:

~~~text
(camera_id, adapter_profile_key)
~~~

where the adapter provides a stable key.

#### camera_stream_bindings

Business purpose -> source profile.

~~~text
id
camera_id
purpose
stream_profile_id
selection_mode
updated_at
~~~

Required unique constraint:

~~~text
UNIQUE(camera_id, purpose)
~~~

Purposes:

~~~text
RECORD
LIVE_HIGH
LIVE_LOW
AI_DETECT
SNAPSHOT
AUDIO
~~~

AUDIO row is optional when no separate audio profile binding is needed.

### User UI preference

#### live_view_layouts

User-saved grid/layout state.

~~~text
id
owner_user_id
name
is_default
layout_json
created_at
updated_at
~~~

This is durable user preference, not media runtime state.

### Product settings

#### system_settings

Use one namespaced product-settings table rather than one table per small settings category.

~~~text
namespace PRIMARY KEY
value_json
updated_at
~~~

Initial namespaces may include:

~~~text
general
time
recording_defaults
email
security
ui
~~~

Secrets are still referenced through SecretRecord/NotificationTarget rather than embedded as plaintext.

Do not use system_settings to hide relational business entities.

## Recording and storage

#### recording_policies

One effective policy per Camera unless future group inheritance proves necessary.

~~~text
id
camera_id UNIQUE
baseline_mode
schedule_json
schedule_timezone
event_recording_enabled
event_filter_json
segment_target_seconds
pre_roll_seconds
post_roll_seconds
storage_target_id nullable
retention_policy_id nullable
enabled
created_at
updated_at
~~~

Interpretation:

- continuous baseline;
- scheduled baseline;
- EVENT_ONLY = baseline disabled + event recording enabled;
- fully disabled = both disabled.

#### retention_policies

~~~text
id
name
scope_type
scope_id nullable
ordinary_keep_days
event_keep_days
manual_keep_days
mode
require_archive_before_delete
enabled
created_at
updated_at
~~~

Avoid a RetentionClaim table in V1.

#### recording_protections

Range-based explicit hold.

~~~text
id
camera_id
started_at
ended_at
reason
created_by
expires_at nullable
created_at
updated_at
~~~

Indexes must support overlap queries by camera/time.

#### recording_triggers

Durable event/manual/external recording request.

~~~text
id
camera_id
type
source
source_event_id nullable
requested_at
pre_roll_seconds
post_roll_seconds
planned_start_at
planned_end_at nullable
state
reason nullable
correlation_id
metadata
created_at
updated_at
~~~

Useful idempotency/lookup index:

~~~text
(source, source_event_id)
~~~

when source_event_id exists.

#### recording_segments

Finalized media facts.

~~~text
id
camera_id
stream_profile_id nullable
started_at
ended_at
duration_ms
timing_status                 PROVISIONAL | FINAL
timing_source                 HOOK_RAW | NEXT_SEGMENT_BOUNDARY | EXPLICIT_STOP | RECOVERY
recording_reasons_json
size_bytes
codec
container
source_media_server_id
source_app
source_stream
integrity_status
completion_reason
created_at
~~~

Required indexes:

~~~text
(camera_id, started_at)                         # Timeline/range reads
(camera_id, ended_at, started_at, id)          # oldest-first retention scan
~~~

The retention index is intentionally covering enough segment identity/time columns to let SQLite drive deletion-candidate scans from camera + end time instead of scanning every AVAILABLE location first.

Use actual finalized times. Never infer exact 300-second duration.

#### storage_targets

V1 recording/archive destinations.

~~~text
id
type                          local | rclone
role                          recording | archive
name
enabled
config_json
credential_secret_ref nullable
created_at
updated_at
~~~

Current capacity/health is derived/observed runtime state; do not update the row every few seconds solely for telemetry.

#### recording_locations

One physical canonical copy of one RecordingSegment.

~~~text
id
recording_segment_id
storage_target_id
object_path
state
size_bytes
checksum nullable
verified_at nullable
last_attempt_at nullable
last_error nullable
created_at
deleted_at nullable
~~~

Required indexes/constraints:

~~~text
UNIQUE(storage_target_id, object_path)
(recording_segment_id, storage_target_id, state)
(storage_target_id, state, recording_segment_id)
~~~

The first composite supports point lookup of the physical copy while scanning RecordingSegments in retention order. The second supports target/state inventory and recovery work. Avoid forcing SQLite to choose between two large uncorrelated partial indexes for retention.

States:

~~~text
AVAILABLE
ARCHIVING
FAILED
DELETING
DELETED
MISSING
~~~

No generic StorageObject table.

## Events, alerts, notifications

#### events

One canonical product Event.

~~~text
id
source
source_instance_id nullable
source_event_id nullable
camera_id nullable
category
label nullable
started_at
ended_at nullable
confidence nullable
severity nullable
zone nullable
snapshot_ref nullable
correlation_id nullable
metadata
created_at
updated_at
~~~

Provider idempotency constraint should be scoped by source instance:

~~~text
UNIQUE(source, source_instance_id, source_event_id)
~~~

where source_event_id exists.

Indexes:

~~~text
(camera_id, started_at)
(source, started_at)
(category, started_at)
~~~

Avoid raw DetectionObservation/EventFusion tables in V1.

#### alert_policies

~~~text
id
name
enabled
camera_scope_json
event_categories_json
labels_json
zones_json
min_confidence nullable
min_duration nullable
severities_json
active_schedule_json
schedule_timezone nullable
cooldown_seconds
notification_target_ids_json
protect_recording
publish_webhook_or_mqtt
created_at
updated_at
~~~

If policy-target relation becomes complex, introduce a small join table instead of an expression engine.

#### alerts

~~~text
id
alert_policy_id
event_id
camera_id nullable
severity
title
message
state
opened_at
last_activity_at
acknowledged_at nullable
acknowledged_by nullable
resolved_at nullable
correlation_id nullable
created_at
updated_at
~~~

#### notification_targets

~~~text
id
name
type
enabled
config_json
credential_secret_ref nullable
health_state
last_test_at nullable
last_error nullable
created_at
updated_at
~~~

SMTP is represented here rather than in a dedicated SMTP table.

#### notification_deliveries

~~~text
id
alert_id nullable
purpose                       alert | password_reset | security | system_test
notification_target_id
state
attempt_count
last_attempt_at nullable
sent_at nullable
last_error nullable
provider_message_id nullable
correlation_id nullable
created_at
updated_at
~~~

Password-reset delivery may reference its workflow through correlation_id/metadata rather than requiring a fake Alert.

Huey owns retry execution.

## Derived media

#### exports

~~~text
id
user_id
camera_id
started_at
ended_at
format
codec_mode
state
output_path
size_bytes nullable
expires_at nullable
completed_at nullable
error_code nullable
sanitized_error nullable
created_at
updated_at
~~~

Export output is a derived asset, not a RecordingLocation.

## Optional integration tables

These tables exist only when the feature is compiled/enabled in the product schema, but they do not add mandatory runtime services.

### external_identities

OIDC account link.

~~~text
id
user_id
issuer
subject
email
created_at
last_login_at
~~~

Constraint:

~~~text
UNIQUE(issuer, subject)
~~~

### ai_provider_instances

V1 provider type: Frigate.

~~~text
id
type
mode                          managed | external
name
enabled
config_json
credential_secret_ref nullable
created_at
updated_at
~~~

Current provider health is derived runtime state.

### ai_provider_camera_bindings

~~~text
id
provider_instance_id
camera_id
external_camera_key
enabled
~~~

Constraints:

~~~text
UNIQUE(provider_instance_id, external_camera_key)
UNIQUE(provider_instance_id, camera_id)
~~~

## Backup and audit

#### backup_policies

~~~text
id
name
enabled
repository_config_ref
credential_secret_ref nullable
database_backend
schedule
retention_policy_json
verify_after_backup
repository_check_schedule
include_deployment_config
created_at
updated_at
~~~

restic owns repository snapshots/dedup/encryption internals.

#### backup_sets

Product-visible history of backup runs/recovery points.

~~~text
id
backup_policy_id
state
reason
started_at
completed_at nullable
app_version
schema_revision
database_engine
restic_snapshot_id nullable
size_bytes nullable
verification_state
last_verified_at nullable
error_code nullable
sanitized_error nullable
created_at
updated_at
~~~

### audit_events

~~~text
id
occurred_at
actor_type
actor_id nullable
action
resource_type
resource_id nullable
camera_id nullable
request_id nullable
correlation_id nullable
source_ip nullable
client_info nullable
result
reason nullable
before_json nullable
after_json nullable
metadata nullable
created_at
~~~

Append-oriented. Sensitive values are redacted before insertion.

## Explicit non-tables in V1

The following concepts must **not** become canonical tables merely because older documents used them:

~~~text
Timeline
Gap
HealthSample
CameraRuntimeStatus
RuntimeGeneration
MediaSession
PlaybackSession
TalkSession

RecordingIntent
RecordingSession
RecordingSessionSegment
PrebufferFragment              # unless the accepted POC later proves durable indexing is required
RetentionClaim

StorageObject
UploadJob
rclone job/lease

DetectionObservation
DetectionPolicy
EventZoneInterval
EventFusionGroup
EventFusionMember
SourceConnectivityIncident
EventLog

AlertSignal
AlertIncident
AlertIncidentSource
EscalationPolicy
EscalationStep
AlertActionSet
AlertAction
RecipientGroup
AlertSilence
AlertDeliveryAttempt

UpgradePlan
UpgradeHistory
DataMigrationJob
DatabaseMigrationPlan

BackupManifest                 # artifact inside backup payload
RecoveryKit                    # external protected recovery artifact

Thumbnail
PlaybackCacheEntry
RcloneCacheEntry
LiveTranscodeSession

ZLM raw config/runtime rows
Frigate raw event/message rows
high-frequency metric/telemetry rows
~~~

A future feature may promote one of these to a persisted entity only through the ADR 0008 promotion rule.

## Foreign-key deletion policy

Default:

- protect historical facts;
- avoid cascading deletion of Camera into RecordingSegment/Event/Audit rows;
- use disable/archive semantics for long-lived entities;
- allow cascade only for clearly subordinate configuration rows with no independent historical meaning.

Examples:

~~~text
Camera delete -> normally blocked/archived if recordings/events exist
RecordingSegment delete -> does not automatically mean physical file was successfully deleted
StorageTarget delete -> blocked while unique retained RecordingLocations exist
User delete -> disable/anonymize policy must preserve AuditEvent references
~~~

## SQLite write budget principles

To keep SQLite first-class:

- no periodic health-sample insertion;
- no raw AI-update append log;
- no per-frame/per-packet data;
- no queue lease table owned by zero-nvr when Huey already handles it;
- batch non-critical last_seen/health timestamps where useful;
- use idempotent UPSERTs for provider Event updates;
- keep archive/delivery state transitions coarse.

The 8-camera/16-camera POC validates the resulting write pattern and retention-query plan. Large bulk imports or engine migrations must refresh SQLite planner statistics (`ANALYZE` / `PRAGMA optimize` as appropriate) before relying on cost-based join ordering.

## Schema-freeze acceptance

Before backend ORM migration work is declared ready:

- every canonical table above has an owner and reason;
- all old prohibited table names are absent from implementation plans;
- SQLite and PostgreSQL can represent the schema without feature forks;
- required unique/idempotency constraints are defined;
- recording/event timeline indexes are defined;
- secret plaintext has no business-table column;
- no media path is stored directly on RecordingSegment;
- no raw third-party event/config database is duplicated;
- no high-frequency telemetry table exists;
- Export is modeled separately from canonical recording copies.

After this point, adding a new canonical table requires an explicit schema/design review and, for ownership changes, an ADR.
