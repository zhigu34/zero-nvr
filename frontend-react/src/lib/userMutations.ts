import {
  createUser,
  issueUserPasswordReset,
  setUserCameraScope,
  setUserEnabled,
  updateUser,
  type CameraScopeUpdate,
  type UserCreate,
  type UserUpdate,
} from "../api/users"
import { ADMIN } from "./queries"
import { useSave } from "./save"

/**
 * Writes for the user administration screen.
 *
 * Everything invalidates the user list. Two of them also invalidate something
 * that is not a cache key but a **rendering decision**, which is the part
 * worth noting: enabling or disabling a user changes what the nav and the
 * route guards render, and those are derived from the signed-in session, not
 * from the user list. A stale "enabled" badge next to a correct table is the
 * failure mode; so is disabling yourself and having the shell keep claiming
 * otherwise.
 */

export function useCreateUser() {
  return useSave<UserCreate, unknown>({
    mutationFn: (body) => createUser(body),
    invalidates: [ADMIN.users],
    success: () => ({ title: "用户已创建" }),
    failure: (error) => ({
      title: "创建用户失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useUpdateUser(userId: string) {
  return useSave<UserUpdate, unknown>({
    mutationFn: (body) => updateUser(userId, body),
    invalidates: [ADMIN.users],
    success: () => ({ title: "用户已更新" }),
    failure: (error) => ({
      title: "更新用户失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

/**
 * Enable/disable is a POST to a dedicated endpoint, not a PATCH field — see
 * note 2 in `api/users.ts`. The optimistic-looking "已禁用" a PATCH would have
 * produced is exactly the silent drop this avoids.
 */
export function useSetUserEnabled() {
  // The branch is read off the **response**, not off the request: the server
  // returns the user as it now stands, and echoing back what we asked for
  // would let the toast claim a state the backend did not actually reach.
  return useSave<
    { userId: string; enabled: boolean },
    Awaited<ReturnType<typeof setUserEnabled>>
  >({
    mutationFn: ({ userId, enabled }) => setUserEnabled(userId, enabled),
    invalidates: [ADMIN.users],
    success: (user) =>
      user.enabled
        ? { title: "用户已启用" }
        : {
            title: "用户已禁用",
            detail: "该用户将无法登录；已签发的会话在后端下次校验时失效。",
          },
    failure: (error) => ({
      title: "操作失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

/**
 * Issues a one-time reset token. The result is deliberately **not** stored in
 * the query cache: there is no endpoint that can read it back, so caching it
 * would suggest it is recoverable when it is not. The caller holds it in
 * component state long enough to show it once.
 */
export function useIssueUserPasswordReset() {
  return useSave<string, Awaited<ReturnType<typeof issueUserPasswordReset>>>({
    mutationFn: (userId) => issueUserPasswordReset(userId),
    success: (issued) => ({
      title: "重置令牌已签发",
      detail: `有效期至 ${new Date(issued.expires_at).toLocaleString("zh-CN")}，只显示这一次。`,
    }),
    failure: (error) => ({
      title: "签发重置令牌失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

/**
 * Camera scope lives on its own endpoint, so a profile save and a scope save
 * can succeed independently. The screen keeps the two apart and says which
 * half is unsaved; merging them into one "Save" would leave the operator
 * unsure whether the scope took effect.
 */
export function useSetUserCameraScope(userId: string) {
  return useSave<CameraScopeUpdate, unknown>({
    mutationFn: (body) => setUserCameraScope(userId, body),
    invalidates: [ADMIN.userScope(userId), ADMIN.users],
    success: () => ({ title: "机位范围已保存" }),
    failure: (error) => ({
      title: "保存机位范围失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}
