import { useState } from "react"
import { Copy, KeyRound, ShieldOff, Trash2 } from "lucide-react"

import {
  API_TOKEN_PREFIX,
  API_TOKEN_STATUS_LABEL,
  apiTokenStatus,
  describeTokenUsage,
  validateApiTokenForm,
  type ApiTokenCreated,
  type ApiTokenForm,
  type ApiTokenView,
} from "../../api/apiTokens"
import { useApiTokens } from "../../lib/queries"
import {
  apiTokenCreateBody,
  useCreateApiToken,
  useRevokeApiToken,
} from "../../lib/tokenMutations"
import { formatClock } from "../../lib/format"
import { useMyPermissions } from "../../stores/auth"
import { Badge, Button, Input } from "../ui/primitives"
import {
  Callout,
  Checkbox,
  EmptyState,
  Field,
  PrototypeNote,
  RowActions,
  Section,
  Segmented,
  StatusDot,
} from "../ui/display"
import { useConfirm } from "../ui/Confirm"
import { cn } from "../../lib/utils"

/**
 * 个人 API 令牌。
 *
 * 三个契约事实决定了这个面板的形状，而其中每一个都是「朴素写法不会报错、
 * 只会悄悄做错事」的那一类：
 *
 * 1. **明文只在一个响应里存在。** 服务端只存 `sha256(plaintext)`
 *    （`api_tokens.py:38-40`），而所有后续读取返回的
 *    `PersonalApiTokenView` 根本没有 token 字段（`api_tokens.py:153-172`）。
 *    所以明文只在创建成功后显示一次：不写进查询缓存（否则刷新一次就在列表
 *    旁边重新「存在」一次），不写进 toast（toast 会比令牌活得更久），
 *    关掉就没有了。
 * 2. **`permissions: null` 是「同我当前权限」，`[]` 是「什么都做不了」。**
 *    服务端按 `body.permissions is not None` 分流（`api.py:514-518`），
 *    两者的区别只体现在 JSON 里有没有这个键——朴素表单里 `[] ?? null` 一行
 *    就能把它写反，而且写反之后令牌能创建成功、只是永远不能用。
 * 3. **`expires_at` 必须带时区且是将来的时间**
 *    （`api_tokens.py:138-151`）。`<input type="datetime-local">` 的值天然
 *    没有偏移量，直接发出去就是 400，所以它必须经 `localExpiryToIso`
 *    转换，而「永不过期」是发一个根本不存在的键。
 *
 * 另外两条与表单无关但会咬人的事实：吊销没有撤销接口（`api_tokens.py:195-197`
 * 只在 `revoked_at` 为空时写入），所以它不可逆，要先确认；而三个接口都要求
 * 交互式会话，API 令牌无法再签发令牌——这是运维真的会遇到的限制。
 */
/**
 * The signed-out fallback must be a constant, not an inline `[]`.
 *
 * `useSyncExternalStore` compares snapshots with `Object.is`, so a selector that
 * builds a new array on every call never reports "unchanged" and re-renders
 * until React gives up. A module-level empty array keeps the identity stable,
 * and the picker only ever reads it.
 */
