import {
  changeOwnPassword,
  revokeSession,
  type PasswordChangeRequest,
} from "../api/account"
import { PASSWORD_CHANGE_FAILURE, SESSION_REVOKE_FAILURE } from "../api/account"
import { ACCOUNT } from "./queries"
import { useSave } from "./save"

/**
 * Every endpoint here needs an interactive session, so an API token gets 403
 * `interactive_session_required` rather than 401 — deliberately, so a leaked
 * token cannot lock its owner out of their own account.
 */

export function useRevokeSession() {
  return useSave<string, void>({
    mutationFn: (sessionId) => revokeSession(sessionId),
    invalidates: [ACCOUNT.sessions],
    success: () => ({ title: "会话已结束" }),
    failure: (error) => {
      const code = (error as { code?: string } | null)?.code
      return {
        title: "结束会话失败",
        detail: SESSION_REVOKE_FAILURE[code ?? ""] ??
          (error instanceof Error ? error.message : String(error)),
      }
    },
  })
}

/**
 * Revoking the session you are on returns 204 *and* clears your cookie, so the
 * next request 401s and the app bounces to login. The success message says that
 * up front — otherwise the navigation looks like a crash.
 */
export function useRevokeCurrentSession() {
  const revoke = useRevokeSession()
  return {
    ...revoke,
    mutateCurrent: (sessionId: string) =>
      revoke.mutate(sessionId, {
        onSuccess: () => {
          // No navigation here: the store's next request 401s and AuthGate
          // handles the redirect. Forcing it would race the cookie clearing.
        },
      }),
  }
}

/**
 * `POST /auth/password/change` **revokes every other session** and mints a new
 * one for this device (`auth/service.py:297-310`). That is the single most
 * surprising thing about the call, so it is in the success message rather than
 * buried: an operator whose other devices just signed out deserves to know why.
 */
export function useChangeOwnPassword(onChanged?: (user: unknown) => void) {
  return useSave<PasswordChangeRequest, unknown>({
    mutationFn: (body) => changeOwnPassword(body),
    invalidates: [ACCOUNT.sessions],
    success: () => ({
      title: "密码已修改",
      detail: "其它设备上的登录已全部失效，当前设备保持登录。",
    }),
    failure: (error) => {
      const code = (error as { code?: string } | null)?.code
      return {
        title: "修改密码失败",
        detail: PASSWORD_CHANGE_FAILURE[code ?? ""] ??
          (error instanceof Error ? error.message : String(error)),
      }
    },
    onSuccess: (data) => onChanged?.(data),
  })
}
