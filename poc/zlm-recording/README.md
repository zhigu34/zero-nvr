# ZLMediaKit Recording / Stream-Sharing POC

This is a **disposable design-freeze harness**, not production zero-nvr code.

It covers:

- **POC-01** — ZLM continuous recording, `on_record_mp4` indexing, deliberately lost hook, idempotent reconciliation;
- **POC-08** — ZLM as the only source-facing reader while multiple downstream viewers consume the ZLM stream.

## Topology

```text
MediaMTX synthetic camera
  cam_main + cam_sub
         ↓
    ZLMediaKit
      ├─ MP4 recording (cam-main)
      └─ RTSP downstream viewers
         ↓
tiny POC FastAPI + SQLite evidence service
```

MediaMTX is only a deterministic fake camera source. It is not a production zero-nvr dependency.

The main source is 1280x720 H.264 at 25 fps with an approximately 2-second GOP. The sub source is 640x360 H.264 at 15 fps with an approximately 2-second GOP.

## Ownership checks

This harness deliberately does **not** contain:

- an FFmpeg permanent recorder;
- a custom RTSP reconnect loop;
- RecordingIntent / RecordingSession tables;
- StoragePool;
- Redis / Celery;
- a custom upload queue.

ZLM performs source pulling, reconnect behavior, and actual recording.

FFmpeg exists in the POC API image only for:

1. ffprobe recovery fallback on an intentionally unindexed finalized file;
2. two temporary RTSP readers used to prove stream sharing.

## Prerequisites

- Docker Engine / compatible Docker Desktop;
- Docker Compose v2;
- network access to pull test images.

## Run

```bash
cd poc/zlm-recording
cp .env.example .env
sh ./scripts/run.sh
```

The script:

1. copies ZLM's own default `config.ini` from the selected image and patches only POC settings;
2. starts synthetic main/sub RTSP sources;
3. adds both sources to ZLM with `addStreamProxy`;
4. enables ZLM MP4 recording only for `cam-main`;
5. waits for at least three finalized `on_record_mp4` hooks;
6. requires zero ffprobe calls on the normal hook path;
7. intentionally acknowledges but does not index the next recording hook;
8. scans finalized files and uses ffprobe only for the missing catalog entry;
9. runs reconciliation a second time and requires zero new rows;
10. starts two extra RTSP readers against **ZLM**, not MediaMTX;
11. requires the source-facing MediaMTX reader count to stay exactly one for main and one for sub;
12. writes evidence under `runtime/`.

By default the containers are stopped after the run. Set:

```text
KEEP_RUNNING=1
```

in `.env` to inspect them.

## Evidence

Generated locally and gitignored:

```text
runtime/evidence.json
runtime/docker-compose.log
runtime/docker-compose-ps.txt
runtime/zlm-container-inspect.json
runtime/mediamtx-container-inspect.json
runtime/poc.db
runtime/recordings/
```

`evidence.json` records ZLM's `/index/api/version` result. This is important because the official `zlmediakit/zlmediakit:master` image follows upstream master rather than representing a fixed product release.

After an actual run, copy the relevant evidence into:

- `docs/poc-results/01-zlm-recording.md`
- `docs/poc-results/08-stream-sharing.md`

Do not commit generated recordings.

## Accelerated segment duration

The harness defaults to 10-second MP4 segments so the test can complete quickly.

That is a **POC acceleration only**. The product design still targets roughly 300-second normal recording segments.

The invariant being tested is that zero-nvr indexes the real `start_time` and `time_len` reported by finalized media instead of assuming either 10 or 300 seconds.

## Ordinary MP4 / fMP4

POC-01 uses:

```text
POC_ZLM_ENABLE_FMP4=0
```

POC-02 will use the same basic environment with fMP4 enabled and deliberately interrupt ZLM while a segment is open, then verify the incomplete file with ffprobe, ZLM VOD, and FFmpeg remux/export.

## Official references

- ZLMediaKit HTTP API: <https://github.com/ZLMediaKit/ZLMediaKit/wiki/MediaServer支持的HTTP-API>
- ZLMediaKit HTTP hook API: <https://github.com/ZLMediaKit/ZLMediaKit/wiki/MediaServer支持的HTTP-HOOK-API>
- ZLMediaKit repository / Docker guidance: <https://github.com/ZLMediaKit/ZLMediaKit>
- MediaMTX hooks: <https://mediamtx.org/docs/features/hooks>
- MediaMTX metrics: <https://mediamtx.org/docs/features/metrics>
- MediaMTX FFmpeg publishing: <https://mediamtx.org/docs/publish/ffmpeg>

## Result rule

A successful code review is **not** a PASS.

The POC can only be marked PASS after `scripts/run.sh` executes in a Docker environment and the generated evidence satisfies `docs/plans/01-design-freeze-poc.md`.
