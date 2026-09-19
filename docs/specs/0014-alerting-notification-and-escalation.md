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

