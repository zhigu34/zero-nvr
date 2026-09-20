# POC-06 — ZLM VOD Seek

Result: **NOT RUN**

## Purpose

Validate the historical playback resolver assumption:

~~~text
wall-clock T
-> RecordingSegment
-> offset = T - segment.start_at
-> ZLM MP4 VOD seek
-> playable decoded frame near requested media position
~~~

## Harness

~~~text
poc/zlm-recording/scripts/run-timeline-playback.sh
~~~

POC-05 and POC-06 share one real recorded segment set.

## Seek verification

A finalized ZLM segment is copied unchanged into the POC VOD directory.

For beginning/middle/near-end offsets:

1. decode a local-MP4 frame neighborhood around the requested offset and collect frame hashes;
2. open the same bytes through ZLM RTSP MP4 VOD with an input seek;
3. hash the first decoded RTSP frame;
4. require it to match a frame from the expected local neighborhood.

The neighborhood accounts for practical keyframe/container seek tolerance without treating arbitrary inaccurate seeks as success.

## Required checks

- the VOD sample is a real finalized ZLM RecordingSegment;
- at least three distinct offsets are tested;
- each RTSP seek yields a decodable frame;
- each returned frame belongs to the expected local media neighborhood;
- beginning/middle/end seeks remain stable after the source-outage/recovery sequence;
- physical file path selection remains backend responsibility rather than frontend logic.

Gap timestamps are handled by the timeline projection and must not be converted into an arbitrary playable seek.

## Expected evidence

~~~text
poc/zlm-recording/runtime/timeline-playback-evidence.json
~~~

Fields:

~~~text
vod.source_segment_id
vod.probe
vod.seek_results[]
~~~

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Known limitations

The first automated seek check uses ZLM RTSP MP4 VOD plus FFmpeg as the test client.

Real browser player compatibility/seam behavior remains a separate frontend integration test; this POC only validates the server-side VOD/seek primitive required by PlaybackResolver.

## Architecture impact

Pending execution.
