# ADR 0009 — fMP4 Is the Default ZLM Recording Container

Status: **accepted**

## Context

ZLMediaKit supports ordinary MP4 and fragmented MP4 recording.

POC-02 executed the same deterministic H.264 source/write/SIGKILL recovery scenario with both modes on:

~~~text
ZLMediaKit master commit b794772
buildTime 2026-09-20T02:21:00
GitHub Actions run 35490249085 / POC 02
~~~

Ordinary in-progress MP4 survived as bytes but failed ffprobe, decode, remux, HTTP playback, and RTSP VOD because the moov metadata was never finalized.

The interrupted fMP4 remained inspectable, decodable, stream-copy/remuxable, and playable through ZLM HTTP/RTSP VOD after restart. Normally finalized fMP4 also passed the intended playback path.

## Decision

V1 sets:

~~~text
[record]
enableFmp4=1
~~~

for zero-nvr-managed ZLM recording unless a future measured compatibility exception explicitly overrides it.

fMP4 does **not** change recording ownership:

~~~text
Camera -> ZLMediaKit -> fMP4 files
                     -> on_record_mp4
                     -> RecordingSegment + RecordingLocation
~~~

FFmpeg remains a derived-media/recovery utility, not the normal recorder.

## Abnormal residue handling

ZLM writes the currently open recording as a hidden/in-progress file and publishes the normal filename only after clean finalize.

After a crash/restart, reconciliation may encounter an old hidden fMP4 that is no longer owned by an active recorder.

Safe recovery flow:

~~~text
prove file is stale / no active writer
-> ffprobe/media validation
-> if usable, publish through a recovery filename/path
-> create RecordingSegment + RecordingLocation
   completion_reason = abnormal_recovery
-> if unreadable/ambiguous, preserve or quarantine and alert
~~~

Never rename/catalog a hidden file that may still be actively written.

No permanent repair daemon is required; this is part of normal startup/periodic reconciliation.

## Playback

Canonical historical playback still resolves through PlaybackResolver and ZLM VOD descriptors.

Direct browser-file compatibility is not the source of truth for the recorder-container choice. If a browser/player needs a different delivery form, use the existing ZLM delivery/player compatibility layer rather than changing normal recording authority.

## Consequences

Positive:

- materially better interrupted-file recoverability in the measured SIGKILL case;
- no extra recording service;
- same normal ZLM hook/catalog path;
- supports EVENT_ONLY rolling tmpfs with the same container baseline;
- explicit crash-residue recovery instead of assuming open MP4 is lost.

Trade-offs:

- exact behavior still depends on the tested ZLM/container implementation;
- future ZLM/browser regressions require compatibility testing during upgrades;
- hidden crash residues need stale-writer proof before recovery.

## Evidence

See [POC-02 — fMP4 Abnormal Termination Recovery](../poc-results/02-fmp4-crash.md).

## Invariants

1. ZLMediaKit remains the normal recorder.
2. Managed V1 recording defaults to fMP4.
3. FFmpeg is not introduced as a permanent recorder to gain crash recovery.
4. Hidden/in-progress files are never treated as finalized while an active writer may own them.
5. Recoverable stale fMP4 media is preserved/cataloged rather than silently discarded.
