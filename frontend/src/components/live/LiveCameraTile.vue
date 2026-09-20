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

import type { CameraSummary } from "../../api/cameras"
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

let hls: Hls | null = null
let generation = 0
let tokenRefreshTimer: number | null = null
let recordingErrorTimer: number | null = null

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

function destroyPlayer(): void {
  generation += 1
  clearTokenRefresh()
  hls?.destroy()
  hls = null
  playing.value = false

  if (video.value) {
    video.value.pause()
    video.value.removeAttribute("src")
    video.value.load()
  }
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
      props.quality
    )
    if (generation !== currentGeneration) return
    descriptor.value = stream
    await attachStream(stream)
    if (generation === currentGeneration) {
      scheduleTokenRefresh(stream.expires_at)
    }
  } catch (caught) {
    if (generation !== currentGeneration) return
    error.value = errorMessage(caught)
  } finally {
    if (generation === currentGeneration) loading.value = false
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

function handleVideoError(): void {
  if (!loading.value) {
    error.value = "Live stream playback failed."
  }
}

onMounted(() => {
  void loadStream()
  void loadRecordingState()
})

watch(
  () => [props.camera.id, props.quality],
  () => {
    destroyPlayer()
    recordingTrigger.value = null
    clearRecordingError()
    void loadStream()
    void loadRecordingState()
  }
)

onBeforeUnmount(() => {
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
      @playing="playing = true"
      @waiting="playing = false"
      @error="handleVideoError"
    />

    <div
      v-if="loading || error"
      class="live-tile__state"
    >
      <UiIcon
        :name="error ? 'warning' : 'cameras'"
        :size="26"
      />
      <strong>{{ error ? "Stream unavailable" : "Connecting…" }}</strong>
      <span>{{ error || "Starting secure live session" }}</span>
      <button
        v-if="error"
        class="media-button media-button--text"
        type="button"
        @click.stop="loadStream"
      >
        <UiIcon name="refresh" :size="14" />
        Retry
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
