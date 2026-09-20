# POC-08 — ZLM Stream Sharing / Camera Connection Count

Result: **NOT RUN**

## Purpose

Prove the intended camera-facing topology:

```text
main source -> ZLM
sub source  -> ZLM

ZLM -> recorder / live / optional downstream consumers
```

without each downstream consumer opening another RTSP connection to the source.

## Harness

```text
poc/zlm-recording/
```

MediaMTX supplies deterministic `cam_main` and `cam_sub` RTSP paths and exposes reader-count metrics.

## Required evidence before PASS

Before extra downstream consumers:

```text
MediaMTX cam_main readers = 1
MediaMTX cam_sub  readers = 1
```

Then start two additional readers against:

```text
rtsp://zlm:554/poc/cam-main
```

while ZLM remains attached to the original source.

Required result:

```text
MediaMTX cam_main readers remains 1
MediaMTX cam_sub  readers remains 1
```

This demonstrates that downstream consumers attach to ZLM rather than multiplying source-facing sessions.

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

Future runtime evidence is expected in:

```text
poc/zlm-recording/runtime/evidence.json

checks.upstream_readers_before
checks.upstream_readers_with_two_zlm_viewers
```

## Known limitations

The Core harness uses two FFmpeg readers as generic downstream consumers.

That is sufficient for the Core architecture gate because the measured invariant is:

~~~text
additional downstream readers
!= additional source-camera RTSP sessions
~~~

Frigate remains optional. If AI is enabled, Managed Frigate has a separate feature-specific smoke requirement: its AI_DETECT input must point at the ZLM internal stream and the source-facing camera reader count must remain unchanged.

This keeps a non-AI deployment from pulling/starting Frigate merely to satisfy the Core design freeze.

## Architecture impact

None yet. Do not mark the stream-sharing assumption frozen until runtime evidence exists.
