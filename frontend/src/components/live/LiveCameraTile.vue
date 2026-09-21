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
  createCameraWhepSession,
  deleteCameraWhepSession,
  getCameraCompatibleLiveStream,
  getCameraLiveStream,
  keepCameraCompatibilityLease,
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

const props = defineProps<{
  camera: CameraSummary
  quality: LiveQuality
  focused?: boolean
  audioEnabled?: boolean
  allowHighQuality?: boolean
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
interface LiveTelemetry {
  bitrateKbps: number | null
  packetLossPct: number | null
  rttMs: number | null
  jitterMs: number | null
  relay: boolean | null
  firstFrameMs: number | null
  reconnects: number
}

const reconnecting = ref(false)
const activeTransport = ref<"webrtc" | "hls" | null>(null)
const telemetry = ref<LiveTelemetry>({
  bitrateKbps: null,
  packetLossPct: null,
  rttMs: null,
  jitterMs: null,
  relay: null,
  firstFrameMs: null,
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

const playbackSuspended = computed(
  () => !pageVisible.value || !tileVisible.value
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

  telemetry.value.reconnects += 1
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
      if (localCandidateId) {
        const local = report.get(localCandidateId)
        if (local) {
          const candidate =
            local as unknown as Record<string, unknown>
          if (candidate.type === "local-candidate") {
            relay = candidate.candidateType === "relay"
          }
        }
      }
    }

    telemetry.value = {
      ...telemetry.value,
      bitrateKbps,
      packetLossPct,
      rttMs,
      jitterMs,
      relay
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
      "Compatibility stream did not return a lease."
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
          "Compatibility stream lease expired. Reconnecting automatically."
        descriptor.value = null
        loading.value = false
        destroyPlayer()
        scheduleReconnect()
      })
    },
    10_000
  )
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
  peer: RTCPeerConnection
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
    const timeout = window.setTimeout(finish, 2500)
    peer.addEventListener(
      "icegatheringstatechange",
      handleChange
    )
  })
}

async function attachWebRtc(
  stream: CameraLiveStream
): Promise<void> {
  if (typeof RTCPeerConnection === "undefined") {
    throw new Error("WebRTC is not available in this browser.")
  }

  await nextTick()
  const element = video.value
  if (!element) {
    throw new Error("Live video element is unavailable.")
  }

  releaseWebRtcSession()
  const peer = new RTCPeerConnection()
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

  peer.onconnectionstatechange = () => {
    if (
      rtcPeer !== peer ||
      peer.connectionState !== "failed" ||
      playbackSuspended.value
    ) {
      return
    }
    error.value =
      "WebRTC was interrupted. Reconnecting automatically."
    descriptor.value = null
    loading.value = false
    destroyPlayer()
    scheduleReconnect()
  }

  try {
    const offer = await peer.createOffer()
    await peer.setLocalDescription(offer)
    await waitForIceGatheringComplete(peer)

    const offerSdp = peer.localDescription?.sdp
    if (!offerSdp) {
      throw new Error("WebRTC offer SDP is unavailable.")
    }

    const mediaSessionId = activeMediaSessionId
    if (!mediaSessionId) {
      throw new Error("Live media session is unavailable.")
    }

    const whep = await createCameraWhepSession(
      props.camera.id,
      requestedQuality.value,
      mediaSessionId,
      offerSdp
    )
    if (rtcPeer !== peer) {
      void deleteCameraWhepSession(whep.location).catch(
        () => undefined
      )
      throw new Error("WebRTC session was superseded.")
    }

    whepLocation = whep.location
    await peer.setRemoteDescription({
      type: "answer",
      sdp: whep.answerSdp
    })
    activeTransport.value = "webrtc"
    startStatsTimer(peer)
    await element.play().catch(() => undefined)
  } catch (caught) {
    if (rtcPeer === peer) {
      releaseWebRtcSession()
    }
    throw caught
  }
}

async function attachHls(
  stream: CameraLiveStream
): Promise<void> {
  await nextTick()
  const element = video.value
  if (!element) return

  releaseWebRtcSession()
  const source = browserMediaUrl(stream.hls_url)

  if (element.canPlayType("application/vnd.apple.mpegurl")) {
    activeTransport.value = "hls"
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
  activeTransport.value = "hls"
  hls.loadSource(source)
  hls.attachMedia(element)
  await element.play().catch(() => undefined)
}

async function attachPreferredStream(
  stream: CameraLiveStream
): Promise<CameraLiveStream> {
  const transports = resolveLivePlaybackTransports(
    stream,
    detectLivePlaybackCapabilities(video.value)
  )

  if (transports.includes("webrtc")) {
    try {
      await attachWebRtc(stream)
      return stream
    } catch {
      // WHEP is preferred but never blocks a compatible HLS fallback.
    }
  }

  if (transports.includes("hls")) {
    await attachHls(stream)
    return stream
  }

  const mediaSessionId = activeMediaSessionId
  if (!mediaSessionId) {
    throw new Error("Live media session is unavailable.")
  }
  const compatible = await getCameraCompatibleLiveStream(
    props.camera.id,
    requestedQuality.value,
    mediaSessionId
  )
  activateCompatibilityLease(compatible)
  await attachHls(compatible)
  return compatible
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
    firstFrameMs: null
  }
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
      void revokeCameraMediaSession(
        props.camera.id,
        stream.media_session_id
      ).catch(() => undefined)
      return
    }
    activeMediaSessionId = stream.media_session_id
    const playableStream = await attachPreferredStream(stream)
    descriptor.value = playableStream
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
  reconnectAttempt = 0
  clearReconnect()
  error.value = null
  if (
    telemetry.value.firstFrameMs === null &&
    streamStartedAt > 0
  ) {
    telemetry.value.firstFrameMs = Math.max(
      0,
      performance.now() - streamStartedAt
    )
  }
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
  () => [
    props.camera.id,
    requestedQuality.value,
    Boolean(props.audioEnabled)
  ],
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
        <span
          v-if="activeTransport"
          class="live-quality-badge"
        >
          {{ activeTransport === "webrtc" ? "RTC" : "HLS" }}
        </span>
        <span
          v-if="descriptor?.compatibility === 'h264_transcode'"
          class="live-quality-badge"
          :title="`Compatibility transcode · ${descriptor.compatibility_acceleration || 'cpu'}`"
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
        <template v-if="focused && activeTransport === 'webrtc'">
          <span v-if="telemetry.bitrateKbps !== null">
            {{ Math.round(telemetry.bitrateKbps) }} kb/s
          </span>
          <span v-if="telemetry.rttMs !== null">
            {{ Math.round(telemetry.rttMs) }} ms RTT
          </span>
          <span v-if="telemetry.packetLossPct !== null">
            {{ telemetry.packetLossPct.toFixed(1) }}% loss
          </span>
          <span v-if="telemetry.jitterMs !== null">
            {{ Math.round(telemetry.jitterMs) }} ms jitter
          </span>
          <span v-if="telemetry.relay === true">Relay</span>
          <span v-else-if="telemetry.relay === false">Direct</span>
        </template>
        <span
          v-if="focused && telemetry.firstFrameMs !== null"
        >
          {{ Math.round(telemetry.firstFrameMs) }} ms first frame
        </span>
        <span
          v-if="focused && telemetry.reconnects"
        >
          {{ telemetry.reconnects }} reconnect{{
            telemetry.reconnects === 1 ? "" : "s"
          }}
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
          v-if="descriptor?.has_audio && audioEnabled"
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
