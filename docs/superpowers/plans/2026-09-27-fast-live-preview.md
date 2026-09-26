# Fast Live Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a low-resolution JPEG preview immediately while an H.265 live source is preparing its H.264 compatibility stream, then replace it with the normal full-motion player at first frame.

**Architecture:** Reuse the exact source already authorized by the live MediaSession and read it from ZLMediaKit's internal RTSP endpoint. A short-lived FFmpeg process emits low-frame-rate multipart JPEG over an authenticated same-origin endpoint; the tile displays that stream only when the source has no direct browser playback path and tears it down as soon as video reaches first frame or playback stops.

**Tech Stack:** FastAPI, asyncio subprocess, FFmpeg, Vue 3, TypeScript, Vitest, pytest.

**Spec:** `docs/specs/0020-live-view-media-session.md`

## Global Constraints

- Recording bindings and recording processes remain unchanged.
- Preview authorization is scoped to the existing user, camera, and MediaSession.
- The preview process is short-lived and must stop on disconnect, cancellation, visibility suspension, or successful full-video playback.
- Directly playable streams do not start a JPEG preview process.
- Preview dimensions and frame rate are bounded by the backend.
- No new frontend or backend dependency is introduced.

## Review Focus

- A MediaSession belonging to another user or camera must not authorize preview access; cover with an API test.
- A disconnected browser must terminate the FFmpeg preview process; cover with a service lifecycle test.
- Direct H.264 playback must not start the preview placeholder; cover with a component test.
- H.265 compatibility startup must keep the preview visible until the real video reaches first frame; cover with component tests for start and replacement.
- Reconnect, source changes, and visibility suspension must discard stale preview URLs; cover with component cleanup tests.

---

### Task 1: Bounded multipart JPEG preview service

**Files:**
- Create: `backend/app/modules/cameras/live_preview.py`
- Test: `backend/tests/test_live_preview.py`

**Interfaces:**
- Produces: `build_live_preview_command(settings, *, source_url: str, width: int, fps: int) -> list[str]`.
- Produces: `open_live_preview(settings, *, source_url: str, width: int, fps: int) -> LivePreviewSession` and `LivePreviewSession.stream()`.

- [ ] Write tests for low-delay FFmpeg arguments, clamped width/FPS, first-chunk startup, and process termination when streaming closes.
- [ ] Run the focused backend test and confirm it fails because the service is absent.
- [ ] Implement the smallest async FFmpeg service that emits `mpjpeg` and owns process cleanup.
- [ ] Run the focused backend test and confirm it passes.
- [ ] Commit the task.

### Task 2: MediaSession-scoped preview endpoint

**Files:**
- Modify: `backend/app/modules/cameras/api.py`
- Test: `backend/tests/test_camera_live_api.py`

**Interfaces:**
- Consumes: `open_live_preview` from Task 1.
- Produces: `GET /api/v1/cameras/{camera_id}/live/preview.mjpeg?media_session_id=...&width=...&fps=...` returning authenticated `multipart/x-mixed-replace` content.

- [ ] Write API tests for a valid session, invalid/cross-camera session, cache headers, and sanitized preview startup failure.
- [ ] Run the focused API tests and confirm the new endpoint is missing.
- [ ] Implement the endpoint using `_require_live_media_session`, `_live_selection_for_media_session`, and a signed internal ZLM RTSP URL.
- [ ] Run the focused API tests and confirm they pass.
- [ ] Commit the task.

### Task 3: Fast placeholder lifecycle in the live tile

**Files:**
- Modify: `frontend/src/api/live.ts`
- Modify: `frontend/src/live/playback.ts`
- Modify: `frontend/src/components/live/LiveCameraTile.vue`
- Modify: `frontend/src/components/live/LiveCameraTile.spec.ts`
- Test: `frontend/src/live/playback.spec.ts`

**Interfaces:**
- Produces: `cameraLivePreviewUrl(cameraId, mediaSessionId, width, fps) -> string`.
- Produces: `needsFastPreview(stream, capabilities) -> boolean`.
- Consumes: the Task 2 endpoint as an `<img>` source with same-origin session credentials.

- [ ] Write failing unit/component tests proving H.265 starts the placeholder, H.264 skips it, and first video frame/source teardown hides it.
- [ ] Run focused frontend tests and confirm the expected failures.
- [ ] Add the URL/helper functions and tile image state; keep the image behind controls and replace it only after a real video frame.
- [ ] Run focused frontend tests and confirm they pass.
- [ ] Commit the task.

### Task 4: Specification and full verification

**Files:**
- Modify: `docs/specs/0020-live-view-media-session.md`

**Interfaces:**
- Consumes: Tasks 1-3 behavior.
- Produces: documented fast-preview lifecycle and operational limits.

- [ ] Document the JPEG placeholder, its lack of audio, and mandatory teardown.
- [ ] Run the full backend and frontend test suites, frontend build/typecheck, compile checks, and `git diff --check`.
- [ ] Commit the documentation and any test-only corrections.
