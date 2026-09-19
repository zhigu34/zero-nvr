# Spec 0021 — Detection Providers, AI Events, Object Tracking, Zones, and Event Fusion

Status: **accepted**

## Goal

Define the complete first-production-release event-ingestion and AI detection model.

Core rule:

> Providers observe. zero-nvr normalizes, persists, correlates, and decides how those observations affect recording, timeline, alerts, and retention.

ONVIF/HIK/Frigate/local detectors remain replaceable event sources. They never own RecordingSession lifecycle or zero-nvr's event history.

## Layer separation

```text
ONVIF / HIK / Frigate / local detector
                ↓
       DetectionProvider
                ↓
      DetectionObservation
                ↓
       EventNormalizer
                ↓
       DetectionEvent
          ↓          ↓
 EventCorrelation   Event policy
 / Fusion Group     recording / alert
```

DetectionObservation preserves source updates. DetectionEvent is the provider-neutral business event. Event fusion is a non-destructive correlation layer and never erases source truth.

## DetectionProvider

Conceptual contract:

```text
capabilities()
start(binding)
stop(binding)
health()
reconcile()
snapshot(event_ref)
```

Initial provider types:

```text
onvif_native
hik_native
frigate
local_motion
integration/custom
```

Provider implementations may be in-process adapters, isolated bridges, MQTT consumers, or external integrations.

## DetectionProviderInstance

System/provider configuration:

```text
DetectionProviderInstance
  id
  type
  name
  enabled
  config
  credential_secret_ref nullable
  health_state
  last_connected_at
  last_observation_at
  last_error_code
  sanitized_error
  created_at
  updated_at
```

External service credentials belong in SecretStore.

## DetectionProviderBinding

Maps an external provider source to a canonical Camera.

```text
DetectionProviderBinding
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

One Camera may have multiple providers simultaneously.

Disabling a provider for recording or alerts does not suppress its canonical event persistence when timeline ingestion remains enabled.

## Provider capabilities

Normalized capability report may include:

```text
stateful_events
instant_events
tracked_objects
bounding_boxes
zones
snapshots
object_classes
sub_labels
face_recognition
license_plate_recognition
audio_detection
confidence_scores
source_timestamps
reconciliation
```

UI exposes what a provider can actually supply rather than assuming every AI provider behaves like Frigate.

## DetectionObservation

Append-oriented normalized source update:

```text
DetectionObservation
  id
  provider_instance_id
  binding_id
  camera_id

  provider_event_key
  provider_track_key nullable
  provider_sequence nullable

  transition             start | update | end | pulse | instant
  provider_event_type
  canonical_hint

  source_occurred_at
  received_at
  occurred_at
  timestamp_quality

  object_class nullable
  object_subclass nullable
  confidence nullable
  bounding_box nullable
  provider_zones
  attributes

  snapshot_ref nullable
  payload_digest
  metadata
  created_at
```

Coordinates are normalized to the source frame where present:

```text
x, y, width, height in [0,1]
```

Raw payload retention is optional/bounded. Credentials and unnecessary sensitive transport data are never stored in raw payload metadata.

## Observation idempotency

Provider delivery is assumed at-least-once unless the provider guarantees otherwise.

Stable local idempotency uses provider identity plus provider event/track key and provider revision/sequence or payload digest.

Repeated MQTT messages, PullPoint redelivery, bridge retries, or process restart must not create duplicate DetectionEvents.

## DetectionEvent

DetectionEvent becomes the provider-neutral aggregate produced from one logical source event/track.

Recommended fields:

```text
id
camera_id
source_kind
provider
provider_instance_id
external_id

event_type
object_class nullable
object_subclass nullable

lifecycle_kind          stateful | instant
status                  active | completed
end_reason nullable

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
fusion_group_id nullable

metadata
created_at
updated_at
```

`last_activity_at` is distinct from `started_at` and is useful for providers that refresh an active track many times.

## Canonical taxonomy

Do not encode every vendor label directly into one fixed enum.

Canonical event_type families:

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

`object_class` carries semantic target labels:

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

AlertRule/recording filters may use event_type and/or object_class.

Legacy simple event labels such as person/vehicle can be mapped into `event_type=object` plus the corresponding object_class at the adapter boundary.

## Provider-specific labels

Unknown AI labels are preserved as object_class/provider metadata rather than discarded.

Canonical aliases may normalize common synonyms, for example vendor-specific human/person labels, without rewriting the provider's original value.

## Stateful lifecycle

Provider adapters normalize to:

```text
START -> UPDATE* -> END
```

Updates mutate the DetectionEvent aggregate summary while DetectionObservation preserves the update history.

Repeated activity for the same provider_event_key/provider_track_key never creates a new business event.

Once a DetectionEvent is completed, late stale updates do not reopen it. They may be retained as late observations/diagnostics.

## Instant lifecycle

Instant sources produce:

```text
started_at = occurred_at
ended_at   = occurred_at
status     = completed
```

Spec 0002 recording pre/post-roll semantics apply.

## Pulse-only lifecycle

Pulse-only providers may derive one stateful event using an adapter-owned hold deadline:

```text
pulse
  -> START if idle
  -> refresh liveness deadline

