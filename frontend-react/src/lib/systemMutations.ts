import {
  applyCameraNtp,
  patchSystemSettings,
  type SystemSettingsPatch,
} from "../api/systemSettings"
import { SYSTEM } from "./queries"
import { useSave } from "./save"
import { wasPersisted } from "./cameraMutations"

/**
 * `PATCH /system/settings` commits the settings first and then re-runs the
 * affected runtime coordination; a failure there is a 503 carrying
 * `details.settings_persisted = true` (`system/api.py:1198`). The operator
 * must be told the setting is stored but not yet in force, rather than being
 * invited to submit it again.
 */
export function useSaveSystemSettings() {
  return useSave<SystemSettingsPatch, unknown>({
    mutationFn: (body) => patchSystemSettings(body),
    invalidates: [SYSTEM.settings, SYSTEM.health],
    success: () => ({ title: "系统设置已保存" }),
    failure: (error) =>
      wasPersisted(error)
        ? {
            title: "设置已保存，但尚未生效",
            detail:
              "配置已经写入，媒体运行时未接受本次变更（通常是媒体服务繁忙）。后台任务会在服务恢复后重试。",
          }
        : {
            title: "系统设置保存失败",
            detail: error instanceof Error ? error.message : String(error),
          },
  })
}

/**
 * Pushing NTP to every managed device. This is the one endpoint that can
 * genuinely partially fail: it walks the fleet and reports per-device
 * outcomes inside a 200, so the message has to carry the count rather than a
 * bare "done".
 */
export function useApplyCameraNtp() {
  return useSave<void, Awaited<ReturnType<typeof applyCameraNtp>>>({
    mutationFn: () => applyCameraNtp(),
    invalidates: [SYSTEM.clockHealth, SYSTEM.health],
    success: (result) => ({
      title: "已下发 NTP 设置",
      detail:
        result.failed > 0
          ? `${result.updated} 台成功，${result.failed} 台失败——请查看下方逐台结果。`
          : `${result.updated} 台已更新。`,
    }),
    failure: (error) => ({
      title: "下发 NTP 失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}
