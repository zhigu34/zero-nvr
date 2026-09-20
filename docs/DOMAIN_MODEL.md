# Canonical Domain Model

This document defines the initial business entities that external components must map into.

## Identity principle

A Camera represents a stable monitoring point.

Changing ONVIF credentials, replacing an RTSP URL, switching adapter implementations, or moving media runtime must not silently create a new Camera identity.

## User

Local interactive account.

```text
id
username
display_name
email
email_verified_at
password_hash
enabled
must_change_password
last_login_at
created_at
updated_at
```

Passwords are stored only as modern password hashes; initial recommendation is Argon2id.

## Role

```text
id
name
description
built_in
created_at
updated_at
```

## RolePermission

```text
role_id
permission
```

## UserRole

```text
user_id
role_id
```

## CameraGroup

```text
id
name
description
created_at
updated_at
```

## CameraGroupMember

```text
camera_group_id
camera_id
```

A Camera may belong to multiple CameraGroups.

## PrincipalCameraScope

```text
principal_type
principal_id
scope_mode      all | selected_groups | selected_cameras | none
created_at
updated_at
```

## PrincipalCameraScopeEntry

```text
principal_type
principal_id
camera_id
camera_group_id
```

A camera-scoped action requires both the relevant permission and effective Camera scope.

## UserSession

```text
id
user_id
created_at
last_seen_at
expires_at
revoked_at
client_info
```

Interactive sessions are revocable. Disabling a User revokes active sessions.


## PasswordResetToken

```text
id
user_id
token_hash
requested_at
expires_at
used_at
requested_ip
created_by_actor_id
```

Only the reset-token hash is persisted. Reset tokens are expiring and single-use.

## PersonalApiToken

~~~text
id
user_id
name
token_hash
permission_scope
created_at
expires_at
last_used_at
revoked_at
~~~

The plaintext token is shown only at creation and is never persisted.

TOTP MFA is an optional enhancement rather than a required V1 entity. If added later, use a mature OTP library, SecretStore for the TOTP secret, and one-way hashes for recovery codes.

## ExternalIdentity

```text
id
user_id
provider
issuer
subject
email
created_at
last_login_at
```

OIDC/SSO identities map to the existing User/Role/Permission/CameraScope authorization model.

See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](specs/0011-auth-authorization-and-audit.md).

## Device

Represents one managed physical/network appliance. A Device may expose one or many Camera channels.

```text
id
display_name
adapter
manufacturer
model
firmware_version
serial_number
hardware_id
stable_device_uid
enabled
onboarding_state
last_probe_at
last_seen_at
created_at
updated_at
```

Network address is not the primary identity.

## DeviceEndpoint

```text
id
device_id
scheme
host
port
path
adapter
priority
status
last_verified_at
created_at
updated_at
```

A DHCP/address change updates endpoint data without recreating the Device/Camera when stable identity proves continuity.

## DeviceCredential

```text
device_id
credential_kind
secret_ref
verification_status
verified_at
updated_at
```

Credential plaintext lives only behind SecretStore.

## DiscoverySession

```text
id
requested_by
adapters
interfaces
target_ranges
state
started_at
completed_at
candidate_count
error_summary
```

## DiscoveryCandidate

Temporary discovery result; never authoritative Camera state.

```text
id
discovery_session_id
adapter_hint
endpoint
device_uid_hint
manufacturer_hint
model_hint
channel_count_hint
matched_device_id
match_confidence
state
first_seen_at
last_seen_at
metadata
```

## Camera

Logical video source/channel owned by or associated with a Device.

```text
id
device_id
channel_key
name
enabled
location
manufacturer
model
form_factor
storage_label
created_at
updated_at
```

A multi-channel NVR/DVR or multi-sensor camera therefore owns several Camera rows while retaining one Device identity.

Changing stream/profile selection does not create a new Camera identity.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](specs/0018-camera-onboarding-discovery-and-stream-selection.md).


## SmtpSettings

System-level SMTP/email delivery configuration.

```text
enabled
host
port
security_mode              starttls | tls | none
username
credential_secret_ref
from_address
from_name
reply_to
timeout_seconds
enabled_for_password_reset
enabled_for_alerts
updated_at
```

