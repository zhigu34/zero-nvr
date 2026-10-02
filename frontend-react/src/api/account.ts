/**
 * Self-account contract. Mirrors
 * `backend/app/modules/auth/{api,schemas,service,password_reset}.py`.
 *
 * Everything here is gated on `require_interactive_session`
 * (`auth/dependencies.py:121-130`), which rejects when the credential is an API
 * token — `resolve_api_token` hardcodes `session=None`
 * (`auth/service.py:270-271`) while only `resolve_session` sets one. So a token
 * gets **403 `interactive_session_required`**, not 401, on all of it. That is
 * the correct answer: a leaked token must not be able to lock its owner out.
 *
 * ## What this account page cannot do
 *
 * There is **no self-service profile endpoint**. `username` and `display_name`
 * are mutable only through `PATCH /users/{user_id}`, which needs
 * `user.manage` and is somebody else's account
 * (`admin_api.py:169-201`). There is no email change, no email verification, and
 * no resend — `email_verified` is `false` for every real user, because nothing
 * outside tests ever sets `email_verified_at`.
 *
 * A page that offers an "edit profile" form would therefore be offering a 403.
 * This module exposes the read-only surface and says so.
 *
 * ## `last_seen_at` is a lie by construction
 *
 * `UserSession.last_seen_at` is written once at creation
 * (`auth/service.py:203`) and never updated again, so it is always identical to
 * `created_at`. Rendering it as "last active" tells the operator their other
 * devices are idle when they may be in use right now. `sessionAge` exists so
 * the one honest statement — "signed in since" — is the only one available.
 *
 * ## Two error envelope shapes
 *
 * A `Field(...)` violation produces FastAPI's own **422 `{"detail": [...]}`**,
 * because no `RequestValidationError` handler is installed (`main.py:275`).
 * Every other failure is `{"error": {...}}`. `api/client.ts` parses both; the
 * forms rely on it rather than assuming one shape.
 */
import { api, ApiError } from "./client"
import type { AuthUser } from "./auth"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type SessionClientInfo = {
  /** Absent rather than null when the header was missing. */
  user_agent?: string
  source_ip?: string
}

export type SessionSummary = {
  id: string
  created_at: string
  /** Always equal to `created_at`. See the module note. */
  last_seen_at: string
  expires_at: string
  /** True for the session making this request. */
  current: boolean
  /** A sparse dict, not a fixed shape. */
  client_info: SessionClientInfo | null
}

export type PasswordChangeRequest = {
  current_password: string
  new_password: string
}

/** `PasswordChangeRequest.new_password` (`schemas.py:26-28`). */
export const PASSWORD_MIN = 12
export const PASSWORD_MAX = 256

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

/** `require_interactive_session`. Live, unrevoked, unexpired only. */
export function listSessions(signal?: AbortSignal) {
  return api.get<SessionSummary[]>("/sessions", signal)
}

/**
 * 204. Idempotent: a second call on an already-revoked id still returns 204
 * (`service.py:346` only stamps `revoked_at` when null). A row owned by another
 * user is a **404, not a 403** — ownership is masked (`service.py:339-344`).
 *
 * Revoking the session you are currently using succeeds, and the response also
 * clears your cookie (`api.py:456-460`); the next request 401s.
 */
export function revokeSession(sessionId: string) {
  return api.del<void>(`/sessions/${sessionId}`)
}

/**
 * `POST /auth/password/change` — **not** `/auth/password`, which does not exist.
 *
 * Returns the updated `AuthUser` and **revokes every other session** before
 * minting a replacement one (`service.py:297-310`), so the caller stays signed
 * in everywhere else does not. The filter is `revoked_at IS NULL` only, so
 * expired-but-unrevoked rows are swept too.
 *
 * A wrong `current_password` is **400 `invalid_current_password`**, not a 401 —
 * it is a form field error, not an authentication failure, and must not be
 * rendered as "please log in again".
 */
export function changeOwnPassword(body: PasswordChangeRequest) {
  return api.post<AuthUser>("/auth/password/change", body)
}

/* -------------------------------------------------------------------------- */
/* Derived state                                                              */
/* -------------------------------------------------------------------------- */

export type SessionLifetime = {
  signedInSince: string
  expiresAt: string
  /** Whole days until expiry, floored; negative once expired. */
  daysLeft: number
}

