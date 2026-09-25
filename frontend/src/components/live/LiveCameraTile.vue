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
import { useI18n } from "vue-i18n"

import {
  moveCameraPtz,
  stopCameraPtz,
  type CameraSummary
} from "../../api/cameras"
import {
  ApiClientError,
  errorMessage
} from "../../api/client"
import { browserMediaUrl } from "../../api/media"
import {
  cameraSnapshotUrl,
  createCameraWhepSession,
  deleteCameraWhepSession,
  getCameraCompatibleLiveStream,
  getCameraLiveDiagnostics,
  getCameraLiveStream,
  keepCameraCompatibilityLease,
  keepCameraMediaSessionAlive,
  releaseCameraCompatibilityLease,
  revokeCameraMediaSession,
  type CameraLiveStream,
  type LiveQuality
} from "../../api/live"
import {
  createRecordingTrigger,
  listRecordingTriggers,
  stopRecordingTrigger,
  type RecordingTrigger
} from "../../api/recordings"
import {
  detectLivePlaybackCapabilities,
  resolveLivePlaybackTransports
} from "../../live/playback"
import { useAuthStore } from "../../stores/auth"
import UiIcon from "../ui/UiIcon.vue"

const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })

const props = withDefaults(defineProps<{
  camera: CameraSummary
  quality: LiveQuality
  focused?: boolean
  audioEnabled?: boolean
  allowHighQuality?: boolean
  playbackEnabled?: boolean
}>(), {
  playbackEnabled: true
})

const emit = defineEmits<{
  focus: [cameraId: string]
  playbackChange: [cameraId: string, enabled: boolean]
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
interface LiveTelemetry {
  bitrateKbps: number | null
  packetLossPct: number | null
  rttMs: number | null
  jitterMs: number | null
  relay: boolean | null
  localCandidateType: string | null
  remoteCandidateType: string | null
  candidateProtocol: string | null
  relayProtocol: string | null
  sessionSeconds: number | null
  firstFrameMs: number | null
  descriptorMs: number | null
  iceGatherMs: number | null
  whepMs: number | null
  answerToFrameMs: number | null
  reconnects: number
}

const reconnecting = ref(false)
const activeTransport = ref<"webrtc" | "hls" | null>(null)
const lastWebRtcFailure = ref<string | null>(null)
const telemetry = ref<LiveTelemetry>({
  bitrateKbps: null,
  packetLossPct: null,
  rttMs: null,
  jitterMs: null,
  relay: null,
  localCandidateType: null,
  remoteCandidateType: null,
  candidateProtocol: null,
  relayProtocol: null,
  sessionSeconds: null,
  firstFrameMs: null,
  descriptorMs: null,
  iceGatherMs: null,
  whepMs: null,
  answerToFrameMs: null,
  reconnects: 0
})

let hls: Hls | null = null
let rtcPeer: RTCPeerConnection | null = null
let whepLocation: string | null = null
let activeMediaSessionId: string | null = null
let compatibilityLeaseId: string | null = null
let compatibilityKeepaliveTimer: number | null = null
let generation = 0
let tokenRefreshTimer: number | null = null
let reconnectTimer: number | null = null
let reconnectAttempt = 0
let statsTimer: number | null = null
let statsPreviousBytes = 0
let statsPreviousAt = 0
let streamStartedAt = 0
let recordingErrorTimer: number | null = null
let ptzMovePromise: Promise<void> | null = null
let ptzStopPromise: Promise<void> | null = null
let visibilityObserver: IntersectionObserver | null = null

const WEBRTC_FIRST_FRAME_TIMEOUT_MS = 6_000
const HLS_FIRST_FRAME_TIMEOUT_MS = 8_000

const manuallyStopped = computed(
  () => props.playbackEnabled === false
)

const playbackSuspended = computed(
  () =>
    manuallyStopped.value ||
    !pageVisible.value ||
    !tileVisible.value
)

const requestedQuality = computed<LiveQuality>(() =>
  fullscreenActive.value &&
  props.allowHighQuality !== false
    ? "high"
    : props.quality
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
    const mediaSessionId = activeMediaSessionId
    if (
      !mediaSessionId ||
      playbackSuspended.value
    ) {
      return
    }

    void keepCameraMediaSessionAlive(
      props.camera.id,
      mediaSessionId
    )
      .then((renewed) => {
        if (
          activeMediaSessionId !== mediaSessionId ||
          playbackSuspended.value
        ) {
          return
        }
        scheduleTokenRefresh(
          renewed.expires_at
        )
      })
      .catch(() => {
        if (
          activeMediaSessionId !== mediaSessionId ||
          playbackSuspended.value
        ) {
          return
        }
        void loadStream()
      })
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

  telemetry.value.reconnects += 1
  const delays = [1_000, 2_000, 4_000, 8_000, 15_000]
  const delay = delays[
    Math.min(reconnectAttempt, delays.length - 1)
  ]
  reconnectAttempt += 1
  reconnecting.value = true
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    if (!playbackSuspended.value) {
      void loadStream({ preserveError: true })
    } else {
      reconnecting.value = false
    }
  }, delay)
}

function clearStatsTimer(): void {
  if (statsTimer !== null) {
    window.clearInterval(statsTimer)
    statsTimer = null
  }
  statsPreviousBytes = 0
  statsPreviousAt = 0
}