SMTP credential material is stored behind SecretStore.

SMTP is a first-production-release platform capability used by password reset, security/account notifications, alerts, and system/storage health notifications.

Operational behavior includes connection testing, test email, queued delivery, transient retry/backoff, sanitized errors, and final delivery-result tracking.

See [Spec 0013 — First Production Release Scope and Completeness Policy](specs/0013-first-production-release-scope.md).

## SystemTimeSettings

System-level time and managed-camera synchronization defaults.

```text
recording_timezone
managed_camera_ntp_mode       manual | dhcp
managed_camera_ntp_servers
clock_warning_threshold_ms
clock_critical_threshold_ms
updated_at
```

`managed_camera_ntp_servers` is an ordered list of NTP hostnames/IPs used when a camera is configured with `time_sync_mode = manage_ntp` and has no camera-specific override.

This configuration does not automatically reconfigure the zero-nvr host's own OS time service. Host NTP/time-sync state is monitored separately.

See [Spec 0009 — Canonical Time, Camera Clock Offset, and Timezone Handling](specs/0009-time-and-camera-clock.md).

## CameraClockStatus

Current normalized view of a camera/device clock relative to zero-nvr canonical time.

```text
camera_id
offset_ms
uncertainty_ms
measured_at
device_timezone
device_time_source
sync_mode
ntp_override_mode
ntp_servers_override
health
```

Possible sync modes:

```text
monitor
manage_ntp
ignore
```

Possible health values:

```text
unknown
healthy
warning
critical
unsupported
```

Camera clock status is used for device-originated timestamp normalization and clock-health UI. It does not shift RecordingSegment time or Playback Master Clock.

See [Spec 0009 — Canonical Time, Camera Clock Offset, and Timezone Handling](specs/0009-time-and-camera-clock.md).

## CameraClockSample

Historical/diagnostic measurement of device clock offset.

```text
camera_id
sampled_at
device_utc_at_sample
device_local_at_sample
device_timezone
device_time_source
round_trip_ms
offset_ms
uncertainty_ms
quality
metadata
```

Offset measurement should account for request round-trip time rather than comparing only against response receipt time.

## SecretRecord

Encrypted recoverable secret managed by SecretStore.

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

Use a mature authenticated-encryption library such as Python cryptography/Fernet/MultiFernet or equivalent. V1 does not require per-record DEK/KEK envelope encryption.

The encryption key/keyring is deployment bootstrap state outside the active product database.

Business rows reference secrets through opaque secret_ref fields. Normal APIs never return SecretRecord plaintext.

Verifier-only credentials such as User passwords, Personal API Tokens, and password-reset tokens use one-way hashing instead.

See [Spec 0012 — Configuration and Secret Storage](specs/0012-config-secrets-key-management.md).

## Camera connection resolution

Camera connection details are resolved through DeviceEndpoint + DeviceCredential and adapter configuration.

This is not a separate canonical table.

Supported V1 adapter paths include:

~~~text
onvif
manual_rtsp
~~~

Optional vendor/GB28181 adapters may later resolve through the same Device/Camera identity without changing this model.

Credentials are referenced through SecretStore and never duplicated into public read models.

## CameraStreamProfile

One discovered/verified source stream profile exposed by the Camera/device.

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
bitrate_mode
gop_seconds
audio_codec
has_audio
stream_uri_ref
status
discovered_at
last_verified_at
metadata
~~~

CameraStreamProfile describes source capability/identity. It does not say why zero-nvr uses the stream.

A profile may satisfy several business purposes.

## DeviceCapabilitySnapshot

```text
device_id
probed_at
supports_events
event_types
supports_ptz
ptz_features
supports_snapshot
supports_audio
supports_two_way_audio
supports_time_read
supports_time_write
supports_ntp_config
supports_profile_management
supports_reboot
vendor_capabilities
adapter_version
```

## CameraStreamBinding

Maps one business purpose to one CameraStreamProfile.

~~~text
id
camera_id
purpose                       RECORD | LIVE_HIGH | LIVE_LOW | AI_DETECT | SNAPSHOT | AUDIO
stream_profile_id
selection_mode                auto | manual
selected_at
updated_at
~~~

