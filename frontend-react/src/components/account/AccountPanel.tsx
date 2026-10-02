import { useState } from "react"
import { MonitorSmartphone, ShieldOff, UserRound } from "lucide-react"

import {
  PASSWORD_CHANGE_FAILURE,
  PASSWORD_MIN,
  SESSION_REVOKE_FAILURE,
  describeSessionSource,
  isInteractiveSessionRequired,
  isWrongCurrentPassword,
  passwordsMatch,
  sessionLifetime,
  validatePasswordForm,
  type SessionSummary,
} from "../../api/account"
import type { AuthUser } from "../../api/auth"
import { useSessions } from "../../lib/queries"
import {
  useChangeOwnPassword,
  useRevokeCurrentSession,
  useRevokeSession,
} from "../../lib/accountMutations"
import { formatClock, formatRelative } from "../../lib/format"
import { useAuthStore } from "../../stores/auth"
import { Badge, Button } from "../ui/primitives"
import { Field, PasswordInput } from "../ui/form"
import {
  Callout,
  EmptyState,
  KeyValue,
  PageHeader,
  PrototypeNote,
  RowActions,
  Section,
  StatusDot,
} from "../ui/display"
import { useConfirm } from "../ui/Confirm"
import { cn } from "../../lib/utils"
import { ApiTokensPanel } from "../system/ApiTokensPanel"

/**
 * The signed-in user's own account.
 *
 * The whole page is shaped by what the account contract does **not** have, and
 * the most consequential absence is the easiest one to write by accident:
 *
 * 1. **There is no self-service profile endpoint.** `username` and
 *    `display_name` move only through `PATCH /users/{user_id}`
 *    (`admin_api.py:169-201`), which needs `user.manage` and addresses
 *    somebody else's account. There is no email change, no verification, no
 *    resend — `email_verified` stays `false` for every real user because
 *    nothing outside tests ever sets `email_verified_at`. An "edit profile"
 *    form here would be a form whose every submission is a 403, so the profile
 *    is read-only and says why.
 * 2. **`last_seen_at` is not an activity signal.** It is stamped once at
 *    creation (`auth/service.py:203`) and never updated, so it is always equal
 *    to `created_at`. Labelling it "last active" would tell an operator that a
 *    device in front of them is idle. The row says 登录于 — the only statement
 *    the data supports.
 * 3. **Revoking is one-way, and the current session is a special case.**
 *    `DELETE /sessions/{id}` has no inverse (`auth/service.py:346` only writes
 *    `revoked_at` when it is null), and revoking the session you are on also
 *    clears the cookie (`auth/api.py:456-460`), so the next request 401s and
 *    the app bounces to login. The current row's confirmation names that
 *    before the click, or the navigation reads as a crash.
 * 4. **`POST /auth/password/change` ends every other session**
 *    (`auth/service.py:297-310`) and mints a replacement for this device. The
 *    operator is about to be signed out everywhere else, so that belongs in the
 *    copy next to the button rather than in what they read afterwards.
 *
 * `/api-tokens` is this account's own resource (there is no
 * `/users/{id}/tokens`, so an admin cannot manage anybody else's — G-32), so
 * the token panel is embedded here instead of being duplicated or moved.
 */
