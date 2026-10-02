import {
  FRIGATE_MAX_LOOKBACK,
  FRIGATE_MIN_LOOKBACK,
  isNotEnabled,
  putFrigateProvider,
  queueFrigateBackfill,
  testFrigateProvider,
  type FrigateBackfillRequest,
  type FrigateProviderPut,
} from "../api/frigate"
import { FRIGATE } from "./queries"
import { useSave } from "./save"

/**
 * Writes for the Frigate integration.
 *
 * The body is a whole-object replace, so `putFrigateProvider` is called with
 * `buildFrigatePut(form)` output rather than a diff — see `api/frigate.ts` for
 * why that is not optional.
 */

export function useSaveFrigateProvider() {
  return useSave<FrigateProviderPut, unknown>({
    mutationFn: (body) => putFrigateProvider(body),
    invalidates: [FRIGATE.provider],
    success: () => ({ title: "Frigate 配置已保存" }),
    failure: (error) => ({
      title: "保存失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * A real outbound HTTP call to the configured Frigate, with a 10s server-side
 * timeout. It has an external side effect, so it is only ever an explicit
 * click — never a connectivity probe on mount.
 */
export function useTestFrigateProvider() {
  return useSave<void, { ok: boolean; version: string | null }>({
    mutationFn: () => testFrigateProvider(),
    success: (data) => ({
      title: "连通性测试通过",
      detail: data.version ? `Frigate 版本 ${data.version}` : undefined,
    }),
    failure: (error) => ({
      title: "连通性测试失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * Queues an event backfill. It enqueues work rather than doing it inline, so a
 * large lookback is not a request that times out — but it is still a real
 * effect on the event table, which is why the panel confirms first.
 */
export function useQueueFrigateBackfill() {
  return useSave<FrigateBackfillRequest, { queued: boolean; lookback_seconds: number }>(
    {
      mutationFn: (body) => queueFrigateBackfill(body),
      invalidates: [FRIGATE.provider],
      success: (data) => ({
        title: "回填已入队",
        detail: `回看窗口 ${formatLookback(data.lookback_seconds)}，由后台任务执行。`,
      }),
      failure: (error) => ({
        title: "回填未能入队",
        detail: describeFailure(error),
      }),
    },
  )
}

export function formatLookback(seconds: number): string {
  const clamped = Math.min(
    FRIGATE_MAX_LOOKBACK,
    Math.max(FRIGATE_MIN_LOOKBACK, seconds),
  )
  if (clamped % 3600 === 0) return `${clamped / 3600} 小时`
  if (clamped % 60 === 0) return `${clamped / 60} 分钟`
  return `${clamped} 秒`
}

/**
 * These two codes are the difference between "you have not finished setting
 * this up" and "it is broken", and both arrive with an English sentence that
 * does not make that distinction visible.
 */
function describeFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  if (isNotEnabled(error)) {
    return "Frigate 集成当前未启用。请先保存配置并勾选「启用」再回填。"
  }
  if (code === "frigate_not_configured") {
    return "尚未配置 Frigate 集成。请先填写地址并保存。"
  }
  if (code === "frigate_credentials_update_invalid") {
    return "凭据只在选择「替换」时提交，且至少要填一项。"
  }
  if (code === "frigate_camera_mapping_duplicate") {
    return "Frigate 侧的机位名重复。同一台 Frigate 上的机位名必须唯一。"
  }
  return error instanceof Error ? error.message : String(error)
}
