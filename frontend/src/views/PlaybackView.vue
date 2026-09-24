<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useRoute } from "vue-router"
import { useI18n } from "vue-i18n"

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
  findNextPlayableTimelineTime,
  findTimelineSegmentAt,
  getAlignedCameraTimelines,
  getCameraTimeline,
  resolveCameraPlayback,
  resolveRecordingSegment,
  type PlaybackGap,
  type PlaybackPlayable,
  type PlaybackResolve,
  type PlaybackTimeline,
  type TimelineDetailLevel,
  type TimelineSegment
} from "../api/playback"
import PlaybackTimelineCanvas from "../components/playback/PlaybackTimelineCanvas.vue"
import TolerantPlaybackTile from "../components/playback/TolerantPlaybackTile.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { PlaybackDriftController } from "../playback/driftController"
import { MasterPlaybackClock } from "../playback/masterClock"
import { useAuthStore } from "../stores/auth"

type ZoomHours = 1 | 6 | 24
type PlaybackRate = 0.5 | 1 | 2 | 4 | 8
type SyncMode = "tolerant" | "strict"
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

const auth = useAuthStore()
const route = useRoute()
const { locale, t, te } = useI18n({
  useScope: "global"
})
const zoomOptions: ZoomHours[] = [1, 6, 24]
const stage = ref<HTMLElement | null>(null)
const videoA = ref<HTMLVideoElement | null>(null)
const videoB = ref<HTMLVideoElement | null>(null)
const cameras = ref<CameraSummary[]>([])
const activeCameraId = ref<string | null>(null)
const syncedCameraIds = ref<string[]>([])
const syncSeekGeneration = ref(0)
const syncMode = ref<SyncMode>("tolerant")
const strictPlaybackRequested = ref(false)
const syncTileStates = ref<
  Record<string, SyncTileState>
>({})
const cameraPanelOpen = ref(true)
const search = ref("")
const timeline = ref<PlaybackTimeline | null>(null)
const alignedTimelineTracks = ref<
  Record<string, PlaybackTimeline>
>({})
const zoomHours = ref<ZoomHours>(24)
const playbackRate = ref<PlaybackRate>(1)
const playbackRateOptions: PlaybackRate[] = [
  0.5,
  1,
  2,
  4,
  8
]
const selectedDate = ref(formatDateInput(new Date()))
const currentAt = ref(new Date())
const masterClock = new MasterPlaybackClock(
  currentAt.value.getTime()
)
const driftController = new PlaybackDriftController()
const timelineCenterMs = ref<number | null>(null)
const playbackAnchorMs = ref<number | null>(null)
const playbackResult = ref<PlaybackResolve | null>(null)
const playerAUrl = ref<string | null>(null)
const playerBUrl = ref<string | null>(null)
const activePlayerSlot = ref<"a" | "b">("a")
const activeSegmentId = ref<string | null>(null)
const activeTimelineSegment = ref<TimelineSegment | null>(null)
const standbyPlayback = ref<PlaybackPlayable | null>(null)
const standbySegment = ref<TimelineSegment | null>(null)
const standbyBoundaryMs = ref<number | null>(null)
const standbyReady = ref(false)
const loadingCameras = ref(false)
const loadingTimeline = ref(false)
const resolving = ref(false)
const error = ref<string | null>(null)
const playing = ref(false)
const muted = ref(true)
const fullscreen = ref(false)
const skipGaps = ref(false)
const diagnosticsOpen = ref(false)
const actionPanelOpen = ref(false)
const actionMode = ref<"protect" | "export">("export")
const actionStart = ref("")
const actionEnd = ref("")
const editingProtectionId = ref<string | null>(null)
const protectionReason = ref("")
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
let preloadRetryTimer: number | null = null
let preloadGeneration = 0
let boundarySwitchTimer: number | null = null
let masterClockFrame: number | null = null
let boundaryWaiting = false
let boundarySwitching = false
let exportPollTimer: number | null = null

const activeCamera = computed(() =>
  cameras.value.find((camera) => camera.id === activeCameraId.value) ?? null
)

const multiCameraMode = computed(
  () => syncedCameraIds.value.length > 0
)

const playbackParticipants = computed(() => {
  const ids = [
    activeCameraId.value,
    ...syncedCameraIds.value
  ].filter(
    (value): value is string =>
      Boolean(value)
  )
  const unique = Array.from(
    new Set(ids)
  )
  return unique
    .map((id) =>
      cameras.value.find(
        (camera) => camera.id === id
      )
    )
    .filter(
      (
        camera
      ): camera is CameraSummary =>
        Boolean(camera)
    )
})

const playbackGridClass = computed(
  () =>
    `playback-video-grid--${Math.min(
      9,
      playbackParticipants.value.length
    )}`
)

const strictBlockers = computed(() =>
  playbackParticipants.value.filter(
    (camera) =>
      syncTileStates.value[camera.id]
        ?.blocksStrict ?? true
  )
)

const strictBarrierActive = computed(
  () =>
    multiCameraMode.value &&
    syncMode.value === "strict" &&
    strictPlaybackRequested.value &&
    strictBlockers.value.length > 0
)

const playbackControlActive = computed(
  () =>
    multiCameraMode.value &&
    syncMode.value === "strict"
      ? strictPlaybackRequested.value
      : playing.value
)

const highSpeedMuted = computed(
  () => playbackRate.value >= 4
)

const effectiveMuted = computed(
  () =>
    muted.value ||
    highSpeedMuted.value
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

const diagnosticResolverState = computed(() => {
  if (resolving.value) return "resolving"
  return playbackResult.value?.status ?? "idle"
})

const diagnosticClock = computed(() => {
  void currentAt.value
  return masterClock.snapshot()
})

const activeMediaDiagnostics = computed(() => {
  const masterTimeMs =
    currentAt.value.getTime()
  const element = activeVideo()
  if (!element) return null

  const mediaTimeMs =
    playbackAnchorMs.value === null
      ? null
      : playbackAnchorMs.value +
        element.currentTime * 1000

  return {
    readyState:
      mediaReadyStateLabel(element),
    currentTimeSeconds:
      element.currentTime,
    mediaTimeMs,
    driftMs:
      mediaTimeMs === null
        ? null
        : mediaTimeMs -
          masterTimeMs,
    playbackRate:
      element.playbackRate,
    paused: element.paused,
    seeking: element.seeking
  }
})

function mediaReadyStateLabel(
  element: HTMLMediaElement
): string {
  switch (element.readyState) {
    case element.HAVE_NOTHING:
      return "nothing"
    case element.HAVE_METADATA:
      return "metadata"
    case element.HAVE_CURRENT_DATA:
      return "current-data"
    case element.HAVE_FUTURE_DATA:
      return "future-data"
    case element.HAVE_ENOUGH_DATA:
      return "enough-data"
    default:
      return String(element.readyState)
  }
}

function formatDiagnosticMs(
  value: number | null
): string {
  if (value === null || !Number.isFinite(value)) {
    return "—"
  }
  return `${Math.round(value)} ms`
}

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
  return new Intl.DateTimeFormat(locale.value, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date)
}

function formatTimestamp(date: Date): string {
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date)
}

function translatedStatus(value: string): string {
  const normalized = value
    .toLowerCase()
    .replaceAll("-", "_")
    .replaceAll(".", "_")
  const key = `playback.status.${normalized}`
  return te(key)
    ? t(key)
    : value.replaceAll("_", " ")
}

