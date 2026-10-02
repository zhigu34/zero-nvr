import {
  acknowledgeAlert,
  createAlertPolicy,
  deleteAlertPolicy,
  mergeMatch,
  resolveAlert,
  updateAlertPolicy,
  type AlertMatch,
  type AlertPolicyCreate,
  type AlertSeverity,
} from "../api/alerts"
import { ALERTS } from "./queries"
import { useSave } from "./save"

/**
 * Writes for the alert screen.
 *
 * The create and update mutations both take the **merged** match rather than
 * the form draft, and the merge happens at the call site. That is deliberate:
 * the PATCH replaces `match` wholesale, so a mutation that received a draft
 * and sent it as-is would be a data-loss path with a 200 in response. Making
 * the caller pass `mergeMatch(existing, draft)` puts the read step next to
 * the write step, where the value it depends on is still in hand.
 */

export function useCreateAlertPolicy() {
  return useSave<AlertPolicyCreate, unknown>({
    mutationFn: (body) => createAlertPolicy(body),
    invalidates: [ALERTS.policies],
    success: () => ({ title: "告警规则已创建" }),
    failure: (error) => ({
      title: "创建告警规则失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useUpdateAlertPolicy(policyId: string, existingMatch: AlertMatch) {
  return useSave<
    {
      name?: string
      enabled?: boolean
      severity?: AlertSeverity
      match?: AlertMatch
      cooldown_seconds?: number
    },
    unknown
  >({
    mutationFn: (body) => {
      // Belt and braces: even if a caller forgets to merge, the mutation does
      // it rather than sending a replacement built from the field list.
      const payload = {
        ...body,
        match:
          body.match === undefined
            ? undefined
            : mergeMatch(existingMatch, body.match),
      }
      return updateAlertPolicy(policyId, payload)
    },
    invalidates: [ALERTS.policies],
    success: () => ({ title: "告警规则已更新" }),
    failure: (error) => ({
      title: "更新告警规则失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useDeleteAlertPolicy() {
  return useSave<string, void>({
    mutationFn: (policyId) => deleteAlertPolicy(policyId),
    invalidates: [ALERTS.policies, ALERTS.list({})],
    success: () => ({ title: "告警规则已删除" }),
    failure: (error) => ({
      title: "删除失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useAcknowledgeAlert() {
  return useSave<string, unknown>({
    mutationFn: (alertId) => acknowledgeAlert(alertId),
    invalidates: [ALERTS.list({})],
    success: () => ({ title: "已确认" }),
    failure: (error) => ({
      title: "确认失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useResolveAlert() {
  return useSave<string, unknown>({
    mutationFn: (alertId) => resolveAlert(alertId),
    invalidates: [ALERTS.list({})],
    success: () => ({ title: "已解决" }),
    failure: (error) => ({
      title: "标记解决失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}
