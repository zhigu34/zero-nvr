import { useState } from "react"
import {
  Activity,
  Check,
  Download,
  Eye,
  Play,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react"
import {
  Badge,
  Button,
  Input,
  Select,
  Switch,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/primitives"
import {
  Callout,
  Checkbox,
  KeyValue,
  PageHeader,
  ProgressBar,
  RowActions,
  Segmented,
  StatCard,
  StatusDot,
  StatusLabel,
  Toolbar,
  ToolbarSpacer,
  type HealthTone,
} from "../components/ui/display"
import {
  cameras,
  categoryLabel,
  events,
  overviewStats,
  stateLabel,
  systemHealth,
  type Camera,
  type CameraEvent,
} from "../lib/mock"
import { cn } from "../lib/utils"

const CATEGORIES = Object.keys(categoryLabel) as CameraEvent["category"][]

const HEALTH_LABEL: Record<Camera["health"], string> = {
  online: "在线",
  offline: "离线",
  degraded: "抖动",
  unknown: "未接入",
}

const STATE_VARIANT: Record<
  CameraEvent["state"],
  "danger" | "warning" | "muted"
> = { new: "danger", acknowledged: "warning", resolved: "muted" }

const STATE_TONE: Record<CameraEvent["state"], HealthTone> = {
  new: "offline",
  acknowledged: "degraded",
  resolved: "online",
}

const CAMERAS_IN_USE = [...new Set(events.map((e) => e.camera))]

/** A 1-frame placeholder — no real image is shipped with the prototype. */
function Thumb({ id }: { id: string }) {
  return (
    <div className="relative h-9 w-16 overflow-hidden rounded bg-black">
      <div
        className="absolute inset-0 opacity-[0.18]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, #fff 0 1px, transparent 1px 10px)",
        }}
      />
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-[8px] text-white/50">{id}</span>
      </div>
    </div>
  )
}

