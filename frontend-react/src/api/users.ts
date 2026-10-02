/**
 * User administration contract. Mirrors `backend/app/modules/auth/schemas.py`
 * and the `/users*` routes in `auth/admin_api.py`.
 *
 * Four things about this contract are not obvious from the route list and
 * each one changes what a form may contain:
 *
 * 1. **A username is immutable.** `UserUpdate` carries `display_name`,
 *    `email` and `role_ids` only (`schemas.py:136-140`). There is no field to
 *    rename a user with, so the edit form does not offer one — offering an
 *    input that silently does nothing is the same failure as G-21.
 * 2. **Enable/disable is not a field either.** `UserUpdate` has no `enabled`;
 *    it is `POST /users/{id}/disable` and `/enable` (`admin_api.py`). Sending
 *    `enabled` in a PATCH would be dropped, so the toggle calls the endpoint.
 * 3. **Camera scope is a separate resource** with a four-state mode
 *    (`inherit | all | selected | none`), fetched and written on its own
 *    endpoint. It is not part of the user record and cannot be saved together
 *    with the profile, so the two are edited and reported independently — a
 *    half-saved screen has to say which half.
 * 4. **Password reset hands back a token, once.** `UserPasswordResetIssue` is
 *    `{token, expires_at}` and nothing can read it back, the same one-shot
 *    shape as an export share link. It is the admin's job to deliver it, so
 *    the UI has to display it rather than offer a "resend" affordance that
 *    would issue a second token and quietly invalidate the first.
 */
import { api } from "./client"

export type RoleSummary = {
  id: string
  name: string
  description: string | null
  built_in: boolean
}

export type RoleView = RoleSummary & {
  permissions: string[]
}

export type UserAdminView = {
  id: string
  username: string
  display_name: string
  email: string | null
  email_verified: boolean
  enabled: boolean
  roles: RoleSummary[]
}

export type UserCreate = {
  /** `^[A-Za-z0-9_.-]+$`, 1–64. */
  username: string
  display_name: string
  email?: string | null
  /** 12–256. The backend rejects anything shorter. */
  password: string
  role_ids?: string[]
}

export type UserUpdate = {
  display_name?: string
  email?: string | null
  role_ids?: string[]
}

export type UserPasswordResetIssue = {
  /** Shown once. No endpoint reads it back. */
  token: string
  expires_at: string
}

export type CameraScopeMode = "inherit" | "all" | "selected" | "none"

export type CameraScopeView = {
  mode: CameraScopeMode
  camera_ids: string[]
  camera_group_ids: string[]
}

export type CameraScopeUpdate = CameraScopeView

/** A plain array, not a page — there is no cursor on this endpoint. */
export function listUsers(signal?: AbortSignal) {
  return api.get<UserAdminView[]>("/users", signal)
}

export function getUser(userId: string, signal?: AbortSignal) {
  return api.get<UserAdminView>(`/users/${userId}`, signal)
}

export function createUser(body: UserCreate) {
  return api.post<UserAdminView>("/users", body)
}

export function updateUser(userId: string, body: UserUpdate) {
  return api.patch<UserAdminView>(`/users/${userId}`, body)
}

export function setUserEnabled(userId: string, enabled: boolean) {
  return api.post<UserAdminView>(
    `/users/${userId}/${enabled ? "enable" : "disable"}`,
  )
}

/** Returns a one-time token; see note 4 above. */
export function issueUserPasswordReset(userId: string) {
  return api.post<UserPasswordResetIssue>(`/users/${userId}/password-reset`)
}

export function getUserCameraScope(userId: string, signal?: AbortSignal) {
  return api.get<CameraScopeView>(`/users/${userId}/camera-scope`, signal)
}

export function setUserCameraScope(
  userId: string,
  body: CameraScopeUpdate,
) {
  return api.put<CameraScopeView>(`/users/${userId}/camera-scope`, body)
}

export function listRoles(signal?: AbortSignal) {
  return api.get<RoleView[]>("/roles", signal)
}

export function listPermissions(signal?: AbortSignal) {
  return api.get<string[]>("/permissions", signal)
}

