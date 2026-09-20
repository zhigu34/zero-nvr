# Spec 0014 — Alerts and Notifications

Status: **accepted**

## Goal

Define a complete but NVR-specific alert/notification model without building a generic incident-management/escalation platform.

Core rule:

> Event says what happened. Alert says zero-nvr wants user attention. NotificationDelivery records an attempt to deliver that alert.

Notification failure never blocks recording or Event persistence.

## Layering

~~~text
Event
  ↓
AlertPolicy
  ↓
Alert
  ↓
NotificationDelivery
  ↓
Apprise / SMTP / webhook / MQTT
~~~

System conditions such as camera offline, storage critical, archive failure, backup failure, or component outage are normalized into Event/system-event facts before alert evaluation.

## AlertPolicy

Conceptual model:

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

The predicate set is intentionally limited to NVR-relevant fields.

Do not add a generic expression language, visual flow editor, arbitrary code actions, or enterprise policy engine.

## Alert

Represents one user-attention item derived from an Event/condition.

~~~text
id
alert_policy_id
event_id
camera_id
severity
title
message
state                 active | acknowledged | resolved
opened_at
last_activity_at
acknowledged_at
acknowledged_by
resolved_at
correlation_id
created_at
updated_at
~~~

Acknowledgement means a human has seen the alert. It does not mean the underlying camera/storage condition recovered.

A source recovery may mark an active health Alert resolved.

For instant detection events, an Alert may be immediately resolvable/closed while remaining in alert history.

## Cooldown

Cooldown controls repeated outbound notification, not Event persistence.

During cooldown:

- matching Events are still stored;
- timeline markers remain;
- recording policy still runs;
- an existing active Alert may update last_activity_at;
- repeated notifications may be suppressed.

Keep this simple; V1 does not require generic incident grouping windows or complex escalation trees.

## NotificationTarget

Friendly UI configuration backed by Apprise/provider settings:

~~~text
id
name
type
enabled
secret_ref/config
health_state
last_test_at
last_error
created_at
updated_at
~~~

Initial channels may include:

- SMTP/email;
- Gotify;
- Telegram;
- Discord;
- generic Apprise-supported targets;
- outbound webhook;
- MQTT where explicitly configured.

Do not implement a separate custom provider client when Apprise already supports the channel adequately.

## NotificationDelivery

Product-visible delivery state:

~~~text
id
alert_id
notification_target_id
state                 pending | sending | sent | failed | suppressed
attempt_count
last_attempt_at
sent_at
last_error
provider_message_id
created_at
updated_at
~~~

Huey performs delivery/retry execution.

A separate generic message broker is not required.

## Retry

Use a small bounded retry policy for transient failures.

Classify at least:

~~~text
transient
permanent/configuration
rate_limited
~~~

The worker may use exponential backoff/jitter.

Retry state does not change the source Event or recording.

Repeated permanent configuration failures should surface NotificationTarget health rather than retry forever.

## SMTP and password reset

SMTP is a V1 platform capability because local account password reset may depend on it.

Password-reset email uses the same configured SMTP/notification delivery infrastructure where practical, but it is a security workflow rather than an Alert.

A broken SMTP configuration must still leave host-local/admin recovery available.

## Recording action

An AlertPolicy may request NVR-specific side effects such as:

- create RecordingProtection over the Event range;
- publish a normalized webhook/MQTT notification.

Do not generate a duplicate MP4 merely because an Alert exists.

Explicit user clip export remains an Export job.

## Quiet schedules

A policy may include an active/quiet schedule and timezone.

This is sufficient for V1.

A separate AlertSilence/maintenance-calendar subsystem is optional later if real usage requires it.

## Templates

V1 may ship built-in templates with a small safe customization surface.

Do not build a general template programming/scripting environment.

Templates never receive raw secrets.

## Snapshots and links

Notification may include:

- Event snapshot when authorized/available;
- short authenticated deep link into zero-nvr;
- camera/time/label/severity.

Never include permanent unauthenticated recording URLs or camera credentials.

## Permissions

Suggested permissions:

~~~text
alert.view
alert.acknowledge
alert.manage
notification.view
notification.manage
~~~

Camera-scoped users may only see Alerts/Events for cameras in their effective scope.

System-wide storage/security Alerts require suitable system scope.

## Audit

Audit:

- AlertPolicy create/update/delete;
- NotificationTarget create/update/delete/test;
- Alert acknowledgement/manual resolution;
- sensitive routing/config changes.

Do not write one AuditEvent for every automated delivery retry.

## Failure isolation

Examples:

~~~text
Frigate offline        -> AI alerts unavailable; recording continues
SMTP offline           -> delivery FAILED; Event/Alert persist
OpenList archive fail  -> archive alert; local recording continues
storage critical       -> Alert generated; deletion still obeys retention/protection
~~~

## UI

Alert Center should provide:

- active/recent Alerts;
- filter by camera/severity/type;
- acknowledge;
- link to Event/playback;
- delivery status;
- clear source condition when known.

Notification settings provide target configuration/test and simple policy routing.

## Acceptance tests

1. Matching Event creates one Alert according to policy.
2. Cooldown suppresses repeated outbound sends but not Events/recording.
3. Acknowledge does not mutate Event or stop recording.
4. Source recovery can resolve a health Alert.
5. SMTP failure creates failed delivery state and recording continues.
6. Retry survives worker restart through Huey/product state.
7. Camera scope prevents hidden-camera alert access.
8. Apprise target test does not expose secret plaintext.
9. RecordingProtection action protects the Event range without copying video.
10. Notification contains no permanent public media credential.

## Invariants

1. Event, Alert, and NotificationDelivery are separate concepts.
2. Alert policy never suppresses canonical Event persistence.
3. Notification failure never blocks recording.
4. V1 has no requirement for a generic incident/escalation/rule engine.
5. Cooldown affects delivery, not media/event truth.
6. Apprise/mature providers are preferred over custom channel implementations.
7. Alert acknowledgement is not source recovery.
8. Notification secrets remain in SecretStore.
