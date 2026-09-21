# Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift

Status: **accepted**

## Goal

Define how durable Camera/Device configuration is reconciled into ONVIF/ZLMediaKit runtime without creating a second media-runtime supervisor.

Core rule:

> zero-nvr owns desired product configuration and reconciliation. ZLMediaKit owns media pull/reconnect/recorder runtime. Mature ONVIF libraries own protocol mechanics.

See [Project Baseline](../PROJECT_BASELINE.md) and [ADR 0006](../adr/0006-zlm-owns-media-reconnect-runtime.md).

## Durable state vs runtime projection

Durable state includes:

- Device;
- Camera;
- DeviceEndpoint;
- Credential reference;
- CameraStreamProfile;
- CameraStreamBinding;
- RecordingPolicy;
- optional integration bindings.

Runtime state is reconstructable:

- ZLM proxy/media registration;
- ZLM recorder state;
- ONVIF event subscription;
- PTZ/time capability session;
- optional Frigate/provider connection.

Runtime state is not the business source of truth.

## RuntimeReconciler

The control plane exposes a thin RuntimeReconciler/service layer.

Responsibilities:

1. load desired durable configuration;
2. query relevant adapter/runtime state;
3. apply the minimum supported operation required to converge;
4. record meaningful health/error state;
5. remain idempotent across restart/retry.

It does not:

- inspect RTP packets;
- implement RTSP reconnect backoff;
- own a STREAMING/RECONNECTING transport state machine;
- spawn a second long-lived camera puller;
- duplicate ZLM recorder logic.

## Configuration revision

Runtime-relevant configuration should carry a monotonically increasing revision when asynchronous adapter work can race with newer configuration.

Typical examples:

- endpoint/credential test;
- profile refresh;
- ONVIF capability probe;
- event-subscription callback;
- delayed adapter result.

A stale result from revision N must not overwrite durable/runtime state already applied for revision N+1.

This is a concurrency-safety mechanism, not a reason to build a generic runtime framework.

## Camera enable / disable

### Enable

Conceptual flow:

```text
camera.enabled = true
-> validate required configuration
-> ensure ZLM stream proxy
-> apply recording desired state
-> ensure optional ONVIF event subscription
-> health projection
```

### Disable

```text
camera.enabled = false
-> stop zero-nvr-requested recording
-> remove/disable managed ZLM proxy where appropriate
-> release managed event subscriptions
-> preserve historical data/configuration
```

Disabling a camera never deletes historical recordings/events.

## Endpoint and credential change

Preferred flow:

```text
save candidate secret/config
-> validate with mature ONVIF/ZLM path
-> if validation succeeds, commit durable reference
-> reconcile runtime
```

Where safe, keep the previous working configuration until the candidate passes validation.

Do not implement a custom reconnect engine; after the endpoint/source is applied, ZLM owns reconnect behavior.

## Stream profile change

Camera stream identity and business purpose are separate.

A user may change:

- RECORD binding;
- LIVE_HIGH;
- LIVE_LOW;
- AI_DETECT;
- SNAPSHOT.

For a recording-source change:

- validate the new profile/source;
- prefer applying at a safe segment boundary where practical;
- finalize the old physical segment when media continuity changes;
- preserve RecordingPolicy/RecordingTrigger semantics;
- record the actual resulting timeline gap if one occurs.

No requirement exists to run a generic dual shadow media runtime in V1.

A temporary parallel validation stream may be used only if ZLM/device capabilities make it simple and demonstrably useful.

## Capability refresh and drift

Capabilities can change after firmware upgrade, credential/permission change, or endpoint replacement.

Periodic/manual refresh may update:

- ONVIF profiles;
- codec/resolution/framerate metadata;
- PTZ capability;
- event capability;
- audio capability;
- time/NTP capability.

Rules:

- user configuration is not silently deleted because a capability temporarily disappears;
- unsupported bindings become degraded/invalid with an actionable warning;
- recovered capability can become available again without recreating Camera identity;
- a changed IP/hostname does not create a new Camera when stable device identity proves it is the same device.

## Multi-channel devices

