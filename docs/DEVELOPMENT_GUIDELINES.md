# Development Guidelines

Status: **required**

This document defines implementation constraints for zero-nvr. They apply to backend, frontend, adapters, workers, runtime components, migrations, and operational scripts unless a more specific project rule overrides them.

## 1. Comments are part of the implementation

zero-nvr code must include complete, useful comments where behavior is not self-evident.

The goal is not to comment every line. Comments must preserve the **reasoning and business constraints** that would otherwise be lost when reading the code later.

Comments are required for:

- state machines and lifecycle transitions;
- recording/event timing rules;
- concurrency, locking, cancellation, retries, idempotency, and deduplication;
- non-obvious boundary conditions and failure recovery;
- protocol/vendor quirks and compatibility workarounds;
- calculations involving timestamps, offsets, buffers, retention, or storage lifecycle;
- security-sensitive behavior;
- code that intentionally differs from a seemingly simpler implementation;
- adapters where external semantics are normalized into zero-nvr domain semantics.

For example, RecordingManager code implementing event recording must explain why:

```text
ACTIVE events prevent event recording from stopping;
the final END starts post-roll;
a new event during post-roll cancels the pending stop;
instant events are zero-duration markers but still extend the recording window;
pre-roll/post-roll belong to recording policy rather than motion detection.
```

Local RTSP motion detection code must document:

```text
start/end hysteresis;
start/end hold timing;
why a fixed motion_record_duration is intentionally not used;
how repeated pulses or frame-level detections are collapsed into one logical event.
```

## 2. Comment what is not obvious

Prefer comments that explain **why**, invariants, assumptions, and edge cases.

Good:

```text
# Keep the existing session alive instead of restarting the recorder.
# A new event inside post-roll belongs to the same continuous recording window.
```

Avoid comments that merely restate syntax:

```text
# Increment i by one.
i += 1
```

## 3. Public contracts require documentation

Public/backend-facing interfaces, domain services, adapter contracts, configuration fields with non-obvious semantics, and reusable frontend composables/services should have concise documentation describing:

- purpose;
- inputs/outputs where not obvious from types;
- important side effects;
- lifecycle or error semantics;
- units for timing/size values.

## 4. State-machine implementation rule

When implementing a state machine, the code must include either:

- a nearby state-transition comment/table; or
- a direct reference to the relevant accepted spec.

Complex state transitions must be traceable back to an architecture/spec document.

## 5. TODO/FIXME rule

TODO/FIXME comments must explain the missing behavior or risk.

Avoid vague placeholders such as:

```text
TODO: fix this
```

Prefer:

```text
TODO: persist the pending post-roll deadline so recorder recovery after process restart
can reconstruct an event RecordingSession without truncating the final window.
```

## 6. Keep comments synchronized

A stale comment is a defect.

When behavior changes, update the adjacent comment and the corresponding accepted design/spec in the same change when applicable.

## 7. Tests complement comments

Comments explain intent; tests verify behavior.

Critical timing/state-machine rules should have tests covering normal flow and edge cases. A comment does not replace a test, and a test does not replace documentation of non-obvious business intent.