async function collectWebRtcStats(
  peer: RTCPeerConnection
): Promise<void> {
  if (rtcPeer !== peer) return

  try {
    const report = await peer.getStats()
    if (rtcPeer !== peer) return

    let bytesReceived = 0
    let packetsReceived = 0
    let packetsLost = 0
    let jitterMs: number | null = null
    let selectedPairId: string | null = null

    report.forEach((raw) => {
      const stat = raw as unknown as Record<string, unknown>
      if (
        stat.type === "inbound-rtp" &&
        stat.isRemote !== true
      ) {
        if (typeof stat.bytesReceived === "number") {
          bytesReceived += stat.bytesReceived
        }
        if (typeof stat.packetsReceived === "number") {
          packetsReceived += stat.packetsReceived
        }
        if (typeof stat.packetsLost === "number") {
          packetsLost += Math.max(0, stat.packetsLost)
        }
        if (typeof stat.jitter === "number") {
          const value = stat.jitter * 1000
          jitterMs = jitterMs === null
            ? value
            : Math.max(jitterMs, value)
        }
      }
      if (
        stat.type === "transport" &&
        typeof stat.selectedCandidatePairId === "string"
      ) {
        selectedPairId = stat.selectedCandidatePairId
      }
    })

    const now = performance.now()
    let bitrateKbps: number | null = null
    if (
      statsPreviousAt > 0 &&
      now > statsPreviousAt &&
      bytesReceived >= statsPreviousBytes
    ) {
      bitrateKbps =
        ((bytesReceived - statsPreviousBytes) * 8) /
        (now - statsPreviousAt)
    }
    statsPreviousBytes = bytesReceived
    statsPreviousAt = now

    const totalPackets = packetsReceived + packetsLost
    const packetLossPct = totalPackets > 0
      ? (packetsLost / totalPackets) * 100
      : null

    let rttMs: number | null = null
    let relay: boolean | null = null
    let localCandidateType: string | null = null
    let remoteCandidateType: string | null = null
    let candidateProtocol: string | null = null
    let relayProtocol: string | null = null
    let pair: Record<string, unknown> | null = null

    if (selectedPairId) {
      const selected = report.get(selectedPairId)
      if (selected) {
        pair = selected as unknown as Record<string, unknown>
      }
    }

    if (!pair) {
      report.forEach((raw) => {
        if (pair) return
        const stat = raw as unknown as Record<string, unknown>
        if (
          stat.type === "candidate-pair" &&
          stat.state === "succeeded" &&
          stat.nominated === true
        ) {
          pair = stat
        }
      })
    }

    if (pair) {
      if (
        typeof pair.currentRoundTripTime === "number"
      ) {
        rttMs = pair.currentRoundTripTime * 1000
      }
      const localCandidateId =
        typeof pair.localCandidateId === "string"
          ? pair.localCandidateId
          : null
      const remoteCandidateId =
        typeof pair.remoteCandidateId === "string"
          ? pair.remoteCandidateId
          : null

      if (localCandidateId) {
        const local = report.get(localCandidateId)
        if (local) {
          const candidate =
            local as unknown as Record<string, unknown>
          if (candidate.type === "local-candidate") {
            localCandidateType =
              typeof candidate.candidateType === "string"
                ? candidate.candidateType
                : null
            relay = localCandidateType === "relay"
            candidateProtocol =
              typeof candidate.protocol === "string"
                ? candidate.protocol.toUpperCase()
                : null
            relayProtocol =
              typeof candidate.relayProtocol === "string"
                ? candidate.relayProtocol.toUpperCase()
                : null
          }
        }
      }

      if (remoteCandidateId) {
        const remote = report.get(remoteCandidateId)
        if (remote) {
          const candidate =
            remote as unknown as Record<string, unknown>
          if (candidate.type === "remote-candidate") {
            remoteCandidateType =
              typeof candidate.candidateType === "string"
                ? candidate.candidateType
                : null
          }
        }
      }
    }

    const sessionSeconds =
      streamStartedAt > 0
        ? Math.max(
            0,
            (performance.now() - streamStartedAt) / 1000
          )
        : null

    telemetry.value = {
      ...telemetry.value,
      bitrateKbps,
      packetLossPct,
      rttMs,
      jitterMs,
      relay,
      localCandidateType,
      remoteCandidateType,
      candidateProtocol,
      relayProtocol,
      sessionSeconds
    }
  } catch {
    // Diagnostic sampling must never disturb live playback.
  }
}

function startStatsTimer(
  peer: RTCPeerConnection
): void {
  clearStatsTimer()
  void collectWebRtcStats(peer)
  statsTimer = window.setInterval(() => {
    void collectWebRtcStats(peer)
  }, 2000)
}

function releaseCompatibilityLease(): void {
  if (compatibilityKeepaliveTimer !== null) {
    window.clearInterval(
      compatibilityKeepaliveTimer
    )
    compatibilityKeepaliveTimer = null
  }

  const leaseId = compatibilityLeaseId
  const mediaSessionId = activeMediaSessionId
  compatibilityLeaseId = null
  if (leaseId && mediaSessionId) {
    void releaseCameraCompatibilityLease(
      props.camera.id,
      leaseId,
      mediaSessionId
    ).catch(() => undefined)
  }
}

