import * as React from "react"

import { useRecordingPolicies } from "../../lib/queries"
import {
  BASELINE_MODE_LABEL,
  DESIRED_MODE_LABEL,
  describeBlocker,
  formatSeconds,
  judgeRuntime,
  runtimeTone,
} from "../../lib/recordingRuntime"
import { formatClock } from "../../lib/format"
import { Card, CardContent, CardHeader, CardTitle } from "../ui/primitives"
import { Callout, KeyValue, Section, StatusDot } from "../ui/display"

/**
 * 回放诊断。
 *
 * ## There is no diagnostics endpoint
 *
 * Nothing under `backend/app` serves `/diagnostics`, an `/api/v1/health` for a
 * camera, or `/metrics` — the old Vue panel was 100% client-side, reading the
 * `HTMLMediaElement` it happened to share a page with. So this panel is built
 * the same way, plus one honest enrichment: the recording-policy runtime, which
 * is the only place the server states anything about what the camera is doing.
 *
 * The consequence is worth stating to the operator rather than hiding: the
 * numbers below describe *this browser tab's* media element. They say nothing
 * about server load, disk, or another operator's session, because the contract
 * has no way to say it.
 *
 * ## `null` is a third value, not a `false`
 *
 * `RecordingRuntime.stream_online` and `.recording` are `boolean | null`, and
 * null means the media runtime could not be observed at all
 * (`api/recordingPolicies.ts:33-44`). Drawing that as "离线" or "未在录制" sends
 * the operator after a fault that may not exist, so each gets its own
 * "无法观测" branch. `blockers` is a `string[]` of free-form backend codes, so
 * every entry is rendered and an unrecognised one falls through as itself —
 * `describeBlocker` keeps the raw code in the text for exactly that reason.
 *
 * ## Drift is reported as unavailable, not guessed
 *
 * `MasterPlaybackClock` is constructed inside `useMasterClock` and kept in a
 * ref (`hooks/useMasterClock.ts:28-32`); there is no store and no context
 * publishing it. A panel that receives only `cameraId` therefore cannot compare
 * the media element against the playhead, and a fabricated number here would be
 * worse than an honest gap — so the row says it cannot be read and why.
 */

export interface PlaybackDiagnosticsPanelProps {
  cameraId: string
}

const READY_STATE_LABEL: Record<number, string> = {
  0: "无数据",
  1: "仅有元数据",
  2: "有当前帧",
  3: "可播放",
  4: "缓冲充足",
}

/** Mirrors `TileSyncState` in `playback/sync.ts`; unknown states pass through. */
const RESOLVER_STATE_LABEL: Record<string, string> = {
  resolving: "正在解析播放地址",
  pending: "正在从远端归档回源",
  ready: "就绪",
  buffering: "缓冲中",
  gap: "该时段没有录像",
  unavailable: "播放失败",
}

interface MediaSnapshot {
  found: boolean
  readyState: number
  paused: boolean
  seeking: boolean
  playbackRate: number
  currentTimeSeconds: number
  buffered: { start: number; end: number }[]
  bufferedReadable: boolean
  resolverState: string | null
}

const MEDIA_EVENTS = [
  "loadstart",
  "loadedmetadata",
  "durationchange",
  "canplay",
  "canplaythrough",
  "playing",
  "play",
  "pause",
  "seeking",
  "seeked",
  "ratechange",
  "timeupdate",
  "progress",
  "waiting",
  "stalled",
  "suspend",
  "emptied",
  "ended",
  "error",
] as const

/**
 * The stage's own media element.
 *
 * Located by the `data-stage-state` marker `PlaybackStage` puts on its wrapper
 * rather than by a prop, because the panel is a sibling of the stage and the
 * contract offers no channel between them. In a multi-camera grid this reads
 * the first stage only — the Vue version had a per-tile `syncTileStates` map
 * from its page, and there is no equivalent registry to read here.
 */
function findMediaElement(): HTMLVideoElement | null {
  if (typeof document === "undefined") return null
  return (
    document.querySelector<HTMLVideoElement>("[data-stage-state] video") ??
    document.querySelector<HTMLVideoElement>("video")
  )
}

