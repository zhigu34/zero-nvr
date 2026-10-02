import { useEffect, useMemo, useState } from "react"

import {
  bindingSelectionMode,
  STREAM_PURPOSE_LABEL,
  STREAM_STATUS_LABEL,
  boundStreamName,
  type CameraDetail,
  type CameraProbeTrack,
  type CameraStreamBinding,
  type CameraStreamBindingInput,
  type CameraStreamDiagnostic,
  type CameraStreamProfile,
  type StreamPurpose,
} from "../../api/cameras"
import { useSaveStreamBindings, useVerifyStream } from "../../lib/cameraMutations"
import { formatClock } from "../../lib/format"
import { Callout, EmptyState, Section, StatusLabel, type HealthTone } from "../ui/display"
import { Button, Select } from "../ui/primitives"

/**
 * 码流配置与用途绑定。
 *
 * 这个面板替 Vue 版 `CameraDetailStreamsTab.vue` 修掉三件事，每一件都是因为旧
 * 实现**看起来是成功的**：
 *
 * 1. **检测结果被丢掉了。** 旧面板调完 verify 就显示一句写死的「已更新最新状态与
 *    分辨率」（`CameraDetailStreamsTab.vue:199`），而响应里带的是媒体通路真正读到
 *    的轨道数据。那是检测唯一的产出，丢掉它之后「检测」按钮和「刷新」按钮对操作
 *    员没有区别。
 * 2. **`selection_mode` 被硬编码成 `manual`**（`CameraDetailStreamsTab.vue:96-120`）。
 *    导入期建的 `auto` 绑定，会在操作员第一次保存**任意**用途时被静默改写。选择权
 *    是服务端的决定，这个表单不拥有它，所以原样回传。
 * 3. **保存是整体替换，不是合并。** `cameras/service.py:569-583` 先删光这一台
 *    通道的绑定行再按 payload 重建，所以只提交改动的那一条会把其余用途全部解绑。
 *    提交的是完整目标集合。
 *
 * 不画的东西：契约里没有的列一律不补占位。特别是 profile 的编码字段叫
 * `codec`，读 `video_codec` 永远拿到 `undefined`（后者是 `CameraSummary` 上的
 * 字段，`cameras/schemas.py:128`）。
 */

/** 六个用途固定按这个顺序渲染，来源是 `StreamPurpose` 而不是服务端返回的顺序。 */
const PURPOSES = [
  "RECORD",
  "LIVE_HIGH",
  "LIVE_LOW",
  "AI_DETECT",
  "SNAPSHOT",
  "AUDIO",
] as const satisfies readonly StreamPurpose[]

/**
 * 未收录的 `status` 一律按「不对劲」着色。
 *
 * 映射表只覆盖 `available` / `unavailable` / `unknown` 三个已知值
 * （`cameras/schemas.py` 里 verify 与 refresh 写的就是这三个）。后端新增一个
 * 状态时，把它当成「未验证，一切正常」着色就是撒谎，所以未知值走 degraded，
 * 文字仍然原样透传。
 */
const STATUS_TONE: Record<string, HealthTone> = {
  available: "online",
  unavailable: "offline",
  unknown: "unknown",
}

function statusTone(status: string): HealthTone {
  return STATUS_TONE[status] ?? "degraded"
}

/**
 * 一行描述：编码、分辨率、帧率、码率、音频。
 *
 * 编码读 `codec`。`CameraStreamProfile` 上的字段就叫这个名字，而
 * `video_codec` 只存在于 `CameraSummary`（`cameras/schemas.py:128`），读错
 * 名字不会报错，只会永远拿到 `undefined`。
 *
 * 缺字段时用「—」占位而不是跳过：宽高只回一半时画 `1920×1080` 会是编造，画
 * `1920×—` 才是「后端只报了一个数」。整串全空时回退到 `adapter_profile_key`——
 * 那是从设备侧来的稳定标识，比一个空白行有信息量。
 */
