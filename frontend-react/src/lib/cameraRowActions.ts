import { useMemo } from "react"

import type { CameraSummary } from "../api/cameras"
import {
  useProbeCamera,
  useRetireCamera,
  useSetCameraEnabled,
} from "./cameraMutations"

/**
 * Per-row write actions for the camera table.
 *
 * Hooks cannot be called conditionally, so a table with N rows cannot mount N
 * of these. One instance keyed on the currently selected camera is enough:
 * the table only ever offers actions for a row the operator has opened.
 */
export function useCameraRowActions(cameraId: string | null) {
  const enabled = useSetCameraEnabled(cameraId ?? "")
  const retired = useRetireCamera(cameraId ?? "")
  const probe = useProbeCamera(cameraId ?? "")

  return useMemo(
    () => ({
      setEnabled: enabled,
      retire: retired,
      probe,
      isPending:
        enabled.isPending || retired.isPending || probe.isPending,
    }),
    [enabled, retired, probe],
  )
}

/** Which action is offered for a row, given its lifecycle state. */
export function rowActionFor(camera: CameraSummary): {
  kind: "enable" | "disable" | "retire" | "restore"
} {
  if (camera.retired_at) return { kind: "restore" }
  return camera.enabled ? { kind: "disable" } : { kind: "enable" }
}

export const ROW_ACTION_LABEL: Record<
  "enable" | "disable" | "retire" | "restore",
  string
> = {
  enable: "启用",
  disable: "停用",
  retire: "退役",
  restore: "恢复",
}
