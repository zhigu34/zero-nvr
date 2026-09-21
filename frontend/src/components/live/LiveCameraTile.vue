<script setup lang="ts">
import Hls from "hls.js"
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch
} from "vue"

import {
  moveCameraPtz,
  stopCameraPtz,
  type CameraSummary
} from "../../api/cameras"
import { errorMessage } from "../../api/client"
import { browserMediaUrl } from "../../api/media"
import {
  cameraSnapshotUrl,
  getCameraLiveStream,
  type CameraLiveStream,
  type LiveQuality
} from "../../api/live"
import {
  createRecordingTrigger,
  listRecordingTriggers,
  stopRecordingTrigger,
  type RecordingTrigger
} from "../../api/recordings"
import { useAuthStore } from "../../stores/auth"
import UiIcon from "../ui/UiIcon.vue"

const auth = useAuthStore()

const props = defineProps<{
  camera: CameraSummary
  quality: LiveQuality
  focused?: boolean
}>()

const emit = defineEmits<{
  focus: [cameraId: string]
}>()

const tile = ref<HTMLElement | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const descriptor = ref<CameraLiveStream | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const playing = ref(false)
const muted = ref(true)
const recordingTrigger = ref<RecordingTrigger | null>(null)
const recordingBusy = ref(false)
const recordingError = ref<string | null>(null)
const ptzOpen = ref(false)
const ptzError = ref<string | null>(null)
const ptzHolding = ref(false)
const pageVisible = ref(!document.hidden)
const tileVisible = ref(true)
const fullscreenActive = ref(false)
const reconnecting = ref(false)

let hls: Hls | null = null
let generation = 0
let tokenRefreshTimer: number | null = null
let reconnectTimer: number | null = null
let reconnectAttempt = 0
let recordingErrorTimer: number | null = null
let ptzMovePromise: Promise<void> | null = null
let ptzStopPromise: Promise<void> | null = null
let visibilityObserver: IntersectionObserver | null = null

const playbackSuspended = computed(
  () => !pageVisible.value || !tileVisible.value
)

const requestedQuality = computed<LiveQuality>(() =>
  fullscreenActive.value ? "high" : props.quality
)

const manualRecordingActive = computed(() => {
  const trigger = recordingTrigger.value
  return Boolean(
    trigger &&
      trigger.type === "MANUAL" &&
      trigger.state === "ACTIVE" &&
      trigger.planned_end_at === null
  )
})

function clearRecordingError(): void {
  if (recordingErrorTimer !== null) {
    window.clearTimeout(recordingErrorTimer)
    recordingErrorTimer = null
  }
  recordingError.value = null
}

function showRecordingError(message: string): void {
  clearRecordingError()
  recordingError.value = message
  recordingErrorTimer = window.setTimeout(() => {
    recordingErrorTimer = null
    recordingError.value = null
  }, 5000)
}

async function stopPtzNow(): Promise<void> {
  if (ptzStopPromise) {
    await ptzStopPromise
    return
  }
  ptzStopPromise = stopCameraPtz(props.camera.id)
    .then(() => undefined)
    .catch((caught) => {
      ptzError.value = errorMessage(caught)
    })
    .finally(() => {
      ptzStopPromise = null
    })
  await ptzStopPromise
}

async function beginPtz(
  pan: number,
  tilt: number,
  zoom = 0
): Promise<void> {
  if (
    !props.camera.ptz_capable ||
    !auth.hasPermission("camera.control")
  ) {
    return
  }
  ptzHolding.value = true
  ptzError.value = null
  if (ptzMovePromise) return

  ptzMovePromise = moveCameraPtz(
    props.camera.id,
    { pan, tilt, zoom }
  )
    .then(() => undefined)
    .catch((caught) => {
      ptzError.value = errorMessage(caught)
      ptzHolding.value = false
    })
    .finally(async () => {
      ptzMovePromise = null
      if (!ptzHolding.value) {
        await stopPtzNow()
      }
    })
  await ptzMovePromise
}

function endPtz(): void {
  if (!ptzHolding.value && !ptzMovePromise) return
  ptzHolding.value = false
  if (!ptzMovePromise) {
    void stopPtzNow()
  }
}

function clearTokenRefresh(): void {
  if (tokenRefreshTimer === null) return
  window.clearTimeout(tokenRefreshTimer)
  tokenRefreshTimer = null
}