function releaseMediaSession(): void {
  const sessionId = activeMediaSessionId
  activeMediaSessionId = null
  if (sessionId) {
    void revokeCameraMediaSession(
      props.camera.id,
      sessionId
    ).catch(() => undefined)
  }
}

function activateCompatibilityLease(
  stream: CameraLiveStream
): void {
  releaseCompatibilityLease()
  const leaseId = stream.compatibility_lease_id
  if (!leaseId) {
    throw new Error(
      t("live.tile.errors.compatibilityLeaseMissing")
    )
  }

  compatibilityLeaseId = leaseId
  compatibilityKeepaliveTimer = window.setInterval(
    () => {
      if (
        compatibilityLeaseId !== leaseId ||
        playbackSuspended.value
      ) {
        return
      }
      const mediaSessionId = activeMediaSessionId
      if (!mediaSessionId) return
      void keepCameraCompatibilityLease(
        props.camera.id,
        leaseId,
        mediaSessionId
      ).catch(() => {
        if (
          compatibilityLeaseId !== leaseId ||
          playbackSuspended.value
        ) {
          return
        }
        error.value =
          t("live.tile.errors.compatibilityLeaseExpired")
        descriptor.value = null
        loading.value = false
        destroyPlayer()
        scheduleReconnect()
      })
    },
    10_000
  )
}

function liveDiagnosticMessage(caught: unknown): string {
  if (caught instanceof ApiClientError) {
    const code = caught.code ? ` [${caught.code}]` : ""
    const requestId = caught.requestId
      ? ` · request ${caught.requestId}`
      : ""
    return `${caught.message}${code}${requestId}`
  }
  return errorMessage(caught)
}

function combinedTransportFailure(
  fallback: string
): string {
  return lastWebRtcFailure.value
    ? t("live.tile.errors.transportFallbackFailed", {
        webrtc: lastWebRtcFailure.value,
        fallback
      })
    : fallback
}

function hlsFatalReason(data: {
  type?: string
  details?: string
  response?: { code?: number }
}): string {
  const details = [
    data.type,
    data.details,
    typeof data.response?.code === "number"
      ? `HTTP ${data.response.code}`
      : null
  ].filter(Boolean).join(" · ")

  return t("live.tile.errors.hlsFatal", {
    details: details || t("live.tile.errors.unknownPlaybackFailure")
  })
}

function nativeVideoFailure(): string {
  const mediaError = video.value?.error
  if (!mediaError) {
    return t("live.tile.errors.playbackFailed")
  }

  const key = mediaError.code === 1
    ? "aborted"
    : mediaError.code === 2
      ? "network"
      : mediaError.code === 3
        ? "decode"
        : mediaError.code === 4
          ? "unsupported"
          : "unknown"
  return t(`live.tile.errors.media.${key}`)
}

class PlaybackCancelledError extends Error {
  constructor() {
    super("Live playback attempt was cancelled.")
    this.name = "PlaybackCancelledError"
  }
}

function requireActivePlayback(
  attemptGeneration: number
): void {
  if (
    generation !== attemptGeneration ||
    playbackSuspended.value
  ) {
    throw new PlaybackCancelledError()
  }
}

class FirstFrameTimeoutError extends Error {
  constructor(
    readonly transport: "webrtc" | "hls",
    readonly timeoutMs: number
  ) {
    super(
      t("live.tile.errors.firstFrameTimeout", {
        transport: transport.toUpperCase(),
        seconds: Math.round(timeoutMs / 1000)
      })
    )
    this.name = "FirstFrameTimeoutError"
  }
}

async function firstFrameTimeoutReason(
  failure: FirstFrameTimeoutError
): Promise<string> {
  const base = failure.message
  const mediaSessionId = activeMediaSessionId
  if (!mediaSessionId) return base

  try {
    const diagnostic = await getCameraLiveDiagnostics(
      props.camera.id,
      requestedQuality.value,
      mediaSessionId
    )
    if (diagnostic.state === "source_offline") {
      return t("live.tile.errors.sourceOffline", {
        base
      })
    }
    if (diagnostic.state === "video_missing") {
      return t("live.tile.errors.videoMissing", {
        base
      })
    }
    if (diagnostic.state === "video_not_ready") {
      return t("live.tile.errors.videoNotReady", {
        base,
        codec: diagnostic.codec || t("live.tile.errors.unknownCodec")
      })
    }
    const shape = (
      diagnostic.width &&
      diagnostic.height
    )
      ? `${diagnostic.width}×${diagnostic.height}`
      : t("live.tile.errors.unknownResolution")
    return t("live.tile.errors.browserNoFrame", {
      base,
      codec: diagnostic.codec || t("live.tile.errors.unknownCodec"),
      resolution: shape
    })
  } catch (caught) {
    return t("live.tile.errors.diagnosticUnavailable", {
      base,
      reason: liveDiagnosticMessage(caught)
    })
  }
}

