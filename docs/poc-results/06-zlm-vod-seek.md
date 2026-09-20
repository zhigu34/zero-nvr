# POC-06 — ZLM VOD Seek

Result: **PASS**

## Purpose

Validate the PlaybackResolver primitive:

~~~text
wall-clock T
-> canonical RecordingSegment
-> offset = T - segment.started_at
-> ZLM VOD seek
-> decoded frame in expected media neighborhood
~~~

## Harness

~~~text
poc/zlm-recording/scripts/run-timeline-playback.sh
~~~

POC-05 and POC-06 share the same real fMP4-recorded segment set.

## Tested versions

~~~text
GitHub Actions run: 35490737812
job: POC 05
ZLMediaKit master commit: b794772
managed recording mode: fMP4
~~~

## Evidence

A finalized ZLM segment with about 10 seconds of media was copied unchanged into the ZLM VOD test path.

Three seek positions were checked against frame hashes from the same local media neighborhood:

~~~text
offset 0.8s:
  decoded = PASS
  matched expected local neighborhood = true

offset 5.0s:
  decoded = PASS
  matched expected local neighborhood = true

offset 8.5s:
  decoded = PASS
  matched expected local neighborhood = true
~~~

The deliberate source-loss Gap midpoint used the same wall-clock resolver and returned an explicit Gap with exact previous/next playable boundaries instead of being coerced into a segment seek.

An Event marker in a playable range resolved to the expected segment and approximately 6.076s relative offset.

## Primary artifact

~~~text
GitHub Actions run: 35490737812
artifact: poc-05-evidence
artifact id: 10599201935
runtime/timeline-playback-evidence.json
~~~

## Known limitations

The automated client is FFmpeg against ZLM RTSP MP4/fMP4 VOD. It validates the server-side PlaybackResolver/VOD seek primitive, not every browser UI/player implementation.

Seek is keyframe/container bounded rather than claimed sample-exact; the acceptance test matches a local frame neighborhood for that reason.

Frontend player compatibility/seam behavior remains normal implementation integration testing, not a reason to reimplement VOD.

## Architecture impact

**Accepted:** historical playback can resolve wall-clock time to RecordingSegment + media offset and delegate file playback/seek to ZLMediaKit VOD.

Gap handling stays in zero-nvr's PlaybackResolver/Timeline projection; no custom playback engine or range downloader is required.
