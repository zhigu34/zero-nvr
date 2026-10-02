import { useMemo, useState } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import { Filter, RotateCcw } from "lucide-react"
import { Badge, Button, Card, CardContent, Input, Select } from "../components/ui/primitives"
import { DataTable } from "../components/ui/data-table"
import {
  Callout,
  KeyValue,
  PageHeader,
  ProgressBar,
  Segmented,
  StatCard,
  StatusDot,
} from "../components/ui/display"
import {
  categoryLabel,
  type EventView,
  type EventFilters,
} from "../api/events"
import { useCameras, useEvents } from "../lib/queries"
import { formatClock, formatFraction, formatTime } from "../lib/format"
import { cn } from "../lib/utils"

const RANGES = [
  { value: "today", label: "今天" },
  { value: "24h", label: "24 小时" },
  { value: "7d", label: "7 天" },
] as const

function rangeBounds(range: string): { from?: string; to?: string } {
  const now = new Date()
  if (range === "today") {
    const start = new Date(now)
    start.setHours(0, 0, 0, 0)
    return { from: start.toISOString(), to: now.toISOString() }
  }
  if (range === "24h") {
    return {
      from: new Date(now.getTime() - 24 * 3600_000).toISOString(),
      to: now.toISOString(),
    }
  }
  if (range === "7d") {
    return {
      from: new Date(now.getTime() - 7 * 24 * 3600_000).toISOString(),
      to: now.toISOString(),
    }
  }
  return {}
}

