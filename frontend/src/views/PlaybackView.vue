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
import {
  createExport,
  createExportShare,
  deleteExport,
  exportDownloadUrl,
  getExport,
  listExportShares,
  listExports,
  revokeExportShare,
  type ExportJob,
  type ExportShare,
  type ExportShareCreated
} from "../api/exports"
import { browserMediaUrl } from "../api/media"
import {
  createRecordingProtection,
  deleteRecordingProtection,
  listRecordingProtections,
  updateRecordingProtection,
  type RecordingProtection
} from "../api/recordings"
import {
  getCameraTimeline,
  resolveCameraPlayback,
  type PlaybackGap,
  type PlaybackResolve,
  type PlaybackTimeline,
  type TimelineDetailLevel
} from "../api/playback"
import PlaybackTimelineCanvas from "../components/playback/PlaybackTimelineCanvas.vue"
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
const timelineCenterMs = ref<number | null>(null)
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
const actionPanelOpen = ref(false)
const actionMode = ref<"protect" | "export">("export")
const actionStart = ref("")
const actionEnd = ref("")
const editingProtectionId = ref<string | null>(null)
const protectionReason = ref("Important footage")
const protectionExpiresAt = ref("")
const exportCodecMode = ref<"auto" | "copy" | "h264">("auto")
const exportGapPolicy = ref<"skip" | "fail">("skip")
const actionSaving = ref(false)
const protections = ref<RecordingProtection[]>([])
const exportJobs = ref<ExportJob[]>([])
const activeExport = ref<ExportJob | null>(null)
const shareExport = ref<ExportJob | null>(null)
const sharePassword = ref("")
const shareExpiresHours = ref(24)
const shareMaxDownloads = ref(0)
const shareSaving = ref(false)
const shareCopied = ref(false)
const createdShare = ref<ExportShareCreated | null>(null)
const exportShares = ref<ExportShare[]>([])

let resolveGeneration = 0
let timelineGeneration = 0
let pendingRetryTimer: number | null = null
let exportPollTimer: number | null = null

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

const cameraProtections = computed(() =>
  protections.value
    .filter((item) => item.camera_id === activeCameraId.value)
    .slice(0, 8)
)

const timelineProtections = computed(() => {
  const now = Date.now()
  return protections.value.filter((item) => {
    if (item.camera_id !== activeCameraId.value) return false
    if (
      item.expires_at &&
      new Date(item.expires_at).getTime() <= now
    ) {
      return false
    }
    return (
      new Date(item.ended_at).getTime() > timelineStartMs.value &&
      new Date(item.started_at).getTime() < timelineEndMs.value
    )
  })
})

const cameraExports = computed(() =>
  exportJobs.value
    .filter((item) => item.camera_id === activeCameraId.value)
    .slice(0, 8)
)

const gapResult = computed<PlaybackGap | null>(() =>
  playbackResult.value?.status === "gap"
    ? playbackResult.value
    : null
)

function toLocalDateTimeInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset)
    .toISOString()
    .slice(0, 16)
}

function fromLocalDateTimeInput(value: string): Date {
  return new Date(value)
}

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
  const duration =
    zoomHours.value * 60 * 60 * 1000

  if (
    zoomHours.value === 24 &&
    timelineCenterMs.value === null
  ) {
    return [
      dayStart,
      new Date(dayStart.getTime() + duration)
    ]
  }

  let center =
    timelineCenterMs.value ??
    currentAt.value.getTime()
  if (
    timelineCenterMs.value === null &&
    formatDateInput(currentAt.value) !==
      selectedDate.value
  ) {
    center =
      dayStart.getTime() +
      12 * 60 * 60 * 1000
  }

  return [
    new Date(center - duration / 2),
    new Date(center + duration / 2)
  ]
}

