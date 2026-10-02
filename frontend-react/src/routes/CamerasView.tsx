import { useMemo, useState } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import { Plus, Upload, Wifi, WifiOff } from "lucide-react"
import { Badge, Button, Input, Select, Switch } from "../components/ui/primitives"
import { DataTable } from "../components/ui/data-table"
import {
  Callout,
  PageHeader,
  StatCard,
  StatusDot,
  type HealthTone,
} from "../components/ui/display"
import { type CameraSummary, normalizeConnectivity } from "../api/cameras"
import { useCameras, useCamera } from "../lib/queries"
import { useProbeCamera, useRetireCamera, useSetCameraEnabled } from "../lib/cameraMutations"
import { CameraEditor } from "../components/cameras/CameraEditor"
import {
  ROW_ACTION_LABEL,
  rowActionFor,
  useCameraRowActions,
} from "../lib/cameraRowActions"
import { formatRelative } from "../lib/format"

const TONE_BY_STATUS: Record<string, HealthTone> = {
  online: "online",
  offline: "offline",
  degraded: "degraded",
  unknown: "unknown",
}

function statusTone(c: CameraSummary): HealthTone {
  if (c.retired_at) return "unknown"
  if (!c.enabled || c.maintenance) return "degraded"
  return TONE_BY_STATUS[normalizeConnectivity(c.connectivity_status)] ?? "unknown"
}

function statusLabel(c: CameraSummary): string {
  if (c.retired_at) return "已退役"
  if (c.maintenance) return "维护中"
  if (!c.enabled) return "已停用"
  const s = normalizeConnectivity(c.connectivity_status)
  return s === "online" ? "在线" : s === "offline" ? "离线" : s === "degraded" ? "抖动" : "未知"
}

