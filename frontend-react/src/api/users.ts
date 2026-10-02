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