function clampRatio(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function clearExportPoll(): void {
  if (exportPollTimer === null) return
  window.clearTimeout(exportPollTimer)
  exportPollTimer = null
}

async function loadPlaybackActions(): Promise<void> {
  const cameraId = activeCameraId.value
  if (!cameraId) {
    protections.value = []
    exportJobs.value = []
    return
  }

  const tasks: Promise<void>[] = []
  if (auth.hasPermission("recording.view")) {
    tasks.push(
      listRecordingProtections(cameraId)
        .then((items) => {
          protections.value = items
        })
        .catch(() => {
          protections.value = []
        })
    )
  }
  if (auth.hasPermission("recording.export")) {
    tasks.push(
      listExports()
        .then((page) => {
          exportJobs.value = page.items
        })
        .catch(() => {
          exportJobs.value = []
        })
    )
  }
  await Promise.all(tasks)
}

async function refreshCameras(): Promise<void> {
  if (!auth.hasPermission("camera.view")) return

  loadingCameras.value = true
  error.value = null
  try {
    cameras.value = await listCameras({
      includeRetired: true
    })
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
      timelineCenterMs.value = routeAt.getTime()
      selectedDate.value = formatDateInput(routeAt)
      zoomHours.value = 6
      await refreshTimeline(false)
      await resolveAt(routeAt, true)
    } else {
      await refreshTimeline(false)
    }
    await loadPlaybackActions()
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
  const detail: TimelineDetailLevel =
    zoomHours.value === 24
      ? "day"
      : zoomHours.value === 6
        ? "hour"
        : "minute"

  try {
    const value = await getCameraTimeline(
      cameraId,
      from,
      to,
      detail
    )
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
  clearExportPoll()
  resolveGeneration += 1
  activeCameraId.value = cameraId
  playbackUrl.value = null
  playbackResult.value = null
  actionPanelOpen.value = false
  void refreshTimeline(false)
  void loadPlaybackActions()
}

function handleDateChange(): void {
  const start = localDayStart()
  const now = new Date()
  currentAt.value =
    formatDateInput(now) === selectedDate.value
      ? now
      : new Date(start.getTime() + 12 * 60 * 60 * 1000)
  timelineCenterMs.value = null
  void refreshTimeline(false)
}

function setZoom(hours: ZoomHours): void {
  zoomHours.value = hours
  timelineCenterMs.value = currentAt.value.getTime()
  selectedDate.value = formatDateInput(
    currentAt.value
  )
  void refreshTimeline(false)
}

function handleTimelineSeek(at: Date): void {
  void resolveAt(at, true)
}

function handleTimelinePan(deltaMs: number): void {
  const [from, to] = rangeWindow()
  const center =
    (from.getTime() + to.getTime()) / 2 +
    deltaMs

  timelineCenterMs.value = center
  selectedDate.value = formatDateInput(
    new Date(center)
  )
  void refreshTimeline(false)
}

function handleTimelineZoom(payload: {
  direction: "in" | "out"
  anchor: Date
}): void {
  const ordered: ZoomHours[] = [1, 6, 24]
  const index = ordered.indexOf(zoomHours.value)
  const nextIndex =
    payload.direction === "in"
      ? Math.max(0, index - 1)
      : Math.min(ordered.length - 1, index + 1)
  const nextZoom = ordered[nextIndex]
  if (nextZoom === zoomHours.value) return

  const [from, to] = rangeWindow()
  const duration = Math.max(
    1,
    to.getTime() - from.getTime()
  )
  const anchorMs = payload.anchor.getTime()
  const ratio = clampRatio(
    (anchorMs - from.getTime()) / duration
  )
  const nextDuration =
    nextZoom * 60 * 60 * 1000
  const nextStart =
    anchorMs - ratio * nextDuration

  zoomHours.value = nextZoom
  timelineCenterMs.value =
    nextStart + nextDuration / 2
  selectedDate.value = formatDateInput(
    payload.anchor
  )
  void refreshTimeline(false)
}

function jumpTo(value: string | null): void {
  if (!value) return
  const at = new Date(value)
  currentAt.value = at
  timelineCenterMs.value = at.getTime()
  selectedDate.value = formatDateInput(at)
  void refreshTimeline(false).then(() => resolveAt(at, true))
}

function openActionPanel(mode: "protect" | "export"): void {
  actionMode.value = mode
  editingProtectionId.value = null
  const center = currentAt.value.getTime()
  actionStart.value = toLocalDateTimeInput(
    new Date(center - 30_000)
  )
  actionEnd.value = toLocalDateTimeInput(
    new Date(center + 30_000)
  )
  protectionReason.value = "Important footage"
  protectionExpiresAt.value = ""
  exportCodecMode.value = "auto"
  exportGapPolicy.value = "skip"
  actionPanelOpen.value = true
}

function openProtectionFromTimeline(
  item: RecordingProtection
): void {
  if (!auth.hasPermission("recording.protect")) return
  editProtection(item)
}

function editProtection(item: RecordingProtection): void {
  actionMode.value = "protect"
  editingProtectionId.value = item.id
  actionStart.value = toLocalDateTimeInput(
    new Date(item.started_at)
  )
  actionEnd.value = toLocalDateTimeInput(
    new Date(item.ended_at)
  )
  protectionReason.value = item.reason
  protectionExpiresAt.value = item.expires_at
    ? toLocalDateTimeInput(new Date(item.expires_at))
    : ""
  actionPanelOpen.value = true
}

function actionRange(): [Date, Date] {
  const start = fromLocalDateTimeInput(actionStart.value)
  const end = fromLocalDateTimeInput(actionEnd.value)
  if (
    Number.isNaN(start.getTime()) ||
    Number.isNaN(end.getTime()) ||
    end <= start
  ) {
    throw new Error("Clip end must be after clip start.")
  }
  return [start, end]
}

async function saveProtection(): Promise<void> {
  const cameraId = activeCameraId.value
  if (!cameraId) return
  actionSaving.value = true
  error.value = null
  try {
    const [start, end] = actionRange()
    const expiresAt = protectionExpiresAt.value
      ? fromLocalDateTimeInput(
          protectionExpiresAt.value
        ).toISOString()
      : null
    const body = {
      started_at: start.toISOString(),
      ended_at: end.toISOString(),
      reason: protectionReason.value.trim(),
      expires_at: expiresAt
    }
    if (editingProtectionId.value) {
      await updateRecordingProtection(
        editingProtectionId.value,
        body
      )
    } else {
      await createRecordingProtection(
        cameraId,
        body
      )
    }
    await loadPlaybackActions()
    editingProtectionId.value = null
    actionPanelOpen.value = false
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    actionSaving.value = false
  }
}

function scheduleExportPoll(exportId: string): void {
  clearExportPoll()
  exportPollTimer = window.setTimeout(async () => {
    exportPollTimer = null
    try {
      const job = await getExport(exportId)
      activeExport.value = job
      exportJobs.value = [
        job,
        ...exportJobs.value.filter((item) => item.id !== job.id)
      ]
      if (
        !["COMPLETED", "FAILED", "CANCELLED", "EXPIRED"].includes(
          job.state.toUpperCase()
        )
      ) {
        scheduleExportPoll(exportId)
      }
    } catch (caught) {
      error.value = errorMessage(caught)
    }
  }, 2000)
}

async function saveExport(): Promise<void> {
  const cameraId = activeCameraId.value
  if (!cameraId) return
  actionSaving.value = true
  error.value = null
  try {
    const [start, end] = actionRange()
    const job = await createExport({
      camera_id: cameraId,
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      format: "mp4",
      codec_mode: exportCodecMode.value,
      gap_policy: exportGapPolicy.value
    })
    activeExport.value = job
    exportJobs.value = [
      job,
      ...exportJobs.value.filter((item) => item.id !== job.id)
    ]
    actionPanelOpen.value = false
    scheduleExportPoll(job.id)
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    actionSaving.value = false
  }
}

async function removeProtection(
  item: RecordingProtection
): Promise<void> {
  if (
    !window.confirm(
      `Remove protection “${item.reason}”? The recording becomes eligible for normal retention again.`
    )
  ) {
    return
  }
  try {
    await deleteRecordingProtection(item.id)
    protections.value = protections.value.filter(
      (current) => current.id !== item.id
    )
    if (editingProtectionId.value === item.id) {
      editingProtectionId.value = null
      actionPanelOpen.value = false
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function openShare(item: ExportJob): Promise<void> {
  shareExport.value = item
  sharePassword.value = ""
  shareExpiresHours.value = 24
  shareMaxDownloads.value = 0
  shareCopied.value = false
  createdShare.value = null
  error.value = null
  try {
    exportShares.value = await listExportShares(item.id)
  } catch (caught) {
    error.value = errorMessage(caught)
    exportShares.value = []
  }
}

function closeShare(): void {
  shareExport.value = null
  createdShare.value = null
  exportShares.value = []
  shareCopied.value = false
}

async function saveShare(): Promise<void> {
  if (!shareExport.value) return
  shareSaving.value = true
  error.value = null
  try {
    const created = await createExportShare(
      shareExport.value.id,
      {
        password: sharePassword.value || null,
        expires_in_hours: Number(shareExpiresHours.value),
        max_downloads:
          Number(shareMaxDownloads.value) > 0
            ? Number(shareMaxDownloads.value)
            : null
      }
    )
    createdShare.value = created
    exportShares.value = [
      created,
      ...exportShares.value.filter(
        (item) => item.id !== created.id
      )
    ]
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    shareSaving.value = false
  }
}

function shareUrl(item: ExportShareCreated): string {
  return new URL(
    item.download_path,
    window.location.origin
  ).toString()
}

async function copyShareLink(): Promise<void> {
  if (!createdShare.value) return
  try {
    await navigator.clipboard.writeText(
      shareUrl(createdShare.value)
    )
    shareCopied.value = true
  } catch {
    shareCopied.value = false
  }
}

async function revokeShare(item: ExportShare): Promise<void> {
  if (!shareExport.value || item.revoked_at) return
  try {
    await revokeExportShare(
      shareExport.value.id,
      item.id
    )
    exportShares.value = exportShares.value.map(
      (current) =>
        current.id === item.id
          ? {
              ...current,
              revoked_at: new Date().toISOString()
            }
          : current
    )
    if (createdShare.value?.id === item.id) {
      createdShare.value = null
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function removeExport(item: ExportJob): Promise<void> {
  if (!window.confirm("Delete this export?")) return
  try {
    if (activeExport.value?.id === item.id) clearExportPoll()
    await deleteExport(item.id)
    exportJobs.value = exportJobs.value.filter(
      (current) => current.id !== item.id
    )
    if (activeExport.value?.id === item.id) {
      activeExport.value = null
    }
    if (shareExport.value?.id === item.id) {
      closeShare()
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function exportStateClass(state: string): string {
  const normalized = state.toUpperCase()
  if (normalized === "COMPLETED") return "status-pill--ok"
  if (normalized === "FAILED") return "status-pill--error"
  return "status-pill--muted"
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
  void loadPlaybackActions()
}

onMounted(() => {
  void refreshCameras()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
  document.addEventListener("fullscreenchange", handleFullscreenChange)
})

onBeforeUnmount(() => {
  clearPendingRetry()
  clearExportPoll()
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

        <div class="playback-action-buttons">
          <button
            v-if="auth.hasPermission('recording.protect')"
            class="media-button media-button--text"
            type="button"
            @click="openActionPanel('protect')"
          >
            <UiIcon name="shield" :size="14" />
            Protect
          </button>
          <button
            v-if="auth.hasPermission('recording.export')"
            class="media-button media-button--text"
            type="button"
            @click="openActionPanel('export')"
          >
            <UiIcon name="export" :size="14" />
            Export
          </button>
        </div>

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
          <span
            v-if="auth.hasPermission('recording.protect')"
          >
            <i class="legend-dot legend-dot--protected" /> Protected
          </span>
          <span v-if="loadingTimeline">Updating…</span>
        </div>

        <PlaybackTimelineCanvas
          :timeline="timeline"
          :protections="timelineProtections"
          :current-at="currentAt"
          :zoom-hours="zoomHours"
          :can-protect="
            auth.hasPermission('recording.protect')
          "
          @seek="handleTimelineSeek"
          @pan="handleTimelinePan"
          @zoom="handleTimelineZoom"
          @protect="openProtectionFromTimeline"
        />
      </div>

      <aside
        v-if="actionPanelOpen"
        class="playback-action-panel"
      >
        <header>
          <div>
            <strong>
              {{
                actionMode === "protect"
                  ? editingProtectionId
                    ? "Edit protection"
                    : "Protect recording"
                  : "Export clip"
              }}
            </strong>
            <span>{{ activeCamera?.name || "Camera" }}</span>
          </div>
          <button
            class="icon-button"
            type="button"
            title="Close"
            @click="actionPanelOpen = false"
          >
            <UiIcon name="close" :size="15" />
          </button>
        </header>

        <form
          class="playback-action-form"
          @submit.prevent="
            actionMode === 'protect'
              ? saveProtection()
              : saveExport()
          "
        >
          <label>
            <span>Start</span>
            <input
              v-model="actionStart"
              type="datetime-local"
              step="1"
              required
            />
          </label>
          <label>
            <span>End</span>
            <input
              v-model="actionEnd"
              type="datetime-local"
              step="1"
              required
            />
          </label>

          <template v-if="actionMode === 'protect'">
            <label>
              <span>Reason</span>
              <input
                v-model="protectionReason"
                required
                maxlength="1024"
              />
            </label>
            <label>
              <span>Expires at</span>
              <input
                v-model="protectionExpiresAt"
                type="datetime-local"
                step="60"
              />
              <small>Leave blank to protect indefinitely.</small>
            </label>
          </template>

          <template v-else>
            <label>
              <span>Codec</span>
              <select v-model="exportCodecMode">
                <option value="auto">Auto</option>
                <option value="copy">Copy when possible</option>
                <option value="h264">Transcode H.264</option>
              </select>
            </label>
            <label>
              <span>Gaps</span>
              <select v-model="exportGapPolicy">
                <option value="skip">Skip gaps</option>
                <option value="fail">Fail if range has gaps</option>
              </select>
            </label>
          </template>

          <div class="playback-action-form__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="actionPanelOpen = false"
            >
              Cancel
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="actionSaving"
            >
              {{
                actionSaving
                  ? "Saving…"
                  : actionMode === "protect"
                    ? editingProtectionId
                      ? "Save protection"
                      : "Protect range"
                    : "Create export"
              }}
            </button>
          </div>
        </form>

        <section
          v-if="actionMode === 'protect' && cameraProtections.length"
          class="playback-action-history"
        >
          <h3>Protected ranges</h3>
          <article
            v-for="item in cameraProtections"
            :key="item.id"
          >
            <div>
              <strong>{{ item.reason }}</strong>
              <span>
                {{ formatTimestamp(new Date(item.started_at)) }}
                →
                {{ formatTimestamp(new Date(item.ended_at)) }}
              </span>
              <span v-if="item.expires_at">
                Expires {{ formatTimestamp(new Date(item.expires_at)) }}
              </span>
            </div>
            <button
              class="icon-button"
              type="button"
              title="Edit protection"
              @click="editProtection(item)"
            >
              <UiIcon name="shield" :size="13" />
            </button>
            <button
              class="icon-button icon-button--danger"
              type="button"
              title="Remove protection"
              @click="removeProtection(item)"
            >
              <UiIcon name="trash" :size="13" />
            </button>
          </article>
        </section>

        <section
          v-if="actionMode === 'export' && cameraExports.length"
          class="playback-action-history"
        >
          <h3>Recent exports</h3>
          <article
            v-for="item in cameraExports"
            :key="item.id"
          >
            <div>
              <strong>
                {{ formatTimestamp(new Date(item.start_at)) }}
              </strong>
              <span>
                {{ Math.round(item.requested_duration_ms / 1000) }}s ·
                {{ item.codec_mode }}
              </span>
            </div>
            <span
              class="status-pill"
              :class="exportStateClass(item.state)"
            >
              {{ item.state }}
            </span>
            <button
              v-if="item.state === 'COMPLETED'"
              class="icon-button"
              type="button"
              title="Manage share link"
              @click="openShare(item)"
            >
              <UiIcon name="share" :size="13" />
            </button>
            <a
              v-if="item.state === 'COMPLETED'"
              class="icon-button"
              :href="exportDownloadUrl(item.id)"
              title="Download MP4"
            >
              <UiIcon name="download" :size="13" />
            </a>
            <button
              class="icon-button icon-button--danger"
              type="button"
              title="Delete export"
              @click="removeExport(item)"
            >
              <UiIcon name="trash" :size="13" />
            </button>
          </article>
        </section>

        <section
          v-if="
            actionMode === 'export' &&
            shareExport
          "
          class="playback-share-editor"
        >
          <header>
            <div>
              <strong>Share export</strong>
              <span>
                {{ formatTimestamp(new Date(shareExport.start_at)) }}
              </span>
            </div>
            <button
              class="icon-button"
              type="button"
              title="Close share editor"
              @click="closeShare"
            >
              <UiIcon name="close" :size="13" />
            </button>
          </header>

          <form @submit.prevent="saveShare">
            <label>
              <span>Password</span>
              <input
                v-model="sharePassword"
                type="password"
                placeholder="Optional"
                autocomplete="new-password"
              />
            </label>
            <label>
              <span>Expires after</span>
              <select v-model.number="shareExpiresHours">
                <option :value="1">1 hour</option>
                <option :value="6">6 hours</option>
                <option :value="24">24 hours</option>
                <option :value="72">3 days</option>
                <option :value="168">7 days</option>
                <option :value="720">30 days</option>
              </select>
            </label>
            <label>
              <span>Maximum downloads</span>
              <input
                v-model.number="shareMaxDownloads"
                type="number"
                min="0"
                max="100000"
                placeholder="0 = unlimited"
              />
            </label>
            <button
              class="button button--primary"
              type="submit"
              :disabled="shareSaving"
            >
              {{ shareSaving ? "Creating…" : "Create share link" }}
            </button>
          </form>

          <div
            v-if="createdShare"
            class="playback-share-created"
          >
            <strong>Share link created</strong>
            <span>
              This token is shown once. Copy it before closing this panel.
            </span>
            <div>
              <input
                :value="shareUrl(createdShare)"
                readonly
                @focus="($event.target as HTMLInputElement).select()"
              />
              <button
                class="button button--ghost button--compact"
                type="button"
                @click="copyShareLink"
              >
                {{ shareCopied ? "Copied" : "Copy" }}
              </button>
            </div>
          </div>

          <div
            v-if="exportShares.length"
            class="playback-share-list"
          >
            <h4>Existing shares</h4>
            <article
              v-for="item in exportShares"
              :key="item.id"
            >
              <div>
                <strong>
                  {{
                    item.revoked_at
                      ? "Revoked"
                      : new Date(item.expires_at) <= new Date()
                        ? "Expired"
                        : "Active"
                  }}
                </strong>
                <span>
                  {{ item.download_count }}
                  {{
                    item.max_downloads
                      ? `/ ${item.max_downloads}`
                      : ""
                  }}
                  downloads · expires
                  {{ formatTimestamp(new Date(item.expires_at)) }}
                </span>
              </div>
              <span
                v-if="item.password_protected"
                class="status-pill"
              >
                Password
              </span>
              <button
                v-if="!item.revoked_at"
                class="icon-button icon-button--danger"
                type="button"
                title="Revoke share"
                @click="revokeShare(item)"
              >
                <UiIcon name="trash" :size="13" />
              </button>
            </article>
          </div>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.playback-action-buttons {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
}

.playback-action-panel {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  bottom: 0;
  z-index: 42;
  width: min(370px, 94vw);
  overflow-y: auto;
  border-left: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-primary);
  box-shadow: -16px 0 42px rgba(0, 0, 0, 0.2);
}

.playback-action-panel > header {
  display: flex;
  min-height: 56px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 10px 0 13px;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-action-panel > header strong,
.playback-action-panel > header span {
  display: block;
}

.playback-action-panel > header strong {
  font-size: 11px;
}

.playback-action-panel > header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.playback-action-form {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-action-form label {
  display: grid;
  gap: 5px;
}

.playback-action-form label > span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}


.playback-action-form label > small {
  color: var(--text-muted);
  font-size: 7px;
  line-height: 1.35;
}

.playback-action-form input,
.playback-action-form select {
  width: 100%;
  min-height: 34px;
  padding: 0 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-base);
  color: var(--text-primary);
  color-scheme: dark;
  font: inherit;
  font-size: 9px;
}

.playback-action-form input:focus,
.playback-action-form select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.playback-action-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding-top: 3px;
}

.playback-action-history {
  padding: 11px 12px;
}

.playback-action-history h3 {
  margin: 0 0 7px;
  color: var(--text-muted);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.playback-action-history article {
  display: flex;
  min-height: 48px;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-action-history article:last-child {
  border-bottom: 0;
}

.playback-action-history article > div {
  min-width: 0;
  flex: 1;
}

.playback-action-history strong,
.playback-action-history div > span {
  display: block;
}

.playback-action-history strong {
  overflow: hidden;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.playback-action-history div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.playback-share-editor {
  display: grid;
  gap: 10px;
  margin: 0 12px 12px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.playback-share-editor > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.playback-share-editor > header strong,
.playback-share-editor > header span {
  display: block;
}

.playback-share-editor > header strong {
  font-size: 9px;
}

.playback-share-editor > header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.playback-share-editor form {
  display: grid;
  gap: 8px;
}

.playback-share-editor form label {
  display: grid;
  gap: 4px;
}

.playback-share-editor form label > span {
  color: var(--text-muted);
  font-size: 7px;
  font-weight: 650;
  text-transform: uppercase;
}

.playback-share-editor input,
.playback-share-editor select {
  width: 100%;
  min-height: 32px;
  padding: 0 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: 8px;
}

.playback-share-created {
  display: grid;
  gap: 5px;
  padding: 8px;
  border: 1px solid rgba(70, 170, 112, 0.2);
  border-radius: var(--radius-sm);
  background: var(--success-soft);
}

.playback-share-created > strong,
.playback-share-created > span {
  display: block;
}

.playback-share-created > strong {
  color: var(--success);
  font-size: 8px;
}

.playback-share-created > span {
  color: var(--text-muted);
  font-size: 7px;
}

.playback-share-created > div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 5px;
}

.playback-share-list {
  display: grid;
  gap: 4px;
}

.playback-share-list h4 {
  margin: 0 0 2px;
  color: var(--text-muted);
  font-size: 7px;
  text-transform: uppercase;
}

.playback-share-list article {
  display: grid;
  min-height: 42px;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 5px;
  padding: 5px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-share-list article:last-child {
  border-bottom: 0;
}

.playback-share-list strong,
.playback-share-list article div > span {
  display: block;
}

.playback-share-list strong {
  font-size: 8px;
}

.playback-share-list article div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}
</style>
