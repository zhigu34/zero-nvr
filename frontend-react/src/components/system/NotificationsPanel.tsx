import { useState } from "react"
import { Check, KeyRound, Mail, Pencil, Plus, Send, Trash2, X } from "lucide-react"

import {
  NOTIFY_TYPES,
  NOTIFY_TYPE_LABEL,
  applyCredentialsEdit,
  applyUrlEdit,
  deliveryPurposeLabel,
  deliveryStateLabel,
  deliveryStateTone,
  toSecretAction,
  type CredentialsEdit,
  type NotificationConfig,
  type NotificationKind,
  type NotificationTargetView,
  type NotifyType,
  type SecretAction,
  type UrlEdit,
} from "../../api/notifications"
import {
  useNotificationDeliveries,
  useNotificationTargets,
  useSecurityEmailTarget,
} from "../../lib/queries"
import {
  useCreateNotificationTarget,
  useDeleteNotificationTarget,
  useSetSecurityEmailTarget,
  useTestNotificationTarget,
  useUpdateNotificationTarget,
} from "../../lib/notificationMutations"
import { useConfirm } from "../ui/Confirm"
import { formatClock, formatRelative } from "../../lib/format"
import { Badge, Button, Input, Select, Switch } from "../ui/primitives"
import {
  Callout,
  EmptyState,
  Field,
  PrototypeNote,
  RowActions,
  Segmented,
  StatusDot,
} from "../ui/display"
import { cn } from "../../lib/utils"

/**
 * 通知渠道。
 *
 * Three contract facts shape this panel, and each one is a way a naive editor
 * silently does the wrong thing rather than failing:
 *
 * 1. **The URL and the SMTP password are write-only.** The read model carries
 *    `url_configured` / `credentials_configured` and nothing else
 *    (`notifications/schemas.py:63-70`). The editor therefore offers three
 *    explicit choices per secret — keep / replace / clear — because
 *    `NotificationTargetUpdate` cannot express "unchanged" with a `null`
 *    (`api/notifications.ts` has the protocol).
 * 2. **`config` is a two-key whitelist**: `notify_type` (four values) and
 *    `password_reset` (bool). Anything else is a 400
 *    `notification_target_config_invalid` (`service.py:54-58`).
 * 3. **Two unrelated settings both look like "the security email."** The
 *    `password_reset` flag and the security-email-default pointer have
 *    different storage, different uniqueness rules and different type
 *    requirements, so they are presented as two separate controls with their
 *    consequences spelled out.
 *
 * The test send is a real POST with an external side effect and is therefore
 * only ever an explicit click — the same rule the storage capacity read
 * follows (G-1).
 */
