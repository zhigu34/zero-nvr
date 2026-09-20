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

## UserMfa

```text
user_id
enabled
totp_secret_ref
enrolled_at
last_verified_at
```

TOTP secret material is stored behind SecretStore.

## MfaRecoveryCode

```text
id
user_id
code_hash
used_at
created_at
```

Recovery codes are verifier-only credentials and are one-way hashed.

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

```text
id
kind
owner_type
owner_id
algorithm
encrypted_payload
payload_nonce
wrapped_data_key
wrap_nonce
wrapping_key_id
version
created_at
updated_at
last_used_at
```

Each record uses a random per-secret data-encryption key (DEK). The DEK is wrapped by a key-encryption key (KEK) that is stored outside PostgreSQL.

Business rows reference secrets through opaque `secret_ref` fields. Normal read APIs never return SecretRecord plaintext.

Verifier-only credentials such as User passwords and authentication tokens use one-way hashing instead.

See [Spec 0012 — Configuration, Secret Storage, Key Rotation, and Backup](specs/0012-config-secrets-key-management.md).

## CameraConnection

Compatibility/read-model view of the currently selected camera/device connection. New implementation should resolve through DeviceEndpoint + DeviceCredential rather than duplicate host/secret state per Camera.

Candidate adapters:

```text
manual_rtsp
onvif
hik_sdk
gb28181
```

Credentials must never be duplicated into public read models.

## SourceMediaProfile

Discovered adapter/source profile.

```text
id
device_id
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
```

Source profile identity is kept separate from product stream roles.

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

## MediaStream

Canonical logical product stream mapped to a discovered source profile.

```text
id
camera_id
role                    recording | live_main | live_preview | detection | audio
source_media_profile_id
codec
width
height
fps
media_plane_key
status
selection_mode          auto | manual
selected_at
last_verified_at
```

One SourceMediaProfile may satisfy several roles. The MediaPlane maps MediaStream to runtime ZLM state; permanent browser URLs are not domain truth.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](specs/0018-camera-onboarding-discovery-and-stream-selection.md).

## CameraRuntimeStatus

Reconstructable runtime read model for one Camera.

```text
camera_id
desired_state             enabled | disabled | maintenance
config_revision
applied_revision
control_health
media_health
event_health
ptz_health
clock_health
effective_recording_profile_id
effective_live_profile_id
effective_preview_profile_id
effective_detection_profile_id
last_transition_at
last_error_code
sanitized_error
updated_at
```

Overall camera health is a UI summary only. Domain decisions consume the specific component health they need.

## RuntimeGeneration

Short-lived runtime identity used to fence stale asynchronous callbacks.

```text
camera_id
role
config_revision
runtime_generation
started_at
ended_at
```

Runtime callbacks from an older config revision/generation cannot mutate authoritative current state.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](specs/0019-device-runtime-lifecycle-and-reconfiguration.md).

## MediaSession

Short-lived authorized live-view session.

```text
id
principal_id
camera_id
requested_purpose        grid | focus | fullscreen | popout | talk
requested_quality        auto | preview | main
effective_stream_role
transport                webrtc | fmp4 | hls
source_codec
delivery_codec
transcoded
runtime_generation
issued_at
expires_at
last_seen_at
ended_at
end_reason
```

MediaSession never exposes camera credentials or a permanent bearer URL.

## TalkSession

Short-lived camera-audio backchannel session.

```text
id
media_session_id
principal_id
camera_id
backend
codec
started_at
last_seen_at
ended_at
end_reason
```

Talk is separately authorized from live viewing and defaults to one active talker per Camera.

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

Describes desired recording behavior.

```text
camera_id
mode                          continuous | schedule | event | hybrid
schedule
prebuffer_enabled
idle_prebuffer_segment_seconds
formal_record_segment_seconds
pre_roll_seconds
post_roll_seconds
retention_policy_id
storage_target_id
enabled
```

V2 recording defaults are:

```text
prebuffer_enabled               = true
idle_prebuffer_segment_seconds  = 20
formal_record_segment_seconds   = 300
pre_roll_seconds                = 10
post_roll_seconds               = 10
```

These values are persisted configuration and must be editable from Recording Settings. They are defaults rather than hard-coded runtime constants.

