/**
 * Auth endpoints. Schemas mirror `backend/app/modules/auth/schemas.py` exactly —
 * ADR-0014 decision 4 freezes the API contract, so nothing here is a redesign.
 */
import { api, ApiError } from "./client"

export type AuthUser = {
  id: string
  username: string
  display_name: string
  email: string | null
  email_verified: boolean
  roles: string[]
  permissions: string[]
}

export type SetupStatus = { requires_initial_admin: boolean }

export type InitialAdministratorCreate = {
  username: string
  display_name: string
  email?: string | null
  password: string
}

export type LoginRequest = {
  username: string
  password: string
}

export type PasswordChangeRequest = {
  current_password: string
  new_password: string
}

/**
 * The backend's three built-in roles (`auth/permissions.py`
 * BUILTIN_ROLE_PERMISSIONS). Capability checks key off these names rather
 * than the 19 fine-grained permission strings: ADR-0014 decision 6 collapses
 * permissions to role level, and the fine-grained list is due to disappear.
 * `can()` therefore reads roles, so the eventual permission-point removal
 * does not ripple through every page.
 */
export const ROLES = {
  ADMIN: "Administrator",
  OPERATOR: "Operator",
  VIEWER: "Viewer",
} as const

export type RoleName = (typeof ROLES)[keyof typeof ROLES]

export function isAuthUser(value: unknown): value is AuthUser {
  if (!value || typeof value !== "object") return false
  const u = value as Partial<AuthUser>
  return typeof u.id === "string" && Array.isArray(u.roles)
}

export function setupStatus(signal?: AbortSignal) {
  return api.get<SetupStatus>("/setup/status", signal)
}

export function createInitialAdministrator(body: InitialAdministratorCreate) {
  return api.post<AuthUser>("/setup/administrator", body)
}

export function login(body: LoginRequest) {
  return api.post<AuthUser>("/auth/login", body)
}

export function logout() {
  return api.post<void>("/auth/logout")
}

export function me(signal?: AbortSignal) {
  return api.get<AuthUser>("/auth/me", signal)
}

export function changePassword(body: PasswordChangeRequest) {
  return api.post<AuthUser>("/auth/password/change", body)
}

export { ApiError }
