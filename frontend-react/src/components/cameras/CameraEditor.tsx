import { useEffect, useMemo, useState } from "react"

import type {
  CameraDetail,
  TimeSyncMode,
} from "../../api/cameras"
import { Button, Input, Select } from "../ui/primitives"
import { Callout } from "../ui/display"
import {
  allowedTimeSyncModes,
  validateCameraForm,
  type FieldError,
} from "../../lib/cameraValidation"
import { useSaveCamera } from "../../lib/cameraMutations"
import { boundStreamName, STREAM_PURPOSE_LABEL } from "../../api/cameras"

/**
 * Editing one camera.
 *
 * Two fields are deliberately absent or conditional, and both because the
 * backend would take the value and then throw it away:
 *
 * - **RTSP address is not editable.** `CameraUpdate` has no stream fields at
 *   all; changing a camera's source means recreating it. Showing a field that
 *   cannot be saved is worse than not showing it.
 * - **Manufacturer / model / form factor are never offered.** They are written
 *   to the *device*, not the camera (`cameras/service.py:437-448`). With no
 *   device the backend drops them and returns 200; on a multi-channel NVR the
 *   write succeeds and changes every channel at once while the audit records one
 *   camera. Both outcomes are wrong enough that the honest move is to not offer
 *   the inputs. ADR-0015 moves them to the channel, which is the real fix.
 *
 * Time sync is offered only for adapters the server can actually manage.
 *
 * ## Chrome-free on purpose
 *
 * This renders a form and nothing else — no panel, no header, no footer. The
 * drawer owns all of that, so a channel has exactly one surface: its facts, its
 * edit form, and its stream / health / clock tabs. Two panels for one camera is
 * how a name gets edited in one place and a binding in another.
 */

const TIME_SYNC_LABEL: Record<TimeSyncMode, string> = {
  manage_ntp: "由服务器托管 NTP",
  monitor: "仅监测时钟偏差",
  ignore: "不处理",
}

export interface CameraEditorProps {
  camera: CameraDetail
}

export function CameraEditor({ camera }: CameraEditorProps) {
  const [name, setName] = useState(camera.name)
  const [location, setLocation] = useState(camera.location ?? "")
  const [storageLabel, setStorageLabel] = useState(camera.storage_label ?? "")
  const [timeSyncMode, setTimeSyncMode] = useState<TimeSyncMode>(
    camera.time_sync_mode ?? "ignore",
  )
  const [maintenance, setMaintenance] = useState(camera.maintenance)

  // Re-seed when a different camera is selected without remounting.
  useEffect(() => {
    setName(camera.name)
    setLocation(camera.location ?? "")
    setStorageLabel(camera.storage_label ?? "")
    setTimeSyncMode(camera.time_sync_mode ?? "ignore")
    setMaintenance(camera.maintenance)
  }, [camera])

  const save = useSaveCamera(camera.id)

  const syncModes = useMemo(
    () => allowedTimeSyncModes(camera.adapter_type),
    [camera.adapter_type],
  )
  const errors: FieldError[] = useMemo(
    () =>
      validateCameraForm({
        name,
        adapterType: camera.adapter_type,
        timeSyncMode,
        isCreate: false,
      }),
    [name, camera.adapter_type, timeSyncMode],
  )
  const errorFor = (field: string) =>
    errors.find((error) => error.field === field)?.message ?? null

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (errors.length) return
    save.mutate({
      name: name.trim(),
      // `exclude_unset` means an explicit null clears the field, which is the
      // only way to remove a location.
      location: location.trim() === "" ? null : location.trim(),
      storage_label: storageLabel.trim() === "" ? null : storageLabel.trim(),
      time_sync_mode: timeSyncMode,
      maintenance,
    })
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-1.5">
          <label htmlFor="camera-name" className="text-xs font-medium">
            名称
          </label>
          <Input
            id="camera-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={Boolean(errorFor("name"))}
          />
          {errorFor("name") ? (
            <p className="text-xs text-status-offline">{errorFor("name")}</p>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="camera-location" className="text-xs font-medium">
            位置
          </label>
          <Input
            id="camera-location"
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            placeholder="留空以清除"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="camera-storage" className="text-xs font-medium">
            存储标签
          </label>
          <Input
            id="camera-storage"
            value={storageLabel}
            onChange={(event) => setStorageLabel(event.target.value)}
            placeholder="留空以清除"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="camera-sync" className="text-xs font-medium">
            时钟同步
          </label>
          <Select
            id="camera-sync"
            value={timeSyncMode}
            onChange={(event) =>
              setTimeSyncMode(event.target.value as TimeSyncMode)
            }
          >
            {syncModes.map((mode) => (
              <option key={mode} value={mode}>
                {TIME_SYNC_LABEL[mode]}
              </option>
            ))}
          </Select>
          {errorFor("time_sync_mode") ? (
            <p className="text-xs text-status-offline">
              {errorFor("time_sync_mode")}
            </p>
          ) : null}
        </div>

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={maintenance}
            onChange={(event) => setMaintenance(event.target.checked)}
          />
          维护模式（暂停取流但保留配置）
        </label>

        {camera.retired_at ? (
          <Callout tone="degraded" title="这条通道已退役">
            退役会把通道从列表里摘下并停止取流，<strong>但绑定、录制计划、录像保护
            与分组全部保留</strong>，恢复后原样回来。它不会解开背后的设备，
            恢复后仍是同一台。恢复后通道仍为停用状态，需要再启用一次才会开始取流。
          </Callout>
        ) : null}

        <Callout tone="degraded" title="换不掉背后的设备">
          <code>PATCH /cameras/:id</code> 不接受码流与凭据字段，而
          <code> PUT /cameras/:id/binding</code> 还不存在。所以今天要换设备只能
          新建一条通道再把旧的退役掉——通道号、计划与保护都带不过去。
          <strong>ADR-0015</strong> 记录了通道与绑定分离的完整方案。
        </Callout>

        <Callout tone="degraded" title="厂商与型号无法编辑">
          这三个字段写在<strong>设备</strong>上，不在机位上（
          <code>cameras/service.py:437-448</code>）。两种结果都不是我们想要的：
          机位没有关联设备时后端静默丢弃并返回 <code>200</code>；而多通道 NVR 的
          几个机位共用一台设备时，写入会<strong>同时改掉同一设备的所有通道</strong>，
          审计里却只记成这一个机位变了。所以这里不提供输入框。
        </Callout>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button
            type="submit"
            size="sm"
            disabled={save.isPending || errors.length > 0}
          >
            {save.isPending ? "保存中…" : "保存机位信息"}
          </Button>
        </div>
    </form>
  )
}