export function ApiTokensPanel() {
  const tokens = useApiTokens()
  const myPermissions = useMyPermissions()
  const create = useCreateApiToken()

  const [name, setName] = useState("")
  const [expiryMode, setExpiryMode] = useState<"never" | "at">("never")
  const [expiryDraft, setExpiryDraft] = useState("")
  const [scopeMode, setScopeMode] = useState<"inherit" | "custom">("inherit")
  const [picked, setPicked] = useState<string[]>([])
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)

  // One clock per render: two `new Date()` calls in the same render can land on
  // opposite sides of a millisecond boundary and label one token twice.
  const now = new Date()

  const form: ApiTokenForm = {
    name,
    permissions: scopeMode === "inherit" ? null : picked,
    expiresAt: expiryMode === "at" ? (expiryDraft.trim() || null) : null,
  }
  const errors = validateApiTokenForm(form)

  // The one guard the contract validator cannot cover. `ApiTokenForm` expresses
  // "no expiry" and "an expiry the operator has not typed yet" with the same
  // `null`, so choosing 指定到期时间 and leaving the input blank would send no
  // `expires_at` at all and quietly mint a token that never expires. The
  // distinction only exists in the form, so it is guarded here.
  const expiryMissing = expiryMode === "at" && expiryDraft.trim() === ""

  const blocked = errors.length > 0 || expiryMissing
  const messageFor = (field: keyof ApiTokenForm) =>
    errors.find((e) => e.field === field)?.message ?? null

  const list = tokens.data ?? []

  function reset() {
    setName("")
    setExpiryMode("never")
    setExpiryDraft("")
    setScopeMode("inherit")
    setPicked([])
  }

  function submit() {
    if (blocked) return
    create.mutate(apiTokenCreateBody(form), {
      // `useCreateApiToken` pins its data to `unknown` even though the endpoint
      // The plaintext exists only in this response, so the one-time reveal is
      // built from the mutation result and never from the list.
      onSuccess: (data) => {
        setCreated(data)
        reset()
      },
    })
  }

  return (
    <div className="space-y-5">
      {created && <TokenReveal created={created} onDismiss={() => setCreated(null)} />}

      {/* ------------------------------------------------------------ form */}
      <Section
        title="创建令牌"
        description="令牌以你的身份访问系统，可以随时吊销——但吊销没有撤销接口，吊销即终点。"
      >
        <div className="rounded-lg border border-border px-3">
          <Field label="令牌名称" hint="用来区分这条令牌的用途，例如「Grafana 告警」。">
            <Input
              className="w-64"
              value={name}
              aria-label="令牌名称"
              placeholder="例如 grafana"
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          {messageFor("name") && (
            <p className="py-1.5 text-[11px] text-status-offline">{messageFor("name")}</p>
          )}

          <Field
            label="有效期"
            hint="「永不过期」是合法选项，但它只能靠吊销收回；选了「指定到期时间」就一定要填时间。"
          >
            <Segmented
              ariaLabel="有效期"
              value={expiryMode}
              onChange={(v) => setExpiryMode(v as "never" | "at")}
              options={[
                { value: "never", label: "永不过期" },
                { value: "at", label: "指定到期时间" },
              ]}
            />
          </Field>
          {expiryMode === "at" && (
            <div className="py-2">
              <Input
                type="datetime-local"
                className="w-64"
                value={expiryDraft}
                aria-label="到期时间"
                onChange={(e) => setExpiryDraft(e.target.value)}
              />
              {/* The offset is added on the way out (`localExpiryToIso`), not
                  here: the value above is a wall clock, and the schema rejects a
                  naive datetime outright. */}
              <p className="mt-1 text-[10px] text-muted-foreground">
                按你当前时区填写，提交时会带上时区偏移量。
              </p>
            </div>
          )}
          {(expiryMissing || messageFor("expiresAt")) && (
            <p className="py-1.5 text-[11px] text-status-offline">
              {expiryMissing ? "请选择到期时间，或改回「永不过期」。" : messageFor("expiresAt")}
            </p>
          )}

          <Field
            label="权限范围"
            hint="服务端会以 403 api_token_scope_invalid 拒绝超过你自身权限的选择，所以下面只列出你已有的权限。"
          >
            <Segmented
              ariaLabel="权限范围"
              value={scopeMode}
              onChange={(v) => setScopeMode(v as "inherit" | "custom")}
              options={[
                { value: "inherit", label: "同我当前权限" },
                { value: "custom", label: "手动选择" },
              ]}
            />
          </Field>
          {scopeMode === "custom" && (
            <PermissionPicker
              available={myPermissions}
              picked={picked}
              onChange={setPicked}
            />
          )}
          {messageFor("permissions") && (
            <p className="py-1.5 text-[11px] text-status-offline">
              {messageFor("permissions")}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={reset}>
            清空
          </Button>
          <Button size="sm" disabled={blocked || create.isPending} onClick={submit}>
            {create.isPending ? "创建中…" : "创建令牌"}
          </Button>
        </div>
      </Section>

      {/* ------------------------------------------------------------ list */}
      <Section title="令牌列表" description="已吊销与已过期的令牌会保留在列表里——这份记录说明曾经存在过什么。">
        {tokens.isPending ? (
          <p className="text-xs text-muted-foreground">读取中…</p>
        ) : tokens.error ? (
          <Callout tone="offline" title="无法读取令牌列表">
            {tokens.error.message}
          </Callout>
        ) : list.length === 0 ? (
          <EmptyState
            icon={<KeyRound />}
            title="还没有 API 令牌"
            description="没有令牌时，外部系统只能靠登录会话访问接口。"
          />
        ) : (
          <ul className="space-y-2" aria-label="令牌列表">
            {list.map((token) => (
              <TokenRow key={token.id} token={token} now={now} />
            ))}
          </ul>
        )}
      </Section>

      <PrototypeNote>
        创建、列出与吊销令牌都要求登录后的交互式会话：API 令牌无法再签发新的
        令牌，也无法吊销别人的令牌。发现泄露时只能回到这个页面处理。
      </PrototypeNote>
    </div>
  )
}

/**
 * The one-time reveal.
 *
 * It is deliberately not a toast: a success toast outlives the thing it
 * announces, and this panel would then keep handing out a copy of a secret the
 * server can no longer produce. Nothing re-opens it — the button that dismisses
 * it is the only control, and there is no "show again" anywhere.
 */
function TokenReveal({
  created,
  onDismiss,
}: {
  created: ApiTokenCreated
  onDismiss: () => void
}) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    const clipboard = navigator.clipboard
    if (!clipboard) return
    try {
      await clipboard.writeText(created.token)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Callout tone="degraded" title="令牌已创建——这是唯一一次能看到明文">
      <div className="space-y-2">
        <p>
          服务端只保存这串明文的 sha256。关闭之后无法再次查看、无法找回，
          下面的列表里也不会有它——如果现在没复制，唯一的补救是吊销并重建。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <code className="select-all break-all rounded bg-muted px-2 py-1 font-mono text-xs">
            {created.token}
          </code>
          <Button size="sm" onClick={copy}>
            <Copy /> {copied ? "已复制" : "复制令牌"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onDismiss}>
            我已保存，关闭
          </Button>
        </div>
        <p className="text-[10px]">
          令牌以 {API_TOKEN_PREFIX} 开头。交给外部系统（CI、监控系统）前请先存入密钥库。
        </p>
      </div>
    </Callout>
  )
}

