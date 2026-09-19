# Spec 0014 — Alert Incidents, Notification Routing, Escalation, and Delivery

Status: **accepted**

## Goal

Define the complete first-production-release alerting and notification model for zero-nvr.

Core rule:

> DetectionEvent says what happened. AlertIncident says what requires attention. AlertDelivery says what zero-nvr tried to notify and how it ended.

Notification failure must never block recording, event persistence, or media recovery.

## Layer separation

```text
DetectionEvent / System Health
          ↓
      AlertSignal
          ↓
       AlertRule
          ↓
     AlertIncident
          ↓
 Escalation / Routing
          ↓
     AlertDelivery
          ↓
 NotificationBackend
```

DetectionEvent remains provider-neutral camera/event truth. System/runtime health remains authoritative in its own models.

AlertSignal is the normalized evaluation envelope, not a replacement source-of-truth database:

```text
kind                 detection | health | security
source_type
source_id
camera_id nullable
signal_type
transition           open | update | resolve | instant
severity_hint
occurred_at
correlation_id
attributes
```

Security signals come from explicit aggregated authentication/security conditions, not arbitrary AuditEvent recursion.

## AlertRule

```text
AlertRule
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
  escalation_policy_id nullable
  created_at
  updated_at
```

Rule matching may include camera/group, canonical event type, provider/source, confidence, zone, lifecycle, health/security type, and schedule. Provider-specific metadata extensions must be namespaced and validated rather than becoming an unbounded rule DSL.

DetectionEvent persists even when no AlertRule matches.

## Health and security signals

Health alert types include at least:

```text
camera.offline
camera.clock_drift
recording.unavailable
storage.pressure
storage.critical
storage.unavailable
remote_archive.failed
secret_store.critical
host_time.unsynchronized
integration.offline
notification_backend.failed
```

Security signals may include:

```text
auth.brute_force_detected
auth.repeated_login_failure
user.lockout
mfa.recovery_used
critical_security_setting_changed
```

Raw high-volume authentication failures remain audit/security telemetry and are aggregated before alert creation.

## AlertIncident

```text
AlertIncident
  id
  alert_rule_id
  source_kind
  primary_source_type
  primary_source_id
  camera_id nullable
  group_key
  title
  severity
  lifecycle_state       active | resolved
  acknowledgement_state unacknowledged | acknowledged
  opened_at
  last_activity_at
  resolved_at nullable
  acknowledged_at nullable
  acknowledged_by nullable
  acknowledgement_note nullable
  trigger_count
  first_snapshot_object_id nullable
  latest_snapshot_object_id nullable
  correlation_id
  created_at
  updated_at
```

Lifecycle and acknowledgement are independent. These are all valid:

```text
active + unacknowledged
active + acknowledged
resolved + unacknowledged
resolved + acknowledged
```

One incident can reference many canonical source events:

```text
AlertIncidentSource
  alert_incident_id
  source_type
  source_id
  occurred_at
  transition
  created_at
```

Source DetectionEvents are never merged or deleted because they share an incident.

## Grouping, deduplication, and cooldown

Default camera-event grouping identity:

```text
alert_rule_id
+ camera_id
+ event_type
+ zone where applicable
```

group_window_seconds determines when compatible activity joins an existing incident.

cooldown_seconds suppresses repeated outbound actions; it never suppresses source-event persistence, recording behavior, incident trigger_count, or last_activity_at.

## Incident resolution

Supported rule modes:

```text
source
auto_timeout
manual
```

source resolves on canonical END/recovery.

auto_timeout resolves after no matching activity for the configured period and refreshes on new activity.

manual remains active until an authorized human resolves it.

Acknowledgement is not source recovery and does not stop recording.

## Severity

Canonical severities:

```text
info
warning
critical
```

Severity affects routing, escalation, and UI; it does not grant authorization.

## EscalationPolicy

