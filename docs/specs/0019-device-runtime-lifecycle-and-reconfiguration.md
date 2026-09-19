# Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift

Status: **accepted**

## Goal

Define the first-production-release runtime lifecycle after a Device/Camera has been onboarded.

Core rule:

> Desired configuration is durable domain state. Device/media/event/PTZ/time runtimes are replaceable projections of that configuration and may be restarted, reprobed, or replaced without changing Camera identity.

This specification covers:

- enable/disable and maintenance lifecycle;
- runtime supervision and restart;
- endpoint/credential/profile changes;
- capability/profile drift;
- multi-channel Device changes;
- event/PTZ/time subscription recovery;
- interaction with ZLMediaKit and RecordingManager;
- revision fencing, idempotency, race handling, health, audit, and UI.

## Runtime ownership

Separate durable configuration from runtime state.

```text
Device / Camera / MediaStream configuration
              ↓
       RuntimeSupervisor
      /       |        \
DeviceControl MediaSource Event/Control
 runtime       runtime    runtimes
              ↓
         ZLMediaKit
              ↓
       RecordingManager
```

Runtime state is reconstructable after process restart. ZLMediaKit/vendor SDK/WVP state is never the source of truth for whether a Camera exists.

## Desired state

Device and Camera have durable desired state:

```text
enabled
disabled
maintenance
```

`disabled` means zero-nvr intentionally stops managed runtime activity while retaining configuration/history.

`maintenance` temporarily suppresses automatic runtime recovery/actions that would interfere with an explicit administrator operation, while preserving identity/history.

Maintenance is never inferred from ordinary network failure.

## Runtime aggregate

Conceptual read model:

```text
CameraRuntimeStatus
  camera_id
  desired_state
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

Do not collapse these dimensions into one boolean `online` field.

## Configuration revisions

Any runtime-relevant committed configuration change increments a monotonic revision.

Examples:

```text
endpoint change
credential change
MediaStream role/profile change
camera enable/disable
device adapter binding change
time-management configuration change
```

Every asynchronous runtime operation carries the revision/generation it was started for.

Callbacks/results from stale revisions are ignored for authoritative state mutation.

Example:

```text
rev 10 starts reconnect
rev 11 changes credentials and starts new reconnect
late callback from rev 10 arrives
  -> record diagnostic if useful
  -> do not overwrite rev 11 runtime state
```

This revision fencing applies to:

- ZLM registration/webhooks;
- ONVIF/vendor probe results;
- event subscription callbacks;
- reconnect timers;
- PTZ/control responses where state mutation would occur;
- profile verification jobs.

## Runtime generations

Short-lived media/event runtime instances also carry generation IDs.

```text
camera_id
role
config_revision
runtime_generation
```

Generation IDs prevent an old stream/subscription from being mistaken for the current one after hot replacement.

## Device control runtime

Management/control health states:

```text
disabled
starting
healthy
degraded
reprobing
reconnecting
auth_failed
offline
maintenance
needs_attention
```

`auth_failed` is distinct from network `offline` so the UI does not endlessly suggest reconnecting when credentials are wrong.

Control-runtime failure does not automatically imply media failure.

## Media source runtime

Media transport/source state remains governed by Spec 0008:

```text
streaming
degraded
reconnecting
offline
```

This specification adds revision/generation fencing and planned reconfiguration behavior around that state machine.

## Enable

Enabling a Camera/Device is idempotent.

Conceptual sequence:

```text
desired_state = enabled
  ↓
resolve current endpoint/credential/profile revision
  ↓
start/probe required control runtime
  ↓
ensure required MediaStream runtimes
  ↓
start required event/time/control runtimes
  ↓
RecordingManager evaluates persisted RecordingIntents/policy
```

Repeated enable requests must not create duplicate ZLM proxies, duplicate event subscriptions, or duplicate recorders.

## Disable

Disabling is explicit configuration, not a failure.

```text
desired_state = disabled
  ↓
stop new reconnect/reprobe scheduling
  ↓
end/withdraw runtime-owned event subscriptions
  ↓
remove active media proxies/readers when no longer needed
  ↓
RecordingManager removes intents that depend on enabled policy/runtime
  ↓