The 20-second segment target applies only to temporary idle tmpfs PrebufferFragments. Formal continuous/manual/schedule/event recording defaults to 5-minute RecordingSegments. For event recording, required pre-roll is included inside the first 5-minute formal segment window.

Event recording duration itself is not fixed in advance. Stateful events keep the event RecordingIntent active until the final event ends, after which post-roll is applied. Other active intents may keep the same RecordingSession alive after the event intent completes.

Initial V2 hybrid semantics are: scheduled baseline recording during configured schedule windows, plus event-triggered recording outside those windows.


## RetentionPolicy

Defines media retention and disk-pressure behavior. System defaults may be overridden per camera.

```text
id
name
continuous_keep_days
schedule_keep_days
event_keep_days
manual_keep_days
warning_usage_percent
cleanup_start_percent
critical_usage_percent
emergency_usage_percent
cleanup_target_percent
min_free_bytes
created_at
updated_at
```

Initial defaults:

```text
continuous_keep_days = 7
schedule_keep_days   = 7
event_keep_days      = 30
manual_keep_days     = 30

warning_usage_percent   = 80
cleanup_start_percent   = 85
critical_usage_percent  = 92
emergency_usage_percent = 96
cleanup_target_percent  = 80
```

See [Spec 0005 — Recording Retention, Disk Pressure, and Safe Purge](specs/0005-recording-retention-and-purge.md).

## RetentionClaim

Represents one reason a RecordingSegment must remain available.

```text
id
recording_segment_id
reason
priority
retain_until
source_type
source_id
created_at
```

Typical reasons:

```text
continuous_policy
schedule_policy
event_policy
manual_policy
user_lock
upload_source
export_job
system_recovery
```

Finite effective retention is the maximum `retain_until` across active claims. `user_lock` is indefinite until explicitly unlocked.

This claim model is required because one 5-minute physical segment may simultaneously belong to normal recording and contain one or more events with longer retention.

## RecordingIntent

Represents one business reason why a camera currently requires formal recording.

```text
id
camera_id
intent_type          continuous | schedule | event | manual
source_type
source_id
started_at
planned_end_at
ended_at
state                pending | active | post_roll | completed | cancelled
correlation_id
metadata
created_at
updated_at
```

Recording intents are additive. A camera may have continuous, event, and manual intents active at the same time without creating duplicate media recorders.

`hybrid` is a RecordingPolicy composition mode rather than a runtime intent type. Initial V2 hybrid semantics are scheduled baseline recording plus event-triggered recording outside the schedule.

See [Spec 0007 — Recording Intent Arbitration and Mode Composition](specs/0007-recording-intent-arbitration.md).

## RecordingSession

Represents one maximal uninterrupted formal-recording interval owned by zero-nvr.

```text
id
camera_id
started_at
planned_end_at
ended_at
actual_media_started_at
actual_media_ended_at
status
origin_intent_type
active_storage_target_id
created_at
updated_at
```

A RecordingSession remains active while at least one RecordingIntent requires media.

`origin_intent_type` records which intent caused the idle → formal transition for diagnostics/history. It is not a mutually exclusive recording classification.

Adding or removing another intent while the active-intent set remains non-empty:

- does not restart the recorder;
- does not create a second media pipeline;
- does not reset the formal segment clock;
- does not force a physical segment boundary.

A true interval with zero active RecordingIntents ends the RecordingSession. A later intent starts a new RecordingSession.

RecorderBackend processes are runtime implementations of this session/media requirement, not the business identity of individual intents.

## PrebufferFragment

Temporary media produced only for idle event pre-recording.

```text
id
camera_id
started_at
ended_at
duration
path
state           writing | ready | protected | consumed | expired
created_at
```

Default physical target is 20 seconds.

PrebufferFragment is not a canonical historical recording. When a RecordingSession starts, the required fragment ranges become source material for the first formal RecordingSegment and may be deleted after that formal segment is verified.

## RecordingSegment

The canonical persisted formal-recording timeline unit.

```text
id
camera_id
stream_role
sequence
started_at
ended_at
duration
codec
container
size
local_object_id
integrity_status
completion_reason     normal_boundary | session_end | manual_stop | schedule_end | source_lost | runtime_restart | media_discontinuity | failure
created_at
```

Segment identity remains stable even if its media object later moves to remote storage.