export function NotificationsPanel() {
  const targets = useNotificationTargets()
  const securityEmail = useSecurityEmailTarget()
  const deliveries = useNotificationDeliveries({ limit: 20 })
  const setSecurityEmailMutation = useSetSecurityEmailTarget()
  const confirm = useConfirm()

  const [editing, setEditing] = useState<NotificationTargetView | "create" | null>(null)
  const [filter, setFilter] = useState("")

  const list = targets.data ?? []
  const deliveryRows = (deliveries.data ?? []).filter(
    (d) => !filter || d.notification_target_id === filter,
  )

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------ security email */}
      <section className="rounded-lg border border-border">
        <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <KeyRound className="size-4 text-muted-foreground" />
            安全邮件目标
          </h3>
        </div>
        <div className="space-y-2 p-3">
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            密码重置与安全提醒实际由哪个目标发出。这与下面每个目标上的
            「用于密码重置」开关<strong className="text-foreground">是两件不同的事</strong>：
            开关决定目标的 URL 是否以 mailto 形式接收重置邮件，这里指定的是
            真正负责发送的 SMTP 目标。
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              className="w-72"
              value={securityEmail.data?.target_id ?? ""}
              aria-label="安全邮件目标"
              disabled={setSecurityEmailMutation.isPending}
              onChange={async (e) => {
                const value = e.target.value || null
                if (value === (securityEmail.data?.target_id ?? null)) return
                const ok = await confirm({
                  title: "更改安全邮件目标",
                  message: value
                    ? "安全提醒与密码重置邮件将改由所选 SMTP 目标发出。"
                    : "将清空安全邮件目标，此后安全类邮件没有发送渠道。",
                  confirmLabel: "保存",
                })
                if (ok) setSecurityEmailMutation.mutate(value)
              }}
            >
              <option value="">未设置</option>
              {list
                .filter((t) => t.kind === "smtp")
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
            </Select>
            {list.length > 0 && list.every((t) => t.kind !== "smtp") && (
              <span className="text-[11px] text-status-degraded">
                当前没有 SMTP 类型的目标，无法设置。
              </span>
            )}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- targets */}
      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">通知目标</h3>
          <Button size="sm" onClick={() => setEditing("create")}>
            <Plus /> 新建目标
          </Button>
        </div>

        {targets.isPending ? (
          <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
        ) : targets.error ? (
          <div className="mt-2">
            <Callout tone="offline" title="无法读取通知目标">
              {targets.error.message}
            </Callout>
          </div>
        ) : list.length === 0 ? (
          <div className="mt-2">
            <EmptyState
              icon={<Mail />}
              title="还没有通知目标"
              description="没有目标时，告警仍会记录在告警页，但不会有人收到通知。"
            />
          </div>
        ) : (
          <ul className="mt-2 space-y-2" aria-label="通知目标列表">
            {list.map((target) => (
              <TargetRow
                key={target.id}
                target={target}
                isSecurityEmail={securityEmail.data?.target_id === target.id}
                onEdit={() => setEditing(target)}
              />
            ))}
          </ul>
        )}
      </section>

      {editing && (
        <TargetEditor
          target={editing === "create" ? undefined : editing}
          existingNames={list.map((t) => t.name)}
          onClose={() => setEditing(null)}
        />
      )}

      {/* ----------------------------------------------------- deliveries */}
      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">投递记录</h3>
          <Segmented
            value={filter}
            ariaLabel="按目标筛选投递记录"
            onChange={setFilter}
            options={[
              { value: "", label: "全部" },
              ...list.map((t) => ({ value: t.id, label: t.name })),
            ]}
          />
        </div>

        {deliveries.isPending ? (
          <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
        ) : deliveryRows.length === 0 ? (
          <p className="mt-2 rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            暂无投递记录
          </p>
        ) : (
          <ul
            className="mt-2 divide-y divide-border rounded-lg border border-border"
            aria-label="投递记录列表"
          >
            {deliveryRows.map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-3 py-2">
                <StatusDot tone={deliveryStateTone(d.state)} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium">{d.title}</p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {deliveryPurposeLabel(d.purpose)} ·{" "}
                    {list.find((t) => t.id === d.notification_target_id)?.name ??
                      "未知目标"}
                    {d.attempt_count > 1 && ` · 第 ${d.attempt_count} 次尝试`}
                    {d.last_error_code && (
                      <span className="ml-1 font-mono text-status-offline">
                        {d.last_error_code}
                      </span>
                    )}
                  </p>
                </div>
                <span
                  className="shrink-0 text-[10px] text-muted-foreground"
                  title={formatClock(d.updated_at)}
                >
                  {formatRelative(d.updated_at)}
                </span>
                <span className="w-16 shrink-0 text-right text-[10px] text-muted-foreground">
                  {deliveryStateLabel(d.state)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <PrototypeNote>
        Apprise URL 与 SMTP 密码都是只写字段：保存后界面只显示「已配置」，
        不再能读回。更换时请重新输入完整值。
      </PrototypeNote>
    </div>
  )
}

function TargetRow({
  target,
  isSecurityEmail,
  onEdit,
}: {
  target: NotificationTargetView
  isSecurityEmail: boolean
  onEdit: () => void
}) {
  const remove = useDeleteNotificationTarget()
  const test = useTestNotificationTarget(target.id)
  const confirm = useConfirm()
  const [recipient, setRecipient] = useState("")

  return (
    <li className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={target.enabled ? "online" : "unknown"} />
        <span className="text-sm font-medium">{target.name}</span>
        <Badge variant="outline">
          {target.kind === "smtp" ? "SMTP" : "Apprise"}
        </Badge>
        <Badge variant="outline">
          {NOTIFY_TYPE_LABEL[target.config.notify_type as NotifyType] ??
            target.config.notify_type ??
            "信息"}
        </Badge>
        {target.config.password_reset && (
          <Badge variant="warning">用于密码重置</Badge>
        )}
        {isSecurityEmail && <Badge variant="secondary">安全邮件目标</Badge>}
        {!target.enabled && <Badge variant="outline">已停用</Badge>}

        <RowActions>
          <Button
            variant="ghost"
            size="icon-sm"
            title="编辑"
            onClick={onEdit}
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            title="删除"
            onClick={async () => {
              const ok = await confirm({
                title: "撤销目标",
                message: `确定删除「${target.name}」？已有的投递记录会保留，但今后不再使用该目标。`,
                confirmLabel: "删除",
                danger: true,
              })
              if (ok) remove.mutate(target.id)
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </RowActions>
      </div>

      <p className="mt-1 text-[11px] text-muted-foreground">
        {target.url_configured ? "URL 已配置" : "未配置 URL"}
        {target.credentials_configured && " · 凭据已配置"}
        {!target.url_configured && (
          <span className="ml-1.5 text-status-degraded">
            该目标无法接收任何通知
          </span>
        )}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Input
          className="w-56"
          placeholder="收件人（留空用目标自身设置）"
          value={recipient}
          aria-label="测试收件人"
          onChange={(e) => setRecipient(e.target.value)}
        />
        <Button
          variant="outline"
          size="sm"
          disabled={test.isPending || !target.url_configured}
          onClick={() =>
            test.mutate(recipient.trim() ? { recipient: recipient.trim() } : undefined)
          }
        >
          <Send /> {test.isPending ? "发送中…" : "发送测试"}
        </Button>
      </div>
    </li>
  )
}

function TargetEditor({
  target,
  existingNames,
  onClose,
}: {
  target?: NotificationTargetView
  existingNames: string[]
  onClose: () => void
}) {
  const creating = !target
  const [name, setName] = useState(target?.name ?? "")
  const [kind, setKind] = useState<NotificationKind>(target?.kind ?? "apprise")
  const [enabled, setEnabled] = useState(target?.enabled ?? true)
  const [notifyType, setNotifyType] = useState<NotifyType>(
    (target?.config?.notify_type as NotifyType) ?? "info",
  )
  const [passwordReset, setPasswordReset] = useState(
    target?.config?.password_reset === true,
  )

  // Secret state records the **verb only**; the value lives in its own state
  // and is read at submit time.
  //
  // The URL is the exception on create, where there is no stored value to keep
  // and a target without a URL can never deliver anything. Starting there would
  // let the operator build a target that looks configured and is dead.
  const [urlEdit, setUrlEdit] = useState<UrlEdit>(
    creating ? { action: "replace", value: "" } : { action: "keep" },
  )
  const [urlValue, setUrlValue] = useState("")
  const [credEdit, setCredEdit] = useState<CredentialsEdit>({ action: "keep" })
  const [smtpUser, setSmtpUser] = useState("")
  const [smtpPass, setSmtpPass] = useState("")

  const create = useCreateNotificationTarget()
  const update = useUpdateNotificationTarget(target?.id ?? "")

  const nameError =
    name.trim() === ""
      ? "请填写名称"
      : creating && existingNames.includes(name.trim())
        ? "名称已存在"
        : null

  // The backend validates the URL shape, but only when the flag is set
  // (`service.py:119-134`); checking here names the rule instead of returning
  // a 400 about a field the operator may not have thought of as related.
  //
  // The other two guards have no server counterpart at all: an empty replace
  // and a clear are both destructive, both are unrecoverable because the value
  // cannot be read back, and both succeed silently.
  const urlError =
    urlEdit.action === "clear"
      ? passwordReset
        ? "该目标承担密码重置，清空 URL 会让它永远收不到重置邮件。"
        : null
      : urlEdit.action === "replace"
        ? urlValue.trim() === ""
          ? "请填写新的 URL"
          : passwordReset && !/^mailto(s)?:\/\/[^/?#]+(\/)?$/i.test(urlValue.trim())
            ? "用于密码重置时，URL 必须是 mailto: 或 mailtos: 形式，且不能带收件人路径"
            : null
        : null

  const credError =
    kind === "smtp" && credEdit.action === "replace"
      ? smtpUser.trim() === ""
        ? "SMTP 凭据需要用户名"
        : smtpPass === ""
          ? "请填写新密码——替换空密码会清掉已存的密码且无法恢复"
          : null
      : null

  const config: NotificationConfig = {
    notify_type: notifyType,
    password_reset: passwordReset,
  }
  const configChanged =
    creating ||
    notifyType !== (target?.config?.notify_type ?? "info") ||
    passwordReset !== (target?.config?.password_reset === true)

  const blocked = Boolean(nameError || urlError || credError)

  function submit() {
    if (blocked) return
    if (creating) {
      const body: Parameters<typeof create.mutate>[0] = {
        name: name.trim(),
        kind,
        enabled,
        config,
      }
      if (urlEdit.action === "replace") body.url = urlValue.trim()
      else if (urlEdit.action === "clear") body.url = null
      if (kind === "smtp") {
        if (credEdit.action === "replace") {
          body.smtp_credentials = {
            username: smtpUser.trim(),
            password: smtpPass,
          }
        } else if (credEdit.action === "clear") {
          body.smtp_credentials = null
        }
      }
      create.mutate(body, { onSuccess: onClose })
      return
    }

    const body: Parameters<typeof update.mutate>[0] = {}
    if (name.trim() !== target!.name) body.name = name.trim()
    if (enabled !== target!.enabled) body.enabled = enabled
    if (configChanged) body.config = config
    if (urlEdit.action === "replace") {
      Object.assign(body, applyUrlEdit({ action: "replace", value: urlValue.trim() }))
    } else if (urlEdit.action === "clear") {
      Object.assign(body, applyUrlEdit({ action: "clear" }))
    }
    if (kind === "smtp" && credEdit.action === "replace") {
      Object.assign(
        body,
        applyCredentialsEdit({
          action: "replace",
          value: { username: smtpUser.trim(), password: smtpPass },
        }),
      )
    } else if (kind === "smtp" && credEdit.action === "clear") {
      Object.assign(body, applyCredentialsEdit({ action: "clear" }))
    }
    update.mutate(body, { onSuccess: onClose })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/40 p-4 pt-16">
      <div className="w-full max-w-lg rounded-lg border border-border bg-background p-4 shadow-lg">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            {creating ? "新建通知目标" : `编辑：${target!.name}`}
          </h3>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭">
            <X className="size-3.5" />
          </Button>
        </div>

        <div className="mt-2">
          <Field label="名称">
            <Input
              value={name}
              aria-label="目标名称"
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          {nameError && (
            <p className="pb-1 text-[11px] text-status-offline">{nameError}</p>
          )}

          <Field
            label="类型"
            hint="类型创建后不可更改——更换类型等于换一条完全不同的投递路径。"
          >
            <Select
              className="w-32"
              value={kind}
              aria-label="目标类型"
              disabled={!creating}
              onChange={(e) => setKind(e.target.value as NotificationKind)}
            >
              <option value="apprise">Apprise</option>
              <option value="smtp">SMTP</option>
            </Select>
          </Field>

          <Field label="启用">
            <Switch
              role="switch"
              aria-checked={enabled}
              aria-label="启用该目标"
              onClick={() => setEnabled((v) => !v)}
            />
          </Field>

          <Field
            label="通知类型"
            hint="按 Apprise 的 tag 过滤该目标接收哪些消息。"
          >
            <Select
              className="w-32"
              value={notifyType}
              aria-label="通知类型"
              onChange={(e) => setNotifyType(e.target.value as NotifyType)}
            >
              {NOTIFY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {NOTIFY_TYPE_LABEL[t]}
                </option>
              ))}
            </Select>
          </Field>

          <Field
            label="用于密码重置"
            hint="全局只能有一个目标开启。开启后其 URL 必须是 mailto:/mailtos: 形式。"
          >
            <Switch
              role="switch"
              aria-checked={passwordReset}
              aria-label="用于密码重置"
              onClick={() => setPasswordReset((v) => !v)}
            />
          </Field>

          <SecretField
            label={kind === "smtp" ? "服务器 URL" : "Apprise URL"}
            configured={target?.url_configured}
            action={urlEdit.action}
            onAction={(next) =>
              setUrlEdit(
                next === "replace" ? { action: "replace", value: urlValue } : { action: next },
              )
            }
            value={urlValue}
            onValue={setUrlValue}
            error={urlError}
          />

          {kind === "smtp" && (
            <SecretField
              label="SMTP 凭据"
              configured={target?.credentials_configured}
              action={credEdit.action}
              onAction={(next) =>
                setCredEdit(
                  next === "replace"
                    ? { action: "replace", value: { username: smtpUser, password: smtpPass } }
                    : { action: next },
                )
              }
              value={smtpUser}
              onValue={setSmtpUser}
              password={smtpPass}
              onPassword={setSmtpPass}
              error={credError}
            />
          )}
        </div>

        <div className="mt-4 flex justify-end gap-2">
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
    </div>
  )
}

/**
 * One write-only secret, with the three states the update schema can express.
 *
 * "保持不变" is the default when editing and the operator needs to say so
 * explicitly: the stored value cannot be read, so the editor has no way to
 * pre-fill it, and an operator who does not type anything must not silently
 * replace or clear it.
 *
 * The parent owns the value and builds the `replace` state, because only it
 * knows whether this secret is a bare string or a username/password pair —
 * keeping the two shapes in one prop type would force a cast exactly where a
 * wrong shape would silently drop half a credential.
 */
function SecretField({
  label,
  configured,
  action,
  onAction,
  value,
  onValue,
  password,
  onPassword,
  error,
}: {
  label: string
  configured?: boolean
  action: SecretAction
  onAction: (next: SecretAction) => void
  value: string
  onValue: (next: string) => void
  password?: string
  onPassword?: (next: string) => void
  error?: string | null
}) {
  const isCredential = password !== undefined
  return (
    // The whole field is the group, not just the button row: the label, the
    // current state and the inputs all belong to one control, and two of them
    // carry the same three option labels.
    <div
      role="group"
      aria-label={label}
      className="border-b border-border py-3 last:border-0"
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-[11px] text-muted-foreground">
          {action === "clear"
            ? "将清空"
            : action === "replace"
              ? "将替换"
              : configured
                ? "已配置"
                : "未配置"}
        </span>
      </div>

      <Segmented
        className="mt-1.5"
        value={action}
        onChange={(v) => onAction(toSecretAction(v))}
        options={[
          { value: "keep", label: "保持不变" },
          { value: "replace", label: "替换" },
          { value: "clear", label: "清空" },
        ]}
      />

      {action === "replace" && (
        <div className="mt-2 space-y-1.5">
          {isCredential && (
            <Input
              value={value}
              aria-label="用户名"
              placeholder="用户名"
              onChange={(e) => onValue(e.target.value)}
            />
          )}
          <Input
            type={isCredential ? "password" : "text"}
            value={isCredential ? password : value}
            aria-label={isCredential ? "新密码" : "新的 URL"}
            placeholder={isCredential ? "密码" : "如 mailto://user:pass@host"}
            onChange={(e) =>
              isCredential ? onPassword?.(e.target.value) : onValue(e.target.value)
            }
          />
          <p className="text-[10px] text-muted-foreground">
            <Check className="mr-1 inline size-3" />
            只写字段，保存后无法读回，也无法撤销。
          </p>
        </div>
      )}

      {error && <p className="mt-1.5 text-[11px] text-status-offline">{error}</p>}
    </div>
  )
}
