# ZLMediaKit / Storage Design-Freeze POC Harness

This directory is a **disposable validation harness**, not production zero-nvr code.

It exercises POC-01 through POC-08 plus POC-10. POC-09 lives in `poc/sqlite-load/`.

## Test topology

~~~text
MediaMTX synthetic camera(s)
        ↓
    ZLMediaKit
        ↓
POC FastAPI + SQLite evidence service
        ↓
optional rclone/WebDAV remote for restore tests
~~~

MediaMTX and the WebDAV server exist only to make tests deterministic. They are not production zero-nvr dependencies.

## Prerequisites

- Docker Engine / compatible Docker Desktop;
- Docker Compose v2;
- network access to pull the selected test images.

## Configure

~~~bash
cd poc/zlm-recording
cp .env.example .env
~~~

Important defaults:

~~~text
ZLM_IMAGE=zlmediakit/zlmediakit:master
MEDIAMTX_IMAGE=bluenviron/mediamtx:1.21.0-ffmpeg
RCLONE_IMAGE=rclone/rclone:latest
~~~

The actual ZLM/rclone runtime versions are recorded in evidence where relevant.

## Run matrix

### POC-01 + POC-08

~~~bash
sh ./scripts/run.sh
~~~

Validates:

- continuous ZLM MP4 recording;
- FastAPI stop/restart while the ZLM recorder continues independently;
- recovery of finalized media produced during control-plane downtime;
- on_record_mp4 indexing;
- deliberate lost-hook reconciliation;
- no ffprobe in the normal hook path;
- ZLM as the only camera-facing reader while downstream viewers attach to ZLM.

### POC-02

~~~bash
sh ./scripts/run-fmp4-crash.sh
~~~

Validates fMP4 normal finalize and SIGKILL recovery with ffprobe, FFmpeg remux, HTTP MP4 and ZLM RTSP VOD.

### POC-03 + POC-04

~~~bash
sh ./scripts/run-event-preroll.sh
~~~

Validates the primary EVENT_ONLY candidate:

~~~text
one normal ZLM recorder
-> bounded tmpfs short fragments
-> Event/Trigger promotion window
-> verify + atomic persistent publish
~~~

It tests ~2s and ~5s GOP sources, ten Event times, overlapping Events, deduplicated promotion, tmpfs GC, and comparison evidence for startRecordTask / GOP-ring startRecord.

### POC-05 + POC-06

~~~bash
sh ./scripts/run-timeline-playback.sh
~~~

Kills MediaMTX to create a real source outage, then validates actual segment ranges/Gap projection, DST/time normalization, Event offset mapping, and beginning/middle/end ZLM VOD seek behavior.

### POC-07

~~~bash
sh ./scripts/run-remote-restore.sh
~~~

Uses rclone WebDAV as a deterministic remote and validates interrupted restore, retry, `.partial` safety, atomic cache publication, ZLM VOD, next-segment prefetch, cache eviction, and remote outage isolation from local recording.

### POC-10

~~~bash
sh ./scripts/run-reconciliation.sh
~~~

Injects lost hook, API downtime, SQLite write-lock downtime, stale catalog metadata, recoverable orphan media, ambiguous orphan media, and a simulated reconciliation-process crash.

## Evidence policy

Generated runtime data is written under `runtime/` and is gitignored.

Result documents live under:

~~~text
docs/poc-results/
~~~

Do not mark a result PASS because the harness builds or because source review looks correct.

A PASS requires real runtime evidence that satisfies `docs/plans/01-design-freeze-poc.md`.

## Ownership guardrails

The harness deliberately does not introduce:

- a permanent FFmpeg recorder;
- a custom RTSP reconnect engine;
- RecordingIntent / RecordingSession persistence;
- StoragePool;
- Redis / Celery;
- a custom cloud-drive protocol;
- a custom compressed-video packet ring.

ZLM remains the media/normal-recording owner. rclone owns remote transfer. FFmpeg/ffprobe are only test/derived-media tools.
