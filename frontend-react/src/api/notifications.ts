/**
 * Notification target + delivery contract. Mirrors
 * `backend/app/modules/notifications/schemas.py`.
 *
 * ## Secrets are write-only, and the update path is a three-way protocol
 *
 * `url` and `smtp_credentials.password` are `SecretStr`: they go out and never
 * come back. The read model says only `url_configured` / `credentials_configured`
 * (`schemas.py:63-70`).
 *
 * That is why `NotificationTargetUpdate` does not simply accept `url: str | null`.
 * `null` would be ambiguous between "leave it alone" and "delete it", so the
 * schema carries an explicit verb alongside the value:
 *
 * ```text
 * url_action:         keep | replace | clear
 * credentials_action: keep | replace | clear
 * ```
 *
 * An editor that sends `url: null` on a PATCH is not clearing the secret — it is
 * asking for one of the other two and the server cannot tell which. `applySecretEdit`
 * below is the only place in the app that builds one of these bodies.
 *
 * ## Two unrelated things both look like "the security email"
 *
 * They are separate settings with different rules, and merging them into one
 * control produces 400s that name neither:
 *
 * | | `config.password_reset: true` | security email default |
 * |---|---|---|
 * | stored on | the target's own `config_json` | a `SystemSetting` pointer |
 * | uniqueness | globally unique — a second one is 409 `password_reset_target_conflict` (`service.py:96-112`) | a single pointer, overwrite freely |
 * | requires | the target's URL be `mailto:`/`mailtos:` with no path and no fragment (`service.py:119-134`) | the target be **`kind == "smtp"`** (`service.py:539-551`) |
 *
 * The first configures how a reset mail is addressed through Apprise; the second
 * points at the SMTP target that actually sends it. The UI keeps them apart and
 * labels each with its own consequence.
 */
import { api } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type NotificationKind = "apprise" | "smtp"

/** `_normalize_config` accepts exactly these four (`service.py:62-72`). */
export const NOTIFY_TYPES = ["info", "success", "warning", "failure"] as const
export type NotifyType = (typeof NOTIFY_TYPES)[number]

export const NOTIFY_TYPE_LABEL: Record<NotifyType, string> = {
  info: "信息",
  success: "成功",
  warning: "警告",
  failure: "失败",
}

export type NotificationConfig = {
  notify_type?: string
  password_reset?: boolean
}

export type NotificationTargetView = {
  id: string
  name: string
  kind: NotificationKind
  enabled: boolean
  config: NotificationConfig
  /** The only signal that a URL exists; the URL itself never comes back. */
  url_configured: boolean
  credentials_configured: boolean
}

export type SmtpCredentialsInput = {
  username: string
  password: string
}

export type NotificationTargetCreate = {
  name: string
  kind?: NotificationKind
  enabled?: boolean
  config?: NotificationConfig
  url?: string | null
  smtp_credentials?: SmtpCredentialsInput | null
}

export type SecretAction = "keep" | "replace" | "clear"

/**
 * Narrow a segmented-control value back to a verb.
 *
 * The shared `Segmented` control is stringly typed, so the three-state editor
 * is the one place that can receive a value outside the union. Unknown values
 * fall to `keep` rather than `clear` on purpose: the two differ in what they
 * destroy, and guessing on a write-only secret is not a recoverable mistake.
 */
export function toSecretAction(value: string): SecretAction {
  return value === "replace" || value === "clear" ? value : "keep"
}

export type NotificationTargetUpdate = {
  name?: string
  enabled?: boolean
  config?: NotificationConfig
  url?: string | null
  url_action?: SecretAction
  credentials_action?: SecretAction
  smtp_credentials?: SmtpCredentialsInput | null
}

export type SecurityEmailTargetView = { target_id: string | null }
export type SecurityEmailTargetUpdate = { target_id: string | null }

export type NotificationTargetTestRequest = { recipient?: string | null }

export type DeliveryState = "PENDING" | "SENDING" | "SENT" | "FAILED" | "SKIPPED"

export type DeliveryPurpose = "alert" | "password_reset" | "security" | "system_test"

export type NotificationDeliveryView = {
  id: string
  alert_id: string | null
  purpose: DeliveryPurpose
  notification_target_id: string
  state: DeliveryState
  attempt_count: number
  title: string
  body: string
  last_attempt_at: string | null
  sent_at: string | null
  last_error_code: string | null
  provider_message_id: string | null
  correlation_id: string | null
  created_at: string
  updated_at: string
}

