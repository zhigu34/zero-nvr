import { useMemo, useState } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import { Plus } from "lucide-react"

import { Badge, Button, Input, Select } from "../components/ui/primitives"
import { DataTable } from "../components/ui/data-table"
import {
  Callout,
  EmptyState,
  PageHeader,
  StatCard,
  StatusDot,
} from "../components/ui/display"
import { PolicyEditor } from "../components/schedules/PolicyEditor"
import { useCameras, useRecordingPolicies } from "../lib/queries"
import {
  BASELINE_MODE_LABEL,
  formatSeconds,
  judgeRuntime,
  runtimeTone,
  type RuntimeVerdict,
} from "../lib/recordingRuntime"
import { WEEKDAY_LABEL } from "../lib/recordingPolicyValidation"
import type { RecordingPolicyView } from "../api/recordingPolicies"

/**
 * Recording plans across all cameras.
 *
 * Every configured policy appears here; cameras without one appear too, with
 * a "未配置" row that can be created — the list endpoint only returns
 * configured policies, so treating its output as the set of cameras would
 * make the missing ones invisible rather than obviously unset.
 *
 * The status column is the reason this page exists separately from the camera
 * list. A policy can be enabled, saved, and answered with 200 while the camera
 * records nothing, because the backend swallows `recording_stream_offline`
 * and reports it only through `runtime`.
 */

interface Row {
  cameraId: string
  cameraName: string
  policy: RecordingPolicyView | null
}

