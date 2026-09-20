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

The harness creates two fMP4 cases.

### Normal finalize

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

### Abnormal termination

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
poc/zlm-recording/runtime/fmp4-evidence.json
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
3. ffprobe inspects the interrupted file;
4. FFmpeg decodes the interrupted file;
5. FFmpeg stream-copy/remux succeeds;
6. ZLM RTSP VOD can open the surviving interrupted content after restart;
7. no separate repair daemon is required.

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
