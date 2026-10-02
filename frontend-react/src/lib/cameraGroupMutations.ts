import {
  createCameraGroup,
  deleteCameraGroup,
  updateCameraGroup,
  type CameraGroupCreate,
  type CameraGroupUpdate,
} from "../api/cameraGroups"
import { ADMIN } from "./queries"
import { useSave } from "./save"

/**
 * There is no delete-anything-else in this module, which is worth noting: the
 * endpoint set is list / get / create / patch / delete and nothing more. There
 * is no trash, no restore, and no soft delete (`cameras/groups.py:323`).
 */

export function useCreateCameraGroup() {
  return useSave<CameraGroupCreate, unknown>({
    mutationFn: (body) => createCameraGroup(body),
    invalidates: [ADMIN.cameraGroups],
    success: () => ({ title: "分组已创建" }),
    failure: (error) => ({ title: "创建分组失败", detail: describeGroupFailure(error) }),
  })
}

/**
 * The body is built by `buildGroupPatch`, which always sends the complete
 * camera list. An editor that sent only the added id would empty the group —
 * see the module note in `api/cameraGroups.ts`.
 */
export function useUpdateCameraGroup(groupId: string) {
  return useSave<CameraGroupUpdate, unknown>({
    mutationFn: (body) => updateCameraGroup(groupId, body),
    invalidates: [ADMIN.cameraGroups],
    success: () => ({ title: "分组已更新" }),
    failure: (error) => ({ title: "更新分组失败", detail: describeGroupFailure(error) }),
  })
}

/**
 * A hard delete with no undo, and two 409s that stand in the way.
 *
 * Both are legitimate refusals rather than bugs, so the messages say what to do
 * next instead of repeating the code:
 *
 * - `camera_group_has_children` — no reparent, so it has to go bottom-up.
 * - `camera_group_in_use` — a user or role camera scope still points at it.
 */
export function useDeleteCameraGroup() {
  return useSave<string, void>({
    mutationFn: (groupId) => deleteCameraGroup(groupId),
    invalidates: [ADMIN.cameraGroups],
    success: () => ({ title: "分组已删除" }),
    failure: (error) => ({ title: "删除分组失败", detail: describeGroupFailure(error) }),
  })
}

function describeGroupFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  switch (code) {
    case "camera_group_has_children":
      return "该分组还有下级分组，请先删除或把它们移到别处。"
    case "camera_group_in_use":
      return "该分组仍被某个用户或角色的摄像机范围引用，请先在那边移除。"
    case "camera_group_name_conflict":
      return "同名分组已存在。分组名称全局唯一。"
    case "camera_group_name_invalid":
      return "名称不能为空。"
    case "camera_group_parent_cycle":
      return "不能把分组挂到它自己或它的下级下面。"
    case "camera_group_parent_invalid":
      return "上级分组不存在。"
    case "camera_group_hierarchy_invalid":
      return "该分组的上级关系已形成环，请先在上游修正层级。"
    case "camera_group_camera_invalid":
      return "摄像机列表无效：其中有本系统不存在的机位。"
    case "camera_group_not_found":
      return "分组已被删除。"
    default:
      return error instanceof Error ? error.message : String(error)
  }
}