For a healthy active RecordingSession, intermediate RecordingSegments follow the configured formal segment cadence anchored at `RecordingSession.started_at`. Shorter files are expected only for the final session segment or an explicit interruption/recovery boundary. `completion_reason` makes that distinction queryable.

Canonical RecordingSegment timestamps are UTC. Calendar/day boundaries do not force segment rollover. Physical location belongs to StorageObject and uses a stable object key such as:

```text
recordings/{name_id}/{YYYY-MM-DD}/{name_id}_{YYYY-MM-DD}_{HH-MM-SS}.mp4
```

The local layout uses the Camera's stable human-readable name/id, configured recording timezone, local start date, and human-readable recording start time. See [Spec 0004 — Recording Storage Layout and Time Index](specs/0004-recording-storage-layout.md).

## RecordingSessionSegment

Maps one logical RecordingSession onto the required range of one physical RecordingSegment.

```text
recording_session_id
recording_segment_id
sequence
use_started_at
use_ended_at
created_at
```

A RecordingSession may span multiple physical MP4 files. The first/last physical files may contain additional footage outside the logical session; `use_started_at` / `use_ended_at` define the business-visible range.

This mapping allows normal playback to cross segment boundaries without first generating a merged MP4. A single-file crop/concat is a derived export operation.

See [Spec 0003 — Rolling MP4 Pre-buffer and Event Segment Composition](specs/0003-rolling-mp4-prebuffer.md).

## DetectionProviderInstance

Configured event/AI provider.

```text
id
type                    onvif_native | hik_native | frigate | local_motion | custom
name
enabled
config
credential_secret_ref
health_state
last_connected_at
last_observation_at
last_error_code
sanitized_error
created_at
updated_at
```

## DetectionProviderBinding

Maps one provider source to a canonical Camera and controls downstream eligibility.

```text
id
provider_instance_id
camera_id
external_source_key
enabled
priority
timeline_enabled
recording_enabled
alert_enabled
event_type_filter
object_class_filter
zone_mapping
config
created_at
updated_at
```

## DetectionObservation

Append-oriented normalized provider update/evidence.

```text
id
provider_instance_id
binding_id
camera_id
provider_event_key
provider_track_key
provider_sequence
transition              start | update | end | pulse | instant
provider_event_type
canonical_hint
source_occurred_at
received_at
occurred_at
timestamp_quality
object_class
object_subclass
confidence
bounding_box
provider_zones
attributes
snapshot_ref
payload_digest
metadata
created_at
```

Provider ingress is idempotent; repeated delivery of the same source update must not create duplicate business events.

## EventZone

```text
id
camera_id
name
enabled
normalized_polygon
presentation
created_at
updated_at
```

## ProviderZoneBinding

```text
detection_provider_binding_id
provider_zone_key
event_zone_id
```

## DetectionEventZoneInterval

```text
detection_event_id
event_zone_id
entered_at
exited_at
```

## DetectionPolicy

```text
camera_id
enabled
provider_bindings
recording_event_filters
alert_event_filters
fusion_enabled
fusion_window_ms
snapshot_policy
observation_retention
updated_at
```

RecordingPolicy still owns recording pre/post-roll and RecordingIntent behavior.

## DetectionEvent

Provider-neutral business event aggregate. Provider updates are retained separately as DetectionObservation.

```text
id
camera_id
source_kind
provider
provider_instance_id
external_id
event_type
object_class
object_subclass
lifecycle_kind          stateful | instant
status                  active | completed
end_reason
source_occurred_at
received_at
occurred_at
timestamp_source
timestamp_quality
clock_offset_ms_applied
started_at
last_activity_at
ended_at
confidence
current_zones
snapshot_object_id
recording_session_id
correlation_id
fusion_group_id
metadata
created_at
updated_at
```

Canonical event-type families include at least:

```text
motion
object
zone_entry
zone_exit
intrusion
line_crossing
loitering
tamper
digital_input
audio
face
plate
custom
unknown
```

Object labels/classes remain separate:

```text
person
vehicle
car
truck
bicycle
motorcycle
animal
dog
cat
package
provider-defined class
```

For stateful events:

```text
START -> UPDATE* -> END
```

While ACTIVE, `ended_at` remains NULL. `last_activity_at` advances as the provider updates the same logical event/track.

For instant events:

```text
started_at = occurred_at
ended_at   = occurred_at
status     = completed
```