export function AccountPanel() {
  return (
    <div className="space-y-6 p-5">
      <PageHeader
        title="个人账号"
        description="自己的资料、密码、登录会话与 API 令牌。"
      />

      <ProfileSection />
      <PasswordSection />
      <SessionsSection />

      {/* Embedded rather than re-implemented: the panel already encodes every
          one-time-plaintext rule, and a second copy would drift. */}
      <div role="region" aria-label="API 令牌">
        <Section
          title="API 令牌"
          description="这些令牌属于你当前的账号。服务端没有「某个用户的令牌列表」这种端点，管理员也无法代你签发或吊销。"
        >
          <ApiTokensPanel />
        </Section>
      </div>

      <PrototypeNote>
        查看会话、结束会话、修改密码这三个接口都要求交互式登录会话
        （`auth/dependencies.py:121-130`）：API 令牌拿到的不是 401，而是 403
        interactive_session_required——泄露的令牌不应该能把它的主人锁在门外。
      </PrototypeNote>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 1. Read-only profile                                                       */
/* -------------------------------------------------------------------------- */

function ProfileSection() {
  const user = useAuthStore((s) => s.user)

  return (
    <div role="region" aria-label="账号资料">
      <Section title="账号资料" description="只读。">
        {user ? (
          <div className="rounded-lg border border-border px-3">
            <KeyValue label="用户名">{user.username}</KeyValue>
            <KeyValue label="显示名">{user.display_name}</KeyValue>
            <KeyValue label="邮箱">{user.email ?? "未设置"}</KeyValue>
            <KeyValue label="角色">
              {user.roles.length > 0 ? user.roles.join("、") : "无"}
            </KeyValue>
            <KeyValue label="权限">{user.permissions.length} 项</KeyValue>
          </div>
        ) : (
          <EmptyState
            icon={<UserRound />}
            title="读不到当前账号"
            description="登录状态已经失效。重新登录后这个页面会恢复。"
          />
        )}

        {/* The reason there is no edit form, stated where a form would be.
            This is the load-bearing text of the section: without it, an
            operator who came here to rename themselves concludes the app is
            broken rather than that the endpoint does not exist. */}
        <Callout tone="degraded" title="这里没有「编辑资料」">
          用户名和显示名只能由管理员在「用户管理」页修改
          （<code>PATCH /users/{'{id}'}</code>
          需要 user.manage 权限，而且改的是别人的账号）。系统没有自助修改资料、
          修改邮箱、验证邮箱或重发验证邮件的接口——所以「保存资料」这样的按钮在这里
          每按一次都只会换来一个 403，不如把这条限制写清楚。
        </Callout>

        {user?.email ? (
          <p className="text-[11px] text-muted-foreground">
            {user.email_verified
              ? "邮箱已验证：这个地址属于你。"
              : "邮箱未验证：系统不会发出验证邮件，也没有重新发送验证的入口——email_verified 只在测试数据里被置为 true。"}
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            这个账号没有邮箱。系统没有「绑定邮箱」的接口，所以它只能一直空着。
          </p>
        )}
      </Section>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 2. Password                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Recovers the typed user from a successful change.
 *
 * `useChangeOwnPassword` pins its data to `unknown` even though the endpoint
 * returns the updated `AuthUser` (`auth/api.py`), so the type has to be
 * re-established here — the store needs it, because the shell header renders
 * `display_name` from it and a stale copy would outlive the change.
 */
function asUpdatedUser(data: unknown): AuthUser | null {
  if (data && typeof data === "object" && "id" in data && "username" in data) {
    return data as AuthUser
  }
  return null
}

/**
 * Why a wrong current password is a field error and not a logout.
 *
 * It is 400 `invalid_current_password` (`auth/api.py`), deliberately not 401:
 * the credentials were accepted, the typed value was wrong. Rendering it as
 * "please sign in again" would sign out an operator whose session is fine, so
 * the message goes on the field and the auth store is never touched.
 */
function passwordFailureMessage(error: unknown): string | null {
  if (!error) return null
  if (isWrongCurrentPassword(error)) {
    return PASSWORD_CHANGE_FAILURE.invalid_current_password
  }
  if (isInteractiveSessionRequired(error)) {
    return PASSWORD_CHANGE_FAILURE.interactive_session_required
  }
  const code = (error as { code?: string } | null)?.code ?? ""
  return (
    PASSWORD_CHANGE_FAILURE[code] ??
    (error instanceof Error ? error.message : String(error))
  )
}

function PasswordSection() {
  const setUser = useAuthStore((s) => s.setUser)
  const change = useChangeOwnPassword((data) => {
    // The old password is never useful again, and leaving it in a form that
    // `attempted` still marks as filled would immediately re-report
    // "请填写当前密码" under a change that just succeeded.
    clearForm()
    setDone(true)
    const updated = asUpdatedUser(data)
    if (updated) setUser(updated)
  })

  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [attempted, setAttempted] = useState(false)
  // A live "请填写当前密码" on an untouched form is noise, so each field's
  // message waits for a blur, a keystroke, or a submit attempt.
  const [touched, setTouched] = useState({
    current: false,
    next: false,
    confirm: false,
  })
  const [done, setDone] = useState(false)

  const form = { currentPassword, newPassword }
  const errors = validatePasswordForm(form)
  const messageFor = (field: "currentPassword" | "newPassword") =>
    errors.find((e) => e.field === field)?.message ?? null

  // Confirmation has no server counterpart: `PasswordChangeRequest` carries
  // only the two passwords (`auth/schemas.py`), so this check can only ever
  // live in the form.
  const confirmMismatch = confirmPassword !== newPassword

  // `passwordsMatch` is a warning, not a block. The server has **no** reuse
  // check (`auth/schemas.py:26-28` is length and nothing else), so refusing to
  // send would be inventing a rule; but silently accepting a "change" that
  // changes nothing is also worth a sentence.
  const sameAsCurrent = passwordsMatch(form)

  // `validatePasswordForm` already treats an empty field as an error, so this
  // list needs no extra "is it filled" clauses of its own.
  const blocked = errors.length > 0 || confirmMismatch

  function clearForm() {
    setCurrentPassword("")
    setNewPassword("")
    setConfirmPassword("")
    setTouched({ current: false, next: false, confirm: false })
    setAttempted(false)
  }

  function submit() {
    setAttempted(true)
    if (blocked) return
    change.reset()
    setDone(false)
    change.mutate({ current_password: currentPassword, new_password: newPassword })
  }

  const wrongCurrent = isWrongCurrentPassword(change.error)
  const otherFailure = change.isError && !wrongCurrent
    ? passwordFailureMessage(change.error)
    : null

  const currentError = wrongCurrent
    ? PASSWORD_CHANGE_FAILURE.invalid_current_password
    : attempted || touched.current
      ? messageFor("currentPassword")
      : null
  const newError =
    attempted || touched.next ? messageFor("newPassword") : null
  const confirmError =
    attempted || touched.confirm
      ? confirmMismatch
        ? "两次输入的新密码不一致"
        : null
      : null

  return (
    <div role="region" aria-label="修改密码">
      <Section
        title="修改密码"
        description="提交后，其它设备上的登录会全部失效；当前设备会换发一个新会话。这条规则无法关闭（auth/service.py:297-310）。"
      >
        <div className="space-y-3 rounded-lg border border-border px-3 py-1">
          <Field
            label="当前密码"
            htmlFor="account-current-password"
            error={currentError}
            hint="填写你正在使用的密码，用来证明这是本人操作。"
          >
            <PasswordInput
              id="account-current-password"
              className="w-64"
              autoComplete="current-password"
              aria-invalid={Boolean(currentError)}
              value={currentPassword}
              onChange={(e) => {
                setCurrentPassword(e.target.value)
                setTouched((t) => ({ ...t, current: true }))
              }}
              onBlur={() => setTouched((t) => ({ ...t, current: true }))}
            />
          </Field>

          <Field
            label="新密码"
            htmlFor="account-new-password"
            error={newError}
            hint={`长度 ${PASSWORD_MIN}–256 个字符。这是服务端唯一的规则：没有大小写或数字要求，也不检查与旧密码是否相同。`}
          >
            <PasswordInput
              id="account-new-password"
              className="w-64"
              autoComplete="new-password"
              aria-invalid={Boolean(newError)}
              value={newPassword}
              onChange={(e) => {
                setNewPassword(e.target.value)
                setTouched((t) => ({ ...t, next: true }))
              }}
              onBlur={() => setTouched((t) => ({ ...t, next: true }))}
            />
          </Field>

          <Field
            label="确认新密码"
            htmlFor="account-confirm-password"
            error={confirmError}
            hint="只比对本表单，不会发给服务端。"
          >
            <PasswordInput
              id="account-confirm-password"
              className="w-64"
              autoComplete="new-password"
              aria-invalid={Boolean(confirmError)}
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value)
                setTouched((t) => ({ ...t, confirm: true }))
              }}
              onBlur={() => setTouched((t) => ({ ...t, confirm: true }))}
            />
          </Field>
        </div>

        {sameAsCurrent && (
          <Callout tone="degraded" title="新密码与当前密码相同">
            服务端并不禁止这样做，这次提交会被接受——但换句话说，其它设备还是会被登出，
            而这里什么也没变。系统里没有旧密码复用检查，所以这句话只能由你来看。
          </Callout>
        )}

        {otherFailure && (
          <Callout tone="offline" title="修改密码失败">
            {otherFailure}
          </Callout>
        )}

        {done && (
          <Callout tone="online" title="密码已修改">
            其它设备上的登录已全部失效，当前设备已换发新会话。如果你在别处被登出，
            那就是这一次操作的直接结果。
          </Callout>
        )}

        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              clearForm()
              setDone(false)
              change.reset()
            }}
          >
            清空
          </Button>
          {/* Deliberately not disabled on `blocked`. A greyed-out button with no
              explanation is the worst of the three options: it neither submits
              nor says why. Clicking a blocked form lists what is missing and
              still sends nothing. */}
          <Button size="sm" disabled={change.isPending} onClick={submit}>
            {change.isPending ? "提交中…" : "修改密码"}
          </Button>
        </div>
      </Section>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 3. Sessions                                                                */
/* -------------------------------------------------------------------------- */

/**
 * The read branch borrows the revoke copy on purpose.
 *
 * `GET /sessions` and `DELETE /sessions/{id}` are behind the same
 * `require_interactive_session` guard, so they answer with the same code and
 * the same advice; keeping one string means the two paths cannot disagree
 * about what an operator should do next.
 */
function sessionReadFailure(error: unknown): string {
  if (isInteractiveSessionRequired(error)) {
    return SESSION_REVOKE_FAILURE.interactive_session_required
  }
  return error instanceof Error ? error.message : String(error)
}

function expiryLabel(days: number): string {
  if (days < 0) return "已过期"
  if (days === 0) return "今天过期"
  return `${days} 天后过期`
}

function SessionsSection() {
  const sessions = useSessions()
  // One clock per render: two `new Date()` calls in the same render can land on
  // opposite sides of a millisecond boundary and label one session twice.
  const now = new Date()
  const list = sessions.data ?? []

  return (
    <div role="region" aria-label="登录会话">
      <Section
        title="登录会话"
        description="一条会话对应一个已登录的设备。结束会话不可撤销——没有恢复接口，所以每一行都要先确认。"
      >
        {sessions.isPending ? (
          <p className="text-xs text-muted-foreground">读取中…</p>
        ) : sessions.isError ? (
          <Callout tone="offline" title="无法读取登录会话">
            {sessionReadFailure(sessions.error)}
          </Callout>
        ) : list.length === 0 ? (
          <EmptyState
            icon={<MonitorSmartphone />}
            title="没有其它登录会话"
            description="每条会话都对应一个已登录的设备；只有这一条，说明没有其它设备在用这个账号。"
          />
        ) : (
          <ul className="space-y-2" aria-label="会话列表">
            {list.map((session) => (
              <SessionRow key={session.id} session={session} now={now} />
            ))}
          </ul>
        )}

        {/* No "sign out all other devices" button on purpose: there is no such
            endpoint, so it would be N sequential DELETEs with a browser tab
            open in between — the first success would be indistinguishable from
            a half-applied batch if one of them failed. */}
        <p className="text-[11px] text-muted-foreground">
          服务端没有「一键退出其它设备」的接口，所以这里没有这个按钮：逐行结束才是可核对的。
        </p>
      </Section>
    </div>
  )
}

function SessionRow({
  session,
  now,
}: {
  session: SessionSummary
  now: Date
}) {
  const confirm = useConfirm()
  const revoke = useRevokeSession()
  // The current session is revoked through its own hook because the response
  // also clears the cookie, so the success is a sign-out rather than a list
  // update.
  const revokeCurrent = useRevokeCurrentSession()
  const busy = revoke.isPending || revokeCurrent.isPending

  const lifetime = sessionLifetime(session, now)
  const expired = lifetime.daysLeft < 0

  async function onRevoke() {
    const ok = session.current
      ? await confirm({
          title: "结束当前会话",
          message:
            "这会结束你现在正在用的这一次登录：成功后本设备的 cookie 立即失效，" +
            "下一次请求就会 401，页面会跳到登录页。这是预期结果，不是崩溃。",
          confirmLabel: "结束并登出",
          danger: true,
        })
      : await confirm({
          title: "结束会话",
          message:
            "确定结束这条登录？该设备会立刻被登出。结束不可撤销——服务端没有恢复会话的接口，" +
            "如果对方没有记住密码，只能重新登录。",
          confirmLabel: "结束会话",
          danger: true,
        })
    if (!ok) return
    if (session.current) revokeCurrent.mutateCurrent(session.id)
    else revoke.mutate(session.id)
  }

  return (
    <li
      data-current={session.current}
      className={cn(
        "rounded-lg border border-border p-3",
        session.current && "border-primary/40",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={expired ? "unknown" : "online"} />
        <span className="text-sm font-medium">
          {describeSessionSource(session)}
        </span>
        {session.current && <Badge variant="success">当前设备</Badge>}
        <Badge
          variant={expired ? "danger" : lifetime.daysLeft <= 3 ? "warning" : "outline"}
        >
          {expiryLabel(lifetime.daysLeft)}
        </Badge>
        <RowActions>
          <Button
            variant="ghost"
            size="icon-sm"
            title="结束会话"
            disabled={busy}
            onClick={onRevoke}
          >
            <ShieldOff className="size-3.5" />
          </Button>
        </RowActions>
      </div>

      {/* `last_seen_at` is deliberately absent. It is stamped once at creation
          and never touched again (`auth/service.py:203`), so it is always
          `created_at`; rendering it as "last active" would report an in-use
          device as idle. 登录于 is the only claim the data supports. */}
      <p className="mt-1 text-[11px] text-muted-foreground">
        登录于 {formatClock(lifetime.signedInSince)}（{formatRelative(lifetime.signedInSince)}）
        {" · "}
        到期于 {formatClock(lifetime.expiresAt)}
      </p>
      <p className="font-mono text-[10px] text-muted-foreground">
        {session.id}
      </p>
    </li>
  )
}