finalize active physical recording safely
```

Historical recordings/events remain queryable.

Disable/enable is audited.

## Device-wide versus channel-wide disable

Disabling a Device disables all child Camera runtimes unless an adapter supports independent channels and product policy explicitly permits a narrower Device maintenance action.

Disabling one Camera channel does not require disabling sibling channels.

## Runtime supervisor restart

On zero-nvr control-plane restart:

```text
load durable Device/Camera config
  ↓
reconstruct desired runtimes
  ↓
inspect existing ZLM/vendor/WVP runtime where possible
  ↓
adopt matching current-generation runtime
or
replace stale/unowned runtime
```

Do not assume every external process restarted just because FastAPI restarted.

Adoption must verify identity/config generation before reuse.

## Configuration apply pipeline

Runtime-relevant changes use prepare -> validate -> commit -> apply.

```text
proposed config
  ↓
prepare candidate secret/endpoint/profile
  ↓
validate candidate
  ↓
commit durable config + revision
  ↓
apply runtime transition
  ↓
verify effective runtime
```

Validation failure keeps the last working configuration whenever practical.

Post-commit runtime failure leaves explicit `needs_attention` state and recovery path; it never silently rewrites the committed configuration back without policy/audit.

## Change classification

Changes are classified so zero-nvr restarts only what is necessary.

```text
metadata_only
control_reconnect
media_role_switch
full_device_reconfigure
destructive/remove
```

### metadata_only

Examples: display name, location, group membership.

No device/media restart.

### control_reconnect

Examples: ONVIF management endpoint or credential change where stream URI remains equivalent.

Rebuild control/event/time runtimes; media may continue if still valid.

### media_role_switch

Selected SourceMediaProfile/stream URI changes for one or more product roles.

Only affected media/detection/recording runtimes are replaced.

### full_device_reconfigure

Examples: adapter identity change, device replacement, endpoint change that alters all stream URIs.

Reprobe and rebuild affected child runtimes under a new revision.

## Endpoint change

For a discovered stable Device moving to a new IP:

```text
probe candidate endpoint
  ↓
confirm stable identity
  ↓
commit preferred DeviceEndpoint revision
  ↓
start shadow control/media verification
  ↓
switch runtimes
  ↓
retire old endpoint when stable
```

Old endpoint is not deleted before the new endpoint has passed required validation unless the old endpoint is already known dead.

## Credential change

Credential replacement follows Spec 0012/0018.

New secret is validated first. On success, the new secret_ref is committed and affected runtimes move to the new revision.

Old runtime callbacks cannot restore old auth status due revision fencing.

## Source profile refresh and drift

Firmware/config changes may add, remove, or alter SourceMediaProfiles.

Reprobe computes a diff:

```text
unchanged
added
removed
changed codec/resolution/fps/URI
identity ambiguous
```

Profile rows should preserve stable adapter identity where possible and record last verification.

## Selected profile disappears

If a selected profile disappears:

```text
MediaStream.status = selection_invalid
```

Then:

- if selection_mode=auto, choose and validate a safe replacement according to Spec 0018;
- if selection_mode=manual, do not silently choose a materially different source unless explicit fallback policy is enabled;
- surface warning and runtime impact;
- audit/config-history the resulting selection change.

Recording must never silently downgrade quality without an observable reason.

## Planned recording-profile switch

A validated recording-profile change should avoid an arbitrary mid-file cut when possible.

Preferred flow:

```text
validate new source in shadow runtime
  ↓
wait for current safe formal segment boundary
  ↓
finalize current segment normally
  ↓
switch recorder/source
  ↓
start next segment on new profile
```

RecordingSession and active RecordingIntents remain unchanged.

When switched exactly at the planned segment boundary, the existing formal cadence may continue.

## Forced recording-profile switch

If the old selected profile has already failed/disappeared:

```text
finalize current physical segment
completion_reason = source_reconfigured
  ↓
switch to verified replacement
  ↓
start new physical segment
```

The same logical RecordingSession/Intents remain active if recording is still required.

A forced discontinuity resets the physical segment cadence from actual recovery/switch time, consistent with Spec 0008.

## Live profile switch

`live_main` / `live_preview` switches use a new runtime generation.

Where MediaPlane supports shadow bring-up:

```text
ensure new ZLM stream
  ↓
