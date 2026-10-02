import { Button, Card } from "../ui/primitives"
import { StatusDot, type HealthTone } from "../ui/display"
import type { TileSyncState } from "../../playback/sync"
import { cn } from "../../lib/utils"

/**
 * The overlay a tile shows when it has no picture.
 *
 * Every state here is a *reason*, not just an absence. The rule this component
 * enforces is that a tile which is not playing must say why, and — when the
 * operator can do something about it — offer the action. A black rectangle
 * with no explanation is the failure mode this exists to prevent.
 *
 * It is a separate component from the player so the states can be exercised
 * without a media element, and so the same overlay serves the live wall and
 * the playback grid.
 */

export interface PlaybackStatusOverlayProps {
  state: TileSyncState
  /** Reason text. Required for anything that is not a transient state. */
  message?: string | null
  /** For `pending`: the backend's own retry hint. */
  retryAfterMs?: number
  /** Shown when a `gap` can be stepped out of. */
  onJumpPrevious?: () => void
  onJumpNext?: () => void
  /** Shown whenever recovery is possible. */
  onRetry?: () => void
  /** True while a retry is in flight, so the button can reflect it. */
  retrying?: boolean
  className?: string
}

const TONE: Record<TileSyncState, HealthTone> = {
  ready: "online",
  gap: "unknown",
  buffering: "degraded",
  resolving: "degraded",
  pending: "degraded",
  unavailable: "offline",
}

const DEFAULT_MESSAGE: Record<TileSyncState, string> = {
  ready: "",
  gap: "该时段没有录像",
  buffering: "缓冲中",
  resolving: "正在解析播放地址",
  pending: "正在从远端归档回源，请稍候",
  unavailable: "播放失败",
}

export function PlaybackStatusOverlay({
  state,
  message,
  retryAfterMs,
  onJumpPrevious,
  onJumpNext,
  onRetry,
  retrying,
  className,
}: PlaybackStatusOverlayProps) {
  if (state === "ready") return null

  const reason = message?.trim() || DEFAULT_MESSAGE[state]
  const canRetry = Boolean(onRetry)
  const showJumps = state === "gap" && Boolean(onJumpPrevious || onJumpNext)

  return (
    <div
      className={cn(
        "absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-background/92 px-4 text-center",
        className,
      )}
      data-tile-state={state}
      role="status"
    >
      <div className="flex items-center gap-2">
        <StatusDot
          tone={TONE[state]}
          pulse={state === "resolving" || state === "pending"}
        />
        <p className="text-sm font-medium">{reason}</p>
      </div>

      {state === "pending" && retryAfterMs ? (
        <p className="text-xs text-muted-foreground">
          约 {Math.round(retryAfterMs / 1000)} 秒后重试
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-center gap-2">
        {showJumps ? (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={onJumpPrevious}
              disabled={!onJumpPrevious}
            >
              上一段
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onJumpNext}
              disabled={!onJumpNext}
            >
              下一段
            </Button>
          </>
        ) : null}

        {canRetry ? (
          <Button size="sm" onClick={onRetry} disabled={retrying}>
            {retrying ? "正在重试…" : "重试"}
          </Button>
        ) : null}
      </div>

      {/* A state with neither a message nor a way out is itself the bug. */}
      {!canRetry && !showJumps && state === "unavailable" ? (
        <p className="text-xs text-muted-foreground">
          切换机位或时间后可重新解析播放地址
        </p>
      ) : null}
    </div>
  )
}

/** Convenience wrapper for a tile that is still empty. */
export function PlaybackTileFrame({
  children,
  className,
}: {
  children?: React.ReactNode
  className?: string
}) {
  return (
    <Card
      className={cn(
        "relative aspect-video overflow-hidden bg-black",
        className,
      )}
    >
      {children}
    </Card>
  )
}
