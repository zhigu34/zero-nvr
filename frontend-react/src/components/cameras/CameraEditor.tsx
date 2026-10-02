import { useEffect, useMemo, useState } from "react"
import { X } from "lucide-react"

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
import { STREAM_PURPOSE_LABEL } from "../../api/cameras"

/**
 * Editing one camera.
 *
 * Two fields are deliberately absent or conditional, and both because the
 * backend would take the value and then throw it away:
 *
 * - **RTSP address is not editable.** `CameraUpdate` has no stream fields at
 *   all; changing a camera's source means recreating it. Showing a field that
 *   cannot be saved is worse than not showing it.
 * - **Manufacturer / model / form factor are hidden** unless the camera has a
 *   `device_id`. With no device the backend drops them silently and returns
 *   200, so the values would vanish on the next reload with no trace
 *   (`cameras/service.py:438`).
 *
 * Time sync is offered only for adapters the server can actually manage.
 */

const TIME_SYNC_LABEL: Record<TimeSyncMode, string> = {
  manage_ntp: "由服务器托管 NTP",
  monitor: "仅监测时钟偏差",
  ignore: "不处理",
}

export interface CameraEditorProps {
  camera: CameraDetail
  onClose: () => void
}

export function CameraEditor({ camera, onClose }: CameraEditorProps) {
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
    <aside className="flex h-full w-full flex-col border-l border-border bg-card">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium">编辑机位</h2>
          <p className="truncate text-xs text-muted-foreground">
            {camera.name} · {camera.adapter_type ?? "未知接入"}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭">
          <X className="h-4 w-4" />
        </Button>
      </header>

      <form className="flex-1 space-y-4 overflow-auto p-4" onSubmit={submit}>
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

        {camera.bindings?.length ? (
          <div className="space-y-1.5">
            <p className="text-xs font-medium">当前码流用途绑定</p>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {camera.bindings.map((binding) => (
                <li key={binding.purpose} className="flex justify-between">
                  <span>
                    {STREAM_PURPOSE_LABEL[binding.purpose] ?? binding.purpose}
                  </span>
                  <span>
                    {binding.stream_profile_id
                      ? binding.selection_mode === "auto"
                        ? "自动"
                        : "手动"
                      : "未绑定"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </form>

      <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
        <Button variant="outline" size="sm" onClick={onClose}>
          取消
        </Button>
        <Button size="sm" onClick={submit} disabled={save.isPending || errors.length > 0}>
          {save.isPending ? "保存中…" : "保存"}
        </Button>
      </footer>
    </aside>
  )
}
