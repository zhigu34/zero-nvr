/**
 * Camera group contract. Mirrors `backend/app/modules/cameras/{schemas,groups}.py`.
 *
 * ## A group is a many-to-many label, and the tree is implicit
 *
 * `camera_group_members` is a composite-PK join table
 * (`models.py:379-391`): a camera may sit in any number of groups and a group
 * may hold any number of cameras, with no limit enforced anywhere. The
 * hierarchy is a single `parent_id` column and the view carries no `child_ids`
 * (`schemas.py:152-157`), so a client has to rebuild the tree itself. That is
 * why `buildGroupTree` lives here rather than in a component.
 *
 * ## PATCH merges fields but replaces members
 *
 * `api.py:540` uses `model_dump(exclude_unset=True)`, so an omitted field is
 * preserved. But `camera_ids` is special: when present it **deletes every
 * membership and re-inserts** (`groups.py:154-168`). An editor that PATCHes
 * the one camera it added, without resending the rest, silently empties the
 * group. `buildGroupPatch` therefore always sends the complete list.
 *
 * And "absent" is not the same as "null":
 *
 * | field | omitted | `null` |
 * |---|---|---|
 * | `name` | preserved | 400 `camera_group_name_invalid` |
 * | `description` | preserved | **cleared** |
 * | `parent_id` | preserved | **cleared** (back to a root) |
 * | `camera_ids` | preserved | 400 `camera_group_camera_invalid` |
 *
 * ## Deleting is hard and frequently blocked
 *
 * There is no soft delete and no trash (`groups.py:323`). Two 409s stand in the
 * way, and both are the correct behaviour rather than a limitation to work
 * around:
 *
 * - `camera_group_has_children` — must delete bottom-up; there is no reparent.
 * - `camera_group_in_use` — a user or role camera scope still references it.
 *
 * ## Naming a group's scope is not a flat choice
 *
 * This does not belong to this endpoint but decides whether a picker built
 * from this data is honest. Granting a user a group expands it to **all
 * descendant groups transitively** (`auth/camera_scope.py:237-252`), and a user
 * scope row **overrides** role scopes rather than intersecting them
 * (`camera_scope.py:296-297`). A flat checkbox list would therefore promise
 * less than it delivers and hide a security-relevant override. See
 * `descendantsOf` and the note in `docs/FRONTEND-CONTRACT-GAPS.md`.
 */
import { api } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type CameraGroupView = {
  id: string
  name: string
  description: string | null
  /** `null` for a root. The view has no `child_ids`; rebuild the tree. */
  parent_id: string | null
  camera_ids: string[]
}

export type CameraGroupCreate = {
  name: string
  description?: string | null
  parent_id?: string | null
  camera_ids?: string[]
}

export type CameraGroupUpdate = {
  name?: string
  description?: string | null
  parent_id?: string | null
  camera_ids?: string[]
}

export const GROUP_NAME_MAX = 128
export const GROUP_DESCRIPTION_MAX = 2048

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

/** `camera.configure`. Not camera-scoped — this returns every group. */
export function listCameraGroups(signal?: AbortSignal) {
  return api.get<CameraGroupView[]>("/camera-groups", signal)
}

export function getCameraGroup(groupId: string, signal?: AbortSignal) {
  return api.get<CameraGroupView>(`/camera-groups/${groupId}`, signal)
}

export function createCameraGroup(body: CameraGroupCreate) {
  return api.post<CameraGroupView>("/camera-groups", body)
}

export function updateCameraGroup(groupId: string, body: CameraGroupUpdate) {
  return api.patch<CameraGroupView>(`/camera-groups/${groupId}`, body)
}

/** 204. Hard delete, blocked by `has_children` and `in_use`. */
export function deleteCameraGroup(groupId: string) {
  return api.del<void>(`/camera-groups/${groupId}`)
}

/* -------------------------------------------------------------------------- */
/* Tree                                                                       */
/* -------------------------------------------------------------------------- */

export type GroupNode = {
  group: CameraGroupView
  children: GroupNode[]
}

/**
 * Rebuild the hierarchy from `parent_id`.
 *
 * The server does not return it and does not guarantee the data is acyclic —
 * `409 camera_group_hierarchy_invalid` exists precisely because a cycle can be
 * in the database (`groups.py:93-97`). A cycle would make this recurse forever,
 * so any group not reached from a root is promoted to a top-level node and the
 * rest is still rendered rather than dropped.
 */
export function buildGroupTree(groups: CameraGroupView[]): GroupNode[] {
  const byId = new Map(groups.map((g) => [g.id, g]))
  const childrenOf = new Map<string | null, CameraGroupView[]>()
  for (const group of groups) {
    const parent = group.parent_id && byId.has(group.parent_id) ? group.parent_id : null
    const bucket = childrenOf.get(parent)
    if (bucket) bucket.push(group)
    else childrenOf.set(parent, [group])
  }

  const roots = childrenOf.get(null) ?? []
  const claimed = new Set<string>()

  function build(group: CameraGroupView): GroupNode {
    claimed.add(group.id)
    const children = (childrenOf.get(group.id) ?? []).map(build)
    return { group, children }
  }

  const tree = roots.map(build)

  // Anything left is inside a cycle. Show it rather than hiding data, and do
  // not recurse into it again.
  for (const group of groups) {
    if (!claimed.has(group.id)) {
      claimed.add(group.id)
      tree.push({ group, children: [] })
    }
  }

  return tree
}