```text
EscalationPolicy
  id
  name
  enabled
  stop_on_acknowledge
  stop_on_resolve
  created_at
  updated_at

EscalationStep
  id
  escalation_policy_id
  sequence
  delay_seconds
  repeat_interval_seconds nullable
  max_repeats nullable
  action_set_id
```

Escalation timers are persisted and recover after restart. Acknowledgement or resolution cancels future steps according to policy.


## Action sets and notification targets

Reusable routing:

```text
AlertActionSet
  id
  name
  enabled
  created_at
  updated_at

AlertAction
  id
  action_set_id
  notification_target_id
  template_id nullable
  send_on             opened | repeat | escalated | resolved
  include_snapshot
  include_deep_link
  enabled
```

NotificationTarget:

```text
NotificationTarget
  id
  name
  type
  enabled
  config
  credential_secret_ref nullable
  health_state
  last_health_at
  last_error
  created_at
  updated_at
```

First-production-release target types:

```text
smtp
apprise
webhook
home_assistant
mqtt
```

Optional means optional to enable, not deferred implementation.

SMTP uses system SmtpSettings for transport and target/action configuration for recipients/templates.

Webhook supports URL, an allowed HTTP method, content type, headers, SecretStore-backed authentication, optional HMAC signing secret, timeout, and delivery/idempotency identifiers.

Home Assistant and MQTT actions go through IntegrationAdapter and never directly manipulate FFmpeg or ZLMediaKit internals.

## RecipientGroup

```text
RecipientGroup
  id
  name
  created_at
  updated_at

RecipientGroupMember
  recipient_group_id
  user_id nullable
  email_address nullable
```

User-linked recipients follow the user's current verified email. Explicit external addresses remain literal.

## NotificationTemplate

```text
NotificationTemplate
  id
  name
  channel_type
  locale
  subject_template nullable
  body_template
  body_format          text | html | json
  built_in
  created_at
  updated_at
```

Supported variables are explicit and sandboxed.

Examples:

```text
incident.id
incident.title
incident.severity
incident.opened_at
camera.name
event.type
event.zone
event.confidence
system.name
deep_link
```

Templates cannot access arbitrary object attributes, executable expressions, or secrets.

Built-in templates cover camera detection, camera offline/recovery, storage/system critical, security, and resolved notices. Password-reset mail uses the platform mail service but is not an AlertIncident.

## Snapshots and deep links

A rule may include an event snapshot when available.

- missing optional snapshot does not fail the message;
- snapshot/object retrieval is bounded and separately diagnosed;
- credentials and secrets never enter the message;
- normal links point to authenticated zero-nvr UI;
- permanent public playback URLs are forbidden.

If an external channel requires direct media, use an explicitly short-lived narrowly scoped resource token.

## Quiet periods and AlertSilence

Recurring quiet hours belong to AlertRule and use the explicit timezone semantics from Spec 0009.

```text
AlertSilence
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

Default:

```text
suppress_notifications = true
suppress_incident_creation = false
```

Silence never suppresses DetectionEvent persistence or recording behavior. Silence management is audited.

## Notification storm protection

System and target safety controls include:

```text
max deliveries per target per minute
max deliveries per incident per interval
queue backlog threshold
global emergency cap
```

When limits trigger:

- events and incidents continue to persist;
- delivery is deferred or suppressed with an explicit reason;
- notification health shows pressure;
- an aggregated suppression summary may be sent later.

Never drop DetectionEvents to control notification volume.

## Durable delivery

```text
AlertIncident transition
       ↓
DeliveryPlanner
       ↓
AlertDelivery
       ↓
Notification Worker
       ↓