Typical defaults:

~~~text
RECORD      -> primary/main
LIVE_HIGH   -> primary/main
LIVE_LOW    -> secondary/sub
AI_DETECT   -> secondary/sub
SNAPSHOT    -> primary/main
AUDIO       -> profile with required audio capability
~~~

One CameraStreamProfile may satisfy several purposes.

The MediaPlane/ZlmAdapter resolves a binding into transient ZLM runtime identifiers. Permanent browser URLs and current ZLM stream registration are not domain truth.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](specs/0018-camera-onboarding-discovery-and-stream-selection.md).

## Runtime camera status (derived, not a table)

Reconstructable runtime read model:

~~~text
camera_id
desired_state                 enabled | disabled | maintenance
config_revision
applied_revision
control_health
media_health
recording_health
event_health
ptz_health
clock_health
ai_health
last_transition_at
last_error
~~~

Current runtime generation/revision may be kept in memory or adapter state to fence stale callbacks. V1 does not require a RuntimeGeneration table.

Overall Camera health is a UI summary only; capability-specific health remains independently observable.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](specs/0019-device-runtime-lifecycle-and-reconfiguration.md).

## MediaSession (runtime, not a canonical table)

A short-lived authorized live-view descriptor/session may contain:

~~~text
principal/user
camera_id
requested purpose/quality
effective CameraStreamBinding
transport
source/delivery codec
short expiry
optional runtime token/id
~~~

It may be represented by a signed/opaque token plus in-memory state rather than a persisted table.

It never exposes camera credentials or a permanent bearer URL.

Two-way talk, when supported, is another short-lived authorized runtime capability. V1 does not require a TalkSession table unless the eventual implementation needs durable concurrency/audit state.

See [Spec 0020 — Live View, Media Sessions, Compatibility, Audio, and Optional Talk](specs/0020-live-view-media-session-and-talk.md).

## LiveViewLayout

Per-user saved live-monitor layout.

```text
id
owner_user_id
name
is_default
grid_definition
created_at
updated_at
```

Layouts reference Camera IDs and presentation preferences, never permanent media URLs.

See [Spec 0020 — Live View, Media Sessions, Adaptive Quality, TURN, and Talk](specs/0020-live-view-media-session-and-talk.md).

## RecordingPolicy

Describes the durable recording policy for one Camera.

The policy intentionally separates baseline recording from event-triggered recording so EVENT_ONLY and hybrid behavior do not require mutually exclusive mode tables.

```text
id
camera_id
baseline_mode                 continuous | schedule | disabled
schedule                      nullable
schedule_timezone             nullable
event_recording_enabled
event_filter                   nullable JSON/object: labels/zones/confidence/types
segment_target_seconds        default 300
pre_roll_seconds              default 10
post_roll_seconds             default 10
storage_target_id             nullable -> system default LOCAL_RECORDING target
retention_policy_id
enabled
created_at
updated_at
```

Interpretation:

```text
CONTINUOUS:
  baseline_mode = continuous

SCHEDULE:
  baseline_mode = schedule

EVENT_ONLY:
  baseline_mode = disabled
  event_recording_enabled = true

SCHEDULE + out-of-window event recording:
  baseline_mode = schedule
  event_recording_enabled = true

DISABLED:
  baseline_mode = disabled
  event_recording_enabled = false
```

The nominal segment duration is a target, not timeline truth. Actual RecordingSegment timestamps come from finalized media metadata.

The requested EVENT_ONLY pre-roll is product policy; its physical implementation is design-freeze POC gated and is not represented by a mandatory PrebufferFragment table.

## RetentionPolicy

Defines how long canonical recordings/copies should remain and when local deletion is legal.

```text
id
name
scope_type                    global | camera_group | camera
scope_id                      nullable
ordinary_keep_days
event_keep_days
manual_keep_days
mode                          best_effort | hard
require_archive_before_delete
enabled
created_at
updated_at
```

Deletion eligibility is derived from the policy, overlapping Events/RecordingTriggers, RecordingProtection ranges, RecordingLocation state, and current disk pressure.

V1 does not require a per-segment RetentionClaim table merely to cache derivable retention facts.