/**
 * A group plus every group beneath it, transitively.
 *
 * This is what a scope grant actually expands to (`auth/camera_scope.py:237-252`),
 * so it is the set a picker must show as "covered by this checkbox" — offering
 * a parent group as if it covered only itself would understate the grant.
 */
export function descendantsOf(
  groups: CameraGroupView[],
  rootId: string,
): Set<string> {
  const childrenOf = new Map<string, string[]>()
  for (const group of groups) {
    if (!group.parent_id) continue
    const bucket = childrenOf.get(group.parent_id)
    if (bucket) bucket.push(group.id)
    else childrenOf.set(group.parent_id, [group.id])
  }
  const seen = new Set<string>()
  const queue = [rootId]
  while (queue.length > 0) {
    const id = queue.pop() as string
    if (seen.has(id)) continue
    seen.add(id)
    for (const child of childrenOf.get(id) ?? []) queue.push(child)
  }
  return seen
}

/** The groups that would be dragged in by selecting `groupId`. */
export function impliedBySelection(
  groups: CameraGroupView[],
  selected: Iterable<string>,
): Set<string> {
  const implied = new Set<string>()
  for (const id of selected) {
    for (const member of descendantsOf(groups, id)) implied.add(member)
  }
  return implied
}

/* -------------------------------------------------------------------------- */
/* Build body                                                                 */
/* -------------------------------------------------------------------------- */

export type GroupForm = {
  name: string
  description: string
  /** `null` = a root group. */
  parentId: string | null
  cameraIds: string[]
}

export type GroupFormField = "name" | "description" | "parentId"

export type GroupFormError = { field: GroupFormField; message: string }

export function groupFormFromView(group: CameraGroupView): GroupForm {
  return {
    name: group.name,
    description: group.description ?? "",
    parentId: group.parent_id,
    cameraIds: [...group.camera_ids],
  }
}

export function emptyGroupForm(): GroupForm {
  return { name: "", description: "", parentId: null, cameraIds: [] }
}

/**
 * The server `.strip()`s the name and rejects a whitespace-only one with 400
 * `camera_group_name_invalid` (`groups.py:181-187`) — but `min_length=1` on the
 * schema lets `" "` through, so the failure arrives as a service error rather
 * than a validation error. Checking it here names the field.
 */
export function validateGroupForm(form: GroupForm): GroupFormError[] {
  const errors: GroupFormError[] = []
  const name = form.name.trim()

  if (name === "") {
    errors.push({ field: "name", message: "请填写分组名称" })
  } else if (name.length > GROUP_NAME_MAX) {
    errors.push({ field: "name", message: `名称最长 ${GROUP_NAME_MAX} 个字符` })
  }

  if (form.description.length > GROUP_DESCRIPTION_MAX) {
    errors.push({
      field: "description",
      message: `说明最长 ${GROUP_DESCRIPTION_MAX} 个字符`,
    })
  }

  return errors
}

/**
 * Build the PATCH body.
 *
 * `camera_ids` is always present and always complete, because the endpoint
 * replaces membership wholesale. Sending it only when it changed would be
 * equivalent, but sending it always is one less thing to get wrong when the
 * form gains a second edit path.
 *
 * `description` and `parent_id` are sent only when they actually moved, and
 * `null` is sent deliberately in the "cleared" case — for these two, `null`
 * means "remove it", which is the opposite of the default and the reason an
 * omitted field must not be used to express it.
 */
export function buildGroupPatch(
  original: CameraGroupView,
  form: GroupForm,
): CameraGroupUpdate {
  const body: CameraGroupUpdate = {}

  if (form.name.trim() !== original.name) body.name = form.name.trim()
  if ((form.description.trim() || null) !== original.description) {
    body.description = form.description.trim() || null
  }
  if (form.parentId !== original.parent_id) body.parent_id = form.parentId

  const before = [...original.camera_ids].sort()
  const after = [...new Set(form.cameraIds)].sort()
  if (before.length !== after.length || before.some((id, i) => id !== after[i])) {
    body.camera_ids = [...new Set(form.cameraIds)]
  }

  return body
}

/** A PATCH with nothing in it is still a request; the form uses this to disable save. */
export function isGroupPatchEmpty(body: CameraGroupUpdate): boolean {
  return Object.keys(body).length === 0
}

/* -------------------------------------------------------------------------- */
/* Delete blockers                                                            */
/* -------------------------------------------------------------------------- */

export const GROUP_DELETE_BLOCK_LABEL: Record<string, string> = {
  camera_group_has_children: "该分组还有下级分组，请先删除或移动下级。",
  camera_group_in_use: "该分组仍被某个用户或角色的摄像机范围引用，请先在那边移除。",
}

/**
 * Whether this group can be deleted at all, from the data already on hand.
 *
 * Children are knowable client-side. `camera_group_in_use` is not — it depends
 * on user and role scopes this endpoint does not return — so the parent is only
 * a *pre-check*, and a 409 from the server stays authoritative. Saying so in the
 * UI beats a button that looks available and then refuses.
 */
export function groupDeleteBlocker(
  group: CameraGroupView,
  groups: CameraGroupView[],
): string | null {
  const hasChildren = groups.some((g) => g.parent_id === group.id)
  if (hasChildren) return GROUP_DELETE_BLOCK_LABEL.camera_group_has_children
  return null
}
