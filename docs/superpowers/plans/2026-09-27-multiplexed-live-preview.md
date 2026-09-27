# Multiplexed Live Grid Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace one endless MJPEG request per H.265 grid tile with one authenticated WebSocket that carries complete JPEG frames for up to 16 slots.

**Architecture:** Keep descriptor and MediaSession ownership inside each tile, but register low-quality H.265 descriptors with a page-level preview wall client. The backend validates every registration, runs one bounded JPEG producer per accepted slot, retains only the latest unsent frame for each slot, and serializes all text events and binary frames through one WebSocket sender.

**Tech Stack:** Python 3.12+, FastAPI/Starlette WebSocket, asyncio, FFmpeg image2pipe, Vue 3, TypeScript, Vitest, pytest

**Spec:** `docs/superpowers/specs/2026-09-27-multiplexed-live-preview-design.md`

## Global Constraints

- The socket endpoint is `WS /api/v1/live/previews/ws` with protocol version `1`.
- Valid grid sizes and server-enforced profiles are exactly: 4 tiles at 640 px/5 FPS, 9 tiles at 480 px/3 FPS, and 16 tiles at 320 px/2 FPS.
- A sync message is at most 64 KiB, contains at most 16 unique slots, and carries a client-generated unsigned 32-bit `subscription_id` for each slot.
- A binary message is `[version byte][slot byte][subscription_id uint32 big-endian][complete JPEG]`; JPEG payloads are at most 2 MiB.
- Each slot retains at most one unsent frame; newer frames replace stale frames and ready slots are drained fairly.
- The WebSocket requires a same-origin interactive browser session with `camera.view`; every camera and MediaSession is authorized independently.
- Direct H.264 playback, focused/high-quality playback, recording, audio, and compatibility-transcode capacity remain unchanged.
- Grid playback never falls back to one multipart HTTP response per tile.
- Frontend reconnect delays are 1, 2, 4, 8, then at most 15 seconds.

## Review Focus

- A frame queued before a slot is reassigned must be discarded by `subscription_id`; Task 4 adds a stale-frame routing test.
- A slow socket must keep only the newest frame per slot without starving another slot; Task 2 adds overwrite and fairness tests.
- Expiring one MediaSession must stop only that producer while other slots continue; Task 3 adds a two-slot revocation test.
- Rapid layout, visibility, and registration changes must never create duplicate sockets or resynchronize removed streams; Task 4 adds lifecycle race tests.
- Missing authentication, cross-origin handshakes, camera-scope violations, and cross-camera MediaSessions must be rejected without starting FFmpeg; Task 3 tests each boundary.

---

### Task 1: Complete JPEG Frame Source

**Files:**
- Modify: `backend/app/modules/cameras/live_preview.py`
- Modify: `backend/app/modules/cameras/api.py`
- Test: `backend/tests/test_live_preview.py`
- Test: `backend/tests/test_camera_live_api.py`

**Interfaces:**
- Produces: `JpegFrameParser(max_frame_bytes: int = 2 * 1024 * 1024)` with `feed(chunk: bytes) -> list[bytes]`.
- Produces: `LivePreviewSession.frames() -> AsyncIterator[bytes]`, yielding complete SOI-to-EOI JPEG images.
- Produces: `multipart_preview_stream(frames: AsyncIterator[bytes], *, boundary: str = "ffmpeg") -> AsyncIterator[bytes]`.
- Preserves: `open_live_preview(settings, *, source_url, width, fps) -> LivePreviewSession` and the existing multipart HTTP endpoint.

- [ ] **Step 1: Add failing parser and command tests**

  Add tests named `test_jpeg_frame_parser_handles_split_noise_and_multiple_frames`, `test_jpeg_frame_parser_rejects_oversized_frame`, and update the command assertion to require `-f image2pipe pipe:1`. Assert exact JPEG boundaries and the 2 MiB limit.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `cd backend && pytest tests/test_live_preview.py -q`

  Expected: FAIL because `JpegFrameParser` does not exist and FFmpeg still emits `mpjpeg`.

