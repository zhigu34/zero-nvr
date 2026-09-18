# Spec 0002 — Optional Home Assistant Integration

Status: **initial optional-feature design**

## Goal

Allow Home Assistant to participate in zero-nvr automation without becoming a core dependency or bypassing zero-nvr recording policy.

Primary use case:

```text
presence / PIR / door / smoke / doorbell sensor
        ↓
Home Assistant automation
        ↓
zero-nvr
        ↓
RecordingTrigger
        ↓
Recording Policy
        ↓
pre-roll + active window + post-roll
```

## Loading model

The integration is disabled by default.

### Core deployment

Requires no Home Assistant and no MQTT broker.

### REST integration

When enabled, Home Assistant may invoke authenticated external-trigger endpoints directly.

This is the minimum/lightweight integration mode.

### MQTT integration

Optional deeper integration may use MQTT for:

- Home Assistant MQTT Discovery;
- NVR/camera state publishing;
- approved command/trigger ingress;
- event state propagation.

MQTT is never required for core recording/playback.

### Custom Integration

A future Home Assistant custom component may provide native setup and entity UX.

It should consume the public zero-nvr API rather than embed recording/media implementation details.

## External trigger contract

Home Assistant does not call low-level operations such as:

```text
start_ffmpeg
stop_ffmpeg
start_zlm_stream
kill_recorder
```

It sends intent.

Conceptual request:

```json
{
  "source": "home_assistant",
  "external_id": "automation.front_door_presence",
  "camera_ids": [1],
  "event_type": "presence",
  "state": "active",
  "pre_roll_seconds": 10,
  "post_roll_seconds": 30,
  "metadata": {
    "entity_id": "binary_sensor.front_door_presence"
  }
}
```

The final API shape is deferred until the integration implementation phase.

## RecordingTrigger behavior

A logical trigger session may be refreshed repeatedly.

Example:

```text
sensor on
  → ACTIVE

sensor continues / automation retries
  → refresh last_active_at

sensor off
  → CLOSING

post-roll expires
  → COMPLETE
```

This avoids repeated recorder start/stop cycles caused by noisy sensors.

## Continuous recording behavior

If the camera is already recording continuously:

```text
external trigger
   ↓
do not launch duplicate recorder
   ↓
link/promote/annotate existing RecordingSegments
```

## Event recording behavior

When only event recording is enabled:

```text
pre-roll buffer / retained recent segments
       +
active trigger interval
       +
post-roll
       ↓
event recording
```

## Home Assistant → zero-nvr examples

Supported future scenarios may include:

- presence starts/extends event recording;
- door open triggers front-door recording;
- doorbell creates a high-priority event;
- smoke alarm triggers multiple cameras;
- lock state creates timeline metadata;
- HA occupancy state changes notification/recording policy.

## zero-nvr → Home Assistant

Deep integration may expose:

- camera online state;
- recording state;
- motion/person events;
- recording mode;
- snapshot action;
- external recording trigger action;
- storage health;
- zero-nvr health.

Possible HA entity classes:

```text
binary_sensor
sensor
switch
select
button
camera
```

Exact entity design is deferred.

## Security

Requirements:

- authenticated API token or equivalent;
- integration-specific permissions;
- external triggers scoped to permitted cameras/actions;
- no source-camera credentials exposed to HA;
- no direct process-management API;
- idempotency support for automation retries.

## Availability

Failure semantics:

```text
HA unavailable
  → HA automation features unavailable
  → core NVR continues

MQTT unavailable
  → MQTT integration degraded
  → REST/core NVR continues
```

## Non-goals

This integration does not make Home Assistant:

- the zero-nvr database;
- the recording scheduler;
- the media server;
- the source of truth for Camera configuration;
- a requirement for normal NVR use.

## Acceptance criteria for future implementation

- zero-nvr boots and records with the integration disabled.
- no MQTT broker is required unless MQTT mode is enabled.
- HA REST trigger can create/update one RecordingTrigger session.
- repeated trigger activity does not start duplicate recorder processes.
- continuous recording reuses existing segments.
- disabling/removing HA does not damage NVR recording history.
- integration credentials and permissions are isolated from camera credentials.
