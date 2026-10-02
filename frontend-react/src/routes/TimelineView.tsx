import { useState } from "react"
import {
  Calendar,
  Car,
  Clock,
  Crosshair,
  Dog,
  Download,
  Footprints,
  Lock,
  Move,
  Play,
  Timer,
  type LucideIcon,
} from "lucide-react"
import { Badge, Button, Input, Select } from "../components/ui/primitives"
import {
  Callout,
  EmptyState,
  KeyValue,
  PageHeader,
  ProgressBar,
  Segmented,
  StatusDot,
  Toolbar,
  ToolbarSpacer,
  type HealthTone,
} from "../components/ui/display"
import {
  cameras,
  categoryLabel,
  events,
  hourlyEventCount,
  stateLabel,
  type CameraEvent,
} from "../lib/mock"
import { cn } from "../lib/utils"

const RANGES = [
  { value: "today", label: "今天" },
  { value: "24h", label: "24 小时" },
  { value: "7d", label: "7 天" },
  { value: "custom", label: "自定义" },
]

const CATEGORY_ICON: Record<CameraEvent["category"], LucideIcon> = {
  person: Footprints,
  vehicle: Car,
  animal: Dog,
  motion: Move,
  intrusion: Crosshair,
  line: Crosshair,
}

const CATEGORY_TONE: Record<CameraEvent["category"], HealthTone> = {
  person: "online",
  vehicle: "online",
  animal: "degraded",
  motion: "unknown",
  intrusion: "offline",
  line: "degraded",
}

const CATEGORIES = Object.keys(categoryLabel) as CameraEvent["category"][]

const groupOf = (camera: string) =>
  cameras.find((c) => c.name === camera)?.group ?? "其他"

const GROUPS = [...new Set(cameras.map((c) => c.group))]

const peak = hourlyEventCount.reduce(
  (max, b) => (b.count > max.count ? b : max),
  hourlyEventCount[0],
)

/** A thumbnail placeholder: no real image, same trick as the live-view tiles. */
function Thumb({ id }: { id: string }) {
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-md bg-black">
      <div
        className="absolute inset-0 opacity-[0.18]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, #fff 0 1px, transparent 1px 12px)",
        }}
      />
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="rounded bg-black/45 px-1.5 py-0.5 text-[10px] text-white/60">
          静态原型
        </span>
      </div>
      <span className="absolute bottom-1 left-1 rounded bg-black/50 px-1 text-[9px] tabular-nums text-white/60">
        {id}
      </span>
    </div>
  )
}