- [ ] **Step 3: Implement complete-frame parsing**

  Add `JpegFrameParser`; change FFmpeg output to `image2pipe`; make startup wait for the first complete JPEG within the existing timeout; store `first_frame` rather than an opaque first chunk; make `frames()` parse subsequent chunks and preserve current cancellation-safe process cleanup.

- [ ] **Step 4: Add a failing multipart compatibility test**

  Update the camera live API fake to expose `frames()`. Assert the response still uses `multipart/x-mixed-replace; boundary=ffmpeg`, contains a complete boundary-delimited JPEG, and closes the preview when its MediaSession is revoked.

- [ ] **Step 5: Wrap frames for the existing HTTP endpoint**

  Implement `multipart_preview_stream` with `Content-Type: image/jpeg` and `Content-Length` per part, and use it in `get_camera_live_preview` without changing its URL, authentication, or cache headers.

- [ ] **Step 6: Verify the task**

  Run: `cd backend && pytest tests/test_live_preview.py tests/test_camera_live_api.py -q`

  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/modules/cameras/live_preview.py backend/app/modules/cameras/api.py backend/tests/test_live_preview.py backend/tests/test_camera_live_api.py
  git commit -m "refactor: expose complete live preview frames"
  ```

### Task 2: Preview Wall Protocol and Backpressure Engine

**Files:**
- Create: `backend/app/modules/cameras/live_preview_wall.py`
- Create: `backend/tests/test_live_preview_wall.py`

**Interfaces:**
- Produces: immutable `PreviewWallProfile(width: int, fps: int)`.
- Produces: immutable `PreviewWallSubscription(slot: int, subscription_id: int, camera_id: UUID, media_session_id: UUID)`.
- Produces: immutable `PreviewWallSync(layout_slots: Literal[4, 9, 16], streams: tuple[PreviewWallSubscription, ...])`.
- Produces: `parse_preview_wall_sync(raw: str) -> PreviewWallSync` and `preview_wall_profile(layout_slots: int) -> PreviewWallProfile`.
- Produces: `encode_preview_wall_frame(subscription, jpeg: bytes) -> bytes`.
- Produces: `OpenedPreview(preview: LivePreviewSession, release: Callable[[], None])`.
- Produces: `PreviewWallSession(open_source: Callable[..., Awaitable[OpenedPreview]])` with `apply_sync(sync)`, `next_message()`, `fail_subscription(...)`, and `close()` async methods.
- Consumes: `LivePreviewSession.frames()` from Task 1.

- [ ] **Step 1: Add failing protocol validation tests**

  Cover the exact three profiles, a valid sync, the 64 KiB limit, invalid versions/layouts/UUIDs, duplicate or out-of-range slots, more than 16 streams, and `subscription_id` values outside uint32.

- [ ] **Step 2: Run protocol tests and verify RED**

  Run: `cd backend && pytest tests/test_live_preview_wall.py -q`

  Expected: collection FAIL because the module and interfaces do not exist.

- [ ] **Step 3: Implement protocol values and binary framing**

  Use Pydantic or explicit validation to produce the immutable domain values. Encode the six-byte header exactly and reject JPEGs larger than 2 MiB or without SOI/EOI markers.

- [ ] **Step 4: Add failing lifecycle, overwrite, and fairness tests**

  Assert that unchanged sync entries keep their producer, changed entries close the old producer, removed entries release cleanup, a slow consumer receives only the latest frame for one slot, another ready slot is not starved, producer failure emits only that subscription's error, and `close()` stops all producers.

- [ ] **Step 5: Implement `PreviewWallSession`**

  Start each new source in an independent task so one slow camera cannot delay other subscriptions. Maintain one latest frame per slot plus a fair ready-slot deque. Route all events and binary frames through `next_message()` so the API layer has exactly one WebSocket sender. Include `subscription_id` in ready/error events and call every `OpenedPreview.release` exactly once.

- [ ] **Step 6: Verify the task**

  Run: `cd backend && pytest tests/test_live_preview.py tests/test_live_preview_wall.py -q`

  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/modules/cameras/live_preview_wall.py backend/tests/test_live_preview_wall.py
  git commit -m "feat: add multiplexed preview wall engine"
  ```

