# ADR-0002 — ZLMediaKit Owns Normal Recording

Status: **Accepted**

## Decision

ZLMediaKit is the normal continuous/scheduled recording authority for zero-nvr.

Normal path:

```text
Camera -> ZLMediaKit -> ZLM MP4 Recorder -> local recording storage
```

The on_record_mp4 hook is the normal catalog-indexing path. ZLM file listing/reconciliation is the recovery path. ffprobe is a fallback/recovery tool, not the normal indexing loop.

FFmpeg is not a permanent per-camera recorder. It is an on-demand derived-media tool for export, remux/transcode, clip composition, frame extraction, inspection, and repair.

## Rationale

Running ZLM as ingest/media bus and then creating a second permanent FFmpeg recorder duplicates a mature ZLM capability, increases processes and failure modes, and conflicts with the project's reuse-first principle.

## Consequences

Existing design text that names FfmpegRecorderBackend as the normal recorder is superseded by this ADR.

EVENT_ONLY pre-roll remains a separate POC because the exact ZLM-native buffering mechanism still requires validation.
