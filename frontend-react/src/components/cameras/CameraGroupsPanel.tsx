import { useMemo, useState } from "react"
import { FolderTree, Pencil, Plus, Trash2, X } from "lucide-react"

import {
  GROUP_DELETE_BLOCK_LABEL,
  buildGroupPatch,
  buildGroupTree,
  descendantsOf,
  emptyGroupForm,
  groupDeleteBlocker,
  groupFormFromView,
  isGroupPatchEmpty,
  validateGroupForm,
  type CameraGroupCreate,
  type CameraGroupUpdate,
  type CameraGroupView,
  type GroupForm,
  type GroupFormField,
  type GroupNode,
} from "../../api/cameraGroups"
import {
  useCreateCameraGroup,
  useDeleteCameraGroup,
  useUpdateCameraGroup,
} from "../../lib/cameraGroupMutations"
import { useCameras, useCameraGroups } from "../../lib/queries"
import { useConfirm } from "../ui/Confirm"
import { Button, Input, Select } from "../ui/primitives"
import {
  Callout,
  Checkbox,
  EmptyState,
  Field,
  PrototypeNote,
  RowActions,
} from "../ui/display"

/**
 * 摄像机分组。
 *
 * A group is a label plus a hierarchy, and both halves have a consequence that
 * a naive editor gets wrong without ever showing an error:
 *
 * 1. **A membership edit is a whole-group replacement.** `PATCH /camera-groups/{id}`
 *    runs `model_dump(exclude_unset=True)` (`api.py:540`), but `camera_ids` is
 *    special: when present it deletes every membership row and re-inserts
 *    (`groups.py:154-168`). Sending only the id that was just added silently
 *    empties the group, so the body is always built by `buildGroupPatch` and
 *    never assembled here.
 * 2. **A field the operator blanks has to be cleared, not preserved.** For
 *    `description` and `parent_id`, `null` *means* remove (`api/cameraGroups.ts`
 *    has the table); omitting the key means leave it alone. Both are offered as
 *    reachable actions — an emptied textarea and a "no parent" choice — because
 *    "I typed nothing here" and "I meant to clear it" are otherwise the same
 *    gesture with opposite outcomes.
 * 3. **A grant of this group is bigger than the group.** Authorising a user or a
 *    role with a group expands to every descendant group
 *    (`modules/auth/camera_scope.py:237-252`), and a user scope *overrides* role
 *    scopes rather than intersecting them (`camera_scope.py:296-297`). A panel
 *    that showed `camera_ids.length` and nothing else would understate a
 *    security-relevant grant, so a group that has descendants also shows the
 *    number of cameras it covers in total.
 *
 * Delete is a hard delete with no trash (`groups.py:323`) and is refused in two
 * situations. `camera_group_has_children` is knowable from the data on hand and
 * disables the button outright; `camera_group_in_use` is not — it depends on user
 * and role scopes this endpoint does not return — so that one stays a server
 * 409 and the message comes back translated.
 *
 * The tree is rebuilt client-side because the view carries no `child_ids`, and
 * the data may genuinely contain a cycle (there is a dedicated 409 for it,
 * `groups.py:93-97`), so `buildGroupTree` terminates rather than recursing.
 */
