import {
  createNotificationTarget,
  deleteNotificationTarget,
  setSecurityEmailTarget,
  testNotificationTarget,
  updateNotificationTarget,
  type NotificationTargetCreate,
  type NotificationTargetUpdate,
} from "../api/notifications"
import { NOTIFICATIONS } from "./queries"
import { useSave } from "./save"

/**
 * Writes for the notification settings.
 *
 * The create/update mutations take a body that the caller has already built
 * with `applyUrlEdit` / `applyCredentialsEdit`. That is deliberate: the verb
 * protocol is the part of this contract most easily got wrong, and building the
 * body next to the form fields that express the intent keeps the two together.
 */

export function useCreateNotificationTarget() {
  return useSave<NotificationTargetCreate, unknown>({
    mutationFn: (body) => createNotificationTarget(body),
    invalidates: [NOTIFICATIONS.targets, NOTIFICATIONS.securityEmail],
    success: () => ({ title: "通知目标已创建" }),
    failure: (error) => ({
      title: "创建通知目标失败",
      detail: describeFailure(error),
    }),
  })
}

export function useUpdateNotificationTarget(targetId: string) {
  return useSave<NotificationTargetUpdate, unknown>({
    mutationFn: (body) => updateNotificationTarget(targetId, body),
    invalidates: [NOTIFICATIONS.targets, NOTIFICATIONS.securityEmail],
    success: () => ({ title: "通知目标已更新" }),
    failure: (error) => ({
      title: "更新通知目标失败",
      detail: describeFailure(error),
    }),
  })
}

export function useDeleteNotificationTarget() {
  return useSave<string, void>({
    mutationFn: (targetId) => deleteNotificationTarget(targetId),
    invalidates: [NOTIFICATIONS.targets, NOTIFICATIONS.securityEmail],
    success: () => ({ title: "通知目标已删除" }),
    failure: (error) => ({
      title: "删除失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * Sends a real message through the target. It is a POST with an external side
 * effect, so it is only ever an explicit operator action — never a probe on
 * mount, the same rule the storage capacity read follows (G-1).
 */
export function useTestNotificationTarget(targetId: string) {
  return useSave<{ recipient?: string } | void, unknown>({
    mutationFn: (variables) => testNotificationTarget(targetId, variables ?? {}),
    // Prefix match: every delivery query key starts with this, so one
    // invalidation covers all filter combinations.
    invalidates: [["notifications", "deliveries"]],
    success: () => ({
      title: "测试通知已发出",
      detail: "请在目标渠道确认是否收到。投递记录在下方。",
    }),
    failure: (error) => ({
      title: "测试通知失败",
      detail: describeFailure(error),
    }),
  })
}

export function useSetSecurityEmailTarget() {
  return useSave<string | null, unknown>({
    mutationFn: (targetId) => setSecurityEmailTarget(targetId),
    invalidates: [NOTIFICATIONS.securityEmail, NOTIFICATIONS.targets],
    success: () => ({ title: "安全邮件目标已更新" }),
    failure: (error) => ({
      title: "设置安全邮件目标失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * Two of these codes name a rule the operator broke rather than a fault, and
 * the raw message does not say which rule:
 *
 * - `password_reset_target_conflict` — a second target already carries
 *   `password_reset: true`, which is globally unique.
 * - `security_email_target_invalid` — the chosen target is not `kind: "smtp"`.
 *
 * Both arrive as a 400/409 with an English sentence. The operator needs to know
 * which of two unrelated settings they are looking at.
 */
function describeFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  if (code === "password_reset_target_conflict") {
    return "密码重置邮件只能由一个通知目标承担。请先在其它目标上关闭「用于密码重置」。"
  }
  if (code === "security_email_target_invalid") {
    return "安全邮件目标必须是 SMTP 类型。Apprise 目标无法承担这个角色。"
  }
  if (code === "password_reset_target_invalid") {
    return "密码重置目标的 URL 必须是 mailto: 或 mailtos: 形式，且不能带收件人路径。"
  }
  return error instanceof Error ? error.message : String(error)
}