function waitForFirstVideoFrame(
  element: HTMLVideoElement,
  transport: "webrtc" | "hls",
  timeoutMs: number,
  attemptGeneration: number,
  phaseStartedAt: number | null = null
): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false
    let playbackStartRequested = false
    let frameCallbackId: number | null = null

    const cleanup = () => {
      window.clearTimeout(timeout)
      element.removeEventListener("playing", handleReady)
      element.removeEventListener("loadeddata", handleReady)
      element.removeEventListener(
        "loadedmetadata",
        startPlaybackIfReady
      )
      element.removeEventListener(
        "canplay",
        startPlaybackIfReady
      )
      element.removeEventListener("error", handleError)
      if (
        frameCallbackId !== null &&
        typeof element.cancelVideoFrameCallback === "function"
      ) {
        element.cancelVideoFrameCallback(frameCallbackId)
      }
    }

    const finish = () => {
      if (settled) return
      if (
        generation !== attemptGeneration ||
        playbackSuspended.value
      ) {
        fail(new PlaybackCancelledError())
        return
      }
      settled = true
      cleanup()
      const now = performance.now()
      if (
        telemetry.value.firstFrameMs === null &&
        streamStartedAt > 0
      ) {
        telemetry.value.firstFrameMs = Math.max(
          0,
          now - streamStartedAt
        )
      }
      if (
        phaseStartedAt !== null &&
        transport === "webrtc"
      ) {
        telemetry.value.answerToFrameMs = Math.max(
          0,
          now - phaseStartedAt
        )
      }
      resolve()
    }

    const fail = (reason: string | Error) => {
      if (settled) return
      settled = true
      cleanup()
      reject(
        reason instanceof Error
          ? reason
          : new Error(reason)
      )
    }

    const startPlaybackIfReady = () => {
      if (settled || playbackStartRequested) return
      if (
        generation !== attemptGeneration ||
        playbackSuspended.value
      ) {
        fail(new PlaybackCancelledError())
        return
      }
      if (
        element.srcObject === null &&
        !element.currentSrc &&
        !element.getAttribute("src")
      ) {
        return
      }

      playbackStartRequested = true
      void element.play().catch((caught) => {
        fail(
          t("live.tile.errors.playStartFailed", {
            transport: transport.toUpperCase(),
            reason: errorMessage(caught)
          })
        )
      })
    }

    const handleReady = () => {
      startPlaybackIfReady()
      if (
        typeof element.requestVideoFrameCallback !== "function" &&
        element.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
      ) {
        finish()
      }
    }

    const handleError = () => {
      fail(nativeVideoFailure())
    }

    const timeout = window.setTimeout(() => {
      if (
        generation !== attemptGeneration ||
        playbackSuspended.value
      ) {
        fail(new PlaybackCancelledError())
        return
      }
      fail(
        new FirstFrameTimeoutError(
          transport,
          timeoutMs
        )
      )
    }, timeoutMs)

    element.addEventListener("playing", handleReady)
    element.addEventListener("loadeddata", handleReady)
    element.addEventListener(
      "loadedmetadata",
      startPlaybackIfReady
    )
    element.addEventListener(
      "canplay",
      startPlaybackIfReady
    )
    element.addEventListener("error", handleError)

    if (
      typeof element.requestVideoFrameCallback === "function"
    ) {
      frameCallbackId =
        element.requestVideoFrameCallback(() => finish())
    } else {
      handleReady()
    }

    // setRemoteDescription() may resolve before WebRTC ontrack binds
    // srcObject. A source-less play() rejection must not force HLS fallback.
    startPlaybackIfReady()
  })
}

function releaseWebRtcSession(): void {
  clearStatsTimer()
  const peer = rtcPeer
  const location = whepLocation
  rtcPeer = null
  whepLocation = null

  if (peer) {
    peer.ontrack = null
    peer.onconnectionstatechange = null
    peer.close()
  }
  if (location) {
    void deleteCameraWhepSession(location).catch(() => undefined)
  }
}

function destroyPlayer(): void {
  generation += 1
  clearTokenRefresh()
  clearReconnect()
  hls?.destroy()
  hls = null
  releaseWebRtcSession()
  releaseCompatibilityLease()
  releaseMediaSession()
  activeTransport.value = null
  playing.value = false

  if (video.value) {
    video.value.pause()
    video.value.srcObject = null
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

function waitForIceGatheringComplete(
  peer: RTCPeerConnection,
  timeoutMs: number
): Promise<void> {
  if (peer.iceGatheringState === "complete") {
    return Promise.resolve()
  }

  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      peer.removeEventListener(
        "icegatheringstatechange",
        handleChange
      )
      window.clearTimeout(timeout)
      resolve()
    }
    const handleChange = () => {
      if (peer.iceGatheringState === "complete") {
        finish()
      }
    }
    const timeout = window.setTimeout(finish, timeoutMs)
    peer.addEventListener(
      "icegatheringstatechange",
      handleChange
    )
  })
}

function webRtcConnectionFailure(
  peer: RTCPeerConnection,
  iceServerFailure: string | null
): string {
  const connectionFailure = t(
    "live.tile.errors.webRtcConnectionFailed",
    { ice: peer.iceConnectionState }
  )
  return iceServerFailure
    ? t("live.tile.errors.webRtcIceConfigFailed", {
        connection: connectionFailure,
        reason: iceServerFailure
      })
    : connectionFailure
}