export function CameraGroupsPanel() {
  const groupsQuery = useCameraGroups()
  const [editing, setEditing] = useState<CameraGroupView | "create" | null>(null)

  const groups = groupsQuery.data ?? []
  const tree = buildGroupTree(groups)

  return (
    <div className="space-y-4">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">摄像机分组</h3>
          <Button size="sm" onClick={() => setEditing("create")}>
            <Plus /> 新建分组
          </Button>
        </div>

        <p className="mt-1 text-[11px] text-muted-foreground">
          这里是全部分组，不受你当前账号的摄像机范围限制。
        </p>

        {groupsQuery.isPending ? (
          <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
        ) : groupsQuery.error ? (
          <div className="mt-2">
            <Callout tone="offline" title="无法读取摄像机分组">
              {groupsQuery.error.message}
            </Callout>
          </div>
        ) : tree.length === 0 ? (
          <div className="mt-2">
            <EmptyState
              icon={<FolderTree />}
              title="还没有任何分组"
              description="分组只是给一组摄像机起的名字：用户和角色可以按分组授权，一个分组还能嵌在另一个分组下面。没有分组不影响摄像机本身的使用。"
            />
          </div>
        ) : (
          <ul className="mt-2 space-y-2" aria-label="分组列表">
            {tree.map((node) => (
              <GroupRow
                key={node.group.id}
                node={node}
                groups={groups}
                onEdit={setEditing}
              />
            ))}
          </ul>
        )}
      </section>

      {editing && (
        <GroupEditor
          group={editing === "create" ? undefined : editing}
          groups={groups}
          onClose={() => setEditing(null)}
        />
      )}

      <PrototypeNote>
        分组授权是传递的：把一个分组授予用户或角色，会连带覆盖它下面所有分组的摄像机（user_scope 优先于角色范围，不是取交集）。
      </PrototypeNote>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

/**
 * How many cameras a group reaches, counting everything below it.
 *
 * The own count is what the operator edited; this is what a scope grant actually
 * hands out, so the two are shown as separate numbers and never merged into one
 * figure that could mean either.
 */
function coveredCameraCount(group: CameraGroupView, groups: CameraGroupView[]): number {
  const byId = new Map(groups.map((g) => [g.id, g]))
  const cameras = new Set<string>()
  for (const groupId of descendantsOf(groups, group.id)) {
    for (const cameraId of byId.get(groupId)?.camera_ids ?? []) cameras.add(cameraId)
  }
  return cameras.size
}

/**
 * One group and the groups filed under it.
 *
 * The action handlers take the group rather than closing over it at the parent:
 * the rows are recursive, so a callback bound where the branch started would
 * edit the root of the branch no matter which row was clicked.
 */
function GroupRow({
  node,
  groups,
  onEdit,
}: {
  node: GroupNode
  groups: CameraGroupView[]
  onEdit: (group: CameraGroupView) => void
}) {
  const { group, children } = node
  const remove = useDeleteCameraGroup()
  const confirm = useConfirm()

  const blocker = groupDeleteBlocker(group, groups)
  const childNames = groups
    .filter((g) => g.parent_id === group.id)
    .map((g) => g.name)
  // `descendantsOf` includes the group itself, so a size above one means the
  // grant reaches further than the row shows.
  const hasDescendants = descendantsOf(groups, group.id).size > 1

  return (
    <li className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <FolderTree className="size-4 shrink-0 text-muted-foreground" />
        <p className="text-sm font-medium">{group.name}</p>
        <span className="text-[11px] text-muted-foreground">
          {`本组 ${group.camera_ids.length} 个摄像机`}
        </span>

        <RowActions>
          <Button
            variant="ghost"
            size="icon-sm"
            title="编辑"
            // Rows nest, so a row's scope contains its children's controls too.
            // The name belongs in the label, or "编辑" is ambiguous three levels
            // down and the test that opens an editor cannot say which group it
            // opened.
            aria-label={`编辑分组 ${group.name}`}
            onClick={() => onEdit(group)}
          >
            <Pencil className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`删除分组 ${group.name}`}
            // A known blocker travels on the button itself, so a row scrolled
            // out of the reason's line still says why it is not clickable.
            title={blocker ?? "删除"}
            disabled={Boolean(blocker) || remove.isPending}
            onClick={async () => {
              const ok = await confirm({
                title: "删除分组",
                message: `确定删除分组「${group.name}」？删除是硬删除，没有回收站，也没有撤销。`,
                confirmLabel: "删除",
                danger: true,
              })
              if (ok) remove.mutate(group.id)
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </RowActions>
      </div>

      {hasDescendants && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          {`连同下级共覆盖 ${coveredCameraCount(group, groups)} 个摄像机`}
        </p>
      )}

      {group.description && (
        <p className="mt-1 text-[11px] text-muted-foreground">{group.description}</p>
      )}

      {blocker && (
        <p className="mt-1 text-[11px] text-status-degraded">
          {childNames.length > 0
            ? `${blocker}（${childNames.join("、")}）`
            : blocker}
        </p>
      )}

      {children.length > 0 && (
        <ul className="mt-2 ml-4 space-y-2 border-l border-border pl-3">
          {children.map((child) => (
            <GroupRow
              key={child.group.id}
              node={child}
              groups={groups}
              onEdit={onEdit}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

/* -------------------------------------------------------------------------- */

function GroupEditor({
  group,
  groups,
  onClose,
}: {
  group?: CameraGroupView
  groups: CameraGroupView[]
  onClose: () => void
}) {
  const creating = !group
  const [form, setForm] = useState<GroupForm>(() =>
    group ? groupFormFromView(group) : emptyGroupForm(),
  )
  const camerasQuery = useCameras()
  const create = useCreateCameraGroup()
  const update = useUpdateCameraGroup(group?.id ?? "")

  const cameras = camerasQuery.data ?? []
  const byId = new Map(groups.map((g) => [g.id, g]))

  // A group may not sit under itself or under anything already beneath it, or
  // the server answers 409 `camera_group_parent_cycle`. Those options are left
  // out rather than disabled, because offering an action that always fails is
  // worse than not offering it. A stale tree can still produce the 409, which
  // the mutation layer translates.
  const forbidden = group ? descendantsOf(groups, group.id) : new Set<string>()
  const parentOptions = groups.filter((g) => !forbidden.has(g.id))

  const patch: CameraGroupUpdate | null = useMemo(
    () => (group ? buildGroupPatch(group, form) : null),
    [group, form],
  )
  const errors = validateGroupForm(form)
  const errorFor = (field: GroupFormField) =>
    errors.find((e) => e.field === field)?.message ?? null

  // A PATCH with nothing in it is still a request, and on an unchanged form it
  // is a request whose only effect is an audit entry nobody wanted.
  const nothingToSave = patch !== null && isGroupPatchEmpty(patch)
  const busy = create.isPending || update.isPending
  const blocked = errors.length > 0 || nothingToSave || busy

  // Members that are not in the camera list — a retired camera, or one the
  // caller cannot see. They stay in `form.cameraIds` untouched, because the
  // membership PATCH replaces the whole set: a picker rebuilt from the visible
  // rows would drop them, and dropping is not something the operator asked for.
  const unknownMembers = form.cameraIds.filter((id) => !cameras.some((c) => c.id === id))

  const impliedNames = group
    ? [...descendantsOf(groups, group.id)]
        .filter((id) => id !== group.id)
        .map((id) => byId.get(id)?.name)
        .filter((name): name is string => Boolean(name))
    : []

  function toggleCamera(cameraId: string, on: boolean) {
    setForm((current) => ({
      ...current,
      cameraIds: on
        ? [...new Set([...current.cameraIds, cameraId])]
        : current.cameraIds.filter((id) => id !== cameraId),
    }))
  }

  function submit() {
    if (blocked) return

    if (creating) {
      // There is no original to diff against on create, so the body is written
      // out here. Omitting an empty `camera_ids` is the same thing as sending
      // `[]` — a new group starts empty either way.
      const body: CameraGroupCreate = { name: form.name.trim() }
      if (form.description.trim()) body.description = form.description.trim()
      if (form.parentId) body.parent_id = form.parentId
      if (form.cameraIds.length > 0) body.camera_ids = [...form.cameraIds]
      create.mutate(body, { onSuccess: onClose })
      return
    }

    if (!group || patch === null) return
    update.mutate(patch, { onSuccess: onClose })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/40 p-4 pt-16">
      <div
        role="dialog"
        aria-label="分组编辑器"
        className="w-full max-w-lg rounded-lg border border-border bg-background p-4 shadow-lg"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            {group ? `编辑分组：${group.name}` : "新建分组"}
          </h3>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭">
            <X className="size-3.5" />
          </Button>
        </div>

        <div className="mt-1">
          <Field label="名称" hint="名称全局唯一；首尾空格会被服务端去掉，只填空格算无效。">
            <Input
              className="w-56"
              value={form.name}
              aria-label="分组名称"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          {errorFor("name") && (
            <p className="pb-1 text-[11px] text-status-offline">{errorFor("name")}</p>
          )}

          <Field
            label="说明"
            hint="清空这一栏并保存＝把说明删掉，不是「保持不变」——留空和清空在这里是同一个动作。"
          >
            <textarea
              className="h-20 w-56 rounded-lg border border-input bg-background px-2.5 py-1.5 text-sm shadow-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
              aria-label="分组说明"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Field>
          {errorFor("description") && (
            <p className="pb-1 text-[11px] text-status-offline">
              {errorFor("description")}
            </p>
          )}

          <Field
            label="上级分组"
            hint="移到「无上级」＝把分组拉回顶级；这里不能选它自己和它的下级，否则会形成环。"
          >
            <Select
              className="w-56"
              aria-label="上级分组"
              value={form.parentId ?? ""}
              onChange={(e) => setForm({ ...form, parentId: e.target.value || null })}
            >
              <option value="">无上级（顶级分组）</option>
              {parentOptions.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="mt-3 border-t border-border pt-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">摄像机成员</p>
            <p className="text-[11px] text-muted-foreground">
              {`已选 ${form.cameraIds.length} 个摄像机`}
            </p>
          </div>
          <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
            保存时会发送完整的摄像机列表：这个接口不是「只加不减」，而是一次性替换整组成员，所以少勾一台＝少一台。
          </p>

          {cameras.length === 0 ? (
            <p className="mt-2 text-[11px] text-muted-foreground">没有可选的摄像机。</p>
          ) : (
            <div
              role="group"
              aria-label="摄像机成员"
              className="mt-2 max-h-44 space-y-1 overflow-y-auto rounded-lg border border-border p-2"
            >
              {cameras.map((camera) => (
                // The checkbox is associated by id instead of by nesting: a
                // checkbox inside its own label toggles once in a browser and is
                // a coin flip under test, which is not a risk worth taking.
                <span
                  key={camera.id}
                  className="flex items-center gap-2 text-xs"
                >
                  <Checkbox
                    id={`group-camera-${camera.id}`}
                    aria-label={camera.name}
                    checked={form.cameraIds.includes(camera.id)}
                    onChange={(e) => toggleCamera(camera.id, e.target.checked)}
                  />
                  <label htmlFor={`group-camera-${camera.id}`}>{camera.name}</label>
                </span>
              ))}
            </div>
          )}

          {unknownMembers.length > 0 && (
            <p className="mt-1.5 text-[11px] text-status-degraded">
              {`有 ${unknownMembers.length} 个成员没有出现在摄像机列表里（可能已停用），保存时会原样保留。`}
            </p>
          )}
        </div>

        {impliedNames.length > 0 && (
          <p className="mt-3 rounded-lg border border-dashed border-border px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground">
            {`把本分组授予用户或角色时，会连带授权 ${impliedNames.length} 个下级分组：${impliedNames.join("、")}。本组的摄像机数量并不等于这次授权的实际范围。`}
          </p>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" disabled={blocked} onClick={submit}>
            {busy ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>
    </div>
  )
}
