import { useState } from "react"
import {
  Check,
  KeyRound,
  LogOut,
  Monitor,
  RefreshCw,
  Trash2,
  TriangleAlert,
  UserPlus,
  X,
} from "lucide-react"
import {
  Badge,
  Button,
  Card,
  CardContent,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Switch,
} from "../components/ui/primitives"
import {
  Callout,
  Mono,
  PageHeader,
  RowActions,
  StatCard,
  StatusDot,
  Tabs,
} from "../components/ui/display"
import { TODAY, apiTokens, sessions, users, type User } from "../lib/mock"

type Role = User["role"]
type Grant = "allow" | "partial" | "deny"

const ROLE_META: Record<
  Role,
  { sub: string; blurb: string; tone: "online" | "degraded" | "unknown" }
> = {
  管理员: {
    sub: "系统负责人",
    blurb: "全部权限：设备、计划、规则、导出，以及用户与角色、API 令牌与 SecretStore、系统设置与配置导入导出。",
    tone: "online",
  },
  操作员: {
    sub: "安保值班",
    blurb: "查看 + 全部写操作：机位、录制计划、告警规则、事件确认、录像导出与公网分享链接。不能管理用户与系统配置。",
    tone: "degraded",
  },
  浏览者: {
    sub: "前台 / 访客",
    blurb: "只读：实时画面、录像回放、事件列表。不能导出录像、不能创建分享链接、不能修改任何设置。",
    tone: "unknown",
  },
}

const CAPABILITIES: { cap: string; grants: Record<Role, Grant> }[] = [
  { cap: "实时画面与录像回放", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "allow" } },
  { cap: "事件列表与确认处理", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "allow" } },
  { cap: "导出 / 下载录像", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "deny" } },
  { cap: "创建公网分享链接", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "deny" } },
  { cap: "删除录像片段", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "deny" } },
  { cap: "摄像机增删改与码流绑定", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "deny" } },
  { cap: "录制计划与保留策略", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "deny" } },
  { cap: "告警规则编辑", grants: { 管理员: "allow", 操作员: "allow", 浏览者: "deny" } },
  { cap: "查看审计日志", grants: { 管理员: "allow", 操作员: "partial", 浏览者: "deny" } },
  { cap: "用户与角色管理", grants: { 管理员: "allow", 操作员: "deny", 浏览者: "deny" } },
  { cap: "API 令牌与 SecretStore 密钥", grants: { 管理员: "allow", 操作员: "deny", 浏览者: "deny" } },
  { cap: "系统设置与配置导入导出", grants: { 管理员: "allow", 操作员: "deny", 浏览者: "deny" } },
]

const ROLE_ORDER: Role[] = ["管理员", "操作员", "浏览者"]

const TABS = [
  { key: "users", label: "用户" },
  { key: "roles", label: "角色" },
  { key: "tokens", label: "API 令牌" },
  { key: "sessions", label: "活动会话" },
]

/** Days since a `YYYY-MM-DD` stamp; null for relative stamps like "6 分钟前". */
function idleDays(stamp: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(stamp)) return null
  return Math.round((Date.parse(TODAY) - Date.parse(stamp)) / 86400000)
}