## RecordingProtection

Explicitly protects a camera/time range from automatic retention deletion.

```text
id
camera_id
started_at
ended_at
reason
created_by
expires_at                    nullable
created_at
updated_at
```

Typical reasons:

```text
manual_lock
incident
legal_hold
user_saved
system_recovery
```

Protection is metadata. zero-nvr does not copy footage into a separate protected-video directory just to retain it.

## RecordingTrigger

Represents a durable event/manual/external request that affects recording behavior.

```text
id
camera_id
type                          motion | ai_object | onvif_event | vendor_event | home_assistant | api | manual
source
source_event_id               nullable
requested_at
pre_roll_seconds
post_roll_seconds
planned_start_at
planned_end_at                nullable for manual-until-stop
state                         active | completed | cancelled | ignored | failed
reason                        nullable
correlation_id
metadata
created_at
updated_at
```

RecordingTrigger records product intent/evidence, not a recorder process.

Continuous and scheduled requirements are derived from RecordingPolicy and wall-clock time. Event/manual/API requirements are derived from active RecordingTriggers. A separate persistent RecordingIntent table is not required in V1.

Multiple overlapping triggers remain independent rows while extending one effective recording window.

See [Spec 0002 — Event Recording Lifecycle and RecordingTrigger](specs/0002-event-recording-lifecycle.md) and [Spec 0007 — Recording Intent Arbitration](specs/0007-recording-intent-arbitration.md).

## RecordingSegment

The canonical finalized recording timeline unit.

```text
id
camera_id
stream_profile_id
started_at
ended_at
duration_ms
recording_reasons             set/list: continuous | schedule | event | manual
size_bytes
codec
container
source_media_server_id
source_app
source_stream
integrity_status
completion_reason             normal_boundary | policy_stop | source_lost | runtime_restart | media_discontinuity | storage_failure | failure
created_at
```

Important rules:

- timestamps are actual finalized-media times in UTC;
- nominal 300-second segmentation is never assumed to be exact;
- RecordingSegment contains no authoritative filesystem/cloud path;
- one segment may have multiple physical RecordingLocations;
- source outage/restart may create shorter segments and true timeline gaps;
- adjacent segments are merged into recording ranges at query time rather than through a persisted Timeline/RecordingSession table.

Recommended local human-readable path:

```text
recordings/{name_id}/{YYYY-MM-DD}/{name_id}_{YYYY-MM-DD}_{HH-MM-SS}.mp4
```

The path belongs to RecordingLocation, not RecordingSegment.

See [Spec 0004 — Recording Storage Layout and Time Index](specs/0004-recording-storage-layout.md).

## AIProviderInstance

Optional configured AI provider. V1's primary provider is Frigate.

```text
id
type                          frigate
mode                          managed | external
name
enabled
config
credential_secret_ref
health_state
last_connected_at
last_event_at
last_error
created_at
updated_at
```

Provider-specific advanced configuration may remain in generated/raw provider configuration rather than becoming dozens of zero-nvr columns.

## AIProviderCameraBinding

Maps an external AI-provider camera/source to a canonical Camera.

```text
id
provider_instance_id
camera_id
external_camera_key
enabled
created_at
updated_at
```

One zero-nvr Camera may receive ordinary ONVIF events and optional Frigate AI events without creating duplicate Camera identities.

## Event

Canonical product event produced from AI, camera-native, system, or manual sources.

```text
id
source                        frigate | onvif | vendor | system | manual | api | ...
source_event_id               nullable
camera_id                     nullable for system-wide events
category
label                         nullable
started_at
ended_at                      nullable
confidence                    nullable
severity                      nullable
zone                          nullable
snapshot_ref                  nullable
correlation_id                nullable
metadata
created_at
updated_at
```

For provider-tracked events, `(source/provider instance, source_event_id)` is idempotent: provider new/update/end messages update the same Event rather than creating duplicates.

V1 does not require raw DetectionObservation, EventZoneInterval, DetectionPolicy, or EventFusionGroup tables. Provider-specific detail that is useful for search/display remains in normalized fields or bounded metadata.

Frigate owns detection/tracking/zones; zero-nvr owns Event normalization, search, alert/recording policy linkage, timeline markers, and permissions.

