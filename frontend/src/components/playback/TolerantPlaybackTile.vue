<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch
} from "vue"
import { useI18n } from "vue-i18n"

import { errorMessage } from "../../api/client"
import { browserMediaUrl } from "../../api/media"
import {
  resolveCameraPlayback,
  type PlaybackResolve
} from "../../api/playback"
import { PlaybackDriftController } from "../../playback/driftController"

type SyncTileStateName =
  | "resolving"
  | "ready"
  | "buffering"
  | "pending"
  | "gap"
  | "unavailable"

interface SyncTileState {
  cameraId: string
  state: SyncTileStateName
  blocksStrict: boolean
}

const { t } = useI18n({
  useScope: "global"
})

const props = defineProps<{
  cameraId: string
  cameraName: string
  masterTimeMs: number
  playing: boolean
  playbackRate: number
  muted: boolean
  seekGeneration: number
  focused: boolean
}>()

const emit = defineEmits<{
  "sync-state": [state: SyncTileState]
}>()

const video = ref<HTMLVideoElement | null>(null)
const playback = ref<PlaybackResolve | null>(null)
const mediaUrl = ref<string | null>(null)
const loading = ref(false)
const buffering = ref(false)
const mediaReady = ref(false)
const failure = ref<string | null>(null)

const driftController = new PlaybackDriftController()

let mediaAnchorMs: number | null = null
let resolveGeneration = 0
let retryTimer: number | null = null
let gapWakeAtMs: number | null = null

const syncState = computed<SyncTileState>(() => {
  if (failure.value) {
    return {
      cameraId: props.cameraId,
      state: "unavailable",
      blocksStrict: true
    }
  }

  if (loading.value) {
    return {
      cameraId: props.cameraId,
      state: "resolving",
      blocksStrict: true
    }
  }

  if (playback.value?.status === "pending") {
    return {
      cameraId: props.cameraId,
      state: "pending",
      blocksStrict: true
    }
  }

  if (playback.value?.status === "gap") {
    return {
      cameraId: props.cameraId,
      state: "gap",
      blocksStrict: false
    }
  }

  if (buffering.value) {
    return {
      cameraId: props.cameraId,
      state: "buffering",
      blocksStrict: true
    }
  }

  if (
    playback.value?.status === "playable" &&
    mediaReady.value
  ) {
    return {
      cameraId: props.cameraId,
      state: "ready",
      blocksStrict: false
    }
  }

  return {
    cameraId: props.cameraId,
    state: "resolving",
    blocksStrict: true
  }
})

const statusLabel = computed(() => {
  if (failure.value) return t("playback.tile.unavailable")
  if (loading.value) return t("playback.tile.loading")
  if (playback.value?.status === "pending") {
    return t("playback.tile.restoring")
  }
  if (playback.value?.status === "gap") {
    const key = `playback.reasonMap.${playback.value.reason.toLowerCase()}`
    return t(key, playback.value.reason.replaceAll("_", " "))
  }
  if (buffering.value) return t("playback.tile.buffering")
  if (playback.value?.status === "playable") {
    return props.playing
      ? t("playback.tile.playing")
      : t("playback.tile.ready")
  }
  return t("playback.tile.waiting")
})

function clearRetry(): void {
  if (retryTimer === null) return
  window.clearTimeout(retryTimer)
  retryTimer = null
}

function resetDrift(): void {
  driftController.reset(
    performance.now()
  )
  if (video.value) {
    video.value.playbackRate =
      props.playbackRate
  }
}

function clearMedia(): void {
  const element = video.value
  if (element) {
    element.pause()
    element.removeAttribute("src")
    element.load()
  }
  mediaUrl.value = null
  mediaAnchorMs = null
  buffering.value = false
  mediaReady.value = false
  resetDrift()
}

function clampMediaTime(
  element: HTMLVideoElement,
  seconds: number
): number {
  const target = Math.max(0, seconds)
  if (
    Number.isFinite(element.duration) &&
    element.duration > 0
  ) {
    return Math.min(
      target,
      Math.max(
        0,
        element.duration - 0.01
      )
    )
  }
  return target
}

function alignToMaster(): void {
  const element = video.value
  if (
    !element ||
    mediaAnchorMs === null
  ) {
    return
  }

  const targetSeconds =
    (props.masterTimeMs -
      mediaAnchorMs) /
    1000
  if (!Number.isFinite(targetSeconds)) {
    return
  }

  element.currentTime = clampMediaTime(
    element,
    targetSeconds
  )
  element.playbackRate =
    props.playbackRate
  driftController.reset(
    performance.now()
  )
}

function scheduleRetry(delayMs: number): void {
  clearRetry()
  retryTimer = window.setTimeout(
    () => {
      retryTimer = null
      void resolveAtMaster()
    },
    Math.max(500, delayMs)
  )
}