verify
  ↓
mark new generation current
  ↓
expire/remove old runtime after grace
```

Existing browser sessions may reconnect/reissue a short-lived media session. They must never receive camera credentials.

## Detection profile switch

Changing detection source invalidates detector runtime generation.

Old-generation detections arriving after cutover are ignored as current-state updates.

If a stateful detector had an active START when its runtime is intentionally replaced, the provider lifecycle is explicitly closed with a reconfiguration reason so a stale active event cannot hold RecordingIntent forever.

Other recording intents are unaffected.

## Event subscription lifecycle

Event runtime states:

```text
disabled
starting
subscribed
renewing
degraded
reconnecting
unsupported
auth_failed
```

Subscriptions are revision/generation fenced.

Renewal/reconnect uses backoff and jitter and must be idempotent.

Duplicate subscriptions are avoided; if a vendor/ONVIF endpoint may temporarily have both old/new subscriptions during handoff, duplicate source events are deduplicated by canonical event identity/correlation rules.

## Capability drift

DeviceCapabilitySnapshot is historical/current observed capability, not an eternal promise.

Examples:

```text
PTZ supported -> unsupported
Events available -> unavailable
NTP management available -> unavailable
audio profile removed
firmware changes profile tokens
channel added/removed
```

Capability loss never silently deletes user configuration.

Instead zero-nvr marks dependent features:

```text
available
temporarily_unavailable
unsupported_currently
configuration_invalid
```

and presents remediation.

## PTZ capability loss

If PTZ disappears:

- stop exposing operational PTZ controls as usable;
- keep historical/audit state;
- do not erase PTZ-related configuration immediately;
- refresh capability on explicit reprobe/recovery;
- stale PTZ responses from old generations do not mutate current state.

## Time-management capability loss

If device time/NTP management disappears:

- CameraClockStatus may continue using monitor/fallback behavior where time read is available;
- `manage_ntp` becomes ineffective/needs_attention rather than silently changing to another policy;
- no repeated aggressive SetSystemDateAndTime/NTP calls;
- health/alert explains the capability loss.

## Multi-channel Device drift

For NVR/DVR/GB28181 devices, channel inventory may change.

Channel outcomes:

```text
existing_present
new_unmanaged_channel
configured_channel_missing
identity_conflict
```

New channels are candidates for onboarding; they are not automatically created as fully managed Cameras unless policy explicitly enables trusted auto-enrollment.

A configured channel that disappears is retained as the same Camera in `missing/offline` state so history remains attached.

If it later returns with the same stable channel identity, the existing Camera is revived.

## Device replacement and identity conflict

A new physical device at an old endpoint never inherits old Device identity solely from address.

If stable identity differs, runtime enters identity_conflict/needs_attention and recording/control does not silently bind historical Camera identity to the new hardware.

Use the explicit replacement workflow from Spec 0018.

## Runtime health

Health is layered and cause-aware.

Conceptual statuses:

```text
control
media
recording
events
ptz
clock
capability
```

Each exposes state, since/last-success, error code, sanitized diagnostic, and relevant config revision/runtime generation.

Overall Camera health is a UI summary only; domain decisions consume the component health they actually need.

## Alerts

Spec 0014 may generate incidents for:

```text
camera.control_unavailable
camera.media_offline
camera.event_subscription_failed
camera.profile_invalid
camera.identity_conflict
camera.capability_changed
camera.channel_missing
```

Alerting does not own runtime restart/recording lifecycle.

## Runtime reconciliation loop

Supervisor periodically/reactionally computes:

```text
desired runtime from durable config
vs
observed current runtime
```

and performs idempotent convergence.

Reconciliation is event-driven where possible and low-cadence as a safety net; do not poll devices aggressively.

## Concurrency and locking

Per Device/Camera runtime mutation uses a logical single-writer/lock boundary appropriate to the active database/runtime architecture.

Rules:

- serialize conflicting endpoint/credential/profile apply operations;
- allow independent read-only health queries;
- keep database transactions short;
- never hold DB locks across network/media calls;
- prepare/probe outside the commit transaction;
- re-check config revision before commit/apply;
- retries are idempotent.

This must work in SQLite and PostgreSQL production modes.

## Crash recovery

If zero-nvr crashes mid-reconfiguration:

- committed config revision remains authoritative;
- uncommitted candidate secrets/profiles are cleaned by lifecycle jobs;
- startup reconciliation reconstructs runtimes for committed revision;
- stale external runtimes are adopted only if identity/revision can be proven, otherwise replaced;
- recording partials/orphans follow existing media reconciliation specs.

## UI

Device Center device detail shows:

```text
Desired state
Applied revision