export function UsersView() {
  const [tab, setTab] = useState("users")
  const [enabled, setEnabled] = useState<Record<string, boolean>>({})
  const [live, setLive] = useState(sessions)

  const isEnabled = (u: User) => enabled[u.id] ?? u.status === "active"
  const active = users.filter(isEnabled).length
  const disabled = users.length - active
  const noMfa = users.filter((u) => !u.mfa && isEnabled(u))
  const killed = sessions.length - live.length

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="用户与权限"
        description="三个固定角色，没有自定义权限位：管理员 / 操作员 / 浏览者。令牌、会话与停用状态都在本页处理。"
        actions={
          <>
            <Button variant="outline" size="sm">
              <RefreshCw /> 刷新
            </Button>
            <Button size="sm">
              <UserPlus /> 新建用户
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="用户总数" value={users.length} unit="个" />
        <StatCard
          label="已停用"
          value={disabled}
          unit="个"
          tone={disabled > 0 ? "offline" : "online"}
          hint="停用后无法登录，已签发会话立即失效"
        />
        <StatCard
          label="未启用二次验证"
          value={noMfa.length}
          unit="个"
          tone={noMfa.length > 0 ? "degraded" : "online"}
          hint={`含 ${noMfa.filter((u) => u.role === "操作员").length} 个操作员账号`}
        />
        <StatCard label="活动会话" value={live.length} unit="个" tone="online" />
      </div>

      <Callout tone="degraded" title="权限正在收敛：19 个细粒度权限点 → 3 个固定角色">
        现有的 19 个权限点将并入上述三个角色，同时按机位授权（
        <Mono>principal_camera_scopes</Mono>）将被移除。后果需要说清楚：收敛后不再存在
        「只能看某几路机位」这种账号，操作员登录即看到全部 10 路机位与全部录像。若现场
        需要区域隔离，只能靠网络分段与反向代理，不在本系统内实现。
      </Callout>

      <Card>
        <Tabs
          tabs={TABS.map((t) => ({
            ...t,
            count:
              t.key === "users"
                ? users.length
                : t.key === "roles"
                  ? ROLE_ORDER.length
                  : t.key === "tokens"
                    ? apiTokens.length
                    : live.length,
          }))}
          active={tab}
          onChange={setTab}
          className="px-2"
        />
        <CardContent className="pt-2">
          {tab === "users" && (
            <UsersTab isEnabled={isEnabled} setEnabled={setEnabled} />
          )}
          {tab === "roles" && <RolesTab />}
          {tab === "tokens" && <TokensTab />}
          {tab === "sessions" && (
            <SessionsTab live={live} setLive={setLive} killed={killed} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------- 用户 tab */

function UsersTab({
  isEnabled,
  setEnabled,
}: {
  isEnabled: (u: User) => boolean
  setEnabled: (
    fn: (prev: Record<string, boolean>) => Record<string, boolean>,
  ) => void
}) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        角色在创建时固定，不支持逐项授权。开关即时生效，无需保存；每次变更写入审计日志。
      </p>
      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <THead>
            <TR>
              <TH>用户名</TH>
              <TH>显示名</TH>
              <TH>角色</TH>
              <TH className="w-20">启用</TH>
              <TH>最近登录</TH>
              <TH>二次验证</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {users.map((u) => {
              const on = isEnabled(u)
              return (
                <TR
                  key={u.id}
                  className={on ? undefined : "bg-muted/40 text-muted-foreground"}
                >
                  <TD>
                    <span className="flex items-center gap-2">
                      <Mono>{u.username}</Mono>
                      {!on && (
                        <Badge variant="danger">
                          <X className="size-3" />
                          已停用
                        </Badge>
                      )}
                    </span>
                  </TD>
                  <TD className="font-medium">{u.displayName}</TD>
                  <TD>
                    <Badge
                      variant={
                        u.role === "管理员"
                          ? "default"
                          : u.role === "操作员"
                            ? "warning"
                            : "muted"
                      }
                    >
                      {u.role}
                    </Badge>
                  </TD>
                  <TD>
                    <Switch
                      aria-checked={on}
                      onClick={() => setEnabled((prev) => ({ ...prev, [u.id]: !on }))}
                    />
                  </TD>
                  <TD className="text-xs">
                    <span className="flex items-center gap-1.5">
                      {u.status === "active" && u.lastLogin.includes("前") && (
                        <StatusDot tone="online" />
                      )}
                      {u.lastLogin}
                    </span>
                  </TD>
                  <TD>
                    {u.mfa ? (
                      <Badge variant="success">
                        <Check className="size-3" />
                        已启用
                      </Badge>
                    ) : (
                      <Badge variant="warning">
                        <TriangleAlert className="size-3" />
                        未启用
                      </Badge>
                    )}
                  </TD>
                  <TD>
                    <RowActions>
                      <Button variant="ghost" size="icon-sm" title="重置密码">
                        <KeyRound className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" title="删除">
                        <Trash2 className="size-3.5" />
                      </Button>
                    </RowActions>
                  </TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
      </div>
      <Callout tone="degraded" title="停用不等于删除">
        停用会立即作废该账号所有已签发会话，但账号与历史审计记录保留。施工方临时账号
        （old.contractor）应保持停用状态而非删除，以便追溯它过去的操作。
      </Callout>
    </div>
  )
}

/* -------------------------------------------------------------- 角色 tab */

function RolesTab() {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 lg:grid-cols-3">
        {ROLE_ORDER.map((role) => {
          const meta = ROLE_META[role]
          const count = users.filter((u) => u.role === role).length
          return (
            <div
              key={role}
              className="space-y-2 rounded-lg border border-border bg-card p-3"
            >
              <div className="flex items-center gap-2">
                <StatusDot tone={meta.tone} />
                <span className="text-sm font-semibold">{role}</span>
                <Badge variant="outline">{meta.sub}</Badge>
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                  {count} 人
                </span>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {meta.blurb}
              </p>
            </div>
          )
        })}
      </div>

      <div>
        <h4 className="mb-2 text-sm font-semibold">能力矩阵</h4>
        <div className="overflow-hidden rounded-lg border border-border">
          <Table>
            <THead>
              <TR>
                <TH>能力</TH>
                {ROLE_ORDER.map((r) => (
                  <TH key={r} className="w-28 text-center">
                    {r}
                  </TH>
                ))}
              </TR>
            </THead>
            <TBody>
              {CAPABILITIES.map((row) => (
                <TR key={row.cap}>
                  <TD className="font-medium">{row.cap}</TD>
                  {ROLE_ORDER.map((r) => (
                    <TD key={r} className="text-center">
                      <GrantCell grant={row.grants[r]} />
                    </TD>
                  ))}
                </TR>
              ))}
              <TR className="bg-muted/40">
                <TD className="font-medium">可见机位范围</TD>
                {ROLE_ORDER.map((r) => (
                  <TD key={r} className="text-center">
                    <GrantCell grant="allow" />
                  </TD>
                ))}
              </TR>
            </TBody>
          </Table>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          最后一行是本次收敛最该被看见的一行：三个角色的机位范围完全相同。受保护
          （带锁）的片段对所有有导出权的角色一致可见；浏览者没有导出权，因此拿不到
          保护片段。
        </p>
      </div>
    </div>
  )
}

function GrantCell({ grant }: { grant: Grant }) {
  if (grant === "allow") {
    return (
      <Badge variant="success">
        <Check className="size-3" />
        允许
      </Badge>
    )
  }
  if (grant === "partial") {
    return (
      <Badge variant="warning" title="只能看到与本人相关的记录">
        受限
      </Badge>
    )
  }
  return (
    <Badge variant="muted">
      <X className="size-3" />
      禁止
    </Badge>
  )
}

/* ------------------------------------------------------------ 令牌 tab */

function TokensTab() {
  return (
    <div className="space-y-3">
      <Callout tone="degraded" title="令牌只以掩码显示，明文永不再出现">
        列表里只保留前缀（<Mono>znvr_a7f3…</Mono>
        ），完整值仅在创建那一次响应中返回，之后任何接口都不再提供，也无法找回。
        遗失即视为泄露，请直接吊销重建。
      </Callout>
      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <THead>
            <TR>
              <TH>名称</TH>
              <TH>前缀</TH>
              <TH>创建时间</TH>
              <TH>最近使用</TH>
              <TH>状态</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {apiTokens.map((t) => {
              const idle = idleDays(t.lastUsed)
              const stale = idle !== null && idle > 30
              return (
                <TR key={t.id} className={stale ? "bg-status-degraded/5" : undefined}>
                  <TD className="font-medium">{t.name}</TD>
                  <TD>
                    <Mono>{t.prefix}</Mono>
                  </TD>
                  <TD className="text-muted-foreground">{t.createdAt}</TD>
                  <TD className="text-muted-foreground">{t.lastUsed}</TD>
                  <TD>
                    {stale ? (
                      <Badge variant="warning">
                        <TriangleAlert className="size-3" />
                        长期未使用 {idle} 天
                      </Badge>
                    ) : (
                      <Badge variant="success">
                        <StatusDot tone="online" />
                        活跃
                      </Badge>
                    )}
                  </TD>
                  <TD>
                    <RowActions>
                      <Button variant="outline" size="sm" className="text-destructive">
                        吊销
                      </Button>
                    </RowActions>
                  </TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        长期未使用的令牌是对外暴露面的残留：它仍然有效、仍能通过鉴权调用接口，只是暂时
        没人调。「旧监控系统对接」已 3 个月未被使用，建议吊销而不是留着。吊销与新建
        都会写入审计日志。
      </p>
    </div>
  )
}

/* ------------------------------------------------------------ 会话 tab */

function SessionsTab({
  live,
  setLive,
  killed,
}: {
  live: typeof sessions
  setLive: (fn: (prev: typeof sessions) => typeof sessions) => void
  killed: number
}) {
  return (
    <div className="space-y-3">
      <Callout tone="degraded" title="强制下线只作废会话，不动账号">
        踢下线会立即作废该会话令牌，已登录的设备需重新输入密码。对被入侵的账号，正确做法
        是先停用账号（用户 tab 的开关），再逐个踢下线。
      </Callout>

      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <THead>
            <TR>
              <TH>设备</TH>
              <TH>来源地址</TH>
              <TH>最后活动</TH>
              <TH className="text-right">操作</TH>
            </TR>
          </THead>
          <TBody>
            {live.map((s) => (
              <TR key={s.id} className={s.current ? "bg-status-online/5" : undefined}>
                <TD>
                  <span className="flex items-center gap-2">
                    <Monitor className="size-3.5 text-muted-foreground" />
                    <span className="font-medium">{s.device}</span>
                    {s.current && <Badge variant="success">当前会话</Badge>}
                  </span>
                </TD>
                <TD>
                  <Mono>{s.location}</Mono>
                </TD>
                <TD className="text-muted-foreground">{s.lastSeen}</TD>
                <TD>
                  <div className="flex justify-end">
                    {s.current ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setLive((prev) => prev.filter((x) => x.id !== s.id))
                        }
                      >
                        <LogOut /> 强制下线
                      </Button>
                    )}
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>

      {live.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
          所有会话均已作废
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          本次已强制下线 {killed} 个会话。
        </p>
      )}
    </div>
  )
}