Instant events do not invent an artificial active duration. Recording policy applies the normal pre-roll/post-roll window around the occurrence timestamp.

Repeated activity for the same provider event/track identity must not create duplicate business events. Late stale updates do not reopen a completed DetectionEvent.

Timeline seek offsets are derived from absolute event timestamps rather than stored as authoritative offsets.

## EventFusionGroup

Non-destructive cross-provider correlation group.

```text
id
camera_id
opened_at
last_activity_at
closed_at
fusion_key
summary_type
summary_object_class
canonical_zone_ids
created_at
updated_at
```

## EventFusionMember

```text
fusion_group_id
detection_event_id
relation                same_occurrence | supports | derived_from | possibly_related
confidence
created_at
```

Fusion helps presentation/alert deduplication but never deletes or rewrites member DetectionEvents.

See [Spec 0021 — Detection Providers, AI Events, Object Tracking, Zones, and Event Fusion](specs/0021-detection-providers-ai-events-and-fusion.md).
## RecordingTrigger

Represents an explicit external or internal **recording intent** when an integration needs to ask zero-nvr to preserve/record something without exposing recorder-process commands.

It is not the canonical model for stateful sensor events. Motion/person/presence-style START/END input should normalize into DetectionEvent and then be evaluated by RecordingManager.

Conceptual fields:

```text
id
camera_id
source
external_id
trigger_type
received_at
processed_at
status
reason
correlation_id
metadata
created_at
```

Typical sources may include:

```text
home_assistant
mqtt
webhook
manual
api
system
```

Typical processing states may include:

```text
received
accepted
ignored
merged
rejected
failed
```

RecordingTrigger records what intent was received and how zero-nvr handled it. It never directly represents or controls an FFmpeg/ZLMediaKit process.

Stateful event-driven recording behavior is defined by DetectionEvent + RecordingSession in [Spec 0002 — Event Recording Lifecycle](specs/0002-event-recording-lifecycle.md).

## AlertRule

Defines which canonical detection/health/security signals become human-facing alert incidents and how they are grouped/routed.

```text
id
name
description
enabled
signal_kinds
camera_scope
event_types
health_types
security_types
min_confidence
zones
severities
schedule_timezone
active_schedule
quiet_schedule
grouping_mode
group_window_seconds
cooldown_seconds
incident_resolution_mode
auto_resolve_after_seconds
escalation_policy_id
created_at
updated_at
```

## AlertIncident

Human-facing alert lifecycle, separate from DetectionEvent.

```text
id
alert_rule_id
source_kind
primary_source_type
primary_source_id
camera_id
group_key
title
severity
lifecycle_state          active | resolved
acknowledgement_state    unacknowledged | acknowledged
opened_at
last_activity_at
resolved_at
acknowledged_at
acknowledged_by
acknowledgement_note
trigger_count
first_snapshot_object_id
latest_snapshot_object_id
correlation_id
created_at
updated_at
```

Incident lifecycle and acknowledgement are independent.

## AlertIncidentSource

```text
alert_incident_id
source_type
source_id
occurred_at
transition
created_at
```

A single AlertIncident may group many source DetectionEvents/health signals without deleting or rewriting them.

## EscalationPolicy

```text
id
name
enabled
stop_on_acknowledge
stop_on_resolve
created_at
updated_at
```

## EscalationStep

```text
id
escalation_policy_id
sequence
delay_seconds
repeat_interval_seconds
max_repeats
action_set_id
```

## AlertActionSet

```text
id
name
enabled
created_at
updated_at
```

## AlertAction

```text
id
action_set_id
notification_target_id
template_id
send_on
include_snapshot
include_deep_link
enabled
```

## NotificationTarget

Configured outbound destination.

```text
id
name
type                    smtp | apprise | webhook | home_assistant | mqtt
enabled
config
credential_secret_ref
health_state
last_health_at
last_error
created_at
updated_at
```

## RecipientGroup

```text
id
name
created_at
updated_at
```

## RecipientGroupMember

```text
recipient_group_id
user_id
email_address
```

## NotificationTemplate

```text
id
name
channel_type
locale
subject_template
body_template
body_format             text | html | json
built_in
created_at
updated_at
```

Template variables are explicitly whitelisted/sandboxed and cannot access secrets.

## AlertSilence

