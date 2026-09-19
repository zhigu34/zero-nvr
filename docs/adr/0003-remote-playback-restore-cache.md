# ADR-0003 — V1 Remote Playback Uses Restore-to-Cache

Status: **Accepted**

## Decision

For remote-only recording media, V1 restores required media through rclone into a bounded local playback cache and then serves it through ZLMediaKit VOD.

```text
Remote RecordingLocation
-> rclone copyto/restore
-> local playback cache
-> ZLM VOD
-> browser
```

FUSE/rclone mount is not a V1 requirement.

## Rationale

A mandatory FUSE path adds host/container privilege, mount propagation, rootless-Docker, NAS-platform, and portability complexity. Restore-to-cache is slower on first access but much easier to deploy reliably with the project's preferred `deploy.sh` workflow.

## Consequences

- cache size/age must be bounded;
- next-segment prefetch may reduce playback stalls;
- cache is disposable and excluded from disaster backup;
- rclone VFS mount or serve-http streaming may be added later as an optimization.