function scheduleTokenRefresh(expiresAt: string): void {
  clearTokenRefresh()
  const refreshIn = Math.max(
    5_000,
    new Date(expiresAt).getTime() - Date.now() - 60_000
  )
  tokenRefreshTimer = window.setTimeout(() => {
    tokenRefreshTimer = null
    void loadStream()
  }, refreshIn)
}

function clearReconnect(): void {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  reconnecting.value = false
}

function scheduleReconnect(): void {
  clearReconnect()
  if (playbackSuspended.value) return

  const delays = [1_000, 2_000, 4_000, 8_000, 15_000]
  const delay = delays[
    Math.min(reconnectAttempt, delays.length - 1)
  ]
  reconnectAttempt += 1
  reconnecting.value = true
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    reconnecting.value = false
    if (!playbackSuspended.value) {
      void loadStream()
    }
  }, delay)
}

function destroyPlayer(): void {
  generation += 1
  clearTokenRefresh()
  clearReconnect()
  hls?.destroy()
  hls = null
  playing.value = false

  if (video.value) {
    video.value.pause()
    video.value.removeAttribute("src")
    video.value.load()
  }
}

function suspendPlayback(): void {
  if (ptzHolding.value || ptzMovePromise) {
    endPtz()
  }
  destroyPlayer()
  descriptor.value = null
  error.value = null
  loading.value = false
}

function handlePageVisibilityChange(): void {
  pageVisible.value = !document.hidden
}

function handleTileFullscreenChange(): void {
  fullscreenActive.value =
    document.fullscreenElement === tile.value
}

async function attachStream(stream: CameraLiveStream): Promise<void> {
  await nextTick()
  const element = video.value
  if (!element) return

  const source = browserMediaUrl(stream.hls_url)

  if (element.canPlayType("application/vnd.apple.mpegurl")) {
    element.src = source
    await element.play().catch(() => undefined)
    return
  }

  if (!Hls.isSupported()) {
    throw new Error("This browser cannot play the live HLS stream.")
  }

  hls = new Hls({
    lowLatencyMode: true,
    backBufferLength: 12,
    maxBufferLength: 18,
    liveSyncDurationCount: 2
  })
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (
      !data.fatal ||
      playbackSuspended.value
    ) {
      return
    }
    error.value =
      "Live stream was interrupted. Reconnecting automatically."
    descriptor.value = null
    loading.value = false
    destroyPlayer()
    scheduleReconnect()
  })
  hls.loadSource(source)
  hls.attachMedia(element)
  await element.play().catch(() => undefined)
}

async function loadRecordingState(): Promise<void> {
  recordingTrigger.value = null
  if (!auth.hasPermission("recording.view")) return

  try {
    const items = await listRecordingTriggers(
      props.camera.id
    )
    recordingTrigger.value =
      items.find(
        (item) =>
          item.type === "MANUAL" &&
          item.state === "ACTIVE" &&
          item.planned_end_at === null
      ) ?? null
  } catch {
    recordingTrigger.value = null
  }
}

async function toggleManualRecording(): Promise<void> {
  if (
    !auth.hasPermission("camera.control") ||
    recordingBusy.value
  ) {
    return
  }

  recordingBusy.value = true
  clearRecordingError()
  try {
    if (manualRecordingActive.value && recordingTrigger.value) {
      await stopRecordingTrigger(recordingTrigger.value.id)
      recordingTrigger.value = null
    } else {
      recordingTrigger.value = await createRecordingTrigger(
        props.camera.id,
        "Live view manual recording"
      )
    }
  } catch (caught) {
    showRecordingError(errorMessage(caught))
  } finally {
    recordingBusy.value = false
  }
}

async function loadStream(): Promise<void> {
  if (playbackSuspended.value) {
    loading.value = false
    return
  }

  clearReconnect()
  const currentGeneration = ++generation
  clearTokenRefresh()
  hls?.destroy()
  hls = null
  descriptor.value = null
  error.value = null
  loading.value = true
  playing.value = false

  try {
    const stream = await getCameraLiveStream(
      props.camera.id,
      requestedQuality.value
    )
    if (
      generation !== currentGeneration ||
      playbackSuspended.value
    ) {
      return
    }
    descriptor.value = stream
    await attachStream(stream)
    if (
      generation === currentGeneration &&
      !playbackSuspended.value
    ) {
      scheduleTokenRefresh(stream.expires_at)
    }
  } catch (caught) {
    if (
      generation !== currentGeneration ||
      playbackSuspended.value
    ) {
      return
    }
    error.value = errorMessage(caught)
    scheduleReconnect()
  } finally {
    if (generation === currentGeneration) {
      loading.value = false
    }
  }
}