no pulse before deadline
  -> END
```

The hold timeout is event normalization policy, not recording duration.

## Provider disconnect during active event

A stateful event must not remain ACTIVE forever because its provider disappeared.

Provider binding may define:

```text
disconnect_grace
active_event_liveness_timeout
```

On disconnect:

- do not immediately falsify an END if the source may reconnect;
- mark active source state uncertain;
- attempt provider reconciliation/reconnect;
- after the bounded liveness deadline, close unresolved source events with `end_reason = provider_lost`;
- RecordingManager then applies normal post-roll.

Reconnection with authoritative active-state reconciliation may preserve/repair the event where provider semantics safely allow it.

## Out-of-order events

Business state transitions are monotonic.

Rules:

- source timestamp is preserved even when delivery is late;
- current aggregate state does not regress because an older UPDATE arrives;
- END before START may be reconciled into a completed event if the adapter has sufficient identity/timestamps;
- ambiguous malformed transitions are stored as rejected/diagnostic observations rather than corrupting active state.

## Time normalization

Spec 0009 owns canonical time provenance.

Provider timestamps are normalized into:

```text
source_occurred_at
received_at
occurred_at
timestamp_source
timestamp_quality
clock_offset_ms_applied
```

Frigate/server-originated time and camera-originated ONVIF/HIK time are not assumed to have the same trust/offset characteristics.

## Bounding boxes and tracks

Tracked-object providers may update bounding boxes over time.

DetectionEvent keeps only the current/best summary needed for ordinary UI; DetectionObservation can retain sampled historical boxes.

Do not persist every video-frame box by default.

Sampling/retention limits protect SQLite/PostgreSQL size and write rate.

## EventZone

zero-nvr supports canonical per-Camera zones:

```text
EventZone
  id
  camera_id
  name
  enabled
  normalized_polygon
  color/presentation
  created_at
  updated_at
```

Coordinates are normalized to the Camera frame/profile reference geometry.

## Provider zone mapping

Provider-defined zones map into canonical zones:

```text
ProviderZoneBinding
  detection_provider_binding_id
  provider_zone_key
  event_zone_id
```

Provider zone semantics are preserved.

For example, if an external provider defines its own rule for deciding when a bounding box is 'inside' a zone, zero-nvr does not silently recompute and overwrite that result unless explicitly configured.

## Zone membership history

For stateful tracked objects, zero-nvr may persist:

```text
DetectionEventZoneInterval
  detection_event_id
  event_zone_id
  entered_at
  exited_at nullable
```

This supports precise zone-entry/exit timelines and alert rules without losing the provider's current-zone updates.

## Snapshots and evidence

Provider snapshots are evidence, not provider ownership of zero-nvr history.

When policy requests an event snapshot:

```text
provider snapshot / media-plane frame
        ↓
validate size/type
        ↓
store as zero-nvr StorageObject
        ↓
DetectionEvent.snapshot_object_id
```

Failure to capture/import a snapshot does not drop the DetectionEvent.

Do not rely on Frigate/vendor thumbnail retention for long-term zero-nvr event history.

## Best snapshot selection

Tracked-object providers may submit improved snapshots during UPDATE.

zero-nvr may replace the DetectionEvent's preferred snapshot reference when the new evidence is better according to provider score/quality policy, while prior observations remain traceable if retained.

## Recognition attributes

Face/LPR/sub-label information is optional structured metadata:

```text
recognition_kind
recognition_value
recognition_confidence
```

These values may be sensitive and follow camera-scope authorization, export permissions, retention configuration, and log-redaction rules.

Recognition metadata is never used as an authentication identity.

## Event fusion problem

Multiple providers may report the same physical occurrence:

```text
ONVIF motion
HIK smart event
Frigate person
local motion
```

Do not destructively merge these independent source events.

Instead create a correlation layer.

## EventFusionGroup

```text
EventFusionGroup
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
EventFusionMember
  fusion_group_id
  detection_event_id
  relation
  confidence
  created_at
