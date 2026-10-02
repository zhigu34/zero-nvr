import { useMemo, useState } from "react"
import { FileSearch, RefreshCw, ScrollText, TriangleAlert } from "lucide-react"

import {
  actionGroup,
  actorTypeLabel,
  changedKeys,
  resultLabel,
  resultTone,
  type AuditEventView,
  type AuditFilters,
} from "../api/audit"
import { useAuditEvents, useCameras, useUsers } from "../lib/queries"
import { formatClock, formatRelative } from "../lib/format"
import { Badge, Button, Input, Select } from "../components/ui/primitives"
import {
  Callout,
  EmptyState,
  PageHeader,
  StatusDot,
  StatusLabel,
} from "../components/ui/display"
import { cn } from "../lib/utils"

/**
 * 审计日志。
 *
 * Unlike most screens here this one is a plain filterable log, and the design
 * work is in not over-claiming what the payload contains.
 *
 * **The actor is a UUID.** `AuditEventView.actor_id` is an id, and
 * `actor_type` is a bare string with no enum. Names live in `/users`, a
 * separate `user.manage` resource. An administrator has both, so the names are
 * joined in memory; anyone without it sees the id rather than a blank cell —
 * a blank reads as "anonymous" and would be wrong. See G-30.
 *
 * **Camera filtering is scope-enforced server-side.** `list_audit_events`
 * threads `allowed_camera_ids` into the query (`audit/api.py:88-94`), so a
 * narrowed operator simply does not get entries for cameras outside their
 * scope. There is nothing to mirror in the UI, and claiming otherwise would
 * be a promise the backend does not make.
 *
 * **`before`/`after` are best-effort.** The backend fills them on some
 * actions and not others, with no flag saying which. "No difference" and
 * "nothing was recorded" look identical in the payload, so the detail panel
 * says which one it is showing rather than rendering an empty diff.
 */

type QuickWindow = "all" | "24h" | "7d"