See [Spec 0021 — Detection Providers, AI Events, and Frigate Integration](specs/0021-detection-providers-ai-events-and-fusion.md).

## AlertPolicy

Defines which canonical Events require user attention and where notifications should be delivered.

~~~text
id
name
enabled
camera_scope
event_categories
labels
zones
min_confidence
min_duration
severities
active_schedule
schedule_timezone
cooldown_seconds
notification_target_ids
protect_recording
publish_webhook_or_mqtt
created_at
updated_at
~~~

The predicate set is intentionally NVR-specific rather than a general rule-expression language.

## Alert

Human-facing attention item derived from one Event/condition.

~~~text
id
alert_policy_id
event_id
camera_id
severity
title
message
state                         active | acknowledged | resolved
opened_at
last_activity_at
acknowledged_at
acknowledged_by
resolved_at
correlation_id
created_at
updated_at
~~~

Acknowledgement does not mean the underlying condition recovered and never changes recording truth.

## NotificationTarget

Configured outbound destination.

~~~text
id
name
type                          smtp | apprise | webhook | mqtt
enabled
config
credential_secret_ref
health_state
last_test_at
last_error
created_at
updated_at
~~~

Apprise is preferred for supported channels rather than custom provider implementations.

## NotificationDelivery

Product-visible delivery/retry state for an Alert and target.

~~~text
id
alert_id
notification_target_id
state                         pending | sending | sent | failed | suppressed
attempt_count
last_attempt_at
sent_at
last_error
provider_message_id
created_at
updated_at
~~~

Huey performs delivery/retry. Cooldown may suppress repeated NotificationDelivery creation but never suppresses Event persistence or recording behavior.

V1 does not require AlertIncidentSource, EscalationPolicy/Step, ActionSet, RecipientGroup, AlertSilence, or per-attempt delivery tables.

See [Spec 0014 — Alerts and Notifications](specs/0014-alerting-notification-and-escalation.md).

## Recording storage routing

V1 has no zero-nvr-managed StoragePool entity.

A RecordingPolicy or Camera may reference an explicit local `storage_target_id`; otherwise the system default local recording target is used. Host-level ZFS/Btrfs/LVM/mergerfs/RAID/NAS aggregation remains outside the domain model.

See [Spec 0010 — Recording Storage Targets and Host-Managed Storage](specs/0010-recording-storage-pool-and-failover.md).

## StorageTarget

Represents a configured canonical recording/archive destination, not a block-storage pool.

```text
id
type                          local | rclone
role                          recording | archive
name
enabled
config
credential_secret_ref         nullable
health_state                  unknown | ok | degraded | pressure | critical | offline | read_only
total_bytes                   nullable
used_bytes                    nullable
free_bytes                    nullable
last_health_at
last_error
created_at
updated_at
```

Interpretation:

- `local + recording`: local disk, host-mounted NAS, ZFS/Btrfs/LVM/RAID/mergerfs path presented as a filesystem;
- `rclone + archive`: S3/WebDAV/SFTP/SMB/OneDrive/OpenList-WebDAV/etc. configured through rclone.

OpenList is not a separate StorageTarget protocol implementation; when used, it is normally exposed to rclone as WebDAV.

Playback cache is disposable local cache configuration, not a canonical recording StorageTarget. System backup repositories are managed by the backup/restic configuration and do not need to masquerade as recording locations.

V1 has no zero-nvr-managed StoragePool entity.

## RecordingLocation

Represents one physical copy of a finalized RecordingSegment.

```text
id
recording_segment_id
storage_target_id
object_path
state                         available | archiving | failed | deleting | deleted | missing
size_bytes
checksum                      nullable
verified_at                   nullable
last_attempt_at               nullable
last_error                    nullable
created_at
deleted_at                    nullable
```

A RecordingSegment may have multiple RecordingLocations, for example:

```text
local SSD        AVAILABLE
NAS              AVAILABLE
cloud/OpenList   AVAILABLE
```

Archive workflow:

```text
create remote RecordingLocation = ARCHIVING
-> Huey worker invokes rclone copy/copyto
-> verify
-> remote RecordingLocation = AVAILABLE
-> retention may later transition local location DELETING -> DELETED
```

