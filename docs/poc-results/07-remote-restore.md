# POC-07 — Remote Restore Playback

Result: **NOT RUN**

## Purpose

Validate the V1 remote playback path without FUSE:

~~~text
remote RecordingLocation
-> rclone copyto
-> bounded local playback cache
-> verify
-> atomic READY publish
-> ZLMediaKit VOD
-> player
~~~

and prove that remote/archive failure cannot interrupt healthy local recording.

## Harness

~~~text
poc/zlm-recording/scripts/run-remote-restore.sh
~~~

The test uses a POC-only rclone WebDAV server as the remote endpoint.

This is intentional:

- WebDAV is directly supported by rclone;
- OpenList exposes special cloud drives through WebDAV;
- zero-nvr still interacts with the remote only through rclone.

No FUSE mount is used.

## Test flow

1. Record at least three real ZLM segments.
2. Copy two segment samples to the WebDAV remote through rclone.
3. Remove temporary upload staging copies.
4. Start restoring remote segment 1 into `*.partial` with a bandwidth limit.
5. Terminate that rclone transfer before completion.
6. Require that the final cache filename was **not** published.
7. Retry the restore to the staging path.
8. ffprobe the completed staging object.
9. Atomically rename it to the READY cache filename.
10. Start prefetching remote segment 2.
11. While prefetch runs, play segment 1 through ZLM RTSP VOD.
12. Complete and publish segment 2.
13. Evict segment 1 from playback cache.
14. Verify a separate canonical local RecordingSegment file still exists.
15. Kill the WebDAV remote.
16. Require remote rclone access to fail.
17. Require the local ZLM recorder to continue finalizing new segments.

## Required checks

- actual rclone version is recorded;
- interrupted restore never publishes a final READY cache file;
- retry produces a valid media file;
- ZLM VOD decodes restored media;
- next-segment prefetch can run while current restored media is being played;
- cache eviction stays inside playback cache;
- canonical local recording media is untouched by cache eviction;
- remote outage is observable as remote failure;
- local recording continues during remote outage;
- no FUSE mount is needed.

## OpenList relevance

The POC remote uses rclone's own WebDAV server rather than OpenList itself.

A later integration smoke test should point the same rclone WebDAV backend configuration at OpenList. If OpenList behaves as a normal WebDAV endpoint, no new zero-nvr storage adapter is required.

## Expected evidence

~~~text
poc/zlm-recording/runtime/remote-restore-state.json
poc/zlm-recording/runtime/remote-restore-evidence.json
poc/zlm-recording/runtime/remote-docker-compose.log
poc/zlm-recording/runtime/remote/
poc/zlm-recording/runtime/playback-cache/
~~~

## Tested versions

Pending execution.

## Test environment

Pending execution.

## Evidence

Pending execution.

## Architecture impact

Pending execution.