export function EventsView() {
  const [frigate, setFrigate] = useState(systemHealth.frigate.enabled)
  const [source, setSource] = useState("all")
  const [category, setCategory] = useState("all")
  const [camera, setCamera] = useState("all")
  const [q, setQ] = useState("")
  const [range, setRange] = useState("today")
  const [sel, setSel] = useState<string[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [states, setStates] = useState<Record<string, CameraEvent["state"]>>({})

  const stateOf = (e: CameraEvent) => states[e.id] ?? e.state

  const rows = events.filter(
    (e) =>
      (frigate || e.source !== "AI 检测") &&
      (source === "all" || e.source === source) &&
      (category === "all" || e.category === category) &&
      (camera === "all" || e.camera === camera) &&
      (q === "" || e.camera.includes(q) || e.id.includes(q)),
  )

  const aiShare = events.filter((e) => e.source === "AI 检测").length / events.length
  const withRecording =
    rows.filter((e) => e.hasRecording).length / Math.max(1, rows.length)
  const unresolved = rows.filter((e) => stateOf(e) !== "resolved").length
  const detail = events.find((e) => e.id === open)

  const setState = (id: string, s: CameraEvent["state"]) =>
    setStates((prev) => ({ ...prev, [id]: s }))

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="事件"
        description="ONVIF 事件与 AI 检测事件的归一化视图。两者共用一套字段，差异只在来源与置信度。"
        actions={
          <>
            <Button variant="outline" size="sm">
              <RefreshCw /> 刷新
            </Button>
            <Button size="sm">
              <Download /> 导出 CSV
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="今日事件"
          value={overviewStats.eventsToday}
          unit="条"
          icon={<Activity className="size-4" />}
          hint={`当前筛选 ${rows.length} 条`}
        />
        <StatCard
          label="未处理"
          value={overviewStats.eventsUnacknowledged}
          unit="条"
          tone={overviewStats.eventsUnacknowledged > 0 ? "degraded" : "online"}
          hint={`本视图可见 ${unresolved} 条待处理`}
        />
        <StatCard
          label="AI 检测占比"
          value={frigate ? (aiShare * 100).toFixed(0) : "—"}
          unit={frigate ? "%" : undefined}
          tone={frigate ? "online" : "unknown"}
          hint={frigate ? "Frigate 已启用 · CPU 检测器" : "Frigate 未启用，本项不适用"}
        />
        <StatCard
          label="关联录像比例"
          value={(withRecording * 100).toFixed(0)}
          unit="%"
          tone={withRecording > 0.5 ? "online" : "degraded"}
          hint="有录像才谈得上回放与取证"
        />
      </div>

      <Toolbar>
        <Select
          className="w-28"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="all">全部来源</option>
          <option value="ONVIF">ONVIF</option>
          <option value="AI 检测">AI 检测{frigate ? "" : "（未启用）"}</option>
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
          className="w-40"
          value={camera}
          onChange={(e) => setCamera(e.target.value)}
        >
          <option value="all">全部机位</option>
          {CAMERAS_IN_USE.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Input
          className="w-44"
          placeholder="搜索机位 / 事件 ID"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Segmented
          value={range}
          onChange={setRange}
          options={[
            { value: "today", label: "今天" },
            { value: "24h", label: "24 小时" },
            { value: "7d", label: "7 天" },
          ]}
        />
        {sel.length > 0 && (
          <span className="text-xs text-muted-foreground">已选 {sel.length} 项</span>
        )}
        <ToolbarSpacer />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Switch
            aria-checked={frigate}
            onClick={() => {
              setFrigate((v) => !v)
              setSource("all")
            }}
            title="Frigate 为可选检测源"
          />
          <Sparkles className="size-3.5" />
          Frigate（可选）
        </label>
      </Toolbar>

      <Callout tone="degraded" title="Frigate 是可选事件源，不是前提">
        关闭「Frigate（可选）」后本页照常工作：来源只剩 ONVIF，AI 检测占比显示
        为「—」，AI 专属筛选项不再是筛选条件，而是缺席。任何依赖 AI 的统计都必须
        在未启用时给出「不适用」，而不是 0。
      </Callout>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <Table>
          <THead>
            <TR>
              <TH className="w-10">
                <Checkbox
                  checked={sel.length === rows.length && rows.length > 0}
                  onChange={(e) =>
                    setSel(e.target.checked ? rows.map((r) => r.id) : [])
                  }
                />
              </TH>
              <TH>缩略图</TH>
              <TH>时间</TH>
              <TH>机位</TH>
              <TH>来源</TH>
              <TH>类别</TH>
              <TH className="w-32">置信度</TH>
              <TH>状态</TH>
              <TH>关联录像</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((e) => {
              const st = stateOf(e)
              return (
                <TR
                  key={e.id}
                  onClick={() => setOpen(open === e.id ? null : e.id)}
                  className={cn("cursor-pointer", open === e.id && "bg-accent/50")}
                >
                  <TD onClick={(ev) => ev.stopPropagation()}>
                    <Checkbox
                      checked={sel.includes(e.id)}
                      onChange={(ev) =>
                        setSel((prev) =>
                          ev.target.checked
                            ? [...prev, e.id]
                            : prev.filter((x) => x !== e.id),
                        )
                      }
                    />
                  </TD>
                  <TD>
                    <Thumb id={e.id} />
                  </TD>
                  <TD className="text-xs tabular-nums">
                    {range === "today" ? e.time : `09-30 ${e.time}`}
                  </TD>
                  <TD className="font-medium">{e.camera}</TD>
                  <TD>
                    <div className="flex items-center gap-1.5">
                      <Badge
                        variant={
                          e.source === "AI 检测"
                            ? frigate
                              ? "default"
                              : "outline"
                            : "secondary"
                        }
                      >
                        {e.source}
                      </Badge>
                      {!frigate && e.source === "AI 检测" && (
                        <span className="text-[10px] text-muted-foreground">
                          来源已停用
                        </span>
                      )}
                    </div>
                  </TD>
                  <TD className="text-muted-foreground">
                    {categoryLabel[e.category]}
                  </TD>
                  <TD>
                    <ProgressBar
                      value={e.confidence * 100}
                      tone={
                        e.confidence >= 0.85
                          ? "online"
                          : e.confidence >= 0.7
                            ? "degraded"
                            : "unknown"
                      }
                      showLabel
                    />
                  </TD>
                  <TD>
                    <div className="flex items-center gap-1.5">
                      <StatusDot tone={STATE_TONE[st]} />
                      <span className="text-xs">{stateLabel[st]}</span>
                    </div>
                  </TD>
                  <TD>
                    {e.hasRecording ? (
                      <Badge variant="success">已关联</Badge>
                    ) : (
                      <span className="text-xs text-status-degraded">缺失</span>
                    )}
                  </TD>
                  <TD onClick={(ev) => ev.stopPropagation()}>
                    <RowActions>
                      {st !== "resolved" && (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="标记已处理"
                          onClick={() => setState(e.id, "resolved")}
                        >
                          <Check className="size-3.5" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title="查看"
                        onClick={() => setOpen(e.id)}
                      >
                        <Eye className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title="回放"
                        disabled={!e.hasRecording}
                      >
                        <Play className="size-3.5" />
                      </Button>
                    </RowActions>
                  </TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
        {rows.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            没有符合条件的事件。放宽筛选，或确认 Frigate 是否处于停用状态。
          </p>
        )}
      </div>

      {detail && (
        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold">事件 {detail.id}</h3>
              <Badge variant={STATE_VARIANT[stateOf(detail)]}>
                {stateLabel[stateOf(detail)]}
              </Badge>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              title="收起"
              onClick={() => setOpen(null)}
            >
              <X className="size-3.5" />
            </Button>
          </div>
          <div className="grid gap-x-8 px-4 py-1 sm:grid-cols-2 lg:grid-cols-4">
            <KeyValue label="时间">
              <span className="tabular-nums">2026-10-02 {detail.time}</span>
            </KeyValue>
            <KeyValue label="机位">{detail.camera}</KeyValue>
            <KeyValue label="来源">
              <Badge
                variant={detail.source === "AI 检测" ? "default" : "secondary"}
              >
                {detail.source}
              </Badge>
            </KeyValue>
            <KeyValue label="类别">{categoryLabel[detail.category]}</KeyValue>
            <KeyValue label="置信度">
              <span className="tabular-nums">
                {(detail.confidence * 100).toFixed(0)}%
              </span>
            </KeyValue>
            <KeyValue label="关联录像">
              {detail.hasRecording ? "seg 片段已索引" : "缺失 · 需检查存储"}
            </KeyValue>
            <KeyValue label="缩略图">
              <span className="font-mono text-xs">{detail.thumbnail}</span>
            </KeyValue>
            <KeyValue label="机位状态">
              <CameraHealth camera={detail.camera} />
            </KeyValue>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
            <Button
              size="sm"
              variant={stateOf(detail) === "resolved" ? "outline" : "default"}
              onClick={() =>
                setState(
                  detail.id,
                  stateOf(detail) === "resolved" ? "new" : "resolved",
                )
              }
            >
              <Check />
              {stateOf(detail) === "resolved" ? "撤销处理" : "标记已处理"}
            </Button>
            <Button size="sm" disabled={!detail.hasRecording}>
              <Play /> 在回放中打开
            </Button>
            <Button variant="ghost" size="sm">
              标记误报
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              处理动作会写入审计日志
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

/** Camera health for the detail panel, resolved from the camera fixture. */
function CameraHealth({ camera }: { camera: string }) {
  const cam = cameras.find((c) => c.name === camera)
  if (!cam) return <span className="text-muted-foreground">—</span>
  return <StatusLabel tone={cam.health}>{HEALTH_LABEL[cam.health]}</StatusLabel>
}