```text
id
name
enabled
starts_at
ends_at
camera_scope
alert_rule_ids
signal_types
suppress_notifications
suppress_incident_creation
reason
created_by
created_at
updated_at
```

Default silence suppresses delivery while keeping incidents/history.

## AlertDelivery

One logical outbound notification/action.

```text
id
alert_incident_id
alert_rule_id
action_id
notification_target_id
delivery_kind
idempotency_key
status                  pending | sending | retry_wait | delivered | failed | cancelled | suppressed
scheduled_at
first_attempt_at
delivered_at
failed_at
attempt_count
last_error_code
last_error_message
rendered_subject
rendered_body_digest
correlation_id
created_at
updated_at
```

## AlertDeliveryAttempt

Append-style history of each provider/network attempt.

```text
id
alert_delivery_id
attempt_number
started_at
finished_at
outcome
provider_status
error_code
sanitized_error
provider_message_id
next_retry_at
```

DetectionEvent/system health remains authoritative. Grouping, cooldown, silence, acknowledgement, escalation, or delivery failure never deletes source events or changes recording lifecycle.

See [Spec 0014 — Alert Incidents, Notification Routing, Escalation, and Delivery](specs/0014-alerting-notification-and-escalation.md).

## Recording storage routing

V1 has no zero-nvr-managed StoragePool entity.

A RecordingPolicy or Camera may reference an explicit local `storage_target_id`; otherwise the system default local recording target is used. Host-level ZFS/Btrfs/LVM/mergerfs/RAID/NAS aggregation remains outside the domain model.

See [Spec 0010 — Recording Storage Targets and Host-Managed Storage](specs/0010-recording-storage-pool-and-failover.md).

## StorageTarget

```text
id
type
name
enabled
priority
config
credential_secret_ref
quota
health
```

Types:

```text
local
s3
rclone
openlist
```

Storage roles:

```text
recording_hot
archive_remote
playback_cache
backup
```

Recording-related state may include:

```text
health_state    unknown | healthy | degraded | pressure | critical | offline | read_only
write_state     eligible | draining | ineligible
total_bytes
used_bytes
free_bytes
last_health_at
last_successful_write_at
last_error
```

## StorageObject

Represents a physical copy of media/data.

```text
id
logical_kind
logical_id
storage_target_id
object_key
size
checksum
state
verified_at
created_at
```

A RecordingSegment can have multiple StorageObjects.

## UploadJob

```text
id
storage_object_id
target_id
state
attempt
next_retry_at
last_error
created_at
updated_at
```

State direction:

```text
PENDING
UPLOADING
VERIFYING
REMOTE_READY
FAILED
```

Local-purge eligibility is a policy decision after verified remote readiness.

## UpgradePlan

```text
id
source_version
target_version
source_schema_revision
target_schema_revision
database_engine
status
rollback_class
requires_maintenance
requires_database_backup
requires_recovery_kit_current
estimated_steps
preflight_result
created_by
created_at
started_at
completed_at
```

## UpgradeHistory

```text
id
upgrade_plan_id
source_version
target_version
source_schema_revision
target_schema_revision
database_engine
safety_backup_set_id
result
rollback_result
started_at
committed_at
completed_at
error_code
sanitized_error
```

## DataMigrationJob

Durable progress for large/restartable data transforms.

```text
id
upgrade_plan_id
migration_id
state
cursor
processed_count
error_count
started_at
updated_at
completed_at
```

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

It is composed from RecordingSegment, StorageObject, DetectionEvent, recording policy/runtime history, and retention state rather than persisted as the primary source of truth.

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
    detection_event_id
    event_type
    lifecycle_kind
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

## HealthSample

```text
camera_id
kind
status
latency
details
sampled_at
```

Kinds may include:

- connectivity;
- media stream;
- recorder;
- storage;
- upload;
- device protocol.


## SourceConnectivityIncident

Represents a historical infrastructure/media-source interruption independently from DetectionEvent.

```text
id
camera_id
started_at
ended_at
state
reason
last_media_at
recovered_at
retry_count
details
created_at
updated_at
```

Typical states/reasons include:

```text
degraded
reconnecting
offline
recovered

source_lost
runtime_restart
media_discontinuity
storage_failure
```

SourceConnectivityIncident can explain playback gaps and health history. It must not be modeled as a DetectionEvent.

