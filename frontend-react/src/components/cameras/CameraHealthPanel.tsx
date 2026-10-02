/**
 * 摄像机能力健康面板。
 *
 * 这是**新增能力**，不是 Vue 移植：`GET /cameras/{id}/health` 在整个 Vue 前端零
 * 调用方，所以这里没有可对照的旧行为，只按契约定义。
 *
 * 面板唯一不可让步的一条：**不谎报**。后端的能力健康投影在设计上是诚实的 ——
 * 它只从已存的配置事实推导状态，无法证明实时的媒体/录制运行时健康
 * （`cameras/capability_health.py:45-49`）。因此六个层里有三个（`control` /
 * `ptz` / `clock`）**在投影函数里根本没有 healthy 分支**：
 * `HEALTHY_POSSIBLE_LAYERS` 就是这张名单。
 *
 * 由此推出本组件唯一有存在理由的那段文案：当这三层停在 `unknown` 时，它不是
 * 「正在观察、很快会好」，而是一个**永远不会被消除的状态**。把它们画成灰色
 * 却让操作员以为在等待，等于用一个后端无法产出的承诺骗人。所以这里明写
 * 「该层不采集实时观测」；`media` 的 unknown 不写，因为它确实可能变成正常。
 */
import { useQuery } from "@tanstack/react-query"

import {
  getCameraHealth,
  HEALTH_LAYER_LABEL,
  HEALTH_LAYER_ORDER,
  HEALTH_REASON_LABEL,
  HEALTH_STATE_LABEL,
  HEALTHY_POSSIBLE_LAYERS,
  type CameraCapabilityHealth,
  type CameraHealthLayer,
  type HealthState,
} from "../../api/cameras"
import { cn } from "../../lib/utils"
import { Callout, Section } from "../ui/display"
import { Badge, Button } from "../ui/primitives"

type HealthLayerKey = (typeof HEALTH_LAYER_ORDER)[number]

/**
 * 状态 → 颜色。
 *
 * `HEALTH_STATE_LABEL` 给文案，这里只给颜色，两者分开是因为它们回答不同的问题：
 * 文案是契约里已经翻好的，颜色是这块面板自己的表达。
 *
 * `unknown` 用 `status-unknown`（低饱和的冷灰蓝）而不是 `muted-foreground`，
 * 是因为 `unsupported` / `disabled` 才是真正的「灰」。把「后端还在等观测」和
 * 「这个设备没有这个能力」画成同一个颜色，等于把两件事说成一件事。
 *
 * 导出是为了让颜色可测：类名是这块面板唯一的颜色实现，改了它测试就该红。
 */
export const HEALTH_STATE_COLOR: Record<HealthState, string> = {
  healthy: "text-status-online",
  degraded: "text-status-degraded",
  critical: "text-status-offline",
  unknown: "text-status-unknown",
  unsupported: "text-muted-foreground",
  disabled: "text-muted-foreground",
}

/**
 * 一个 detail 值的可读文本，空值返回 `null`。
 *
 * `details` 是开放字典，键随 reason 变化（`cameras/schemas.py:82-88` 之外没有
 * 任何键名清单），所以这里按值本身的形状处理，不按任何固定键名解构。
 *
 * 返回 `null` 的四种情况都是「这一行不存在」而不是「这一行是空的」：`null`、
 * `undefined`、空数组、空对象。把它们画成「无」或「—」是给操作员看的噪音 ——
 * 一个没有 detail 的层和 detail 为空的层没有区别。
 */
function detailText(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (Array.isArray(value)) {
    const parts = value
      .map(detailText)
      .filter((part): part is string => part !== null)
    return parts.length ? parts.join("、") : null
  }
  if (typeof value === "object") {
    // 嵌套对象展平成 `k=v`，而不是 JSON：details 的键是机器名，JSON 只会把
    // 同一份信息写两遍。
    const parts = Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => {
        const text = detailText(nested)
        return text === null ? null : `${key}=${text}`
      })
      .filter((part): part is string => part !== null)
    return parts.length ? parts.join("，") : null
  }
  if (typeof value === "string") return value.trim() === "" ? null : value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return null
}

/** `reason` 是稳定的机器码；未收录的码原样显示，新的 reason 是信息不是噪音。 */
function reasonText(reason: string | null): string | null {
  if (!reason) return null
  return HEALTH_REASON_LABEL[reason] ?? reason
}