export function SchedulesView() {
  const camerasQuery = useCameras()
  const policiesQuery = useRecordingPolicies()
  const [selected, setSelected] = useState<string | null>(null)
  const [q, setQ] = useState("")

  const rows = useMemo<Row[]>(() => {
    const cameras = Array.isArray(camerasQuery.data) ? camerasQuery.data : []
    // The hook normalises the response, but a cached value from an older
    // build or a contract drift must not crash the page on `.map`.
    const policies = Array.isArray(policiesQuery.data) ? policiesQuery.data : []
    const byCamera = new Map(
      policies.map((policy) => [policy.camera_id, policy]),
    )
    return cameras
      .filter((camera) =>
        q ? camera.name.includes(q) : true,
      )
      .map((camera) => ({
        cameraId: camera.id,
        cameraName: camera.name,
        policy: byCamera.get(camera.id) ?? null,
      }))
  }, [camerasQuery.data, policiesQuery.data, q])

  const stats = useMemo(() => {
    const verdicts = rows.map((row) =>
      judgeRuntime(
        row.policy?.runtime,
        row.policy?.baseline_mode ?? "continuous",
        row.policy?.enabled ?? false,
      ),
    )
    return {
      total: rows.length,
      configured: rows.filter((row) => row.policy).length,
      recording: verdicts.filter((v) => v.health === "recording").length,
      problem: verdicts.filter(
        (v) => v.health === "not_recording" || v.health === "unobservable",
      ).length,
    }
  }, [rows])

  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      {
        accessorKey: "cameraName",
        header: "机位",
        cell: ({ row }) => (
          <span className="text-sm font-medium">{row.original.cameraName}</span>
        ),
      },
      {
        id: "mode",
        header: "模式",
        cell: ({ row }) => {
          const policy = row.original.policy
          if (!policy) {
            return <Badge variant="muted">未配置</Badge>
          }
          return (
            <div className="flex items-center gap-1.5">
              <Badge variant={policy.enabled ? "secondary" : "muted"}>
                {BASELINE_MODE_LABEL[policy.baseline_mode]}
              </Badge>
              {!policy.enabled ? <Badge variant="warning">已停用</Badge> : null}
            </div>
          )
        },
      },
      {
        id: "schedule",
        header: "时段",
        cell: ({ row }) => (
          <ScheduleCell policy={row.original.policy} />
        ),
      },
      {
        id: "segment",
        header: "目标分段",
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {row.original.policy
              ? formatSeconds(row.original.policy.segment_target_seconds)
              : "—"}
          </span>
        ),
      },
      {
        id: "status",
        header: "实际状态",
        cell: ({ row }) => <StatusCell row={row.original} />,
      },
    ],
    [],
  )

  const selectedRow = rows.find((row) => row.cameraId === selected) ?? null

  if (camerasQuery.isPending || policiesQuery.isPending) {
    return (
      <div className="p-6">
        <PageHeader title="录制计划" description="正在加载…" />
      </div>
    )
  }

  const failed = camerasQuery.error ?? policiesQuery.error

  return (
    <div className="flex h-full">
      <div className="flex-1 space-y-4 overflow-auto p-5">
        <PageHeader
          title="录制计划"
          description="每机位的录制模式、时段与实际录制状态。"
          actions={
            <Button size="sm" disabled={rows.length === 0}>
              <Plus /> 新建计划
            </Button>
          }
        />

        {failed ? (
          <Callout tone="offline" title="无法加载录制计划">
            {failed instanceof Error ? failed.message : String(failed)}
          </Callout>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="机位总数" value={stats.total} unit="路" />
          <StatCard label="已配置计划" value={stats.configured} unit="路" />
          <StatCard
            label="正在录制"
            value={stats.recording}
            unit="路"
            tone="online"
          />
          <StatCard
            label="未录制 / 不可观测"
            value={stats.problem}
            unit="路"
            tone={stats.problem > 0 ? "offline" : "online"}
          />
        </div>

        {rows.length === 0 ? (
          <EmptyState
            title="没有可配置的机位"
            description="先在机位管理中添加并启用摄像机。"
          />
        ) : (
          <DataTable
            columns={columns}
            data={rows}
            rowKey={(row) => row.cameraId}
            selectedKey={selected}
            onRowClick={(row) =>
              setSelected((current) =>
                current === row.cameraId ? null : row.cameraId,
              )
            }
            emptyTitle="没有匹配的机位"
            emptyDescription="调整搜索词试试。"
            toolbar={
              <Input
                className="w-48"
                placeholder="搜索机位"
                value={q}
                onChange={(event) => setQ(event.target.value)}
              />
            }
          />
        )}

        <Callout tone="degraded" title="状态列读的是 runtime，不是保存结果">
          保存录制计划返回 200 并不代表机位在录像。服务端会吞掉
          <code>recording_stream_offline</code> 与媒体服务的启动超时
          （<code>recordings/api.py:648,672</code>），真实结果只在响应的
          <code> runtime</code> 字段里。因此本页的状态列来自
          <code> runtime.recording</code> 与 <code>runtime.blockers</code>。
        </Callout>
      </div>

      {selectedRow ? (
        <div className="w-[30rem] shrink-0">
          <PolicyEditor
            cameraId={selectedRow.cameraId}
            cameraName={selectedRow.cameraName}
            policy={selectedRow.policy}
            onClose={() => setSelected(null)}
          />
        </div>
      ) : null}
    </div>
  )
}

function StatusCell({ row }: { row: Row }) {
  const verdict: RuntimeVerdict = judgeRuntime(
    row.policy?.runtime,
    row.policy?.baseline_mode ?? "continuous",
    row.policy?.enabled ?? false,
  )
  return (
    <div className="flex items-center gap-2">
      <StatusDot tone={runtimeTone(verdict.health)} />
      <span
        className="text-xs text-muted-foreground"
        data-testid={`status-${verdict.health}`}
      >
        {verdict.message}
      </span>
    </div>
  )
}

function ScheduleCell({ policy }: { policy: RecordingPolicyView | null }) {
  if (!policy) return <span className="text-xs text-muted-foreground">—</span>
  if (policy.baseline_mode !== "schedule") {
    return <span className="text-xs text-muted-foreground">全天</span>
  }
  const weekly = Array.isArray(policy.schedule?.weekly) ? policy.schedule.weekly : []
  if (weekly.length === 0) {
    return <span className="text-xs text-status-degraded">未设置时段</span>
  }
  return (
    <div className="space-y-0.5 text-xs text-muted-foreground">
      {weekly.slice(0, 2).map((entry, index) => {
        const window = entry as { days?: number[]; start?: string; end?: string }
        const days = (window.days ?? [])
          .map((day) => WEEKDAY_LABEL[day] ?? "?")
          .join("、")
        return (
          <p key={index}>
            {days} {window.start}–{window.end}
          </p>
        )
      })}
      {weekly.length > 2 ? <p>…共 {weekly.length} 个时段</p> : null}
    </div>
  )
}
