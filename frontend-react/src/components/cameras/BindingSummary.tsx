/**
 * 通道当前绑定的摘要。
 *
 * ADR-0015 把「通道」定义为系统拥有的稳定槽位，「摄像头」是绑在槽位上可替换的
 * 东西。`channel_no` 落地之前前端能做的、最有价值的一件事，就是把**槽位背后现在
 * 绑着什么**如实摆出来——这样「槽位」与「绑定」的区别在界面上先立起来。
 *
 * 三种状态必须分开，不能糊成一种：
 *
 * 1. **未绑定**：`adapter_type` 为 `null`。`Camera.device_id` 允许为 `null`
 *    （`cameras/models.py:220-224`），这是「槽位在、设备不在」。
 * 2. **已绑定**：有接入类型，也有地址。
 * 3. **绑定信息不全**：有 `adapter_type` 但没有 `ip`。设备行存在却没有启用的
 *    endpoint 时就是这个样子（`cameras/api.py:272-276` 只在遍历到 enabled
 *    endpoint 时才填 `ip`）。这种情况必须说清楚，不能显示成「未绑定」——
 *    那会把一个可修的配置问题说成一个设计状态。
 *
 * 刻意不画的：
 *
 * - **通道号**。用列表序号冒充通道号会在改名或排序变化时漂移，而「不变」正是
 *   ADR-0015 第 1 条的前提。在 `channel_no` 真的存在之前，这里宁可空着。
 * - **密码与用户名**。契约里没有回读路径（只写秘密），画了也只能是假的。
 */
import type { CameraSummary } from "../../api/cameras"
import { Badge } from "../ui/primitives"

const ADAPTER_LABEL: Record<string, string> = {
  onvif: "ONVIF",
  manual_rtsp: "手动 RTSP",
}

/** Unknown adapter types render verbatim rather than collapsing to a dash. */
export function adapterLabel(adapterType: string | null): string {
  if (!adapterType) return "未绑定"
  return ADAPTER_LABEL[adapterType] ?? adapterType
}

/**
 * `host:port` for the first enabled endpoint, or `null` when there is none.
 *
 * `port` is defaulted to 554 by the backend alongside `ip`
 * (`cameras/api.py:274-276`), so a set `ip` always has a set `port`. The `?? 554`
 * is belt-and-braces for a cached value from an older build, not a second source
 * of truth.
 */
export function bindingAddress(camera: {
  ip: string | null
  port: number | null
}): string | null {
  if (!camera.ip) return null
  return `${camera.ip}:${camera.port ?? 554}`
}

/** The endpoint paths, main first. Paths only — the host is on the line above. */
function bindingPaths(camera: CameraSummary): string[] {
  const paths = [camera.rtsp_path, camera.sub_rtsp_path].filter(
    (path): path is string => typeof path === "string" && path !== "",
  )
  // A device with two identical paths is one endpoint, not two. The backend
  // already guards this (`cameras/api.py:280`), and so does the type, but the
  // list is rendered directly so a duplicate would be visible.
  return [...new Set(paths)]
}

export function BindingSummary({ camera }: { camera: CameraSummary }) {
  if (!camera.adapter_type) {
    return (
      <div className="min-w-0">
        <Badge variant="outline">未绑定</Badge>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          通道存在，没有设备
        </p>
      </div>
    )
  }

  const address = bindingAddress(camera)
  const paths = bindingPaths(camera)

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-1">
        <Badge variant="secondary">{adapterLabel(camera.adapter_type)}</Badge>
        {address ? (
          <span className="truncate font-mono text-[11px] tabular-nums text-muted-foreground">
            {address}
          </span>
        ) : (
          <span className="text-[11px] text-status-degraded">无启用的地址</span>
        )}
      </div>
      {paths.length > 0 && (
        <p
          className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground"
          title={paths.join(" · ")}
        >
          {paths.join(" · ")}
        </p>
      )}
      {!address && (
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          设备记录存在，但没有启用的接入地址
        </p>
      )}
    </div>
  )
}
