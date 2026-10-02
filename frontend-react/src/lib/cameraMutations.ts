/**
 * Camera writes.
 *
 * The interesting one is `enable` / `disable` / `retire`. The backend commits
 * the database change first and only then hands the change to the media
 * runtime; if that second step fails it returns **503** with
 * `details.camera_persisted = true` (`cameras/api.py:1587`). A client that
 * reads only the status code will tell the operator "操作失败" and they will
 * retry — against a state that was already saved.
 *
 * So the message is chosen by whether anything was persisted, not by the
 * status line. "Saved, but the camera is not streaming yet" and "nothing was
 * saved" are different situations and the operator's next action differs.
 */
import {
  disableCamera,
  enableCamera,
  probeCamera,
  replaceStreamBindings,
  restoreCamera,
  retireCamera,
  updateCamera,
  type CameraStreamBindingInput,
  type CameraUpdate,
} from "../api/cameras"
import { CAMS } from "./queries"
import { useSave } from "./save"
import type { ApiError } from "../api/client"

/** True when the request failed *after* its change was already committed. */
export function wasPersisted(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const details = (error as ApiError).details
  if (!details || typeof details !== "object") return false
  return Object.values(details).some((value) => value === true)
}

function partialFailure(entity: string) {
  return (error: unknown) => {
    if (wasPersisted(error)) {
      return {
        title: `${entity}已保存，但尚未生效`,
        detail:
          "数据库中的更改已经写入，媒体运行时未接受该操作（通常是媒体服务繁忙或摄像机离线）。配置会在服务恢复后由后台任务重试。",
      }
    }
    return {
      title: `${entity}保存失败`,
      detail: error instanceof Error ? error.message : String(error),
    }
  }
}

export function useSaveCamera(cameraId: string) {
  return useSave<CameraUpdate, unknown>({
    mutationFn: (body) => updateCamera(cameraId, body),
    invalidates: [CAMS.list(false), CAMS.list(true), CAMS.detail(cameraId)],
    success: () => ({ title: "机位已更新" }),
    failure: partialFailure("机位"),
  })
}

export function useSetCameraEnabled(cameraId: string) {
  const enable = useSave<void, unknown>({
    mutationFn: () => enableCamera(cameraId),
    invalidates: [CAMS.list(false), CAMS.list(true), CAMS.detail(cameraId)],
    success: () => ({ title: "已启用" }),
    failure: partialFailure("启用"),
  })
  const disable = useSave<void, unknown>({
    mutationFn: () => disableCamera(cameraId),
    invalidates: [CAMS.list(false), CAMS.list(true), CAMS.detail(cameraId)],
    success: () => ({ title: "已停用" }),
    failure: partialFailure("停用"),
  })
  return {
    enable: () => enable.mutate(undefined),
    disable: () => disable.mutate(undefined),
    isPending: enable.isPending || disable.isPending,
  }
}

export function useRetireCamera(cameraId: string) {
  const retire = useSave<void, unknown>({
    mutationFn: () => retireCamera(cameraId),
    invalidates: [CAMS.list(false), CAMS.list(true), CAMS.detail(cameraId)],
    failure: partialFailure("退役"),
  })
  const restore = useSave<void, unknown>({
    mutationFn: () => restoreCamera(cameraId),
    invalidates: [CAMS.list(false), CAMS.list(true), CAMS.detail(cameraId)],
    // Restoring deliberately does not re-enable the camera: the server keeps
    // `enabled = false` so a retired camera cannot start streaming the moment
    // somebody restores it by accident.
    success: () => ({
      title: "已恢复",
      detail: "机位已回到列表，但仍处于停用状态，需要再点一次「启用」才会开始取流。",
    }),
  })
  return {
    retire: () => retire.mutate(undefined),
    restore: () => restore.mutate(undefined),
    isPending: retire.isPending || restore.isPending,
  }
}

export function useProbeCamera(cameraId: string) {
  return useSave<void, unknown>({
    mutationFn: () => probeCamera(cameraId),
    invalidates: [CAMS.list(false), CAMS.list(true), CAMS.detail(cameraId)],
    success: () => ({ title: "已重新探测" }),
    failure: (error) => ({
      title: "探测失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useSaveStreamBindings(cameraId: string) {
  return useSave<CameraStreamBindingInput[], unknown>({
    mutationFn: (bindings) => replaceStreamBindings(cameraId, bindings),
    invalidates: [CAMS.detail(cameraId)],
    success: () => ({ title: "码流绑定已保存" }),
    failure: partialFailure("码流绑定"),
  })
}