```

Possible relations:

```text
same_occurrence
supports
derived_from
possibly_related
```

## Conservative fusion

Automatic cross-provider correlation may consider:

- same Camera;
- overlapping/near timestamps;
- compatible event/object classes;
- matching canonical zones;
- bounding-box overlap when comparable;
- provider/source priority;
- track identity supplied by an integration.

Fusion must be conservative.

Low-confidence correlation remains separate or `possibly_related`; it never deletes events.

## Fusion effects

Fusion is a presentation/policy hint:

- timeline UI may collapse one fusion group into one card with provider badges;
- AlertEvaluator may use fusion_group_id for dedup/grouping;
- forensic detail always exposes every member event/observation;
- RecordingManager still sees valid canonical source events and its one-pipeline intent arbitration prevents duplicate recorder creation.

Fusion must not rewrite member timestamps/end state to force providers to agree.

## Provider priority and policy

Camera detection policy may specify which providers are eligible for which actions.

Example:

```text
ONVIF motion
  timeline = true
  recording = true
  alerts = false

Frigate person
  timeline = true
  recording = true
  alerts = true
```

This allows native motion to preserve prebuffer/recording while AI object events drive human notifications.

## DetectionPolicy

Conceptual model:

```text
DetectionPolicy
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

Recording policy still owns pre/post-roll and RecordingIntent behavior; DetectionPolicy only decides which canonical events are eligible inputs.

## ONVIF provider

ONVIF event ingestion uses the maintained ONVIF library/event service rather than hand-built SOAP.

Support includes:

- PullPoint subscription where supported;
- renew/unsubscribe/reconnect;
- synchronization point/state recovery where supported;
- canonical topic mapping;
- motion/property-state START/END normalization;
- instant analytics/alarm topics;
- unknown topic preservation as custom events.

Subscription lifecycle follows Spec 0019 generation fencing.

## HIK provider

HIK/vendor bridge may provide richer smart events than ONVIF.

Rules:

- map vendor events into the same DetectionObservation contract;
- correlate with the same canonical Device/Camera;
- do not create duplicate Camera identities;
- retain vendor event code in metadata;
- use fusion/correlation when ONVIF and HIK report the same physical occurrence.

## Frigate provider

Frigate is an optional-to-enable DetectionProvider, not a competing NVR database.

Initial integration:

```text
Frigate MQTT events
  -> tracked-object lifecycle observations

Frigate API
  -> capability/health/detail/snapshot reconciliation where needed
```

Frigate camera names are mapped explicitly to zero-nvr Camera IDs through DetectionProviderBinding.

Frigate's tracked object ID becomes provider_event_key/provider_track_key; repeated new/update/end messages update one DetectionEvent.

Frigate zones map to canonical EventZones where configured.

Frigate review items may enrich severity/context/fusion but do not create a second duplicate DetectionEvent by default for every underlying tracked object.

zero-nvr never treats Frigate recordings, retention, or event database as authoritative NVR history.

## Frigate reconnection

MQTT reconnect is idempotent.

After a connectivity gap, the adapter reconciles recent/active provider state through available Frigate interfaces where practical, then closes unresolved stale events by liveness policy.

Do not fabricate continuous AI coverage across an interval where the provider was unavailable.

## Local lightweight motion provider

Built-in local motion is a DetectionProvider consuming the `detection` MediaStream role.

It implements the hysteresis/hold state machine from Spec 0002:

```text
IDLE
  -> sustained motion
ACTIVE
  -> sustained quiet
IDLE
```

Detection compute must not run on the FastAPI request loop.

Sampling rate/resolution and CPU/resource limits are configurable.

Local detector overload degrades/drops detection work explicitly; it must not destabilize recording.

## AI provider resource isolation

External AI or local detection failure does not stop normal camera recording unless the user's RecordingPolicy specifically requires event-only recording and no event source remains available.

System health distinguishes:

```text
provider unavailable
detection delayed
detection backlog
observation dropped/invalid
event normalizer error
```

Recording transport/source health remains separate.

## Provider health

Normalized states:

```text
disabled
starting
healthy
degraded
disconnected
auth_failed
misconfigured
unsupported
```

Metrics include:

```text
last_observation_at
ingest_rate
processing_lag
reconnect_count
invalid_observation_count
deduplicated_count
active_event_count
observation_backlog
```

## Event Center UI

Event Center supports:

- event type;
- object class/sub-label;
- Camera/CameraGroup;
- provider;
- zone;
- confidence;
- active/completed;
- time range;
- snapshot availability;
- fusion group/provider detail.

An event card shows canonical summary first and provider detail on demand.

Tracked-object detail may show:

```text
person
confidence 92%
Front Yard
Frigate
12:01:04 - 12:01:17
snapshot
linked recording
correlated native motion
```

## Provider settings UI

