# ADR 0011 — Normalize ZLM Recording Time Within Proven Media Sessions

Status: **accepted**

## Context

zero-nvr needs a true wall-clock recording timeline.

ZLMediaKit remains recording authority, and `on_record_mp4` remains the normal finalized-media indexing signal. However POC-05 showed that current ZLM `start_time` cannot always be used directly as canonical media start time.

On the tested ZLM build, the first file in a continuous source/recorder session showed a raw boundary error of about one GOP:

~~~text
raw first boundary delta ≈ 2.042 s
~~~

The same behavior reappeared after source reconnect at about:

~~~text
≈ 1.041 s
~~~

This occurs because the file is created on receipt of early frames while the MP4 muxer may not retain leading non-keyframes before the first usable keyframe.

Blindly storing:

~~~text
started_at = hook.start_time
ended_at   = hook.start_time + hook.time_len
~~~

therefore creates a false Timeline gap even when the media session was continuous.

## Decision

The ZLM adapter owns recording-time normalization.

For segment N inside a **proven continuous ZLM media/recording session**, when the next segment boundary B is known:

~~~text
D = actual finalized media duration of segment N

ended_at(N)   = B
started_at(N) = B - D
~~~

`D` comes from ZLM finalized-media duration evidence such as `on_record_mp4.time_len`.

### Continuity session boundary

A source unregister/re-register or equivalent proven media-runtime interruption ends the continuity session.

Never use a post-reconnect segment boundary to normalize a pre-disconnect segment.

ZLM `on_stream_changed` is a valid source of runtime continuity evidence for the managed ZLM integration.

### Current tail segment

When no next segment boundary is known yet:

1. use a stronger explicit stop/source-loss boundary when available;
2. otherwise retain the raw Hook start + actual duration as a provisional/fallback coverage value;
3. refine the projection when stronger boundary evidence arrives.

Do not invent continuity merely to remove a visual gap.

### Raw evidence

Preserve the raw ZLM Hook/runtime evidence needed for diagnosis/reconciliation.

Canonical `RecordingSegment.started_at/ended_at` represent the accepted product projection of actual media coverage, not an unexamined copy of one vendor timestamp field.

### ffprobe

Do not ffprobe every successfully finalized normal segment merely to correct the ZLM startup/keyframe bias.

ffprobe remains a recovery/ambiguity fallback.

## Runtime evidence

POC-05 passing rerun:

~~~text
GitHub Actions run: 35490899825
job: POC 05

ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00
~~~

Same-session normalized boundary deltas:

~~~text
0.040 s
0.040 s
0.000 s
0.040 s
0.000 s
~~~

The deliberate source outage remained a real Gap:

~~~text
ZLM-observed source loss:
  ≈ 13.033 s

projected media Gap:
  ≈ 16.641 s
~~~

A real 0.400-second partial segment was preserved instead of being stretched to the configured segment target.

## Consequences

Positive:

- eliminates false GOP-sized gaps inside proven continuous sessions;
- keeps actual muxed duration authoritative;
- keeps ffprobe out of the normal hot path;
- preserves real source-loss gaps;
- keeps ZLM-specific quirks inside the ZLM adapter rather than generic Timeline code.

Trade-offs:

- the latest/tail segment can have provisional timing until another boundary is known;
- runtime media-state evidence must be observed/reconciled;
- a future ZLM version may improve timestamp semantics, so the adapter behavior remains version-testable.

## Invariants

1. Configured segment duration is never treated as actual duration.
2. Raw `on_record_mp4.start_time` is not blindly canonicalized.
3. Same-session normalization requires proven continuity.
4. Source unregister/reconnect always splits timing sessions.
5. No normalization crosses a source-loss boundary.
6. Real partial segments remain partial.
7. Gap is a Timeline projection; no Gap table is introduced.
8. Timing normalization belongs in the ZLM adapter/catalog ingestion boundary.
9. Normal successful indexing does not require per-segment ffprobe.
10. Material changes to this rule require regression coverage equivalent to POC-05.
