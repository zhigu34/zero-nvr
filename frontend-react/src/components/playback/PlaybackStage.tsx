import * as React from "react"

import {
  resolveCameraPlayback,
  type PlaybackResolve,
  type PlaybackTimelineView,
} from "../../api/playback"
import { gapReasonLabel } from "../../api/playback"
import { ReconnectScheduler } from "../../live/reconnect"
import type { TileSyncState } from "../../playback/sync"
import {
  gapAt,
  nextPlayableInstant,
  previousPlayableInstant,
  selectSegmentAt,
} from "../../playback/session"
import { PlaybackStatusOverlay } from "./PlaybackStatusOverlay"
import { cn } from "../../lib/utils"

/**
 * One camera's playback surface.
 *
 * The loop this component drives is the one that actually made the old page
 * fragile: the playhead moves, the segment under it changes, the media has to
 * be re-resolved, and the result may be playable, still-restoring, or a gap
 * with no media at all. Each of those is a different UI state, and conflating
 * them is what produced tiles that either went black or polled forever.
 *
 * Recovery is automatic. A failed resolve schedules its own retry through
 * `ReconnectScheduler` rather than waiting for the user to change something —
 * a camera that comes back has to come back on its own.
 */

export interface PlaybackStageProps {
  cameraId: string | null
  timeline: PlaybackTimelineView | null
  currentMs: number
  /**
   * Bumped on every seek. An in-flight resolve for an older generation is
   * abandoned rather than allowed to attach the wrong clip to the playhead.
   */
  seekGeneration: number
  /** Ask the page to move the playhead. Used by the gap jump targets. */
  onSeek?: (atMs: number) => void
  className?: string
}

interface StageState {
  syncState: TileSyncState
  message: string | null
  retryAfterMs?: number
  mediaUrl: string | null
  offsetMs: number
}

const INITIAL: StageState = {
  syncState: "resolving",
  message: null,
  mediaUrl: null,
  offsetMs: 0,
}

export function PlaybackStage({
  cameraId,
  timeline,
  currentMs,
  seekGeneration,
  onSeek,
  className,
}: PlaybackStageProps) {
  const [state, setState] = React.useState<StageState>(INITIAL)
  const videoRef = React.useRef<HTMLVideoElement | null>(null)
  const generationRef = React.useRef(0)
  const retryTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const schedulerRef = React.useRef<ReconnectScheduler | null>(null)

  const applyResult = React.useCallback((result: PlaybackResolve) => {
    setState((prev) => {
      switch (result.status) {
        case "playable":
          return {
            syncState: "buffering",
            message: null,
            mediaUrl: result.url,
            offsetMs: result.offset_ms,
          }
        case "pending":
          return {
            syncState: "pending",
            message: null,
            mediaUrl: null,
            offsetMs: 0,
            retryAfterMs: result.retry_after_ms,
          }
        case "gap":
          return {
            syncState: "gap",
            message: gapReasonLabel(result.reason),
            mediaUrl: null,
            offsetMs: 0,
          }
      }
    })
  }, [])

  const runResolve = React.useCallback(
    async (id: string, atMs: number) => {
      const generation = ++generationRef.current
      setState((prev) => ({ ...prev, syncState: "resolving", message: null }))

      try {
        const result = await resolveCameraPlayback(
          id,
          new Date(atMs).toISOString(),
        )
        // A response for a playhead the user has already left is discarded
        // rather than allowed to attach the wrong clip.
        if (generation !== generationRef.current) return
        applyResult(result)

        if (result.status === "pending") {
          const delay = Math.max(500, result.retry_after_ms)
          retryTimerRef.current = setTimeout(() => {
            void runResolve(id, atMs)
          }, delay)
        }
      } catch (cause) {
        if (generation !== generationRef.current) return
        setState((prev) => ({
          ...prev,
          syncState: "unavailable",
          message: describeResolveError(cause),
          mediaUrl: null,
        }))
        // Keep trying. A camera that returns should restore itself.
        schedulerRef.current?.schedule()
      }
    },
    [applyResult],
  )

  React.useEffect(() => {
    if (!cameraId) return
    schedulerRef.current?.stop()
    schedulerRef.current = new ReconnectScheduler({
      attempt: () => runResolve(cameraId, currentMs),
    })
    void runResolve(cameraId, currentMs)
    return () => {
      schedulerRef.current?.stop()
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current)
        retryTimerRef.current = null
      }
    }
    // `currentMs` intentionally excluded: the clock drives a rAF loop, and
    // re-resolving on every frame would hammer the backend. Resolves happen on
    // seek, on camera change, and on a restore completing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, seekGeneration, runResolve])

  // Attach the resolved media exactly once per source. A re-attach would drop
  // buffered data and visibly stall on every resolution.
  React.useEffect(() => {
    const element = videoRef.current
    if (!element || !state.mediaUrl) return
    element.src = state.mediaUrl
    element.load()
  }, [state.mediaUrl])

  const effective = state.syncState

  const jumpPrevious = React.useMemo(() => {
    const target = previousPlayableInstant(timeline, currentMs)
    return target === null || !onSeek ? undefined : () => onSeek(target)
  }, [timeline, currentMs, onSeek])

  const jumpNext = React.useMemo(() => {
    const target = nextPlayableInstant(timeline, currentMs)
    return target === null || !onSeek ? undefined : () => onSeek(target)
  }, [timeline, currentMs, onSeek])

  const currentGap = gapAt(timeline, currentMs)
  const selected = selectSegmentAt(timeline, currentMs)

  return (
    <div
      className={cn(
        "relative aspect-video overflow-hidden rounded-lg border border-border bg-black",
        className,
      )}
      data-stage-state={effective}
    >
      <video
        ref={videoRef}
        className="h-full w-full object-contain"
        playsInline
        muted
        onCanPlay={() =>
          setState((prev) => ({ ...prev, syncState: "ready" }))
        }
        onWaiting={() =>
          setState((prev) =>
            prev.syncState === "ready"
              ? { ...prev, syncState: "buffering" }
              : prev,
          )
        }
        onError={() =>
          setState((prev) => ({
            ...prev,
            syncState: "unavailable",
            message: "媒体元素解码失败",
          }))
        }
      />

      <PlaybackStatusOverlay
        state={effective}
        message={currentGap ? gapReasonLabel(currentGap.reason) : state.message}
        retryAfterMs={state.retryAfterMs}
        onJumpPrevious={jumpPrevious}
        onJumpNext={jumpNext}
        onRetry={() => {
          schedulerRef.current?.retryNow()
        }}
        retrying={effective === "resolving"}
      />

      {selected ? (
        <span className="sr-only" data-testid="active-segment">
          {selected.segment.playback_ref}
        </span>
      ) : null}
    </div>
  )
}

function describeResolveError(cause: unknown): string {
  if (cause instanceof Error) {
    if (/failed to fetch|network/i.test(cause.message)) {
      return "无法连接后端，请检查服务是否运行"
    }
    return cause.message
  }
  return "解析播放地址失败"
}
