/**
 * The permission matrix — the editor for a **custom** role.
 *
 * ## The built-in three are not editable, and this component never pretends they are
 *
 * The backend re-syncs Administrator / Operator / Viewer to their exact
 * permission sets on every start (`auth/service.py:71-97`) and refuses
 * `PATCH /roles/{id}` on any `built_in` role with 409
 * `auth/admin_service.py:293-298`. A checkbox that silently refuses to save is
 * the same failure as a field the server drops, so the caller only ever opens
 * this for a role with `built_in === false`; the three are listed as a fixed
 * reference elsewhere on the page.
 *
 * ## No "select the whole domain" toggle
 *
 * Permissions are grouped by domain for reading, not as switchable units.
 * `recording.export` and `recording.delete` are not a pair that travels
 * together, so a group toggle would only produce partial states and a second
 * way to grant the wrong thing. Nineteen flat checkboxes, labelled, is the
 * whole matrix.
 *
 * ## An empty set is legal
 *
 * Creating a role that grants nothing is how an operator stages one before
 * assigning it. So it is not blocked — but the consequence is stated, because a
 * role with no permissions silently grants nothing and looks like a mistake.
 */
import type React from "react"
import { useEffect, useMemo, useState } from "react"

import {
  groupPermissions,
  validateRole,
  type RoleView,
} from "../../api/users"
import { Button, Input, Textarea } from "../ui/primitives"
import { Callout, Checkbox } from "../ui/display"
import { CameraScopeEditor } from "./CameraScopeEditor"
import {
  useCameraGroups,
  useCameras,
  useRoleCameraScope,
} from "../../lib/queries"
import { useSetRoleCameraScope } from "../../lib/userMutations"

export function RoleEditor({
  role,
  catalogue,
  onClose,
  onSubmit,
  busy,
}: {
  /** `null` creates a new role. */
  role: RoleView | null
  catalogue: string[]
  onClose: () => void
  onSubmit: (body: { name: string; description: string | null; permissions: string[] }) => void
  busy: boolean
}) {
  const [name, setName] = useState(role?.name ?? "")
  const [description, setDescription] = useState(role?.description ?? "")
  const [granted, setGranted] = useState<string[]>(role?.permissions ?? [])

  // A different role without a remount (the page swaps the panel in place).
  useEffect(() => {
    setName(role?.name ?? "")
    setDescription(role?.description ?? "")
    setGranted(role?.permissions ?? [])
  }, [role])

  const groups = useMemo(() => groupPermissions(catalogue), [catalogue])
  const errors = useMemo(() => validateRole({ name }), [name])

  // A granted permission the catalogue no longer lists would be invisible in
  // the matrix yet still submitted. `PATCH /roles` replaces the whole set, so a
  // stale entry is silently dropped server-side; showing it is the honest option.
  const orphans = useMemo(
    () => granted.filter((p) => !catalogue.includes(p)).sort(),
    [granted, catalogue],
  )

  const toggle = (permission: string, on: boolean) =>
    setGranted((prev) =>
      on
        ? [...new Set([...prev, permission])]
        : prev.filter((p) => p !== permission),
    )

  return (
    <div className="flex h-full w-full flex-col border-l border-border bg-card">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium">
            {role ? `编辑角色 ${role.name}` : "新建角色"}
          </h2>
          <p className="truncate text-xs text-muted-foreground">
            权限决定这个角色能做什么，机位范围决定它能看到哪些画面。
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭">
          关闭
        </Button>
      </header>

      <div className="flex-1 space-y-4 overflow-auto p-4">
        <div className="space-y-1.5">
          <label htmlFor="role-name" className="text-xs font-medium">
            角色名
          </label>
          <Input
            id="role-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={Boolean(errors.name)}
            placeholder="例如：夜班值班员"
          />
          {errors.name ? (
            <p className="text-xs text-status-offline">{errors.name}</p>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="role-description" className="text-xs font-medium">
            说明（可选）
          </label>
          <Textarea
            id="role-description"
            value={description}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
              setDescription(e.target.value)
            }
            rows={2}
            placeholder="给以后看这个角色的人留一句上下文。"
          />
        </div>

        {granted.length === 0 && (
          <Callout tone="degraded" title="这个角色目前不授予任何权限">
            分配给用户后，该用户在所有这些页面上都会是空的或被拒绝。留空是合法的——
            常见用法是先建好角色，确认无误再分配。
          </Callout>
        )}

        {orphans.length > 0 && (
          <Callout tone="degraded" title="有权限已不在目录中">
            {`这些权限服务端已不再支持，保存时会被丢弃：${orphans.join("、")}。`}
          </Callout>
        )}

        <div
          role="group"
          aria-label="权限"
          className="space-y-3 rounded-lg border border-border p-3"
        >
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium">
              权限（已选 {granted.length} / {catalogue.length}）
            </p>
            <Button
              variant="ghost"
              size="sm"
              // A "clear all" is worth having: a role staged with everything
              // ticked by accident needs a way back that is not 19 clicks.
              disabled={granted.length === 0}
              onClick={() => setGranted([])}
            >
              清空
            </Button>
          </div>

          {groups.map((group) => (
            <div key={group.domain}>
              <p className="mb-1 text-[11px] text-muted-foreground">
                {group.label}
              </p>
              <div className="space-y-1">
                {group.items.map((item) => (
                  <label
                    key={item.permission}
                    className="flex items-center gap-2 text-xs"
                  >
                    <Checkbox
                      checked={granted.includes(item.permission)}
                      onChange={(e) => toggle(item.permission, e.target.checked)}
                    />
                    <span className="min-w-0 flex-1">{item.label}</span>
                    <code className="font-mono text-[10px] text-muted-foreground">
                      {item.permission}
                    </code>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
        <Button variant="outline" size="sm" onClick={onClose}>
          取消
        </Button>
        <Button
          size="sm"
          disabled={busy || Object.keys(errors).length > 0}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              description: description.trim() === "" ? null : description.trim(),
              permissions: granted,
            })
          }
        >
          {busy ? "保存中…" : "保存权限"}
        </Button>
      </footer>
    </div>
  )
}

/**
 * A role's camera scope.
 *
 * Deliberately a **separate step** from the permission save above. A role has
 * two independent resources — a permission set and a camera scope — on two
 * endpoints. Their change rates differ by an order of magnitude (permissions
 * maybe yearly, scope weekly), and one "Save" for both would leave the operator
 * unable to tell which half landed.
 */
export function RoleScopeSection({ role }: { role: RoleView }) {
  const scope = useRoleCameraScope(role.id)
  const save = useSetRoleCameraScope(role.id)
  const cameras = useCameras()
  const groups = useCameraGroups()

  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-semibold">这个角色的可见机位范围</h3>
      <p className="text-[11px] text-muted-foreground">
        与权限分开保存。机位范围决定「有权限的人能看到哪几台」，两者互不替代。
      </p>
      <CameraScopeEditor
        scope={scope.data}
        isPending={scope.isPending}
        error={scope.error}
        cameras={cameras.data ?? []}
        groups={groups.data ?? []}
        busy={save.isPending}
        subject="该角色下的人"
        onSave={(body) => save.mutate(body)}
      />
    </section>
  )
}