Control      Healthy
Media        Streaming
Recording    Healthy
Events       Subscribed
PTZ          Available
Clock        Warning
Capabilities Changed / Current

Endpoint
Credential status
Firmware
Channels
Profiles

[Refresh capabilities]
[Test connection]
[Reconnect]
[Disable]
[Maintenance]
```

Runtime/config changes show whether they are:

```text
no restart
control reconnect
stream handoff
recording boundary switch
full device reconfigure
```

## Permissions and audit

`camera.manage` is required for enable/disable, reconnect, capability refresh, endpoint/credential/profile changes, maintenance, and resolving identity conflicts.

Operational PTZ remains `camera.ptz`.

Audit at minimum:

```text
device.enabled
device.disabled
device.maintenance_started
device.maintenance_ended
device.reconnected
device.runtime_reconfigured
device.capability_changed
device.channel_missing
device.channel_returned
camera.profile_runtime_switched
camera.identity_conflict_detected
```

Automatic transient reconnect attempts live in operational runtime logs/health history, not one AuditEvent per retry.

## Acceptance tests

1. repeated enable/reconcile never creates duplicate ZLM proxies/subscriptions/recorders;
2. stale old-revision ZLM/event/probe callbacks cannot overwrite current runtime state;
3. credential change validates new secret and preserves old working secret on validation failure;
4. DHCP endpoint update hot-reconnects the same Device/Camera identities;
5. metadata-only Camera edit does not restart media;
6. planned recording-profile change switches at a safe segment boundary and preserves RecordingSession/Intent;
7. disappeared recording profile forces explicit `source_reconfigured` segment boundary and preserves logical recording intent;
8. live-preview profile switch replaces only the affected runtime generation;
9. detection runtime replacement closes stale stateful detection lifecycle and cannot hold recording forever;
10. ONVIF event subscription renewal/reconnect is idempotent and stale subscription events are fenced;
11. PTZ/time/event capability loss is visible without deleting user configuration;
12. NVR channel disappearance retains Camera identity/history and channel return revives the same Camera;
13. different stable Device identity appearing at old IP creates conflict rather than silently taking over;
14. control endpoint failure with healthy RTSP leaves media/recording health independently correct;
15. crash during reconfiguration reconstructs the committed revision after restart.

## Invariants

1. Durable Device/Camera configuration is authoritative; runtimes are reconstructable projections.
2. Runtime-relevant configuration is revisioned and stale asynchronous results are fenced.
3. Enable/disable/reconcile/reconnect operations are idempotent.
4. Control, media, recording, event, PTZ, clock, and capability health remain separate.
5. Configuration validation occurs before replacing working endpoint/credential/profile state where practical.
6. Metadata-only changes do not restart media.
7. Recording profile changes preserve RecordingSession/RecordingIntent; only physical segment continuity changes when necessary.
8. Intentional runtime reconfiguration never causes old callbacks/events to regain authority.
9. Capability loss does not silently erase user configuration.
10. Missing multi-channel sources retain canonical Camera identity/history.
11. Stable-identity conflict prevents an unknown replacement device from silently inheriting historical Camera identity.
12. Runtime locks never span external network/media operations.
13. SQLite and PostgreSQL modes preserve the same lifecycle correctness.
14. Automatic retries are observable but do not flood AuditEvent.
15. Non-obvious revision fencing, handoff, idempotency, race, and recovery logic requires comments per Development Guidelines.

## MediaSession runtime reference

Live browser sessions are not Device/Camera runtime source-of-truth objects. They are short-lived authorized MediaSessions defined in [Spec 0020](0020-live-view-media-session-and-talk.md).

A live_main/live_preview runtime-generation change causes active MediaSessions to re-resolve/reconnect. It does not expose stale camera/ZLM URLs indefinitely and does not recreate Camera identity.