export type DeliveryFilters = {
  alertId?: string
  targetId?: string
  limit?: number
}

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

export function listNotificationTargets(signal?: AbortSignal) {
  return api.get<NotificationTargetView[]>("/notification-targets", signal)
}

export function createNotificationTarget(body: NotificationTargetCreate) {
  return api.post<NotificationTargetView>("/notification-targets", body)
}

export function updateNotificationTarget(
  targetId: string,
  body: NotificationTargetUpdate,
) {
  return api.patch<NotificationTargetView>(
    `/notification-targets/${targetId}`,
    body,
  )
}

export function deleteNotificationTarget(targetId: string) {
  return api.del<void>(`/notification-targets/${targetId}`)
}

/** Sends a real message. `recipient` overrides the target's own addressing. */
export function testNotificationTarget(
  targetId: string,
  body: NotificationTargetTestRequest = {},
) {
  return api.post<{ ok: true }>(
    `/notification-targets/${targetId}/test`,
    body,
  )
}

export function getSecurityEmailTarget(signal?: AbortSignal) {
  return api.get<SecurityEmailTargetView>(
    "/notification-targets/security-email-default",
    signal,
  )
}

export function setSecurityEmailTarget(targetId: string | null) {
  return api.put<SecurityEmailTargetView>(
    "/notification-targets/security-email-default",
    { target_id: targetId },
  )
}

/** A plain list, not a page — no cursor on this endpoint. */
export function listNotificationDeliveries(
  filters: DeliveryFilters = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (filters.alertId) qs.set("alert_id", filters.alertId)
  if (filters.targetId) qs.set("target_id", filters.targetId)
  qs.set("limit", String(filters.limit ?? 50))
  return api.get<NotificationDeliveryView[]>(
    `/notification-deliveries?${qs}`,
    signal,
  )
}

/* -------------------------------------------------------------------------- */
/* The secret-edit protocol                                                  */
/* -------------------------------------------------------------------------- */

/**
 * What the operator decided to do about a write-only secret.
 *
 * Two shapes rather than one: replacing SMTP credentials needs a username as
 * well as a password, so a single `value: string` would either lose the
 * username or smuggle it in through a cast.
 */
export type SecretEdit =
  | { action: "keep" }
  | { action: "replace"; value: string }
  | { action: "replace"; value: SmtpCredentialsInput }

export type UrlEdit =
  | { action: "keep" }
  | { action: "replace"; value: string }
  | { action: "clear" }

export type CredentialsEdit =
  | { action: "keep" }
  | { action: "replace"; value: SmtpCredentialsInput }
  | { action: "clear" }

/**
 * Turn an operator's intent about the URL into the two fields the schema
 * expects.
 *
 * Returns only the pair it touched, so an edit to the URL never disturbs the
 * stored password. Sending `url: null` without a verb is exactly the ambiguity
 * this endpoint was designed to avoid.
 */
export function applyUrlEdit(
  edit: UrlEdit,
): { url_action: SecretAction; url?: string | null } {
  return edit.action === "replace"
    ? { url_action: "replace", url: edit.value }
    : { url_action: edit.action }
}

/** The same for SMTP credentials. `clear` is distinct from an empty object. */
export function applyCredentialsEdit(
  edit: CredentialsEdit,
): {
  credentials_action: SecretAction
  smtp_credentials?: SmtpCredentialsInput | null
} {
  return edit.action === "replace"
    ? { credentials_action: "replace", smtp_credentials: edit.value }
    : { credentials_action: edit.action }
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

export const DELIVERY_STATE_LABEL: Record<DeliveryState, string> = {
  PENDING: "待发送",
  SENDING: "发送中",
  SENT: "已发送",
  FAILED: "失败",
  SKIPPED: "已跳过",
}

export function deliveryStateLabel(state: string): string {
  return DELIVERY_STATE_LABEL[state as DeliveryState] ?? state
}

export function deliveryStateTone(
  state: string,
): "online" | "offline" | "degraded" | "unknown" {
  if (state === "SENT") return "online"
  if (state === "FAILED") return "offline"
  if (state === "SENDING" || state === "PENDING") return "degraded"
  return "unknown"
}

export const DELIVERY_PURPOSE_LABEL: Record<DeliveryPurpose, string> = {
  alert: "告警通知",
  password_reset: "密码重置",
  security: "安全提醒",
  system_test: "连通性测试",
}

export function deliveryPurposeLabel(purpose: string): string {
  return DELIVERY_PURPOSE_LABEL[purpose as DeliveryPurpose] ?? purpose
}