export function CamerasView() {
  const [includeRetired, setIncludeRetired] = useState(false)
  const [q, setQ] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [selected, setSelected] = useState<string | null>(null)

  const { data, isLoading, error, refetch } = useCameras(includeRetired)
  // The list returns `CameraSummary`, which has no streams or bindings — the
  // editor needs the detail, and fetching it only when a row is opened keeps
  // the list at one request instead of one per row.
  const detailQuery = useCamera(selected)
  const actions = useCameraRowActions(selected)

  // Guard the shape before deriving from it. `CameraSummary[]` is what the
  // endpoint promises, but a cached value from an older build (or a
  // contract drift) must degrade to the error/empty state rather than crash
  // the page on `.filter`.
  const list = Array.isArray(data) ? data : null
  const failed = error ?? (data !== undefined && !Array.isArray(data) ? new TypeError("机位列表响应不是数组") : null)

  const rows = useMemo(() => {
    const all = list ?? []
    return all.filter((c) => {
      if (q && !`${c.name}${c.manufacturer ?? ""}${c.model ?? ""}${c.location ?? ""}`.includes(q)) {
        return false
      }
      if (statusFilter === "on") return normalizeConnectivity(c.connectivity_status) === "online"
      if (statusFilter === "off") return normalizeConnectivity(c.connectivity_status) !== "online"
      return true
    })
  }, [list, q, statusFilter])

  const stats = useMemo(() => {
    const all = list ?? []
    return {
      total: all.length,
      online: all.filter((c) => normalizeConnectivity(c.connectivity_status) === "online").length,
      ptz: all.filter((c) => c.ptz_capable).length,
      unknown: all.filter((c) => normalizeConnectivity(c.connectivity_status) === "unknown").length,
    }
  }, [list])

  const columns = useMemo<ColumnDef<CameraSummary, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "机位",
        cell: ({ row }) => {
          const c = row.original
          return (
            <div className="flex items-center gap-2">
              <StatusDot tone={statusTone(c)} pulse={statusTone(c) === "online"} />
              <div className="min-w-0">
                <p className="truncate font-medium">{c.name}</p>
                {c.location && (
                  <p className="truncate text-[11px] text-muted-foreground">{c.location}</p>
                )}
              </div>
            </div>
          )
        },
      },
      {
        accessorKey: "manufacturer",
        header: "厂商 / 型号",
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {row.original.manufacturer ?? "—"}
            {row.original.model ? ` / ${row.original.model}` : ""}
          </span>
        ),
      },
      {
        accessorKey: "adapter_type",
        header: "接入",
        cell: ({ row }) => (
          <Badge variant={row.original.adapter_type ? "secondary" : "outline"}>
            {row.original.adapter_type ?? "—"}
          </Badge>
        ),
      },
      {
        id: "status",
        accessorFn: (c) => statusLabel(c),
        header: "状态",
        cell: ({ row }) => {
          const c = row.original
          return (
            <div className="flex items-center gap-2">
              <span className="text-xs">{statusLabel(c)}</span>
              {c.retired_at ? (
                <Badge variant="muted">已退役</Badge>
              ) : !c.enabled ? (
                <Badge variant="muted">停用</Badge>
              ) : c.maintenance ? (
                <Badge variant="warning">维护</Badge>
              ) : null}
            </div>
          )
        },
      },
      {
        id: "resolution",
        accessorFn: (c) => c.width ?? 0,
        header: "分辨率",
        cell: ({ row }) => {
          const c = row.original
          if (!c.width || !c.height) return <span className="text-xs text-muted-foreground">—</span>
          return (
            <span className="text-xs tabular-nums text-muted-foreground">
              {c.width}×{c.height}
              {c.fps ? ` · ${Math.round(c.fps)}fps` : ""}
              {c.video_codec ? ` · ${c.video_codec}` : ""}
            </span>
          )
        },
      },
      {
        accessorKey: "ptz_capable",
        header: "PTZ",
        cell: ({ row }) =>
          row.original.ptz_capable ? (
            <Wifi className="size-3.5 text-status-online" />
          ) : (
            <WifiOff className="size-3.5 text-muted-foreground/50" />
          ),
      },
      {
        accessorKey: "time_sync_mode",
        header: "时钟",
        cell: ({ row }) => (
          <Badge
            variant={
              row.original.time_sync_mode === "manage_ntp" ? "success" : "outline"
            }
          >
            {row.original.time_sync_mode === "manage_ntp"
              ? "托管 NTP"
              : row.original.time_sync_mode === "monitor"
                ? "仅监测"
                : "忽略"}
          </Badge>
        ),
      },
      {
        accessorKey: "last_probe_at",
        header: "最后探测",
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatRelative(row.original.last_probe_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => {
          const camera = row.original
          const action = rowActionFor(camera)
          const busy =
            selected === camera.id &&
            (actions.setEnabled.isPending ||
              actions.retire.isPending ||
              actions.probe.isPending)

          return (
            <div
              className="flex items-center justify-end gap-1"
              onClick={(event) => event.stopPropagation()}
            >
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => actions.probe.mutate(undefined)}
                title="重新探测码流"
              >
                探测
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => {
                  if (action.kind === "enable") actions.setEnabled.enable()
                  else if (action.kind === "disable")
                    actions.setEnabled.disable()
                  else if (action.kind === "restore") actions.retire.restore()
                  else actions.retire.retire()
                }}
              >
                {ROW_ACTION_LABEL[action.kind]}
              </Button>
            </div>
          )
        },
      },
    ],
    [selected, actions],
  )

  return (
    <div className="flex h-full">
      <div className="flex-1 space-y-4 overflow-auto p-5">
      <PageHeader
        title="摄像机"
        description="设备接入与在线状态。码流绑定与时钟偏差不在列表接口里，见下方说明。"
        actions={
          <>
            <Button variant="outline" size="sm">
              <Upload /> 批量导入
            </Button>
            <Button size="sm">
              <Plus /> 添加机位
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="机位总数" value={stats.total} unit="路" />
        <StatCard label="在线" value={stats.online} unit={`/ ${stats.total}`} tone="online" />
        <StatCard label="支持 PTZ" value={stats.ptz} unit="路" />
        <StatCard
          label="状态未知"
          value={stats.unknown}
          unit="路"
          tone={stats.unknown > 0 ? "degraded" : "online"}
          hint="后端 connectivity_status 不是已知取值"
        />
      </div>

      <DataTable
        columns={columns}
        data={rows}
        isLoading={isLoading}
        error={failed}
        selectedKey={selected}
        onRowClick={(c) => setSelected((cur) => (cur === c.id ? null : c.id))}
        onRetry={() => void refetch()}
        emptyTitle="没有匹配的机位"
        emptyDescription="调整搜索词或状态筛选，或先添加一个机位。"
        toolbar={
          <>
            <Input
              className="w-48"
              placeholder="搜索名称 / 厂商 / 位置"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <Select
              className="w-32"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">全部状态</option>
              <option value="on">仅在线</option>
              <option value="off">非在线</option>
            </Select>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Switch
                aria-checked={includeRetired}
                onClick={() => setIncludeRetired((v) => !v)}
              />
              含已退役
            </label>
            <span className="ml-auto text-xs text-muted-foreground">
              {rows.length} / {list?.length ?? 0} 路
            </span>
          </>
        }
      />

      <Callout tone="degraded" title="列表接口不返回码流绑定与时钟偏差">
        GET /api/v1/cameras 返回的是 CameraSummary，其中没有码流绑定、时钟偏差、
        录像占用。这些分别要 GET /cameras/:id（CameraDetail 带 streams 与 bindings）
        和 GET /cameras/:id/clock 逐台拉取。在列表里画这两列会对每行发一次请求，
        所以这里没有画——点开某台机位再取详情是正确的做法。另有一点：录像、
        实时主/子码流、AI 检测、抓图、音频这六种用途绑定是逐机位独立配置的。
      </Callout>

      <Callout tone="degraded" title="萤石设备不走 ONVIF 接入">
        本页的 ONVIF 探测 / 局域网发现仅适用于能本地直连的设备。萤石无 Linux
        SDK、局域网能力只覆盖手机端，事件只经公网 HTTPS WebHook 到达，因此它被归为
        「事件源」配置，不在本页出现。
      </Callout>
      </div>

      {selected && detailQuery.data ? (
        <div className="w-[26rem] shrink-0">
          <CameraEditor
            camera={detailQuery.data}
            onClose={() => setSelected(null)}
          />
        </div>
      ) : null}
    </div>
  )
}