function readSnapshot(): MediaSnapshot {
  const element = findMediaElement()
  if (!element) {
    return {
      found: false,
      readyState: 0,
      paused: true,
      seeking: false,
      playbackRate: 1,
      currentTimeSeconds: 0,
      buffered: [],
      bufferedReadable: false,
      resolverState:
        document
          .querySelector("[data-stage-state]")
          ?.getAttribute("data-stage-state") ?? null,
    }
  }

  // `buffered` is a live TimeRanges. jsdom ships a stub with `length === 0`,
  // and a browser throws from `start()` if the ranges mutate mid-read, so the
  // read is guarded rather than assumed.
  const ranges: { start: number; end: number }[] = []
  let bufferedReadable = false
  try {
    const timeRanges = element.buffered
    if (timeRanges && typeof timeRanges.length === "number") {
      bufferedReadable = typeof timeRanges.start === "function"
      for (let index = 0; index < timeRanges.length; index += 1) {
        ranges.push({
          start: timeRanges.start(index),
          end: timeRanges.end(index),
        })
      }
    }
  } catch {
    ranges.length = 0
  }

  return {
    found: true,
    readyState: element.readyState,
    paused: element.paused,
    seeking: element.seeking,
    playbackRate: element.playbackRate,
    currentTimeSeconds: element.currentTime,
    buffered: ranges,
    bufferedReadable,
    resolverState:
      element
        .closest("[data-stage-state]")
        ?.getAttribute("data-stage-state") ?? null,
  }
}

function useMediaSnapshot(): MediaSnapshot {
  const [snapshot, setSnapshot] = React.useState<MediaSnapshot>(readSnapshot)

  React.useEffect(() => {
    let element = findMediaElement()
    const refresh = () => setSnapshot(readSnapshot())

    const bind = () => {
      element = findMediaElement()
      if (!element) return
      for (const name of MEDIA_EVENTS) {
        element.addEventListener(name, refresh)
      }
    }
    const unbind = (target: HTMLVideoElement | null) => {
      if (!target) return
      for (const name of MEDIA_EVENTS) {
        target.removeEventListener(name, refresh)
      }
    }

    bind()
    // Read once after mount as well: the first `useState(readSnapshot)` runs
    // during render, before the stage's element is in the document, so without
    // this the panel would claim there is no media element until the first
    // media event happens to fire.
    refresh()
    // The stage resolves its media asynchronously, so the element can also
    // appear (or be replaced) long after this panel mounted.
    const observer = new MutationObserver(() => {
      const next = findMediaElement()
      if (next === element) return
      unbind(element)
      bind()
      refresh()
    })
    observer.observe(document.body, { childList: true, subtree: true })

    return () => {
      observer.disconnect()
      unbind(element)
    }
  }, [])

  return snapshot
}

