<script setup lang="ts">
import Hls from "hls.js"
import {
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
  getCameraLiveStream,
  type CameraLiveStream,
  type LiveQuality
} from "../../api/live"
import UiIcon from "../ui/UiIcon.vue"

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

let hls: Hls | null = null
let generation = 0
let tokenRefreshTimer: number | null = null

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
})

watch(
  () => [props.camera.id, props.quality],
  () => {
    destroyPlayer()
    void loadStream()
  }
)

onBeforeUnmount(destroyPlayer)
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

      <span v-if="descriptor" class="live-quality-badge">
        {{
          descriptor.purpose === "LIVE_LOW"
            ? "SD"
            : descriptor.purpose === "RECORD"
              ? "REC"
              : "HD"
        }}
      </span>
    </header>

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
