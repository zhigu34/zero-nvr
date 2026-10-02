import { useMemo, useState } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import {
  Archive,
  CircleCheck,
  Cloud,
  Disc3,
  Gauge,
  HardDrive,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Select,
} from "../components/ui/primitives"
import { DataTable } from "../components/ui/data-table"
import {
  Callout,
  EmptyState,
  PageHeader,
  ProgressBar,
  Section,
  StatCard,
  type HealthTone,
} from "../components/ui/display"
import {
  CAPACITY_LEVEL_LABEL,
  formatBytes,
  probeTarget,
  type CapacityLevel,
  type RetentionPolicy,
  type StorageTarget,
  type StorageTargetTest,
} from "../api/storage"
import { useRetentionPolicies, useStorageTargets } from "../lib/queries"
import { cn } from "../lib/utils"

/**
 * 存储页。
 *
 * 这一页的核心约束写在 `api/storage.ts` 顶部：GET /storage/targets 返回的
 * StorageTargetView 里没有任何容量字段，容量只能通过 POST /storage/targets/:id/test
 * 主动探测拿到——那是一个会真实访问目标的副作用型 POST，不是读。
 *
 * 所以这里不画 0% 进度条、不写占位数字。每个目标在用户点「检测容量」之前，容量槽
 * 是明确为空的（"尚未检测"）。画一条看着合理的 0% 水位线，和真实数据无法区分，
 * 这是把"未知"谎报成"已知"。
 */

/* ------------------------------------------------------------------ Maps */

const TYPE_META: Record<
  StorageTarget["type"],
  { label: string; icon: typeof HardDrive }
> = {
  local: { label: "本地磁盘", icon: HardDrive },
  rclone: { label: "rclone 远程", icon: Cloud },
}

const ROLE_META: Record<
  StorageTarget["role"],
  { label: string; icon: typeof Disc3; variant: "default" | "secondary" }
> = {
  recording: { label: "录像", icon: Disc3, variant: "default" },
  archive: { label: "归档", icon: Archive, variant: "secondary" },
}

const LEVEL_TONE: Record<CapacityLevel, HealthTone> = {
  normal: "online",
  warning: "degraded",
  high: "degraded",
  critical: "offline",
}

const LEVEL_BADGE: Record<CapacityLevel, "success" | "warning" | "danger"> = {
  normal: "success",
  warning: "warning",
  high: "warning",
  critical: "danger",
}

const SCOPE_LABEL: Record<RetentionPolicy["scope_type"], string> = {
  GLOBAL: "全局",
  CAMERA: "单相机",
  CAMERA_GROUP: "相机组",
}

const MODE_LABEL: Record<RetentionPolicy["mode"], string> = {
  BEST_EFFORT: "尽力而为",
  HARD: "严格",
}

const MODE_HINT: Record<RetentionPolicy["mode"], string> = {
  BEST_EFFORT: "空间吃紧时允许普通录像早于到期清理",
  HARD: "未到期一律不删，宁可空间不足",
}

/** `config` 是自由字典，后端目前只写入下面这些键；未知键按原样显示键名。 */
const CONFIG_LABEL: Record<string, string> = {
  path: "路径",
  default_recording: "默认录像目标",
  remote: "远程名",
  base_path: "基础路径",
  provider: "提供方",
  default_archive: "默认归档目标",
  warning_used_percent: "告警水位",
  high_used_percent: "高水位",
  critical_used_percent: "临界水位",
}

/** 凭据永远不该出现在 config 里；真出现了也不展示，只说明有值。 */
const SECRET_KEY = /(pass|secret|token|credential|apikey|api_key)/i

/* ------------------------------------------------------------ Probe state */

/** 按 target id 存的探测结果，互相不覆盖：探测 A 不会清掉 B 的结果。 */
type ProbeState =
  | { status: "idle" }
  | { status: "probing" }
  | { status: "done"; result: StorageTargetTest }
  | { status: "failed"; reason: string }

/* --------------------------------------------------------- Config 渲染 */

function ConfigValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">—</span>
  }
  if (typeof value === "boolean") {
    return <span>{value ? "是" : "否"}</span>
  }
  if (typeof value === "number") {
    return <span className="tabular-nums">{value}</span>
  }
  if (typeof value === "string") {
    return <span className="break-all">{value || "（空字符串）"}</span>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-muted-foreground">（空列表）</span>
    }
    const flat = value.filter((v) => v === null || typeof v !== "object")
    if (flat.length !== value.length || depth >= 2) {
      return <span className="text-muted-foreground">{value.length} 项</span>
    }
    return <span className="break-all">{flat.map((v) => String(v)).join("、")}</span>
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) {
      return <span className="text-muted-foreground">（空对象）</span>
    }
    if (depth >= 2) {
      return (
        <span className="text-muted-foreground">
          {entries.length} 项（层级过深，未展开）
        </span>
      )
    }
    return (
      <div className="space-y-0.5">
        {entries.map(([k, v]) => (
          <p key={k} className="text-left text-[11px] leading-relaxed">
            <span className="text-muted-foreground">
              {CONFIG_LABEL[k] ?? k}：
            </span>
            {SECRET_KEY.test(k) ? (
              <span className="text-muted-foreground">不展示</span>
            ) : (
              <ConfigValue value={v} depth={depth + 1} />
            )}
          </p>
        ))}
      </div>
    )
  }
  return <span className="text-muted-foreground">（未知类型）</span>
}

