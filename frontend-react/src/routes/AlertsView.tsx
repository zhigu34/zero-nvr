import { useState } from "react"
import { Bell, Check, Inbox, ListChecks, Pencil, Plus, X } from "lucide-react"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
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
  EmptyState,
  Field,
  PageHeader,
  RowActions,
  Segmented,
  StatCard,
  StatusLabel,
  Tabs,
} from "../components/ui/display"
import {
  alertPolicies,
  cameras,
  categoryLabel,
  events,
  stateLabel,
  type AlertPolicy,
  type CameraEvent,
} from "../lib/mock"

/**
 * The fixture keeps conditions as one flat string, but the real match_json is
 * nested (an OR group of categories, ANDed with the rest). Parsing it here lets
 * the table show that structure instead of one unreadable sentence.
 */
type ParsedConditions = { or: string[]; and: string[] }

function parseConditions(raw: string): ParsedConditions {
  const or: string[] = []
  const and: string[] = []
  raw
    .split("·")
    .map((s) => s.trim())
    .filter(Boolean)
    .forEach((part, i) => {
      if (part.includes(" 或 ")) {
        or.push(
          ...part
            .split("或")
            .map((s) => s.trim())
            .filter(Boolean),
        )
      } else if (i === 0) {
        or.push(part)
      } else {
        and.push(part)
      }
    })
  return { or, and }
}

function ConditionChips({ raw }: { raw: string }) {
  const { or, and } = parseConditions(raw)
  return (
    <div className="flex max-w-[420px] flex-wrap items-center gap-1 whitespace-normal">
      {or.map((t, i) => (
        <span key={t} className="flex items-center gap-1">
          {i > 0 && <Badge variant="muted">或</Badge>}
          <Badge variant="default">{t}</Badge>
        </span>
      ))}
      {and.map((t) => (
        <span key={t} className="flex items-center gap-1">
          <Badge variant="muted">且</Badge>
          <Badge variant="secondary">{t}</Badge>
        </span>
      ))}
    </div>
  )
}