export function TimelineView() {
  const [range, setRange] = useState("today")
  const [source, setSource] = useState("all")
  const [category, setCategory] = useState<string>("all")
  const [group, setGroup] = useState("all")
  const [minConf, setMinConf] = useState("0")
  const [q, setQ] = useState("")
  const [hour, setHour] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>("ev-09")

  const shown = events.filter(
    (e) =>
      (source === "all" || e.source === source) &&
      (category === "all" || e.category === category) &&
      (group === "all" || groupOf(e.camera) === group) &&
      e.confidence >= Number(minConf) &&
      (q === "" || e.camera.includes(q) || e.id.includes(q)) &&
      (hour === null || e.time.slice(0, 2) === hour),
  )

  const active = events.find((e) => e.id === selected)
  const hourLabel = hour === null ? null : `${hour}:00–${hour}:59`

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="事件时间轴"
        description="跨摄像机的全局事件流。用于回答「昨天傍晚到底有没有人」——先看密度，再看具体事件。"
        actions={
          <Button variant="outline" size="sm">
            <Download /> 导出选中时段
          </Button>
        }
      />

      <Toolbar>
        <Segmented value={range} onChange={setRange} options={RANGES} />
        {range === "custom" && (
          <>
            <Input type="date" className="w-36" defaultValue="2026-10-01" />
            <span className="text-xs text-muted-foreground">至</span>
            <Input type="date" className="w-36" defaultValue="2026-10-02" />
          </>
        )}
        <Select
          className="w-28"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="all">全部来源</option>
          <option value="ONVIF">ONVIF</option>
          <option value="AI 检测">AI 检测</option>
        </Select>
        <Select
          className="w-32"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="all">全部类别</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {categoryLabel[c]}
            </option>
          ))}
        </Select>
        <Select
          className="w-28"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
        >
          <option value="all">全部分组</option>
          {GROUPS.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </Select>
        <Select
          className="w-32"
          value={minConf}
          onChange={(e) => setMinConf(e.target.value)}
        >
          <option value="0">置信度不限</option>
          <option value="0.5">≥ 50%</option>
          <option value="0.7">≥ 70%</option>
          <option value="0.9">≥ 90%</option>
        </Select>
        <Input
          className="w-40"
          placeholder="搜索机位 / 事件 ID"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ToolbarSpacer />
        {hour !== null ? (
          <Button variant="outline" size="sm" onClick={() => setHour(null)}>
            <Calendar /> {hourLabel} · 取消
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">
            点击下方柱状图可锁定时段
          </span>
        )}
      </Toolbar>

      {/* Category chips double as toggles so the common case is one click. */}
      <div className="flex flex-wrap items-center gap-1.5">
        {CATEGORIES.map((c) => {
          const Icon = CATEGORY_ICON[c]
          const on = category === c
          return (
            <button
              key={c}
              type="button"
              onClick={() => setCategory(on ? "all" : c)}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs transition-colors",
                on
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {categoryLabel[c]}
              <span className="tabular-nums opacity-60">
                {events.filter((e) => e.category === c).length}
              </span>
            </button>
          )
        })}
      </div>

      {/* ------------------------------------------------------ density chart */}
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">事件密度</h3>
            <span className="text-xs text-muted-foreground">
              2 小时一桶 · 峰值 {peak.count} / {peak.hour}:00
            </span>
          </div>
          <span className="text-xs text-muted-foreground">
            匹配 {shown.length} / {events.length} 条
          </span>
        </div>

        <div className="mt-3 flex h-28 items-end gap-1.5">
          {hourlyEventCount.map((b) => {
            const on = hour === b.hour
            const h = peak.count > 0 ? (b.count / peak.count) * 100 : 0
            return (
              <button
                key={b.hour}
                type="button"
                onClick={() => setHour(on ? null : b.hour)}
                title={`${b.hour}:00–${b.hour}:59 · ${b.count} 条`}
                className="group flex h-full flex-1 flex-col justify-end gap-1"
              >
                <span
                  className={cn(
                    "w-full rounded-t transition-colors",
                    on
                      ? "bg-primary"
                      : b.count === 0
                        ? "bg-muted"
                        : "bg-primary/50 group-hover:bg-primary/80",
                  )}
                  style={{ height: `${b.count === 0 ? 3 : Math.max(6, h)}%` }}
                />
                <span
                  className={cn(
                    "text-center text-[10px] tabular-nums",
                    on ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {b.hour}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* -------------------------------------------------------- event cards */}
      {shown.length === 0 ? (
        <EmptyState
          icon={<Clock />}
          title="该时段没有事件"
          description="空白是结论，不是故障。若怀疑漏检，先确认机位是否在线、计划时段是否覆盖。"
          action={
            <Button variant="outline" size="sm" onClick={() => setHour(null)}>
              清除时段筛选
            </Button>
          }
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {shown.map((e) => {
            const on = selected === e.id
            return (
              <button
                key={e.id}
                type="button"
                onClick={() => setSelected(on ? null : e.id)}
                className={cn(
                  "rounded-xl border border-border bg-card p-2.5 text-left transition-colors hover:bg-accent/40",
                  on &&
                    "border-primary bg-accent/40 sm:col-span-2 lg:col-span-3 2xl:col-span-4",
                )}
              >
                <div className={cn("flex gap-2.5", on && "flex-col sm:flex-row")}>
                  <div className={cn("w-full shrink-0", on && "sm:w-64")}>
                    <Thumb id={e.id} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <StatusDot tone={CATEGORY_TONE[e.category]} />
                      <span className="truncate text-sm font-medium">
                        {e.camera}
                      </span>
                      <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground">
                        {e.time}
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge
                        variant={e.source === "AI 检测" ? "default" : "secondary"}
                        className="text-[10px]"
                      >
                        {e.source}
                      </Badge>
                      <Badge variant="outline" className="text-[10px]">
                        {categoryLabel[e.category]}
                      </Badge>
                      <span className="text-[11px] font-medium tabular-nums">
                        {(e.confidence * 100).toFixed(0)}%
                      </span>
                      {e.hasRecording ? (
                        <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                          <Lock className="size-3" /> 有关联录像
                        </span>
                      ) : (
                        <span className="text-[10px] text-status-degraded">
                          无关联录像
                        </span>
                      )}
                    </div>

                    {on && (
                      <div className="mt-3 grid gap-x-6 border-t border-border pt-2 sm:grid-cols-2">
                        <KeyValue label="事件 ID">
                          <span className="font-mono text-xs">{e.id}</span>
                        </KeyValue>
                        <KeyValue label="时间">
                          <span className="tabular-nums">
                            {range === "today" ? `2026-10-02 ${e.time}` : e.time}
                          </span>
                        </KeyValue>
                        <KeyValue label="机位分组">{groupOf(e.camera)}</KeyValue>
                        <KeyValue label="状态">
                          <Badge
                            variant={
                              e.state === "new"
                                ? "danger"
                                : e.state === "acknowledged"
                                  ? "warning"
                                  : "muted"
                            }
                          >
                            {stateLabel[e.state]}
                          </Badge>
                        </KeyValue>
                        <div className="py-2 sm:col-span-2">
                          <p className="mb-1 text-xs text-muted-foreground">
                            置信度
                          </p>
                          <ProgressBar
                            value={e.confidence * 100}
                            tone={CATEGORY_TONE[e.category]}
                            showLabel
                          />
                        </div>
                        <div className="flex items-center gap-2 py-2 sm:col-span-2">
                          <Button size="sm">
                            <Play /> 在回放中打开
                          </Button>
                          <Button variant="outline" size="sm">
                            <Timer /> 查看前后 5 分钟
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}

      <Callout tone="degraded" title="密度图统计的是事件，不是画面">
        没有事件不等于没有画面。事件来自 ONVIF 通知与 AI 检测，两者都可能缺席
        （机位未接 AI、计划时段外、检测器离线）。要确认「到底有没有人」，用密度
        图圈出时段，再切到录像回放逐段核对。
      </Callout>

      {active && !shown.some((e) => e.id === active.id) && (
        <p className="text-xs text-muted-foreground">
          当前展开的事件已被筛选条件隐藏。
        </p>
      )}
    </div>
  )
}