NotificationBackend
```

Recording and event transactions never wait on SMTP, webhook, or provider network calls.

```text
AlertDelivery
  id
  alert_incident_id nullable
  alert_rule_id nullable
  action_id
  notification_target_id
  delivery_kind        opened | repeat | escalated | resolved | test | security
  idempotency_key
  status               pending | sending | retry_wait | delivered | failed | cancelled | suppressed
  scheduled_at
  first_attempt_at nullable
  delivered_at nullable
  failed_at nullable
  attempt_count
  last_error_code
  last_error_message
  rendered_subject nullable
  rendered_body_digest
  correlation_id
  created_at
  updated_at
```

```text
AlertDeliveryAttempt
  id
  alert_delivery_id
  attempt_number
  started_at
  finished_at
  outcome
  provider_status
  error_code
  sanitized_error
  provider_message_id nullable
  next_retry_at nullable
```

Full rendered-body retention is a privacy and diagnostics setting. The default may retain only digest plus safe metadata instead of sensitive message content.

## Delivery and idempotency semantics

Worker processing is at-least-once with a stable idempotency_key.

zero-nvr prevents duplicate local jobs where possible, but it does not promise exactly-once external delivery when a provider or network cannot guarantee it.

Webhook consumers receive the delivery ID/idempotency key so they can deduplicate.

## Retry policy

Classify failures as:

```text
transient
permanent
rate_limited
configuration
```

Retry uses persisted backoff plus jitter and maximum attempt/age bounds. Provider retry hints are honored when safe. Configuration failures mark the target unhealthy instead of hammering indefinitely. Failed deliveries can be retried manually after repair.

## Notification backend health

States:

```text
unknown
healthy
degraded
unhealthy
disabled
```

Health includes configuration validity, latest test/result, recent failure rate, queue backlog, and last successful delivery.

One failing target never blocks another target.


## Test and preview

First-production-release UI includes:

- rule preview against selected historical/sample signals;
- target test message;
- template preview with safe sample data.

Rule preview shows match/no-match, group key, severity, quiet/silence result, and action/escalation plan without sending a real notification.

Externally delivered tests are audited.

## Alert Center UI

Alert Center includes:

- active/unacknowledged incidents;
- active/acknowledged incidents;
- resolved history;
- severity/camera/group/rule/source filters;
- search;
- bulk acknowledgement where authorized;
- incident detail with source events;
- notification delivery and per-attempt history;
- retry failed delivery;
- authenticated deep link to event/playback time.

UI separately displays:

```text
incident active/resolved
acknowledged/unacknowledged
notification delivered/failed/suppressed
```

A failed email never makes the incident disappear.

## Permissions

Initial permissions:

```text
alert.view
alert.acknowledge
alert.manage
notification.view
notification.manage
```

Semantics:

- alert.view: view incidents within camera scope;
- alert.acknowledge: acknowledge or manually resolve allowed incidents within camera scope;
- alert.manage: configure rules, escalation policies, and silences within authorized scope;
- notification.view: view target health/delivery history without secrets;
- notification.manage: configure targets/templates/recipient groups and send tests.

System-wide health/security rule management additionally requires the relevant system authorization.

## Audit

Audit at minimum:

```text
alert.rule_created
alert.rule_updated
alert.rule_disabled
alert.incident_acknowledged
alert.incident_resolved_manually
alert.silence_created
alert.silence_updated
alert.silence_removed
alert.delivery_retried
notification.target_created
notification.target_updated
notification.target_disabled
notification.target_tested
notification.template_updated
notification.recipient_group_updated
```

Automatic worker attempts belong in delivery history and operational logs, not one AuditEvent per retry.

## Interaction with recording

```text
DetectionEvent
   ├─ RecordingManager
   └─ AlertEvaluator
