import { useEffect, useState } from "react"
import {
  Archive,
  Camera,
  ChevronRight,
  Download,
  HardDrive,
  Lock,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  StepBack,
  StepForward,
  Volume2,
  VolumeX,
} from "lucide-react"
import {
  Badge,
  Button,
  Input,
  Select,
  Separator,
} from "../components/ui/primitives"
import {
  Callout,
  EmptyState,
  KeyValue,
  PrototypeNote,
  Segmented,
  StatusDot,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import {
  TODAY,
  cameras,
  categoryLabel,
  segments,
  timelineBlocks,
  timelineEvents,
  type CameraEvent,
  type RecordingSegment,
} from "../lib/mock"
import { cn } from "../lib/utils"

/** The strip renders a fixed 2-hour window; every offset below is minutes into it. */
const WINDOW_MIN = 120
const WINDOW_START = 14 * 60

const RATES = [
  { value: "0.25", label: "0.25x" },
  { value: "0.5", label: "0.5x" },
  { value: "1", label: "1x" },
  { value: "2", label: "2x" },
  { value: "4", label: "4x" },
  { value: "8", label: "8x" },
]

const TICK_LABELS = [0, 20, 40, 60, 80, 100, 120]

const LOCATION_TONE: Record<
  RecordingSegment["location"],
  "default" | "secondary" | "outline"
> = { 本地: "default", 已归档: "secondary", 备份: "outline" }

/** category keys arrive as plain strings from the fixture; narrow them safely. */
function asCategory(label: string): CameraEvent["category"] {
  return label in categoryLabel ? (label as CameraEvent["category"]) : "motion"
}

const CATEGORY_DOT: Record<CameraEvent["category"], string> = {
  person: "bg-primary",
  vehicle: "bg-primary",
  intrusion: "bg-status-offline",
  line: "bg-status-degraded",
  animal: "bg-status-degraded",
  motion: "bg-status-unknown",
}

const EVENTS = timelineEvents.map((e, i) => ({
  key: `${e.at}-${i}`,
  at: e.at,
  category: asCategory(e.label),
}))

function pad(n: number) {
  return String(n).padStart(2, "0")
}

/** Offset (minutes into the window) → wall clock. */
function clockAt(offset: number) {
  const total = Math.max(0, Math.round((WINDOW_START + offset) * 60))
  return `${pad(Math.floor(total / 3600) % 24)}:${pad(Math.floor(total / 60) % 60)}:${pad(total % 60)}`
}

/** "14:45:00" → minutes into the window (negative when outside it). */
function toOffset(hhmmss: string) {
  const [h, m, s] = hhmmss.split(":").map(Number)
  return h * 60 + m + s / 60 - WINDOW_START
}

const clampOffset = (v: number) => Math.max(0, Math.min(WINDOW_MIN, v))

export function PlaybackView() {
  const [camera, setCamera] = useState("前门人行入口")
  const [date, setDate] = useState(TODAY)
  const [jump, setJump] = useState("14:52:08")
  const [rate, setRate] = useState("1")
  const [playhead, setPlayhead] = useState(52)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(true)
  const [focus, setFocus] = useState(false)
  const [selected, setSelected] = useState<string | null>("seg-02")

  const list = segments.filter((s) => s.camera === camera)
  const active = list.find((s) => s.id === selected) ?? list[0]
  const cam = cameras.find((c) => c.name === camera)

  // Gap under the playhead: the strip is never blank without an explanation.
  const currentGap = timelineBlocks.find(
    (b) => b.kind === "gap" && playhead >= b.start && playhead < b.end,
  )
  const gaps = timelineBlocks.filter((b) => b.kind === "gap")

  // Demo playback: 1x moves 15s of footage per 250ms tick, so the whole window
  // plays in ~20s. Real timing comes from the file itself, not from here.
  useEffect(() => {
    if (!playing) return
    if (playhead >= WINDOW_MIN) {
      setPlaying(false)
      return
    }
    const id = window.setInterval(() => {
      setPlayhead((p) => clampOffset(p + 0.25 * Number(rate)))
    }, 250)
    return () => window.clearInterval(id)
  }, [playing, rate, playhead])

  const step = (delta: number) => setPlayhead((p) => clampOffset(p + delta))

  const jumpEvent = (dir: -1 | 1) => {
    const sorted = EVENTS.map((e) => e.at)
    const next =
      dir === 1
        ? sorted.find((at) => at > playhead)
        : [...sorted].reverse().find((at) => at < playhead)
    if (next !== undefined) setPlayhead(next)
  }

  const seekToEvent = (at: number) => {
    setPlayhead(clampOffset(at))
    setSelected(null)
  }

  return (
    <div className="flex h-full flex-col">
      {/* ------------------------------------------------------------ toolbar */}
      <div className="shrink-0 p-4 pb-3">
        <Toolbar>
          <Select
            className="w-44"
            value={camera}
            onChange={(e) => {
              setCamera(e.target.value)
              setSelected(null)
            }}
          >
            {cameras.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
              </option>
            ))}
          </Select>
          <Input
            type="date"
            className="w-36"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          <div className="flex items-center gap-1.5">
            <Input
              className="w-28 font-mono tabular-nums"
              value={jump}
              onChange={(e) => setJump(e.target.value)}
            />
            <Button
              variant="outline"
              size="icon-sm"
              title="跳转到时间点"
              onClick={() => {
                const [h, m, s] = jump.split(":").map(Number)
                setPlayhead(
                  clampOffset((h || 0) * 60 + (m || 0) + (s || 0) / 60 - WINDOW_START),
                )
                setSelected(null)
              }}
            >
              <ChevronRight className="size-3.5" />
            </Button>
          </div>
          <Separator className="mx-1 h-5 w-px" />
          <Segmented
            value={rate}
            onChange={setRate}
            options={RATES.map((r) => ({ value: r.value, label: r.label }))}
          />
          <ToolbarSpacer />
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {cam && <StatusDot tone={cam.health} pulse={playing} />}
            {date} · 14:00–16:00
          </span>
          <Button
            variant="outline"
            size="icon-sm"
            title={focus ? "退出专注" : "专注画面"}
            onClick={() => setFocus((v) => !v)}
          >
            {focus ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
          </Button>
          <Button variant="outline" size="sm">
            <Download /> 导出片段
          </Button>
        </Toolbar>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* ------------------------------------------------------- side listing */}
        {!focus && (
          <aside className="flex w-[260px] shrink-0 flex-col border-r border-border">
            <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
              <span className="text-xs font-medium">当日片段</span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {list.length} 个
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {list.length === 0 ? (
                <EmptyState
                  className="border-0 px-2 py-8"
                  icon={<Camera className="size-6" />}
                  title="该机位当日无录像"
                  description="计划时段外或机位未接入。缺口会显示在下方时间轴上，而不是留白。"
                />
              ) : (
                <ul className="space-y-1.5">
                  {list.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelected(s.id)
                          setPlayhead(clampOffset(toOffset(s.start)))
                          setPlaying(false)
                        }}
                        className={cn(
                          "w-full rounded-lg border border-border bg-card px-2.5 py-2 text-left transition-colors hover:bg-accent",
                          selected === s.id && "border-primary bg-accent",
                        )}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm font-medium tabular-nums">
                            {s.start}
                          </span>
                          {s.protected && (
                            <Lock
                              className="size-3 text-status-degraded"
                              aria-label="已保护录像"
                            />
                          )}
                          <Badge
                            variant={LOCATION_TONE[s.location]}
                            className="ml-auto text-[10px]"
                          >
                            {s.location}
                          </Badge>
                        </div>
                        <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
                          {s.duration} · {s.size}
                        </p>
                        <p className="mt-0.5 text-[11px] text-muted-foreground">
                          {s.resolution} · {s.codec}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="shrink-0 border-t border-border p-2">
              <PrototypeNote>
                「已保护」片段不会被保留策略清理，仅管理员可解除。
              </PrototypeNote>
            </div>
          </aside>
        )}

        {/* ------------------------------------------------------------- stage */}
        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto p-4">
          <div className="mx-auto w-full max-w-5xl space-y-3">
            {/* player */}
            <div className="overflow-hidden rounded-xl border border-border">
              <div className="relative aspect-video w-full bg-black">
                <div
                  className="absolute inset-0 opacity-[0.18]"
                  style={{
                    backgroundImage:
                      "repeating-linear-gradient(45deg, #fff 0 1px, transparent 1px 14px)",
                  }}
                />
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="rounded bg-black/45 px-2 py-0.5 text-[10px] text-white/60">
                    静态原型 · 无真实画面
                  </span>
                </div>

                <div className="absolute inset-x-0 top-0 flex items-center gap-2 bg-gradient-to-b from-black/70 to-transparent p-2.5">
                  <span className="truncate text-xs font-medium text-white">
                    {camera}
                  </span>
                  {active && (
                    <span className="text-[10px] tabular-nums text-white/50">
                      {active.resolution} · {active.codec} · {active.location}
                    </span>
                  )}
                  <span className="ml-auto text-[10px] tabular-nums text-white/60">
                    {clockAt(playhead)}
                  </span>
                </div>

                {currentGap && (
                  <div className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center">
                    <span className="rounded bg-status-degraded/90 px-2 py-1 text-[11px] font-medium text-black">
                      录像缺口 · {currentGap.reason}
                    </span>
                  </div>
                )}
              </div>

              {/* transport */}
              <div className="flex flex-wrap items-center gap-1 border-t border-border bg-card px-2.5 py-2">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="上一个事件"
                  onClick={() => jumpEvent(-1)}
                >
                  <SkipBack className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="上一帧"
                  onClick={() => step(-1 / 60)}
                >
                  <StepBack className="size-3.5" />
                </Button>
                <Button
                  size="icon"
                  title={playing ? "暂停" : "播放"}
                  onClick={() => setPlaying((v) => !v)}
                >
                  {playing ? (
                    <Pause className="size-4" />
                  ) : (
                    <Play className="size-4" />
                  )}
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="下一帧"
                  onClick={() => step(1 / 60)}
                >
                  <StepForward className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="下一个事件"
                  onClick={() => jumpEvent(1)}
                >
                  <SkipForward className="size-3.5" />
                </Button>
                <Separator className="mx-1 h-5 w-px" />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title={muted ? "打开音频" : "静音"}
                  onClick={() => setMuted((v) => !v)}
                >
                  {muted ? (
                    <VolumeX className="size-3.5" />
                  ) : (
                    <Volume2 className="size-3.5" />
                  )}
                </Button>
                <span className="ml-1 text-xs tabular-nums text-muted-foreground">
                  {rate}x · {currentGap ? "缺口" : "连续录制"}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {clockAt(playhead)}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="全屏"
                    onClick={() => setFocus((v) => !v)}
                  >
                    <Maximize2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            </div>

            {/* timeline */}
            {!focus && (
              <div className="space-y-2 rounded-xl border border-border bg-card p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium">时间轴 · 14:00–16:00</p>
                  <p className="text-[11px] text-muted-foreground">
                    {currentGap
                      ? `当前位置：缺口 ${currentGap.reason}`
                      : `已录制 ${EVENTS.length} 个事件标记`}
                  </p>
                </div>

                <div
                  className="relative h-9 cursor-pointer overflow-hidden rounded-md border border-border bg-muted"
                  onClick={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect()
                    setPlayhead(clampOffset(((e.clientX - rect.left) / rect.width) * WINDOW_MIN))
                  }}
                >
                  {timelineBlocks.map((b) => {
                    const on = playhead >= b.start && playhead < b.end
                    const geom = {
                      left: `${(b.start / WINDOW_MIN) * 100}%`,
                      width: `${((b.end - b.start) / WINDOW_MIN) * 100}%`,
                    }
                    if (b.kind === "recorded") {
                      return (
                        <div
                          key={b.start}
                          className={cn(
                            "absolute top-0 h-full bg-primary/70",
                            on && "bg-primary ring-1 ring-inset ring-ring",
                          )}
                          style={geom}
                          title={`已录制 ${clockAt(b.start)}–${clockAt(b.end)}`}
                        />
                      )
                    }
                    return (
                      <div
                        key={b.start}
                        className={cn(
                          "absolute top-0 h-full border-x border-dashed border-status-degraded/70",
                          on && "border-status-degraded",
                        )}
                        style={{
                          ...geom,
                          backgroundImage:
                            "repeating-linear-gradient(45deg, var(--color-status-degraded) 0 2px, transparent 2px 6px)",
                          opacity: on ? 1 : 0.5,
                        }}
                        title={`缺口 ${clockAt(b.start)}–${clockAt(b.end)} · ${b.reason}`}
                      />
                    )
                  })}

                  {EVENTS.map((e) => (
                    <button
                      key={e.key}
                      type="button"
                      title={`${categoryLabel[e.category]} · ${clockAt(e.at)}`}
                      onClick={(ev) => {
                        ev.stopPropagation()
                        seekToEvent(e.at)
                      }}
                      className="absolute top-0 h-full w-2.5 -translate-x-1/2 cursor-pointer"
                      style={{ left: `${(e.at / WINDOW_MIN) * 100}%` }}
                    >
                      <span
                        className={cn(
                          "block size-1.5 rounded-full",
                          CATEGORY_DOT[e.category],
                        )}
                      />
                      <span className="mx-auto block h-[calc(100%-6px)] w-px bg-foreground/30" />
                    </button>
                  ))}

                  <div
                    className="pointer-events-none absolute top-0 h-full w-0.5 bg-foreground"
                    style={{ left: `${(playhead / WINDOW_MIN) * 100}%` }}
                  />
                </div>

                <div className="flex justify-between text-[10px] tabular-nums text-muted-foreground">
                  {TICK_LABELS.map((t) => (
                    <span key={t}>{clockAt(t).slice(0, 5)}</span>
                  ))}
                </div>

                {/* Gap ledger: the reason is always written down, not just on hover. */}
                <div className="flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
                  <span className="text-[11px] text-muted-foreground">缺口：</span>
                  {gaps.map((g) => (
                    <button
                      key={g.start}
                      type="button"
                      onClick={() => setPlayhead(clampOffset(g.start))}
                      className={cn(
                        "rounded border border-status-degraded/40 px-1.5 py-0.5 text-[10px] tabular-nums text-status-degraded transition-colors hover:bg-accent",
                        playhead >= g.start && playhead < g.end && "bg-accent",
                      )}
                    >
                      {clockAt(g.start).slice(0, 5)}–{clockAt(g.end).slice(0, 5)}{" "}
                      {g.reason}
                    </button>
                  ))}
                  <span className="ml-auto text-[10px] text-muted-foreground">
                    已录制 / 缺口 / 事件标记
                  </span>
                </div>
              </div>
            )}

            {/* storage tiers + callout */}
            {!focus && (
              <div className="space-y-2.5">
                <div className="rounded-xl border border-border bg-card p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium">读取层级</span>
                    <Badge variant="default">
                      <HardDrive className="size-3" /> 本地
                    </Badge>
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                    <Badge variant="secondary">
                      <Archive className="size-3" /> 已归档
                    </Badge>
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                    <Badge variant="outline">备份</Badge>
                    <span className="ml-auto text-[11px] text-muted-foreground">
                      先查本地，再回落归档 / 备份
                    </span>
                  </div>
                  <div className="mt-1.5 divide-y divide-border">
                    {gaps.map((g) => (
                      <KeyValue
                        key={g.start}
                        label={`${clockAt(g.start).slice(0, 5)}–${clockAt(g.end).slice(0, 5)}`}
                      >
                        <span className="text-status-degraded">{g.reason}</span>
                      </KeyValue>
                    ))}
                    {active && (
                      <KeyValue label="当前片段">
                        <span className="tabular-nums">
                          {active.start} · {active.size} · {active.location}
                        </span>
                      </KeyValue>
                    )}
                  </div>
                </div>

                <Callout tone="degraded" title="回放不走 ZLM VOD">
                  预览走 ZLM（WHEP / HLS）是因为它是实时流；回放拿到的是
                  FileResponse —— 后端直接从磁盘读出录像文件推给浏览器，不进
                  媒体服务器。因此时间轴上的空白一律是「缺口」并写出原因，不会
                  假装成没有事件。
                </Callout>
              </div>
            )}

            {focus && (
              <Callout tone="degraded" title="回放不走 ZLM VOD">
                专注模式：后端以 FileResponse 直读磁盘文件，不经 ZLM。
              </Callout>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
