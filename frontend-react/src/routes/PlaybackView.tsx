import { useCallback, useEffect, useMemo, useState } from "react"
import { Pause, Play, SkipBack, SkipForward } from "lucide-react"

import { Button, Select } from "../components/ui/primitives"
import {
  Callout,
  EmptyState,
  PageHeader,
  Segmented,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import { PlaybackStage } from "../components/playback/PlaybackStage"
import { TimelineTrack } from "../components/playback/TimelineTrack"
import { useMasterClock } from "../hooks/useMasterClock"
import { useCameraTimeline, useCameras } from "../lib/queries"
import {
  gapReasonLabel,
  type TimelineDetail,
} from "../api/playback"
import { gapAt } from "../playback/session"

/**
 * Historical playback, single camera.
 *
 * The window is a fixed wall-clock range rather than a "last N minutes" that
 * slides with the clock: a viewer reading a timeline needs the range to stay
 * put, and a range that moves under the playhead makes a seek land somewhere
 * different from where it was clicked.
 *
 * The playhead itself is owned by `useMasterClock`, which reads a monotonic
 * source rather than the wall clock, so an NTP correction on the host cannot
 * make playback jump.
 */

const WINDOWS = [
  { label: "1 小时", ms: 60 * 60 * 1000 },
  { label: "2 小时", ms: 2 * 60 * 60 * 1000 },
  { label: "6 小时", ms: 6 * 60 * 60 * 1000 },
  { label: "24 小时", ms: 24 * 60 * 60 * 1000 },
] as const

/** Matches the Vue control set; the prototype's 0.25 step was never specified. */
const RATES = [0.5, 1, 2, 4, 8] as const

/** Speed at or above which audio is muted, because it is unintelligible. */
const HIGH_SPEED_MUTE_FROM = 4

export function PlaybackView() {
  const camerasQuery = useCameras()
  const [cameraId, setCameraId] = useState<string | null>(null)
  const [windowMs, setWindowMs] = useState<number>(2 * 60 * 60 * 1000)
  const [anchorMs, setAnchorMs] = useState(() => Date.now())
  const [detail, setDetail] = useState<TimelineDetail>("minute")
  const [seekGeneration, setSeekGeneration] = useState(0)

  // Default to the first camera once the list arrives.
  useEffect(() => {
    if (!cameraId && camerasQuery.data?.[0]) {
      setCameraId(camerasQuery.data[0].id)
    }
  }, [cameraId, camerasQuery.data])

  const range = useMemo(
    () => ({
      from: new Date(anchorMs - windowMs).toISOString(),
      to: new Date(anchorMs).toISOString(),
      detail,
    }),
    [anchorMs, windowMs, detail],
  )

  const timelineQuery = useCameraTimeline(cameraId, range)
  const clock = useMasterClock(anchorMs - windowMs / 2)

  const seek = useCallback(
    (atMs: number) => {
      clock.seek(atMs)
      // Invalidate any resolve still in flight for the previous playhead.
      setSeekGeneration((generation) => generation + 1)
    },
    [clock],
  )

  const currentGap = gapAt(timelineQuery.data ?? null, clock.currentMs)
  const cameraName =
    camerasQuery.data?.find((camera) => camera.id === cameraId)?.name ?? null

  const seekRelative = useCallback(
    (deltaMs: number) => {
      const next = Math.min(
        anchorMs,
        Math.max(anchorMs - windowMs, clock.currentMs + deltaMs),
      )
      seek(next)
    },
    [anchorMs, windowMs, clock, seek],
  )

  if (camerasQuery.isPending) {
    return (
      <div className="p-6">
        <PageHeader title="录像回放" description="正在加载机位列表…" />
      </div>
    )
  }

  if (camerasQuery.isError) {
    return (
      <div className="p-6">
        <PageHeader title="录像回放" />
        <Callout tone="offline" title="无法加载机位列表">
          {describeError(camerasQuery.error)}
        </Callout>
      </div>
    )
  }

  if (!camerasQuery.data.length) {
    return (
      <div className="p-6">
        <PageHeader title="录像回放" />
        <EmptyState
          title="还没有可回放的机位"
          description="先在机位管理中添加并启用摄像机。"
        />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <Toolbar>
        <Select
          value={cameraId ?? ""}
          onChange={(event) => {
            setCameraId(event.target.value)
            setSeekGeneration((generation) => generation + 1)
          }}
          className="w-48"
        >
          {camerasQuery.data.map((camera) => (
            <option key={camera.id} value={camera.id}>
              {camera.name}
            </option>
          ))}
        </Select>

        <Segmented
          options={WINDOWS.map((window_) => ({
            value: String(window_.ms),
            label: window_.label,
          }))}
          value={String(windowMs)}
          onChange={(value) => setWindowMs(Number(value))}
        />

        <ToolbarSpacer />

        <Button
          variant="outline"
          size="sm"
          onClick={() => setAnchorMs(Date.now())}
        >
          回到当前时间
        </Button>
      </Toolbar>

      <div className="flex flex-1 flex-col gap-3 p-4">
        {timelineQuery.isError ? (
          <Callout tone="offline" title="无法加载录像时间轴">
            {describeError(timelineQuery.error)}
          </Callout>
        ) : null}

        <PlaybackStage
          cameraId={cameraId}
          timeline={timelineQuery.data ?? null}
          currentMs={clock.currentMs}
          seekGeneration={seekGeneration}
          onSeek={seek}
        />

        {currentGap ? (
          <Callout tone="degraded" title="当前时刻没有录像">
            {gapReasonLabel(currentGap.reason)}
          </Callout>
        ) : null}

        <div className="flex flex-col gap-2">
          <TimelineTrack
            timeline={timelineQuery.data ?? null}
            rangeStartMs={anchorMs - windowMs}
            rangeEndMs={anchorMs}
            currentMs={clock.currentMs}
            onSeek={seek}
          />

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => seekRelative(-30_000)}
              aria-label="后退 30 秒"
            >
              <SkipBack className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              onClick={clock.toggle}
              aria-label={clock.state === "playing" ? "暂停" : "播放"}
            >
              {clock.state === "playing" ? (
                <Pause className="h-4 w-4" />
              ) : (
                <Play className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => seekRelative(30_000)}
              aria-label="前进 30 秒"
            >
              <SkipForward className="h-4 w-4" />
            </Button>

            <span className="ml-2 font-mono text-xs text-muted-foreground">
              {formatInstant(clock.currentMs)}
            </span>

            <ToolbarSpacer />

            <Segmented
              options={RATES.map((rate) => ({
                value: String(rate),
                label: `${rate}×`,
              }))}
              value={String(clock.playbackRate)}
              onChange={(value) => clock.setRate(Number(value))}
            />
          </div>

          {clock.playbackRate >= HIGH_SPEED_MUTE_FROM ? (
            <p className="text-xs text-muted-foreground">
              {clock.playbackRate}× 播放已静音，高速下音频不可辨识。
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function formatInstant(ms: number): string {
  return new Date(ms).toLocaleString("zh-CN", { hour12: false })
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message
  return "未知错误"
}
