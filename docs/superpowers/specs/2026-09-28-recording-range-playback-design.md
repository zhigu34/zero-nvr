# Recording Range Playback Design

**Date:** 2026-09-28

## Context

Historical playback currently asks ZLMediaKit to expose a recording as a
live fragmented-MP4 stream. Production playback can display the requested
frame but then remains on that frame. The existing proof of concept only
verified that RTSP VOD could seek and decode a first frame; it did not prove
continuous browser playback through `.live.mp4`.

The camera-recorder reference serves completed browser-compatible recordings
as ordinary MP4 over same-origin HTTP Range requests. Browsers then own normal
file buffering and playback progression.

## Selected Design

- A playable local or restored recording resolves to a same-origin,
  permission-protected MP4 URL under `/api/v1/recordings/{id}/media`.
- The media route repeats `recording.view` and camera-scope authorization and
  resolves the current playable filesystem copy without exposing its path.
- The response is inline `video/mp4` and supports HTTP byte ranges.
- The descriptor keeps `segment_start_at` and `offset_ms`. On metadata load,
  the browser seeks once to `offset_ms / 1000`; ordinary playback then advances
  without further `currentTime` writes.
- Single-camera and tolerant multi-camera players use the same one-time seek
  rule. Multi-camera drift may still reload a descriptor, after which the new
  source receives one new initial seek.
- Remote-only recordings retain the existing restore-to-cache pending flow.

## Constraints

- Never expose filesystem paths or camera credentials.
- Media reads require both `recording.view` and effective camera scope.
- Missing or no-longer-playable media returns the existing product errors.
- Do not route completed MP4 playback through ZLMediaKit.
- Do not repeatedly write `currentTime` during normal playback.
- Preserve timeline, gap, remote restore, segment preloading, and synchronized
  playback behavior.

## Scope Boundary

This change fixes transport for browser-compatible completed MP4 recordings.
Codec compatibility transcoding is a separate path and is not added here.
