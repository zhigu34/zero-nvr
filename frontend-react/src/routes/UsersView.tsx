import { useEffect, useMemo, useState } from "react"
import { Check, Copy, KeyRound, Lock, Plus, Shield, UserX, X } from "lucide-react"

import {
  CAMERA_SCOPE_HINT,
  CAMERA_SCOPE_LABEL,
  hasErrors,
  validateUser,
  type CameraScopeMode,
  type UserAdminView,
  type UserPasswordResetIssue,
} from "../api/users"
import {
  useCameraGroups,
  useRoles,
  useUserCameraScope,
  useUsers,
  useCameras,
} from "../lib/queries"
import {
  useCreateUser,
  useIssueUserPasswordReset,
  useSetUserCameraScope,
  useSetUserEnabled,
  useUpdateUser,
} from "../lib/userMutations"
import { useAuthStore } from "../stores/auth"
import { formatClock } from "../lib/format"
import { Badge, Button, Input, Select } from "../components/ui/primitives"
import {
  Checkbox,
  EmptyState,
  Field,
  PageHeader,
  PrototypeNote,
  RowActions,
  Segmented,
  StatusDot,
} from "../components/ui/display"

/**
 * 用户与权限。
 *
 * The prototype had one screen with three stacked tables (users / API tokens /
 * sessions) and a permission matrix. The contract is more specific and less
 * uniform than that, and the differences are the design:
 *
 * - **A username is immutable** (`UserUpdate` has no such field), so the edit
 *   form shows it as read-only text rather than as a disabled input that
 *   invites the question "why can't I change this".
 * - **Enable/disable is an endpoint, not a field.** The toggle calls
 *   `POST /users/{id}/disable`. A `PATCH` with `enabled` would return 200 and
 *   change nothing.
 * - **Camera scope is its own resource** with a four-state mode, so it gets
 *   its own panel and its own save. One "Save" covering both would leave the
 *   operator unable to tell which half landed.
 * - **Password reset returns a token, once.** It is shown in full and says so.
 *
 * API tokens and sessions have endpoints under `/api-tokens` and `/sessions`,
 * but they belong to the signed-in user's own account rather than to another
 * person's, and the admin page has no path to them. They are therefore not
 * reproduced here; see the note at the bottom of the screen.
 */

type Panel = "none" | "create" | UserAdminView