/**
 * 这一层的 `unknown` 是不是「永远不会被消除」的那种。
 *
 * 只看两层事实：现在是 `unknown`，且这个层根本不在 `HEALTHY_POSSIBLE_LAYERS` 里。
 * 不按 reason 名单来判，是因为名单会过期 —— 后端新增一个 `awaiting_*` reason 时，
 * 基于名单的实现会静默地把说明吞掉；而基于名单的**集合**则天然对新增 reason 免疫。
 */
function isUnprovableUnknown(key: HealthLayerKey, layer: CameraHealthLayer): boolean {
  return layer.state === "unknown" && !HEALTHY_POSSIBLE_LAYERS.has(key)
}

function LayerRow({ layerKey, layer }: { layerKey: HealthLayerKey; layer: CameraHealthLayer }) {
  const label = HEALTH_LAYER_LABEL[layerKey]
  const reason = reasonText(layer.reason)
  const details = Object.entries(layer.details)
    .map(([key, value]) => ({ key, text: detailText(value) }))
    .filter((entry): entry is { key: string; text: string } => entry.text !== null)

  return (
    <li
      role="group"
      aria-label={`健康层 ${label}`}
      className="rounded-lg border border-border px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{label}</span>
        <Badge variant="outline" className={cn(HEALTH_STATE_COLOR[layer.state])}>
          {HEALTH_STATE_LABEL[layer.state]}
        </Badge>
        {reason && <span className="text-xs text-muted-foreground">{reason}</span>}
      </div>

      {isUnprovableUnknown(layerKey, layer) && (
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          该层不采集实时观测，永远不会显示为「正常」
        </p>
      )}

      {details.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {details.map((entry) => (
            <li key={entry.key} className="flex items-start gap-2 text-[11px]">
              <span className="shrink-0 font-mono text-muted-foreground">{entry.key}</span>
              <span className="min-w-0 break-words text-muted-foreground">{entry.text}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export function CameraHealthPanel({
  cameraId,
  enabled,
}: {
  cameraId: string
  /** 通道自身的 `Camera.enabled`，**不是** react-query 的开关。 */
  enabled: boolean
}) {
  // 刻意不写进 `lib/queries.tsx`：这个端点目前只有这一个调用方，没有跨组件共享
  // 的失效需求。接线时如果需要按通道统一失效，那里再加 hook。
  //
  // `enabled: Boolean(cameraId)` 只看 id，**不看**上面那个 `enabled` 属性。通道停用
  // 时后端要返回的是「多层 disabled + camera_disabled」（`capability_health.py:74-87`），
  // 那是要如实显示的结果，不是可以不拉的理由 —— 用属性名去关掉查询，会把一个
  // 有意义的读取消成空白面板。
  const health = useQuery({
    queryKey: ["cameras", "health", cameraId],
    queryFn: ({ signal }) => getCameraHealth(cameraId, signal),
    enabled: Boolean(cameraId),
    staleTime: 10_000,
  })

  if (health.isPending) {
    return <p className="text-xs text-muted-foreground">读取中…</p>
  }

  // 失败就是失败。这里绝不退化成「六层全部未知」—— 那会把一次没读到的数据说成
  // 后端说了「不知道」，而这两件事需要做的动作完全不同。
  if (health.isError) {
    return (
      <div className="space-y-3">
        <Callout tone="offline" title="无法读取能力健康">
          <p>{health.error.message}</p>
          <p className="mt-1">
            这一层是读不到，不是「未知」。控制、云台、时钟这三层即使读到了也不会是
            「正常」，但那和这次请求失败是两件事。
          </p>
        </Callout>
        <Button variant="outline" size="sm" onClick={() => health.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  const data: CameraCapabilityHealth | undefined = health.data
  if (!data) return null

  return (
    <Section
      title="能力健康"
      description="六个独立层，全部由已存配置与已记录观测推导。带「未知」的不一定在等待 —— 标记了「不采集实时观测」的层永远不会变成正常。"
    >
      <div className="space-y-3">
        {/* 通道停用不是错误。这里的「已停用」是配置事实，没有需要处理的故障，
            所以用中性语气说明一句，而不是加一条错误横幅。 */}
        {!enabled && (
          <Callout tone="unknown" title="该通道已停用">
            下面的「已停用」是配置事实，不是故障。重新启用通道后这里会重新推导。
          </Callout>
        )}

        <ul className="space-y-2">
          {HEALTH_LAYER_ORDER.map((key) => (
            <LayerRow key={key} layerKey={key} layer={data[key]} />
          ))}
        </ul>
      </div>
    </Section>
  )
}