export function EventsView() {
  const [range, setRange] = useState<string>("24h")
  const [source, setSource] = useState("")
  const [category, setCategory] = useState("")
  const [minConfidence, setMinConfidence] = useState("")
  const [selected, setSelected] = useState<EventView | null>(null)

  const baseFilters: EventFilters = useMemo(
    () => ({
      ...rangeBounds(range),
      source: source || undefined,
      category: category || undefined,
      minConfidence: minConfidence ? Number(minConfidence) : undefined,
      limit: 50,
    }),
    [range, source, category, minConfidence],
  )

  const query = useEvents(baseFilters)
  const { data: camData } = useCameras()

  const cameraNames = useMemo(() => {
    const m = new Map<string, string>()
    // Same shape guard as the camera list: a non-array here must degrade to
    // "unknown camera", never crash the table.
    if (!Array.isArray(camData)) return m
    for (const c of camData) m.set(c.id, c.name)
    return m
  }, [camData])

  // Keyset pagination can repeat an item across a page boundary, so merge by
  // id rather than concatenating.
  const items = useMemo(() => {
    const seen = new Set<string>()
    const out: EventView[] = []
    for (const page of query.data?.pages ?? []) {
      for (const e of page.items ?? []) {
        if (seen.has(e.id)) continue
        seen.add(e.id)
        out.push(e)
      }
    }
    return out
  }, [query.data])

  const stats = useMemo(() => {
    const ai = items.filter((e) => e.source.toLowerCase().includes("frigate"))
    const withScore = items.filter((e) => e.confidence !== null)
    return {
      total: items.length,
      withSnapshot: items.filter((e) => e.snapshot_ref).length,
      open: items.filter((e) => e.ended_at === null).length,
      avgConfidence: withScore.length
        ? withScore.reduce((s, e) => s + (e.confidence ?? 0), 0) / withScore.length
        : null,
      ai: ai.length,
    }
  }, [items])

  /**
   * Changing a filter must discard every page already fetched, otherwise the
   * table would keep rows that no longer match the new conditions. A new
   * query key does that automatically; this only clears the open detail row.
   */
  function resetPages() {
    setSelected(null)
  }

  const columns = useMemo<ColumnDef<EventView, unknown>[]>(
    () => [
      {
        accessorKey: "started_at",
        header: "开始时间",
        cell: ({ row }) => (
          <span className="text-xs tabular-nums">
            {formatTime(row.original.started_at)}
          </span>
        ),
      },
      {
        id: "camera",
        accessorFn: (e) => (e.camera_id ? cameraNames.get(e.camera_id) ?? "" : ""),
        header: "机位",
        cell: ({ row }) => {
          const e = row.original
          if (!e.camera_id) {
            return <span className="text-xs text-muted-foreground">无关联机位</span>
          }
          const name = cameraNames.get(e.camera_id)
          return (
            <span className={cn("text-xs", !name && "text-muted-foreground")}>
              {name ?? `未知机位 ${e.camera_id.slice(0, 8)}`}
            </span>
          )
        },
      },
      {
        accessorKey: "source",
        header: "来源",
        cell: ({ row }) => (
          <Badge
            variant={row.original.source.toLowerCase().includes("frigate") ? "default" : "secondary"}
          >
            {row.original.source}
          </Badge>
        ),
      },
      {
        accessorKey: "category",
        header: "类别",
        cell: ({ row }) => <span className="text-xs">{categoryLabel(row.original.category)}</span>,
      },
      {
        id: "confidence",
        accessorFn: (e) => e.confidence ?? -1,
        header: "置信度",
        cell: ({ row }) => {
          const c = row.original.confidence
          if (c === null) return <span className="text-xs text-muted-foreground">—</span>
          return (
            <div className="flex w-24 items-center gap-2">
              <ProgressBar
                value={c * 100}
                tone={c >= 0.8 ? "online" : c >= 0.6 ? "degraded" : "unknown"}
              />
              <span className="text-xs tabular-nums text-muted-foreground">
                {formatFraction(c)}
              </span>
            </div>
          )
        },
      },
      {
        accessorKey: "severity",
        header: "严重度",
        cell: ({ row }) => {
          const s = row.original.severity
          if (!s) return <span className="text-xs text-muted-foreground">—</span>
          return (
            <Badge variant={s.toLowerCase() === "high" ? "danger" : "outline"}>{s}</Badge>
          )
        },
      },
      {
        id: "state",
        accessorFn: (e) => (e.ended_at === null ? 0 : 1),
        header: "状态",
        cell: ({ row }) => {
          const open = row.original.ended_at === null
          return (
            <span className="inline-flex items-center gap-1.5 text-xs">
              <StatusDot tone={open ? "degraded" : "online"} />
              {open ? "进行中" : "已结束"}
            </span>
          )
        },
      },
      {
        accessorKey: "ended_at",
        header: "结束时间",
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {row.original.ended_at ? formatTime(row.original.ended_at) : "—"}
          </span>
        ),
      },
    ],
    [cameraNames],
  )

  const hasMore = query.hasNextPage ?? false

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="事件"
        description="ONVIF 事件与 AI 检测事件的归一化视图。列表按游标分页，不提供总条数。"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setRange("24h")
              setSource("")
              setCategory("")
              setMinConfidence("")
              resetPages()
            }}
          >
            <RotateCcw /> 重置筛选
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="已加载事件" value={items.length} unit="条" />
        <StatCard
          label="进行中"
          value={stats.open}
          unit="条"
          tone={stats.open > 0 ? "degraded" : "online"}
          hint="ended_at 为空"
        />
        <StatCard
          label="平均置信度"
          value={stats.avgConfidence === null ? "—" : formatFraction(stats.avgConfidence)}
          hint={`${items.length - stats.ai} 条无置信度或非 AI 来源`}
        />
        <StatCard
          label="有快照"
          value={stats.withSnapshot}
          unit="条"
          tone={stats.withSnapshot === 0 && items.length > 0 ? "degraded" : "online"}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-3 py-2.5">
        <Segmented
          value={range}
          onChange={(v) => {
            setRange(v)
            resetPages()
          }}
          options={RANGES.map((r) => ({ value: r.value, label: r.label }))}
        />
        <Select
          className="w-36"
          value={source}
          onChange={(e) => {
            setSource(e.target.value)
            resetPages()
          }}
        >
          <option value="">全部来源</option>
          <option value="onvif">ONVIF</option>
          <option value="frigate">Frigate（AI）</option>
        </Select>
        <Select
          className="w-36"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value)
            resetPages()
          }}
        >
          <option value="">全部类别</option>
          <option value="person">人员</option>
          <option value="vehicle">车辆</option>
          <option value="animal">动物</option>
          <option value="motion">移动侦测</option>
          <option value="intrusion">区域入侵</option>
          <option value="line">越线</option>
        </Select>
        <Input
          className="w-32"
          type="number"
          min={0}
          max={1}
          step={0.05}
          placeholder="置信度 ≥"
          value={minConfidence}
          onChange={(e) => {
            setMinConfidence(e.target.value)
            resetPages()
          }}
        />
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <Filter className="size-3.5" />
          游标分页 · 每页 50
        </span>
      </div>

      <DataTable
        columns={columns}
        data={items}
        isLoading={query.isPending}
        error={query.error}
        onRetry={() => void query.refetch()}
        selectedKey={selected?.id ?? null}
        onRowClick={(e) => setSelected((cur) => (cur?.id === e.id ? null : e))}
        emptyTitle="该条件下没有事件"
        emptyDescription="放宽时间范围或清除筛选条件再试。"
      />

      <div className="flex items-center justify-center gap-2">
        {hasMore ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => void query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
          >
            {query.isFetchingNextPage ? "加载中…" : "加载更多"}
          </Button>
        ) : (
          items.length > 0 && (
            <span className="text-xs text-muted-foreground">
              已到末尾 · 共加载 {items.length} 条
            </span>
          )
        )}
      </div>

      {selected && <EventDetail event={selected} cameraName={selected.camera_id ? cameraNames.get(selected.camera_id) : undefined} />}

      <Callout tone="degraded" title="机位列是客户端 join 的结果">
        GET /api/v1/events 只返回 camera_id，不带机位名，所以这一列要拿
        GET /api/v1/cameras 的结果在客户端拼。camera_id 为空的事件来自非摄像机源，
        显示「无关联机位」；id 在机位列表里找不到时显示「未知机位 + id 前 8 位」，
        而不是留空——留空会和"没加载出来"混淆。
      </Callout>

      <Callout tone="degraded" title="Frigate 是可选事件源">
        未配置 AI 引擎时事件流里只会有 ONVIF 来源，来源筛选依然可用。本页不把
        AI 相关筛选项当作必备功能渲染。
      </Callout>
    </div>
  )
}