async function resolveAtMaster(): Promise<void> {
  const generation = ++resolveGeneration
  clearRetry()
  clearMedia()
  playback.value = null
  loading.value = true
  failure.value = null
  gapWakeAtMs = null

  try {
    const result = await resolveCameraPlayback(
      props.cameraId,
      new Date(props.masterTimeMs)
    )
    if (generation !== resolveGeneration) {
      return
    }

    playback.value = result

    if (result.status === "pending") {
      scheduleRetry(
        result.retry_after_ms
      )
      return
    }

    if (result.status === "gap") {
      gapWakeAtMs = result.next_at
        ? new Date(
            result.next_at
          ).getTime()
        : null
      return
    }

    mediaAnchorMs =
      new Date(
        result.segment_start_at
      ).getTime() +
      result.offset_ms
    mediaUrl.value = browserMediaUrl(
      result.url
    )
    await nextTick()

    const element = video.value
    if (!element) return

    element.muted = props.muted
    element.playbackRate =
      props.playbackRate
    element.load()

    if (
      element.readyState >=
      element.HAVE_FUTURE_DATA
    ) {
      alignToMaster()
      if (props.playing) {
        await element.play().catch(
          () => undefined
        )
      }
    }
  } catch (caught) {
    if (generation === resolveGeneration) {
      failure.value = errorMessage(
        caught
      )
      playback.value = null
    }
  } finally {
    if (generation === resolveGeneration) {
      loading.value = false
    }
  }
}

function handleCanPlay(): void {
  buffering.value = false
  mediaReady.value = true
  alignToMaster()
  const element = video.value
  if (
    props.playing &&
    element
  ) {
    void element.play().catch(
      () => undefined
    )
  }
}

function handleWaiting(): void {
  buffering.value = true
  mediaReady.value = false
}

function handlePlaying(): void {
  buffering.value = false
  mediaReady.value = true
}

function handleEnded(): void {
  void resolveAtMaster()
}

function handleTimeUpdate(): void {
  const element = video.value
  if (
    !element ||
    mediaAnchorMs === null ||
    !props.playing ||
    element.paused ||
    element.seeking
  ) {
    return
  }

  const mediaTimeMs =
    mediaAnchorMs +
    element.currentTime * 1000
  const driftMs =
    mediaTimeMs -
    props.masterTimeMs
  const action = driftController.evaluate(
    driftMs,
    props.playbackRate,
    performance.now()
  )

  if (action.kind === "rate") {
    if (
      Math.abs(
        element.playbackRate -
          action.playbackRate
      ) > 0.001
    ) {
      element.playbackRate =
        action.playbackRate
    }
    return
  }

  if (action.kind !== "hard_seek") {
    return
  }

  element.playbackRate =
    props.playbackRate
  const targetSeconds =
    (props.masterTimeMs -
      mediaAnchorMs) /
    1000
  element.currentTime = clampMediaTime(
    element,
    targetSeconds
  )
}

watch(
  syncState,
  (state) => {
    emit("sync-state", state)
  },
  { immediate: true }
)

watch(
  () => props.playing,
  (playing) => {
    const element = video.value
    if (!element) return

    if (!playing) {
      element.pause()
      resetDrift()
      return
    }

    alignToMaster()
    if (
      element.readyState >=
      element.HAVE_FUTURE_DATA
    ) {
      void element.play().catch(
        () => undefined
      )
    }
  }
)

watch(
  () => props.playbackRate,
  () => {
    resetDrift()
  }
)

watch(
  () => props.muted,
  (muted) => {
    if (video.value) {
      video.value.muted = muted
    }
  }
)

watch(
  () => props.seekGeneration,
  () => {
    void resolveAtMaster()
  }
)

watch(
  () => props.cameraId,
  () => {
    void resolveAtMaster()
  }
)

watch(
  () => props.masterTimeMs,
  (timeMs) => {
    if (
      playback.value?.status === "gap" &&
      gapWakeAtMs !== null &&
      timeMs >= gapWakeAtMs
    ) {
      void resolveAtMaster()
    }
  }
)

onMounted(() => {
  void resolveAtMaster()
})

onBeforeUnmount(() => {
  resolveGeneration += 1
  clearRetry()
  clearMedia()
})
</script>

<template>
  <article
    class="tolerant-playback-tile"
    :class="{
      'tolerant-playback-tile--focused':
        focused
    }"
  >
    <header>
      <div>
        <strong>{{ cameraName }}</strong>
        <span v-if="focused">{{ t("playback.tile.primary") }}</span>
      </div>
      <span class="tolerant-playback-tile__status">
        {{ statusLabel }}
      </span>
    </header>

    <div class="tolerant-playback-tile__media">
      <video
        v-if="mediaUrl"
        ref="video"
        :src="mediaUrl"
        playsinline
        preload="auto"
        :muted="muted"
        @canplay="handleCanPlay"
        @playing="handlePlaying"
        @waiting="handleWaiting"
        @stalled="handleWaiting"
        @timeupdate="handleTimeUpdate"
        @ended="handleEnded"
      />

      <div
        v-if="
          !mediaUrl ||
          loading ||
          buffering
        "
        class="tolerant-playback-tile__overlay"
      >
        <strong v-if="loading">
          {{ t("playback.tile.loadingRecording") }}
        </strong>
        <strong
          v-else-if="
            playback?.status === 'pending'
          "
        >
          {{ t("playback.tile.restoringRemote") }}
        </strong>
        <strong
          v-else-if="
            playback?.status === 'gap'
          "
        >
          {{ t("playback.tile.noRecording") }}
        </strong>
        <strong v-else-if="buffering">
          {{ t("playback.tile.bufferingEllipsis") }}
        </strong>
        <strong v-else-if="failure">
          {{ t("playback.tile.channelUnavailable") }}
        </strong>
        <strong v-else>
          {{ t("playback.tile.waitingForMedia") }}
        </strong>

        <span
          v-if="
            playback?.status === 'gap'
          "
        >
          {{
            statusLabel
          }}
        </span>
        <span v-else-if="failure">
          {{ failure }}
        </span>
      </div>
    </div>
  </article>
</template>