A connectivity incident may split physical RecordingSegments while the same RecordingSession continues if one or more RecordingIntents remain active.

See [Spec 0008 — Stream Loss, Reconnect, and Recording Recovery](specs/0008-stream-reconnect-and-recording-recovery.md).

## EventLog

Persists structured business/runtime events needed to explain recording behavior.

```text
id
timestamp
level
category
event_type
camera_id
detection_event_id
recording_session_id
correlation_id
action
reason
details
```

Important actions include:

```text
event_started
event_ended
recording_started
post_roll_started
post_roll_cancelled
recording_extended
marker_created
recording_completed
event_ignored
event_rejected
```

EventLog complements normal application logs. It should make recording decisions queryable from the product UI/API.

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

AuditEvent answers **who did what**. EventLog explains runtime/business behavior. They are separate concerns.

Normal product APIs do not edit/delete historical AuditEvents.

See [Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit](specs/0011-auth-authorization-and-audit.md).

## Invariants

1. Camera is the stable identity.
2. External component IDs are never primary business identities.
3. Recording metadata survives storage movement.
4. DetectionEvent is provider-neutral and is the source of truth for event timeline markers.
5. zero-nvr alone owns recording lifecycle decisions; event/integration providers never directly control media recorder processes.
6. Stateful event recording duration is determined by event START/END plus pre-roll/post-roll, not a fixed record duration.
7. Multiple events may share one RecordingSession while remaining independent DetectionEvents and EventLog records.
8. External explicit recording intent may enter through RecordingTrigger, but stateful sensor events normalize into DetectionEvent.
9. Credentials do not appear in public read contracts.
10. Media runtime state is reconstructable and not authoritative metadata.
11. Remote upload requires verification before local purge eligibility.
12. Historical data blocks destructive Camera deletion unless an explicit archival/deletion design says otherwise.
13. Instant events are zero-duration DetectionEvents; they use recording pre-roll/post-roll without a fabricated event lifetime.
14. RecordingSession logical boundaries are independent from physical MP4 segment boundaries.
15. RecordingSessionSegment defines which time range of each physical segment contributes to a logical recording.
16. Event pre-buffer segment rollover must never require recorder stop/start to preserve correctness.
17. Idle tmpfs pre-buffering and formal recording are mutually exclusive modes of one recording pipeline, not duplicate recorders.
18. Idle 20-second tmpfs files are temporary PrebufferFragments, not canonical RecordingSegments.
19. The first event RecordingSegment window starts at RecordingSession.started_at, including pre-roll; a pre-buffer fragment boundary must not restart the 5-minute formal segment clock.
20. The first formal RecordingSegment may be assembled from one or more protected PrebufferFragment ranges plus persistent continuation media.
21. While a formal RecordingSession remains active and healthy, all intermediate RecordingSegments follow the configured duration from the session-anchored segment clock.
22. A normal RecordingSession completion may produce a shorter final segment; abnormal interruptions may also produce partial segments and must be identified by `completion_reason`.
23. The tail of a completed formal recording remains eligible to bridge pre-buffer warm-up for at least the configured pre-roll interval.
24. Recording segment durations and pre/post-roll values are policy/configuration data exposed through Recording Settings, not hard-coded constants.
25. Segment-duration configuration changes apply at a safe next segment boundary without force-cutting the current MP4 merely to apply the setting.
26. Canonical recording timestamps are UTC; all local directory/file timestamps are generated in the effective configured recording timezone so they align with camera wall-clock/OSD time.
27. Midnight/date boundaries never force a formal segment split.
28. Camera.storage_label is a stable human-readable storage identity; changing Camera display name does not silently rename historical media.
29. Local recording paths must remain browseable without zero-nvr by camera/date/start time.
30. Recording paths/object keys are storage metadata; playback and retention still use database timestamps/relations rather than directory scanning.
31. Retention is claim-based; a shared physical segment keeps the strongest active retention requirement without duplicating media.
32. User-locked media is never automatically purged.
33. Upload success without verified REMOTE_READY state never permits safe local-source deletion.
34. Critical disk-pressure purge is priority ordered and explicitly logged; currently writing/finalizing media is never an automatic purge candidate.
35. Historical playback is absolute-time driven; physical MP4 boundaries and filenames are never the playback clock.
36. Playback API time values use UTC Unix milliseconds consistently.
37. PlaybackTimeline is a derived read model with playable segments, explicit gaps, and DetectionEvent markers.
38. Multi-camera historical playback shares one Master Clock; one camera's gap never shifts another camera to a different absolute time.
39. Playback references resolve storage lazily so local/remote migration does not rewrite timeline semantics.
40. Purged, missing, corrupted, source-loss, and intentionally-unrecorded ranges remain distinguishable in playback.
41. Recording reasons are additive RecordingIntents; a camera has at most one formal media pipeline.
42. RecordingSession spans one uninterrupted formal-recording interval and may contain several overlapping intent types.
43. Adding/removing an intent while another remains active never restarts the recorder or resets formal segment cadence.
44. Manual stop removes only the manual intent and never force-stops other active recording reasons.
45. Initial V2 hybrid mode means scheduled baseline recording plus event-triggered recording outside schedule windows.
46. Canonical persisted timestamps are UTC and derive from zero-nvr/server canonical time rather than camera wall-clock time.
47. Device-originated event timestamps preserve source/receive/correction metadata and may be normalized by a reliable measured camera-clock offset.
48. Camera-clock correction never directly shifts RecordingSegment time or Playback Master Clock.
49. Historical normalized timestamps are not silently rewritten when later camera clock measurements change.
50. Recording schedules carry explicit wall-clock timezone semantics and elapsed runtime timers use monotonic clocks.
51. Confirmed source/media loss closes the current physical RecordingSegment but does not end RecordingSession while any RecordingIntent remains active.
52. Post-reconnect media always starts a new RecordingSegment and is never appended into an interrupted MP4.
53. A real media discontinuity resets the physical formal-segment cadence from actual recovery time.
54. Infrastructure/source-connectivity incidents are distinct from DetectionEvent and may explain historical playback gaps.
55. Camera offline/reconnecting state does not cancel enabled RecordingIntents or background source retry by itself.
56. SystemTimeSettings owns the default managed-camera NTP source and recording timezone.
57. A camera may inherit the system managed-camera NTP source or use an explicit camera-specific override.
58. Host OS time synchronization is monitored separately from managed-camera NTP configuration in initial V2.
59. Direct formal recording writes to an explicit local/host-mounted StorageTarget; archive-remote targets are asynchronous.
60. V1 does not contain a zero-nvr-managed StoragePool or automatic multi-disk balancing/failover scheduler.
61. Multiple local StorageTargets may be configured for explicit routing or migration, but host/storage software owns disk aggregation and redundancy.
62. A local storage failure is surfaced explicitly and never causes implicit live recording to an archive remote.
63. Disk-pressure cleanup must respect protection and archive-before-delete requirements.
64. StorageTarget removal never silently discards unique retained media.
65. Backend authorization is authoritative; frontend visibility alone never grants access.
66. Camera-scoped actions require both the action permission and effective camera scope.
67. Viewing does not imply export/download, lock, delete, PTZ, or management permission.
68. Live/playback media access uses short-lived scoped authorization and never exposes camera credentials.
69. External integrations use dedicated least-privilege service principals rather than administrator sessions.
70. AuditEvent is append-oriented actor accountability and remains separate from EventLog runtime/business history.
71. Disabling a User revokes active interactive sessions.
72. Domain safety invariants still apply even when the actor is an Administrator.
73. Password reset tokens are single-use expiring verifier-only credentials; plaintext reset tokens are never persisted.
74. Successful password reset revokes prior interactive sessions by default.
75. TOTP MFA secrets are protected through SecretStore while MFA recovery codes are one-way hashed.
76. OIDC/SSO identities map into the same User/Role/Permission/CameraScope model and never bypass authorization.
77. SMTP/email delivery is a first-production-release platform capability with SecretStore-backed credentials and durable retry/result tracking.
78. Self-service password reset depends on SMTP when email recovery is used, but administrator-issued and host-local recovery remain available when SMTP is unavailable.
79. AlertIncident is a human-facing grouping/lifecycle layer and never replaces or mutates DetectionEvent/system health truth.
80. Alert acknowledgement and source resolution are independent states; acknowledgement never stops RecordingIntent.
81. Alert grouping/cooldown/silence may suppress outbound delivery but never suppress canonical event persistence or recording.
82. Escalation and AlertDelivery retry state is durable/recoverable across process restart.
83. Notification targets are independently healthy and use SecretStore for recoverable credentials.
84. Per-attempt notification diagnostics are append-style AlertDeliveryAttempt records; exactly-once external delivery is not assumed.
85. StorageTarget may carry a backup role independently or together with archive_remote.
86. V1 system backup uses database-native consistent backup plus restic; PITR engines are optional advanced capabilities.
87. Database/system backup never implies local-only recording media is disaster-protected.
88. SecretStore recovery requires matching keyring/RecoveryKit; encrypted database rows alone are insufficient.
89. A complete disaster-recovery target must be bootstrap-accessible without first restoring the lost SecretStore.
90. Any restore is followed by non-destructive StorageObject/media reconciliation before normal cleanup.
91. Backup creation, verification, repository checking, and restore testing are distinct protection states.
73. Ordinary configuration and recoverable secrets are separate storage concerns.
74. Domain resources reference recoverable secrets by opaque secret_ref and never embed plaintext credentials.
75. Verifier-only credentials use one-way hashing rather than reversible encryption.
76. Recoverable SecretRecords use authenticated envelope encryption with per-record DEKs.
77. SecretStore KEK/keyring material is external to the active production database and versioned for rotation.
78. Normal APIs, logs, traces, EventLog, and AuditEvent never expose secret plaintext.
79. Existing encrypted SecretRecords plus a missing/wrong keyring are an explicit critical error, never converted to blank credentials.
80. Normal configuration/support exports exclude secrets; portable secret backups require explicit encrypted export.
81. Cryptographic key material is separated by purpose and rotated without silently invalidating active secrets.