export function AuditView() {
  const [window, setWindow] = useState<QuickWindow>("24h")
  const [action, setAction] = useState("")
  const [result, setResult] = useState("")
  const [resourceType, setResourceType] = useState("")
  const [actorId, setActorId] = useState("")
  const [cameraId, setCameraId] = useState("")
  const [selected, setSelected] = useState<AuditEventView | null>(null)

  const users = useUsers()
  const cameras = useCameras()

  const actorNames = useMemo(
    () => new Map((users.data ?? []).map((u) => [u.id, u.display_name])),
    [users.data],
  )
  const cameraNames = useMemo(
    () => new Map((cameras.data ?? []).map((c) => [c.id, c.name])),
    [cameras.data],
  )

  const filters = useMemo<AuditFilters>(() => {
    const now = Date.now()
    return {
      action: action || undefined,
      result: result || undefined,
      resourceType: resourceType || undefined,
      actorId: actorId || undefined,
      cameraId: cameraId || undefined,
      from:
        window === "all"
          ? undefined
          : new Date(
              now - (window === "24h" ? 1 : 7) * 24 * 60 * 60 * 1000,
            ).toISOString(),
    }
  }, [action, result, resourceType, actorId, cameraId, window])

  const query = useAuditEvents(filters)
  const rows = query.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <PageHeader
          title="审计日志"
          description="所有写操作的留痕。范围与筛选都在服务端完成，页面不持有全量日志。"
          actions={
            <>
              <Badge variant="outline">{rows.length} 条</Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void query.refetch()}
              >
                <RefreshCw /> 刷新
              </Button>
            </>
          }
        />
      </div>

      <div className="flex shrink-0 flex-wrap items-end gap-2 border-b border-border px-4 py-2.5">
        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">时间</span>
          <Select
            className="w-32"
            value={window}
            aria-label="时间范围"
            onChange={(e) => setWindow(e.target.value as QuickWindow)}
          >
            <option value="24h">最近 24 小时</option>
            <option value="7d">最近 7 天</option>
            <option value="all">全部</option>
          </Select>
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">操作</span>
          <Input
            className="w-44"
            placeholder="如 export.create"
            value={action}
            aria-label="按操作筛选"
            onChange={(e) => setAction(e.target.value.trim())}
          />
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">资源类型</span>
          <Input
            className="w-36"
            placeholder="如 export"
            value={resourceType}
            aria-label="按资源类型筛选"
            onChange={(e) => setResourceType(e.target.value.trim())}
          />
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">结果</span>
          <Select
            className="w-28"
            value={result}
            aria-label="按结果筛选"
            onChange={(e) => setResult(e.target.value)}
          >
            <option value="">全部</option>
            <option value="SUCCESS">成功</option>
            <option value="DENIED">拒绝</option>
            <option value="FAILURE">失败</option>
          </Select>
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">操作者</span>
          <Select
            className="w-40"
            value={actorId}
            aria-label="按操作者筛选"
            onChange={(e) => setActorId(e.target.value)}
          >
            <option value="">全部</option>
            {(users.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name}
              </option>
            ))}
          </Select>
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">机位</span>
          <Select
            className="w-40"
            value={cameraId}
            aria-label="按机位筛选"
            onChange={(e) => setCameraId(e.target.value)}
          >
            <option value="">全部</option>
            {(cameras.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </label>
      </div>

      <div className="flex min-h-0 flex-1">
        <section className="min-w-0 flex-1 overflow-auto">
          {query.isPending ? (
            <p className="p-4 text-xs text-muted-foreground">读取中…</p>
          ) : query.error ? (
            <div className="p-4">
              <EmptyState
                icon={<TriangleAlert />}
                title="无法读取审计日志"
                description={query.error.message}
              />
            </div>
          ) : rows.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<ScrollText />}
                title="该条件下没有记录"
                description="审计日志按时间倒序游标分页。放宽时间范围或清空筛选再试。"
              />
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {rows.map((event) => (
                <li key={event.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(event)}
                    className={cn(
                      "flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent",
                      selected?.id === event.id && "bg-accent",
                    )}
                  >
                    <StatusDot tone={resultTone(event.result)} className="mt-1.5" />
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-1.5 text-xs">
                        <span className="font-mono font-medium">{event.action}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {actionGroup(event.action)}
                        </span>
                        <StatusLabel tone={resultTone(event.result)} className="text-[10px]">
                          {resultLabel(event.result)}
                        </StatusLabel>
                        {event.reason && (
                          <span className="text-[10px] text-status-degraded">
                            {event.reason}
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {actorLabel(event, actorNames)} · {actorTypeLabel(event.actor_type)}
                        {event.resource_type && <> · {event.resource_type}</>}
                        {event.camera_id && (
                          <> · {cameraNames.get(event.camera_id) ?? "未知机位"}</>
                        )}
                        {event.source_ip && <> · {event.source_ip}</>}
                      </p>
                    </div>
                    <span
                      className="shrink-0 text-right text-[11px] tabular-nums text-muted-foreground"
                      title={formatClock(event.occurred_at)}
                    >
                      {formatRelative(event.occurred_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {query.hasNextPage && (
            <div className="flex justify-center border-t border-border p-3">
              <Button
                variant="outline"
                size="sm"
                disabled={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                {query.isFetchingNextPage ? "读取中…" : "加载更多"}
              </Button>
            </div>
          )}
        </section>

        {selected && (
          <aside className="w-96 shrink-0 overflow-y-auto border-l border-border p-4">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                <FileSearch className="size-4 text-muted-foreground" />
                记录详情
              </h2>
              <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                关闭
              </Button>
            </div>

            <dl className="mt-3 space-y-1.5 text-xs">
              <Row label="操作">{selected.action}</Row>
              <Row label="分组">{actionGroup(selected.action)}</Row>
              <Row label="结果">
                <StatusLabel tone={resultTone(selected.result)} className="text-xs">
                  {resultLabel(selected.result)}
                </StatusLabel>
              </Row>
              <Row label="时间">{formatClock(selected.occurred_at)}</Row>
              <Row label="操作者">
                {actorLabel(selected, actorNames)}（{actorTypeLabel(selected.actor_type)}）
              </Row>
              <Row label="资源">
                {selected.resource_type}
                {selected.resource_id && (
                  <span className="ml-1 font-mono text-[10px] text-muted-foreground">
                    {selected.resource_id}
                  </span>
                )}
              </Row>
              {selected.camera_id && (
                <Row label="机位">
                  {cameraNames.get(selected.camera_id) ?? selected.camera_id}
                </Row>
              )}
              {selected.source_ip && <Row label="来源 IP">{selected.source_ip}</Row>}
              {selected.request_id && <Row label="请求 ID">{selected.request_id}</Row>}
              {selected.correlation_id && (
                <Row label="关联 ID">{selected.correlation_id}</Row>
              )}
              {selected.reason && <Row label="原因">{selected.reason}</Row>}
            </dl>

            <DiffSection event={selected} />
          </aside>
        )}
      </div>

      {users.error && (
        <div className="shrink-0 px-4 py-2">
          <Callout tone="unknown">
            无法读取用户列表，操作者显示为 ID。审计页本身不依赖它。
          </Callout>
        </div>
      )}
    </div>
  )
}

/**
 * Show the raw id when the name is unavailable. An empty cell here would read
 * as "this action had no actor", which is a materially different claim from
 * "this actor's name is not loaded".
 */
function actorLabel(
  event: AuditEventView,
  names: ReadonlyMap<string, string>,
): string {
  if (!event.actor_id) return "系统"
  return names.get(event.actor_id) ?? event.actor_id
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1 break-words">{children}</dd>
    </div>
  )
}

function DiffSection({ event }: { event: AuditEventView }) {
  const keys = changedKeys(event)
  const hasAny =
    Object.keys(event.before ?? {}).length > 0 ||
    Object.keys(event.after ?? {}).length > 0

  return (
    <section className="mt-4 space-y-2">
      <h3 className="text-xs font-medium">变更</h3>
      {!hasAny ? (
        // The two cases are indistinguishable in the payload, so say which
        // one this is instead of rendering an empty panel.
        <p className="text-[11px] text-muted-foreground">
          后端未记录该操作的字段快照。
        </p>
      ) : keys.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          前后快照内容相同。
        </p>
      ) : (
        <ul className="space-y-1.5">
          {keys.map((key) => (
            <li key={key} className="rounded-md border border-border p-2">
              <p className="font-mono text-[11px] font-medium">{key}</p>
              <div className="mt-1 grid grid-cols-2 gap-2 text-[10px]">
                <div>
                  <p className="text-muted-foreground">变更前</p>
                  <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap break-all rounded bg-muted/50 p-1.5">
                    {JSON.stringify(event.before?.[key] ?? null, null, 1)}
                  </pre>
                </div>
                <div>
                  <p className="text-muted-foreground">变更后</p>
                  <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap break-all rounded bg-muted/50 p-1.5">
                    {JSON.stringify(event.after?.[key] ?? null, null, 1)}
                  </pre>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