Huey owns job execution/retry scheduling. V1 does not require a separate UploadJob business table or a second rclone-job state machine.

A failed transfer is reflected on the target RecordingLocation as FAILED with sanitized error/attempt metadata and may be retried idempotently.

Caches, thumbnails, exports, and temporary pre-roll fragments are not RecordingLocations unless they become canonical retained copies of a RecordingSegment.

## Upgrade/runtime migration state

V1 does not require canonical `UpgradePlan`, `UpgradeHistory`, or generic `DataMigrationJob` business tables.

Host mutation is driven by `deploy.sh`, while Alembic owns schema revision history. When the application database is available, important update/migration outcomes are recorded through AuditEvent/SystemEvent.

A dedicated resumable progress table should be introduced only for a specific proven large migration that cannot be completed safely in one controlled migration step.

## DatabaseMigrationPlan

Tracks explicit SQLite ↔ PostgreSQL migration/cutover.

```text
id
source_engine
target_engine
source_schema_revision
target_schema_revision
source_version
status
safety_backup_set_id
validation_summary
cutover_at
rollback_deadline
created_by
created_at
completed_at
```

Software upgrade and cross-database migration are separate operations. Both preserve canonical IDs and use verified safety backups where required.

See [Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback](specs/0017-upgrade-migration-and-rollback.md).

## BackupPolicy

Defines lightweight system-backup scheduling and retention.

```text
id
name
enabled
backup_target_id
database_backend          auto | sqlite | postgresql
schedule
retention_policy
verify_after_backup
repository_check_schedule
include_deployment_config
created_at
updated_at
```

V1 database backup is SQLite Online Backup or pg_dump followed by restic. Continuous replication/PITR engines are optional advanced integrations rather than required BackupPolicy modes.

## BackupSet

User-visible backup/recovery point.

```text
id
backup_policy_id
backup_target_id
state                     preparing | backing_up | verifying | ready | failed | expired
reason                    scheduled | manual | pre_upgrade | pre_restore | pre_database_migration
started_at
completed_at
app_version
schema_revision
database_engine
restic_snapshot_id
size_bytes
verification_state
last_verified_at
error_code
sanitized_error
created_at
updated_at
```

## BackupManifest

Versioned restore metadata describing application/schema/database-engine versions, database repository references, required SecretStore key IDs, recovery capsule reference, storage targets, media-protection summary, included components, and checksums.

It never contains plaintext credentials.

## RecoveryKit

Operator-controlled encrypted bootstrap material for clean-host disaster recovery.

Conceptually protects:

```text
backup repository identity
backup target bootstrap credential package
SecretStore keyring package
required key ids
recovery metadata/checksums
```

RecoveryKit is encrypted outside the active production database using an operator-controlled recovery passphrase/key.

See [Spec 0015 — Backup, Disaster Recovery, and System Migration](specs/0015-backup-disaster-recovery-and-pitr.md).

## PlaybackSession

Tracks authorized live/historical playback when needed.

```text
id
user_id
camera_id
mode
created_at
expires_at
metadata
```


## PlaybackTimeline

A non-authoritative read model returned by playback APIs for an absolute time range.

It is composed from RecordingSegment, RecordingLocation, Event, RecordingPolicy/RecordingTrigger state, and retention/protection facts rather than persisted as the primary source of truth.

Conceptual shape:

```text
range_start_ms
range_end_ms

tracks[]
  camera_id

  segments[]
    recording_segment_id
    start_ms
    end_ms
    availability
    playback_ref

  gaps[]
    start_ms
    end_ms
    reason

  events[]
    event_id
    category
    label
    start_ms
    end_ms
```

Playback API timestamps are UTC Unix milliseconds.

Initial segment availability values:

```text
local
remote
cached_remote
missing
corrupted
purged
```

Initial gap reasons:

```text
not_scheduled
no_event
source_lost
runtime_restart
storage_failure
missing_media
purged
unknown
```

Playback URLs are resolved lazily from `playback_ref`; the timeline read model must not depend on a permanent storage-specific URL.