### Task 3: Authenticated WebSocket Endpoint

**Files:**
- Modify: `backend/app/modules/auth/dependencies.py`
- Modify: `backend/app/modules/cameras/api.py`
- Create: `backend/app/modules/cameras/live_preview_wall_api.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/tests/test_live_preview_wall_api.py`
- Test: `backend/tests/test_camera_live_api.py`

**Interfaces:**
- Produces: `resolve_auth_context(connection: HTTPConnection, session: Session) -> AuthContext`; existing HTTP dependency delegates to it.
- Produces: public `LiveSelection` and `live_selection_for_media_session(connection: HTTPConnection, *, media_session_id, camera_id, user_id, session) -> LiveSelection` in the camera API module.
- Produces: `same_origin_websocket(websocket: WebSocket) -> bool`.
- Produces: `router` containing `@router.websocket("/live/previews/ws")`.
- Consumes: `PreviewWallSession`, `OpenedPreview`, `preview_wall_profile`, and `open_live_preview`.

- [ ] **Step 1: Add failing authentication and origin tests**

  Use `TestClient.websocket_connect` to assert that no session cookie, an API-token-only context, a missing/mismatched Origin, or a user without `camera.view` closes without starting a preview. Assert a logged-in same-origin administrator can connect.

- [ ] **Step 2: Run the endpoint tests and verify RED**

  Run: `cd backend && pytest tests/test_live_preview_wall_api.py -q`

  Expected: FAIL because the WebSocket route does not exist.

- [ ] **Step 3: Extract connection-neutral authentication and live selection**

  Move request-independent authentication into `resolve_auth_context`, accepting Starlette `HTTPConnection`, while preserving all existing HTTP behavior. Rename `_LiveSelection` and `_live_selection_for_media_session` to their public names and accept `HTTPConnection`, then update existing references and run `test_camera_live_api.py`.

- [ ] **Step 4: Add failing subscription authorization tests**

  Create live descriptors through the existing API, then sync subscriptions over the socket. Assert camera-scope denial, cross-user ownership, cross-camera MediaSession use, expired session, and changed binding each emit a slot error and never expose a URL or credential.

- [ ] **Step 5: Implement the WebSocket route and source opener**

  Accept only after same-origin interactive authentication. Parse sync messages up to 64 KiB, send `fatal` then close 1008 for socket-wide violations, and use a single sender loop over `PreviewWallSession.next_message()`. For each source, open a short database session, verify effective camera scope and MediaSession selection, commit/close the database session, sign the ZLM internal RTSP URL, open the preview, and register a MediaSession cleanup callback that is safe to invoke from its timer thread.

- [ ] **Step 6: Add failing isolation and cleanup tests**

  With two subscribed slots, revoke one MediaSession and assert only its producer closes and the other still emits a binary frame. Disconnect the socket and assert every preview closes and every registry cleanup is removed.

- [ ] **Step 7: Implement revocation and disconnect cleanup**

  Bridge registry callbacks onto the endpoint event loop with `call_soon_threadsafe`; include slot and `subscription_id` in revocation errors; close `PreviewWallSession` in the WebSocket `finally` block.

- [ ] **Step 8: Verify the task**

  Run: `cd backend && pytest tests/test_live_preview_wall_api.py tests/test_camera_live_api.py tests/test_live_preview.py tests/test_live_preview_wall.py -q`

  Expected: PASS.

- [ ] **Step 9: Commit**

  ```bash
  git add backend/app/modules/auth/dependencies.py backend/app/modules/cameras/api.py backend/app/modules/cameras/live_preview_wall_api.py backend/app/api/v1/router.py backend/tests/test_live_preview_wall_api.py backend/tests/test_camera_live_api.py
  git commit -m "feat: expose authenticated preview wall socket"
  ```