function TargetConfig({ config }: { config: Record<string, unknown> }) {
  const entries = Object.entries(config)
  if (entries.length === 0) {
    return <p className="text-[11px] text-muted-foreground">config 为空</p>
  }
  return (
    <dl className="space-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-3 text-[11px]">
          <dt className="shrink-0 text-muted-foreground">
            {CONFIG_LABEL[k] ?? k}
          </dt>
          <dd className="min-w-0 text-right">
            {SECRET_KEY.test(k) ? (
              <span className="text-muted-foreground">不展示</span>
            ) : (
              <ConfigValue value={v} />
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/* ---------------------------------------------------------- 容量槽 */

function CapacitySlot({ state }: { state: ProbeState | undefined }) {
  if (!state || state.status === "idle") {
    return (
      <div className="rounded-lg border border-dashed border-border px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Gauge className="size-3.5" /> 尚未检测
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          列表接口不返回容量，这里没有水位数据，也没有 0% 可填。检测会实际访问该目标。
        </p>
      </div>
    )
  }

  if (state.status === "probing") {
    return (
      <div className="rounded-lg border border-border bg-muted/40 px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-xs">
          <RefreshCw className="size-3.5 animate-spin" /> 正在检测…
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          等待后端返回该目标的容量，检测期间不显示任何数字。
        </p>
      </div>
    )
  }

  if (state.status === "failed") {
    return (
      <div className="rounded-lg border border-status-offline/30 bg-status-offline/8 px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-xs font-medium text-status-offline">
          <TriangleAlert className="size-3.5" /> 检测失败
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-foreground">
          {state.reason}
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          失败即未知，页面不会用 0% 或上一张图的数字顶替。
        </p>
      </div>
    )
  }

  const r = state.result
  if (r.used_percent === null) {
    return (
      <div className="rounded-lg border border-border bg-muted/40 px-3 py-2.5">
        <p className="text-xs">探测成功，但未返回容量</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          {r.detail || "后端没有给出 free/used/total。"}
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">容量</span>
        <span className="tabular-nums">
          {formatBytes(r.used_bytes)} / {formatBytes(r.total_bytes)}
        </span>
      </div>
      <ProgressBar
        value={r.used_percent}
        tone={r.capacity_level ? LEVEL_TONE[r.capacity_level] : "unknown"}
        showLabel
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <span className="tabular-nums">剩余 {formatBytes(r.free_bytes)}</span>
        {r.capacity_level ? (
          <Badge variant={LEVEL_BADGE[r.capacity_level]}>
            {CAPACITY_LEVEL_LABEL[r.capacity_level]}
          </Badge>
        ) : (
          <Badge variant="muted">无水位判定</Badge>
        )}
      </div>
    </div>
  )
}

/* -------------------------------------------------------- 目标卡片 */

function TargetCard({
  target,
  state,
  onProbe,
}: {
  target: StorageTarget
  state: ProbeState | undefined
  onProbe: (id: string) => void
}) {
  const TypeIcon = TYPE_META[target.type].icon
  const RoleIcon = ROLE_META[target.role].icon
  const probing = state?.status === "probing"
  const probed = state?.status === "done" || state?.status === "failed"
  const isCurrentRecording = target.role === "recording" && target.enabled

  return (
    <Card className={cn("flex flex-col", isCurrentRecording && "border-primary/50")}>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <TypeIcon className="size-4 text-muted-foreground" />
            <span className="truncate">{target.name}</span>
          </CardTitle>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">{TYPE_META[target.type].label}</Badge>
            <Badge variant={ROLE_META[target.role].variant}>
              <RoleIcon className="size-3" />
              {ROLE_META[target.role].label}
            </Badge>
            {isCurrentRecording && (
              <Badge variant="default">当前录像目标</Badge>
            )}
            <Badge variant={target.enabled ? "success" : "muted"}>
              {target.enabled ? "已启用" : "已停用"}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">凭据</span>
          {target.credentials_configured ? (
            <span className="inline-flex items-center gap-1 text-status-online">
              <CircleCheck className="size-3.5" /> 已配置
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-status-degraded">
              <TriangleAlert className="size-3.5" /> 未配置
            </span>
          )}
        </div>

        <TargetConfig config={target.config} />

        <div className="mt-auto space-y-2">
          <CapacitySlot state={state} />
          <div className="flex items-center justify-between gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={probing}
              onClick={() => onProbe(target.id)}
            >
              {probing ? (
                <>
                  <RefreshCw className="animate-spin" /> 检测中…
                </>
              ) : (
                <>
                  <Gauge /> {probed ? "重新检测容量" : "检测容量"}
                </>
              )}
            </Button>
            <span className="text-[11px] text-muted-foreground">
              {probed ? "上次结果保留在本次会话" : "检测 = 真实访问该目标"}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/* --------------------------------------------------------------- Page */

export function StorageView() {
  const [probes, setProbes] = useState<Record<string, ProbeState>>({})
  const [q, setQ] = useState("")
  const [scope, setScope] = useState("all")

  const {
    data: targets,
    isLoading: targetsLoading,
    error: targetsError,
    refetch: refetchTargets,
  } = useStorageTargets()
  const {
    data: policies,
    isLoading: policiesLoading,
    error: policiesError,
    refetch: refetchPolicies,
  } = useRetentionPolicies()

  const list = useMemo(() => targets ?? [], [targets])

  async function runProbe(id: string) {
    setProbes((prev) => ({ ...prev, [id]: { status: "probing" } }))
    try {
      const result = await probeTarget(id)
      setProbes((prev) => ({
        ...prev,
        [id]: result.ok
          ? { status: "done", result }
          : { status: "failed", reason: result.detail || "后端未给出失败原因" },
      }))
    } catch (e) {
      setProbes((prev) => ({
        ...prev,
        [id]: {
          status: "failed",
          reason: e instanceof Error ? e.message : "检测请求失败",
        },
      }))
    }
  }

  const stats = useMemo(() => {
    const recording = list.filter((t) => t.role === "recording")
    const enabledRecording = recording.filter((t) => t.enabled)
    return {
      total: list.length,
      recording: recording.length,
      enabledRecording: enabledRecording.length,
      archive: list.filter((t) => t.role === "archive").length,
      missingCredentials: list.filter((t) => !t.credentials_configured).length,
    }
  }, [list])

  /** 只统计真的探测出数字的目标；一个都没探测就明确说未知。 */
  const capacity = useMemo(() => {
    const measured = Object.values(probes).filter(
      (p): p is { status: "done"; result: StorageTargetTest } =>
        p.status === "done" && p.result.used_percent !== null,
    )
    return {
      measuredCount: measured.length,
      used: measured.reduce((sum, p) => sum + (p.result.used_bytes ?? 0), 0),
      total: measured.reduce((sum, p) => sum + (p.result.total_bytes ?? 0), 0),
    }
  }, [probes])

  const policyRows = useMemo(() => {
    const all = policies ?? []
    return all.filter((p) => {
      if (scope !== "all" && p.scope_type !== scope) return false
      if (q && !`${p.name}${p.scope_id ?? ""}`.includes(q)) return false
      return true
    })
  }, [policies, q, scope])

  const policyColumns = useMemo<ColumnDef<RetentionPolicy, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "策略",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate font-medium">{row.original.name}</p>
            <p className="truncate text-[11px] text-muted-foreground">
              {SCOPE_LABEL[row.original.scope_type]}
              {row.original.scope_id
                ? ` · ${row.original.scope_id.slice(0, 8)}`
                : ""}
            </p>
          </div>
        ),
      },
      {
        id: "keep_days",
        accessorFn: (p) => p.ordinary_keep_days,
        header: "保留天数 普通 / 事件 / 手动",
        cell: ({ row }) => {
          const p = row.original
          return (
            <span className="text-xs tabular-nums">
              {p.ordinary_keep_days} / {p.event_keep_days} / {p.manual_keep_days} 天
            </span>
          )
        },
      },
      {
        accessorKey: "mode",
        header: "清理模式",
        cell: ({ row }) => (
          <div className="flex flex-col">
            <Badge
              variant={row.original.mode === "HARD" ? "secondary" : "warning"}
            >
              {MODE_LABEL[row.original.mode]}
            </Badge>
            <span className="mt-0.5 text-[11px] text-muted-foreground">
              {MODE_HINT[row.original.mode]}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "require_archive_before_delete",
        header: "先归档后删除",
        cell: ({ row }) =>
          row.original.require_archive_before_delete ? (
            <span className="inline-flex items-center gap-1.5 text-xs">
              <ShieldCheck className="size-3.5 text-status-online" /> 安全删除
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs text-status-degraded">
              <TriangleAlert className="size-3.5" /> 到期直接删除
            </span>
          ),
      },
      {
        accessorKey: "enabled",
        header: "启用",
        cell: ({ row }) => (
          <Badge variant={row.original.enabled ? "success" : "muted"}>
            {row.original.enabled ? "已启用" : "已停用"}
          </Badge>
        ),
      },
    ],
    [],
  )

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="存储"
        description="存储目标、容量水位与保留策略。容量不来自列表接口，需要逐个目标主动检测。"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void refetchTargets()
              void refetchPolicies()
            }}
          >
            <RefreshCw /> 刷新
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <StatCard label="目标总数" value={stats.total} unit="个" />
        <StatCard
          label="录像目标"
          value={stats.recording}
          unit="个"
          tone={stats.enabledRecording === 0 ? "offline" : "online"}
          hint={
            stats.enabledRecording === 0
              ? "没有已启用的录像目标，新录像无处写入"
              : `已启用 ${stats.enabledRecording} 个`
          }
        />
        <StatCard label="归档目标" value={stats.archive} unit="个" />
        <StatCard
          label="未配置凭据"
          value={stats.missingCredentials}
          unit="个"
          tone={stats.missingCredentials > 0 ? "degraded" : "online"}
          hint={
            stats.missingCredentials > 0
              ? "这些目标无法完成凭据校验"
              : "全部已配置"
          }
        />
        <StatCard
          label="容量"
          icon={<Gauge className="size-4" />}
          value={
            capacity.measuredCount > 0
              ? `${formatBytes(capacity.used)} / ${formatBytes(capacity.total)}`
              : "尚未检测"
          }
          tone={capacity.measuredCount > 0 ? undefined : "unknown"}
          hint={
            capacity.measuredCount > 0
              ? `仅统计已检测的 ${capacity.measuredCount} / ${stats.total} 个目标`
              : "列表接口不返回容量"
          }
        />
      </div>

      <Section
        title="存储目标"
        description="标记「当前录像目标」的那个目标承载实时写入；其余用于归档。凭据状态是后端返回的布尔值，页面上没有任何凭据内容可读。"
      >
        {targetsLoading ? (
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Card key={i} className="p-4">
                <div className="h-4 w-32 animate-pulse rounded bg-muted" />
                <div className="mt-3 h-3 w-24 animate-pulse rounded bg-muted" />
                <div className="mt-4 h-16 w-full animate-pulse rounded bg-muted" />
              </Card>
            ))}
          </div>
        ) : targetsError ? (
          <Callout tone="offline" title="存储目标加载失败">
            <p>{targetsError.message}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => void refetchTargets()}
            >
              <RefreshCw /> 重试
            </Button>
          </Callout>
        ) : list.length === 0 ? (
          <EmptyState
            icon={<HardDrive />}
            title="没有配置存储目标"
            description="录像需要至少一个已启用的本地目标。没有目标时保留策略不会删除任何东西，新录像也不会落盘。"
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
            {list.map((t) => (
              <TargetCard
                key={t.id}
                target={t}
                state={probes[t.id]}
                onProbe={(id) => void runProbe(id)}
              />
            ))}
          </div>
        )}
      </Section>

      <Section
        title="保留策略"
        description="普通 / 事件 / 手动三类录像各自的保留天数与清理方式。接口不返回 sweep 的执行时间与结果，所以这里没有「上次执行」这一列。"
      >
        <DataTable
          columns={policyColumns}
          data={policyRows}
          isLoading={policiesLoading}
          error={policiesError}
          onRetry={() => void refetchPolicies()}
          emptyTitle="没有匹配的保留策略"
          emptyDescription="调整搜索词或范围筛选。"
          toolbar={
            <>
              <Input
                className="w-48"
                placeholder="搜索策略名称"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <Select
                className="w-32"
                value={scope}
                onChange={(e) => setScope(e.target.value)}
              >
                <option value="all">全部范围</option>
                <option value="GLOBAL">全局</option>
                <option value="CAMERA">单相机</option>
                <option value="CAMERA_GROUP">相机组</option>
              </Select>
              <span className="ml-auto text-xs text-muted-foreground">
                {policyRows.length} / {policies?.length ?? 0} 条
              </span>
            </>
          }
        />

        <Callout tone="online" title="先归档、后删除：这是安全删除，不是删除">
          带 <span className="text-foreground">「安全删除」</span>的策略要求清理前先确认归档副本
          真的存在：sweep 先把待清理片段写入归档目标，只有确认归档可用才删除本地副本。
          归档失败时片段
          <span className="text-foreground">留在原地</span>，等待下次执行重试，不会因为一次云端故障
          把磁盘清空。代价是这段时间容量只涨不降。标为「到期直接删除」的策略没有这层保护。
        </Callout>
      </Section>

      <Callout tone="degraded" title="容量拿不到，是接口的缺口，不是页面的取巧">
        GET /api/v1/storage/targets 返回的是 StorageTargetView，只有{" "}
        <span className="font-mono text-foreground">
          {"id, type, role, name, enabled, config, credentials_configured"}
        </span>
        ——整个读路径上没有任何
        free / used / percent 字段。容量只出现在 POST /storage/targets/:id/test 的响应里，
        而那是一个会真实访问目标的 POST：挂在页面上等于给每个目标开一个定时探测，
        改成 GET 也不会更对。正确的修法是后端补一个只读统计接口（挂上
        capacity_level 与水位阈值，或直接并进列表），前端就能像摄像机状态那样随轮询刷新。
        在那之前，页面上「检测容量」按目标逐个触发，结果只存在于本次会话：响应里连探测时间戳都没有，
        刷新页面就回到「尚未检测」，因此这里也不显示「上次检测时间」。
      </Callout>
    </div>
  )
}