See [Spec 0006 — Historical Playback Timeline and Multi-Camera Sync](specs/0006-historical-playback-timeline.md).

## Runtime health and system events

Current health is adapter/runtime state, not a high-frequency business table.

Examples:

~~~text
camera media: ONLINE / DEGRADED / OFFLINE
recording: OK / DEGRADED / ERROR
storage: OK / PRESSURE / CRITICAL / OFFLINE
archive: OK / DEGRADED / ERROR
AI: OK / DEGRADED / DISABLED
worker/database/ZLM: OK / DEGRADED / ERROR
~~~

Current status may live in memory and be recomputed from adapters/services.

Meaningful transitions become canonical `Event` rows with `source=system`, for example:

~~~text
camera_offline
camera_recovered
recording_failed
recording_recovered
storage_pressure
storage_critical
archive_failed
archive_recovered
zlm_offline
zlm_recovered
backup_failed
backup_recovered
~~~

This provides product history and alert input without persisting 5-second health samples.

Gap reasons are normally projected from recording coverage plus known system Events/policy state. zero-nvr does not require a separate SourceConnectivityIncident or EventLog table in V1.

## AuditEvent

Append-oriented record of actor-driven administrative, destructive, authentication, and security-relevant operations.

```text
id
occurred_at
actor_type
actor_id
actor_display
action
resource_type
resource_id
camera_id
request_id
correlation_id
source_ip
client_info
result
reason
before
after
metadata
created_at
```

Sensitive fields are redacted from before/after/metadata.

AuditEvent answers **who did what**. Canonical Event rows explain product/runtime occurrences. They are separate concerns.

Normal product APIs do not edit/delete historical AuditEvents.

See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](specs/0011-auth-authorization-and-audit.md).

## Invariants

### Product and identity

1. Camera is the stable product identity; external provider/media IDs are adapter references.
2. Durable business state lives in the selected zero-nvr database; runtime component state is reconstructable.
3. Frontend authorization/UI visibility never replaces backend permission and camera-scope checks.
4. Credentials and secret plaintext never appear in normal read APIs, logs, Event, or AuditEvent payloads.

### Recording

5. ZLMediaKit owns normal media pull, reconnect runtime, recording, and VOD.
6. zero-nvr owns RecordingPolicy/RecordingTrigger decisions and reconciles desired recording state with one normal ZLM recorder per camera.
7. V1 does not require persisted RecordingIntent or RecordingSession tables; current recording requirement is derived from policy, time, active triggers, and observed ZLM state.
8. RecordingTrigger is durable evidence/request state for event/manual/external recording behavior.
9. Multiple overlapping triggers remain independent records and never create duplicate recorders.
10. RecordingSegment is a finalized media fact using actual UTC start/end/duration; nominal segment duration is not timeline truth.
11. RecordingSegment has no authoritative path; physical copies belong to RecordingLocation.
12. EVENT_ONLY pre-roll semantics are product policy, while the physical pre-buffer mechanism remains POC-gated until validated.
13. zero-nvr does not implement a custom compressed-video packet ring buffer.
14. Source/runtime interruptions produce real shorter segments/gaps; timestamps are never stretched to hide missing video.
15. API/worker/database restart must not deliberately terminate healthy existing ZLM recording when avoidable.
16. Missed recording hooks are recoverable through idempotent reconciliation; ffprobe is fallback rather than the normal indexing path.

### Event and AI

17. Event is the canonical provider-neutral product event used for search, timeline, alerts, and recording-policy linkage.
18. Provider source identity is preserved so Frigate/ONVIF retries or updates are idempotent.
19. Frigate owns AI detection/tracking/zones; zero-nvr does not clone its inference engine.
20. V1 does not require raw DetectionObservation/EventFusion tables; provider detail remains normalized fields or bounded metadata.
21. AI/provider failure never stops healthy core recording.

### Storage and retention