### Task 4: Shared Frontend Preview Wall Client

**Files:**
- Create: `frontend/src/live/previewWall.ts`
- Create: `frontend/src/live/previewWall.spec.ts`

**Interfaces:**
- Produces: `type PreviewGridSlots = 4 | 9 | 16`.
- Produces: `interface PreviewWallListener { onFrame(jpeg: Blob): void; onReady(): void; onError(message: string): void; onReconnecting(): void }`.
- Produces: `interface PreviewWallRegistration { firstFrame: Promise<boolean>; close(): void }`.
- Produces: `interface LivePreviewWallClient { setLayout(slots: PreviewGridSlots | null): void; subscribe(input, listener): PreviewWallRegistration; close(): void }`.
- Produces: `createLivePreviewWallClient(options?) -> LivePreviewWallClient`; production options use same-origin `ws:`/`wss:` URL and browser timers, while tests inject WebSocket and timer fakes.

- [ ] **Step 1: Add failing single-socket and sync tests**

  Register 9 and then 16 streams and assert one WebSocket is created, sync messages contain the current layout and registrations, registration IDs are uint32 and change when a slot is reassigned, and unsubscribe removes the stream from the next sync.

- [ ] **Step 2: Run the client tests and verify RED**

  Run: `cd frontend && npm test -- src/live/previewWall.spec.ts`

  Expected: FAIL because `createLivePreviewWallClient` does not exist.

- [ ] **Step 3: Implement connection and synchronization**

  Set `binaryType = "arraybuffer"`; debounce sync to one microtask after registration changes; keep one socket while layout is 4/9/16 and at least one subscription exists; send the complete sync after open and reconnect; close when layout becomes null or the client closes.

- [ ] **Step 4: Add failing routing, stale-frame, and lifecycle tests**

  Assert ready/error/binary messages reach only the matching slot and `subscription_id`; an old queued frame after slot reassignment is ignored; malformed server frames are ignored safely; rapid layout changes create no duplicate socket; reconnect uses delays 1/2/4/8/15 seconds and sends only current subscriptions; explicit close cancels reconnect.

- [ ] **Step 5: Implement decoding and reconnect**

  Decode the six-byte header with `DataView`, validate protocol version, slot, current registration, JPEG markers, and payload limit, then deliver a JPEG `Blob`. Resolve `firstFrame` on the first matching binary frame, not merely the `ready` event. Preserve the latest displayed image through reconnect by notifying listeners rather than clearing frames.