async function waitForWebRtcFirstFrame(
  peer: RTCPeerConnection,
  element: HTMLVideoElement,
  iceServerFailure: string | null,
  attemptGeneration: number,
  phaseStartedAt: number
): Promise<void> {
  const handleConnectionFailure = () => {
    if (
      rtcPeer !== peer ||
      generation !== attemptGeneration ||
      playbackSuspended.value ||
      peer.connectionState !== "failed"
    ) {
      return
    }
    rejectConnectionFailure?.(
      new Error(
        webRtcConnectionFailure(
          peer,
          iceServerFailure
        )
      )
    )
  }

  let rejectConnectionFailure:
    ((reason: Error) => void) | null = null
  const connectionFailure = new Promise<never>(
    (_resolve, reject) => {
      rejectConnectionFailure = reject
    }
  )

  peer.addEventListener(
    "connectionstatechange",
    handleConnectionFailure
  )
  handleConnectionFailure()

  try {
    await Promise.race([
      waitForFirstVideoFrame(
        element,
        "webrtc",
        WEBRTC_FIRST_FRAME_TIMEOUT_MS,
        attemptGeneration,
        phaseStartedAt
      ),
      connectionFailure
    ])
  } finally {
    peer.removeEventListener(
      "connectionstatechange",
      handleConnectionFailure
    )
    rejectConnectionFailure = null
  }
}

async function attachWebRtc(
  stream: CameraLiveStream,
  attemptGeneration: number
): Promise<void> {
  if (typeof RTCPeerConnection === "undefined") {
    throw new Error(t("live.tile.errors.webRtcUnavailable"))
  }

  await nextTick()
  requireActivePlayback(attemptGeneration)
  const element = video.value
  if (!element) {
    throw new Error(t("live.tile.errors.videoUnavailable"))
  }

  releaseWebRtcSession()

  const mediaSessionId = activeMediaSessionId
  if (!mediaSessionId) {
    throw new Error(
      t("live.tile.errors.mediaSessionUnavailable")
    )
  }

  const iceServerFailure = stream.ice_error
  const iceServers: RTCIceServer[] =
    stream.ice_servers.map(
      (server) => ({
        urls: server.urls,
        username: server.username,
        credential: server.credential
      })
    )

  const peer = new RTCPeerConnection({
    iceServers,
    iceCandidatePoolSize: 1
  })
  const remoteStream = new MediaStream()
  rtcPeer = peer

  peer.addTransceiver("video", { direction: "recvonly" })
  if (stream.has_audio && props.audioEnabled) {
    peer.addTransceiver("audio", { direction: "recvonly" })
  }

  peer.ontrack = (event) => {
    if (!remoteStream.getTrackById(event.track.id)) {
      remoteStream.addTrack(event.track)
    }
    if (element.srcObject !== remoteStream) {
      element.srcObject = remoteStream
    }
  }

  try {
    const offer = await peer.createOffer()
    const iceStartedAt = performance.now()
    await peer.setLocalDescription(offer)
    await waitForIceGatheringComplete(
      peer,
      iceServers.length ? 2500 : 800
    )
    requireActivePlayback(attemptGeneration)
    if (rtcPeer !== peer) {
      throw new PlaybackCancelledError()
    }
    telemetry.value.iceGatherMs = Math.max(
      0,
      performance.now() - iceStartedAt
    )

    const offerSdp = peer.localDescription?.sdp
    if (!offerSdp) {
      throw new Error(t("live.tile.errors.offerUnavailable"))
    }

    const whepStartedAt = performance.now()
    const whep = await createCameraWhepSession(
      props.camera.id,
      requestedQuality.value,
      mediaSessionId,
      offerSdp
    )
    telemetry.value.whepMs = Math.max(
      0,
      performance.now() - whepStartedAt
    )
    if (
      generation !== attemptGeneration ||
      playbackSuspended.value ||
      rtcPeer !== peer
    ) {
      void deleteCameraWhepSession(whep.location).catch(
        () => undefined
      )
      throw new PlaybackCancelledError()
    }

    whepLocation = whep.location
    await peer.setRemoteDescription({
      type: "answer",
      sdp: whep.answerSdp
    })
    requireActivePlayback(attemptGeneration)
    if (rtcPeer !== peer) {
      throw new PlaybackCancelledError()
    }
    const answerAppliedAt = performance.now()
    activeTransport.value = "webrtc"
    startStatsTimer(peer)
    await waitForWebRtcFirstFrame(
      peer,
      element,
      iceServerFailure,
      attemptGeneration,
      answerAppliedAt
    )

    const handleEstablishedConnectionFailure = () => {
      if (
        rtcPeer !== peer ||
        peer.connectionState !== "failed" ||
        playbackSuspended.value
      ) {
        return
      }
      error.value = webRtcConnectionFailure(
        peer,
        iceServerFailure
      )
      descriptor.value = null
      loading.value = false
      destroyPlayer()
      scheduleReconnect()
    }
    peer.onconnectionstatechange =
      handleEstablishedConnectionFailure
    handleEstablishedConnectionFailure()
  } catch (caught) {
    if (rtcPeer === peer) {
      releaseWebRtcSession()
    }
    throw caught
  }
}

