/**
 * Personal API token contract. Mirrors
 * `backend/app/modules/auth/{api_tokens,schemas}.py`.
 *
 * ## The plaintext exists for exactly one request
 *
 * `create` returns `PersonalApiTokenCreated`, which is the view **plus** a
 * `token` field holding the only copy of the secret the system will ever have
 * (`api_tokens.py:153-172`). What gets stored is `sha256(plaintext)`
 * (`api_tokens.py:38-40`), and `PersonalApiTokenView` — the type every later
 * read returns — has no token field at all.
 *
 * So the create response is not a normal response. Refreshing the list does not
 * bring the token back, and a client that caches the create response and shows
 * it on every visit is quietly lying about a value that no longer exists. The
 * panel shows it once, says so, and drops it.
 *
 * ## `permissions: null` is not "no permissions"
 *
 * `PersonalApiTokenCreate.permissions` is `list[str] | None`, and `None` means
 * "inherit mine":
 *
 * ```python
 * requested = frozenset(body.permissions) if body.permissions is not None
 *             else context.permissions
 * ```
 * (`api.py:514-518`)
 *
 * An editor that sends `permissions: []` on purpose is asking for a token that
 * can do nothing at all, and `[]` is not falsy-checked anywhere on the way in —
 * the two are genuinely different requests. The form therefore never sends an
 * empty list to mean "same as me".
 *
 * ## The scope ceiling is the creator, checked server-side
 *
 * `permissions - allowed_permissions` is a 403 `api_token_scope_invalid`
 * (`api_tokens.py:128-136`). The form can narrow the picker against the
 * signed-in user's own permissions, but the server is the one that decides —
 * and an admin who pastes someone else's admin token is not creating a token,
 * they are creating a 403.
 */
import { api } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type ApiTokenView = {
  id: string
  name: string
  /** Sorted by the server (`api.py:472-474`). Never null. */
  permissions: string[]
  created_at: string
  /** `null` means it never expires — not "expires at the epoch". */
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

/** The create response. The `token` field appears here and nowhere else. */
export type ApiTokenCreated = ApiTokenView & { token: string }

export type ApiTokenCreate = {
  name: string
  /**
   * Omit entirely to inherit the creator's permissions. Do not send `[]` as a
   * shorthand for that — an empty list is a valid, useless token.
   */
  permissions?: string[]
  /** Must be timezone-aware and in the future (`api_tokens.py:138-151`). */
  expires_at?: string | null
}

/** The prefix every personal token carries (`api_tokens.py:18`). */
export const API_TOKEN_PREFIX = "znr_pat_"

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

export function listApiTokens(signal?: AbortSignal) {
  return api.get<ApiTokenView[]>("/api-tokens", signal)
}

export function createApiToken(body: ApiTokenCreate) {
  return api.post<ApiTokenCreated>("/api-tokens", body)
}

/**
 * Idempotent: a second revoke of the same token returns 204 with no complaint
 * (`api_tokens.py:195-197` only sets `revoked_at` when it is still null), and a
 * token belonging to somebody else is a 404 rather than a 403 — the endpoint
 * will not confirm that a foreign id exists.
 */
export function revokeApiToken(tokenId: string) {
  return api.del<void>(`/api-tokens/${tokenId}`)
}

/* -------------------------------------------------------------------------- */
/* Derived state                                                              */
/* -------------------------------------------------------------------------- */

export type ApiTokenStatus = "active" | "expired" | "revoked"

/**
 * Three dead-or-alive states, and the order matters.
 *
 * `revoked_at` wins over `expires_at`: a token revoked before it expired stays
 * revoked, and showing it as merely "expired" invites somebody to look for an
 * expiry date they can push forward — a token that was deliberately cut off
 * cannot be brought back by waiting.
 *
 * `now` is a parameter rather than a `Date.now()` call inside, because the
 * caller already has a render's worth of "now" and two different calls in one
 * render disagree at a boundary.
 */
export function apiTokenStatus(
  token: ApiTokenView,
  now: Date = new Date(),
): ApiTokenStatus {
  if (token.revoked_at) return "revoked"
  if (token.expires_at && new Date(token.expires_at) <= now) return "expired"
  return "active"
}

export const API_TOKEN_STATUS_LABEL: Record<ApiTokenStatus, string> = {
  active: "有效",
  expired: "已过期",
  revoked: "已吊销",
}

/**
 * What to say about a token that has never been used.
 *
 * `last_used_at` is only written on a successful authentication
 * (`api_tokens.py:70-71`), so `null` means "has never authenticated", which is
 * the normal state for a token minted seconds ago and worth saying plainly
 * rather than rendering as an empty timestamp.
 */
export function describeTokenUsage(token: ApiTokenView): string {
  return token.last_used_at ? "已使用" : "从未使用"
}

/* -------------------------------------------------------------------------- */
/* Build body                                                                 */
/* -------------------------------------------------------------------------- */

export type ApiTokenForm = {
  name: string
  /**
   * `null` = inherit. Distinct from `[]` = a token that can do nothing.
   */
  permissions: string[] | null
  /** Wall clock, or `null` for "never expires". */
  expiresAt: string | null
}

export type ApiTokenFormError = { field: keyof ApiTokenForm; message: string }

/**
 * Validate against the contract rather than against a guess at it.
 *
 * The expiry rule is the one worth spelling out: the server rejects a naive
 * datetime as `api_token_expiry_invalid` ("must include a timezone"), and
 * `new Date("2026-10-01T14:30")` in a browser is exactly that — it parses as
 * local time and sends no offset. A `<input type="datetime-local">` value is
 * therefore appended with the browser's own offset rather than sent bare.
 */
export function validateApiTokenForm(form: ApiTokenForm): ApiTokenFormError[] {
  const errors: ApiTokenFormError[] = []

  const name = form.name.trim()
  if (name === "") {
    errors.push({ field: "name", message: "请填写令牌名称" })
  } else if (name.length > 128) {
    errors.push({ field: "name", message: "名称最长 128 个字符" })
  }

  if (form.permissions !== null && form.permissions.length === 0) {
    errors.push({
      field: "permissions",
      message: "一个权限都不给的话，这个令牌无法完成任何操作",
    })
  }

  if (form.expiresAt) {
    const parsed = new Date(form.expiresAt)
    if (Number.isNaN(parsed.getTime())) {
      errors.push({ field: "expiresAt", message: "有效期无法解析" })
    } else if (parsed <= new Date()) {
      errors.push({ field: "expiresAt", message: "有效期必须是将来的时间" })
    }
  }

  return errors
}

/**
 * Turn a `<input type="datetime-local">` value into what the schema accepts.
 *
 * The value has no offset by construction. `new Date(value)` would parse it in
 * the browser's zone and then serialize back to UTC, which is right *only* by
 * accident — the operator typed a wall clock meaning their own time, and
 * sending the bare string is what makes the server reject it outright rather
 * than silently shifting it.
 */
export function localExpiryToIso(value: string): string | null {
  if (!value.trim()) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}