export function PlaybackDiagnosticsPanel({ cameraId }: PlaybackDiagnosticsPanelProps) {
  const media = useMediaSnapshot()
  const { data: policies, isPending: policiesPending } = useRecordingPolicies()
  const policy = policies?.find((item) => item.camera_id === cameraId) ?? null
  const runtime = policy?.runtime ?? null

  return (
    <Card data-testid="playback-diagnostics-panel">
      <CardHeader>
        <CardTitle>回放诊断</CardTitle>
        <span className="text-xs text-muted-foreground">{cameraId}</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <Callout tone="unknown" title="这里没有诊断接口">
          后端没有提供 /diagnostics 或按机位的健康接口。下面的「媒体元素」全部读自
          当前页面里的那个 video 元素，只反映这个标签页的播放器状态；
          「录制运行时」是唯一来自服务端的信号。任何关于服务器负载、磁盘或连接数的数字，
          当前契约都拿不到。
        </Callout>

        <Section title="媒体元素（本页面）" description="来自 HTMLMediaElement，没有网络请求。">
          {media.found ? (
            <dl className="divide-y divide-border">
              <KeyValue label="就绪状态">
                {`${
                  READY_STATE_LABEL[media.readyState] ?? String(media.readyState)
                }（${media.readyState}）`}
              </KeyValue>
              <KeyValue label="当前时间">
                {media.currentTimeSeconds.toFixed(3)} 秒
              </KeyValue>
              <KeyValue label="播放时钟偏差">无法读取</KeyValue>
              <KeyValue label="播放速率">{media.playbackRate.toFixed(3)}x</KeyValue>
              <KeyValue label="暂停">{media.paused ? "是" : "否"}</KeyValue>
              <KeyValue label="定位中">{media.seeking ? "是" : "否"}</KeyValue>
              <KeyValue label="缓冲">
                {media.buffered.length === 0
                  ? "暂无缓冲"
                  : `${media.buffered.length} 段，共 ${formatSeconds(
                      media.buffered.reduce((sum, r) => sum + (r.end - r.start), 0),
                    )}`}
              </KeyValue>
              <KeyValue label="解析器状态">
                {media.resolverState === null
                  ? "—"
                  : (RESOLVER_STATE_LABEL[media.resolverState] ?? media.resolverState)}
              </KeyValue>
            </dl>
          ) : (
            <p className="text-xs text-muted-foreground">
              当前页面没有找到媒体元素，播放器可能还没有解析出地址。
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            播放时钟保存在页面组件内部的 ref 里（hooks/useMasterClock.ts:28-32），
            没有 store 或 context 对外发布，所以本面板拿不到播放头，也就无法计算真实偏差。
          </p>
        </Section>

        <Section title="录制运行时（服务端）" description="来自该机位的录制策略响应。">
          {policiesPending ? (
            <p className="text-xs text-muted-foreground">正在读取录制策略…</p>
          ) : policy === null ? (
            // A camera with no policy row is a normal state, not a gap: the
            // list endpoint only returns cameras that have one.
            <p className="text-xs text-muted-foreground">
              该机位没有配置录制策略，因此没有运行时状态。
            </p>
          ) : (
            <>
              {(() => {
                const verdict = judgeRuntime(
                  runtime,
                  policy.baseline_mode,
                  policy.enabled,
                )
                return (
                  <div className="mb-2 flex items-center gap-2">
                    <StatusDot tone={runtimeTone(verdict.health)} />
                    <span className="text-sm">{verdict.message}</span>
                  </div>
                )
              })()}

              <dl className="divide-y divide-border">
                <KeyValue label="基础模式">
                  {BASELINE_MODE_LABEL[policy.baseline_mode] ?? policy.baseline_mode}
                </KeyValue>
                <KeyValue label="码流在线">
                  {observableLabel(runtime?.stream_online ?? null, {
                    true: "在线",
                    false: "离线",
                  })}
                </KeyValue>
                <KeyValue label="录制状态">
                  {observableLabel(runtime?.recording ?? null, {
                    true: "正在录制",
                    false: "未在录制",
                  })}
                </KeyValue>
                <KeyValue label="期望模式">
                  {runtime
                    ? (DESIRED_MODE_LABEL[runtime.desired_mode] ?? runtime.desired_mode)
                    : "—"}
                </KeyValue>
                <KeyValue label="观测时间">
                  {runtime ? formatClock(runtime.observed_at) : "尚未观测"}
                </KeyValue>
              </dl>

              <div className="mt-3">
                <h4 className="text-sm font-medium">阻塞原因</h4>
                {runtime === null || runtime.blockers.length === 0 ? (
                  <p className="mt-1 text-xs text-muted-foreground">没有阻塞项。</p>
                ) : (
                  <ul aria-label="阻塞原因列表" className="mt-1 flex flex-col gap-1">
                    {runtime.blockers.map((code) => (
                      <li key={code} className="text-xs">
                        {/* Free-form backend codes. `describeBlocker` keeps the
                            raw code in the text when it has no translation, so
                            an unfamiliar code stays searchable. */}
                        {describeBlocker(code)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </Section>
      </CardContent>
    </Card>
  )
}

/**
 * The three-way answer, kept as one function so `null` cannot be rendered as
 * `false` in one row and as "无法观测" in another. `undefined` — no runtime at
 * all — is collapsed into the same "not observable" branch deliberately: with
 * no runtime there is nothing to observe either way.
 */
function observableLabel(
  value: boolean | null,
  labels: { true: string; false: string },
): string {
  if (value === null) return "无法观测"
  return value ? labels.true : labels.false
}