/* -------------------------------------------------------------------------- */
/* Custom roles                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Roles are not a three-item enum, and the built-in three are not editable.
 *
 * The backend re-syncs Administrator / Operator / Viewer to their exact
 * permission sets on every start and force-marks them `built_in`
 * (`auth/service.py:71-97`), then refuses `PATCH /roles/{id}` on any `built_in`
 * role with 409 `builtin_role_immutable` (`auth/admin_service.py:293-298`).
 * Even an Administrator cannot widen or narrow them.
 *
 * So the only thing this screen can change is a **custom** role
 * (`built_in: false`), and the three built-ins are listed as a fixed reference
 * rather than as three rows of editable checkboxes. Offering disabled
 * checkboxes for them would invite an operator to try.
 */

export type RoleCreate = {
  /** 1–64. Conflicting names return 409 `role_name_conflict`. */
  name: string
  description?: string | null
  permissions?: string[]
}

export type RoleUpdate = {
  name?: string
  description?: string | null
  /**
   * **Replace**, not merge — the whole set is written
   * (`auth/admin_service.py:306-314`). Omitting the key leaves the set alone;
   * sending `[]` strips every permission.
   */
  permissions?: string[]
}

export function createRole(body: RoleCreate) {
  return api.post<RoleView>("/roles", body)
}

export function updateRole(roleId: string, body: RoleUpdate) {
  return api.patch<RoleView>(`/roles/${roleId}`, body)
}

/**
 * There is no `DELETE /roles/{id}`. A custom role can be emptied of
 * permissions and left unassigned, but it stays in the list forever.
 *
 * (G-44: the endpoint should exist, and refuse while users still hold the role.)
 */

export function getRoleCameraScope(roleId: string, signal?: AbortSignal) {
  return api.get<CameraScopeView>(`/roles/${roleId}/camera-scope`, signal)
}

export function setRoleCameraScope(roleId: string, body: CameraScopeUpdate) {
  return api.put<CameraScopeView>(`/roles/${roleId}/camera-scope`, body)
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

export const USERNAME_PATTERN = /^[A-Za-z0-9_.-]+$/
export const MIN_PASSWORD_LENGTH = 12

export const CAMERA_SCOPE_LABEL: Record<CameraScopeMode, string> = {
  inherit: "继承角色",
  all: "全部机位",
  selected: "指定机位",
  none: "无权限",
}

export const CAMERA_SCOPE_HINT: Record<CameraScopeMode, string> = {
  inherit: "沿用其角色所允许的机位范围。",
  all: "不受机位范围限制。",
  selected: "只能看到下面勾选的机位。",
  none: "看不到任何机位——录像、直播与事件列表都会为空。",
}

export type UserFieldErrors = Partial<
  Record<"username" | "display_name" | "email" | "password", string>
>

/**
 * Checked here as well as on the server so the operator sees the reason next
 * to the field. The backend's own rules are `pattern` + length on the schema
 * (`schemas.py:130-135`), reproduced rather than guessed.
 */
export function validateUser(
  values: {
    username?: string
    display_name?: string
    email?: string | null
    password?: string
  },
  { requirePassword }: { requirePassword: boolean },
): UserFieldErrors {
  const errors: UserFieldErrors = {}

  const username = values.username?.trim() ?? ""
  if (!username) errors.username = "请填写用户名"
  else if (username.length > 64) errors.username = "用户名最长 64 字符"
  else if (!USERNAME_PATTERN.test(username)) {
    errors.username = "只能包含字母、数字、下划线、点和连字符"
  }

  const displayName = values.display_name?.trim() ?? ""
  if (!displayName) errors.display_name = "请填写显示名"
  else if (displayName.length > 128) errors.display_name = "显示名最长 128 字符"

  if (values.email) {
    // Deliberately loose: EmailStr does full RFC validation server-side, and a
    // stricter client regex rejects addresses the backend would accept.
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) {
      errors.email = "邮箱格式不正确"
    }
  }

  if (requirePassword) {
    const password = values.password ?? ""
    if (!password) errors.password = "请填写初始密码"
    else if (password.length < MIN_PASSWORD_LENGTH) {
      errors.password = `密码至少 ${MIN_PASSWORD_LENGTH} 位`
    }
  }

  return errors
}

export function hasErrors(errors: UserFieldErrors): boolean {
  return Object.keys(errors).length > 0
}

/* -------------------------------------------------------------------------- */
/* Permissions                                                                */
/* -------------------------------------------------------------------------- */