22. StorageTarget represents a configured local recording target or rclone archive target; it is not a RAID/JBOD pool.
23. Host/storage software owns disk aggregation, filesystem redundancy, and block-device failover.
24. RecordingLocation represents one physical canonical copy of one RecordingSegment.
25. A RecordingSegment may have zero, one, or multiple RecordingLocations over its lifecycle; deleted/missing copies do not rewrite segment time.
26. Remote archive follows copy -> verify -> remote RecordingLocation AVAILABLE -> optional local deletion.
27. rclone move and whole-tree sync are not the default archive semantics.
28. Huey owns archive job execution/retry; V1 does not require a separate UploadJob business table.
29. A local copy is never deleted under archive-before-delete policy until another required verified RecordingLocation is AVAILABLE.
30. RecordingProtection always blocks automatic deletion of overlapping protected media.
31. Retention is computed from durable policy/reason/protection/location facts rather than a mandatory per-segment RetentionClaim table.
32. If disk pressure cannot be resolved legally without violating hard/protected retention, zero-nvr raises a critical condition rather than silently deleting protected evidence.

### Playback and time

33. Timeline and Gap are projections, not authoritative tables.
34. Historical playback is driven by absolute wall-clock time, not filename order or nominal segment cadence.
35. PlaybackResolver chooses an AVAILABLE RecordingLocation and hides local/archive/cache mechanics from the timeline API.
36. Remote-only V1 playback restores media through rclone into bounded disposable local cache before ZLM VOD; FUSE is not required.
37. Canonical persisted timestamps are UTC; API timestamps are ISO 8601 with timezone and UI uses configured/user timezone.
38. Camera clock measurements may normalize device-originated Event timestamps but never rewrite RecordingSegment media time.
39. Host time synchronization health and camera clock offset are observable V1 capabilities.

### Security, alerts, backup, deployment

40. Alert acknowledgement/delivery failure never mutates or deletes canonical Event/recording facts.
41. Notification delivery is isolated from recording and uses Apprise/provider adapters.
42. System backup and recording archive are separate; V1 backup is database-native consistent backup plus restic.
43. RecoveryKit/bootstrap secret material required to decrypt restored credentials must survive disaster recovery.
44. Disposable thumbnails/export/playback/rclone cache are not required system-backup data.
45. SQLite is the default production database; PostgreSQL is optional without changing the product model.
46. deploy.sh + .env + Docker Compose Profiles is the V1 deployment/upgrade authority.
47. Optional managed services are not pulled or started unless enabled.
48. The web application does not require unrestricted Docker-socket access.
49. Core target is two images / three containers: API, worker, ZLMediaKit.
50. Changes to component ownership, recording authority, storage lifecycle, Core container boundaries, or database-default policy require an ADR after architecture freeze.

### Runtime reconciliation

- Runtime-relevant configuration may use revisions/generations to fence stale asynchronous adapter results.
- ZLMediaKit owns RTSP reconnect/backoff; zero-nvr only projects health and reconciles desired configuration.
- Metadata-only edits should not restart media.
- Capability loss does not silently delete durable Camera/user configuration.
- Control, media, recording, event, PTZ, clock, AI, archive, and backup health remain independently observable.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](specs/0019-device-runtime-lifecycle-and-reconfiguration.md).

### Live-view invariants

- MediaSession is short-lived authorization/runtime state and never contains reusable camera credentials.
- Grid viewing prefers LIVE_LOW; focused/fullscreen may promote to LIVE_HIGH.
- Recording source/profile remains independent from browser playback compatibility.
- FFmpeg compatibility transcode is bounded/on-demand derived media only.
- TURN and talk are optional capabilities; their failure never affects recording.

See [Spec 0020 — Live View, Media Sessions, Compatibility, Audio, and Optional Talk](specs/0020-live-view-media-session-and-talk.md).

### AI-provider invariants

- Provider ingress is idempotent and maps into canonical Event.
- Frigate remains an optional AI provider, not NVR source of truth.
- External and Managed provider modes use the same product contract.
- Generic cross-provider fusion is not a V1 requirement.

See [Spec 0021 — Detection Providers, AI Events, and Frigate Integration](specs/0021-detection-providers-ai-events-and-fusion.md).

## Derived projections are not tables

The following are query/projection concepts rather than authoritative persisted entities:

- Timeline
- Gap
- thumbnail cache
- playback cache
- current high-frequency health samples

Timeline is derived from RecordingSegment coverage plus Event markers. Gap is the complement of merged recording coverage over a requested wall-clock range.