### Device runtime lifecycle invariants

- Runtime-relevant configuration is revisioned; stale asynchronous results from older revisions/generations cannot mutate current authoritative runtime state.
- Runtime state is reconstructable projection state rather than business source of truth.
- Enable, disable, reconnect, and reconciliation operations are idempotent.
- Metadata-only edits do not restart media.
- Planned recording-profile changes preserve RecordingSession/RecordingIntent and switch at safe segment boundaries when possible.
- Forced source/profile reconfiguration records an explicit physical-media discontinuity while preserving logical recording intent when still active.
- Capability/profile/channel drift never silently deletes user configuration or historical Camera identity.
- Control, media, recording, event, PTZ, clock, and capability health remain independently observable.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](specs/0019-device-runtime-lifecycle-and-reconfiguration.md).


### Live-view invariants

- MediaSession is short-lived authorization/runtime state and never contains reusable camera credentials.
- Grid viewing prefers live_preview; focused/fullscreen may promote to live_main.
- Recording source/profile selection remains independent from browser playback compatibility.
- H.265 live use is capability-dependent; browser incompatibility may trigger an on-demand H.264 live derivative without changing recording.
- WebRTC is preferred for low-latency viewing; fMP4 and HLS are bounded fallbacks.
- Compatible viewers share transcode derivatives where practical.
- TURN credentials are short-lived and issued only for authorized MediaSessions.
- Talk is separately authorized and isolated from video/recording lifecycle.