```

Alerting never owns recording lifecycle.

Therefore:

- disabling an AlertRule does not disable event recording;
- muting notifications does not disable event recording;
- SMTP/provider outage does not stop recording;
- acknowledging an incident does not stop RecordingIntent;
- resolving/deleting an alert does not delete DetectionEvent or media.

## Interaction with retention

AlertIncident alone does not lock footage forever.

Default media retention remains governed by Spec 0005 and RecordingPolicy. Any rule action that explicitly extends/locks media must use supported RetentionClaim behavior and authorization.

## Security and privacy

- channel credentials use SecretStore;
- reset/auth secrets follow Specs 0011/0012/0013;
- logs and errors are sanitized;
- webhook authentication headers are not exposed through normal APIs;
- templates cannot access secrets;
- permanent public playback links are forbidden;
- camera credentials never enter notifications;
- recipient/media configuration is privileged because alerts may contain sensitive images.

## Recovery / restart

After restart:

- pending deliveries resume;
- retry_wait schedules resume;
- escalation timers reconstruct;
- expired silences stop applying;
- active incidents remain based on source/rule lifecycle;
- in-flight delivery follows idempotency rules before retry;
- source DetectionEvents are not recreated merely to recover alert state.

## Acceptance tests

1. repeated motion burst:
   - all DetectionEvents persist;
   - compatible triggers group into one incident where configured;
   - cooldown prevents email floods;

2. stateful event:
   - START opens incident;
   - END resolves source-mode incident;
   - configured recovery notice sends once;

3. camera offline/recovered:
   - incident lifecycle follows health;
   - reconnect/recording remains independent;

4. escalation:
   - initial delivery occurs;
   - unacknowledged incident advances escalation steps;
   - configured acknowledgement cancels future steps;

5. silence:
   - event/incident persists;
   - outbound delivery is explicitly suppressed;
   - recording is unaffected;

6. SMTP outage:
   - durable retry occurs;
   - target becomes unhealthy;
   - other channels continue;
   - recording continues;

7. restart:
   - pending retry and escalation state recover without duplicate incident creation;

8. webhook timeout after possible remote acceptance:
   - local job remains idempotency-keyed;
   - external duplicate possibility is not falsely hidden;

9. snapshot failure:
   - optional snapshot failure does not prevent text delivery;

10. authorization:
   - scoped user cannot view/acknowledge hidden-camera incidents;
   - notification secrets remain inaccessible;

11. quiet schedule and DST:
   - schedule follows Spec 0009 timezone behavior;

12. notification storm:
   - deliveries suppress/defer explicitly;
   - source events/incidents remain intact.

## Invariants

1. DetectionEvent/system health remains authoritative regardless of AlertRule state.
2. AlertIncident and AlertDelivery are separate from source events and recording lifecycle.
3. Notification failure never blocks recording/event persistence.
4. Cooldown/grouping/silence never delete or falsify DetectionEvents.
5. Incident lifecycle and acknowledgement are independent.
6. Acknowledgement does not imply source recovery and does not stop recording.
7. Rule schedules and silences use explicit timezone semantics.
8. Escalation/retry schedules are persistent and recoverable.
9. Per-attempt diagnostics live in AlertDeliveryAttempt.
10. Internal delivery is idempotency-keyed; exactly-once external delivery is not falsely guaranteed.
11. Notification targets are independently healthy; one failure does not block another.
12. Channel secrets use SecretStore and never appear in normal APIs/logs/audit.
13. Deep links are authenticated; permanent public playback URLs are forbidden.
14. Human alert actions are permission- and camera-scope controlled.
15. Alert configuration changes and human incident actions are audited.
16. First production release includes SMTP, Apprise, webhook, Home Assistant, and MQTT notification routing.
17. Non-obvious grouping/cooldown/escalation/retry behavior requires comments per Development Guidelines.


## Detection fusion reference

AlertRule consumes canonical DetectionEvent transitions from [Spec 0021](0021-detection-providers-ai-events-and-fusion.md).

Rules may filter by event_type, object_class/subclass, provider, zone, confidence, and fusion group. EventFusionGroup may be used as a grouping/deduplication hint so the same physical occurrence reported by several providers does not necessarily create several human notifications.

Fusion never deletes/suppresses the underlying DetectionEvents and does not change RecordingManager ownership.