function translatedReason(value: string): string {
  const normalized = value
    .toLowerCase()
    .replaceAll("-", "_")
  const key = `playback.reasonMap.${normalized}`
  return te(key)
    ? t(key)
    : value.replaceAll("_", " ")
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
    const wasMulti =
      multiCameraMode.value
    cameras.value = await listCameras({
      includeRetired: true
    })
    const validIds = new Set(
      cameras.value.map(
        (camera) => camera.id
      )
    )
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
      activeCameraId.value =
        cameras.value[0]?.id ?? null
    }

    syncedCameraIds.value =
      syncedCameraIds.value.filter(
        (cameraId) =>
          cameraId !==
            activeCameraId.value &&
          validIds.has(cameraId)
      )
    const lostMulti =
      wasMulti &&
      !multiCameraMode.value

    if (hasRouteAt && routeAt) {
      timelineCenterMs.value =
        routeAt.getTime()
      selectedDate.value =
        formatDateInput(routeAt)
      zoomHours.value = 6

      if (multiCameraMode.value) {
        applySynchronizedMasterTime(
          routeAt,
          true
        )
        await refreshTimeline(false)
      } else {
        setMasterClockTime(
          routeAt.getTime(),
          "seeking"
        )
        await refreshTimeline(false)
        await resolveAt(routeAt, true)
      }
    } else {
      await refreshTimeline(false)
      if (
        lostMulti &&
        activeCameraId.value
      ) {
        const shouldPlay =
          syncMode.value === "strict"
            ? strictPlaybackRequested.value
            : playing.value
        strictPlaybackRequested.value = false
        syncTileStates.value = {}
        await resolveAt(
          new Date(
            masterClock.currentTimeMs()
          ),
          shouldPlay
        )
      }
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
    if (
      multiCameraMode.value &&
      playbackParticipants.value.length >= 2
    ) {
      const aligned =
        await getAlignedCameraTimelines(
          playbackParticipants.value.map(
            (camera) => camera.id
          ),
          from,
          to,
          detail
        )
      if (
        generation !== timelineGeneration
      ) {
        return
      }

      alignedTimelineTracks.value =
        Object.fromEntries(
          aligned.tracks.map(
            (track) => [
              track.camera_id,
              track
            ]
          )
        )
      timeline.value =
        alignedTimelineTracks.value[
          cameraId
        ] ?? null
    } else {
      const value = await getCameraTimeline(
        cameraId,
        from,
        to,
        detail
      )
      if (
        generation !== timelineGeneration
      ) {
        return
      }
      alignedTimelineTracks.value = {}
      timeline.value = value
    }

    if (resolveCurrent) {
      await resolveAt(
        currentAt.value,
        false
      )
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

function clearPreloadRetry(): void {
  preloadGeneration += 1
  if (preloadRetryTimer !== null) {
    window.clearTimeout(preloadRetryTimer)
    preloadRetryTimer = null
  }
}

function clearBoundarySwitchTimer(): void {
  if (boundarySwitchTimer === null) return
  window.clearTimeout(boundarySwitchTimer)
  boundarySwitchTimer = null
}

function stopMasterClockFrame(): void {
  if (masterClockFrame === null) return
  window.cancelAnimationFrame(
    masterClockFrame
  )
  masterClockFrame = null
}

function synchronizedTimelines():
  PlaybackTimeline[] {
  if (!multiCameraMode.value) {
    return timeline.value
      ? [timeline.value]
      : []
  }

  return playbackParticipants.value
    .map(
      (camera) =>
        alignedTimelineTracks.value[
          camera.id
        ]
    )
    .filter(
      (
        track
      ): track is PlaybackTimeline =>
        Boolean(track)
    )
}

function findSkipGapTarget(
  timeMs: number
): number | null {
  if (!skipGaps.value) return null

  const tracks = synchronizedTimelines()
  if (
    !tracks.length ||
    (
      multiCameraMode.value &&
      tracks.length !==
        playbackParticipants.value.length
    )
  ) {
    return null
  }

  return findNextPlayableTimelineTime(
    tracks,
    timeMs
  )
}

function skipSynchronizedGap(
  timeMs: number
): boolean {
  if (
    !multiCameraMode.value ||
    !playing.value
  ) {
    return false
  }

  const target = findSkipGapTarget(
    timeMs
  )
  if (
    target === null ||
    target <= timeMs
  ) {
    return false
  }

  applySynchronizedMasterTime(
    new Date(target),
    true
  )
  return true
}

function renderMasterClock(): void {
  masterClockFrame = null
  const timeMs = masterClock.currentTimeMs()
  currentAt.value = new Date(timeMs)

  if (
    skipSynchronizedGap(timeMs)
  ) {
    return
  }

  const segment = activeTimelineSegment.value
  if (!multiCameraMode.value && segment) {
    const boundaryMs = new Date(
      segment.end_at
    ).getTime()
    if (timeMs >= boundaryMs) {
      requestBoundarySwitch(
        activePlayerSlot.value,
        boundaryMs
      )
    }
  }

  if (masterClock.state === "playing") {
    masterClockFrame =
      window.requestAnimationFrame(
        renderMasterClock
      )
  }
}

function startMasterClockFrame(): void {
  if (
    masterClockFrame !== null ||
    masterClock.state !== "playing"
  ) {
    return
  }
  masterClockFrame =
    window.requestAnimationFrame(
      renderMasterClock
    )
}

function setMasterClockTime(
  timeMs: number,
  state: "paused" | "seeking"
): void {
  stopMasterClockFrame()
  if (state === "seeking") {
    masterClock.seek(timeMs)
  } else {
    masterClock.pause(timeMs)
  }
  currentAt.value = new Date(timeMs)
}

function videoForSlot(
  slot: "a" | "b"
): HTMLVideoElement | null {
  return slot === "a"
    ? videoA.value
    : videoB.value
}

function activeVideo(): HTMLVideoElement | null {
  return videoForSlot(activePlayerSlot.value)
}

function standbySlot(): "a" | "b" {
  return activePlayerSlot.value === "a"
    ? "b"
    : "a"
}

function setPlayerUrl(
  slot: "a" | "b",
  value: string | null
): void {
  if (slot === "a") {
    playerAUrl.value = value
  } else {
    playerBUrl.value = value
  }
}

function clearVideoElement(
  element: HTMLVideoElement | null
): void {
  if (!element) return
  element.pause()
  element.removeAttribute("src")
  element.load()
}

function resetDriftCorrection(): void {
  driftController.reset(
    performance.now()
  )
  const element = activeVideo()
  if (element) {
    element.playbackRate =
      playbackRate.value
  }
}

function isSyncParticipant(
  cameraId: string
): boolean {
  return (
    cameraId === activeCameraId.value ||
    syncedCameraIds.value.includes(
      cameraId
    )
  )
}

function synchronizeTileStateMap(): void {
  const next: Record<string, SyncTileState> = {}
  for (const camera of playbackParticipants.value) {
    next[camera.id] =
      syncTileStates.value[camera.id] ?? {
        cameraId: camera.id,
        state: "resolving",
        blocksStrict: true
      }
  }
  syncTileStates.value = next
}

function markSyncTilesResolving(): void {
  const next: Record<string, SyncTileState> = {}
  for (const camera of playbackParticipants.value) {
    next[camera.id] = {
      cameraId: camera.id,
      state: "resolving",
      blocksStrict: true
    }
  }
  syncTileStates.value = next
}

function pauseSynchronizedMaster(): void {
  const timeMs = masterClock.currentTimeMs()
  masterClock.pause(timeMs)
  currentAt.value = new Date(timeMs)
  playing.value = false
  stopMasterClockFrame()
}

function resumeSynchronizedMaster(): void {
  masterClock.play(
    currentAt.value.getTime(),
    playbackRate.value
  )
  playing.value = true
  startMasterClockFrame()
}

function reconcileStrictPlayback(): void {
  if (
    !multiCameraMode.value ||
    syncMode.value !== "strict"
  ) {
    return
  }

  if (!strictPlaybackRequested.value) {
    if (playing.value) {
      pauseSynchronizedMaster()
    }
    return
  }

  if (strictBlockers.value.length > 0) {
    if (playing.value) {
      pauseSynchronizedMaster()
    }
    return
  }

  if (!playing.value) {
    resumeSynchronizedMaster()
  }
}

function handleSyncTileState(
  state: SyncTileState
): void {
  if (!isSyncParticipant(state.cameraId)) {
    return
  }

  syncTileStates.value = {
    ...syncTileStates.value,
    [state.cameraId]: state
  }
  reconcileStrictPlayback()
}

function setSyncMode(mode: SyncMode): void {
  if (
    !multiCameraMode.value ||
    syncMode.value === mode
  ) {
    return
  }

  if (mode === "strict") {
    syncMode.value = "strict"
    strictPlaybackRequested.value =
      playing.value
    synchronizeTileStateMap()
    reconcileStrictPlayback()
    return
  }

  const shouldResume =
    strictPlaybackRequested.value
  syncMode.value = "tolerant"
  strictPlaybackRequested.value = false

  if (shouldResume && !playing.value) {
    resumeSynchronizedMaster()
  }
}

function applySynchronizedMasterTime(
  at: Date,
  autoplay: boolean
): void {
  stopMasterClockFrame()
  const timeMs = at.getTime()
  currentAt.value = new Date(timeMs)

  if (syncMode.value === "strict") {
    masterClock.pause(timeMs)
    playing.value = false
    strictPlaybackRequested.value =
      autoplay
    markSyncTilesResolving()
    syncSeekGeneration.value += 1
    reconcileStrictPlayback()
    return
  }

  strictPlaybackRequested.value = false
  if (autoplay) {
    masterClock.play(
      timeMs,
      playbackRate.value
    )
    playing.value = true
    startMasterClockFrame()
  } else {
    masterClock.pause(timeMs)
    playing.value = false
  }

  syncSeekGeneration.value += 1
}

function enterTolerantMode(): void {
  const timeMs =
    masterClock.currentTimeMs()
  const shouldPlay = playing.value

  clearPendingRetry()
  resolveGeneration += 1
  clearPlayers()
  playbackResult.value = null

  if (shouldPlay) {
    masterClock.play(
      timeMs,
      playbackRate.value
    )
    playing.value = true
    startMasterClockFrame()
  } else {
    masterClock.pause(timeMs)
    playing.value = false
  }

  currentAt.value = new Date(timeMs)
  synchronizeTileStateMap()
  syncSeekGeneration.value += 1

  if (syncMode.value === "strict") {
    strictPlaybackRequested.value =
      shouldPlay
    reconcileStrictPlayback()
  }
}

function leaveTolerantMode(): void {
  const at = new Date(
    masterClock.currentTimeMs()
  )
  const shouldPlay =
    syncMode.value === "strict"
      ? strictPlaybackRequested.value
      : playing.value

  strictPlaybackRequested.value = false
  syncTileStates.value = {}
  syncSeekGeneration.value += 1
  void resolveAt(
    at,
    shouldPlay
  )
}

function toggleSyncCamera(
  cameraId: string
): void {
  if (cameraId === activeCameraId.value) {
    return
  }

  const wasMulti =
    multiCameraMode.value
  const current = [
    ...syncedCameraIds.value
  ]
  const existing = current.indexOf(
    cameraId
  )

  if (existing >= 0) {
    current.splice(existing, 1)
  } else {
    if (current.length >= 8) {
      error.value = t("playback.maxSyncCameras")
      return
    }
    current.push(cameraId)
  }

  syncedCameraIds.value = current
  synchronizeTileStateMap()
  error.value = null

  if (
    !wasMulti &&
    multiCameraMode.value
  ) {
    enterTolerantMode()
  } else if (
    wasMulti &&
    !multiCameraMode.value
  ) {
    leaveTolerantMode()
  } else if (
    multiCameraMode.value &&
    syncMode.value === "strict"
  ) {
    reconcileStrictPlayback()
  }
}

function clearPlayers(): void {
  resetDriftCorrection()
  if (masterClock.state === "playing") {
    masterClock.pause()
    currentAt.value = new Date(
      masterClock.currentTimeMs()
    )
  }
  stopMasterClockFrame()
  clearPreloadRetry()
  clearBoundarySwitchTimer()
  clearVideoElement(videoA.value)
  clearVideoElement(videoB.value)
  playerAUrl.value = null
  playerBUrl.value = null
  activePlayerSlot.value = "a"
  activeSegmentId.value = null
  activeTimelineSegment.value = null
  standbyPlayback.value = null
  standbySegment.value = null
  standbyBoundaryMs.value = null
  standbyReady.value = false
  boundaryWaiting = false
  boundarySwitching = false
  playbackAnchorMs.value = null
}

function nextContinuationSegment(
  segmentId: string
): {
  segment: TimelineSegment
  boundaryMs: number
  offsetMs: number
} | null {
  const segments = timeline.value?.segments ?? []
  const index = segments.findIndex(
    (item) => item.id === segmentId
  )
  if (index < 0) return null

  const currentEnd = new Date(
    segments[index].end_at
  ).getTime()

  for (
    let nextIndex = index + 1;
    nextIndex < segments.length;
    nextIndex += 1
  ) {
    const next = segments[nextIndex]
    const nextStart = new Date(
      next.start_at
    ).getTime()
    const nextEnd = new Date(
      next.end_at
    ).getTime()

    if (nextStart > currentEnd) {
      return null
    }
    if (nextEnd <= currentEnd) {
      continue
    }

    return {
      segment: next,
      boundaryMs: currentEnd,
      offsetMs: Math.max(
        0,
        currentEnd - nextStart
      )
    }
  }

  return null
}

async function preloadNextSegment(
  segmentId: string
): Promise<void> {
  clearPreloadRetry()
  const generation = preloadGeneration
  const continuation = nextContinuationSegment(
    segmentId
  )
  if (!continuation) {
    standbyPlayback.value = null
    standbySegment.value = null
    standbyBoundaryMs.value = null
    standbyReady.value = false
    setPlayerUrl(standbySlot(), null)
    return
  }

  const {
    segment: next,
    boundaryMs,
    offsetMs
  } = continuation

  try {
    const result = await resolveRecordingSegment(
      next.playback_ref,
      offsetMs
    )
    if (
      generation !== preloadGeneration ||
      activeSegmentId.value !== segmentId
    ) {
      return
    }

    if (result.status === "pending") {
      preloadRetryTimer = window.setTimeout(
        () => {
          preloadRetryTimer = null
          if (
            generation === preloadGeneration &&
            activeSegmentId.value === segmentId
          ) {
            void preloadNextSegment(
              segmentId
            )
          }
        },
        Math.max(
          500,
          result.retry_after_ms
        )
      )
      return
    }

    if (result.status !== "playable") {
      standbyPlayback.value = null
      standbySegment.value = null
      standbyBoundaryMs.value = null
      standbyReady.value = false
      setPlayerUrl(standbySlot(), null)
      if (boundaryWaiting) {
        void resolveAt(
          new Date(boundaryMs),
          true
        )
      }
      return
    }

    standbyPlayback.value = result
    standbySegment.value = next
    standbyBoundaryMs.value = boundaryMs
    standbyReady.value = false
    setPlayerUrl(
      standbySlot(),
      browserMediaUrl(result.url)
    )
    await nextTick()

    const standby = videoForSlot(
      standbySlot()
    )
    if (standby) {
      standby.muted = effectiveMuted.value
      standby.playbackRate =
        playbackRate.value
      standby.load()
    }
  } catch {
    if (generation === preloadGeneration) {
      standbyPlayback.value = null
      standbySegment.value = null
      standbyBoundaryMs.value = null
      standbyReady.value = false
      setPlayerUrl(standbySlot(), null)
      if (boundaryWaiting) {
        void resolveAt(
          new Date(boundaryMs),
          true
        )
      }
    }
  }
}

function standbyCanSwitch(): boolean {
  const element = videoForSlot(
    standbySlot()
  )
  return Boolean(
    standbyPlayback.value &&
    standbySegment.value &&
    standbyReady.value &&
    element &&
    element.readyState >=
      element.HAVE_FUTURE_DATA
  )
}

async function switchToStandbyAtBoundary(
  slot: "a" | "b",
  boundaryMs: number
): Promise<void> {
  if (
    boundarySwitching ||
    slot !== activePlayerSlot.value ||
    standbyBoundaryMs.value !== boundaryMs ||
    !standbyCanSwitch()
  ) {
    return
  }

  const standby = standbyPlayback.value
  const nextSegment = standbySegment.value
  const nextSlot = standbySlot()
  const nextElement = videoForSlot(
    nextSlot
  )
  if (
    !standby ||
    !nextSegment ||
    !nextElement
  ) {
    return
  }

  boundarySwitching = true
  clearBoundarySwitchTimer()

  const previousSlot = activePlayerSlot.value
  const previousElement = videoForSlot(
    previousSlot
  )
  const basePlaybackRate =
    playbackRate.value

  activePlayerSlot.value = nextSlot
  activeSegmentId.value = standby.segment_id
  activeTimelineSegment.value = nextSegment
  playbackResult.value = standby
  playbackAnchorMs.value = boundaryMs
  setMasterClockTime(
    boundaryMs,
    "seeking"
  )
  driftController.reset(
    performance.now()
  )
  standbyPlayback.value = null
  standbySegment.value = null
  standbyBoundaryMs.value = null
  standbyReady.value = false
  boundaryWaiting = false
  setPlayerUrl(previousSlot, null)

  await nextTick()
  clearVideoElement(previousElement)
  nextElement.muted = effectiveMuted.value
  nextElement.playbackRate =
    basePlaybackRate
  await nextElement.play().catch(
    () => undefined
  )

  boundarySwitching = false
  if (
    activePlayerSlot.value === nextSlot &&
    activeSegmentId.value === standby.segment_id
  ) {
    void preloadNextSegment(
      standby.segment_id
    )
  }
}

function requestBoundarySwitch(
  slot: "a" | "b",
  boundaryMs: number
): void {
  if (slot !== activePlayerSlot.value) return

  clearBoundarySwitchTimer()
  masterClock.pause(boundaryMs)
  stopMasterClockFrame()
  currentAt.value = new Date(boundaryMs)

  const segmentId = activeSegmentId.value
  if (
    !segmentId ||
    !nextContinuationSegment(segmentId)
  ) {
    void resolveAt(
      new Date(boundaryMs),
      true
    )
    return
  }

  boundaryWaiting = true

  if (
    standbyBoundaryMs.value === boundaryMs &&
    standbyCanSwitch()
  ) {
    void switchToStandbyAtBoundary(
      slot,
      boundaryMs
    )
    return
  }

  activeVideo()?.pause()
}

function scheduleBoundarySwitch(
  slot: "a" | "b"
): void {
  clearBoundarySwitchTimer()
  if (slot !== activePlayerSlot.value) {
    return
  }

  const segment = activeTimelineSegment.value
  const element = videoForSlot(slot)
  const absolute = masterClock.currentTimeMs()
  if (
    !segment ||
    !element ||
    masterClock.state !== "playing" ||
    element.paused
  ) {
    return
  }

  const boundaryMs = new Date(
    segment.end_at
  ).getTime()
  const remaining = boundaryMs - absolute

  if (remaining <= 0) {
    requestBoundarySwitch(
      slot,
      boundaryMs
    )
    return
  }

  boundarySwitchTimer = window.setTimeout(
    () => {
      boundarySwitchTimer = null
      const actual = (
        masterClock.currentTimeMs()
      )
      if (actual >= boundaryMs) {
        requestBoundarySwitch(
          slot,
          boundaryMs
        )
      } else {
        scheduleBoundarySwitch(slot)
      }
    },
    Math.max(
      16,
      Math.ceil(
        remaining /
          playbackRate.value
      )
    )
  )
}

function handlePlayerCanPlay(
  slot: "a" | "b"
): void {
  if (slot !== standbySlot()) return

  const element = videoForSlot(slot)
  standbyReady.value = Boolean(
    standbyPlayback.value &&
    standbySegment.value &&
    element &&
    element.readyState >=
      element.HAVE_FUTURE_DATA
  )

  if (
    standbyReady.value &&
    boundaryWaiting &&
    standbyBoundaryMs.value !== null
  ) {
    void switchToStandbyAtBoundary(
      activePlayerSlot.value,
      standbyBoundaryMs.value
    )
  }
}

async function resolveAt(
  at: Date,
  autoplay = true
): Promise<void> {
  clearPendingRetry()
  const cameraId = activeCameraId.value
  if (!cameraId) return

  const generation = ++resolveGeneration
  clearPlayers()
  setMasterClockTime(
    at.getTime(),
    "seeking"
  )
  resolving.value = true
  error.value = null
  playing.value = false

  try {
    const segment = (
      timeline.value?.camera_id === cameraId
        ? findTimelineSegmentAt(
            timeline.value.segments,
            at
          )
        : null
    )
    const result = segment
      ? await resolveRecordingSegment(
          segment.playback_ref,
          Math.max(
            0,
            Math.round(
              at.getTime() -
                new Date(
                  segment.start_at
                ).getTime()
            )
          )
        )
      : await resolveCameraPlayback(
          cameraId,
          at
        )
    if (generation !== resolveGeneration) return
    playbackResult.value = result

    if (result.status === "gap") {
      if (
        skipGaps.value &&
        autoplay
      ) {
        const target =
          findSkipGapTarget(
            at.getTime()
          )
        if (
          target !== null &&
          target > at.getTime()
        ) {
          void resolveAt(
            new Date(target),
            true
          )
          return
        }
      }

      setMasterClockTime(
        at.getTime(),
        "paused"
      )
      return
    }

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

    const canonicalSegment = (
      segment ??
      timeline.value?.segments.find(
        (item) => item.id === result.segment_id
      ) ??
      null
    )
    playbackAnchorMs.value = (
      new Date(
        result.segment_start_at
      ).getTime() +
      result.offset_ms
    )
    setMasterClockTime(
      playbackAnchorMs.value,
      "seeking"
    )
    activeSegmentId.value = result.segment_id
    activeTimelineSegment.value = canonicalSegment
    setPlayerUrl(
      activePlayerSlot.value,
      browserMediaUrl(result.url)
    )
    await nextTick()

    const element = activeVideo()
    if (element) {
      element.muted = effectiveMuted.value
      element.load()
      if (autoplay) {
        await element.play().catch(() => undefined)
      }
    }
    void preloadNextSegment(
      result.segment_id
    )
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

  if (multiCameraMode.value) {
    const previous =
      activeCameraId.value
    const nextSynced = new Set(
      syncedCameraIds.value
    )
    nextSynced.delete(cameraId)
    if (previous) {
      nextSynced.add(previous)
    }

    activeCameraId.value = cameraId
    syncedCameraIds.value = Array.from(
      nextSynced
    ).slice(0, 8)
    playbackResult.value = null
    actionPanelOpen.value = false
    void refreshTimeline(false)
    void loadPlaybackActions()
    return
  }

  clearPendingRetry()
  clearPreloadRetry()
  clearExportPoll()
  resolveGeneration += 1
  activeCameraId.value = cameraId
  clearPlayers()
  playbackResult.value = null
  actionPanelOpen.value = false
  void refreshTimeline(false)
  void loadPlaybackActions()
}

function handleDateChange(): void {
  const start = localDayStart()
  const now = new Date()
  const selectedTime =
    formatDateInput(now) === selectedDate.value
      ? now
      : new Date(start.getTime() + 12 * 60 * 60 * 1000)

  if (multiCameraMode.value) {
    applySynchronizedMasterTime(
      selectedTime,
      false
    )
    playbackResult.value = null
    timelineCenterMs.value = null
    void refreshTimeline(false)
    return
  }

  clearPendingRetry()
  resolveGeneration += 1
  clearPlayers()
  playing.value = false
  playbackResult.value = null
  setMasterClockTime(
    selectedTime.getTime(),
    "paused"
  )
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
  if (multiCameraMode.value) {
    applySynchronizedMasterTime(
      at,
      true
    )
    return
  }
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

  if (multiCameraMode.value) {
    applySynchronizedMasterTime(
      at,
      true
    )
    timelineCenterMs.value =
      at.getTime()
    selectedDate.value =
      formatDateInput(at)
    void refreshTimeline(false)
    return
  }

  clearPendingRetry()
  resolveGeneration += 1
  clearPlayers()
  playing.value = false
  setMasterClockTime(
    at.getTime(),
    "seeking"
  )
  timelineCenterMs.value = at.getTime()
  selectedDate.value = formatDateInput(at)
  void refreshTimeline(false).then(
    () => resolveAt(at, true)
  )
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
  protectionReason.value = t("playback.importantFootage")
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
    throw new Error(t("playback.clipRangeInvalid"))
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
      t("playback.removeProtectionConfirm", {
        reason: item.reason
      })
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
  if (!window.confirm(t("playback.deleteExportConfirm"))) return
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
  if (multiCameraMode.value) {
    if (syncMode.value === "strict") {
      if (strictPlaybackRequested.value) {
        strictPlaybackRequested.value = false
        if (playing.value) {
          pauseSynchronizedMaster()
        }
      } else {
        strictPlaybackRequested.value = true
        synchronizeTileStateMap()
        reconcileStrictPlayback()
      }
      return
    }

    if (playing.value) {
      pauseSynchronizedMaster()
    } else {
      resumeSynchronizedMaster()
    }
    return
  }

  if (boundaryWaiting) {
    if (
      standbyBoundaryMs.value !== null &&
      standbyCanSwitch()
    ) {
      void switchToStandbyAtBoundary(
        activePlayerSlot.value,
        standbyBoundaryMs.value
      )
    }
    return
  }

  const element = activeVideo()
  if (!element) {
    void resolveAt(currentAt.value, true)
    return
  }

  if (element.paused) {
    void element.play()
  } else {
    element.pause()
  }
}

function setPlaybackRate(
  rate: PlaybackRate
): void {
  if (playbackRate.value === rate) {
    return
  }

  masterClock.setPlaybackRate(rate)
  playbackRate.value = rate
  driftController.reset(
    performance.now()
  )

  for (const element of [
    videoA.value,
    videoB.value
  ]) {
    if (!element) continue
    element.playbackRate = rate
    element.muted =
      effectiveMuted.value
  }

  if (
    !multiCameraMode.value &&
    playing.value
  ) {
    scheduleBoundarySwitch(
      activePlayerSlot.value
    )
  }
}

function toggleMute(): void {
  if (highSpeedMuted.value) {
    return
  }

  muted.value = !muted.value
  if (videoA.value) {
    videoA.value.muted =
      effectiveMuted.value
  }
  if (videoB.value) {
    videoB.value.muted =
      effectiveMuted.value
  }
}

function handlePlayerPlay(
  slot: "a" | "b"
): void {
  if (multiCameraMode.value) return
  if (slot === activePlayerSlot.value) {
    const element = videoForSlot(slot)
    driftController.reset(
      performance.now()
    )
    if (element) {
      element.playbackRate =
        playbackRate.value
    }
    masterClock.play(
      masterClock.currentTimeMs(),
      playbackRate.value
    )
    playing.value = true
    startMasterClockFrame()
    scheduleBoundarySwitch(slot)
  }
}

function handlePlayerPause(
  slot: "a" | "b"
): void {
  if (multiCameraMode.value) return
  if (slot === activePlayerSlot.value) {
    if (
      masterClock.state === "playing"
    ) {
      masterClock.pause()
      currentAt.value = new Date(
        masterClock.currentTimeMs()
      )
    }
    driftController.reset(
      performance.now()
    )
    const element = videoForSlot(slot)
    if (element) {
      element.playbackRate =
        playbackRate.value
    }
    stopMasterClockFrame()
    playing.value = false
    clearBoundarySwitchTimer()
  }
}

function handleTimeUpdate(
  slot: "a" | "b"
): void {
  if (
    slot !== activePlayerSlot.value ||
    playbackAnchorMs.value === null
  ) {
    return
  }

  const element = videoForSlot(slot)
  if (!element) return

  const masterTimeMs =
    masterClock.currentTimeMs()
  const segment = activeTimelineSegment.value
  if (segment) {
    const boundaryMs = new Date(
      segment.end_at
    ).getTime()
    if (masterTimeMs >= boundaryMs) {
      requestBoundarySwitch(
        slot,
        boundaryMs
      )
      return
    }
  }

  if (
    masterClock.state !== "playing" ||
    element.paused ||
    element.seeking
  ) {
    return
  }

  const mediaTimeMs =
    playbackAnchorMs.value +
    element.currentTime * 1000
  const driftMs =
    mediaTimeMs - masterTimeMs
  const action = driftController.evaluate(
    driftMs,
    playbackRate.value,
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
    playbackRate.value
  const targetSeconds = Math.max(
    0,
    (masterTimeMs -
      playbackAnchorMs.value) /
      1000
  )
  if (
    Number.isFinite(element.duration) &&
    element.duration > 0
  ) {
    element.currentTime = Math.min(
      targetSeconds,
      Math.max(
        0,
        element.duration - 0.01
      )
    )
  } else {
    element.currentTime =
      targetSeconds
  }
}

function handleEnded(
  slot: "a" | "b"
): void {
  if (slot !== activePlayerSlot.value) return

  const segment = activeTimelineSegment.value
  if (segment) {
    requestBoundarySwitch(
      slot,
      new Date(
        segment.end_at
      ).getTime()
    )
    return
  }

  const next = new Date(
    currentAt.value.getTime() + 250
  )
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
  clearPreloadRetry()
  clearBoundarySwitchTimer()
  stopMasterClockFrame()
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
          <strong>{{ t("playback.cameras") }}</strong>
          <span>{{ t("playback.availableCount", { count: cameras.length }) }}</span>
        </div>
        <button
          class="icon-button topbar-icon-button"
          type="button"
          :title="t('playback.refreshCameras')"
          :aria-label="t('playback.refreshCameras')"
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
          :placeholder="t('playback.searchCameras')"
          :aria-label="t('playback.searchCameras')"
        />
      </label>

      <div class="live-camera-list">
        <div
          v-for="camera in filteredCameras"
          :key="camera.id"
          class="playback-camera-select-row"
        >
          <button
            class="live-camera-row playback-camera-select-row__primary"
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
                'live-camera-row__status--enabled':
                  camera.enabled
              }"
            />
            <span class="live-camera-row__copy">
              <strong>{{ camera.name }}</strong>
              <small>
                {{
                  camera.location ||
                  camera.adapter_type ||
                  t("playback.cameraFallback")
                }}
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

          <button
            class="playback-sync-toggle"
            :class="{
              'playback-sync-toggle--active':
                isSyncParticipant(camera.id)
            }"
            type="button"
            :disabled="
              activeCameraId === camera.id
            "
            :title="
              activeCameraId === camera.id
                ? t('playback.primarySyncCamera')
                : isSyncParticipant(camera.id)
                  ? t('playback.removeFromSync')
                  : t('playback.addToSync')
            "
            :aria-label="
              isSyncParticipant(camera.id)
                ? t('playback.removeSyncCamera')
                : t('playback.addSyncCamera')
            "
            @click="toggleSyncCamera(camera.id)"
          >
            <UiIcon
              :name="
                isSyncParticipant(camera.id)
                  ? 'check'
                  : 'plus'
              "
              :size="13"
            />
          </button>
        </div>

        <div
          v-if="!filteredCameras.length && !loadingCameras"
          class="live-camera-list__empty"
        >
          {{ t("playback.noCamerasFound") }}
        </div>
      </div>
    </aside>

    <div ref="stage" class="playback-stage">
      <header class="live-toolbar playback-toolbar">
        <div class="live-toolbar__left">
          <button
            class="media-button"
            type="button"
            :title="cameraPanelOpen ? t('playback.hideCameras') : t('playback.showCameras')"
            @click="cameraPanelOpen = !cameraPanelOpen"
          >
            <UiIcon name="panel" :size="16" />
          </button>
          <span class="live-toolbar__title">
            {{ activeCamera?.name || t("playback.title") }}
          </span>
          <span
            v-if="multiCameraMode"
            class="playback-sync-mode-badge"
          >
            {{
              syncMode === "strict"
                ? strictBarrierActive
                  ? t("playback.strictWaiting", { count: strictBlockers.length })
                  : t("playback.strict")
                : t("playback.tolerant")
            }}
            · {{ t("playback.participantCount", { count: playbackParticipants.length }) }}
          </span>
        </div>

        <div class="playback-toolbar__center">
          <label class="playback-date-control">
            <UiIcon name="calendar" :size="14" />
            <input
              v-model="selectedDate"
              type="date"
              :aria-label="t('playback.playbackDate')"
              @change="handleDateChange"
            />
          </label>
        </div>

        <div class="live-toolbar__actions">
          <div
            v-if="multiCameraMode"
            class="playback-sync-switcher"
          >
            <button
              class="media-button media-button--text"
              :class="{
                'media-button--active':
                  syncMode === 'tolerant'
              }"
              type="button"
              @click="setSyncMode('tolerant')"
            >
              {{ t("playback.tolerant") }}
            </button>
            <button
              class="media-button media-button--text"
              :class="{
                'media-button--active':
                  syncMode === 'strict'
              }"
              type="button"
              @click="setSyncMode('strict')"
            >
              {{ t("playback.strict") }}
            </button>
          </div>

          <button
            class="media-button media-button--text"
            :class="{
              'media-button--active':
                skipGaps
            }"
            type="button"
            :aria-pressed="skipGaps"
            :title="t('playback.skipGapsTitle')"
            @click="skipGaps = !skipGaps"
          >
            {{ t("playback.skipGaps") }}
          </button>

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
            :title="fullscreen ? t('playback.exitFullscreen') : t('playback.fullscreenPlayback')"
            @click="toggleFullscreen"
          >
            <UiIcon
              :name="fullscreen ? 'minimize' : 'maximize'"
              :size="16"
            />
          </button>
        </div>
      </header>

      <div
        v-if="multiCameraMode"
        class="playback-video-grid"
        :class="playbackGridClass"
      >
        <TolerantPlaybackTile
          v-for="camera in playbackParticipants"
          :key="camera.id"
          :camera-id="camera.id"
          :camera-name="camera.name"
          :master-time-ms="currentAt.getTime()"
          :playing="playing"
          :playback-rate="playbackRate"
          :muted="
            camera.id === activeCameraId
              ? effectiveMuted
              : true
          "
          :seek-generation="syncSeekGeneration"
          :focused="
            camera.id === activeCameraId
          "
          @sync-state="handleSyncTileState"
        />
      </div>

      <div
        v-else
        class="playback-video-area"
      >
        <video
          v-if="playerAUrl"
          ref="videoA"
          class="playback-video playback-video--layer"
          :class="{
            'playback-video--active':
              activePlayerSlot === 'a'
          }"
          :src="playerAUrl"
          playsinline
          :muted="effectiveMuted"
          preload="auto"
          @play="handlePlayerPlay('a')"
          @pause="handlePlayerPause('a')"
          @canplay="handlePlayerCanPlay('a')"
          @timeupdate="handleTimeUpdate('a')"
          @ended="handleEnded('a')"
        />
        <video
          v-if="playerBUrl"
          ref="videoB"
          class="playback-video playback-video--layer"
          :class="{
            'playback-video--active':
              activePlayerSlot === 'b'
          }"
          :src="playerBUrl"
          playsinline
          :muted="effectiveMuted"
          preload="auto"
          @play="handlePlayerPlay('b')"
          @pause="handlePlayerPause('b')"
          @canplay="handlePlayerCanPlay('b')"
          @timeupdate="handleTimeUpdate('b')"
          @ended="handleEnded('b')"
        />

        <div
          v-if="!playerAUrl && !playerBUrl"
          class="playback-video-state"
        >
          <UiIcon
            :name="resolving ? 'refresh' : 'playback'"
            :size="32"
          />
          <strong v-if="resolving">{{ t("playback.loadingRecording") }}</strong>
          <template v-else-if="playbackResult?.status === 'pending'">
            <strong>{{ t("playback.restoringRemote") }}</strong>
            <span>
              {{ t("playback.restoringDescription") }}
            </span>
            <button
              class="media-button media-button--text"
              type="button"
              @click="resolveAt(currentAt, true)"
            >
              <UiIcon name="refresh" :size="14" />
              {{ t("playback.checkNow") }}
            </button>
          </template>
          <template v-else-if="gapResult">
            <strong>{{ t("playback.noRecording") }}</strong>
            <span>{{ translatedReason(gapResult.reason) }}</span>
            <div class="playback-gap-actions">
              <button
                v-if="gapResult.previous_at"
                class="media-button media-button--text"
                type="button"
                @click="jumpTo(gapResult.previous_at)"
              >
                <UiIcon name="previous" :size="14" />
                {{ t("playback.previous") }}
              </button>
              <button
                v-if="gapResult.next_at"
                class="media-button media-button--text"
                type="button"
                @click="jumpTo(gapResult.next_at)"
              >
                {{ t("playback.next") }}
                <UiIcon name="next" :size="14" />
              </button>
            </div>
          </template>
          <template v-else>
            <strong>{{ t("playback.selectTimelinePoint") }}</strong>
            <span>
              {{ t("playback.selectTimelineDescription") }}
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
          :aria-label="
            playbackControlActive
              ? t('playback.pause')
              : t('playback.play')
          "
          @click="togglePlayback"
        >
          <UiIcon
            :name="
              playbackControlActive
                ? 'pause'
                : 'play'
            "
            :size="16"
          />
        </button>

        <button
          class="media-button"
          type="button"
          :disabled="highSpeedMuted"
          :title="
            highSpeedMuted
              ? t('playback.highSpeedMuted')
              : effectiveMuted
                ? t('playback.unmute')
                : t('playback.mute')
          "
          :aria-label="
            highSpeedMuted
              ? t('playback.highSpeedMutedLabel')
              : effectiveMuted
                ? t('playback.unmute')
                : t('playback.mute')
          "
          @click="toggleMute"
        >
          <UiIcon
            :name="
              effectiveMuted
                ? 'volume-off'
                : 'volume'
            "
            :size="16"
          />
        </button>

        <div class="playback-speed-switcher">
          <button
            v-for="rate in playbackRateOptions"
            :key="rate"
            class="media-button media-button--text"
            :class="{
              'media-button--active':
                playbackRate === rate
            }"
            type="button"
            :aria-pressed="
              playbackRate === rate
            "
            @click="setPlaybackRate(rate)"
          >
            {{ rate }}x
          </button>
        </div>

        <button
          class="media-button media-button--text"
          :class="{
            'media-button--active':
              diagnosticsOpen
          }"
          type="button"
          :aria-pressed="diagnosticsOpen"
          @click="
            diagnosticsOpen =
              !diagnosticsOpen
          "
        >
          {{ t("playback.diagnostics") }}
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
            {{ t("playback.protect") }}
          </button>
          <button
            v-if="auth.hasPermission('recording.export')"
            class="media-button media-button--text"
            type="button"
            @click="openActionPanel('export')"
          >
            <UiIcon name="export" :size="14" />
            {{ t("playback.export") }}
          </button>
        </div>

        <span
          v-if="multiCameraMode"
          class="playback-codec"
        >
          {{ t("playback.tolerantSync") }}
        </span>
        <span
          v-else-if="
            playbackResult?.status === 'playable'
          "
          class="playback-codec"
        >
          {{ playbackResult.codec || t("playback.video") }}
        </span>
      </div>

      <aside
        v-if="diagnosticsOpen"
        class="playback-diagnostics"
      >
        <header>
          <div>
            <strong>{{ t("playback.diagnosticsTitle") }}</strong>
            <span>
              {{ t("playback.diagnosticsDescription") }}
            </span>
          </div>
          <button
            class="media-button media-button--text"
            type="button"
            @click="diagnosticsOpen = false"
          >
            {{ t("playback.close") }}
          </button>
        </header>

        <div class="playback-diagnostics__grid">
          <section>
            <strong>{{ t("playback.masterClock") }}</strong>
            <dl>
              <div>
                <dt>{{ t("playback.state") }}</dt>
                <dd>{{ translatedStatus(diagnosticClock.state) }}</dd>
              </div>
              <div>
                <dt>{{ t("playback.intent") }}</dt>
                <dd>
                  {{
                    playbackControlActive
                      ? t("playback.play")
                      : t("playback.pause")
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.rate") }}</dt>
                <dd>{{ playbackRate }}x</dd>
              </div>
              <div>
                <dt>{{ t("playback.clock") }}</dt>
                <dd>
                  {{
                    formatTimestamp(
                      new Date(
                        diagnosticClock.currentTimeMs
                      )
                    )
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.sync") }}</dt>
                <dd>
                  {{
                    multiCameraMode
                      ? `${translatedStatus(syncMode)} · ${playbackParticipants.length}`
                      : t("playback.single")
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.skipGapsLabel") }}</dt>
                <dd>{{ skipGaps ? t("playback.on") : t("playback.off") }}</dd>
              </div>
            </dl>
          </section>

          <section>
            <strong>{{ t("playback.resolver") }}</strong>
            <dl>
              <div>
                <dt>{{ t("playback.statusLabel") }}</dt>
                <dd>{{ translatedStatus(diagnosticResolverState) }}</dd>
              </div>
              <div>
                <dt>{{ t("playback.segment") }}</dt>
                <dd>
                  {{ activeSegmentId || "—" }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.availability") }}</dt>
                <dd>
                  {{
                    activeTimelineSegment
                      ?.availability ? translatedStatus(activeTimelineSegment.availability) : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.standby") }}</dt>
                <dd>
                  {{
                    standbySegment
                      ? standbyReady
                        ? t("playback.ready")
                        : t("playback.loading")
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.transport") }}</dt>
                <dd>
                  {{
                    playbackResult?.status ===
                    "playable"
                      ? playbackResult.transport
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.gap") }}</dt>
                <dd>
                  {{
                    gapResult?.reason ? translatedReason(gapResult.reason) : "—"
                  }}
                </dd>
              </div>
            </dl>
          </section>

          <section v-if="!multiCameraMode">
            <strong>{{ t("playback.activeMedia") }}</strong>
            <dl>
              <div>
                <dt>{{ t("playback.mediaReady") }}</dt>
                <dd>
                  {{
                    activeMediaDiagnostics
                      ?.readyState
                      ? translatedStatus(
                          activeMediaDiagnostics.readyState
                        )
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.mediaTime") }}</dt>
                <dd>
                  {{
                    activeMediaDiagnostics
                      ? `${activeMediaDiagnostics.currentTimeSeconds.toFixed(3)} s`
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.drift") }}</dt>
                <dd>
                  {{
                    formatDiagnosticMs(
                      activeMediaDiagnostics
                        ?.driftMs ?? null
                    )
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.mediaRate") }}</dt>
                <dd>
                  {{
                    activeMediaDiagnostics
                      ? `${activeMediaDiagnostics.playbackRate.toFixed(3)}x`
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.paused") }}</dt>
                <dd>
                  {{
                    activeMediaDiagnostics
                      ? activeMediaDiagnostics.paused
                        ? t("playback.yes")
                        : t("playback.no")
                      : "—"
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ t("playback.seeking") }}</dt>
                <dd>
                  {{
                    activeMediaDiagnostics
                      ? activeMediaDiagnostics.seeking
                        ? t("playback.yes")
                        : t("playback.no")
                      : "—"
                  }}
                </dd>
              </div>
            </dl>
          </section>

          <section v-else>
            <strong>{{ t("playback.syncChannels") }}</strong>
            <div class="playback-diagnostics__channels">
              <div
                v-for="camera in playbackParticipants"
                :key="camera.id"
              >
                <span>{{ camera.name }}</span>
                <strong>
                  {{
                    syncTileStates[camera.id]
                      ?.state ? translatedStatus(syncTileStates[camera.id].state) : translatedStatus("resolving")
                  }}
                </strong>
                <small>
                  {{
                    syncTileStates[camera.id]
                      ?.blocksStrict
                      ? t("playback.strictBlocker")
                      : t("playback.nonBlocking")
                  }}
                </small>
              </div>
            </div>
          </section>
        </div>
      </aside>

      <div class="playback-timeline-shell">
        <div class="playback-timeline-legend">
          <span><i class="legend-dot legend-dot--local" /> {{ t("playback.local") }}</span>
          <span><i class="legend-dot legend-dot--remote" /> {{ t("playback.remote") }}</span>
          <span><i class="legend-dot legend-dot--event" /> {{ t("playback.event") }}</span>
          <span
            v-if="auth.hasPermission('recording.protect')"
          >
            <i class="legend-dot legend-dot--protected" /> {{ t("playback.protected") }}
          </span>
          <span v-if="loadingTimeline">{{ t("playback.updating") }}</span>
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
                    ? t("playback.editProtection")
                    : t("playback.protectRecording")
                  : t("playback.exportClip")
              }}
            </strong>
            <span>{{ activeCamera?.name || t("playback.cameraFallback") }}</span>
          </div>
          <button
            class="icon-button"
            type="button"
            :title="t('playback.close')"
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
            <span>{{ t("playback.start") }}</span>
            <input
              v-model="actionStart"
              type="datetime-local"
              step="1"
              required
            />
          </label>
          <label>
            <span>{{ t("playback.end") }}</span>
            <input
              v-model="actionEnd"
              type="datetime-local"
              step="1"
              required
            />
          </label>

          <template v-if="actionMode === 'protect'">
            <label>
              <span>{{ t("playback.reason") }}</span>
              <input
                v-model="protectionReason"
                required
                maxlength="1024"
              />
            </label>
            <label>
              <span>{{ t("playback.expiresAt") }}</span>
              <input
                v-model="protectionExpiresAt"
                type="datetime-local"
                step="60"
              />
              <small>{{ t("playback.indefiniteHint") }}</small>
            </label>
          </template>

          <template v-else>
            <label>
              <span>{{ t("playback.codec") }}</span>
              <select v-model="exportCodecMode">
                <option value="auto">{{ t("playback.auto") }}</option>
                <option value="copy">{{ t("playback.copyWhenPossible") }}</option>
                <option value="h264">{{ t("playback.transcodeH264") }}</option>
              </select>
            </label>
            <label>
              <span>{{ t("playback.gaps") }}</span>
              <select v-model="exportGapPolicy">
                <option value="skip">{{ t("playback.skipGapsOption") }}</option>
                <option value="fail">{{ t("playback.failOnGaps") }}</option>
              </select>
            </label>
          </template>

          <div class="playback-action-form__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="actionPanelOpen = false"
            >
              {{ t("playback.cancel") }}
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="actionSaving"
            >
              {{
                actionSaving
                  ? t("playback.saving")
                  : actionMode === "protect"
                    ? editingProtectionId
                      ? t("playback.saveProtection")
                      : t("playback.protectRange")
                    : t("playback.createExport")
              }}
            </button>
          </div>
        </form>

        <section
          v-if="actionMode === 'protect' && cameraProtections.length"
          class="playback-action-history"
        >
          <h3>{{ t("playback.protectedRanges") }}</h3>
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
                {{ t("playback.expires", { time: formatTimestamp(new Date(item.expires_at)) }) }}
              </span>
            </div>
            <button
              class="icon-button"
              type="button"
              :title="t('playback.editProtection')"
              @click="editProtection(item)"
            >
              <UiIcon name="shield" :size="13" />
            </button>
            <button
              class="icon-button icon-button--danger"
              type="button"
              :title="t('playback.removeProtection')"
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
          <h3>{{ t("playback.recentExports") }}</h3>
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
              {{ translatedStatus(item.state) }}
            </span>
            <button
              v-if="item.state === 'COMPLETED'"
              class="icon-button"
              type="button"
              :title="t('playback.manageShareLink')"
              @click="openShare(item)"
            >
              <UiIcon name="share" :size="13" />
            </button>
            <a
              v-if="item.state === 'COMPLETED'"
              class="icon-button"
              :href="exportDownloadUrl(item.id)"
              :title="t('playback.downloadMp4')"
            >
              <UiIcon name="download" :size="13" />
            </a>
            <button
              class="icon-button icon-button--danger"
              type="button"
              :title="t('playback.deleteExport')"
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
              <strong>{{ t("playback.shareExport") }}</strong>
              <span>
                {{ formatTimestamp(new Date(shareExport.start_at)) }}
              </span>
            </div>
            <button
              class="icon-button"
              type="button"
              :title="t('playback.closeShareEditor')"
              @click="closeShare"
            >
              <UiIcon name="close" :size="13" />
            </button>
          </header>

          <form @submit.prevent="saveShare">
            <label>
              <span>{{ t("playback.password") }}</span>
              <input
                v-model="sharePassword"
                type="password"
                :placeholder="t('playback.optional')"
                autocomplete="new-password"
              />
            </label>
            <label>
              <span>{{ t("playback.expiresAfter") }}</span>
              <select v-model.number="shareExpiresHours">
                <option :value="1">{{ t("playback.oneHour") }}</option>
                <option :value="6">{{ t("playback.sixHours") }}</option>
                <option :value="24">{{ t("playback.twentyFourHours") }}</option>
                <option :value="72">{{ t("playback.threeDays") }}</option>
                <option :value="168">{{ t("playback.sevenDays") }}</option>
                <option :value="720">{{ t("playback.thirtyDays") }}</option>
              </select>
            </label>
            <label>
              <span>{{ t("playback.maximumDownloads") }}</span>
              <input
                v-model.number="shareMaxDownloads"
                type="number"
                min="0"
                max="100000"
                :placeholder="t('playback.unlimitedDownloads')"
              />
            </label>
            <button
              class="button button--primary"
              type="submit"
              :disabled="shareSaving"
            >
              {{ shareSaving ? t("playback.creating") : t("playback.createShareLink") }}
            </button>
          </form>

          <div
            v-if="createdShare"
            class="playback-share-created"
          >
            <strong>{{ t("playback.shareLinkCreated") }}</strong>
            <span>
              {{ t("playback.oneTimeTokenHint") }}
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
                {{ shareCopied ? t("playback.copied") : t("playback.copy") }}
              </button>
            </div>
          </div>

          <div
            v-if="exportShares.length"
            class="playback-share-list"
          >
            <h4>{{ t("playback.existingShares") }}</h4>
            <article
              v-for="item in exportShares"
              :key="item.id"
            >
              <div>
                <strong>
                  {{
                    item.revoked_at
                      ? t("playback.revoked")
                      : new Date(item.expires_at) <= new Date()
                        ? t("playback.expired")
                        : t("playback.active")
                  }}
                </strong>
                <span>
                  {{
                    item.max_downloads
                      ? t("playback.downloadsLimited", {
                          downloads: item.download_count,
                          max: item.max_downloads,
                          time: formatTimestamp(new Date(item.expires_at))
                        })
                      : t("playback.downloadsExpires", {
                          downloads: item.download_count,
                          time: formatTimestamp(new Date(item.expires_at))
                        })
                  }}
                </span>
              </div>
              <span
                v-if="item.password_protected"
                class="status-pill"
              >
                {{ t("playback.passwordProtected") }}
              </span>
              <button
                v-if="!item.revoked_at"
                class="icon-button icon-button--danger"
                type="button"
                :title="t('playback.revokeShare')"
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
