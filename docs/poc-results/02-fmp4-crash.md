# POC-02 — fMP4 Abnormal Termination Recovery

Result: **NOT RUN**

## Purpose

Determine whether ZLMediaKit fMP4 recording should become the default recording container by measuring real abnormal-termination recoverability without breaking normal playback/export behavior.

Candidate configuration:

~~~text
[record]
enableFmp4=1
~~~

## Harness

~~~text
poc/zlm-recording/scripts/run-fmp4-crash.sh
~~~

No runtime evidence has been produced by this conversation environment yet.

## Test design

The harness now runs an **A/B abnormal-termination comparison**.

### A — ordinary MP4 baseline

~~~text
POC_ZLM_ENABLE_FMP4=0
MediaMTX cam_main
-> ZLM ordinary MP4 recorder
-> hidden in-progress MP4 grows
-> docker SIGKILL ZLM
~~~

The unchanged interrupted bytes are tested with:

- ffprobe;
- FFmpeg decode;
- FFmpeg stream-copy/remux;
- ZLM HTTP MP4 after restart;
- ZLM RTSP VOD after restart.

Failures are recorded as baseline evidence rather than aborting the comparison immediately.

### B — fMP4 candidate

The environment is recreated with:

~~~text
POC_ZLM_ENABLE_FMP4=1
~~~

Then the same source / growth / SIGKILL / recovery checks are executed.

The fMP4 candidate also includes a normally finalized segment check before the crash case.

### fMP4 normal finalize

~~~text
MediaMTX cam_main
-> ZLM fmp4-normal proxy
-> ZLM normal fMP4 segment finalize
-> on_record_mp4
~~~

Required checks:

- finalized file opens with ffprobe;
- finalized file is readable through ZLM HTTP MP4;
- ZLM RTSP MP4 VOD can demux/play it.

### fMP4 abnormal termination

~~~text
MediaMTX cam_main
-> ZLM fmp4-crash proxy
-> hidden in-progress .mp4 grows for several seconds
-> docker SIGKILL ZLM
-> file remains on disk
~~~

Before restarting ZLM:

- the interrupted hidden file must still exist;
- ffprobe must inspect it;
- FFmpeg must decode valid surviving coverage;
- FFmpeg stream-copy/remux must succeed;
- the remuxed result must be inspectable.

After ZLM restart:

- the unchanged interrupted fMP4 bytes are copied into the POC VOD directory under a normal filename;
- ZLM HTTP MP4 path must be readable;
- ZLM RTSP MP4 VOD must demux/play the interrupted file.

## Required evidence before PASS

~~~text
poc/zlm-recording/runtime/mp4-baseline-state.json
poc/zlm-recording/runtime/mp4-baseline-evidence.json
poc/zlm-recording/runtime/fmp4-evidence.json
poc/zlm-recording/runtime/mp4-vs-fmp4-comparison.json
poc/zlm-recording/runtime/fmp4-precrash.json
poc/zlm-recording/runtime/fmp4-crash-inspection.json
poc/zlm-recording/runtime/fmp4-docker-compose.log
poc/zlm-recording/runtime/fmp4-zlm-container-inspect.json
~~~

The result must include the actual ZLM version/commit returned at runtime.

## Pass rule

PASS requires **all** of the following:

1. normal finalized fMP4 remains usable through the intended ZLM playback path;
2. an in-progress fMP4 survives SIGKILL with non-trivial readable media;
3. ffprobe inspects the interrupted fMP4;
4. FFmpeg decodes the interrupted fMP4;
5. FFmpeg stream-copy/remux succeeds;
6. ZLM HTTP MP4 and RTSP VOD can consume the surviving interrupted fMP4 after restart;
7. no separate repair daemon is required;
8. the same ordinary-MP4 SIGKILL baseline does **not** pass every equivalent recovery check.

If ordinary MP4 passes all of the same checks on the tested ZLM/filesystem, this POC returns FAIL for the claim “fMP4 is materially better,” even if fMP4 itself works.

If fMP4 improves crash recovery but causes unacceptable normal VOD/browser/export regression, the result is not an unconditional PASS.

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Known limitations

The POC copies the **unchanged interrupted file bytes** from ZLM's hidden in-progress filename to `www/record/interrupted.mp4` after the crash so ZLM's normal MP4 VOD URL can address it. This changes only the filename/location used for the VOD test; it does not repair or rewrite the interrupted media.

Browser-specific codec/container compatibility is also covered by the later live/playback validation and must remain acceptable before fMP4 becomes the default.

## Architecture impact

Pending execution.

Do not change the project baseline from “fMP4 preferred candidate” to “fMP4 default” until this POC passes with recorded evidence.