See [Spec 0020 — Live View, Media Sessions, Adaptive Quality, TURN, and Talk](specs/0020-live-view-media-session-and-talk.md).


### Detection-provider invariants

- DetectionProvider produces observations; zero-nvr owns canonical DetectionEvent state.
- DetectionObservation preserves source evidence while DetectionEvent remains the business/timeline aggregate.
- Provider ingress is idempotent and tolerant of at-least-once/redelivered messages.
- Provider loss cannot leave stateful events ACTIVE forever; bounded liveness/reconciliation closes unresolved events.
- Event fusion is non-destructive correlation and never removes source events.
- Recording eligibility and alert eligibility are independent from event persistence.
- ONVIF/HIK/Frigate/local detection normalize into the same event model.
- AI/local-detection overload or failure never destabilizes healthy recording/media runtime.

See [Spec 0021 — Detection Providers, AI Events, Object Tracking, Zones, and Event Fusion](specs/0021-detection-providers-ai-events-and-fusion.md).


## Derived projections are not tables

The following are query/projection concepts rather than authoritative persisted entities:

- Timeline
- Gap
- thumbnail cache
- playback cache
- current high-frequency health samples

Timeline is derived from RecordingSegment coverage plus Event markers. Gap is the complement of merged recording coverage over a requested wall-clock range.
