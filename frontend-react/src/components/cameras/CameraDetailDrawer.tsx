/**
 * 摄像机详情抽屉。
 *
 * 一个通道的四块信息，各自有独立端点与独立刷新节奏，所以是 tab 而不是一张长
 * 表：概览随 `GET /cameras/{id}` 一起来，码流在检测后自己变，健康与时钟各有
 * 自己的投影。
 *
 * **没有实时预览。** Vue 的详情面板有 `LiveCameraTile`，但那是一个独立的播放
 * 栈（会话租约、编解码协商、兼容性回退），在摄像机页里重建一份会立刻产生第二
 * 套真相源。直播仍然只在直播页。
 *
 * 抽屉的键盘与焦点契约全在 `Drawer` 原语里，这里不重复实现。
 */
import { useState } from "react"

import type { CameraDetail } from "../../api/cameras"
import { boundStreamName, STREAM_PURPOSE_LABEL } from "../../api/cameras"
import { Drawer } from "../ui/Drawer"
import { Callout, KeyValue, Mono, Section, Tabs } from "../ui/display"
import { BindingSummary } from "./BindingSummary"
import { CameraEditor } from "./CameraEditor"
import { CameraStreamsPanel } from "./CameraStreamsPanel"
import { CameraHealthPanel } from "./CameraHealthPanel"
import { CameraClockPanel } from "./CameraClockPanel"

const TABS = [
  { key: "overview", label: "概览" },
  { key: "streams", label: "码流" },
  { key: "health", label: "健康" },
  { key: "clock", label: "时钟" },
] as const

const TIME_SYNC_LABEL: Record<string, string> = {
  monitor: "仅监测",
  manage_ntp: "由系统管理设备时间",
  ignore: "忽略设备时间",
}

const FORM_FACTOR_LABEL: Record<string, string> = {
  unknown: "未知",
  bullet: "枪机",
  dome: "半球",
  turret: "筒型",
  ptz: "球机",
  doorbell: "门铃",
  indoor: "室内",
  panoramic: "全景",
}

const ALL_PURPOSES = [
  "RECORD",
  "LIVE_HIGH",
  "LIVE_LOW",
  "AI_DETECT",
  "SNAPSHOT",
  "AUDIO",
] as const

export function CameraDetailDrawer({
  camera,
  onClose,
}: {
  camera: CameraDetail
  onClose: () => void
}) {
  const [tab, setTab] = useState<string>("overview")
  // A new camera means a new subject: keeping the operator on 「健康」 after they
  // move to the next channel would show the previous camera's layers until they
  // noticed. The Vue panel reset per camera and so does this.
  const [seenId, setSeenId] = useState(camera.id)
  if (seenId !== camera.id) {
    setSeenId(camera.id)
    setTab("overview")
  }

  return (
    <Drawer
      open
      onClose={onClose}
      title={camera.name}
      description={
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <BindingSummary camera={camera} />
        </span>
      }
    >
      <div className="px-4 py-3">
        <Tabs tabs={TABS} active={tab} onChange={setTab} />

        <div className="pt-4">
          {tab === "overview" && <Overview camera={camera} />}
          {tab === "streams" && <CameraStreamsPanel camera={camera} />}
          {tab === "health" && (
            <CameraHealthPanel cameraId={camera.id} enabled={camera.enabled} />
          )}
          {tab === "clock" && (
            <CameraClockPanel
              cameraId={camera.id}
              syncMode={camera.time_sync_mode}
            />
          )}
        </div>
      </div>
    </Drawer>
  )
}

function Overview({ camera }: { camera: CameraDetail }) {
  const boundPurposes = new Set(camera.bindings.map((b) => b.purpose))
  // All six purposes, always. A purpose with no binding is a fact about this
  // camera worth seeing — listing only the bound ones would hide the gap that
  // stops recording.
  const unbound = ALL_PURPOSES.filter((purpose) => !boundPurposes.has(purpose))

  return (
    <div className="space-y-5">
      <Section title="设备" description="来自设备记录，通道级字段不可编辑。">
        <div className="rounded-lg border border-border px-3 py-1">
          <KeyValue label="接入方式">
            {camera.adapter_type ?? "未绑定设备"}
          </KeyValue>
          <KeyValue label="厂商 / 型号">
            {[camera.manufacturer, camera.model].filter(Boolean).join(" / ") ||
              "设备未提供"}
          </KeyValue>
          <KeyValue label="外形">
            {FORM_FACTOR_LABEL[camera.form_factor] ?? camera.form_factor}
          </KeyValue>
          <KeyValue label="位置">{camera.location ?? "未填写"}</KeyValue>
          <KeyValue label="存储标签">
            {camera.storage_label ?? "未填写"}
          </KeyValue>
          <KeyValue label="时钟同步">
            {TIME_SYNC_LABEL[camera.time_sync_mode] ?? camera.time_sync_mode}
          </KeyValue>
        </div>
      </Section>

      <Section title="分辨率" description="取自已记录的码流 profile。">
        {camera.width && camera.height ? (
          <Mono>
            {`${camera.width}×${camera.height} · ${Math.round(
              camera.fps ?? 0,
            )}fps · ${camera.video_codec ?? "编码未知"}`}
          </Mono>
        ) : (
          <p className="text-xs text-muted-foreground">
            还没有任何码流记录。到「码流」页检测一次即可补齐。
          </p>
        )}
      </Section>

      <Section title="码流用途绑定">
        {camera.bindings.length > 0 ? (
          <ul className="space-y-1 text-xs">
            {camera.bindings.map((binding) => (
              <li
                key={binding.purpose}
                className="flex items-center justify-between gap-2"
              >
                <span>{STREAM_PURPOSE_LABEL[binding.purpose]}</span>
                <span className="truncate text-muted-foreground">
                  {boundStreamName(camera.streams, binding)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            还没有任何用途绑定。未绑定录制用途的通道不会录像。
          </p>
        )}
        {unbound.length > 0 && (
          <Callout tone="degraded" title={`${unbound.length} 个用途未绑定`}>
            {`未绑定：${unbound
              .map((purpose) => STREAM_PURPOSE_LABEL[purpose])
              .join("、")}。到「码流」页可以调整。`}
          </Callout>
        )}
      </Section>

      {/* The edit form lives here rather than in a panel beside the table: a
          channel's name and its stream bindings are one subject, and two places
          to change it is how they drift apart. */}
      <Section title="编辑">
        <CameraEditor camera={camera} />
      </Section>
    </div>
  )
}