async function attachHls(
  stream: CameraLiveStream,
  attemptGeneration: number
): Promise<void> {
  await nextTick()
  requireActivePlayback(attemptGeneration)
  const element = video.value
  if (!element) {
    throw new Error(t("live.tile.errors.videoUnavailable"))
  }

  releaseWebRtcSession()
  if (element.srcObject) {
    element.pause()
    element.srcObject = null
  }
  element.removeAttribute("src")
  element.load()
  const source = browserMediaUrl(stream.hls_url)

  if (element.canPlayType("application/vnd.apple.mpegurl")) {
    activeTransport.value = "hls"
    element.src = source
    try {
      await waitForFirstVideoFrame(
        element,
        "hls",
        HLS_FIRST_FRAME_TIMEOUT_MS,
        attemptGeneration
      )
    } catch (caught) {
      if (caught instanceof FirstFrameTimeoutError) {
        throw new Error(
          await firstFrameTimeoutReason(caught)
        )
      }
      throw caught
    }
    return
  }

  if (!Hls.isSupported()) {
    throw new Error(t("live.tile.errors.hlsUnsupported"))
  }

  const player = new Hls({
    lowLatencyMode: true,
    backBufferLength: 12,
    maxBufferLength: 18,
    liveSyncDurationCount: 2
  })
  hls = player

  let firstFrameReady = false
  let rejectStartupFailure:
    ((reason: Error) => void) | null = null
  const startupFailure = new Promise<never>(
    (_resolve, reject) => {
      rejectStartupFailure = reject
    }
  )
  const handleHlsError = (
    _event: string,
    data: {
      fatal: boolean
      type?: string
      details?: string
      response?: { code?: number }
    }
  ) => {
    if (
      !data.fatal ||
      generation !== attemptGeneration ||
      playbackSuspended.value ||
      hls !== player
    ) {
      return
    }
    const reason = hlsFatalReason(data)
    if (!firstFrameReady) {
      rejectStartupFailure?.(new Error(reason))
      return
    }
    error.value = combinedTransportFailure(reason)
    descriptor.value = null
    loading.value = false
    destroyPlayer()
    scheduleReconnect()
  }

  player.on(Hls.Events.ERROR, handleHlsError)
  activeTransport.value = "hls"
  player.loadSource(source)
  player.attachMedia(element)
  try {
    await Promise.race([
      waitForFirstVideoFrame(
        element,
        "hls",
        HLS_FIRST_FRAME_TIMEOUT_MS,
        attemptGeneration
      ),
      startupFailure
    ])
    firstFrameReady = true
    rejectStartupFailure = null
  } catch (caught) {
    rejectStartupFailure = null
    if (hls === player) {
      player.destroy()
      hls = null
    }
    if (caught instanceof FirstFrameTimeoutError) {
      throw new Error(
        await firstFrameTimeoutReason(caught)
      )
    }
    throw caught
  }
}