function EventDetail({
  event,
  cameraName,
}: {
  event: EventView
  cameraName?: string
}) {
  const meta = Object.entries(event.metadata ?? {})

  return (
    <Card>
      <CardContent className="space-y-1 py-2">
        <div className="px-2 pb-2 text-sm font-semibold">
          事件详情 · {categoryLabel(event.category)}
        </div>
        <div className="divide-y divide-border">
          <KeyValue label="事件 ID">{event.id}</KeyValue>
          <KeyValue label="来源">
            {event.source}
            {event.source_instance_id ? ` · ${event.source_instance_id}` : ""}
          </KeyValue>
          <KeyValue label="来源事件 ID">{event.source_event_id ?? "—"}</KeyValue>
          <KeyValue label="机位">{cameraName ?? (event.camera_id ? event.camera_id : "无关联机位")}</KeyValue>
          <KeyValue label="开始 / 结束">
            {formatClock(event.started_at)} → {event.ended_at ? formatClock(event.ended_at) : "进行中"}
          </KeyValue>
          <KeyValue label="置信度">{formatFraction(event.confidence)}</KeyValue>
          <KeyValue label="严重度">{event.severity ?? "—"}</KeyValue>
          <KeyValue label="区域">{event.zone ?? "—"}</KeyValue>
          <KeyValue label="标签">{event.label ?? "—"}</KeyValue>
          <KeyValue label="关联 ID">{event.correlation_id ?? "—"}</KeyValue>
          <KeyValue label="快照">{event.snapshot_ref ?? "无"}</KeyValue>
        </div>
        {meta.length > 0 && (
          <div className="mt-2 border-t border-border pt-2">
            <p className="px-2 pb-1 text-xs font-medium text-muted-foreground">
              原始 metadata（{meta.length} 项）
            </p>
            <div className="divide-y divide-border">
              {meta.map(([k, v]) => (
                <KeyValue key={k} label={k}>
                  <span className="font-mono text-xs">
                    {renderMetaValue(v)}
                  </span>
                </KeyValue>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** metadata is `dict[str, object]` — values may be null, nested, or absent. */
function renderMetaValue(v: unknown): string {
  if (v === null || v === undefined) return "—"
  if (typeof v === "string") return v
  if (typeof v === "number" || typeof v === "boolean") return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return "[无法序列化]"
  }
}