function describeStream(profile: CameraStreamProfile): string {
  const parts: string[] = []
  if (profile.codec) parts.push(profile.codec)
  if (profile.width != null || profile.height != null) {
    parts.push(`${profile.width ?? "—"}×${profile.height ?? "—"}`)
  }
  if (profile.fps != null) parts.push(`${profile.fps}fps`)
  if (profile.bitrate_kbps != null) parts.push(`${profile.bitrate_kbps}kbps`)
  if (profile.audio_codec) parts.push(`音频 ${profile.audio_codec}`)
  else if (profile.has_audio) parts.push("含音频（未报告编码）")
  // `has_audio: false` 不进描述串。绝大多数 profile 是纯视频，写一句「无音频」
  // 只是噪声；而且一旦写进去，整串就永远不会为空，上面那个回退分支就成了死代码。
  return parts.length ? parts.join(" · ") : profile.adapter_profile_key
}

/**
 * 一个用途能选哪些 profile。
 *
 * - `AUDIO` 只列 `has_audio` 的：纯视频的 profile 绑到音频用途上，录制时拿到的是
 *   一条没有声音的轨。
 * - 其它用途排除 `codec === "aac"`：纯音频 profile 当不了视频源。
 *
 * 两条都是业务规则，不是排版偏好——下拉里的每个选项都是一次会真的写进
 * `PUT /stream-bindings` 的选择。
 */
function candidatesFor(
  purpose: StreamPurpose,
  streams: readonly CameraStreamProfile[],
): CameraStreamProfile[] {
  return purpose === "AUDIO"
    ? streams.filter((stream) => stream.has_audio)
    : streams.filter((stream) => stream.codec !== "aac")
}

/** 从服务端状态播种表单；`""` 表示该用途不绑定。 */
function seedSelection(
  bindings: readonly CameraStreamBinding[],
): Record<StreamPurpose, string> {
  const seeded = {} as Record<StreamPurpose, string>
  for (const purpose of PURPOSES) {
    seeded[purpose] =
      bindings.find((binding) => binding.purpose === purpose)?.stream_profile_id ?? ""
  }
  return seeded
}

/**
 * 目标集合 = 当前表单里所有非空的用途。
 *
 * `selection_mode` 由 `bindingSelectionMode` 决定：**操作员动过的用途存 manual，
 * 没动过的原样回传**。判据与理由见 `api/cameras.ts` —— 简版是 `auto` 会让直播
 * 路径每次重新挑码流，操作员的显式选择会被丢弃；而没碰过的用途不该被这个表单
 * 替服务端做主。
 */
function collectBindings(
  selection: Record<StreamPurpose, string>,
  touched: ReadonlySet<StreamPurpose>,
  bindings: readonly CameraStreamBinding[],
): CameraStreamBindingInput[] {
  return PURPOSES.flatMap((purpose) => {
    const streamProfileId = selection[purpose]
    if (!streamProfileId) return []
    const existing = bindings.find((binding) => binding.purpose === purpose)
    return [
      {
        purpose,
        stream_profile_id: streamProfileId,
        selection_mode: bindingSelectionMode(existing, touched.has(purpose)),
      },
    ]
  })
}

/** 轨道有没有被读到，和轨道存不存在是两回事，必须分开说。 */
function trackState(track: CameraProbeTrack | null): { text: string; tone: HealthTone } {
  if (!track) return { text: "没有这条轨道", tone: "unknown" }
  // `ready: false` 是「轨道在、探测读不到」，不是检测成功。把它显示成成功就是
  // 谎报——那正是这类面板最容易骗过操作员的地方。
  if (!track.ready) return { text: "轨道存在，但探测读不到数据", tone: "degraded" }
  return { text: "已读到数据", tone: "online" }
}

function trackMeasurements(track: CameraProbeTrack): string {
  const parts: string[] = []
  if (track.codec) parts.push(track.codec)
  if (track.kind === "video") {
    if (track.width != null || track.height != null) {
      parts.push(`${track.width ?? "—"}×${track.height ?? "—"}`)
    }
    if (track.fps != null) parts.push(`${track.fps}fps`)
    if (track.gop_seconds != null) parts.push(`GOP ${track.gop_seconds}s`)
  } else {
    if (track.sample_rate != null) parts.push(`${track.sample_rate}Hz`)
    if (track.channels != null) parts.push(`${track.channels} 声道`)
  }
  return parts.join(" · ") || "没有可用数据"
}