/**
 * The 19 permissions, grouped by their domain prefix for display.
 *
 * Grouping is presentation only. There is deliberately **no** "select the whole
 * domain" affordance: the permissions inside a domain are not a set that is
 * meaningful all-or-nothing (`recording.export` and `recording.delete` are not
 * switches that travel together), so a group-level toggle would only ever
 * manufacture partial states and a second way to be wrong.
 */
export const PERMISSION_LABEL: Record<string, string> = {
  "camera.view": "查看机位",
  "camera.control": "控制机位（PTZ、快照）",
  "camera.configure": "配置机位",
  "recording.view": "查看录像",
  "recording.export": "导出录像",
  "recording.protect": "保护录像",
  "recording.delete": "删除录像",
  "event.view": "查看事件",
  "alert.view": "查看告警",
  "alert.acknowledge": "确认告警",
  "alert.manage": "管理告警规则",
  "notification.view": "查看通知",
  "notification.manage": "管理通知渠道",
  "storage.manage": "管理存储",
  "system.view": "查看系统状态",
  "system.manage": "管理系统设置",
  "user.manage": "管理用户与角色",
  "integration.manage": "管理外部集成",
  "audit.view": "查看审计日志",
}

const PERMISSION_DOMAIN_LABEL: Record<string, string> = {
  camera: "摄像机",
  recording: "录像",
  event: "事件",
  alert: "告警",
  notification: "通知",
  storage: "存储",
  system: "系统",
  user: "用户",
  integration: "集成",
  audit: "审计",
}

export type PermissionGroup = {
  domain: string
  label: string
  items: { permission: string; label: string }[]
}

/**
 * Group the catalogue by domain. The catalogue comes from the server, so an
 * unknown permission renders with its raw code rather than disappearing — a new
 * backend permission is information, and a checkbox that is missing is not.
 */
export function groupPermissions(catalogue: readonly string[]): PermissionGroup[] {
  const byDomain = new Map<string, string[]>()
  for (const permission of catalogue) {
    const domain = permission.split(".", 1)[0] || "other"
    const bucket = byDomain.get(domain)
    if (bucket) bucket.push(permission)
    else byDomain.set(domain, [permission])
  }
  return Array.from(byDomain.entries())
    .map(([domain, items]) => ({
      domain,
      label: PERMISSION_DOMAIN_LABEL[domain] ?? domain,
      items: items
        .slice()
        .sort()
        .map((permission) => ({
          permission,
          label: PERMISSION_LABEL[permission] ?? permission,
        })),
    }))
    .sort((a, b) => a.domain.localeCompare(b.domain))
}

export type RoleFieldErrors = Partial<Record<"name", string>>

/**
 * Client-side pre-check, reproduced from the schema
 * (`auth/schemas.py:80-89`) rather than guessed.
 *
 * There is deliberately no "permissions required" rule. An **empty permission
 * set is legal** — it is how an operator stages a role before assigning it — so
 * it is not blocked here, and the UI says what such a role does rather than
 * pretending the form is incomplete.
 */
export function validateRole(values: { name?: string }): RoleFieldErrors {
  const errors: RoleFieldErrors = {}
  const name = values.name?.trim() ?? ""
  if (!name) errors.name = "请填写角色名"
  else if (name.length > 64) errors.name = "角色名最长 64 字符"
  return errors
}

/* -------------------------------------------------------------------------- */
/* Camera groups                                                              */
/* -------------------------------------------------------------------------- */

/**
 * `GET /camera-groups` — used by the user scope picker, because
 * `CameraScopeUpdate.camera_group_ids` is a first-class part of the scope and
 * the groups are real, managed resources with their own CRUD
 * (`cameras/api.py`). Writing `camera_group_ids: []` because "groups are not
 * implemented" would silently strip every group-scoped assignment.
 */
/**
 * Re-exported rather than redeclared.
 *
 * The type and the list call used to live here, which meant two definitions of
 * the same wire shape and two places to forget the PATCH-is-a-whole-replace
 * rule for `camera_ids`. `api/cameraGroups.ts` is now the single home; this
 * re-export keeps the user scope picker's import working.
 */
export { listCameraGroups, type CameraGroupView } from "./cameraGroups"
