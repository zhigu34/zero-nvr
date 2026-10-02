import { useCallback, useEffect, useRef, useState } from "react"

import {
  getCameraLiveStream,
  keepaliveLiveSession,
  releaseLiveSession,
  type CameraLiveStreamView,
  type LiveSource,
} from "../api/live"
import { FirstFrameGate, type FirstFrameOutcome } from "../live/firstFrame"
import { LiveHlsAttachment } from "../live/hlsAttachment"
import { ReconnectScheduler } from "../live/reconnect"
import { detectLivePlaybackCapabilities } from "./capabilities"
import {
  needsFastPreview,
  resolveLivePlaybackTransports,
  type LivePlaybackCapabilities,
} from "./transports"

/**
 * One live tile, end to end.
 *
 * The subtle part is session lifetime, and it is not symmetrical. Keeping a
 * media session alive only extends the *server-side* lease — it does not
 * re-sign the HLS URL, whose signature is good for 30 minutes and no longer.
 * So a wall left open overnight would keep reporting healthy keepalives while
 * every tile silently went dark. This hook therefore tracks two deadlines and
 * treats the earlier one as the one that matters: the tile is re-resolved
 * before the signature lapses, releasing the old session as it goes so the
 * media server is not holding a lease for a stream nobody is watching.
 */

/** Renew a little before expiry so a slow frame never lands on a dead URL. */
const KEEPALIVE_LEAD_MS = 60_000
const KEEPALIVE_FLOOR_MS = 5_000
/** Re-resolve this far ahead of the HLS signature expiring. */
const SIGNATURE_LEAD_MS = 120_000

export type LiveTileState =
  | { kind: "idle" }
  | { kind: "resolving" }
  | { kind: "starting" }
  | { kind: "playing" }
  | { kind: "buffering" }
  | { kind: "unavailable"; reason: string; retrying: boolean }

export interface UseLiveTileOptions {
  cameraId: string | null
  source?: LiveSource
  /** Injected by tests; real tiles detect this from the video element. */
  capabilities?: LivePlaybackCapabilities
  createHls: (config: typeof import("../live/hlsAttachment").LIVE_HLS_CONFIG) => import("../live/hlsAttachment").HlsLike
  useNativeHls?: boolean
}

export interface UseLiveTile {
  state: LiveTileState
  stream: CameraLiveStreamView | null
  /** True when there is no direct playback path and a preview is needed. */
  showPreview: boolean
  videoRef: (element: HTMLVideoElement | null) => void
  retryNow: () => void
}