export function AlertsView() {
  const [tab, setTab] = useState("rules")
  const [rules, setRules] = useState<AlertPolicy[]>(alertPolicies)
  const [filter, setFilter] = useState("pending")

  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [scope, setScope] = useState<string>(cameras[0].name)
  const [action, setAction] = useState("通知值班")

  // Inbox handling is local to this page; the fixture events double as the
  // pending alert queue so no parallel fixture is needed.
  const [overrides, setOverrides] = useState<Record<string, CameraEvent["state"]>>({})
  const stateOf = (e: CameraEvent) => overrides[e.id] ?? e.state
  const pending = events.filter((e) => stateOf(e) !== "resolved")
  const visible = pending.filter((e) => {
    if (filter === "all") return true
    return filter === "pending" ? stateOf(e) === "new" : stateOf(e) === "acknowledged"
  })

  const enabledCount = rules.filter((r) => r.enabled).length
  const hits24h = rules.reduce((a, r) => a + r.hits24h, 0)
  const unhandled = pending.filter((e) => stateOf(e) === "new").length

  const setEventState = (id: string, next: CameraEvent["state"]) =>
    setOverrides((prev) => ({ ...prev, [id]: next }))

  const matchedRule = (e: CameraEvent) =>
    rules.find((r) => r.enabled && r.cameras !== "—" && r.cameras.includes(e.camera))

  const createRule = () => {
    if (name.trim() === "") return
    setRules((prev) => [
      ...prev,
      {
        id: `ap-local-${prev.length + 1}`,
        name: name.trim(),
        enabled: true,
        cameras: scope,
        conditions: "person · 置信度 ≥ 0.8",
        actions: action,
        hits24h: 0,
      },
    ])
    setName("")
    setCreating(false)
  }

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="告警规则"
        description="事件匹配规则：按摄像机、来源、类别、标签、置信度、时段过滤。命中后可保护录像不被自动清理。"
        actions={
          <Button size="sm" onClick={() => setCreating((v) => !v)}>
            <Plus /> 新建规则
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="规则总数"
          value={rules.length}
          unit="条"
          icon={<ListChecks className="size-4" />}
        />
        <StatCard label="已启用" value={enabledCount} unit="条" tone="online" />
        <StatCard
          label="24h 命中"
          value={hits24h}
          unit="次"
          tone={hits24h > 100 ? "degraded" : "unknown"}
          hint="车库车辆停留单条占 41 次"
        />
        <StatCard
          label="未处理告警"
          value={unhandled}
          unit="条"
          tone={unhandled ? "degraded" : "online"}
          icon={<Bell className="size-4" />}
        />
      </div>

      <Callout tone="offline" title="两处真相：过滤条件互不同步">
        <code className="font-mono text-foreground">
          recording_policies.event_filter_json
        </code>{" "}
        与{" "}
        <code className="font-mono text-foreground">alert_policies.match_json</code>{" "}
        定义了重叠的字段（类别、置信度、时段），但两处各自独立配置、从不互相写入。
        在这里改一个过滤条件，录制计划页不会跟着变；反过来也一样。缺陷修复前，"
        <span className="text-foreground">请只在本页维护过滤条件</span>
        ，并把计划侧的条件视为副本。
      </Callout>

      <Card>
        <Tabs
          className="px-2"
          active={tab}
          onChange={setTab}
          tabs={[
            { key: "rules", label: "规则", count: rules.length },
            { key: "inbox", label: "收件箱", count: pending.length },
          ]}
        />
        <CardContent className="pt-3">
          {tab === "rules" ? (
            <div className="space-y-3">
              {creating && (
                <Card>
                  <CardHeader>
                    <CardTitle>新建规则</CardTitle>
                    <Badge variant="warning">写入 alert_policies.match_json</Badge>
                  </CardHeader>
                  <CardContent className="pt-1">
                    <Field label="规则名称">
                      <Input
                        className="w-56"
                        placeholder="例如：夜间周界入侵"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                      />
                    </Field>
                    <Field
                      label="摄像机范围"
                      hint="留空表示不限定机位（如设备目录类规则）"
                    >
                      <Select
                        className="w-44"
                        value={scope}
                        onChange={(e) => setScope(e.target.value)}
                      >
                        {cameras.map((c) => (
                          <option key={c.id} value={c.name}>
                            {c.name}
                          </option>
                        ))}
                        <option value="全部">全部</option>
                      </Select>
                    </Field>
                    <Field label="命中动作">
                      <Select
                        className="w-44"
                        value={action}
                        onChange={(e) => setAction(e.target.value)}
                      >
                        <option value="通知值班">通知值班</option>
                        <option value="通知安保主管">通知安保主管</option>
                        <option value="通知值班 + 保护录像">通知值班 + 保护录像</option>
                      </Select>
                    </Field>
                    <div className="flex items-center justify-end gap-2 pt-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setCreating(false)}
                      >
                        取消
                      </Button>
                      <Button size="sm" disabled={name.trim() === ""} onClick={createRule}>
                        创建规则
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              <div className="overflow-hidden rounded-lg border border-border">
                <Table>
                  <THead>
                    <TR>
                      <TH className="w-14">启用</TH>
                      <TH>名称</TH>
                      <TH>摄像机范围</TH>
                      <TH className="min-w-[300px]">匹配条件</TH>
                      <TH>命中动作</TH>
                      <TH className="text-right">24h 命中</TH>
                      <TH className="text-right">操作</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {rules.map((r) => (
                      <TR key={r.id}>
                        <TD>
                          <Switch
                            aria-checked={r.enabled}
                            aria-label={`启用 ${r.name}`}
                            onClick={() =>
                              setRules((prev) =>
                                prev.map((x) =>
                                  x.id === r.id ? { ...x, enabled: !x.enabled } : x,
                                ),
                              )
                            }
                          />
                        </TD>
                        <TD className="font-medium">
                          <div className="flex items-center gap-2">
                            {r.name}
                            {!r.enabled && (
                              <Badge variant="muted" className="text-[10px]">
                                未启用
                              </Badge>
                            )}
                          </div>
                        </TD>
                        <TD className="text-xs text-muted-foreground">
                          {r.cameras}
                        </TD>
                        <TD>
                          <ConditionChips raw={r.conditions} />
                        </TD>
                        <TD className="text-xs">{r.actions}</TD>
                        <TD className="text-right">
                          {r.hits24h === 0 ? (
                            <span className="text-xs text-muted-foreground">0</span>
                          ) : (
                            <Badge variant={r.hits24h >= 20 ? "warning" : "secondary"}>
                              {r.hits24h}
                            </Badge>
                          )}
                        </TD>
                        <TD>
                          <RowActions>
                            <Button variant="ghost" size="icon-sm" title="编辑规则">
                              <Pencil className="size-3.5" />
                            </Button>
                          </RowActions>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Segmented
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: "pending", label: "未处理" },
                    { value: "ack", label: "已确认" },
                    { value: "all", label: "全部" },
                  ]}
                />
                <span className="text-xs text-muted-foreground">
                  {visible.length} 条待处理
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={unhandled === 0}
                    onClick={() =>
                      pending
                        .filter((e) => stateOf(e) === "new")
                        .forEach((e) => setEventState(e.id, "acknowledged"))
                    }
                  >
                    全部确认
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={pending.length === 0}
                    onClick={() => pending.forEach((e) => setEventState(e.id, "resolved"))}
                  >
                    清空收件箱
                  </Button>
                </div>
              </div>

              {visible.length === 0 ? (
                <EmptyState
                  icon={<Inbox />}
                  title="收件箱已清空"
                  description="没有待处理的告警。已解决的告警保留在事件与审计日志中，不在此处删除。"
                />
              ) : (
                <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
                  {visible.map((e) => {
                    const s = stateOf(e)
                    const rule = matchedRule(e)
                    return (
                      <div
                        key={e.id}
                        className="flex flex-wrap items-center gap-3 px-3 py-2.5"
                      >
                        <span className="w-16 text-xs tabular-nums text-muted-foreground">
                          {e.time}
                        </span>
                        <Badge variant="secondary">{categoryLabel[e.category]}</Badge>
                        <span className="min-w-32 flex-1 text-sm font-medium">
                          {e.camera}
                        </span>
                        <span className="text-xs tabular-nums text-muted-foreground">
                          置信度 {(e.confidence * 100).toFixed(0)}%
                        </span>
                        <Badge variant="outline">{e.source}</Badge>
                        <span className="w-40 truncate text-xs text-muted-foreground">
                          {rule ? (
                            <>命中规则 · {rule.name}</>
                          ) : (
                            <span className="text-status-degraded">
                              未匹配任何启用规则
                            </span>
                          )}
                        </span>
                        <StatusLabel
                          tone={
                            s === "new"
                              ? "degraded"
                              : s === "acknowledged"
                                ? "unknown"
                                : "online"
                          }
                        >
                          {stateLabel[s]}
                        </StatusLabel>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            title="确认"
                            disabled={s !== "new"}
                            onClick={() => setEventState(e.id, "acknowledged")}
                          >
                            <Check className="size-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            title="标记已解决"
                            disabled={s === "resolved"}
                            onClick={() => setEventState(e.id, "resolved")}
                          >
                            <X className="size-3.5" />
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              <p className="text-xs leading-relaxed text-muted-foreground">
                确认只表示有人看过，不改变匹配结果；解决会写入审计日志。保护录像的动作
                来自规则本身，与此处的确认无关。
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
