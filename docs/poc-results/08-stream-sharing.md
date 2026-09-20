# POC-08 — ZLM Stream Sharing / Camera Connection Count

Result: **PASS**

## Purpose

Prove the intended camera-facing topology:

~~~text
camera main -> ZLM
camera sub  -> ZLM

ZLM -> recorder / live / optional downstream consumers
~~~

without downstream consumers multiplying source-camera RTSP sessions.

## Harness

~~~text
poc/zlm-recording/scripts/run.sh
~~~

MediaMTX supplies deterministic main/sub RTSP paths and exposes source reader-count metrics.

## Tested versions

~~~text
GitHub Actions run: 35490899825
job: POC 01
ZLMediaKit master commit: b794772
MediaMTX: 1.21.0-ffmpeg
managed recording mode: fMP4
~~~

## Evidence

After ZLM attached to both original source profiles:

~~~text
upstream_readers_before:
  cam_main = 1
  cam_sub  = 1
~~~

The harness then opened two additional FFmpeg readers against:

~~~text
rtsp://zlm:554/poc/cam-main
~~~

while ZLM recording remained active.

Source-facing result:

~~~text
upstream_readers_with_two_zlm_viewers:
  cam_main = 1
  cam_sub  = 1
~~~

The downstream consumers therefore attached to ZLM and did not create additional source pulls.

## Primary artifact

~~~text
GitHub Actions run: 35490899825
artifact: poc-01-evidence
artifact id: 10598049983
artifact SHA256: eaea47b3a2a26cb3ddebec1a6712c01d8df5c39f344feabb726035fff1e3f95a
runtime/evidence.json
~~~

## Known limitations

The Core test uses FFmpeg readers as generic downstream consumers. That is sufficient for the Core invariant: consumer count must not equal additional source-camera RTSP sessions.

Managed Frigate remains an optional feature-specific acceptance test: when AI is enabled, Frigate `AI_DETECT` input must use the ZLM internal stream and source-facing reader count must remain unchanged.

## Architecture impact

**Accepted:** ZLMediaKit is the camera-facing media bus. Main/sub streams are pulled once by ZLM and shared to recording/live/other consumers.