export function useLiveTile(options: UseLiveTileOptions): UseLiveTile {
  const { cameraId, source = "auto" } = options

  const [state, setState] = useState<LiveTileState>({ kind: "idle" })
  const [stream, setStream] = useState<CameraLiveStreamView | null>(null)

  const elementRef = useRef<HTMLVideoElement | null>(null)
  const attachmentRef = useRef<LiveHlsAttachment | null>(null)
  const gateRef = useRef<FirstFrameGate | null>(null)
  const schedulerRef = useRef<ReconnectScheduler | null>(null)
  const keepaliveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const signatureTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sessionRef = useRef<{ cameraId: string; sessionId: string } | null>(null)
  const generationRef = useRef(0)

  /**
   * Player construction is held in a ref rather than read from props.
   *
   * A caller passing an inline arrow for `createHls` would otherwise hand this
   * hook a new function identity on every render, which re-creates `load`,
   * which re-runs the load effect, which sets state, which renders again —
   * an unbounded re-resolve loop against the backend. Reading through a ref
   * keeps the effect keyed on things that actually change what is playing.
   */
  const playerConfigRef = useRef({
    createHls: options.createHls,
    useNativeHls: options.useNativeHls ?? false,
    capabilities: options.capabilities,
  })
  playerConfigRef.current = {
    createHls: options.createHls,
    useNativeHls: options.useNativeHls ?? false,
    capabilities: options.capabilities,
  }

  const clearTimers = useCallback(() => {
    if (keepaliveTimerRef.current !== null) {
      clearTimeout(keepaliveTimerRef.current)
      keepaliveTimerRef.current = null
    }
    if (signatureTimerRef.current !== null) {
      clearTimeout(signatureTimerRef.current)
      signatureTimerRef.current = null
    }
  }, [])

  const releaseSession = useCallback(async () => {
    const held = sessionRef.current
    sessionRef.current = null
    if (!held) return
    try {
      await releaseLiveSession(held.cameraId, held.sessionId)
    } catch {
      // A session the server already expired needs no cleanup. Holding the
      // local reference clear is what matters.
    }
  }, [])

  const load = useCallback(
    async (isRetry = false) => {
      const element = elementRef.current
      if (!cameraId || !element) return

      const generation = ++generationRef.current
      setState((prev) =>
        prev.kind === "unavailable" && isRetry
          ? { ...prev, retrying: true }
          : { kind: "resolving" },
      )

      let descriptor: CameraLiveStreamView
      try {
        descriptor = await getCameraLiveStream(cameraId, { source })
      } catch (cause) {
        if (generation !== generationRef.current) return
        setState({
          kind: "unavailable",
          reason:
            cause instanceof Error
              ? `获取直播地址失败：${cause.message}`
              : "获取直播地址失败",
          retrying: false,
        })
        schedulerRef.current?.schedule()
        return
      }
      if (generation !== generationRef.current) return

      // Probe against the real element: what this browser can decode is not
      // a constant, and a capability assumed rather than measured is exactly
      // how a tile ends up silently trying a codec it cannot play.
      const capabilities =
        playerConfigRef.current.capabilities ??
        detectLivePlaybackCapabilities(element)

      const usable = resolveLivePlaybackTransports(descriptor, capabilities)
      if (usable.length === 0) {
        setState({
          kind: "unavailable",
          reason: needsFastPreview(descriptor, capabilities)
            ? "该码流编码暂不支持直接播放，已切换为快速预览"
            : "没有可用的播放通道",
          retrying: false,
        })
        return
      }

      // Replace the previous session only once the new one exists, so a failed
      // re-resolve does not leave the tile with nothing at all.
      await releaseSession()
      sessionRef.current = {
        cameraId,
        sessionId: descriptor.media_session_id,
      }
      setStream(descriptor)
      setState({ kind: "starting" })

      attachmentRef.current?.detach()
      const attachment = new LiveHlsAttachment({
        createHls: playerConfigRef.current.createHls,
        useNativeHls: playerConfigRef.current.useNativeHls,
        onFailure: (message) => {
          setState({ kind: "unavailable", reason: message, retrying: false })
          schedulerRef.current?.schedule()
        },
      })
      attachmentRef.current = attachment
      attachment.attach(element, descriptor.hls_url)

      gateRef.current?.cancel()
      const gate = new FirstFrameGate(element, { timeoutMs: 6_000 })
      gateRef.current = gate
      const outcome: FirstFrameOutcome = await gate.wait()
      if (generation !== generationRef.current) return
      if (outcome.kind === "frame") {
        setState({ kind: "playing" })
        schedulerRef.current?.succeed()
      } else {
        setState({
          kind: "unavailable",
          reason: describeFirstFrame(outcome, descriptor.has_audio),
          retrying: false,
        })
      }

      clearTimers()
      scheduleRenewals(descriptor)
    },
    // `state` is only read to preserve a retrying flag; excluding it keeps the
    // callback stable so it does not tear down the session on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cameraId, source, clearTimers, releaseSession],
  )

  const scheduleRenewals = useCallback(
    (descriptor: CameraLiveStreamView) => {
      const now = Date.now()
      const sessionExpiry = new Date(descriptor.expires_at).getTime()

      // 1. Keep the server-side lease alive.
      const keepaliveDelay = Math.max(
        KEEPALIVE_FLOOR_MS,
        sessionExpiry - now - KEEPALIVE_LEAD_MS,
      )
      keepaliveTimerRef.current = setTimeout(() => {
        void keepaliveLiveSession(descriptor.camera_id, descriptor.media_session_id)
          .then(() => {
            // The lease is extended, but the URL is not re-signed; re-enter
            // through the signature timer rather than assuming one covers the
            // other.
            scheduleRenewals(descriptor)
          })
          .catch(() => {
            schedulerRef.current?.schedule()
          })
      }, keepaliveDelay)

      // 2. Re-resolve before the HLS signature lapses. This is the deadline
      //    that actually ends playback; the keepalive above does not extend it.
      const signatureDelay = Math.max(
        1_000,
        sessionExpiry - now - SIGNATURE_LEAD_MS,
      )
      signatureTimerRef.current = setTimeout(() => {
        void load(true)
      }, signatureDelay)
    },
    [load],
  )

  useEffect(() => {
    if (!cameraId) return

    schedulerRef.current?.stop()
    schedulerRef.current = new ReconnectScheduler({
      attempt: () => load(true),
    })
    void load()

    return () => {
      generationRef.current += 1
      clearTimers()
      schedulerRef.current?.stop()
      gateRef.current?.cancel()
      attachmentRef.current?.detach()
      void releaseSession()
    }
  }, [cameraId, load, clearTimers, releaseSession])

  const retryNow = useCallback(() => {
    schedulerRef.current?.retryNow()
  }, [])

  return {
    state,
    stream,
    showPreview: stream
      ? needsFastPreview(stream, detectLivePlaybackCapabilities(elementRef.current))
      : false,
    videoRef: (element) => {
      elementRef.current = element
    },
    retryNow,
  }
}

function describeFirstFrame(
  outcome: FirstFrameOutcome,
  hasAudio: boolean,
): string {
  if (outcome.kind === "timeout") {
    return hasAudio
      ? "已连接但未收到画面，摄像机可能未出图"
      : "已连接但未收到画面"
  }
  if (outcome.kind === "error") return outcome.message
  if (outcome.kind === "cancelled") return "播放已取消"
  return "播放失败"
}