export function UsersView() {
  const users = useUsers()
  const roles = useRoles()
  const create = useCreateUser()
  const setEnabled = useSetUserEnabled()
  const issueReset = useIssueUserPasswordReset()
  const [panel, setPanel] = useState<Panel>("none")
  const [issued, setIssued] = useState<Record<string, UserPasswordResetIssue>>({})
  const me = useAuthStore((s) => s.user)

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <PageHeader
          title="用户与权限"
          description="账号、角色与可见机位范围。用户名创建后不可更改；启停是独立操作，不是列表里的一个字段。"
          actions={
            <Button size="sm" onClick={() => setPanel("create")}>
              <Plus /> 新建用户
            </Button>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1">
        <section className="min-w-0 flex-1 overflow-auto">
          {users.isPending ? (
            <div className="p-4 text-xs text-muted-foreground">读取中…</div>
          ) : users.error ? (
            <div className="p-4">
              <EmptyState
                icon={<UserX />}
                title="无法读取用户列表"
                description={users.error.message}
              />
            </div>
          ) : !users.data || users.data.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={<UserX />}
                title="还没有用户"
                description="系统至少需要一个管理员账号才能登录。"
              />
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {users.data.map((user) => {
                const self = user.id === me?.id
                return (
                  <li key={user.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <StatusDot tone={user.enabled ? "online" : "offline"} />
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-2 text-sm font-medium">
                          {user.display_name}
                          <span className="font-mono text-xs text-muted-foreground">
                            {user.username}
                          </span>
                          {self && <Badge variant="outline">当前登录</Badge>}
                          {!user.enabled && <Badge variant="warning">已禁用</Badge>}
                          {!user.email_verified && user.email && (
                            <Badge variant="outline">邮箱未验证</Badge>
                          )}
                        </p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                          {user.email ?? "无邮箱"}
                          {user.roles.map((role) => (
                            <span
                              key={role.id}
                              className="rounded bg-muted px-1.5 py-0.5 text-[10px]"
                            >
                              {role.name}
                            </span>
                          ))}
                        </p>
                      </div>

                      <RowActions>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="编辑资料与角色"
                          onClick={() => setPanel(user)}
                        >
                          <Shield className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="签发密码重置令牌"
                          onClick={() =>
                            issueReset.mutate(user.id, {
                              onSuccess: (result) =>
                                setIssued((prev) => ({ ...prev, [user.id]: result })),
                            })
                          }
                        >
                          <KeyRound className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title={user.enabled ? "禁用该用户" : "启用该用户"}
                          disabled={setEnabled.isPending}
                          onClick={() =>
                            setEnabled.mutate({
                              userId: user.id,
                              enabled: !user.enabled,
                            })
                          }
                        >
                          {user.enabled ? (
                            <UserX className="size-3.5" />
                          ) : (
                            <Check className="size-3.5" />
                          )}
                        </Button>
                      </RowActions>
                    </div>

                    {issued[user.id] && (
                      <ResetTokenPanel
                        issued={issued[user.id]}
                        onDismiss={() =>
                          setIssued((prev) => {
                            const next = { ...prev }
                            delete next[user.id]
                            return next
                          })
                        }
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          <div className="space-y-3 p-4">
            <PrototypeNote>
              API 令牌与会话不在本页。`/api-tokens` 与 `/sessions` 属于**当前登录用户
              自己的账号**，不是管理员操作别人的账号的入口；把它们和用户管理并排会让人
              以为可以代他人签发令牌。契约层面也没有「某用户的令牌列表」这种端点。
            </PrototypeNote>
            {roles.data && roles.data.length > 0 && (
              <div className="rounded-lg border border-border p-3">
                <p className="flex items-center gap-1.5 text-xs font-medium">
                  <Lock className="size-3.5 text-muted-foreground" />
                  系统角色
                </p>
                <ul className="mt-2 space-y-1">
                  {roles.data.map((role) => (
                    <li key={role.id} className="text-[11px]">
                      <span className="font-medium">{role.name}</span>
                      {role.built_in && (
                        <span className="ml-1.5 text-muted-foreground">内置</span>
                      )}
                      {role.description && (
                        <span className="ml-1.5 text-muted-foreground">
                          {role.description}
                        </span>
                      )}
                      <span className="ml-1.5 tabular-nums text-muted-foreground">
                        {role.permissions.length} 项权限
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>

        {panel === "create" && (
          <CreateUserPanel
            roleIds={(roles.data ?? []).map((r) => r.id)}
            busy={create.isPending}
            onCancel={() => setPanel("none")}
            onSubmit={(body) =>
              create.mutate(body, { onSuccess: () => setPanel("none") })
            }
          />
        )}
        {panel !== "none" && panel !== "create" && (
          <EditUserPanel
            user={panel}
            roleIds={(roles.data ?? []).map((r) => r.id)}
            onClose={() => setPanel("none")}
          />
        )}
      </div>
    </div>
  )
}

function ResetTokenPanel({
  issued,
  onDismiss,
}: {
  issued: UserPasswordResetIssue
  onDismiss: () => void
}) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-status-degraded/30 bg-status-degraded/8 p-3">
      <p className="text-xs font-medium">
        密码重置令牌（只显示这一次，无法再取回）
      </p>
      <code className="block break-all rounded bg-background px-2 py-1.5 font-mono text-[11px]">
        {issued.token}
      </code>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void navigator.clipboard?.writeText(issued.token)
            setCopied(true)
          }}
        >
          {copied ? <Check /> : <Copy />} {copied ? "已复制" : "复制"}
        </Button>
        <span className="text-[11px] text-muted-foreground">
          有效期至 {formatClock(issued.expires_at)}
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onDismiss}>
          <X />
        </Button>
      </div>
    </div>
  )
}

function CreateUserPanel({
  roleIds,
  busy,
  onCancel,
  onSubmit,
}: {
  roleIds: string[]
  busy: boolean
  onCancel: () => void
  onSubmit: (body: {
    username: string
    display_name: string
    email: string | null
    password: string
    role_ids: string[]
  }) => void
}) {
  const [values, setValues] = useState({
    username: "",
    display_name: "",
    email: "",
    password: "",
  })
  const [picked, setPicked] = useState<string[]>([])
  const [touched, setTouched] = useState(false)

  const errors = validateUser(values, { requirePassword: true })
  const valid = !hasErrors(errors)

  return (
    <aside className="w-96 shrink-0 overflow-y-auto border-l border-border p-4">
      <h2 className="text-sm font-semibold">新建用户</h2>
      <div className="mt-3">
        <Field label="用户名" hint="创建后不可更改。字母、数字、下划线、点、连字符。">
          <Input
            value={values.username}
            aria-label="用户名"
            onChange={(e) =>
              setValues((p) => ({ ...p, username: e.target.value }))
            }
          />
        </Field>
        <Field label="显示名">
          <Input
            value={values.display_name}
            aria-label="显示名"
            onChange={(e) =>
              setValues((p) => ({ ...p, display_name: e.target.value }))
            }
          />
        </Field>
        <Field label="邮箱" hint="可空。">
          <Input
            value={values.email}
            aria-label="邮箱"
            onChange={(e) => setValues((p) => ({ ...p, email: e.target.value }))}
          />
        </Field>
        <Field label="初始密码" hint="至少 12 位。后端会拒绝更短的。">
          <Input
            type="password"
            value={values.password}
            aria-label="初始密码"
            onChange={(e) =>
              setValues((p) => ({ ...p, password: e.target.value }))
            }
          />
        </Field>
      </div>

      <div className="mt-3 space-y-1.5">
        <p className="text-sm font-medium">角色</p>
        {roleIds.length === 0 ? (
          <p className="text-xs text-muted-foreground">读取中…</p>
        ) : (
          roleIds.map((id) => (
            <label key={id} className="flex items-center gap-2 text-xs">
              <Checkbox
                aria-label={`角色 ${id}`}
                checked={picked.includes(id)}
                onChange={(e) =>
                  setPicked((prev) =>
                    e.target.checked ? [...prev, id] : prev.filter((x) => x !== id),
                  )
                }
              />
              {id}
            </label>
          ))
        )}
        <p className="text-[11px] text-muted-foreground">
          不选任何角色时，该用户登录后看不到任何机位。
        </p>
      </div>

      {touched && !valid && (
        <p className="mt-3 text-xs text-status-offline">
          {Object.values(errors)[0]}
        </p>
      )}

      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          取消
        </Button>
        <Button
          size="sm"
          disabled={busy}
          onClick={() => {
            setTouched(true)
            if (!valid) return
            onSubmit({
              username: values.username.trim(),
              display_name: values.display_name.trim(),
              email: values.email.trim() || null,
              password: values.password,
              role_ids: picked,
            })
          }}
        >
          {busy ? "创建中…" : "创建"}
        </Button>
      </div>
    </aside>
  )
}

function EditUserPanel({
  user,
  roleIds,
  onClose,
}: {
  user: UserAdminView
  roleIds: string[]
  onClose: () => void
}) {
  const [displayName, setDisplayName] = useState(user.display_name)
  const [email, setEmail] = useState(user.email ?? "")
  const [picked, setPicked] = useState(user.roles.map((r) => r.id))
  const save = useUpdateUser(user.id)

  const dirty =
    displayName !== user.display_name ||
    email !== (user.email ?? "") ||
    picked.join(",") !== user.roles.map((r) => r.id).join(",")

  return (
    <aside className="w-96 shrink-0 overflow-y-auto border-l border-border">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">编辑用户</h2>
        <Button variant="ghost" size="icon-sm" onClick={onClose}>
          <X className="size-3.5" />
        </Button>
      </div>

      <div className="p-4">
        <Field
          label="用户名"
          hint="后端的 UserUpdate 没有这个字段，创建后不可更改。"
        >
          <span className="font-mono text-xs text-muted-foreground">
            {user.username}
          </span>
        </Field>
        <Field label="显示名">
          <Input
            value={displayName}
            aria-label="显示名"
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </Field>
        <Field label="邮箱" hint="可空。">
          <Input
            value={email}
            aria-label="邮箱"
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <div className="mt-3 space-y-1.5">
          <p className="text-sm font-medium">角色</p>
          {roleIds.map((id) => (
            <label key={id} className="flex items-center gap-2 text-xs">
              <Checkbox
                aria-label={`角色 ${id}`}
                checked={picked.includes(id)}
                onChange={(e) =>
                  setPicked((prev) =>
                    e.target.checked ? [...prev, id] : prev.filter((x) => x !== id),
                  )
                }
              />
              {id}
            </label>
          ))}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
          <Button
            size="sm"
            disabled={!dirty || save.isPending}
            onClick={() =>
              save.mutate(
                {
                  display_name: displayName.trim(),
                  email: email.trim() || null,
                  role_ids: picked,
                },
                { onSuccess: onClose },
              )
            }
          >
            {save.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>

      <ScopeSection user={user} />
    </aside>
  )
}

/**
 * Camera scope is a separate resource with its own save, and it says so.
 * Merging it into the profile form's Save would make a failure ambiguous:
 * "did my role change land and my scope not, or neither?"
 */
function ScopeSection({ user }: { user: UserAdminView }) {
  const scope = useUserCameraScope(user.id)
  const save = useSetUserCameraScope(user.id)
  const cameras = useCameras()
  const groups = useCameraGroups()
  const [mode, setMode] = useState<CameraScopeMode>("inherit")
  const [picked, setPicked] = useState<string[]>([])
  const [pickedGroups, setPickedGroups] = useState<string[]>([])
  const [loaded, setLoaded] = useState<string | null>(null)

  useEffect(() => {
    if (!scope.data || loaded === user.id) return
    setMode(scope.data.mode)
    setPicked(scope.data.camera_ids)
    setPickedGroups(scope.data.camera_group_ids)
    setLoaded(user.id)
  }, [scope.data, loaded, user.id])

  const baseline = useMemo(
    () =>
      JSON.stringify([
        scope.data?.mode,
        scope.data?.camera_ids,
        scope.data?.camera_group_ids,
      ]),
    [scope.data],
  )
  const dirty =
    loaded === user.id &&
    JSON.stringify([mode, picked, pickedGroups]) !== baseline

  const isSelected = mode === "selected"

  return (
    <section className="border-t border-border p-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Lock className="size-3.5 text-muted-foreground" />
          可见机位范围
        </h3>
        {dirty && (
          <span className="text-[11px] text-status-degraded">范围未保存</span>
        )}
      </div>

      {scope.isPending ? (
        <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
      ) : scope.error ? (
        <p className="mt-2 text-xs text-status-offline">{scope.error.message}</p>
      ) : (
        <>
          <Segmented
            className="mt-2"
            value={mode}
            onChange={(v) => setMode(v as CameraScopeMode)}
            options={(["inherit", "all", "selected", "none"] as const).map(
              (m) => ({ value: m, label: CAMERA_SCOPE_LABEL[m] }),
            )}
          />
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            {CAMERA_SCOPE_HINT[mode]}
          </p>

          {isSelected && (
            <div className="mt-2 space-y-2">
              {(groups.data ?? []).length > 0 && (
                <div className="rounded-md border border-border p-2">
                  <p className="mb-1 text-[11px] text-muted-foreground">
                    机位组（与下面的机位合并生效）
                  </p>
                  <div className="max-h-32 space-y-1 overflow-y-auto">
                    {(groups.data ?? []).map((group) => (
                      <label
                        key={group.id}
                        className="flex items-center gap-2 text-xs"
                      >
                        <Checkbox
                          aria-label={`机位组 ${group.name}`}
                          checked={pickedGroups.includes(group.id)}
                          onChange={(e) =>
                            setPickedGroups((prev) =>
                              e.target.checked
                                ? [...prev, group.id]
                                : prev.filter((x) => x !== group.id),
                            )
                          }
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {group.name}
                        </span>
                        <span className="tabular-nums text-[10px] text-muted-foreground">
                          {group.camera_ids.length} 台
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                <p className="text-[11px] text-muted-foreground">单个机位</p>
                {(cameras.data ?? []).map((camera) => (
                  <label
                    key={camera.id}
                    className="flex items-center gap-2 text-xs"
                  >
                    <Checkbox
                      aria-label={`机位 ${camera.name}`}
                      checked={picked.includes(camera.id)}
                      onChange={(e) =>
                        setPicked((prev) =>
                          e.target.checked
                            ? [...prev, camera.id]
                            : prev.filter((x) => x !== camera.id),
                        )
                      }
                    />
                    <span className="min-w-0 flex-1 truncate">{camera.name}</span>
                  </label>
                ))}
                {picked.length === 0 && pickedGroups.length === 0 && (
                  <p className="text-[11px] text-status-degraded">
                    两者都不选 = 该用户看不到任何机位。
                  </p>
                )}
              </div>
            </div>
          )}

          <div className="mt-3 flex justify-end">
            <Button
              size="sm"
              disabled={!dirty || save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    mode,
                    // `inherit` and `all` carry no list; sending a stale
                    // selection alongside them would store ids the scope
                    // never reads.
                    camera_ids: isSelected ? picked : [],
                    camera_group_ids: isSelected ? pickedGroups : [],
                  },
                  { onSuccess: () => setLoaded(null) },
                )
              }
            >
              {save.isPending ? "保存中…" : "保存范围"}
            </Button>
          </div>
        </>
      )}
    </section>
  )
}
