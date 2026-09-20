<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useRoute } from "vue-router"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import { browserMediaUrl } from "../api/media"
import {
  getCameraTimeline,
  resolveCameraPlayback,
  type PlaybackGap,
  type PlaybackResolve,
  type PlaybackTimeline,
  type TimelineEvent,
  type TimelineGap,
  type TimelineRecordingRange
} from "../api/playback"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type ZoomHours = 1 | 6 | 24

const auth = useAuthStore()
const route = useRoute()
const zoomOptions: ZoomHours[] = [1, 6, 24]
const stage = ref<HTMLElement | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const cameras = ref<CameraSummary[]>([])
const activeCameraId = ref<string | null>(null)
const cameraPanelOpen = ref(true)
const search = ref("")
const timeline = ref<PlaybackTimeline | null>(null)
const zoomHours = ref<ZoomHours>(24)
const selectedDate = ref(formatDateInput(new Date()))
const currentAt = ref(new Date())
const playbackAnchorMs = ref<number | null>(null)
const playbackResult = ref<PlaybackResolve | null>(null)
const playbackUrl = ref<string | null>(null)
const loadingCameras = ref(false)
const loadingTimeline = ref(false)
const resolving = ref(false)
const error = ref<string | null>(null)
const playing = ref(false)
const muted = ref(true)
const fullscreen = ref(false)

let resolveGeneration = 0
let timelineGeneration = 0
let pendingRetryTimer: number | null = null

const activeCamera = computed(() =>
  cameras.value.find((camera) => camera.id === activeCameraId.value) ?? null
)

const filteredCameras = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return cameras.value

  return cameras.value.filter((camera) =>
    [camera.name, camera.location, camera.adapter_type]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle))
  )
})

const timelineStartMs = computed(() =>
  timeline.value
    ? new Date(timeline.value.range.start_at).getTime()
    : rangeWindow()[0].getTime()
)

const timelineEndMs = computed(() =>
  timeline.value
    ? new Date(timeline.value.range.end_at).getTime()
    : rangeWindow()[1].getTime()
)

const timelineDurationMs = computed(() =>
  Math.max(1, timelineEndMs.value - timelineStartMs.value)
)

const playheadPercent = computed(() =>
  clampPercent(
    ((currentAt.value.getTime() - timelineStartMs.value) /
      timelineDurationMs.value) *
      100
  )
)

const ticks = computed(() => {
  const count = zoomHours.value === 24 ? 8 : 6
  return Array.from({ length: count + 1 }, (_, index) => {
    const ratio = index / count
    const time =
      timelineStartMs.value + timelineDurationMs.value * ratio
    return {
      left: ratio * 100,
      label: formatClock(new Date(time))
    }
  })
})

const gapResult = computed<PlaybackGap | null>(() =>
  playbackResult.value?.status === "gap"
    ? playbackResult.value
    : null
)

function formatDateInput(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function formatClock(date: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date)
}

function formatTimestamp(date: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date)
}

function localDayStart(): Date {
  const [year, month, day] = selectedDate.value
    .split("-")
    .map(Number)
  return new Date(year, month - 1, day, 0, 0, 0, 0)
}

