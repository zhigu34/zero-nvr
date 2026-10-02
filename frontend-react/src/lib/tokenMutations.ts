import {
  createApiToken,
  revokeApiToken,
  type ApiTokenCreate,
  type ApiTokenCreated,
  type ApiTokenForm,
} from "../api/apiTokens"
import { localExpiryToIso } from "../api/apiTokens"
import { TOKENS } from "./queries"
import { useSave } from "./save"

/**
 * Writes for personal API tokens.
 *
 * The bodies are built here rather than in the panel for one reason that is
 * easy to get wrong: `permissions: null` means "inherit mine" and
 * `permissions: []` means "a token that can do nothing". Those are different
 * requests, and the difference is a `JSON.stringify` behaviour, so it cannot
 * be left to a form to express.
 */

/**
 * Typed as `ApiTokenCreated` rather than `unknown` on purpose: the plaintext
 * only exists in this one response, so the panel has to read it off the
 * mutation result. Leaving it `unknown` would push a cast to the call site —
 * and a cast there is exactly the kind of thing that survives long after the
 * reason for it has been forgotten.
 */
export function useCreateApiToken() {
  return useSave<ApiTokenCreate, ApiTokenCreated>({
    mutationFn: (body) => createApiToken(body),
    invalidates: [TOKENS.list],
    // No detail line: the panel has to show the plaintext itself, and a toast
    // that said "created" while the token scrolled past would be worse than
    // saying nothing.
    success: () => ({ title: "令牌已创建" }),
    failure: (error) => ({
      title: "创建令牌失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * Revocation has no undo endpoint, so it is irreversible and the panel asks
 * first. It is also idempotent server-side, which is why a retry here is
 * harmless even though `useSave` never retries.
 */
export function useRevokeApiToken() {
  return useSave<string, void>({
    mutationFn: (tokenId) => revokeApiToken(tokenId),
    invalidates: [TOKENS.list],
    success: () => ({ title: "令牌已吊销" }),
    failure: (error) => ({
      title: "吊销失败",
      detail: describeFailure(error),
    }),
  })
}

/**
 * Translate the form into the request body.
 *
 * The expiry goes through `localExpiryToIso` because a
 * `<input type="datetime-local">` value carries no offset, and the schema
 * rejects a naive datetime outright — the operator would see
 * `api_token_expiry_invalid` for a date that looks perfectly valid on screen.
 */
export function apiTokenCreateBody(form: ApiTokenForm): ApiTokenCreate {
  const body: ApiTokenCreate = { name: form.name.trim() }
  if (form.permissions !== null) {
    body.permissions = [...form.permissions]
  }
  const expiresAt = form.expiresAt ? localExpiryToIso(form.expiresAt) : null
  if (expiresAt) body.expires_at = expiresAt
  return body
}

/**
 * Three of these codes name a rule the operator broke rather than a fault:
 *
 * - `api_token_scope_invalid` — the requested permissions exceed the creator's
 *   own. The 403 message does not say which permission.
 * - `api_token_expiry_invalid` — either naive (no timezone) or not in the
 *   future. Two different mistakes, one code.
 * - `api_token_not_found` — a 404, which is also what a token owned by
 *   somebody else returns, so it must not be reported as "it is gone".
 */
function describeFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  if (code === "api_token_scope_invalid") {
    return "令牌权限不能超过你当前的权限。请先移除非管理员专属的权限。"
  }
  if (code === "api_token_expiry_invalid") {
    return "有效期无效：必须带时区，且是将来的时间。"
  }
  if (code === "api_token_name_invalid") {
    return "名称不能为空（最长 128 个字符）。"
  }
  if (code === "api_token_not_found") {
    return "找不到该令牌，或它不属于当前账号。"
  }
  return error instanceof Error ? error.message : String(error)
}