function toggleMute(): void {
  muted.value = !muted.value
  if (video.value) video.value.muted = muted.value
}

function downloadSnapshot(): void {
  const anchor = document.createElement("a")
  anchor.href = cameraSnapshotUrl(props.camera.id)
  anchor.download = `${props.camera.name.replaceAll(/[^A-Za-z0-9._-]+/g, "-") || "camera"}-snapshot.jpg`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

async function enterFullscreen(): Promise<void> {
  await tile.value?.requestFullscreen?.()
}

function handlePlaying(): void {
  playing.value = true
  reconnectAttempt = 0
  clearReconnect()
  error.value = null
}

function retryStream(): void {
  reconnectAttempt = 0
  destroyPlayer()
  descriptor.value = null
  error.value = null
  if (!playbackSuspended.value) {
    void loadStream()
  }
}

function handleVideoError(): void {
  if (
    loading.value ||
    playbackSuspended.value
  ) {
    return
  }
  error.value =
    "Live stream playback failed. Reconnecting automatically."
  descriptor.value = null
  destroyPlayer()
  scheduleReconnect()
}

onMounted(() => {
  pageVisible.value = !document.hidden

  if (
    typeof IntersectionObserver !== "undefined" &&
    tile.value
  ) {
    tileVisible.value = false
    visibilityObserver = new IntersectionObserver(
      (entries) => {
        const entry = entries.find(
          (item) => item.target === tile.value
        )
        if (entry) {
          tileVisible.value =
            entry.isIntersecting &&
            entry.intersectionRatio > 0
        }
      },
      { threshold: 0.01 }
    )
    visibilityObserver.observe(tile.value)
  } else {
    tileVisible.value = true
  }

  if (playbackSuspended.value) {
    suspendPlayback()
  } else {
    void loadStream()
  }
  void loadRecordingState()

  window.addEventListener("pointerup", endPtz)
  window.addEventListener("pointercancel", endPtz)
  document.addEventListener(
    "visibilitychange",
    handlePageVisibilityChange
  )
  document.addEventListener(
    "fullscreenchange",
    handleTileFullscreenChange
  )
})

watch(
  () => [props.camera.id, requestedQuality.value],
  () => {
    reconnectAttempt = 0
    destroyPlayer()
    descriptor.value = null
    recordingTrigger.value = null
    clearRecordingError()
    if (!playbackSuspended.value) {
      void loadStream()
    }
    void loadRecordingState()
  }
)

watch(playbackSuspended, (suspended, wasSuspended) => {
  if (suspended) {
    suspendPlayback()
  } else if (wasSuspended) {
    reconnectAttempt = 0
    void loadStream()
  }
})

onBeforeUnmount(() => {
  if (ptzHolding.value || ptzMovePromise) {
    endPtz()
  }
  visibilityObserver?.disconnect()
  visibilityObserver = null
  window.removeEventListener("pointerup", endPtz)
  window.removeEventListener("pointercancel", endPtz)
  document.removeEventListener(
    "visibilitychange",
    handlePageVisibilityChange
  )
  document.removeEventListener(
    "fullscreenchange",
    handleTileFullscreenChange
  )
  destroyPlayer()
  clearRecordingError()
})
</script>

<template>
  <article
    ref="tile"
    class="live-tile"
    :class="{
      'live-tile--focused': focused,
      'live-tile--error': error
    }"
    @dblclick="emit('focus', camera.id)"
  >
    <video
      ref="video"
      class="live-tile__video"
      autoplay
      playsinline
      :muted="muted"
      @playing="handlePlaying"
      @waiting="playing = false"
      @error="handleVideoError"
    />

    <div
      v-if="loading || error || playbackSuspended"
      class="live-tile__state"
    >
      <UiIcon
        :name="
          error
            ? 'warning'
            : playbackSuspended
              ? 'pause'
              : 'cameras'
        "
        :size="26"
      />
      <strong>
        {{
          error
            ? reconnecting
              ? "Reconnecting…"
              : "Stream unavailable"
            : playbackSuspended
              ? "Live view paused"
              : "Connecting…"
        }}
      </strong>
      <span>
        {{
          error ||
          (
            playbackSuspended
              ? "Playback resumes automatically when this view is visible."
              : "Starting secure live session"
          )
        }}
      </span>
      <button
        v-if="error && !playbackSuspended"
        class="media-button media-button--text"
        type="button"
        @click.stop="retryStream"
      >
        <UiIcon name="refresh" :size="14" />
        Retry now
      </button>
    </div>

    <header class="live-tile__top">
      <div class="live-tile__identity">
        <span
          class="live-status-dot"
          :class="{ 'live-status-dot--active': playing }"
        />
        <div>
          <strong>{{ camera.name }}</strong>
          <span>{{ camera.location || "No location" }}</span>
        </div>
      </div>

      <div class="live-tile__badges">
        <span
          v-if="manualRecordingActive"
          class="live-recording-badge"
        >
          <i />
          REC
        </span>
        <span v-if="descriptor" class="live-quality-badge">
          {{
            descriptor.purpose === "LIVE_LOW"
              ? "SD"
              : descriptor.purpose === "RECORD"
                ? "REC"
                : "HD"
          }}
        </span>
      </div>
    </header>

    <div
      v-if="ptzOpen && camera.ptz_capable"
      class="live-ptz-panel"
      @dblclick.stop
    >
      <div class="live-ptz-pad">
        <button
          class="media-button"
          type="button"
          aria-label="Pan up"
          @pointerdown.stop.prevent="beginPtz(0, 0.6)"
          @pointerleave="endPtz"
        >
          <UiIcon name="chevron-up" :size="15" />
        </button>
        <button
          class="media-button"
          type="button"
          aria-label="Pan left"
          @pointerdown.stop.prevent="beginPtz(-0.6, 0)"
          @pointerleave="endPtz"
        >
          <UiIcon name="chevron-left" :size="15" />
        </button>
        <span class="live-ptz-pad__center">
          <UiIcon name="ptz" :size="14" />
        </span>
        <button
          class="media-button"
          type="button"
          aria-label="Pan right"
          @pointerdown.stop.prevent="beginPtz(0.6, 0)"
          @pointerleave="endPtz"
        >
          <UiIcon name="chevron-right" :size="15" />
        </button>
        <button
          class="media-button"
          type="button"
          aria-label="Pan down"
          @pointerdown.stop.prevent="beginPtz(0, -0.6)"
          @pointerleave="endPtz"
        >
          <UiIcon name="chevron-down" :size="15" />
        </button>
      </div>

      <div class="live-ptz-zoom">
        <button
          class="media-button media-button--text"
          type="button"
          @pointerdown.stop.prevent="beginPtz(0, 0, -0.6)"
          @pointerleave="endPtz"
        >
          <UiIcon name="minus" :size="14" />
          Zoom
        </button>
        <button
          class="media-button media-button--text"
          type="button"
          @pointerdown.stop.prevent="beginPtz(0, 0, 0.6)"
          @pointerleave="endPtz"
        >
          <UiIcon name="plus" :size="14" />
          Zoom
        </button>
      </div>
      <span v-if="ptzError" class="live-ptz-error">
        {{ ptzError }}
      </span>
    </div>

    <div
      v-if="recordingError"
      class="live-tile__action-error"
    >
      {{ recordingError }}
    </div>

    <footer class="live-tile__controls">
      <div class="live-tile__meta">
        <span v-if="descriptor?.width && descriptor?.height">
          {{ descriptor.width }}×{{ descriptor.height }}
        </span>
        <span v-if="descriptor?.fps">
          {{ Math.round(descriptor.fps) }} FPS
        </span>
      </div>

      <div class="live-tile__buttons">
        <button
          v-if="
            camera.ptz_capable &&
            auth.hasPermission('camera.control')
          "
          class="media-button"
          :class="{ 'media-button--active': ptzOpen }"
          type="button"
          aria-label="Toggle PTZ controls"
          title="PTZ controls"
          @click.stop="ptzOpen = !ptzOpen"
        >
          <UiIcon name="ptz" :size="16" />
        </button>

        <button
          v-if="auth.hasPermission('camera.control')"
          class="media-button"
          :class="{
            'media-button--recording': manualRecordingActive
          }"
          type="button"
          :disabled="recordingBusy"
          :aria-label="
            manualRecordingActive
              ? 'Stop manual recording'
              : 'Start manual recording'
          "
          :title="
            manualRecordingActive
              ? 'Stop manual recording'
              : 'Start manual recording'
          "
          @click.stop="toggleManualRecording"
        >
          <UiIcon name="record" :size="16" />
        </button>

        <button
          class="media-button"
          type="button"
          aria-label="Download snapshot"
          title="Snapshot"
          @click.stop="downloadSnapshot"
        >
          <UiIcon name="snapshot" :size="16" />
        </button>

        <button
          v-if="descriptor?.has_audio"
          class="media-button"
          type="button"
          :aria-label="muted ? 'Unmute camera' : 'Mute camera'"
          :title="muted ? 'Unmute' : 'Mute'"
          @click.stop="toggleMute"
        >
          <UiIcon
            :name="muted ? 'volume-off' : 'volume'"
            :size="16"
          />
        </button>

        <button
          class="media-button"
          type="button"
          aria-label="Focus camera"
          title="Focus camera"
          @click.stop="emit('focus', camera.id)"
        >
          <UiIcon name="focus" :size="16" />
        </button>

        <button
          class="media-button"
          type="button"
          aria-label="Fullscreen camera"
          title="Fullscreen"
          @click.stop="enterFullscreen"
        >
          <UiIcon name="maximize" :size="16" />
        </button>
      </div>
    </footer>
  </article>
