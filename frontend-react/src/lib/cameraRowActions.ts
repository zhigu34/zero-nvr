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
 * of these. One instance is enough — **because every action takes the camera id
 * as an argument**. The row buttons stop propagation, so clicking one never
 * changes the selection; binding the mutations to a selected camera made every
 * row action apply to whichever row was open instead of the one clicked.
 */
export function useCameraRowActions() {
  const enabled = useSetCameraEnabled()
  const lifecycle = useRetireCamera()
  const probe = useProbeCamera()

  return useMemo(
    () => ({
      setEnabled: enabled,
      retire: lifecycle,
      probe,
      isPending:
        enabled.isPending || lifecycle.isPending || probe.isPending,
    }),
    [enabled, lifecycle, probe],
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