export function sessionLifetime(
  session: SessionSummary,
  now: Date = new Date(),
): SessionLifetime {
  const expires = new Date(session.expires_at)
  return {
    signedInSince: session.created_at,
    expiresAt: session.expires_at,
    daysLeft: Math.floor((expires.getTime() - now.getTime()) / 86_400_000),
  }
}

/**
 * A one-line description of where a session came from.
 *
 * `client_info` is a sparse dict — both keys can be missing — so this never
 * claims a browser or an IP it does not have. An unrecognised user agent is
 * reported as such rather than as a blank.
 */
export function describeSessionSource(session: SessionSummary): string {
  const agent = session.client_info?.user_agent?.trim()
  const ip = session.client_info?.source_ip?.trim()
  const browser = agent ? guessBrowser(agent) : null
  const parts: string[] = []
  if (browser) parts.push(browser)
  else if (agent) parts.push("其他客户端")
  else parts.push("客户端信息未记录")
  if (ip) parts.push(ip)
  return parts.join(" · ")
}

function guessBrowser(userAgent: string): string | null {
  const ua = userAgent.toLowerCase()
  if (ua.includes("edg/")) return "Edge"
  if (ua.includes("opr/") || ua.includes("opera")) return "Opera"
  if (ua.includes("chrome/") && !ua.includes("chromium")) return "Chrome"
  if (ua.includes("firefox/")) return "Firefox"
  if (ua.includes("safari/") && !ua.includes("chrome/")) return "Safari"
  return null
}

/* -------------------------------------------------------------------------- */
/* Validation                                                                 */
/* -------------------------------------------------------------------------- */

export type PasswordForm = { currentPassword: string; newPassword: string }

export type PasswordFormError = {
  field: "currentPassword" | "newPassword"
  message: string
}

/**
 * The entire server-side rule is length: 12 to 256 (`schemas.py:26-28`).
 *
 * There is no character-class requirement, no similarity check against the
 * username, and **no old-password reuse check** — the new password may be the
 * current one verbatim and the server will accept it. The messages below say
 * only what is actually checked, because a form that claims reuse protection
 * it does not have is worse than one that says nothing.
 */
export function validatePasswordForm(form: PasswordForm): PasswordFormError[] {
  const errors: PasswordFormError[] = []

  if (form.currentPassword === "") {
    errors.push({ field: "currentPassword", message: "请填写当前密码" })
  }

  if (form.newPassword === "") {
    errors.push({ field: "newPassword", message: "请填写新密码" })
  } else if (form.newPassword.length < PASSWORD_MIN) {
    errors.push({
      field: "newPassword",
      message: `新密码至少 ${PASSWORD_MIN} 个字符`,
    })
  } else if (form.newPassword.length > PASSWORD_MAX) {
    errors.push({
      field: "newPassword",
      message: `新密码最长 ${PASSWORD_MAX} 个字符`,
    })
  }

  return errors
}

export function passwordsMatch(form: PasswordForm): boolean {
  return (
    form.newPassword.length > 0 && form.newPassword === form.currentPassword
  )
}

/* -------------------------------------------------------------------------- */
/* Failures the UI branches on                                               */
/* -------------------------------------------------------------------------- */

/**
 * Whether the credential itself is the problem, as opposed to the request.
 *
 * Covers both `interactive_session_required` (403 — the caller is an API token)
 * and `authentication_required` (401 — the session expired). Both mean "this
 * screen is the wrong place to fix it", so one predicate is the useful thing to
 * have; `isSessionExpired` below is the strict one for callers that must tell
 * them apart.
 */
export function isInteractiveSessionRequired(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.code === "interactive_session_required" ||
      error.code === "authentication_required")
  )
}

/** Strictly a 401 — the session is gone, as opposed to the wrong credential type. */
export function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.code === "authentication_required"
}

export function isWrongCurrentPassword(error: unknown): boolean {
  return error instanceof ApiError && error.code === "invalid_current_password"
}

export const SESSION_REVOKE_FAILURE: Record<string, string> = {
  session_not_found: "找不到该会话，或它不属于当前账号。",
  interactive_session_required: "API 令牌无法管理会话，请用网页登录后再试。",
}

export const PASSWORD_CHANGE_FAILURE: Record<string, string> = {
  invalid_current_password: "当前密码不正确。",
  interactive_session_required: "API 令牌无法修改密码，请用网页登录后再试。",
  authentication_required: "登录已过期，请重新登录。",
}
