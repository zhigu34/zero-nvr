/**
 * 摄像机时钟偏差。
 *
 * Vue 那版在这里犯的错不是「阈值算错了」，而是**把四种完全不同的状态塌缩成了
 * 同一句话**（`CamerasView.vue:481-497`）：它只检查 `offset_ms === null`，然后
 * 拿 `time_sync_mode` 拼一句文案。界面上分不出来的是这四种：
 *
 * 1. **能力缺失**：`health === "unsupported"`。没有 device_id
 *    （`cameras/api.py:1424-1431`），或设备不是 ONVIF（`:1437-1447`）。
 *    一台手动 RTSP 摄像机永远不会有漂移数据——这不是故障，配置改对了也不会有。
 * 2. **主动忽略**：`time_sync_mode === "ignore"`（`cameras/api.py:1449-1456`）。
 *    操作员的选择，不是待办。
 * 3. **尚未测量**：`health === "unknown"` 且没有读数
 *    （`cameras/api.py:1465-1472`，投影缓存里还没有这台设备）。这才是唯一
 *    一种「等一下可能会好」的状态。
 * 4. **有读数**：`offset_ms !== null`。
 *
 * Vue 把第 1 种说成「待测」是最糟的一种：它暗示再等等就有数据，而按定义不会有。
 *
 * ## 第五种：读失败
 *
 * 简报里的四分支没有覆盖这一种，但后端能产生它：测量真的跑了、失败了，存进
 * 投影缓存的是 `health="critical"` 且 `offset_ms=None` 加一个 `error_code`
 * （`system/api.py:1337-1350`、`:1479-1492`、`:1506-1519`）。它是
 * `health` 已知但没有数字，和第 3 种必须分开——把一次失败读数说成「尚未测量」
 * 同样是谎报。
 *
 * ## 为什么只用 `health` 判健康
 *
 * Vue 的判定是 `health === "healthy" || |offset| < 200`（`CamerasView.vue:488-496`），
 * 两个来源互相覆盖：`health` 是 critical 但 offset 小时判「正常」，`health` 是
 * healthy 但 offset 巨大时也判「正常」。这里只信 `health`，因为它是后端拿
 * offset、rtt 与不确定度一起算出来的（`system/api.py:1409-1432`），比前端自己
 * 拿一个阈值猜可靠。`offset_ms` 作为独立的事实照实显示，不参与判定。
 *
 * 判定分支的顺序照抄后端自己的短路顺序（`cameras/api.py:1424-1472`）：`unsupported`
 * 在 `ignore` 之前，所以一台非 ONVIF 且被设为忽略的通道，界面上说「不支持」而不是
 * 「已忽略」——顺序反了就会说错。
 */
import { useQuery } from "@tanstack/react-query"

import {
  getCameraClock,
  type CameraClock,
  type TimeSyncMode,
} from "../../api/cameras"
import { formatClock } from "../../lib/format"
import { Callout, KeyValue, Mono, Section, type HealthTone } from "../ui/display"

/**
 * 前端把 `health` / `quality` / `sync_mode` 声明成了裸 `string`
 * （`api/cameras.ts:104-105`），而后端是 Literal（`cameras/schemas.py:54-71`）。
 * 所以映射表必须允许未登记的值，并且**原样显示**——一个新取值是信息，不是噪音。
 */
const HEALTH_LABEL: Record<string, string> = {
  healthy: "正常",
  warning: "偏差或延迟偏大",
  critical: "严重偏差",
  unknown: "未知",
  unsupported: "不支持",
}

/** `critical` 用 offline（红），`warning` 用 degraded（黄），与系统页一致。 */
const HEALTH_TONE: Record<string, HealthTone> = {
  healthy: "online",
  warning: "degraded",
  critical: "offline",
  unknown: "unknown",
  unsupported: "unknown",
}

const QUALITY_LABEL: Record<string, string> = {
  unknown: "未知",
  good: "良好",
  degraded: "下降",
  poor: "差",
}

type ClockState =
  | "unsupported"
  | "ignored"
  | "unmeasured"
  | "unreadable"
  | "measured"

/**
 * 判据顺序即后端 `get_camera_clock_projection` 的短路顺序（`cameras/api.py:1424-1472`）。
 *
 * `ignore` 用 `syncMode` 这个 prop 而不是响应里的 `sync_mode`：后端在 ignore 分支
 * 显式回写 `"ignore"`（`cameras/api.py:1455`），两者一致，用调用方已经拿在手上的
 * 那个，省一次对响应体的依赖。
 */
