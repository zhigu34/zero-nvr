import { useMemo, useState } from "react"

import { describeLiveSource, type LiveSource } from "../../api/live"
import { createHlsInstance } from "../../live/hlsInstance"
import { useLiveTile } from "../../live/useLiveTile"
import { PlaybackStatusOverlay } from "../playback/PlaybackStatusOverlay"
import { StatusDot, type HealthTone } from "../ui/display"
import { Button } from "../ui/primitives"
import { cn } from "../../lib/utils"

/**
 * One camera in the live wall.
 *
 * The overlay here is the same component the playback grid uses, deliberately:
 * a tile that is not showing a picture owes the operator the same thing in
 * both places — a reason, and a way to act on it.
 */

export interface LiveTileProps {
  cameraId: string
  cameraName: string
  className?: string
}

const STATE_TONE: Record<string, HealthTone> = {
  playing: "online",
  buffering: "degraded",
  starting: "degraded",
  resolving: "degraded",
  unavailable: "offline",
  idle: "unknown",
}

const STATE_TEXT: Record<string, string> = {
  playing: "播放中",
  buffering: "缓冲中",
  starting: "正在连接",
  resolving: "正在获取直播地址",
  unavailable: "无法播放",
  idle: "等待中",
}

const SOURCES: Array<{ value: LiveSource; label: string }> = [
  { value: "auto", label: "自动" },
  { value: "sub", label: "子码流" },
  { value: "main", label: "主码流" },
]

export function LiveTile({ cameraId, cameraName, className }: LiveTileProps) {
  const [source, setSource] = useState<LiveSource>("auto")

  // The factory is module-level, so this is stable across renders and does not
  // feed the re-resolve loop the hook deliberately guards against.
  const createHls = useMemo(() => createHlsInstance, [])

  const { state, stream, videoRef, retryNow } = useLiveTile({
    cameraId,
    source,
    createHls,
  })

  const overlayState =
    state.kind === "unavailable"
      ? "unavailable"
      : state.kind === "playing"
        ? "ready"
        : state.kind === "buffering"
          ? "buffering"
          : state.kind === "starting"
            ? "resolving"
            : "resolving"

  return (
    <div
      className={cn(
        "relative flex flex-col overflow-hidden rounded-lg border border-border bg-black",
        className,
      )}
    >
      <div className="relative flex-1">
        <video
          ref={videoRef}
          className="h-full w-full object-contain"
          playsInline
          muted
        />

        <PlaybackStatusOverlay
          state={overlayState}
          message={state.kind === "unavailable" ? state.reason : null}
          onRetry={state.kind === "unavailable" ? retryNow : undefined}
          retrying={state.kind === "unavailable" && state.retrying}
        />
      </div>

      <div className="flex items-center gap-2 border-t border-border bg-card px-2.5 py-2">
        <StatusDot tone={STATE_TONE[state.kind] ?? "unknown"} />
        <span className="min-w-0 flex-1 truncate text-xs font-medium">
          {cameraName}
        </span>

        <select
          value={source}
          onChange={(event) => setSource(event.target.value as LiveSource)}
          className="rounded border border-border bg-background px-1 py-0.5 text-[11px]"
          aria-label={`${cameraName} 码流选择`}
        >
          {SOURCES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-border bg-card px-2.5 py-1.5">
        <span className="truncate text-[11px] text-muted-foreground">
          {stream ? describeLiveSource(stream) : STATE_TEXT[state.kind]}
        </span>
        {state.kind === "unavailable" ? (
          <Button size="sm" variant="outline" onClick={retryNow}>
            重试
          </Button>
        ) : null}
      </div>
    </div>
  )
}
