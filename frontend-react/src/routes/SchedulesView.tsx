import { useState } from "react"
import { CalendarClock, Clock, Pencil, Play, Plus, Square } from "lucide-react"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/primitives"
import {
  Callout,
  Field,
  KeyValue,
  PageHeader,
  PrototypeNote,
  RowActions,
  Segmented,
  StatCard,
  StatusLabel,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import { schedules, type Schedule } from "../lib/mock"
import { cn } from "../lib/utils"

/* ------------------------------------------------------------- Local maps */

const OBSERVED_META: Record<
  Schedule["observed"],
  { label: string; tone: "online" | "offline" | "degraded" | "unknown" }
> = {
  recording: { label: "录制中", tone: "online" },
  idle: { label: "空闲", tone: "unknown" },
  blocked: { label: "阻塞", tone: "offline" },
  unknown: { label: "未知", tone: "unknown" },
}

const MODE_META: Record<Schedule["mode"], { hint: string; badge: "default" | "secondary" | "outline" }> = {
  连续录制: { hint: "时段内不间断写入", badge: "default" },
  事件触发: { hint: "全程预录缓冲，事件提升为正式片段", badge: "secondary" },
  仅事件: { hint: "无预录时事件仅标记时间点", badge: "outline" },
}

const DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
const HOURS = Array.from({ length: 24 }, (_, i) => i)
const HOUR_LABELS = [0, 3, 6, 9, 12, 15, 18, 21]
/** Fixed "now" so the prototype never drifts between renders. */
const NOW_HOUR = 15

/**
 * The fixture stores the window as human text ("全天", "07:00–22:00"). Anything
 * that does not carry an explicit range is a full day.
 */
function parseWindow(win: string): { start: number; end: number } {
  const m = win.match(/(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})/)
  if (!m) return { start: 0, end: 24 }
  return {
    start: Number(m[1]) + Number(m[2]) / 60,
    end: Number(m[3]) + Number(m[4]) / 60,
  }
}

const FILL = {
  record: "bg-status-recording/70",
  buffer: "bg-status-recording/25",
  event: "bg-status-unknown/20",
  outside: "bg-muted/30",
} as const

type FillKind = keyof typeof FILL

function cellFill(s: Schedule, hour: number): FillKind {
  const { start, end } = parseWindow(s.window)
  if (hour < start || hour >= end) return "outside"
  if (s.mode === "连续录制") return "record"
  return s.prebufferSec > 0 ? "buffer" : "event"
}

/* ------------------------------------------------------------------ Page */