System/Detection settings include:

```text
Providers
  ONVIF native
  HIK native
  Frigate
  Local motion

Per Camera
  provider bindings
  timeline/recording/alert eligibility
  object/event filters
  zone mappings
  fusion policy
  snapshot policy
```

Frigate setup provides connection test, MQTT/API health, Camera mapping, and sample-event diagnostics.

## Permissions

Existing `event.view` governs viewing canonical events within camera scope.

`camera.manage` or `integration.manage` is required for provider/camera binding and detection configuration according to where the setting lives.

Changing system-wide external provider credentials/configuration requires `integration.manage`.

Event export/download remains governed by existing recording/export permissions for linked media/evidence.

## Audit

Audit at minimum:

```text
detection.provider_created
detection.provider_updated
detection.provider_disabled
detection.binding_created
detection.binding_updated
detection.policy_updated
detection.zone_created
detection.zone_updated
detection.zone_deleted
```

Automatic observations/events are operational/business records, not one AuditEvent per detection.

## Interaction with RecordingManager

DetectionProvider never starts/stops FFmpeg or ZLM recording.

```text
DetectionObservation
      ↓
DetectionEvent
      ↓
DetectionPolicy eligibility
      ↓
RecordingManager
      ↓
RecordingIntent(event)
```

Multiple simultaneous/fused events still result in one formal media pipeline because RecordingManager arbitrates additive intents.

Provider failure/end semantics affect only the event intents owned by those events; continuous/manual/schedule intents remain independent.

## Interaction with Alerting

AlertEvaluator consumes canonical DetectionEvent transitions.

AlertRule may filter:

```text
event_type
object_class
object_subclass
provider
zone
confidence
fusion_group
```

Event fusion/grouping helps suppress duplicate notifications but never suppresses source event persistence.

## Restart recovery

After zero-nvr restart:

- provider bindings are reconstructed;
- subscriptions/MQTT consumers reconnect with generation fencing;
- active DetectionEvents reconcile through provider state where possible;
- unresolved stale stateful events close via liveness timeout rather than remaining active forever;
- observation deduplication survives restart through durable provider event identity;
- RecordingManager reconstructs active event intents from canonical state/policy.

## Acceptance tests

1. repeated Frigate new/update messages with the same tracked-object ID update one DetectionEvent rather than creating duplicates;
2. Frigate end completes the same event and preserves zone/snapshot updates;
3. ONVIF motion true/false normalizes into one START/END DetectionEvent;
4. pulse-only native event refreshes one hold deadline rather than creating repeated markers;
5. provider disconnect cannot leave a stateful event active forever;
6. out-of-order stale update cannot reopen a completed DetectionEvent;
7. same physical occurrence reported by ONVIF + HIK/Frigate can enter one EventFusionGroup while all member events remain queryable;
8. low-confidence cross-provider match remains separate and is never destructively merged;
9. provider zone mapping preserves external zone semantics and canonical zone history;
10. snapshot failure does not drop the event;
11. recognition/sub-label metadata is retained without appearing in logs/secrets;
12. recording-disabled/alert-enabled provider event remains in timeline and may alert without creating RecordingIntent;
13. Frigate outage does not corrupt zero-nvr Camera/Recording history or make Frigate authoritative;
14. local motion overload degrades detector health without interrupting recorder/media runtime;
15. restart/reconnect deduplication prevents replayed provider messages from duplicating events.

## Invariants

1. DetectionProvider reports observations; zero-nvr owns canonical DetectionEvent state.
2. External provider databases/recordings never become zero-nvr's event/media source of truth.
3. DetectionObservation is append-oriented source evidence; DetectionEvent is the canonical business aggregate.
4. Provider ingress is idempotent and tolerant of at-least-once delivery.
5. Stateful event transitions are monotonic; stale updates cannot reopen completed events.
6. Provider loss cannot leave active events indefinitely.
7. Canonical time provenance follows Spec 0009.
8. Unknown provider labels/topics are preserved without polluting the canonical taxonomy.
9. Event fusion is non-destructive correlation, not source-event deletion.
10. Zone semantics from external providers are preserved and explicitly mapped.
11. Provider snapshot/evidence failure never causes event loss.
12. Recording eligibility and alert eligibility are independent provider/event policy decisions.
13. Multiple providers/events never create duplicate recorder pipelines; RecordingManager remains sole lifecycle owner.
14. AI/local detection resource pressure never destabilizes healthy recording.
15. Provider configuration/secrets obey camera/integration authorization and SecretStore rules.
16. Non-obvious deduplication, out-of-order handling, liveness timeout, fusion, and provider normalization logic requires comments per Development Guidelines.