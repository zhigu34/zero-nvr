import { useEffect, useMemo, useState } from "react"
import {
  Bell,
  BellRing,
  Check,
  Copy,
  Plus,
  Shield,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react"

import {
  MATCH_KEYS,
  MATCH_KEY_META,
  alertStateLabel,
  mergeMatch,
  severityLabel,
  severityTone,
  unmanagedMatchKeys,
  type AlertMatch,
  type AlertPolicyView,
  type AlertSeverity,
  type MatchKey,
} from "../api/alerts"
import {
  clearTimeWindow,
  hasMatchErrors,
  importFromRecordingFilter,
  recordingFilterKeys,
  validateMatch,
  weekdayLabel,
  MAX_COOLDOWN_SECONDS,
} from "../lib/alertValidation"
import {
  useAcknowledgeAlert,
  useCreateAlertPolicy,
  useDeleteAlertPolicy,
  useResolveAlert,
  useUpdateAlertPolicy,
} from "../lib/alertMutations"
import { useAlertPolicies, useAlerts, useCameras, useRecordingPolicies } from "../lib/queries"
import { formatClock, formatRelative } from "../lib/format"
import { Badge, Button, Input, Select, Switch } from "../components/ui/primitives"
import {
  Callout,
  Checkbox,
  EmptyState,
  Field,
  PageHeader,
  PrototypeNote,
  RowActions,
  Segmented,
  StatusDot,
  StatusLabel,
  Tabs,
} from "../components/ui/display"
import { cn } from "../lib/utils"

/**
 * 告警规则 + 告警列表。
 *
 * ## The two filters are deliberately not merged
 *
 * The rule editor's `match` and a camera's recording `event_filter` overlap
 * on three keys and **disagree about two of them**. `zones` is the sharp one:
 * the recording side reads `event.metadata_json["zones"]` (every region the
 * event touched) while the alert side reads `Event.zone` (the primary region
 * only). For a multi-region provider, copying it produces two rules that look
 * identical and behave differently — the recording exists and no alert fires.
 *
 * That is D-2, and it is undecided. So this page does not resolve it. It
 * shows the recording filter read-only, offers a per-key copy **only for the
 * two keys whose meaning is identical** (`labels`, `min_confidence`), and
 * prints the reason beside every other one. That shape is correct whichever
 * way D-2 goes, because it changes no backend behaviour on its own.
 *
 * ## The bug this rewrite is really about
 *
 * `PATCH /alert-policies/{id}` replaces `match` wholesale. The Vue screen
 * rebuilt the object from the fields it showed
 * (`SystemAlertRulesPanel.vue:275-298`), so any rule carrying a key the form
 * did not render lost it on the first save — with a 200 in response. Every
 * save here goes through `mergeMatch(existing, draft)`, and the mutation
 * merges again as a backstop.
 */

type Tab = "policies" | "alerts"
type Panel = "none" | "create" | AlertPolicyView

export function AlertsView() {
  const [tab, setTab] = useState<Tab>("policies")
  const [panel, setPanel] = useState<Panel>("none")
  const policies = useAlertPolicies()

  const openAlerts = useAlerts({ state: "OPEN" })

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <PageHeader
          title="告警"
          description="匹配规则与产生的告警。规则里的过滤条件与录制计划的事件过滤是两套独立配置，本页不做合并。"
          actions={
            <Button size="sm" onClick={() => setPanel("create")}>
              <Plus /> 新建规则
            </Button>
          }
        />
      </div>

      <div className="shrink-0 border-b border-border px-4">
        <Tabs
          active={tab}
          onChange={(key) => setTab(key as Tab)}
          tabs={[
            { key: "policies", label: "告警规则", count: policies.data?.length },
            { key: "alerts", label: "告警", count: openAlerts.data?.pages[0]?.items.length },
          ]}
        />
      </div>

      {tab === "policies" ? (
        <div className="flex min-h-0 flex-1">
          <section className="min-w-0 flex-1 overflow-auto p-4">
            <D2Notice />
            {policies.isPending ? (
              <p className="mt-4 text-xs text-muted-foreground">读取中…</p>
            ) : policies.error ? (
              <EmptyState
                icon={<TriangleAlert />}
                title="无法读取告警规则"
                description={policies.error.message}
              />
            ) : !policies.data || policies.data.length === 0 ? (
              <EmptyState
                icon={<Bell />}
                title="还没有告警规则"
                description="没有启用中的规则时，事件只会被记录，不会产生告警，也不会触发通知或录像保护。"
              />
            ) : (
              <ul className="mt-4 space-y-2">
                {policies.data.map((policy) => (
                  <li key={policy.id} className="rounded-lg border border-border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusDot tone={policy.enabled ? "online" : "unknown"} />
                      <span className="text-sm font-medium">{policy.name}</span>
                      <Badge variant={policy.severity === "critical" ? "warning" : "outline"}>
                        {severityLabel(policy.severity)}
                      </Badge>
                      {!policy.enabled && <Badge variant="outline">已停用</Badge>}
                      <span className="ml-auto flex items-center gap-1 text-[11px] tabular-nums text-muted-foreground">
                        {Object.keys(policy.match).length} 个匹配条件
                        {policy.cooldown_seconds > 0 &&
                          ` · 冷却 ${policy.cooldown_seconds}s`}
                      </span>
                      <RowActions>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="编辑"
                          onClick={() => setPanel(policy)}
                        >
                          <Shield className="size-3.5" />
                        </Button>
                        <DeletePolicyButton policy={policy} onDone={() => setPanel("none")} />
                      </RowActions>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      更新于 {formatClock(policy.updated_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {panel === "create" && <PolicyEditor onClose={() => setPanel("none")} />}
          {panel !== "none" && panel !== "create" && (
            <PolicyEditor policy={panel} onClose={() => setPanel("none")} />
          )}
        </div>
      ) : (
        <AlertList />
      )}
    </div>
  )
}

function D2Notice() {
  return (
    <Callout tone="degraded" title="录制过滤与告警匹配是两套独立配置">
      <p>
        两者在 <code className="font-mono">labels</code> 与{" "}
        <code className="font-mono">min_confidence</code> 上含义一致，可以互相参考；
        但 <code className="font-mono">zones</code> 读的是事件的两个不同字段，
        多区域事件会出现「录了但没告警」。这不是配置问题，因此本页不提供一键同步。
      </p>
      <p className="mt-1">
        详见 <code className="font-mono">docs/D-2-DECISION-MATERIAL.md</code>。
      </p>
    </Callout>
  )
}

function DeletePolicyButton({
  policy,
  onDone,
}: {
  policy: AlertPolicyView
  onDone: () => void
}) {
  const remove = useDeleteAlertPolicy()
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      title="删除该规则"
      disabled={remove.isPending}
      onClick={() => remove.mutate(policy.id, { onSuccess: onDone })}
    >
      <Trash2 className="size-3.5" />
    </Button>
  )
}

/* -------------------------------------------------------------------------- */
/* Policy editor                                                              */
/* -------------------------------------------------------------------------- */

function PolicyEditor({
  policy,
  onClose,
}: {
  policy?: AlertPolicyView
  onClose: () => void
}) {
  const creating = !policy
  const existing = policy?.match ?? {}

  const [name, setName] = useState(policy?.name ?? "")
  const [enabled, setEnabled] = useState(policy?.enabled ?? true)
  const [severity, setSeverity] = useState<AlertSeverity>(policy?.severity ?? "warning")
  const [cooldown, setCooldown] = useState(String(policy?.cooldown_seconds ?? 0))
  const [draft, setDraft] = useState<AlertMatch>({ ...existing })

  const create = useCreateAlertPolicy()
  const update = useUpdateAlertPolicy(policy?.id ?? "", existing)

  const errors = validateMatch(draft)
  const unmanaged = unmanagedMatchKeys(existing)

  const dirty =
    creating ||
    name !== (policy?.name ?? "") ||
    enabled !== (policy?.enabled ?? true) ||
    severity !== (policy?.severity ?? "warning") ||
    cooldown !== String(policy?.cooldown_seconds ?? 0) ||
    JSON.stringify(draft) !== JSON.stringify(existing)

  const cooldownValue = Number(cooldown)
  const cooldownError =
    !Number.isInteger(cooldownValue) || cooldownValue < 0 || cooldownValue > MAX_COOLDOWN_SECONDS
      ? `须为 0–${MAX_COOLDOWN_SECONDS} 秒的整数`
      : null

  const blocked = hasMatchErrors(errors) || Boolean(cooldownError) || name.trim() === ""

  function submit() {
    if (blocked) return
    const body = {
      name: name.trim(),
      enabled,
      severity,
      cooldown_seconds: cooldownValue,
      match: creating ? draft : mergeMatch(existing, draft),
    }
    if (creating) create.mutate(body, { onSuccess: onClose })
    else update.mutate(body, { onSuccess: onClose })
  }

  return (
    <aside className="w-[30rem] shrink-0 overflow-y-auto border-l border-border">
      <div className="sticky top-0 flex items-center justify-between border-b border-border bg-background px-4 py-3">
        <h2 className="text-sm font-semibold">
          {creating ? "新建告警规则" : `编辑：${policy!.name}`}
        </h2>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭">
          <X className="size-3.5" />
        </Button>
      </div>

      <div className="p-4">
        <Field label="名称">
          <Input value={name} aria-label="规则名称" onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="启用" hint="停用后规则保留但不参与匹配。">
          <Switch
            aria-checked={enabled}
            role="switch"
            aria-label="启用该规则"
            onClick={() => setEnabled((v) => !v)}
          />
        </Field>
        <Field
          label="严重度"
          hint="规则命中后产生的告警级别。与匹配条件里的「事件严重度」是两回事。"
        >
          <Select
            className="w-32"
            value={severity}
            aria-label="告警严重度"
            onChange={(e) => setSeverity(e.target.value as AlertSeverity)}
          >
            <option value="info">提示</option>
            <option value="warning">警告</option>
            <option value="critical">严重</option>
          </Select>
        </Field>
        <Field label="冷却秒数" hint={`0–${MAX_COOLDOWN_SECONDS}。冷却期内同一事件不重复告警。`}>
          <Input
            className="w-32"
            inputMode="numeric"
            value={cooldown}
            aria-label="冷却秒数"
            onChange={(e) => setCooldown(e.target.value)}
          />
        </Field>
        {cooldownError && (
          <p className="pb-2 text-[11px] text-status-offline">{cooldownError}</p>
        )}

        {unmanaged.length > 0 && (
          <Callout tone="degraded" className="mb-3" title="有本表单未覆盖的字段">
            <p>
              保存时会原样保留：{unmanaged.join("、")}。这是有意的——但也意味着
              本页无法纠正这些字段。
            </p>
          </Callout>
        )}

        <MatchFields draft={draft} onChange={setDraft} errors={errors} />
        <RecordingReference draft={draft} onChange={setDraft} />

        <div className="mt-4 flex items-center justify-end gap-2">
          {dirty && <span className="mr-auto text-[11px] text-status-degraded">有未保存的修改</span>}
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            size="sm"
            disabled={blocked || create.isPending || update.isPending}
            onClick={submit}
          >
            {create.isPending || update.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>
    </aside>
  )
}

/**
 * One input per key in `MATCH_KEYS`.
 *
 * The completeness of this mapping is load-bearing: `mergeMatch` treats every
 * key in that list as authoritative, so a key added to the list without an
 * input here would start being cleared on every save. `AlertsView.spec.tsx`
 * asserts the two lists stay the same length.
 */
function MatchFields({
  draft,
  onChange,
  errors,
}: {
  draft: AlertMatch
  onChange: (next: AlertMatch) => void
  errors: Partial<Record<MatchKey, string>>
}) {
  const set = (key: MatchKey, value: unknown) => {
    const next = { ...draft }
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
      delete next[key]
    } else {
      next[key] = value
    }
    onChange(next)
  }
  const list = (key: MatchKey) =>
    Array.isArray(draft[key]) ? (draft[key] as string[]) : []

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold">匹配条件</h3>
      <p className="text-[11px] text-muted-foreground">
        留空表示不限制。全部字段留空时规则匹配所有事件。
      </p>

      {MATCH_KEYS.map((key) => {
        const meta = MATCH_KEY_META[key]
        const error = errors[key]
        return (
          <div key={key} className="space-y-1">
            <label className="flex items-center justify-between text-xs font-medium">
              <span>
                {meta.label}
                {meta.maxItems > 0 && (
                  <span className="ml-1 font-normal text-muted-foreground">
                    （≤{meta.maxItems}）
                  </span>
                )}
              </span>
            </label>

            {meta.kind === "string-list" || meta.kind === "uuid-list" ? (
              <ListInput
                ariaLabel={meta.label}
                values={list(key)}
                onChange={(values) => set(key, values)}
              />
            ) : meta.kind === "number" ? (
              <Input
                inputMode="decimal"
                aria-label={meta.label}
                value={(draft[key] as string | number) ?? ""}
                onChange={(e) => set(key, e.target.value)}
              />
            ) : meta.kind === "weekdays" ? (
              <WeekdayPicker
                value={Array.isArray(draft.weekdays) ? (draft.weekdays as number[]) : []}
                onChange={(days) => set("weekdays", days)}
              />
            ) : meta.kind === "time" || meta.kind === "tz" ? (
              <div className="flex items-center gap-2">
                <Input
                  className="w-28"
                  placeholder="HH:MM"
                  aria-label={meta.label}
                  value={(draft[key] as string) ?? ""}
                  onChange={(e) => set(key, e.target.value)}
                />
                {key === "time_end" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    title="清除整个时间窗"
                    onClick={() => onChange(clearTimeWindow(draft))}
                  >
                    清除时间窗
                  </Button>
                )}
              </div>
            ) : null}

            {error && <p className="text-[11px] text-status-offline">{error}</p>}
          </div>
        )
      })}
    </section>
  )
}

function ListInput({
  values,
  onChange,
  ariaLabel,
}: {
  values: string[]
  onChange: (next: string[]) => void
  ariaLabel: string
}) {
  const [text, setText] = useState("")
  return (
    <div className="space-y-1.5">
      {values.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {values.map((value) => (
            <li
              key={value}
              className="flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px]"
            >
              {value}
              <button
                type="button"
                aria-label={`移除 ${value}`}
                onClick={() => onChange(values.filter((v) => v !== value))}
                className="text-muted-foreground hover:text-foreground"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-1.5">
        <Input
          value={text}
          aria-label={`新增${ariaLabel}`}
          placeholder="输入后回车"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return
            e.preventDefault()
            const value = text.trim()
            if (!value || values.includes(value)) {
              setText("")
              return
            }
            onChange([...values, value])
            setText("")
          }}
        />
      </div>
    </div>
  )
}

function WeekdayPicker({
  value,
  onChange,
}: {
  value: number[]
  onChange: (next: number[]) => void
}) {
  return (
    <div className="flex gap-1" role="group" aria-label="星期">
      {WEEKDAYS.map((day) => (
        <button
          key={day}
          type="button"
          aria-pressed={value.includes(day)}
          aria-label={weekdayLabel(day)}
          onClick={() =>
            onChange(
              value.includes(day) ? value.filter((d) => d !== day) : [...value, day].sort(),
            )
          }
          className={cn(
            "size-7 rounded border text-[11px] transition-colors",
            value.includes(day)
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border hover:bg-accent",
          )}
        >
          {weekdayLabel(day).slice(1)}
        </button>
      ))}
    </div>
  )
}

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const

/* -------------------------------------------------------------------------- */
/* The D-2 read-only reference                                               */
/* -------------------------------------------------------------------------- */

function RecordingReference({
  draft,
  onChange,
}: {
  draft: AlertMatch
  onChange: (next: AlertMatch) => void
}) {
  const policies = useRecordingPolicies()
  const [cameraId, setCameraId] = useState("")

  const cameras = useCameras()
  const policy = useMemo(
    () => policies.data?.find((p) => p.camera_id === cameraId) ?? null,
    [policies.data, cameraId],
  )
  const eventFilter = (policy?.event_filter ?? null) as Record<string, unknown> | null
  const keys = recordingFilterKeys(eventFilter)

  return (
    <section className="mt-5 space-y-2 rounded-lg border border-border p-3">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Copy className="size-3.5 text-muted-foreground" />
        参考：该机位的录制事件过滤
      </h3>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        只读参考，不会自动同步。仅对两侧含义一致的字段提供复制。
      </p>

      <Select
        value={cameraId}
        aria-label="选择参考机位"
        onChange={(e) => setCameraId(e.target.value)}
      >
        <option value="">选择机位…</option>
        {(cameras.data ?? []).map((camera) => (
          <option key={camera.id} value={camera.id}>
            {camera.name}
          </option>
        ))}
      </Select>

      {cameraId && !policy && (
        <p className="text-[11px] text-muted-foreground">该机位没有录制计划。</p>
      )}

      {policy && keys.length === 0 && (
        <p className="text-[11px] text-muted-foreground">
          该机位的录制计划未设置事件过滤。
        </p>
      )}

      {keys.map((key) => {
        const meta = MATCH_KEY_META[key]
        const result = importFromRecordingFilter(draft, eventFilter, key, {
          allowed: meta.importable,
        })
        return (
          <div key={key} className="rounded border border-border p-2">
            <p className="text-[11px] font-medium">{meta.label}</p>
            <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] text-muted-foreground">
              {JSON.stringify(eventFilter?.[key])}
            </pre>
            {meta.importable ? (
              <Button
                variant="outline"
                size="sm"
                className="mt-1.5"
                onClick={() => onChange(result.draft)}
              >
                <Copy /> 复制到本规则
              </Button>
            ) : (
              <p className="mt-1 text-[10px] leading-relaxed text-status-degraded">
                {meta.importNote}
              </p>
            )}
          </div>
        )
      })}

      <PrototypeNote>
        两套过滤之间没有连接键：录制策略按摄像机唯一，告警策略是全局的、摄像机范围写在
        match.camera_ids 里。因此不存在「自动同步」，只有上面这种逐字段的显式复制。
      </PrototypeNote>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Alert list                                                                 */
/* -------------------------------------------------------------------------- */

function AlertList() {
  const [state, setState] = useState("OPEN")
  const [severity, setSeverity] = useState("")
  const query = useAlerts({ state: state || undefined, severity: severity || undefined })
  const acknowledge = useAcknowledgeAlert()
  const resolve = useResolveAlert()

  const rows = query.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-2.5">
        <Segmented
          value={state}
          onChange={setState}
          options={[
            { value: "", label: "全部" },
            { value: "OPEN", label: "未处理" },
            { value: "ACKNOWLEDGED", label: "已确认" },
            { value: "RESOLVED", label: "已解决" },
          ]}
        />
        <Segmented
          value={severity}
          onChange={setSeverity}
          options={[
            { value: "", label: "全部级别" },
            { value: "critical", label: "严重" },
            { value: "warning", label: "警告" },
            { value: "info", label: "提示" },
          ]}
        />
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {rows.length} 条
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {query.isPending ? (
          <p className="p-4 text-xs text-muted-foreground">读取中…</p>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<BellRing />}
              title="没有符合条件的告警"
              description="未处理的告警会自动出现在这里，不需要刷新页面。"
            />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((alert) => (
              <li key={alert.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                <StatusDot tone={severityTone(alert.severity)} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{alert.title}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    <StatusLabel tone={severityTone(alert.severity)} className="text-[10px]">
                      {severityLabel(alert.severity)}
                    </StatusLabel>
                    <span className="ml-1.5">{alertStateLabel(alert.state)}</span>
                    {alert.message && <span className="ml-1.5">{alert.message}</span>}
                    <span className="ml-1.5" title={formatClock(alert.created_at)}>
                      {formatRelative(alert.created_at)}
                    </span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {alert.state === "OPEN" && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={acknowledge.isPending}
                      onClick={() => acknowledge.mutate(alert.id)}
                    >
                      <Check /> 确认
                    </Button>
                  )}
                  {alert.state !== "RESOLVED" && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate(alert.id)}
                    >
                      标记解决
                    </Button>
                  )}
                </div>
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
      </div>
    </div>
  )
}