function rangeWindow(): [Date, Date] {
  const dayStart = localDayStart()
  if (zoomHours.value === 24) {
    return [
      dayStart,
      new Date(dayStart.getTime() + 24 * 60 * 60 * 1000)
    ]
  }

  const dayEnd = dayStart.getTime() + 24 * 60 * 60 * 1000
  let center = currentAt.value.getTime()
  if (formatDateInput(currentAt.value) !== selectedDate.value) {
    center = dayStart.getTime() + 12 * 60 * 60 * 1000
  }

  const halfWindow = (zoomHours.value * 60 * 60 * 1000) / 2
  let start = center - halfWindow
  let end = center + halfWindow

  if (start < dayStart.getTime()) {
    start = dayStart.getTime()
    end = start + halfWindow * 2
  }
  if (end > dayEnd) {
    end = dayEnd
    start = end - halfWindow * 2
  }

  return [new Date(start), new Date(end)]
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function rangeStyle(
  item: TimelineRecordingRange | TimelineGap
): Record<string, string> {
  const start = new Date(item.start_at).getTime()
  const end = new Date(item.end_at).getTime()
  const left =
    ((start - timelineStartMs.value) / timelineDurationMs.value) * 100
  const width =
    ((end - start) / timelineDurationMs.value) * 100
  return {
    left: `${clampPercent(left)}%`,
    width: `${Math.max(0.15, Math.min(100, width))}%`
  }
}

function eventStyle(item: TimelineEvent): Record<string, string> {
  const at = new Date(item.start_at).getTime()
  return {
    left: `${clampPercent(
      ((at - timelineStartMs.value) / timelineDurationMs.value) * 100
    )}%`
  }
}

function eventTitle(item: TimelineEvent): string {
  const label = item.label ? ` · ${item.label}` : ""
  return `${item.category}${label} · ${formatTimestamp(
    new Date(item.start_at)
  )}`
}

async function refreshCameras(): Promise<void> {
  if (!auth.hasPermission("camera.view")) return

  loadingCameras.value = true
  error.value = null
  try {
    cameras.value = await listCameras()
    const validIds = new Set(cameras.value.map((camera) => camera.id))
    const routeCamera =
      typeof route.query.camera === "string"
        ? route.query.camera
        : null
    const routeAt =
      typeof route.query.at === "string"
        ? new Date(route.query.at)
        : null
    const hasRouteAt =
      routeAt !== null && !Number.isNaN(routeAt.getTime())

    if (routeCamera && validIds.has(routeCamera)) {
      activeCameraId.value = routeCamera
    } else if (
      !activeCameraId.value ||
      !validIds.has(activeCameraId.value)
    ) {
      activeCameraId.value = cameras.value[0]?.id ?? null
    }

    if (hasRouteAt && routeAt) {
      currentAt.value = routeAt
      selectedDate.value = formatDateInput(routeAt)
      zoomHours.value = 6
      await refreshTimeline(false)
      await resolveAt(routeAt, true)
    } else {
      await refreshTimeline(false)
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loadingCameras.value = false
  }
}

async function refreshTimeline(resolveCurrent = false): Promise<void> {
  const cameraId = activeCameraId.value
  if (!cameraId || !auth.hasPermission("recording.view")) {
    timeline.value = null
    return
  }

  const generation = ++timelineGeneration
  loadingTimeline.value = true
  error.value = null
  const [from, to] = rangeWindow()

  try {
    const value = await getCameraTimeline(cameraId, from, to)
    if (generation !== timelineGeneration) return
    timeline.value = value
    if (resolveCurrent) {
      await resolveAt(currentAt.value, false)
    }
  } catch (caught) {
    if (generation === timelineGeneration) {
      error.value = errorMessage(caught)
    }
  } finally {
    if (generation === timelineGeneration) {
      loadingTimeline.value = false
    }
  }
}

function clearPendingRetry(): void {
  if (pendingRetryTimer === null) return
  window.clearTimeout(pendingRetryTimer)
  pendingRetryTimer = null
}

async function resolveAt(
  at: Date,
  autoplay = true
): Promise<void> {
  clearPendingRetry()
  const cameraId = activeCameraId.value
  if (!cameraId) return

  const generation = ++resolveGeneration
  currentAt.value = new Date(at)
  resolving.value = true
  error.value = null
  playbackUrl.value = null
  playbackAnchorMs.value = null
  playing.value = false

  if (video.value) {
    video.value.pause()
    video.value.removeAttribute("src")
    video.value.load()
  }

  try {
    const result = await resolveCameraPlayback(cameraId, at)
    if (generation !== resolveGeneration) return
    playbackResult.value = result

    if (result.status === "pending") {
      const retryAt = new Date(at)
      pendingRetryTimer = window.setTimeout(() => {
        pendingRetryTimer = null
        if (
          generation === resolveGeneration &&
          activeCameraId.value === cameraId
        ) {
          void resolveAt(retryAt, autoplay)
        }
      }, Math.max(500, result.retry_after_ms))
      return
    }

    if (result.status !== "playable") return

    playbackAnchorMs.value = at.getTime()
    playbackUrl.value = browserMediaUrl(result.url)
    await nextTick()

    if (video.value) {
      video.value.load()
      if (autoplay) {
        await video.value.play().catch(() => undefined)
      }
    }
  } catch (caught) {
    if (generation === resolveGeneration) {
      error.value = errorMessage(caught)
      playbackResult.value = null
    }
  } finally {
    if (generation === resolveGeneration) {
      resolving.value = false
    }
  }
}

function selectCamera(cameraId: string): void {
  if (cameraId === activeCameraId.value) return
  clearPendingRetry()
  resolveGeneration += 1
  activeCameraId.value = cameraId
  playbackUrl.value = null
  playbackResult.value = null
  void refreshTimeline(false)
}

function handleDateChange(): void {
  const start = localDayStart()
  const now = new Date()
  currentAt.value =
    formatDateInput(now) === selectedDate.value
      ? now
      : new Date(start.getTime() + 12 * 60 * 60 * 1000)
  void refreshTimeline(false)
}

function setZoom(hours: ZoomHours): void {
  zoomHours.value = hours
  void refreshTimeline(false)
}

function handleTimelineClick(event: MouseEvent): void {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  if (!rect.width) return

  const ratio = clampPercent(
    ((event.clientX - rect.left) / rect.width) * 100
  ) / 100
  const at = new Date(
    timelineStartMs.value + timelineDurationMs.value * ratio
  )
  void resolveAt(at, true)
}

function jumpTo(value: string | null): void {
  if (!value) return
  const at = new Date(value)
  currentAt.value = at
  selectedDate.value = formatDateInput(at)
  void refreshTimeline(false).then(() => resolveAt(at, true))
}

function togglePlayback(): void {
  const element = video.value
  if (!element || !playbackUrl.value) {
    void resolveAt(currentAt.value, true)
    return
  }

  if (element.paused) {
    void element.play()
  } else {
    element.pause()
  }
}

function toggleMute(): void {
  muted.value = !muted.value
  if (video.value) video.value.muted = muted.value
}

function handleTimeUpdate(): void {
  if (!video.value || playbackAnchorMs.value === null) return
  currentAt.value = new Date(
    playbackAnchorMs.value + video.value.currentTime * 1000
  )
}

function handleEnded(): void {
  const next = new Date(currentAt.value.getTime() + 250)
  void resolveAt(next, true)
}

async function toggleFullscreen(): Promise<void> {
  if (!document.fullscreenElement) {
    await stage.value?.requestFullscreen?.()
  } else {
    await document.exitFullscreen()
  }
}

function handleFullscreenChange(): void {
  fullscreen.value = Boolean(document.fullscreenElement)
}

function handleRefreshEvent(): void {
  void refreshTimeline(false)
}

onMounted(() => {
  void refreshCameras()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
  document.addEventListener("fullscreenchange", handleFullscreenChange)
})

onBeforeUnmount(() => {
  clearPendingRetry()
  resolveGeneration += 1
  timelineGeneration += 1
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
  document.removeEventListener("fullscreenchange", handleFullscreenChange)
})
</script>

<template>
  <section class="playback-workspace">
    <aside
      v-if="cameraPanelOpen"
      class="live-camera-panel playback-camera-panel"
    >
      <div class="live-camera-panel__header">
        <div>
          <strong>Cameras</strong>
          <span>{{ cameras.length }} available</span>
        </div>
        <button
          class="icon-button topbar-icon-button"
          type="button"
          title="Refresh cameras"
          aria-label="Refresh cameras"
          :disabled="loadingCameras"
          @click="refreshCameras"
        >
          <UiIcon name="refresh" :size="16" />
        </button>
      </div>

      <label class="live-search">
        <UiIcon name="search" :size="15" />
        <input
          v-model="search"
          type="search"
          placeholder="Search cameras"
          aria-label="Search cameras"
        />
      </label>

      <div class="live-camera-list">
        <button
          v-for="camera in filteredCameras"
          :key="camera.id"
          class="live-camera-row"
          :class="{
            'live-camera-row--selected':
              activeCameraId === camera.id
          }"
          type="button"
          @click="selectCamera(camera.id)"
        >
          <span
            class="live-camera-row__status"
            :class="{
              'live-camera-row__status--enabled': camera.enabled
            }"
          />
          <span class="live-camera-row__copy">
            <strong>{{ camera.name }}</strong>
            <small>
              {{ camera.location || camera.adapter_type || "Camera" }}
            </small>
          </span>
          <span class="live-camera-row__check">
            <UiIcon
              v-if="activeCameraId === camera.id"
              name="chevron-right"
              :size="14"
            />
          </span>
        </button>

        <div
          v-if="!filteredCameras.length && !loadingCameras"
          class="live-camera-list__empty"
        >
          No cameras found.
        </div>
      </div>
    </aside>

    <div ref="stage" class="playback-stage">
      <header class="live-toolbar playback-toolbar">
        <div class="live-toolbar__left">
          <button
            class="media-button"
            type="button"
            :title="cameraPanelOpen ? 'Hide cameras' : 'Show cameras'"
            @click="cameraPanelOpen = !cameraPanelOpen"
          >
            <UiIcon name="panel" :size="16" />
          </button>
          <span class="live-toolbar__title">
            {{ activeCamera?.name || "Playback" }}
          </span>
        </div>

        <div class="playback-toolbar__center">
          <label class="playback-date-control">
            <UiIcon name="calendar" :size="14" />
            <input
              v-model="selectedDate"
              type="date"
              aria-label="Playback date"
              @change="handleDateChange"
            />
          </label>
        </div>

        <div class="live-toolbar__actions">
          <div class="playback-zoom-switcher">
            <button
              v-for="hours in zoomOptions"
              :key="hours"
              class="media-button media-button--text"
              :class="{ 'media-button--active': zoomHours === hours }"
              type="button"
              @click="setZoom(hours)"
            >
              {{ hours }}h
            </button>
          </div>

          <button
            class="media-button"
            type="button"
            :title="fullscreen ? 'Exit fullscreen' : 'Fullscreen playback'"
            @click="toggleFullscreen"
          >
            <UiIcon
              :name="fullscreen ? 'minimize' : 'maximize'"
              :size="16"
            />
          </button>
        </div>
      </header>

      <div class="playback-video-area">
        <video
          v-if="playbackUrl"
          ref="video"
          class="playback-video"
          :src="playbackUrl"
          autoplay
          playsinline
          :muted="muted"
          @play="playing = true"
          @pause="playing = false"
          @timeupdate="handleTimeUpdate"
          @ended="handleEnded"
        />

        <div
          v-if="!playbackUrl"
          class="playback-video-state"
        >
          <UiIcon
            :name="resolving ? 'refresh' : 'playback'"
            :size="32"
          />
          <strong v-if="resolving">Loading recording…</strong>
          <template v-else-if="playbackResult?.status === 'pending'">
            <strong>Restoring remote recording…</strong>
            <span>
              Copying this segment into the bounded local playback cache.
              Playback will start automatically when it is ready.
            </span>
            <button
              class="media-button media-button--text"
              type="button"
              @click="resolveAt(currentAt, true)"
            >
              <UiIcon name="refresh" :size="14" />
              Check now
            </button>
          </template>
          <template v-else-if="gapResult">
            <strong>No recording at this time</strong>
            <span>{{ gapResult.reason.replaceAll("_", " ") }}</span>
            <div class="playback-gap-actions">
              <button
                v-if="gapResult.previous_at"
                class="media-button media-button--text"
                type="button"
                @click="jumpTo(gapResult.previous_at)"
              >
                <UiIcon name="previous" :size="14" />
                Previous
              </button>
              <button
                v-if="gapResult.next_at"
                class="media-button media-button--text"
                type="button"
                @click="jumpTo(gapResult.next_at)"
              >
                Next
                <UiIcon name="next" :size="14" />
              </button>
            </div>
          </template>
          <template v-else>
            <strong>Select a point in the timeline</strong>
            <span>
              Choose a recording range or event marker to begin playback.
            </span>
          </template>
        </div>

        <div v-if="error" class="playback-error">
          {{ error }}
        </div>
      </div>

      <div class="playback-controls">
        <button
          class="media-button"
          type="button"
          :aria-label="playing ? 'Pause' : 'Play'"
          @click="togglePlayback"
        >
          <UiIcon :name="playing ? 'pause' : 'play'" :size="16" />
        </button>

        <button
          class="media-button"
          type="button"
          :aria-label="muted ? 'Unmute' : 'Mute'"
          @click="toggleMute"
        >
          <UiIcon
            :name="muted ? 'volume-off' : 'volume'"
            :size="16"
          />
        </button>

        <span class="playback-current-time">
          {{ formatTimestamp(currentAt) }}
        </span>

        <span
          v-if="playbackResult?.status === 'playable'"
          class="playback-codec"
        >
          {{ playbackResult.codec || "video" }}
        </span>
      </div>

      <div class="playback-timeline-shell">
        <div class="playback-timeline-legend">
          <span><i class="legend-dot legend-dot--local" /> Local</span>
          <span><i class="legend-dot legend-dot--remote" /> Remote</span>
          <span><i class="legend-dot legend-dot--event" /> Event</span>
          <span v-if="loadingTimeline">Updating…</span>
        </div>

        <div
          class="playback-timeline"
          role="slider"
          tabindex="0"
          aria-label="Recording timeline"
          @click="handleTimelineClick"
        >
          <div class="playback-timeline__ticks">
            <span
              v-for="tick in ticks"
              :key="`${tick.left}-${tick.label}`"
              class="playback-tick"
              :style="{ left: `${tick.left}%` }"
            >
              <i />
              <small>{{ tick.label }}</small>
            </span>
          </div>

          <div class="playback-timeline__lane">
            <span
              v-for="gap in timeline?.gaps || []"
              :key="`gap-${gap.start_at}-${gap.end_at}`"
              class="timeline-gap-range"
              :class="`timeline-gap-range--${gap.reason}`"
              :style="rangeStyle(gap)"
              :title="gap.reason.replaceAll('_', ' ')"
            />

            <button
              v-for="range in timeline?.recording_ranges || []"
              :key="`recording-${range.start_at}-${range.end_at}`"
              class="timeline-recording-range"
              :class="`timeline-recording-range--${range.availability}`"
              :style="rangeStyle(range)"
              type="button"
              :title="`${range.availability} · ${formatTimestamp(
                new Date(range.start_at)
              )}`"
              tabindex="-1"
            />

            <button
              v-for="item in timeline?.events || []"
              :key="item.id"
              class="timeline-event-marker"
              :style="eventStyle(item)"
              type="button"
              :title="eventTitle(item)"
              tabindex="-1"
              @click.stop="resolveAt(new Date(item.start_at), true)"
            >
              <span />
            </button>

            <span
              class="playback-playhead"
              :style="{ left: `${playheadPercent}%` }"
            >
              <i />
            </span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
