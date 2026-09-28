# Recording Range Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make historical recordings advance continuously by serving completed MP4 files over an authorized HTTP Range endpoint and seeking once after metadata loads.

**Architecture:** The resolver returns a same-origin static-media descriptor for every local or restored `PlayablePlan`. A protected FastAPI route resolves and streams the current file, while both Vue playback paths apply the descriptor offset once per loaded source and then leave the media clock alone.

**Tech Stack:** Python 3.12, FastAPI/Starlette, SQLAlchemy, pytest, Vue 3, TypeScript, Vitest

**Spec:** `docs/superpowers/specs/2026-09-28-recording-range-playback-design.md`

## Global Constraints

- Media reads require `recording.view` and effective camera scope.
- Never expose filesystem paths or camera credentials.
- Remote-only recordings retain the existing restore flow.
- Browser `currentTime` is written exactly once per static MP4 source load.
- Existing fMP4 live-stream timebase behavior remains available in the frontend type contract.

## Review Focus

- A scoped user must receive 404 for media belonging to an unassigned camera; Task 1 tests this.
- A Range request must return 206 with correct bytes and headers; Task 1 tests this.
- A file removed after descriptor resolution must fail cleanly; Task 1 tests this.
- A non-zero playback offset must be applied once even if metadata events repeat; Task 2 tests this.
- Preloaded and re-resolved synchronized tiles must reset the one-time seek for the new source; Task 2 tests the source lifecycle.

---

### Task 1: Authorized MP4 Range Transport

**Files:**
- Modify: `backend/app/modules/recordings/api.py`
- Modify: `backend/app/modules/recordings/schemas.py`
- Modify: `backend/app/modules/recordings/playback.py`
- Test: `backend/tests/test_playback_cache.py`

**Interfaces:**
- Produces: `GET /api/v1/recordings/{segment_id}/media` returning inline `video/mp4` with byte-range support.
- Produces: playable descriptors with `transport: "mp4"` and `/api/v1/recordings/{segment_id}/media` URL.
- Preserves: `PlaybackResolverService.plan*` and pending/gap behavior.

- [ ] Add failing API tests for direct descriptor transport, authorized full and Range reads, camera-scope denial, and a missing file.
- [ ] Run the focused backend test and verify RED because descriptors still use fMP4 and the route is absent.
- [ ] Implement the media route and static descriptor without invoking ZLMediaKit.
- [ ] Run `backend/.venv/bin/pytest backend/tests/test_playback_cache.py -q` and verify PASS.
- [ ] Commit the backend task.

### Task 2: One-Time Browser Offset Seek

**Files:**
- Modify: `frontend/src/api/playback.ts`
- Modify: `frontend/src/views/PlaybackView.vue`
- Modify: `frontend/src/views/PlaybackView.spec.ts`
- Modify: `frontend/src/components/playback/TolerantPlaybackTile.vue`
- Modify: `frontend/src/components/playback/TolerantPlaybackTile.spec.ts`

**Interfaces:**
- Consumes: `PlaybackPlayable.transport: "mp4" | "fmp4"`, `offset_ms`, and `segment_start_at`.
- Produces: exactly one initial static-file seek per source after `loadedmetadata`.
- Preserves: no browser hard-seek for fMP4 live VOD descriptors.

- [ ] Add failing single-player and tolerant-tile tests for one offset seek and no repeat on later media events/time updates.
- [ ] Run the focused Vitest files and verify RED because MP4 descriptors are not recognized or sought.
- [ ] Implement per-source initial-seek state and correct absolute media anchoring.
- [ ] Run the focused tests and verify PASS.
- [ ] Run full backend and frontend suites plus frontend build and `git diff --check`.
- [ ] Commit the frontend task.