</template>


<style scoped>
.live-tile__badges {
  display: flex;
  align-items: center;
  gap: 5px;
}

.live-recording-badge {
  display: inline-flex;
  min-height: 20px;
  align-items: center;
  gap: 4px;
  padding: 0 6px;
  border: 1px solid rgba(255, 93, 107, 0.28);
  border-radius: 4px;
  background: rgba(20, 8, 10, 0.72);
  color: #ff7f8b;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.04em;
  backdrop-filter: blur(8px);
}

.live-recording-badge i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 3px rgba(255, 93, 107, 0.12);
}

.media-button--recording {
  background: rgba(207, 63, 79, 0.22);
  color: #ff8691;
}

.live-ptz-panel {
  position: absolute;
  right: 10px;
  bottom: 50px;
  z-index: 6;
  width: 156px;
  padding: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: var(--radius-md);
  background: rgba(10, 12, 15, 0.88);
  color: #f4f6f8;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.25);
  backdrop-filter: blur(14px);
}

.live-ptz-pad {
  display: grid;
  grid-template-columns: repeat(3, 34px);
  grid-template-rows: repeat(3, 34px);
  justify-content: center;
  gap: 3px;
}

.live-ptz-pad > :nth-child(1) {
  grid-column: 2;
  grid-row: 1;
}

.live-ptz-pad > :nth-child(2) {
  grid-column: 1;
  grid-row: 2;
}

.live-ptz-pad__center {
  display: grid;
  grid-column: 2;
  grid-row: 2;
  color: rgba(255, 255, 255, 0.5);
  place-items: center;
}

.live-ptz-pad > :nth-child(4) {
  grid-column: 3;
  grid-row: 2;
}

.live-ptz-pad > :nth-child(5) {
  grid-column: 2;
  grid-row: 3;
}

.live-ptz-zoom {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin-top: 6px;
}

.live-ptz-zoom .media-button {
  justify-content: center;
}

.live-ptz-error {
  display: block;
  margin-top: 6px;
  color: #ff9da6;
  font-size: 7px;
  line-height: 1.35;
}

.live-tile__action-error {
  position: absolute;
  right: 10px;
  bottom: 50px;
  left: 10px;
  z-index: 5;
  padding: 7px 8px;
  border: 1px solid rgba(224, 106, 119, 0.24);
  border-radius: var(--radius-sm);
  background: rgba(20, 8, 10, 0.86);
  color: #ff9da6;
  font-size: 8px;
  line-height: 1.35;
  backdrop-filter: blur(10px);
}
</style>
