# Spec 0021 — Detection Providers, AI Events, and Frigate Integration

Status: **accepted**

## Goal

Define a lightweight provider boundary for camera-native events and optional AI while keeping zero-nvr as the canonical Event/Alert/RecordingTrigger system.

Core rule:

> Providers observe. zero-nvr normalizes product-relevant observations. Providers do not become recording authority or the product source of truth.

V1 does not require a generic multi-provider fusion engine.

See [Project Baseline](../PROJECT_BASELINE.md) and [Spec 0013](0013-first-production-release-scope.md).

## V1 event sources

Supported source categories may include:

- ONVIF events;
- optional vendor-native events;
- Frigate AI;
- manual/API/Home Assistant/MQTT triggers;
- zero-nvr system health events.

Frigate is the primary supported optional AI provider for V1.

Additional AI providers may use the same adapter contract later.

## Provider boundary

A provider adapter is responsible for:

- connection/subscription;
- provider-specific authentication;
- mapping provider camera/source identity to zero-nvr Camera;
- parsing provider event payloads;
- preserving provider event identity;
- normalizing only the fields zero-nvr needs.

A provider adapter is not responsible for:

- starting/stopping ZLM recorder directly;
- retention;
- timeline storage;
- Alert policy decisions;
- zero-nvr user permissions;
- deleting canonical Event history.

## Canonical Event

Conceptual fields:

```text
Event
  id
  source
  source_event_id
  camera_id
  category
  label
  started_at
  ended_at
  confidence
  zone
  severity
  snapshot_ref
  metadata
  created_at
  updated_at
```

Examples:

- person detected;
- vehicle detected;
- ONVIF motion;
- line-crossing where supplied by device/provider;
- camera offline;
- storage critical;
- archive failed.

AI/device details that are useful but not worth first-class columns remain in bounded metadata.

## Provider identity and idempotency

Provider-originated events must retain a stable external identity.

Recommended uniqueness:

```text
(source/provider instance, source_event_id)
```

When a provider sends updates for the same tracked object/event, zero-nvr performs idempotent UPSERT rather than creating a new Event on every update.

At-least-once delivery is assumed unless a provider guarantees otherwise.

## Frigate integration

Preferred flow:

```text
Camera main/sub
   -> ZLMediaKit
   -> ZLM internal stream
   -> Frigate AI_DETECT input
   -> Frigate event updates
   -> FrigateAdapter
   -> zero-nvr Event
```

In Managed mode, Frigate should consume the ZLM internal stream rather than independently pulling the same camera when practical.

This reduces duplicate camera connections and keeps ZLM as the camera-facing media bus.

## Frigate event lifecycle

Frigate tracked objects may emit:

```text
new
update
end
```

All updates for the same Frigate event ID map to the same zero-nvr Event.

Typical mapping:

- Frigate ID -> source_event_id;
- camera mapping -> camera_id;
- label -> Event.label;
- start/end -> canonical timestamps;
- score/confidence -> confidence;
- zones -> zone/metadata;
- snapshot -> snapshot_ref.

Do not duplicate every raw Frigate message into a separate product event table unless needed for diagnostics.

## Event and RecordingTrigger

Event and RecordingTrigger are related but not identical.

An AlertPolicy/recording policy may turn an Event into a RecordingTrigger.

Example:

```text
Frigate person Event
-> recording policy matches
-> RecordingTrigger
   type = AI_OBJECT
   source = frigate
   source_event_id = ...
   correlation_id = ...
```

If continuous recording is already active, the Event is simply a timeline marker and may protect/annotate the existing footage. It does not require a second event video copy.

For EVENT_ONLY recording, the trigger participates in pre/post-roll and recording-window extension semantics.

## Frigate snapshots

Snapshot preference:

1. use Frigate event snapshot when the AI event already has one;
2. use ZLM snapshot for live/manual current image;
3. FFmpeg historical frame extraction only as fallback.

Do not regenerate an existing good Frigate snapshot with FFmpeg.

## Zones, labels, and confidence

Frigate owns its native:

- object detection;
- tracking;
- zones;
- confidence;
- model-specific attributes.

zero-nvr stores enough normalized fields to search, display, alert, and link playback.

The normal zero-nvr UI may expose common managed Frigate settings, but it should not reproduce every advanced Frigate configuration field. Advanced/raw override or External mode is preferable to cloning the full Frigate UI.

## Managed and External mode

### Managed

zero-nvr deployment may provide a Frigate container/profile and generate the subset of configuration it owns.

### External

The user may connect an already-running Frigate instance.

Both modes normalize into the same provider adapter/Event contract.

Frigate availability is capability-specific:

```text
Camera       ONLINE
Recording    OK
AI           DEGRADED/OFFLINE
```

AI failure must not stop normal recording.

## MQTT

If Frigate event integration uses MQTT:

- use an existing external broker when configured;
- optionally deploy Managed Mosquitto;
- do not force a duplicate broker when one already exists.

MQTT is transport, not the Event source of truth.

## Camera-native events

ONVIF/device motion/smart events use the same canonical Event model.

Do not route ordinary standard camera events through Frigate merely for normalization.

Vendor-private adapters are optional enhancements when ONVIF cannot expose the required signal.

## Multi-provider duplication

V1 does not implement a generic Event Fusion Engine.

If the same physical occurrence is reported by ONVIF and Frigate, both source Events may exist.

Product UI may later add simple correlation/grouping for presentation, but V1 must not risk deleting or rewriting source truth to force deduplication.

Advanced provider fusion/correlation is POST-V1 unless a concrete use case proves it necessary.

## Provider liveness

Provider health includes:

- reachable/connected;
- degraded;
- offline;
- disabled.

Persist meaningful provider state transitions as SystemEvents when useful.

Do not write high-frequency provider heartbeat samples into SQLite.

## Alerting

AlertPolicy evaluates canonical Event fields such as:

- camera;
- source/category;
- label;
- zone;
- confidence;
- duration;
- severity;
- time window.

The rule system remains NVR-specific; it is not a generic expression/automation platform.

## Permissions

Users only see AI/device Events for Cameras within their effective camera scope.

Provider administration requires system/integration management permissions.

Raw provider credentials are never returned through normal APIs.

## Acceptance tests

1. Frigate new/update/end:
   - one zero-nvr Event is updated idempotently;
   - start/end/confidence/zones are preserved.

2. Duplicate provider delivery:
   - retrying the same source event does not create duplicate Events.

3. Frigate offline:
   - AI health degrades;
   - ZLM live/recording remains healthy.

4. Managed stream path:
   - Frigate consumes the intended ZLM internal detect stream;
   - camera RTSP connection count does not multiply per downstream consumer.

5. External Frigate:
   - can map provider camera names/IDs to zero-nvr Camera.

6. Event recording:
   - matching AI Event creates/updates RecordingTrigger semantics without starting duplicate recorders.

7. Continuous recording:
   - AI Event is linked to existing footage rather than creating a second MP4 copy.

8. Snapshot:
   - existing Frigate event snapshot is reused.

9. Camera-native event:
   - ONVIF event maps into the same canonical Event API without requiring Frigate.

## Invariants

1. zero-nvr Event is canonical product event state.
2. Frigate owns AI detection/tracking, not recording authority.
3. Provider event identity is preserved for idempotent UPSERT.
4. AI failure never stops normal ZLM recording.
5. Events reference existing recording time ranges; they do not automatically duplicate media.
6. V1 does not require generic multi-provider event fusion.
7. Provider-specific raw detail is bounded metadata, not a second business database.
8. External and Managed provider modes share the same product contract.