- [ ] **Step 6: Verify the task**

  Run: `cd frontend && npm test -- src/live/previewWall.spec.ts && npm run typecheck`

  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/live/previewWall.ts frontend/src/live/previewWall.spec.ts
  git commit -m "feat: add shared live preview client"
  ```

### Task 5: Live View and Tile Integration

**Files:**
- Modify: `frontend/src/views/LiveView.vue`
- Create: `frontend/src/views/LiveView.spec.ts`
- Modify: `frontend/src/components/live/LiveCameraTile.vue`
- Modify: `frontend/src/components/live/LiveCameraTile.spec.ts`

**Interfaces:**
- `LiveView.vue` owns one `LivePreviewWallClient`, sets its layout to 4/9/16 or null, passes it plus the stable zero-based visible slot index to each tile, and closes it on unmount.
- `LiveCameraTile` adds optional `previewWall: LivePreviewWallClient | null` and `previewSlot: number | null` props.
- Low-quality H.265 grid preview consumes `PreviewWallRegistration.firstFrame`; focused/high-quality startup continues to use `cameraLivePreviewUrl`.

- [ ] **Step 1: Add failing LiveView ownership tests**

  Mock `createLivePreviewWallClient`, mount the view with 9 visible cameras, and assert exactly one client is created, layout 9 is selected, slots 0-8 are passed to tiles, layout/focus changes update or suspend the client, and unmount closes it.

- [ ] **Step 2: Add failing tile registration tests**

  Replace the low-quality H.265 multipart expectation with a fake shared client. Assert the tile registers camera ID, MediaSession ID, and its slot; does not render a `/preview.mjpeg` URL; remains connecting until the first matching frame; displays the Blob URL and JPEG badge; unregisters and revokes object URLs on stop, quality/source change, suspension, and unmount.

- [ ] **Step 3: Run component tests and verify RED**

  Run: `cd frontend && npm test -- src/views/LiveView.spec.ts src/components/live/LiveCameraTile.spec.ts`

  Expected: FAIL because the view does not own/pass a client and the tile still opens multipart MJPEG for low-quality grid playback.

- [ ] **Step 4: Implement LiveView ownership and explicit tile props**

  Create the client once in component setup. Drive `setLayout` from focused state and `layoutSlots`, use `(camera, index)` in the visible camera loop, and close the client in the existing teardown.

- [ ] **Step 5: Implement shared grid preview in the tile**

  Split preview cleanup into shared-registration and single-HTTP cleanup. For low-quality playback with a supplied client/slot, register with the shared client, create and replace object URLs on frames, and make the first-frame promise the successful `preview` transport boundary. For high/focused playback, preserve the current multipart bridge and compatibility upgrade behavior. On shared errors, enter the existing reconnect path without starting per-tile multipart fallback.

- [ ] **Step 6: Verify the task**

  Run: `cd frontend && npm test -- src/live/previewWall.spec.ts src/views/LiveView.spec.ts src/components/live/LiveCameraTile.spec.ts && npm run build`

  Expected: PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/views/LiveView.vue frontend/src/views/LiveView.spec.ts frontend/src/components/live/LiveCameraTile.vue frontend/src/components/live/LiveCameraTile.spec.ts
  git commit -m "feat: multiplex H.265 grid previews"
  ```

### Task 6: Documentation, Full Verification, and Integration

**Files:**
- Modify: `docs/specs/0020-live-view-media-session.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/TECH_STACK.md`

**Interfaces:**
- Documents the one-WebSocket grid path, binary protocol boundary, layout profiles, MediaSession authorization, and focused-playback promotion.
- Preserves the standalone multipart endpoint as a focused startup bridge and diagnostic path.

- [ ] **Step 1: Update product and architecture documentation**

  Replace language that describes one low-quality multipart response per grid tile. Record the 4/9/16 profiles, one-latest-frame backpressure rule, subscription cleanup, and unchanged H.264/focused paths.

- [ ] **Step 2: Run full backend verification**

  Run: `cd backend && python -m compileall -q app tests && pytest`

  Expected: compile exit 0 and all tests PASS. If local proxy variables affect HTTP clients, rerun with HTTP/HTTPS/ALL proxy variables unset and record that environment correction.

- [ ] **Step 3: Run full frontend verification**

  Run: `cd frontend && npm test && npm run build`

  Expected: all Vitest tests PASS and Vue typecheck/Vite build exit 0.

- [ ] **Step 4: Run repository checks**

  Run: `git diff --check && bash -n deploy.sh`

  Expected: exit 0.

- [ ] **Step 5: Commit documentation**

  ```bash
  git add docs/specs/0020-live-view-media-session.md docs/ARCHITECTURE.md docs/TECH_STACK.md
  git commit -m "docs: specify multiplexed grid preview"
  ```

- [ ] **Step 6: Review the complete branch**

  Compare the branch against the approved spec. Confirm every acceptance criterion has a corresponding automated test and inspect the final diff for credential leakage, orphaned tasks/processes, unbounded queues, and stale object URLs.

- [ ] **Step 7: Create and attach the pull request**

  Use title `feat: multiplex H.265 grid previews`. The description leads with the five-stream HTTP/1.1 stall, explains the single-WebSocket result, lists 4/9/16 resource profiles, and includes local validation.

- [ ] **Step 8: Wait for CI and merge**

  Wait for Backend, Frontend, and Deployment workflows. If all required checks pass and the PR head SHA is unchanged, squash merge automatically under the user's standing authorization and report the exact merge SHA plus `git pull --ff-only && ./deploy.sh`.