/**
 * 当前绑定不在候选里时，把它按原样补回下拉。
 *
 * 两种情况都会让原生 select 显示成空白——操作员于是以为这条用途没绑，而保存
 * 仍会把那个 id 发出去：一是编码不再符合该用途（被过滤掉），二是绑定指向一条
 * 已不存在的 profile（`boundStreamName` 对这一种有专门的说法）。所以这里补回
 * 一个带标注的 option，而不是让下拉静默变空。
 */
function orphanOption(
  purpose: StreamPurpose,
  selected: string,
  options: readonly CameraStreamProfile[],
  streams: readonly CameraStreamProfile[],
  bindings: readonly CameraStreamBinding[],
): { id: string; label: string } | null {
  if (selected === "") return null
  if (options.some((option) => option.id === selected)) return null
  const existing = bindings.find((binding) => binding.purpose === purpose)
  return {
    id: selected,
    label: `${boundStreamName(streams, {
      purpose,
      stream_profile_id: selected,
      selection_mode: existing?.selection_mode ?? "manual",
    })}（当前绑定）`,
  }
}

const TRACK_LABEL: Record<CameraProbeTrack["kind"], string> = {
  video: "视频轨道",
  audio: "音频轨道",
}

function DiagnosticTracks({ diagnostic }: { diagnostic: CameraStreamDiagnostic }) {
  return (
    <div className="mt-2 space-y-1.5 rounded-lg border border-border bg-muted/30 px-2.5 py-2">
      <p className="text-[11px] text-muted-foreground">
        检测时间 {formatClock(diagnostic.verified_at)}
      </p>
      <ul className="space-y-1">
        {(["video", "audio"] as const).map((kind) => {
          const track = kind === "video" ? diagnostic.video : diagnostic.audio
          const state = trackState(track)
          return (
            <li key={kind} className="flex flex-wrap items-baseline gap-2 text-xs">
              <span className="w-16 shrink-0 text-muted-foreground">
                {TRACK_LABEL[kind]}
              </span>
              <StatusLabel tone={state.tone}>{state.text}</StatusLabel>
              {track ? (
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  {trackMeasurements(track)}
                </span>
              ) : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function StreamRow({
  profile,
  diagnostic,
  verifying,
  onVerify,
}: {
  profile: CameraStreamProfile
  diagnostic: CameraStreamDiagnostic | undefined
  verifying: boolean
  onVerify: (profileId: string) => void
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{profile.name}</span>
          <StatusLabel tone={statusTone(profile.status)}>
            {STREAM_STATUS_LABEL[profile.status] ?? profile.status}
          </StatusLabel>
          {profile.last_verified_at ? (
            <span className="text-[11px] text-muted-foreground">
              上次检测 {formatClock(profile.last_verified_at)}
            </span>
          ) : null}
        </div>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">
          {describeStream(profile)}
        </p>
        {diagnostic ? <DiagnosticTracks diagnostic={diagnostic} /> : null}
      </div>
      <Button
        variant="outline"
        size="sm"
        // 名字要跟着状态变：aria-label 会盖掉按钮文字，所以只在文字上写
        // 「检测中…」的话，读屏的人只会听到一个变灰的按钮，不知道它在忙什么。
        aria-label={verifying ? `正在检测 ${profile.name}` : `检测 ${profile.name}`}
        disabled={verifying}
        onClick={() => onVerify(profile.id)}
      >
        {verifying ? "检测中…" : "检测"}
      </Button>
    </li>
  )
}

export function CameraStreamsPanel({ camera }: { camera: CameraDetail }) {
  const [selection, setSelection] = useState<Record<StreamPurpose, string>>(() =>
    seedSelection(camera.bindings),
  )
  // 哪些用途被操作员动过。播种时全为 false：表单初始状态不表达任何关于选择权的
  // 意见，所以已有绑定的 mode 必须原样回传。
  const [touched, setTouched] = useState<ReadonlySet<StreamPurpose>>(
    () => new Set(),
  )
  const [diagnostics, setDiagnostics] = useState<Record<string, CameraStreamDiagnostic>>(
    {},
  )

  // 换一台通道就重新播种。保存成功后 mutation 已经 invalidate 了
  // `CAMS.detail`，父组件带着新的 `camera` 回来，这里把表单状态一起换掉——
  // 否则下拉里留着操作员刚点的那一版，而下面的绑定摘要已经显示成服务端的样子。
  useEffect(() => {
    setSelection(seedSelection(camera.bindings))
    setTouched(new Set())
    setDiagnostics({})
  }, [camera])

  const verify = useVerifyStream(camera.id)
  const save = useSaveStreamBindings(camera.id)

  const candidates = useMemo(
    () =>
      Object.fromEntries(
        PURPOSES.map((purpose) => [purpose, candidatesFor(purpose, camera.streams)]),
      ) as Record<StreamPurpose, CameraStreamProfile[]>,
    [camera.streams],
  )

  const onVerify = (profileId: string) => {
    verify.mutate(profileId, {
      onSuccess: (data, verifiedProfileId) => {
        setDiagnostics((previous) => ({ ...previous, [verifiedProfileId]: data }))
      },
    })
  }

  const submit = () => {
    save.mutate(collectBindings(selection, touched, camera.bindings))
  }

  return (
    <div className="space-y-6">
      <Section
        title="可用媒体配置"
        description="检测会真实走一遍媒体通路，并把读到的轨道数据回显在这里。"
      >
        {camera.streams.length === 0 ? (
          <EmptyState
            title="该通道还没有记录任何码流"
            description="先完成设备探测或重新发现码流，才有可供绑定与检测的媒体配置。"
          />
        ) : (
          <ul aria-label="码流配置列表" className="space-y-2">
            {camera.streams.map((profile) => (
              <StreamRow
                key={profile.id}
                profile={profile}
                diagnostic={diagnostics[profile.id]}
                verifying={verify.isPending && verify.variables === profile.id}
                onVerify={onVerify}
              />
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="用途绑定"
        description="每个用途指定一条码流；留空表示该用途不绑定。"
        actions={
          <Button size="sm" disabled={save.isPending} onClick={submit}>
            {save.isPending ? "保存中…" : "保存绑定"}
          </Button>
        }
      >
        <Callout tone="degraded" title="保存是整体替换，不是合并">
          <code>PUT /cameras/:id/stream-bindings</code> 会先删掉这台通道的全部绑定再按
          请求体重建（<code>cameras/service.py:569-583</code>），所以这里每次提交六个
          用途的完整目标集合。任何一个用途没出现在请求里，它就被解绑了。
        </Callout>

        <ul aria-label="用途绑定列表" className="space-y-2">
          {PURPOSES.map((purpose) => {
            const options = candidates[purpose]
            const selected = selection[purpose]
            const orphan = orphanOption(
              purpose,
              selected,
              options,
              camera.streams,
              camera.bindings,
            )

            return (
              <li
                key={purpose}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5"
              >
                <div className="min-w-0">
                  <label
                    htmlFor={`stream-binding-${purpose}`}
                    className="text-sm font-medium"
                  >
                    {STREAM_PURPOSE_LABEL[purpose]}
                  </label>
                  {orphan ? (
                    <p className="mt-0.5 text-[11px] text-status-degraded">
                      {orphan.label} 不在可选范围内，仍会原样提交；换一条可选项即可解除。
                    </p>
                  ) : null}
                </div>
                <div className="w-56 shrink-0">
                  <Select
                    id={`stream-binding-${purpose}`}
                    value={selected}
                    onChange={(event) => {
                      setTouched((previous) => new Set(previous).add(purpose))
                      setSelection((previous) => ({
                        ...previous,
                        [purpose]: event.target.value,
                      }))
                    }}
                  >
                    <option value="">不绑定</option>
                    {options.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.name}
                      </option>
                    ))}
                    {orphan ? (
                      <option value={orphan.id}>{orphan.label}</option>
                    ) : null}
                  </Select>
                </div>
              </li>
            )
          })}
        </ul>

        {camera.bindings.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            这台通道目前没有绑定任何用途。保存后，录像与 AI 检测会因缺少码流而无法工作。
          </p>
        ) : null}
      </Section>
    </div>
  )
}