export function SchedulesView() {
  const [q, setQ] = useState("")
  const [mode, setMode] = useState("all")
  const [state, setState] = useState("all")
  const [gridCam, setGridCam] = useState<string>(schedules[0].camera)

  // The time-boxed override. Not a recording mode: it only forces promotion of
  // the prebuffer for a bounded number of minutes.
  const [triggerCam, setTriggerCam] = useState<string>(schedules[0].camera)
  const [triggerMins, setTriggerMins] = useState("30")
  const [trigger, setTrigger] = useState<{ camera: string; minutes: number } | null>(null)

  const rows = schedules.filter((s) => {
    if (mode !== "all" && s.mode !== mode) return false
    if (state === "recording" && s.observed !== "recording") return false
    if (state === "blocked" && s.observed !== "blocked") return false
    return q === "" || s.camera.includes(q)
  })

  const recordingCount = schedules.filter((s) => s.observed === "recording").length
  const blocked = schedules.filter((s) => s.observed === "blocked")
  const buffered = schedules.filter((s) => s.prebufferSec > 0)
  const avgPre = buffered.length
    ? Math.round(buffered.reduce((a, s) => a + s.prebufferSec, 0) / buffered.length)
    : 0

  const gridSchedule = schedules.find((s) => s.camera === gridCam) ?? schedules[0]

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="录制计划"
        description="决定每台机器录不录、录多久。录像全部由计划驱动，无手动录像。状态如实显示观测结果与阻塞原因。"
        actions={
          <>
            <Badge variant="outline" className="text-[11px]">
              计划驱动 · 无手动录像
            </Badge>
            <Button size="sm">
              <Plus /> 新建计划
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="计划总数"
          value={schedules.length}
          unit="路"
          icon={<CalendarClock className="size-4" />}
          hint="每个机位一条生效计划"
        />
        <StatCard label="录制中" value={recordingCount} unit="路" tone="online" />
        <StatCard
          label="阻塞中"
          value={blocked.length}
          unit="路"
          tone={blocked.length ? "offline" : "online"}
          hint={blocked.length ? "计划已启用但录制进程未运行" : "无阻塞"}
        />
        <StatCard
          label="预录平均时长"
          value={avgPre}
          unit="s"
          icon={<Clock className="size-4" />}
          hint={`${buffered.length} / ${schedules.length} 个计划启用预录`}
        />
      </div>

      <Callout tone="online" title="事件不触发「开始录制」">
        录像进程按计划持续以预录缓冲模式运行。事件到达时，只是把已缓冲的画面提升为
        正式录像片段，并不会从事件时刻才开始录。所以事件发生前的预录时长同样有画面
        —— 界面上看不到这段画面，说明问题出在计划或阻塞状态，不是事件没触发。
      </Callout>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card>
          <CardHeader>
            <div className="min-w-0">
              <CardTitle>周计划视图</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                按机位查看 7 天 × 24 小时的计划时段
              </p>
            </div>
            <Select
              className="w-44 shrink-0"
              value={gridCam}
              onChange={(e) => setGridCam(e.target.value)}
            >
              {schedules.map((s) => (
                <option key={s.id} value={s.camera}>
                  {s.camera}
                </option>
              ))}
            </Select>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={MODE_META[gridSchedule.mode].badge}>
                {gridSchedule.mode}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {gridSchedule.window} · {MODE_META[gridSchedule.mode].hint}
              </span>
            </div>

            <WeeklyGrid schedule={gridSchedule} />

            <KeyValue label="预录时长">
              {gridSchedule.prebufferSec > 0 ? (
                <span className="tabular-nums">{gridSchedule.prebufferSec} s</span>
              ) : (
                <span className="text-muted-foreground">未启用</span>
              )}
            </KeyValue>
            <KeyValue label="保留天数">
              <span className="tabular-nums">{gridSchedule.retainDays} 天</span>
            </KeyValue>
            <KeyValue label="观测状态">
              <StatusLabel tone={OBSERVED_META[gridSchedule.observed].tone}>
                {OBSERVED_META[gridSchedule.observed].label}
              </StatusLabel>
            </KeyValue>
          </CardContent>
        </Card>

        <Card className="self-start">
          <CardHeader>
            <CardTitle>临时手动触发</CardTitle>
            <Badge variant="warning">时间盒覆盖</Badge>
          </CardHeader>
          <CardContent className="space-y-1 pt-2">
            <p className="pb-1 text-xs leading-relaxed text-muted-foreground">
              这不是一种录制模式。它只对已有计划做一次性覆盖：到期后录像状态自动回到计划
              所决定的结果，不会写入计划表。
            </p>
            <Field label="机位" htmlFor="trigger-cam">
              <Select
                id="trigger-cam"
                className="w-40"
                value={triggerCam}
                onChange={(e) => setTriggerCam(e.target.value)}
              >
                {schedules.map((s) => (
                  <option key={s.id} value={s.camera}>
                    {s.camera}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="持续时长" htmlFor="trigger-mins">
              <Select
                id="trigger-mins"
                className="w-40"
                value={triggerMins}
                onChange={(e) => setTriggerMins(e.target.value)}
              >
                <option value="15">15 分钟</option>
                <option value="30">30 分钟</option>
                <option value="60">60 分钟</option>
              </Select>
            </Field>
            <div className="flex items-center justify-end gap-2 pt-3">
              {trigger ? (
                <>
                  <Badge variant="danger" className="mr-auto">
                    临时录制中 · {trigger.minutes} 分钟
                  </Badge>
                  <Button variant="outline" size="sm" onClick={() => setTrigger(null)}>
                    <Square /> 停止
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  onClick={() =>
                    setTrigger({
                      camera: triggerCam,
                      minutes: Number(triggerMins),
                    })
                  }
                >
                  <Play /> 启动临时录制
                </Button>
              )}
            </div>
            {trigger && (
              <p className="pt-2 text-[11px] leading-relaxed text-muted-foreground">
                {trigger.camera} · 到期前该机位的观测状态显示为「临时录制」；其余机位不受影响。
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Toolbar>
        <Input
          className="w-48"
          placeholder="搜索机位"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Select
          className="w-32"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="all">全部模式</option>
          <option value="连续录制">连续录制</option>
          <option value="事件触发">事件触发</option>
          <option value="仅事件">仅事件</option>
        </Select>
        <Segmented
          value={state}
          onChange={setState}
          options={[
            { value: "all", label: "全部" },
            { value: "recording", label: "录制中" },
            { value: "blocked", label: "阻塞" },
          ]}
        />
        <span className="text-xs text-muted-foreground">
          {rows.length} / {schedules.length} 条计划
        </span>
        <ToolbarSpacer />
        <Button variant="outline" size="sm">
          <CalendarClock /> 批量套用时段
        </Button>
      </Toolbar>

      {blocked.length > 0 && (
        <Callout tone="offline" title={`${blocked.length} 路计划已阻塞`}>
          <ul className="mt-0.5 space-y-1">
            {blocked.map((s) => (
              <li key={s.id}>
                <span className="font-medium text-foreground">{s.camera}</span>
                ：{s.blockReason}
              </li>
            ))}
          </ul>
        </Callout>
      )}

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <THead>
            <TR>
              <TH>机位</TH>
              <TH>模式</TH>
              <TH>录制时段</TH>
              <TH>预录时长</TH>
              <TH>保留天数</TH>
              <TH>观测状态</TH>
              <TH className="min-w-[220px]">阻塞原因</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((s) => {
              const meta = OBSERVED_META[s.observed]
              const isBlocked = s.observed === "blocked"
              return (
                <TR
                  key={s.id}
                  className={cn(
                    isBlocked && "bg-status-offline/5 hover:bg-status-offline/10",
                  )}
                >
                  <TD className="font-medium">{s.camera}</TD>
                  <TD>
                    <Badge variant={MODE_META[s.mode].badge}>{s.mode}</Badge>
                  </TD>
                  <TD className="text-muted-foreground">{s.window}</TD>
                  <TD>
                    {s.prebufferSec > 0 ? (
                      <span className="tabular-nums">{s.prebufferSec} s</span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TD>
                  <TD>
                    <span className="tabular-nums">{s.retainDays} 天</span>
                  </TD>
                  <TD>
                    <StatusLabel tone={meta.tone}>{meta.label}</StatusLabel>
                  </TD>
                  <TD className="whitespace-normal">
                    {s.blockReason ? (
                      <span className="block max-w-[280px] text-xs leading-relaxed text-destructive">
                        {s.blockReason}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TD>
                  <TD>
                    <RowActions>
                      <Button variant="ghost" size="icon-sm" title="编辑计划">
                        <Pencil className="size-3.5" />
                      </Button>
                    </RowActions>
                  </TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
      </div>

      <PrototypeNote>
        本页不含「开始录像」入口是产品决策而非功能缺失：录像只能由计划产生，事件只做
        提升。观测状态取自录像进程的真实回报，因此「计划已启用」并不等于「正在录制」。
      </PrototypeNote>
    </div>
  )
}

/* --------------------------------------------------------- Weekly grid */

function WeeklyGrid({ schedule }: { schedule: Schedule }) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[3rem_minmax(0,1fr)] items-end gap-x-2">
        <span />
        <div className="flex">
          {HOURS.map((h) =>
            HOUR_LABELS.includes(h) ? (
              <span
                key={h}
                className="flex-1 text-[10px] tabular-nums text-muted-foreground"
              >
                {String(h).padStart(2, "0")}
              </span>
            ) : (
              <span key={h} className="flex-1" />
            ),
          )}
        </div>
      </div>

      <div className="relative">
        {/* Playhead spans the whole week at a single wall-clock position. */}
        <div className="pointer-events-none absolute inset-y-0 left-[3.5rem] right-0">
          <div
            className="absolute inset-y-0 w-px bg-primary"
            style={{ left: `${(NOW_HOUR / 24) * 100}%` }}
          />
        </div>
        <div className="space-y-1">
          {DAYS.map((day) => (
            <div
              key={day}
              className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-2"
            >
              <span className="text-[11px] text-muted-foreground">{day}</span>
              <div className="flex h-6 overflow-hidden rounded-md border border-border">
                {HOURS.map((h) => (
                  <div
                    key={h}
                    className={cn(
                      "h-full flex-1 border-r border-border/50 last:border-r-0",
                      FILL[cellFill(schedule, h)],
                    )}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", FILL.record)} /> 正式录制
        </span>
        <span className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", FILL.buffer)} /> 预录缓冲
        </span>
        <span className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", FILL.event)} /> 仅事件 · 无预录
        </span>
        <span className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", FILL.outside)} /> 计划外
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-px bg-primary" /> 现在 15:00
        </span>
      </div>
    </div>
  )
}
