import { useMemo, useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { CalendarRange, Layers, Play, TriangleAlert } from "lucide-react"

import {
  MAX_ALIGNED_CAMERAS,
  MIN_ALIGNED_CAMERAS,
  availabilityLabel,
  gapReasonLabel,
  type PlaybackTimelineView,
  type TimelineDetail,
  type TimelineEventMarker,
} from "../api/playback"
import { categoryLabel } from "../api/events"
import { normalizeConnectivity } from "../api/cameras"
import {
  useAlignedTimelines,
  useCameraTimeline,
  useCameras,
  useSystemSettings,
} from "../lib/queries"
import { localInputToUtcIso } from "../lib/exportValidation"
import {
  axisTicks,
  bucketMinutes,
  defaultDetailFor,
  detailWarning,
  resolveRange,
  DETAIL_OPTIONS,
  RANGE_PRESETS,
  type RangePreset,
} from "../lib/timelineRange"
import { instantMs } from "../playback/session"
import { formatClock, formatSpan } from "../lib/format"
import { Badge, Button, Input, Select } from "../components/ui/primitives"
import {
  Callout,
  Checkbox,
  EmptyState,
  PageHeader,
  Segmented,
  StatusDot,
} from "../components/ui/display"
import { TimelineTrack } from "../components/playback/TimelineTrack"
import { cn } from "../lib/utils"

/**
 * 时间轴：多机位在同一时间窗上的并排对照。
 *
 * The prototype was a per-camera event list with a decorative strip. What the
 * contract actually supports is a *record track* per camera — merged recording
 * ranges, gaps carrying a reason, and event markers — which is a different and
 * more useful thing: it is the only view in the product that answers "was this
 * camera recording, and when did it stop" across several cameras at once.
 *
 * Three contract facts shape the controls:
 *
 * 1. **Two endpoints, and the cheap one needs 2–9 cameras.** `POST
 *    /playback/timeline` returns every track in one response but rejects
 *    fewer than 2 or more than 9 (`schemas.py:96-98`). A single camera goes
 *    through `GET /cameras/{id}/timeline` instead. The cap is the endpoint's,
 *    so the page states it rather than silently trimming the selection.
 * 2. **The detail levels are named for something else.** `day` buckets events
 *    hourly, `hour` every five minutes; only `minute` is literal
 *    (`timeline.py:414-418`). The controls are labelled by bucket size.
 * 3. **Neither the range nor the marker count is capped server-side.** A week
 *    at per-event granularity is a request for tens of thousands of markers,
 *    so the default granularity follows the range and the mismatch is warned
 *    about rather than refused.
 */

function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  } catch {
    return "UTC"
  }
}

type Selection = {
  cameraId: string
  atMs: number
  event: TimelineEventMarker | null
}

