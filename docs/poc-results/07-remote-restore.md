# POC-07 — Remote Restore Playback

Result: **PASS**

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
13. Record first-frame wall time for segment 1 through ZLM RTSP VOD.
14. Compute a deterministic cache byte limit that can hold one restored segment but not both.
15. Enforce the cache limit by oldest-entry eviction and record bytes/files before and after.
16. Verify a separate canonical local RecordingSegment file still exists.
17. Kill the WebDAV remote.
18. Require remote rclone access to fail.
19. Require the local ZLM recorder to continue finalizing new segments.

## Required checks

- actual rclone version is recorded;
- interrupted restore never publishes a final READY cache file;
- retry produces a valid media file;
- ZLM VOD decodes restored media;
- next-segment prefetch can run while current restored media is being played;
- restore retry-to-READY time and first-frame wall time are recorded;
- cache eviction is triggered by an explicit byte limit rather than a manual one-off delete;
- cache bytes/files before and after eviction are recorded;
- the configured playback-cache byte limit is actually exceeded before eviction so the bound is exercised;
- byte-based eviction returns READY cache bytes to or below the configured limit;
- protected current/next cache media is not evicted;
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

First passing runtime execution:

~~~text
GitHub Actions run: 35489849518
job: POC 07
runner: Ubuntu 24.04.5 / linux amd64
Docker Engine: 28.0.4
Docker Compose: v2.38.2
rclone: v1.75.1
ZLMediaKit image: zlmediakit/zlmediakit:master
~~~

The first POC-07 evidence did not yet serialize ZLM's `/index/api/version` result into its own JSON. The harness has been updated so future runs capture the exact ZLM commit/build time as well. Other jobs in the same matrix pulled current master commit `b794772`, but this result does not rely on cross-job inference for its PASS decision.

## Test environment

GitHub-hosted Ubuntu 24.04.5 runner:

~~~text
kernel: 6.17.0-1022-azure
architecture: x86_64
host-visible RAM: ~15 GiB
Docker Engine: 28.0.4
Docker Compose: v2.38.2
~~~

Remote endpoint was the deterministic POC WebDAV service consumed only through rclone. No FUSE mount was used.

## Evidence

Runtime result:

~~~text
result = PASS

interrupted restore:
  final READY path published after interruption = false
  retry_to_ready_seconds ≈ 0.066
  interrupted attempt + retry wall time ≈ 1.644 s

restored segment 1:
  size = 1,555,980 bytes
  media duration = 7.997 s

prefetched segment 2:
  size = 1,932,263 bytes
  media duration = 10.000 s

ZLM RTSP VOD:
  first decoded frame after READY ≈ 2.093 s
  current segment decoded while next segment prefetch ran = PASS

bounded cache:
  bytes before eviction = 3,488,243
  enforced limit = 1,997,799
  evicted = remote-1.mp4
  bytes after eviction = 1,932,263
  canonical local guard recording still exists = true

remote outage:
  rclone remote command failed as expected
  local segment count: 4 -> 5
  local ZLM recorder active = true
~~~

Primary artifact:

~~~text
GitHub Actions artifact:
  poc-07-evidence
  run 35489849518
~~~

The JSON artifact path produced by the harness is:

~~~text
poc/zlm-recording/runtime/remote-restore-evidence.json
~~~

## Known limitations

- This validates rclone over WebDAV, not an actual OpenList process.
- OpenList remains an optional protocol gateway; a later smoke test should point the same rclone WebDAV configuration at a real OpenList instance.
- The first-frame number is a GitHub-runner operational measurement, not a universal WAN/cloud SLA.
- A real Internet/cloud backend will have different throughput and startup latency.

## Architecture impact

**V1 remote playback baseline is accepted:**

~~~text
remote RecordingLocation
-> rclone restore/copyto
-> bounded local playback cache
-> verify
-> atomic READY publish
-> ZLMediaKit VOD
~~~

No FUSE/rclone mount is required for V1.

Remote archive/playback failure remains isolated from healthy local recording.

OpenList stays outside the zero-nvr storage-transfer implementation: when used, it supplies WebDAV to rclone rather than requiring a new zero-nvr cloud-drive adapter.