/**
 * The scope picker, narrowed to what the signed-in user already holds.
 *
 * The ceiling is the server's to enforce (`api_tokens.py:128-136`) — this only
 * avoids offering a choice that is guaranteed to 403. "同我当前权限" is a
 * separate control rather than a pre-ticked box, because inheriting is
 * expressed by the *absence* of the `permissions` key, and a checkbox has no
 * way to say "send nothing at all".
 */
function PermissionPicker({
  available,
  picked,
  onChange,
}: {
  available: readonly string[]
  picked: string[]
  onChange: (next: string[]) => void
}) {
  if (available.length === 0) {
    return (
      <p className="py-2 text-[11px] text-muted-foreground">
        当前账号没有可细分的权限项，只能用「同我当前权限」。
      </p>
    )
  }
  return (
    <div
      role="group"
      aria-label="可选权限"
      className="flex flex-wrap gap-x-4 gap-y-1.5 py-2"
    >
      {/* Associated by id rather than by wrapping: a checkbox nested inside its
          own label toggles once in a browser and is a coin flip in a test
          environment, which is not a risk worth taking over a list of scopes. */}
      {available.map((permission) => (
        <span key={permission} className="flex items-center gap-1.5 text-xs">
          <Checkbox
            id={`token-perm-${permission}`}
            checked={picked.includes(permission)}
            aria-label={permission}
            onChange={() =>
              onChange(
                picked.includes(permission)
                  ? picked.filter((p) => p !== permission)
                  : [...picked, permission],
              )
            }
          />
          <label htmlFor={`token-perm-${permission}`} className="font-mono">
            {permission}
          </label>
        </span>
      ))}
    </div>
  )
}

/**
 * One row of the record.
 *
 * There is no token column, and that is not an omission: `ApiTokenView` has no
 * token field at all, so any masked prefix here would be a value this screen
 * cannot obtain. `permissions` is always the server's resolved set — inherit is
 * expanded before it reaches this view — so the row never says "同我当前权限",
 * it says what the token can actually do.
 */
function TokenRow({ token, now }: { token: ApiTokenView; now: Date }) {
  const status = apiTokenStatus(token, now)
  const revoke = useRevokeApiToken()
  const confirm = useConfirm()
  const dead = status !== "active"

  return (
    <li
      data-status={status}
      className={cn(
        "rounded-lg border border-border p-3",
        dead && "border-dashed opacity-70",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={dead ? "unknown" : "online"} />
        <span className="text-sm font-medium">{token.name}</span>
        <Badge
          variant={
            status === "active" ? "success" : status === "expired" ? "warning" : "danger"
          }
        >
          {API_TOKEN_STATUS_LABEL[status]}
        </Badge>
        {token.permissions.length === 0 && (
          <Badge variant="outline">无任何权限</Badge>
        )}

        {/* Only a live token can be revoked. A "更多操作" affordance on a dead
            row would offer an action that can only ever be a no-op. */}
        {status === "active" && (
          <RowActions>
            <Button
              variant="ghost"
              size="icon-sm"
              title="吊销"
              disabled={revoke.isPending}
              onClick={async () => {
                const ok = await confirm({
                  title: "吊销令牌",
                  message: `确定吊销「${token.name}」？吊销不可撤销，令牌会保留在列表里但立即失效。`,
                  confirmLabel: "吊销",
                  danger: true,
                })
                if (ok) revoke.mutate(token.id)
              }}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </RowActions>
        )}
      </div>

      <p className="mt-1 text-[11px] text-muted-foreground">
        {describePermissions(token)} · 创建于 {formatClock(token.created_at)} ·{" "}
        {token.expires_at ? `到期于 ${formatClock(token.expires_at)}` : "永不过期"}
      </p>
      <p className="text-[11px] text-muted-foreground">
        {/* `last_used_at` is only written on a successful authentication, so
            `null` is the normal state right after minting — never an empty
            timestamp. */}
        使用情况：{describeTokenUsage(token)}
        {token.last_used_at && ` · ${formatClock(token.last_used_at)}`}
      </p>
      {token.revoked_at && (
        <p className="text-[11px] text-status-offline">
          <ShieldOff className="mr-1 inline size-3" />
          吊销于 {formatClock(token.revoked_at)}
        </p>
      )}
    </li>
  )
}

/** Short enough to read at a glance, complete enough not to mislead. */
function describePermissions(token: ApiTokenView): string {
  if (token.permissions.length === 0) return "权限：空（该令牌无法完成任何操作）"
  if (token.permissions.length <= 3) return `权限：${token.permissions.join("、")}`
  return `权限：${token.permissions.slice(0, 3).join("、")} 等 ${token.permissions.length} 项`
}
