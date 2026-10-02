import { Fragment, useState } from "react"
import {
  ChevronDown,
  ChevronRight,
  Download,
  FileDiff,
  Lock,
  RefreshCw,
  Search,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react"
import {
  Badge,
  Button,
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
  EmptyState,
  KeyValue,
  Mono,
  PageHeader,
  StatCard,
  StatusDot,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui/display"
import { auditEntries, type AuditEntry } from "../lib/mock"

/* ------------------------------------------------------------------ Model */

type DiffField = {
  field: string
  before: string
  after: string
  /** Value was redacted by the backend; the frontend never sees it. */
  redacted?: boolean
}

const DIFFS: Record<string, DiffField[]> = {
  "export.create": [
    { field: "segment", before: "—", after: "seg-02" },
    { field: "container", before: "—", after: "mp4 · H.265 → H.264 转码" },
    { field: "share_link", before: "—", after: "已生成 · 24 小时有效" },
  ],
  "alert.acknowledge": [
    { field: "event", before: "—", after: "ev-09 · 西南角周界 · 区域入侵 0.79" },
    { field: "event.state", before: "new（未处理）", after: "acknowledged（已确认）" },
  ],
  "recording-policy.update": [
    { field: "cam-04.mode", before: "事件触发", after: "仅事件" },
    { field: "cam-04.window", before: "00:00–24:00", after: "07:00–22:00" },
    { field: "cam-04.retain_days", before: "30", after: "7" },
  ],
  "recording.delete": [
    { field: "segments", before: "7 个片段 / 2.4 GB", after: "未变更（操作被拒绝）" },
    { field: "reason", before: "—", after: "role=浏览者 缺少 recording.delete" },
    {
      field: "principal_camera_scopes",
      before: "后院周界 等 8 路",
      after: "不再参与判定：按机位授权将被移除",
    },
  ],
  "secret-store.rotate": [
    { field: "ref", before: "—", after: "ss://openlist-webdav" },
    {
      field: "value",
      before: "••••••••••••",
      after: "••••••••••••",
      redacted: true,
    },
    { field: "rotated_at", before: "2026-07-14 09:12", after: "2026-10-02 10:44" },
  ],
  "camera.disable": [
    { field: "cam-05.recording", before: "true", after: "false" },
    { field: "cam-05.health", before: "degraded", after: "offline" },
    { field: "note", before: "—", after: "收货月台离线，停止无效探测" },
  ],
  "retention.sweep": [
    { field: "target", before: "—", after: "st-01 · 主录像盘" },
    { field: "planned_delete", before: "—", after: "1,204 个片段" },
    { field: "deleted", before: "—", after: "0（写入阻塞，本轮未清理）" },
  ],
  "token.create": [
    { field: "name", before: "—", after: "旧监控系统对接" },
    { field: "prefix", before: "—", after: "znvr_c04e…" },
    { field: "value", before: "—", after: "••••••••••••", redacted: true },
  ],
}

function diffFor(e: AuditEntry): DiffField[] {
  if (e.action === "auth.login") {
    return e.result === "success"
      ? [
          { field: "username", before: "—", after: e.actor },
          { field: "mfa", before: "—", after: "TOTP 通过 · Safari / macOS" },
          { field: "session", before: "—", after: "已签发 · 有效期 7d" },
        ]
      : [
          { field: "username", before: "—", after: "（未匹配到任何账号）" },
          { field: "mfa", before: "—", after: "未提供" },
          { field: "reason", before: "—", after: `密码不匹配 · 来源 ${e.ip}` },
        ]
  }
  return (
    DIFFS[e.action] ?? [
      { field: "—", before: "—", after: "该动作未返回结构化变更集" },
    ]
  )
}

const RESULT_META: Record<
  AuditEntry["result"],
  { label: string; variant: "success" | "danger"; hint: string }
> = {
  success: { label: "成功", variant: "success", hint: "已生效" },
  failed: { label: "失败", variant: "danger", hint: "尝试了但没做成，通常是系统或存储侧问题" },
  denied: { label: "拒绝", variant: "danger", hint: "权限不足被拦截，数据未发生变化" },
}

const ACTORS = [...new Set(auditEntries.map((e) => e.actor))]
const ACTION_GROUPS = [...new Set(auditEntries.map((e) => e.action.split(".")[0]))]
const RESOURCES = [...new Set(auditEntries.map((e) => e.resource))]

const isToday = (t: string) => !t.includes("昨天")

/* ------------------------------------------------------------------- Page */

export function AuditView() {
  const [actor, setActor] = useState("all")
  const [group, setGroup] = useState("all")
  const [resource, setResource] = useState("all")
  const [result, setResult] = useState("all")
  const [range, setRange] = useState("48h")
  const [q, setQ] = useState("")
  const [open, setOpen] = useState<string | null>(null)

  const rows = auditEntries.filter(
    (e) =>
      (actor === "all" || e.actor === actor) &&
      (group === "all" || e.action.split(".")[0] === group) &&
      (resource === "all" || e.resource === resource) &&
      (result === "all" || e.result === result) &&
      (range === "all" || (range === "today" ? isToday(e.time) : true)) &&
      (q === "" ||
        e.action.includes(q) ||
        e.resource.includes(q) ||
        e.ip.includes(q) ||
        e.actor.includes(q)),
  )

  const todayCount = auditEntries.filter((e) => isToday(e.time)).length
  const failedCount = auditEntries.filter((e) => e.result === "failed").length
  const deniedCount = auditEntries.filter((e) => e.result === "denied").length
  const actorCount = ACTORS.filter((a) => a !== "system" && a !== "unknown").length

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="审计日志"
        description="敏感操作留痕：谁改了机位、谁删了录像、谁读过凭据。日志只增不改，保留 180 天。"
        actions={
          <>
            <Badge variant="warning">
              <TriangleAlert className="size-3" />
              未接入
            </Badge>
            <Button variant="outline" size="sm">
              <RefreshCw /> 刷新
            </Button>
            <Button variant="outline" size="sm">
              <Download /> 导出 CSV
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="今日操作数" value={todayCount} unit="条" icon={<ShieldCheck className="size-4" />} />
        <StatCard
          label="失败操作"
          value={failedCount}
          unit="条"
          tone={failedCount > 0 ? "degraded" : "online"}
          hint="retention.sweep 昨日清理失败"
        />
        <StatCard
          label="拒绝操作"
          value={deniedCount}
          unit="条"
          tone={deniedCount > 0 ? "offline" : "online"}
          hint="wang.guest 尝试删除录像 · 越权尝试"
        />
        <StatCard
          label="涉及用户数"
          value={actorCount}
          unit="人"
          hint="另有 system / unknown 来源 2 条"
        />
      </div>

      <Callout tone="offline" title="凭据访问必须留痕">
        只要触及秘密就要有记录：SecretStore 的读取与轮换、API 令牌的创建与吊销、
        公网分享链接的签发与撤销，全部必须落审计。页面上看不到某次轮换，意味着那把
        凭据是被人直接改掉或从库里删掉的——这正是这一页存在的理由。
      </Callout>

      <Toolbar>
        <Select
          className="w-32"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
        >
          <option value="all">全部操作者</option>
          {ACTORS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </Select>
        <Select
          className="w-32"
          value={group}
          onChange={(e) => setGroup(e.target.value)}
        >
          <option value="all">全部动作</option>
          {ACTION_GROUPS.map((g) => (
            <option key={g} value={g}>
              {g}.*
            </option>
          ))}
        </Select>
        <Select
          className="w-36"
          value={resource}
          onChange={(e) => setResource(e.target.value)}
        >
          <option value="all">全部资源类型</option>
          {RESOURCES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </Select>
        <Select
          className="w-28"
          value={result}
          onChange={(e) => setResult(e.target.value)}
        >
          <option value="all">全部结果</option>
          <option value="success">成功</option>
          <option value="failed">失败</option>
          <option value="denied">拒绝</option>
        </Select>
        <Select
          className="w-32"
          value={range}
          onChange={(e) => setRange(e.target.value)}
        >
          <option value="today">今天</option>
          <option value="48h">最近 48 小时</option>
          <option value="all">全部</option>
        </Select>
        <Input
          className="w-48"
          placeholder="搜索动作 / 资源 / IP"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ToolbarSpacer />
        <span className="text-xs tabular-nums text-muted-foreground">
          {rows.length} / {auditEntries.length} 条
        </span>
      </Toolbar>

      <p className="text-xs text-muted-foreground">
        脱敏在服务端完成：写入前已替换凭据、令牌与口令，接口只返回掩码值，前端不再做
        任何二次处理，也不尝试还原。
      </p>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        {rows.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<Search />}
              title="没有匹配的审计记录"
              description="放宽筛选条件再试一次。审计记录只增不改，缺失的记录无法补写。"
            />
          </div>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="w-8" />
                <TH>时间</TH>
                <TH>操作者</TH>
                <TH>动作</TH>
                <TH>资源</TH>
                <TH>结果</TH>
                <TH>来源 IP</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((e) => {
                const meta = RESULT_META[e.result]
                const expanded = open === e.id
                return (
                  <Fragment key={e.id}>
                    <TR
                      onClick={() => setOpen(expanded ? null : e.id)}
                      className={
                        e.result === "denied"
                          ? "bg-destructive/5 hover:bg-destructive/10"
                          : undefined
                      }
                    >
                      <TD>
                        {expanded ? (
                          <ChevronDown className="size-3.5 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="size-3.5 text-muted-foreground" />
                        )}
                      </TD>
                      <TD className="tabular-nums">{e.time}</TD>
                      <TD className="font-medium">
                        <span className="flex items-center gap-1.5">
                          {e.actor === "system" || e.actor === "unknown" ? (
                            <StatusDot tone="unknown" />
                          ) : null}
                          {e.actor}
                        </span>
                      </TD>
                      <TD>
                        <Mono>{e.action}</Mono>
                      </TD>
                      <TD>
                        <Mono>{e.resource}</Mono>
                      </TD>
                      <TD>
                        {e.result === "denied" ? (
                          <Badge variant="danger">
                            <Lock className="size-3" />
                            拒绝
                          </Badge>
                        ) : (
                          <Badge variant={meta.variant}>{meta.label}</Badge>
                        )}
                      </TD>
                      <TD>
                        <Mono>{e.ip}</Mono>
                      </TD>
                    </TR>
                    {expanded && (
                      <TR className="bg-muted/40 hover:bg-muted/40">
                        <TD colSpan={7} className="p-0 whitespace-normal">
                          <div className="flex flex-col gap-4 p-4 lg:flex-row">
                            <div className="min-w-0 flex-1 space-y-2">
                              <p className="flex items-center gap-1.5 text-xs font-semibold">
                                <FileDiff className="size-3.5 text-muted-foreground" />
                                变更前后
                                <span className="font-normal text-muted-foreground">
                                  （服务端记录的请求参数快照）
                                </span>
                              </p>
                              <div className="overflow-hidden rounded-lg border border-border bg-card">
                                <div className="grid grid-cols-[minmax(0,10rem)_1fr_1fr] gap-px bg-border text-xs">
                                  <div className="bg-muted/60 px-2.5 py-1.5 text-muted-foreground">
                                    字段
                                  </div>
                                  <div className="bg-muted/60 px-2.5 py-1.5 text-muted-foreground">
                                    变更前
                                  </div>
                                  <div className="bg-muted/60 px-2.5 py-1.5 text-muted-foreground">
                                    变更后
                                  </div>
                                  {diffFor(e).map((d) => (
                                    <Fragment key={d.field}>
                                      <div className="bg-card px-2.5 py-1.5 font-mono">
                                        {d.field}
                                      </div>
                                      <div className="bg-card px-2.5 py-1.5 font-mono text-status-offline">
                                        {d.before}
                                      </div>
                                      <div className="flex items-center gap-1.5 bg-card px-2.5 py-1.5 font-mono text-status-online">
                                        {d.redacted && (
                                          <Lock className="size-3 shrink-0" />
                                        )}
                                        {d.after}
                                      </div>
                                    </Fragment>
                                  ))}
                                </div>
                              </div>
                              {diffFor(e).some((d) => d.redacted) && (
                                <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
                                  <Lock className="mt-0.5 size-3 shrink-0" />
                                  带锁字段在服务端即被替换为掩码，轮换与令牌创建因此「只
                                  能证明发生过、看不到内容」——这是刻意的：审计要可证，
                                  但不应成为新的凭据泄漏面。
                                </p>
                              )}
                            </div>

                            <div className="w-full shrink-0 space-y-1 lg:w-72">
                              <p className="text-xs font-semibold">条目信息</p>
                              <KeyValue label="条目 ID">
                                <Mono>{e.id}</Mono>
                              </KeyValue>
                              <KeyValue label="时间">
                                <Mono>{e.time}</Mono>
                              </KeyValue>
                              <KeyValue label="操作者">
                                <Mono>{e.actor}</Mono>
                              </KeyValue>
                              <KeyValue label="来源 IP">
                                <Mono>{e.ip}</Mono>
                              </KeyValue>
                              <KeyValue label="结果">
                                <span
                                  className={
                                    e.result === "success"
                                      ? "text-status-online"
                                      : "text-status-offline"
                                  }
                                >
                                  {meta.label} · {meta.hint}
                                </span>
                              </KeyValue>
                              {e.result === "denied" && (
                                <Callout tone="offline" className="mt-2">
                                  拒绝同样留痕：这是账号在试探自己没有的权限，值得单独排查。
                                  收敛为三角色后，权限判定只看角色、不再按机位逐一路
                                  核对。
                                </Callout>
                              )}
                            </div>
                          </div>
                        </TD>
                      </TR>
                    )}
                  </Fragment>
                )
              })}
            </TBody>
          </Table>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        旧前端从未为这个接口提供入口，页面长期处于不可达状态；后端接口已存在且返回
        脱敏字段，因此本页是按真实返回结构搭建的，而不是占位。
      </p>
    </div>
  )
}