function clockState(clock: CameraClock, syncMode: TimeSyncMode): ClockState {
  if (clock.health === "unsupported") return "unsupported"
  if (syncMode === "ignore") return "ignored"
  // 有读数就是有读数，health 另说（`camera_ntp_verify_mode_mismatch` 就是
  // offset 存在、health=critical 的一例，`system/api.py:1409-1414`）。
  if (clock.offset_ms !== null) return "measured"
  // 到这里没有读数。`unknown` 是「还没测」（`cameras/api.py:1465-1472`），
  // 其它取值都来自一次真实但失败的测量，必须说成读失败。
  if (clock.health === "unknown") return "unmeasured"
  return "unreadable"
}

/** 带符号的毫秒数。0 也带 `+`，这是一列有符号的读数，不是绝对值。 */
function signedMs(value: number): string {
  return `${value >= 0 ? "+" : ""}${value} ms`
}

export function CameraClockPanel({
  cameraId,
  syncMode,
}: {
  cameraId: string
  syncMode: TimeSyncMode
}) {
  const query = useQuery({
    queryKey: ["cameras", "clock", cameraId],
    queryFn: ({ signal }) => getCameraClock(cameraId, signal),
    staleTime: 10_000,
  })

  if (query.isPending) {
    return <p className="text-xs text-muted-foreground">读取中…</p>
  }

  if (query.error || !query.data) {
    return (
      <Callout tone="offline" title="无法读取摄像机时钟">
        {query.error?.message ?? "响应为空。"}
      </Callout>
    )
  }

  const clock = query.data
  const state = clockState(clock, syncMode)

  // 「有读数」的分界用 `measured_at` 而不是 `offset_ms`：读失败的那一次同样
  // 有 `measured_at`（`system/api.py:1340`），所以测量时间、设备时区、时间来源
  // 仍然该显示，只是没有偏差数字。unsupported / ignored / unmeasured 三种情况下
  // 后端压根不填这些字段（`cameras/api.py:1425-1431`、`:1450-1456`、`:1466-1472`），
  // 画出来就是一列「—」，不画。
  const hasReading = clock.measured_at !== null

  return (
    <Section
      title="时钟偏差"
      description="设备时钟相对本机时钟的偏差，只反映最近一次读数。"
    >
      {state === "unsupported" && (
        <Callout tone="unknown" title="该设备不支持读取时钟">
          读时钟是 ONVIF 能力，这台设备没有。所以这里永远不会有漂移数据——不是
          坏了，也不用等。
        </Callout>
      )}

      {state === "ignored" && (
        <Callout tone="unknown" title="该通道已设为忽略时钟">
          这是操作员的选择：不再监控这台设备的时钟。没有读数是预期的。
        </Callout>
      )}

      {state === "unmeasured" && (
        <Callout tone="unknown" title="尚未测量">
          还没有采集到这台设备的时钟读数。
        </Callout>
      )}

      {state === "unreadable" && (
        <Callout tone="offline" title="读取设备时钟失败">
          试过了，但这一次没拿到偏差值。原因见下面的错误码。
        </Callout>
      )}

      {state === "measured" && (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums tracking-tight">
              {signedMs(clock.offset_ms as number)}
            </span>
            <span className="text-xs text-muted-foreground">
              正值表示设备时钟比本机快
            </span>
          </div>
          <Callout
            tone={HEALTH_TONE[clock.health] ?? "unknown"}
            title={HEALTH_LABEL[clock.health] ?? clock.health}
          >
            结论来自后端对偏差、往返延迟和不确定度的综合判定，不由这里的数字反推。
          </Callout>
        </>
      )}

      {hasReading && (
        <div>
          <KeyValue label="测量时间">
            <Mono>{formatClock(clock.measured_at)}</Mono>
          </KeyValue>
          <KeyValue label="不确定度">
            <Mono>
              {clock.uncertainty_ms === null ? "—" : `${clock.uncertainty_ms} ms`}
            </Mono>
          </KeyValue>
          <KeyValue label="往返延迟">
            <Mono>{clock.rtt_ms === null ? "—" : `${clock.rtt_ms} ms`}</Mono>
          </KeyValue>
          <KeyValue label="设备时区">
            <Mono>{clock.device_timezone ?? "—"}</Mono>
          </KeyValue>
          <KeyValue label="设备时间来源">
            <Mono>{clock.device_time_source ?? "—"}</Mono>
          </KeyValue>
          <KeyValue label="测量质量">
            {QUALITY_LABEL[clock.quality] ?? clock.quality}
          </KeyValue>
          {/* 只在真有值时出现这一行。没有值时留一行「错误码 —」比不画更糟：
              它会让人以为出错的是没填，而不是这里本来就没发生过。 */}
          {clock.error_code && (
            <KeyValue label="错误码">
              <Mono>{clock.error_code}</Mono>
            </KeyValue>
          )}
        </div>
      )}
    </Section>
  )
}