export function TimelineView() {
  const navigate = useNavigate()
  const cameras = useCameras()

  const [preset, setPreset] = useState<RangePreset>("today")
  const [custom, setCustom] = useState({ from: "", to: "" })
  const [detail, setDetail] = useState<TimelineDetail>("hour")
  const [selected, setSelected] = useState<string[]>([])
  const [pick, setPick] = useState<Selection | null>(null)

  // A `datetime-local` value has no offset on it. Passing one through as if
  // it were UTC shifts the whole window by the operator's offset — the same
  // trap the export form hit — so it is converted against the system display
  // zone here rather than at the request boundary.
  const settings = useSystemSettings()
  const timeZone = settings.data?.general?.display_timezone ?? browserZone()

  const customUtc = useMemo(() => {
    if (!custom.from || !custom.to) return undefined
    const from = localInputToUtcIso(custom.from, timeZone)
    const to = localInputToUtcIso(custom.to, timeZone)
    return from && to ? { from, to } : undefined
  }, [custom.from, custom.to, timeZone])

  const range = useMemo(
    () => resolveRange(preset, customUtc),
    [preset, customUtc],
  )
  const startMs = instantMs(range.from)
  const endMs = instantMs(range.to)
  const rangeMs = Math.max(0, endMs - startMs)

  const cameraIds = useMemo(
    () => selected.filter((id) => cameras.data?.some((c) => c.id === id)),
    [selected, cameras.data],
  )

  // One request for 2–9 cameras, the single-camera endpoint for exactly one.
  const aligned = useAlignedTimelines(
    cameraIds.length >= MIN_ALIGNED_CAMERAS ? cameraIds : [],
    { from: range.from, to: range.to, detail },
  )
  const single = useCameraTimeline(
    cameraIds.length === 1 ? cameraIds[0] : null,
    { from: range.from, to: range.to, detail },
  )

  const tracks: PlaybackTimelineView[] = useMemo(() => {
    const list = aligned.data ?? (single.data ? [single.data] : [])
    // Keep the caller's ordering: a comparison is easier to read when the
    // rows stay where the operator put them.
    const byCamera = new Map(list.map((t) => [t.camera_id, t]))
    return cameraIds
      .map((id) => byCamera.get(id))
      .filter((t): t is PlaybackTimelineView => Boolean(t))
  }, [aligned.data, single.data, cameraIds])

  const loading = cameraIds.length === 0 ? false : aligned.isPending || single.isPending
  const failed = aligned.error ?? single.error
  const warning = detailWarning(rangeMs, detail)

  const buckets = bucketMinutes(detail)
  const ticks = useMemo(() => axisTicks(startMs, endMs), [startMs, endMs])

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  function changePreset(next: RangePreset) {
    setPreset(next)
    // The granularity follows the range unless the operator has already
    // chosen one; changing the range behind a stale "逐个事件" is how a week
    // of markers gets requested by accident.
    if (next !== "custom") {
      const span =
        next === "7d" ? 7 * 24 * 60 * 60 * 1000 : 24 * 60 * 60 * 1000
      setDetail(defaultDetailFor(span))
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <PageHeader
          title="时间轴"
          description="多个机位在同一时间窗上的录像与事件对照。空缺段按后端给出的原因着色，不画成普通黑条。"
          actions={
            <>
              <Badge variant="outline">
                {cameraIds.length} / {MAX_ALIGNED_CAMERAS} 机位
              </Badge>
              <Badge variant="outline">{formatSpan(rangeMs)}</Badge>
            </>
          }
        />
      </div>

      {/* ------------------------------------------------------- controls */}
      <div className="flex shrink-0 flex-wrap items-end gap-3 border-b border-border px-4 py-3">
        <div className="space-y-1">
          <span className="text-[11px] text-muted-foreground">时间范围</span>
          <Segmented
            value={preset}
            onChange={(v) => changePreset(v as RangePreset)}
            options={RANGE_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
          />
        </div>

        {preset === "custom" && !customUtc && (
          <p className="pb-1.5 text-[11px] text-status-degraded">
            请填写完整的起止时间
          </p>
        )}

        {preset === "custom" && (
          <>
            <label className="space-y-1">
              <span className="text-[11px] text-muted-foreground">开始</span>
              <Input
                type="datetime-local"
                className="w-52"
                value={custom.from}
                aria-label="自定义开始时间"
                onChange={(e) => setCustom((p) => ({ ...p, from: e.target.value }))}
              />
            </label>
            <label className="space-y-1">
              <span className="text-[11px] text-muted-foreground">结束</span>
              <Input
                type="datetime-local"
                className="w-52"
                value={custom.to}
                aria-label="自定义结束时间"
                onChange={(e) => setCustom((p) => ({ ...p, to: e.target.value }))}
              />
            </label>
          </>
        )}

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">事件粒度</span>
          <Select
            className="w-40"
            value={detail}
            aria-label="事件粒度"
            onChange={(e) => setDetail(e.target.value as TimelineDetail)}
          >
            {DETAIL_OPTIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}（{d.bucket}）
              </option>
            ))}
          </Select>
        </label>

        {buckets !== null && (
          <span className="pb-1.5 text-[11px] text-muted-foreground">
            每个标记代表最多 {buckets} 分钟
          </span>
        )}
      </div>

      {warning && (
        <div className="shrink-0 px-4 pt-3">
          <Callout tone="degraded" title="当前组合可能很慢">
            {warning}
          </Callout>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* ------------------------------------------------ camera picker */}
        <aside className="flex w-60 shrink-0 flex-col border-r border-border">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2.5">
            <Layers className="size-4 text-muted-foreground" />
            <span className="text-sm font-semibold">机位</span>
            <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
              {selected.length}
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {(cameras.data ?? []).map((camera) => {
              const on = selected.includes(camera.id)
              const atCap = selected.length >= MAX_ALIGNED_CAMERAS
              return (
                <button
                  key={camera.id}
                  type="button"
                  aria-pressed={on}
                  disabled={!on && atCap}
                  onClick={() => toggle(camera.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50",
                    on && "bg-accent text-accent-foreground",
                  )}
                >
                  <Checkbox checked={on} tabIndex={-1} className="pointer-events-none" />
                  <span className="min-w-0 flex-1 truncate">{camera.name}</span>
                  <StatusDot tone={normalizeConnectivity(camera.connectivity_status)} />
                </button>
              )
            })}
          </div>
          {selected.length === 1 && (
            <p className="shrink-0 border-t border-border px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              单机位走单机位接口；选中 2–9 台时会合并为一次请求。
            </p>
          )}
          {selected.length >= MAX_ALIGNED_CAMERAS && (
            <p className="shrink-0 border-t border-border px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              已达对齐接口上限 {MAX_ALIGNED_CAMERAS} 台。
            </p>
          )}
        </aside>

        {/* ------------------------------------------------------- tracks */}
        <section className="flex min-w-0 flex-1 flex-col">
          {cameraIds.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<CalendarRange />}
                title="选择机位以查看时间轴"
                description="时间轴按机位逐条对照录像覆盖与事件。左侧最多可选 9 台——这是对齐接口本身的限制。"
              />
            </div>
          ) : failed ? (
            <div className="p-4">
              <EmptyState
                icon={<TriangleAlert />}
                title="无法读取时间轴"
                description={failed.message}
              />
            </div>
          ) : loading && tracks.length === 0 ? (
            <div className="space-y-2 p-4">
              {cameraIds.map((id) => (
                <div key={id} className="h-14 animate-pulse rounded-lg bg-muted/40" />
              ))}
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {/* axis */}
              <div className="mb-2 flex pl-40">
                <div className="relative h-4 flex-1">
                  {ticks.map((tick) => (
                    <span
                      key={tick.ms}
                      className="absolute -translate-x-1/2 text-[10px] tabular-nums text-muted-foreground"
                      style={{
                        left: `${((tick.ms - startMs) / Math.max(1, rangeMs)) * 100}%`,
                      }}
                    >
                      {tick.label}
                    </span>
                  ))}
                </div>
              </div>

              <ul className="space-y-3">
                {tracks.map((track) => {
                  const name =
                    cameras.data?.find((c) => c.id === track.camera_id)?.name ??
                    track.camera_id
                  const gapCount = track.gaps?.length ?? 0
                  const eventCount =
                    track.events?.reduce((sum, e) => sum + (e.count || 1), 0) ?? 0
                  return (
                    <li key={track.camera_id} className="flex items-center gap-3">
                      <div className="w-40 shrink-0">
                        <p className="truncate text-xs font-medium">{name}</p>
                        <p className="text-[10px] tabular-nums text-muted-foreground">
                          {[
                            `${track.segments?.length ?? 0} 段`,
                            `${eventCount} 事件`,
                            ...(gapCount > 0 ? [`${gapCount} 处空缺`] : []),
                          ].join(" · ")}
                        </p>
                      </div>
                      <TimelineTrack
                        timeline={track}
                        rangeStartMs={startMs}
                        rangeEndMs={endMs}
                        currentMs={endMs}
                        showEvents
                        height={40}
                        onSeek={(atMs) => setPick({ cameraId: track.camera_id, atMs, event: null })}
                      />
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </section>

        {/* --------------------------------------------------- detail rail */}
        {pick && (
          <aside className="w-72 shrink-0 space-y-3 overflow-y-auto border-l border-border p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">该时刻</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPick(null)}
              >
                关闭
              </Button>
            </div>
            <p className="text-xs tabular-nums text-muted-foreground">
              {formatClock(pick.atMs)}
            </p>
            <Button
              className="w-full"
              onClick={() =>
                navigate({
                  to: "/playback",
                  search: {
                    camera: pick.cameraId,
                    at: new Date(pick.atMs).toISOString(),
                  },
                })
              }
            >
              <Play /> 在回放中打开
            </Button>

            {pick.event ? (
              <EventDetail event={pick.event} />
            ) : (
              <CoverageDetail
                timeline={tracks.find((t) => t.camera_id === pick.cameraId) ?? null}
                atMs={pick.atMs}
              />
            )}
          </aside>
        )}
      </div>
    </div>
  )
}

function EventDetail({ event }: { event: TimelineEventMarker }) {
  const buckets = event.category_counts ?? {}
  const labels = event.label_counts ?? {}
  return (
    <div className="space-y-2 text-xs">
      <p className="font-medium">
        {event.label ? `${categoryLabel(event.category)} · ${event.label}` : categoryLabel(event.category)}
      </p>
      {event.marker_type === "aggregate" && (
        <p className="tabular-nums text-muted-foreground">
          该分桶内共 {event.count} 个事件
        </p>
      )}
      {Object.keys(buckets).length > 0 && (
        <div className="space-y-1">
          <p className="text-muted-foreground">按类别</p>
          {Object.entries(buckets).map(([k, v]) => (
            <p key={k} className="flex justify-between">
              <span>{categoryLabel(k)}</span>
              <span className="tabular-nums">{v}</span>
            </p>
          ))}
        </div>
      )}
      {Object.keys(labels).length > 0 && (
        <div className="space-y-1">
          <p className="text-muted-foreground">按标签</p>
          {Object.entries(labels).slice(0, 8).map(([k, v]) => (
            <p key={k} className="flex justify-between">
              <span className="truncate">{k}</span>
              <span className="tabular-nums">{v}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function CoverageDetail({
  timeline,
  atMs,
}: {
  timeline: PlaybackTimelineView | null
  atMs: number
}) {
  const segment =
    timeline?.segments?.find(
      (s) => instantMs(s.start_at) <= atMs && atMs < instantMs(s.end_at),
    ) ?? null
  const gap =
    timeline?.gaps?.find(
      (g) => instantMs(g.start_at) <= atMs && atMs < instantMs(g.end_at),
    ) ?? null

  if (segment) {
    return (
      <div className="space-y-1 text-xs">
        <p className="flex items-center gap-1.5">
          <StatusDot tone="online" /> 有录像
        </p>
        <p className="text-muted-foreground">
          {availabilityLabel(segment.availability)} ·{" "}
          {formatClock(instantMs(segment.start_at))} –{" "}
          {formatClock(instantMs(segment.end_at))}
        </p>
      </div>
    )
  }
  if (gap) {
    return (
      <div className="space-y-1 text-xs">
        <p className="flex items-center gap-1.5">
          <StatusDot tone="degraded" /> 无录像
        </p>
        <p className="text-muted-foreground">{gapReasonLabel(gap.reason)}</p>
      </div>
    )
  }
  return (
    <p className="text-xs text-muted-foreground">
      该时刻既没有录像段也没有空缺记录。
    </p>
  )
}