async function attachPreferredStream(
  stream: CameraLiveStream,
  attemptGeneration: number
): Promise<CameraLiveStream> {
  requireActivePlayback(attemptGeneration)
  const transports = resolveLivePlaybackTransports(
    stream,
    detectLivePlaybackCapabilities(video.value)
  )

  let webRtcDiagnostic: Promise<string> | null = null

  if (transports.includes("webrtc")) {
    try {
      await attachWebRtc(
        stream,
        attemptGeneration
      )
      lastWebRtcFailure.value = null
      return stream
    } catch (caught) {
      if (caught instanceof PlaybackCancelledError) {
        throw caught
      }
      requireActivePlayback(attemptGeneration)
      // WHEP is preferred but never blocks a compatible HLS fallback.
      if (caught instanceof FirstFrameTimeoutError) {
        const initial = caught.message
        lastWebRtcFailure.value = initial
        webRtcDiagnostic = firstFrameTimeoutReason(caught).then(
          (reason) => {
            if (lastWebRtcFailure.value === initial) {
              lastWebRtcFailure.value = reason
            }
            return reason
          }
        )
      } else {
        lastWebRtcFailure.value = liveDiagnosticMessage(caught)
      }
    }
  }

  let originalHlsFailure: string | null = null
  requireActivePlayback(attemptGeneration)
  if (transports.includes("hls")) {
    try {
      await attachHls(
        stream,
        attemptGeneration
      )
      return stream
    } catch (caught) {
      if (caught instanceof PlaybackCancelledError) {
        throw caught
      }
      originalHlsFailure = liveDiagnosticMessage(caught)
    }
  }

  requireActivePlayback(attemptGeneration)
  const mediaSessionId = activeMediaSessionId
  if (!mediaSessionId) {
    throw new Error(t("live.tile.errors.mediaSessionUnavailable"))
  }

  let compatible: CameraLiveStream
  try {
    compatible = await getCameraCompatibleLiveStream(
      props.camera.id,
      requestedQuality.value,
      mediaSessionId
    )
    requireActivePlayback(attemptGeneration)
    activateCompatibilityLease(compatible)
    await attachHls(
      compatible,
      attemptGeneration
    )
    return compatible
  } catch (caught) {
    if (caught instanceof PlaybackCancelledError) {
      throw caught
    }
    const compatibilityFailure = liveDiagnosticMessage(caught)
    if (webRtcDiagnostic) {
      await webRtcDiagnostic
      requireActivePlayback(attemptGeneration)
    }
    const fallbackFailure = originalHlsFailure
      ? t("live.tile.errors.compatibilityFallbackFailed", {
          hls: originalHlsFailure,
          compatibility: compatibilityFailure
        })
      : compatibilityFailure
    throw new Error(
      combinedTransportFailure(fallbackFailure)
    )
  }
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

async function loadStream(
  options: { preserveError?: boolean } = {}
): Promise<void> {
  if (playbackSuspended.value) {
    loading.value = false
    return
  }

  const preserveError = options.preserveError === true
  clearReconnect()
  if (preserveError) {
    reconnecting.value = true
  }
  releaseWebRtcSession()
  releaseCompatibilityLease()
  releaseMediaSession()
  const currentGeneration = ++generation
  streamStartedAt = performance.now()
  telemetry.value = {
    ...telemetry.value,
    bitrateKbps: null,
    packetLossPct: null,
    rttMs: null,
    jitterMs: null,
    relay: null,
    localCandidateType: null,
    remoteCandidateType: null,
    candidateProtocol: null,
    relayProtocol: null,
    sessionSeconds: null,
    firstFrameMs: null,
    descriptorMs: null,
    iceGatherMs: null,
    whepMs: null,
    answerToFrameMs: null
  }
  clearTokenRefresh()
  hls?.destroy()
  hls = null
  descriptor.value = null
  if (!preserveError) {
    error.value = null
  }
  lastWebRtcFailure.value = null
  loading.value = true
  playing.value = false

  try {
    const descriptorStartedAt = performance.now()
    const stream = await getCameraLiveStream(
      props.camera.id,
      requestedQuality.value
    )
    telemetry.value.descriptorMs = Math.max(
      0,
      performance.now() - descriptorStartedAt
    )
    if (
      generation !== currentGeneration ||
      playbackSuspended.value
    ) {
      void revokeCameraMediaSession(
        props.camera.id,
        stream.media_session_id
      ).catch(() => undefined)
      return
    }
    activeMediaSessionId = stream.media_session_id
    const playableStream = await attachPreferredStream(
      stream,
      currentGeneration
    )
    requireActivePlayback(currentGeneration)
    descriptor.value = playableStream
    error.value = null
    reconnecting.value = false
    reconnectAttempt = 0
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
    error.value = liveDiagnosticMessage(caught)
    releaseWebRtcSession()
    releaseCompatibilityLease()
    releaseMediaSession()
    scheduleReconnect()
  } finally {
    if (generation === currentGeneration) {
      loading.value = false
    }
  }
}

function toggleMute(): void {
  if (!props.audioEnabled) return
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
  error.value = combinedTransportFailure(
    nativeVideoFailure()
  )
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
  () => [
    props.camera.id,
    requestedQuality.value,
    Boolean(props.audioEnabled)
  ] as const,
  (
    [cameraId, quality, audioEnabled],
    [previousCameraId, previousQuality, previousAudioEnabled]
  ) => {
    if (
      cameraId === previousCameraId &&
      quality === previousQuality &&
      previousAudioEnabled &&
      !audioEnabled
    ) {
      return
    }

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

watch(
  () => props.audioEnabled,
  (enabled) => {
    if (enabled) return
    muted.value = true
    if (video.value) {
      video.value.muted = true
    }
  }
)

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
          manuallyStopped
            ? 'play'
            : error
              ? 'warning'
              : playbackSuspended
                ? 'pause'
                : 'cameras'
        "
        :size="26"
      />
      <strong>
        {{
          manuallyStopped
            ? t("live.tile.stopped")
            : error
              ? reconnecting
                ? t("live.tile.reconnecting")
                : t("live.tile.streamUnavailable")
              : playbackSuspended
                ? t("live.tile.paused")
                : t("live.tile.connecting")
        }}
      </strong>
      <span>
        {{
          manuallyStopped
            ? t("live.tile.startPlaybackHint")
            : error ||
              (
                playbackSuspended
                  ? t("live.tile.resumeWhenVisible")
                  : t("live.tile.startingSecureSession")
              )
        }}
      </span>
      <button
        v-if="manuallyStopped"
        class="media-button media-button--text"
        type="button"
        @click.stop="emit('playbackChange', camera.id, true)"
      >
        <UiIcon name="play" :size="14" />
        {{ t("live.tile.startPlayback") }}
      </button>
      <button
        v-else-if="error && !playbackSuspended"
        class="media-button media-button--text"
        type="button"
        @click.stop="retryStream"
      >
        <UiIcon name="refresh" :size="14" />
        {{ t("live.tile.retryNow") }}
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
          <span>{{ camera.location || t("live.tile.noLocation") }}</span>
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
        <span
          v-if="activeTransport"
          class="live-quality-badge"
        >
          {{ activeTransport === "webrtc" ? "RTC" : "HLS" }}
        </span>
        <span
          v-if="descriptor?.compatibility === 'h264_transcode'"
          class="live-quality-badge"
          :title="t('live.tile.compatibilityTranscode', {
            acceleration: descriptor.compatibility_acceleration || 'cpu'
          })"
        >
          H264
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
          :aria-label="t('live.tile.panUp')"
          @pointerdown.stop.prevent="beginPtz(0, 0.6)"
          @pointerleave="endPtz"
        >
          <UiIcon name="chevron-up" :size="15" />
        </button>
        <button
          class="media-button"
          type="button"
          :aria-label="t('live.tile.panLeft')"
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
          :aria-label="t('live.tile.panRight')"
          @pointerdown.stop.prevent="beginPtz(0.6, 0)"
          @pointerleave="endPtz"
        >
          <UiIcon name="chevron-right" :size="15" />
        </button>
        <button
          class="media-button"
          type="button"
          :aria-label="t('live.tile.panDown')"
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
          {{ t("live.tile.zoom") }}
        </button>
        <button
          class="media-button media-button--text"
          type="button"
          @pointerdown.stop.prevent="beginPtz(0, 0, 0.6)"
          @pointerleave="endPtz"
        >
          <UiIcon name="plus" :size="14" />
          {{ t("live.tile.zoom") }}
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
        <template v-if="focused && activeTransport === 'webrtc'">
          <span v-if="telemetry.bitrateKbps !== null">
            {{ Math.round(telemetry.bitrateKbps) }} kb/s
          </span>
          <span v-if="telemetry.rttMs !== null">
            {{ Math.round(telemetry.rttMs) }} ms RTT
          </span>
          <span v-if="telemetry.packetLossPct !== null">
            {{ t("live.tile.packetLoss", { value: telemetry.packetLossPct.toFixed(1) }) }}
          </span>
          <span v-if="telemetry.jitterMs !== null">
            {{ t("live.tile.jitter", { milliseconds: Math.round(telemetry.jitterMs) }) }}
          </span>
          <span v-if="telemetry.relay === true">
            {{ t("live.tile.relay") }}{{
              telemetry.relayProtocol
                ? ` · ${telemetry.relayProtocol}`
                : telemetry.candidateProtocol
                  ? ` · ${telemetry.candidateProtocol}`
                  : ""
            }}
          </span>
          <span v-else-if="telemetry.relay === false">
            {{ t("live.tile.direct") }}{{
              telemetry.candidateProtocol
                ? ` · ${telemetry.candidateProtocol}`
                : ""
            }}
          </span>
          <span
            v-if="
              telemetry.localCandidateType &&
              telemetry.remoteCandidateType
            "
          >
            {{ telemetry.localCandidateType }}→{{
              telemetry.remoteCandidateType
            }}
          </span>
          <span v-if="telemetry.sessionSeconds !== null">
            {{ t("live.tile.sessionSeconds", { seconds: Math.round(telemetry.sessionSeconds) }) }}
          </span>
        </template>
        <template v-if="focused">
          <span v-if="telemetry.descriptorMs !== null">
            API {{ Math.round(telemetry.descriptorMs) }} ms
          </span>
          <span v-if="telemetry.iceGatherMs !== null">
            ICE {{ Math.round(telemetry.iceGatherMs) }} ms
          </span>
          <span v-if="telemetry.whepMs !== null">
            WHEP {{ Math.round(telemetry.whepMs) }} ms
          </span>
          <span v-if="telemetry.answerToFrameMs !== null">
            FRAME {{ Math.round(telemetry.answerToFrameMs) }} ms
          </span>
          <span v-if="telemetry.firstFrameMs !== null">
            {{ t("live.tile.firstFrame", { milliseconds: Math.round(telemetry.firstFrameMs) }) }}
          </span>
        </template>
        <span
          v-if="focused && telemetry.reconnects"
        >
          {{ t("live.tile.reconnectCount", { count: telemetry.reconnects }) }}
        </span>
      </div>

      <div class="live-tile__buttons">
        <button
          class="media-button"
          type="button"
          :aria-label="
            playbackEnabled
              ? t('live.tile.stopPlayback')
              : t('live.tile.startPlayback')
          "
          :title="
            playbackEnabled
              ? t('live.tile.stopPlayback')
              : t('live.tile.startPlayback')
          "
          @click.stop="
            emit(
              'playbackChange',
              camera.id,
              !playbackEnabled
            )
          "
        >
          <UiIcon
            :name="playbackEnabled ? 'pause' : 'play'"
            :size="16"
          />
        </button>

        <button
          v-if="
            camera.ptz_capable &&
            auth.hasPermission('camera.control')
          "
          class="media-button"
          :class="{ 'media-button--active': ptzOpen }"
          type="button"
          :aria-label="t('live.tile.ptzControls')"
          :title="t('live.tile.ptzControls')"
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
              ? t('live.tile.stopManualRecording')
              : t('live.tile.startManualRecording')
          "
          :title="
            manualRecordingActive
              ? t('live.tile.stopManualRecording')
              : t('live.tile.startManualRecording')
          "
          @click.stop="toggleManualRecording"
        >
          <UiIcon name="record" :size="16" />
        </button>

        <button
          class="media-button"
          type="button"
          :aria-label="t('live.tile.downloadSnapshot')"
          :title="t('live.tile.snapshot')"
          @click.stop="downloadSnapshot"
        >
          <UiIcon name="snapshot" :size="16" />
        </button>

        <button
          v-if="descriptor?.has_audio && audioEnabled"
          class="media-button"
          type="button"
          :aria-label="muted ? t('live.tile.unmuteCamera') : t('live.tile.muteCamera')"
          :title="muted ? t('live.tile.unmute') : t('live.tile.mute')"
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
          :aria-label="t('live.tile.focusCamera')"
          :title="t('live.tile.focusCamera')"
          @click.stop="emit('focus', camera.id)"
        >
          <UiIcon name="focus" :size="16" />
        </button>

        <button
          class="media-button"
          type="button"
          :aria-label="t('live.tile.fullscreenCamera')"
          :title="t('live.tile.fullscreen')"
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