One Device may expose multiple Camera channels.

Runtime/capability refresh must preserve channel identity using stable evidence such as:

- ONVIF profile/channel tokens;
- device serial/hardware identity;
- vendor channel identity when an optional adapter is used.

Missing channels become unavailable; they are not silently deleted.

## ONVIF event subscription

Use mature ONVIF library mechanisms.

zero-nvr owns the product lifecycle:

- whether events are enabled;
- subscription creation/recreation after app restart;
- mapping events to Camera;
- normalized Event persistence;
- capability/health.

The ONVIF client/protocol implementation owns SOAP/WS-* details.

Renewal/retry should rely on the library and a small idempotent adapter loop, not a generic protocol engine.

## Health model

Health is layered by capability:

```text
control
media
recording
events
ptz
clock
ai
```

Examples:

- ONVIF control unavailable but RTSP/ZLM recording still healthy;
- camera media healthy but PTZ unsupported;
- recording healthy but AI provider offline.

Do not collapse every optional capability failure into Camera OFFLINE.

## Control-plane restart

After API/worker restart:

```text
load enabled Cameras
-> query ZLM / ONVIF / optional provider state
-> ensure required runtime projections
-> reconcile recording/catalog state
-> resume normal health/event handling
```

Already-running ZLM recording should not be deliberately stopped merely because FastAPI restarted.

## ZLM restart

When ZLM is restarted:

- media health becomes degraded/offline;
- zero-nvr waits for/observes ZLM availability;
- RuntimeReconciler ensures configured proxies/recording desired state again;
- physical recording gaps remain real;
- catalog reconciliation runs after media recovery.

ZLM remains responsible for source pull/reconnect behavior after configuration is restored.

## Maintenance mode

A camera may have an administrative maintenance flag that suppresses noisy alerts while preserving explicit visibility that the camera is intentionally under maintenance.

Maintenance does not silently rewrite RecordingPolicy or historical data.

## UI behavior

Camera detail should expose:

- enabled/disabled/maintenance;
- endpoint/control health;
- media health;
- recording health;
- event/PTZ/clock capability;
- latest configuration test error;
- capability refresh action;
- current stream-purpose bindings.

Advanced diagnostics may show ZLM/source details without exposing credentials.

## Audit

Audit actor-driven changes such as:

- camera enabled/disabled;
- endpoint changed;
- credential changed;
- stream binding changed;
- capability refresh requested;
- maintenance entered/exited.

Do not create one AuditEvent per automatic ZLM reconnect attempt.

## Acceptance tests

1. FastAPI restart:
   - durable Camera configuration survives;
   - RuntimeReconciler restores required adapter state;
   - healthy existing ZLM recording is not intentionally stopped.

2. Endpoint change:
   - invalid candidate does not destroy the last known-good secret/config where safe;
   - valid candidate is applied and ZLM handles source runtime.

3. Credential change:
   - secrets remain in SecretStore;
   - plaintext does not leak to logs/API.

4. Stream binding change:
   - new source is validated;
   - recording uses the new source at a safe boundary where practical;
   - any real gap remains visible.

5. Capability drift:
   - temporarily missing PTZ/event/profile capability becomes degraded rather than deleting user config.

6. DHCP/IP change:
   - same physical device is reconciled to the same Device/Camera identity when stable evidence exists.

7. ZLM restart:
   - product media health degrades;
   - configured runtime is restored;
   - no zero-nvr RTSP reconnect engine is involved.

8. Optional provider failure:
   - only that capability degrades;
   - core recording remains independent.

## Invariants

1. Durable Camera/Device configuration is authoritative product state.
2. Runtime projections are reconstructable and idempotent.
3. ZLM owns media transport/reconnect/recording runtime.
4. zero-nvr does not implement a competing RTSP reconnect state machine.
5. Stable device identity is not replaced merely because IP changes.
6. Capability loss does not silently delete durable user configuration.
7. Stale asynchronous adapter results cannot overwrite newer configuration.
8. Camera capability health is layered rather than one global status.
9. API/worker restart is recoverable without treating runtime state as canonical business data.
