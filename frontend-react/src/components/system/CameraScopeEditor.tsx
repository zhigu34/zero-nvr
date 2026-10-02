/**
 * The camera-scope editor, shared by users and roles.
 *
 * A scope is four-state plus two id lists (`auth/schemas.py:88-99`), and both
 * the user and the role endpoint take exactly the same body
 * (`auth/admin_api.py:406, 488`). The Vue implementation had this logic once
 * per owner type; here it is one component, so a fix to the `inherit` / `all`
 * list-clearing rule cannot land on one owner type and miss the other.
 *
 * ## Why the list is cleared for `inherit` and `all`
 *
 * `inherit` and `all` carry no id list. Sending a stale selection alongside
 * them would store ids the scope never reads, and a later switch to `selected`
 * would resurrect a selection nobody made in this session.
 *
 * ## Why it is its own save
 *
 * A scope and whatever else the page edits (a user profile, a role's permission
 * set) are separate resources with separate endpoints. They can succeed
 * independently, so they get separate buttons and this component reports
 * "范围未保存" on its own.
 */
import { useEffect, useMemo, useState } from "react"

import {
  CAMERA_SCOPE_HINT,
  CAMERA_SCOPE_LABEL,
  type CameraScopeMode,
  type CameraScopeUpdate,
  type CameraScopeView,
} from "../../api/users"
import type { CameraGroupView } from "../../api/cameraGroups"
import type { CameraSummary } from "../../api/cameras"
import { Button } from "../ui/primitives"
import { Checkbox, Segmented } from "../ui/display"

const MODES = ["inherit", "all", "selected", "none"] as const

export function CameraScopeEditor({
  scope,
  isPending,
  error,
  cameras,
  groups,
  onSave,
  busy,
  /** "该用户" / "该角色" — the empty-state sentence differs. */
  subject,
}: {
  scope: CameraScopeView | undefined
  isPending: boolean
  error: Error | null
  cameras: CameraSummary[]
  groups: CameraGroupView[]
  onSave: (body: CameraScopeUpdate) => void
  busy: boolean
  subject: string
}) {
  const [mode, setMode] = useState<CameraScopeMode>("inherit")
  const [picked, setPicked] = useState<string[]>([])
  const [pickedGroups, setPickedGroups] = useState<string[]>([])
  // What the form was last seeded from, as a string. Re-seeding on *this* rather
  // than on the owner id means a refetch that returns identical data does not
  // yank the form out from under an operator mid-edit, while a successful save
  // (which changes the payload) does refresh it.
  const [seeded, setSeeded] = useState<string | null>(null)

  const incoming = useMemo(
    () =>
      scope
        ? JSON.stringify([scope.mode, scope.camera_ids, scope.camera_group_ids])
        : null,
    [scope],
  )

  useEffect(() => {
    if (!scope || incoming === null || incoming === seeded) return
    setMode(scope.mode)
    setPicked(scope.camera_ids)
    setPickedGroups(scope.camera_group_ids)
    setSeeded(incoming)
  }, [scope, incoming, seeded])

  const baseline = useMemo(
    () =>
      JSON.stringify([
        scope?.mode,
        scope?.camera_ids,
        scope?.camera_group_ids,
      ]),
    [scope],
  )
  const dirty = incoming !== null && JSON.stringify([mode, picked, pickedGroups]) !== baseline

  const isSelected = mode === "selected"

  if (isPending) {
    return <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
  }
  if (error) {
    return <p className="mt-2 text-xs text-status-offline">{error.message}</p>
  }

  return (
    <>
      <Segmented
        className="mt-2"
        // Four mutually exclusive modes. Without a group name a screen reader
        // announces four unrelated buttons and the "which one is on" question
        // has no answer.
        ariaLabel="机位范围模式"
        value={mode}
        onChange={(v) => setMode(v as CameraScopeMode)}
        options={MODES.map((m) => ({ value: m, label: CAMERA_SCOPE_LABEL[m] }))}
      />
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        {CAMERA_SCOPE_HINT[mode]}
      </p>

      {isSelected && (
        <div className="mt-2 space-y-2">
          {groups.length > 0 && (
            <div className="rounded-md border border-border p-2">
              <p className="mb-1 text-[11px] text-muted-foreground">
                机位组（与下面的机位合并生效）
              </p>
              <div className="max-h-32 space-y-1 overflow-y-auto">
                {groups.map((group) => (
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
                    <span className="min-w-0 flex-1 truncate">{group.name}</span>
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
            {cameras.map((camera) => (
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
                {`两者都不选 = ${subject}看不到任何机位。`}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center justify-end gap-2">
        {dirty && (
          <span className="mr-auto text-[11px] text-status-degraded">
            范围未保存
          </span>
        )}
        <Button
          size="sm"
          disabled={!dirty || busy}
          onClick={() =>
            onSave({
              mode,
              camera_ids: isSelected ? picked : [],
              camera_group_ids: isSelected ? pickedGroups : [],
            })
          }
        >
          {busy ? "保存中…" : "保存范围"}
        </Button>
      </div>
    </>
  )
}
