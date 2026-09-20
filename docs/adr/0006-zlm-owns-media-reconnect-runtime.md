# ADR 0006 — ZLMediaKit Owns Media Pull and Reconnect Runtime

Status: **accepted**

## Context

An earlier roadmap/spec introduced a zero-nvr per-camera transport state machine with packet/media starvation detection, reconnect backoff/jitter, retry scheduling, and explicit STREAMING/DEGRADED/RECONNECTING/OFFLINE media states.

ZLMediaKit already owns camera pulling, protocol/runtime media state, reconnect behavior, stream registration, and recorder execution.

Duplicating that logic would create two media runtimes that can disagree.

## Decision

ZLMediaKit is the media-runtime authority for:

- source pull;
- RTSP/protocol reconnect;
- media stream registration;
- codec/track runtime;
- recorder execution.

zero-nvr uses a thin MediaPlane/RuntimeReconciler to:

- map Camera/StreamProfile to ZLM identifiers;
- apply desired configuration through supported ZLM APIs;
- observe ZLM APIs/hooks;
- project product health;
- persist meaningful health transitions;
- reconcile state/catalog after restart or missed hooks.

zero-nvr does not implement a competing packet monitor, RTSP reconnect scheduler, or media transport state machine.

Product-facing ONLINE/DEGRADED/OFFLINE states are health projections, not an independent transport engine.

## Consequences

Positive:

- one clear media owner;
- less duplicate networking code;
- fewer race conditions between reconnect engines;
- API/database outages are less likely to disrupt existing ZLM recording;
- testing focuses on adapter/reconciliation behavior rather than reimplementing RTSP.

Trade-off:

- zero-nvr relies on documented/tested ZLM reconnect/runtime behavior;
- ZLM-version compatibility must be monitored by the adapter.

If a ZLM limitation is discovered, prefer configuration, upstream contribution, or a narrowly scoped adapter workaround before building a second media runtime.
