# POC-06 — ZLM VOD Seek

Result: **PASS**

## Purpose

Validate the V1 historical playback resolver path:

~~~text
wall-clock T
-> normalized RecordingSegment coverage
-> offset = T - segment.start_at
-> ZLM MP4/fMP4 VOD
-> seek/decode near requested media position
~~~

## Harness

~~~text
poc/zlm-recording/scripts/run-timeline-playback.sh
~~~

POC-05 and POC-06 share GitHub Actions run `35490899825`, job `POC 05`.

## Tested versions

~~~text
GitHub Actions run: 35490899825
job: POC 05

ZLMediaKit:
  branch: master
  commit: b794772
  buildTime: 2026-09-20T02:21:00

Docker Engine: 28.0.4
Docker Compose: v2.38.2
runner: Ubuntu 24.04.5 / linux amd64
~~~ 

## Test method

A real finalized ZLM recording segment was copied unchanged into ZLM's VOD namespace.

Sample:

~~~text
container: mov/mp4
duration: 10.000 s
size: 1,902,878 bytes
~~~

For each requested media offset:

1. decode a local file neighborhood around the target and collect frame MD5 values;
2. seek through ZLM RTSP MP4 VOD;
3. decode the first returned frame;
4. require that the returned frame hash exists in the expected local target neighborhood.

This verifies actual decoded content rather than merely accepting a successful RTSP/HTTP response.

## Evidence

All three required seek positions passed:

~~~text
near beginning:
  requested offset = 0.8 s
  matched local frame neighborhood = true

middle:
  requested offset = 5.0 s
  matched local frame neighborhood = true

near end:
  requested offset = 8.5 s
  matched local frame neighborhood = true
~~~

Representative hashes:

~~~text
0.8 s -> e79abc027a4e562164f05f241209fb4f
5.0 s -> 90af8503863a5cbe520a36f54e464a37
8.5 s -> a4d78dc494193fd29d06e350aa524f83
~~~

Local comparison neighborhoods contained 74–75 decoded frame hashes.

## Resolver implication

The backend may resolve a wall-clock instant to:

~~~text
segment_id
normalized segment_start_at
offset_ms
short-lived ZLM VOD descriptor
~~~

The frontend does not need to know:

- local-vs-remote RecordingLocation selection;
- physical recording directories;
- rclone restore behavior;
- ZLM admin credentials.

POC-07 separately validates remote RecordingLocation restore into the same local-ZLM VOD path.

## Artifact

~~~text
GitHub Actions run: 35490899825
artifact: poc-05-evidence
artifact id: 10598254986
SHA256: 961320410b2389a21f72d9bf5431c84badf3ee1ed769da0b69238b5f46725cda
~~~ 

Primary file:

~~~text
runtime/timeline-playback-evidence.json
~~~

## Known limitations

- This POC validates one finalized H.264 MP4/fMP4-compatible ZLM VOD sample. Browser/player compatibility for every codec/profile remains an integration concern handled by the live/playback player adapter.
- Seek lands at decoder/keyframe-valid media near the requested offset; the product should not promise arbitrary frame-exact seek for inter-frame codecs.
- Exact seek latency was not used as a freeze gate; correctness of returned media position was.

## Architecture impact

**Accepted.**

ZLM VOD remains the V1 historical playback engine.

zero-nvr owns:

- wall-clock -> normalized RecordingSegment mapping;
- offset calculation;
- RecordingLocation selection;
- remote restore/cache orchestration;
- authorization and short-lived playback descriptors.

zero-nvr does **not** build a separate video playback engine.
