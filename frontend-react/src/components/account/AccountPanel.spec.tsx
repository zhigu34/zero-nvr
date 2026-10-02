import { QueryClient } from "@tanstack/react-query"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AccountPanel } from "./AccountPanel"
import { renderWithProviders } from "../../test-utils"
import { ACCOUNT } from "../../lib/queries"
import { formatClock } from "../../lib/format"
import { useAuthStore } from "../../stores/auth"
import {
  PASSWORD_CHANGE_FAILURE,
  SESSION_REVOKE_FAILURE,
  type SessionSummary,
} from "../../api/account"
import type { ApiTokenView } from "../../api/apiTokens"
import type { AuthUser } from "../../api/auth"

/**
 * Most of these tests are statements about what the page must **not** offer.
 *
 * The account contract is a list of absences — no profile endpoint, no email
 * verification, no reuse check, no bulk sign-out — and each one is a button or
 * a label that a naive implementation would add and that would then fail at
 * runtime:
 *
 * 1. **No edit-profile form.** Every submission of one is a 403
 *    (`PATCH /users/{id}` is somebody else's account). The page shows the
 *    profile read-only and says why.
 * 2. **No "resend verification" affordance.** Nothing sends mail and
 *    `email_verified` is `false` for every real user, so a button promising a
 *    verification mail is a button that cannot work.
 * 3. **No "last active".** `last_seen_at` is stamped once at creation
 *    (`auth/service.py:203`), so the fixtures below deliberately give it a
 *    *different* value from `created_at` — the row must render `created_at`.
 * 4. **A wrong current password is a field error**, not a sign-out. 400
 *    `invalid_current_password`, and this page has no router at all, so any
 *    navigation attempt would have thrown during render.
 * 5. **The current session's revoke clears the cookie.** The confirmation has
 *    to name that before the click.
 *
 * `last_seen_at` on every fixture is deliberately *not* equal to
 * `created_at`, which the server guarantees it is. A test that only ever fed
 * the real (equal) values could not tell the two columns apart.
 */

const CREATED = "2025-06-01T08:00:00Z"
const LAST_SEEN = "2026-01-01T00:00:00Z"
const EXPIRES = "2099-01-01T00:00:00Z"
const TOKEN_CREATED = "2025-06-01T08:00:00Z"
const PLAINTEXT = "znr_pat_plaintext_that_exists_once"

const CURRENT: SessionSummary = {
  id: "s-current",
  created_at: CREATED,
  last_seen_at: LAST_SEEN,
  expires_at: EXPIRES,
  current: true,
  client_info: {
    user_agent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    source_ip: "192.168.1.20",
  },
}

const OTHER: SessionSummary = {
  id: "s-phone",
  created_at: CREATED,
  last_seen_at: LAST_SEEN,
  expires_at: EXPIRES,
  current: false,
  client_info: {
    user_agent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    source_ip: "10.0.0.9",
  },
}

/** A sparse dict with nothing in it — `client_info` is nullable, not fixed. */
const NO_CLIENT: SessionSummary = {
  id: "s-headless",
  created_at: CREATED,
  last_seen_at: LAST_SEEN,
  expires_at: EXPIRES,
  current: false,
  client_info: null,
}

const TOKEN: ApiTokenView = {
  id: "tok-1",
  name: "grafana",
  permissions: ["camera.view"],
  created_at: TOKEN_CREATED,
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
}

const USER: AuthUser = {
  id: "u1",
  username: "zhi",
  display_name: "Zhi",
  email: "zhi@example.com",
  /** False for every real user: nothing outside tests ever sets it. */
  email_verified: false,
  roles: ["Administrator"],
  permissions: ["camera.view", "recording.view"],
}

const CURRENT_PASSWORD = "current-password-123"
const NEW_PASSWORD = "new-password-4567"

type Call = { method: string; url: string; body: unknown }
type Failure = {
  status: number
  code: string
  message: string
  /** Restricts the failure to one endpoint; omit to fail every request. */
  when?: string
}

let calls: Call[] = []
/** What the (fake) server currently holds; DELETE removes from it. */
let server: SessionSummary[] = []
let tokens: ApiTokenView[] = []
let failure: Failure | null = null

beforeEach(() => {
  useAuthStore.setState({ user: USER, status: "authenticated" })
})

afterEach(() => {
  // Unmount first. Vitest runs afterEach hooks in reverse registration order,
  // so resetting the store while the panel is still mounted would update a live
  // component outside `act` — once per test, and it drowns the real output.
  cleanup()
  calls = []
  server = []
  tokens = []
  failure = null
  useAuthStore.setState({ user: null, status: "anonymous" })
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderAccount(
  options: { sessions?: SessionSummary[]; seed?: boolean } = {},
) {
  const {
    sessions = [CURRENT, OTHER, NO_CLIENT],
    seed = true,
  } = options
  server = sessions.map((s) => ({ ...s }))
  tokens = [TOKEN]
  calls = []

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  // Seeded so the list renders synchronously; the queries are otherwise served
  // by the stub below.
  if (seed) client.setQueryData(ACCOUNT.sessions, server)

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })

      if (failure && (!failure.when || url.includes(failure.when))) {
        return json(
          { error: { code: failure.code, message: failure.message } },
          failure.status,
        )
      }

      if (method === "POST" && url.includes("/auth/password/change")) {
        return json({ ...USER })
      }
      if (method === "POST" && url.includes("/api-tokens")) {
        const sent = (body ?? {}) as { name: string }
        return json(
          {
            id: "tok-new",
            name: sent.name,
            permissions: USER.permissions,
            created_at: TOKEN_CREATED,
            expires_at: null,
            last_used_at: null,
            revoked_at: null,
            token: PLAINTEXT,
          },
          201,
        )
      }
      if (method === "DELETE") {
        const id = url.slice(url.lastIndexOf("/") + 1)
        server = server.filter((s) => s.id !== id)
        return new Response(null, { status: 204 })
      }
      if (url.includes("/sessions")) return json(server)
      if (url.includes("/api-tokens")) return json(tokens)
      return json({})
    }),
  )

  return renderWithProviders(<AccountPanel />, { client })
}

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

function passwordBodies(): Record<string, unknown>[] {
  return callsTo("/auth/password/change", "POST").map(
    (c) => c.body as Record<string, unknown>,
  )
}

/** The four top-level sections, each named so queries never fight over text. */
function region(name: string) {
  return screen.getByRole("region", { name })
}

function profile() {
  return region("账号资料")
}

function password() {
  return region("修改密码")
}

function sessions_() {
  return region("登录会话")
}

function tokens_() {
  return region("API 令牌")
}

/** A session row, found by the text that identifies it. */
function sessionRow(label: string) {
  const list = within(sessions_()).getByRole("list", { name: "会话列表" })
  return within(list).getByText(label).closest("li") as HTMLElement
}

function currentSessionRow() {
  return sessionRow("当前设备")
}

function revokeButton(row: HTMLElement) {
  return within(row).getByTitle("结束会话")
}

function fillPasswords(
  current: string,
  next: string,
  confirm: string = next,
) {
  fireEvent.change(within(password()).getByLabelText("当前密码"), {
    target: { value: current },
  })
  fireEvent.change(within(password()).getByLabelText("新密码"), {
    target: { value: next },
  })
  fireEvent.change(within(password()).getByLabelText("确认新密码"), {
    target: { value: confirm },
  })
}

function submitPassword() {
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }))
}

function toasts() {
  return within(screen.getByRole("region", { name: "通知" }))
}

/* -------------------------------------------------------------------------- */
/* 1. The profile is read-only                                                */
/* -------------------------------------------------------------------------- */

describe("账号资料 · 没有可编辑的字段", () => {
  it("资料区里没有任何可输入框：用户名、显示名、邮箱都不可改", () => {
    renderAccount()

    // Password inputs have no `textbox` role, so this count is a direct
    // statement about editable fields inside the profile.
    expect(within(profile()).queryAllByRole("textbox")).toHaveLength(0)
    expect(within(profile()).queryAllByRole("combobox")).toHaveLength(0)
    // No input anywhere on the page is pre-filled with an identity value.
    expect(screen.queryByDisplayValue(USER.username)).toBeNull()
    expect(screen.queryByDisplayValue(USER.display_name)).toBeNull()
    expect(screen.queryByDisplayValue(USER.email ?? "")).toBeNull()
  })

  it("没有「编辑资料」按钮，也不存在一个注定 403 的保存动作", () => {
    renderAccount()

    expect(
      screen.queryByRole("button", {
        name: /编辑资料|修改资料|保存资料|保存修改|重命名/,
      }),
    ).toBeNull()
    // And the limit is stated where the form would have been, so an operator
    // who came to rename themselves learns the reason rather than guessing.
    expect(within(profile()).getByText(/这里没有「编辑资料」/)).toBeTruthy()
    expect(
      within(profile()).getByText(/每按一次都只会换来一个 403/),
    ).toBeTruthy()
  })

  it("邮箱只读展示；email_verified 为 false 时说明验证不存在，也没有重发入口", () => {
    renderAccount()

    expect(within(profile()).getByText(USER.email as string)).toBeTruthy()
    expect(
      within(profile()).getByText(/没有重新发送验证的入口/),
    ).toBeTruthy()
    // The one thing a user with an unverified address always wants is the
    // button that does not exist.
    expect(
      screen.queryByRole("button", { name: /重新发送|发送验证|验证邮箱|重发/ }),
    ).toBeNull()
  })

  it("没有邮箱的账号说明原因，而不是显示一个空值", () => {
    useAuthStore.setState({ user: { ...USER, email: null } })
    renderAccount()

    expect(within(profile()).getByText("未设置")).toBeTruthy()
    expect(within(profile()).getByText(/没有「绑定邮箱」的接口/)).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */
/* 2. Password                                                                */
/* -------------------------------------------------------------------------- */

describe("修改密码", () => {
  it("发出 {current_password, new_password} 到 /auth/password/change，并说明其它设备已失效", async () => {
    renderAccount()
    // The consequence is on the screen *before* the click, and again in the
    // result — the operator's other devices are about to be signed out.
    expect(
      within(password()).getByText(/其它设备上的登录会全部失效/),
    ).toBeTruthy()

    fillPasswords(CURRENT_PASSWORD, NEW_PASSWORD)
    submitPassword()

    await waitFor(() => expect(passwordBodies()).toHaveLength(1))
    // The confirm field is local-only: `PasswordChangeRequest` has no third key.
    expect(passwordBodies()[0]).toEqual({
      current_password: CURRENT_PASSWORD,
      new_password: NEW_PASSWORD,
    })
    expect(callsTo("/sessions", "DELETE")).toHaveLength(0)

    expect(
      await within(password()).findByText(/其它设备上的登录已全部失效/),
    ).toBeTruthy()
  })

  it("400 invalid_current_password 是当前密码字段上的行内错误，不登出也不跳转", async () => {
    failure = {
      status: 400,
      code: "invalid_current_password",
      message: "current password is invalid",
    }
    renderAccount()
    fillPasswords("wrong-password-9999", NEW_PASSWORD)
    submitPassword()

    const field = within(password()).getByLabelText("当前密码")
    await waitFor(() =>
      expect(within(password()).getByText("当前密码不正确。")).toBeTruthy(),
    )
    expect(field.getAttribute("aria-invalid")).toBe("true")

    // No sign-out. The credentials were accepted; the typed value was wrong.
    expect(useAuthStore.getState().status).toBe("authenticated")
    expect(useAuthStore.getState().user?.username).toBe("zhi")
    // No navigation either — this page is rendered without a router at all, so
    // a redirect would have thrown rather than silently "worked".
    expect(within(password()).queryByText(/重新登录/)).toBeNull()
    expect(screen.queryByText(/session expired|invalid_current_password/)).toBeNull()
  })

  it("403 interactive_session_required 提示改用网页登录", async () => {
    failure = {
      status: 403,
      code: "interactive_session_required",
      message: "interactive session required",
      when: "/auth/password/change",
    }
    renderAccount()
    fillPasswords(CURRENT_PASSWORD, NEW_PASSWORD)
    submitPassword()

    await waitFor(() =>
      expect(within(password()).getByText("修改密码失败")).toBeTruthy(),
    )
    expect(
      within(password()).getByText(
        PASSWORD_CHANGE_FAILURE.interactive_session_required,
      ),
    ).toBeTruthy()
    // Still a form the operator can correct, not a dead screen.
    expect(
      (within(password()).getByLabelText("当前密码") as HTMLInputElement).value,
    ).toBe(CURRENT_PASSWORD)
  })

  it("空当前密码被挡住，不发请求", () => {
    renderAccount()
    fillPasswords("", NEW_PASSWORD)
    submitPassword()

    expect(within(password()).getByText("请填写当前密码")).toBeTruthy()
    expect(passwordBodies()).toHaveLength(0)
  })

  it("新密码不足 12 个字符被挡住，不发请求", () => {
    renderAccount()
    fillPasswords(CURRENT_PASSWORD, "short-123")
    submitPassword()

    expect(within(password()).getByText("新密码至少 12 个字符")).toBeTruthy()
    expect(passwordBodies()).toHaveLength(0)
  })

  it("两次输入的新密码不一致被挡住，不发请求", () => {
    renderAccount()
    fillPasswords(CURRENT_PASSWORD, NEW_PASSWORD, `${NEW_PASSWORD}-typo`)
    submitPassword()

    expect(within(password()).getByText("两次输入的新密码不一致")).toBeTruthy()
    expect(passwordBodies()).toHaveLength(0)
  })

  it("新密码与当前密码相同只是警告：仍可提交，且不声称服务端禁止", () => {
    renderAccount()
    const same = "identical-password-1"
    fillPasswords(same, same)

    expect(within(password()).getByText("新密码与当前密码相同")).toBeTruthy()
    // The server has no reuse check, so the form must not claim one.
    expect(within(password()).getByText(/服务端并不禁止这样做/)).toBeTruthy()
    expect(
      within(password()).queryByText(/不允许重复|禁止使用相同的密码|必须更换/),
    ).toBeNull()
    // A warning, not a block: the operator may legitimately want to re-send it.
    expect(
      (screen.getByRole("button", { name: "修改密码" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })

  it("没有凭空多出的密码规则", () => {
    renderAccount()

    const text = password().textContent ?? ""
    expect(text).toContain("12–256")
    expect(text).not.toMatch(/必须包含数字|必须含有大写|不能与用户名相似/)
  })

  it("挂载时不发送任何写请求", async () => {
    renderAccount()
    await screen.findByRole("list", { name: "会话列表" })

    expect(passwordBodies()).toHaveLength(0)
    expect(callsTo("/sessions", "DELETE")).toHaveLength(0)
    expect(callsTo("/api-tokens", "POST")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */
/* 3. Sessions                                                                */
/* -------------------------------------------------------------------------- */

describe("登录会话 · 结束会话", () => {
  it("结束其它会话先确认；取消不发 DELETE", async () => {
    renderAccount()
    fireEvent.click(revokeButton(sessionRow("Safari · 10.0.0.9")))

    const dialog = await screen.findByRole("alertdialog")
    expect(within(dialog).getByText(/该设备会立刻被登出/)).toBeTruthy()
    expect(within(dialog).getByText(/不可撤销/)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
    expect(callsTo("/sessions/s-phone", "DELETE")).toHaveLength(0)
  })

  it("确认后才发 DELETE，该行随之从列表里消失", async () => {
    renderAccount()
    fireEvent.click(revokeButton(sessionRow("Safari · 10.0.0.9")))
    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "结束会话" }))

    await waitFor(() =>
      expect(callsTo("/sessions/s-phone", "DELETE")).toHaveLength(1),
    )
    // Idempotent server-side, so the read after the write is what actually
    // removes the row.
    await waitFor(() =>
      expect(within(sessions_()).queryByText("Safari · 10.0.0.9")).toBeNull(),
    )
  })

  it("结束当前会话的确认先说明会被登出，确认前不发 DELETE", async () => {
    renderAccount()
    const row = currentSessionRow()
    expect(within(row).getByText("当前设备")).toBeTruthy()
    fireEvent.click(revokeButton(row))

    const dialog = await screen.findByRole("alertdialog")
    // The consequence has to be on screen before the click: the response
    // clears the cookie, so the next request 401s and the app leaves this page.
    expect(within(dialog).getByText(/本设备的 cookie 立即失效/)).toBeTruthy()
    expect(within(dialog).getByText(/跳到登录页/)).toBeTruthy()
    expect(within(dialog).getByText(/这是预期结果，不是崩溃/)).toBeTruthy()
    expect(callsTo("/sessions/s-current", "DELETE")).toHaveLength(0)

    fireEvent.click(within(dialog).getByRole("button", { name: "结束并登出" }))
    await waitFor(() =>
      expect(callsTo("/sessions/s-current", "DELETE")).toHaveLength(1),
    )
  })
})

describe("登录会话 · 读模型说了什么", () => {
  it("行上写「登录于」并取自 created_at，页面从不说「最后活跃」", () => {
    renderAccount()
    const row = sessionRow("Safari · 10.0.0.9")

    expect(within(row).getByText(/^登录于/)).toBeTruthy()
    // The fixture's `last_seen_at` differs from `created_at` precisely so this
    // assertion can tell the two columns apart.
    expect(row.textContent).toContain(formatClock(CREATED))
    expect(row.textContent).not.toContain(formatClock(LAST_SEEN))
    expect(document.body.textContent ?? "").not.toMatch(
      /最后活跃|最近活跃|最后活动|最近使用|last active|last seen/i,
    )
  })

  it("client_info 为 null 时说明「客户端信息未记录」，而不是留白或一串横线", () => {
    renderAccount()
    const row = sessionRow("客户端信息未记录")

    expect(within(row).getByText("客户端信息未记录")).toBeTruthy()
    // A missing dict must not fall through to formatClock's "—".
    expect(row.textContent).not.toContain("—")
  })

  it("到期时间用 sessionLifetime().daysLeft 算出来", () => {
    renderAccount()
    const expected = Math.floor(
      (new Date(EXPIRES).getTime() - Date.now()) / 86_400_000,
    )
    expect(
      within(sessionRow("Safari · 10.0.0.9")).getByText(`${expected} 天后过期`),
    ).toBeTruthy()
    expect(sessionRow("Safari · 10.0.0.9").textContent).toContain("到期于")
  })

  it("没有「一键退出其它设备」这类批量按钮", () => {
    renderAccount()

    expect(
      screen.queryByRole("button", {
        name: /退出所有|全部退出|一键登出|登出其它|退出其它设备/,
      }),
    ).toBeNull()
    // One row, one DELETE: no bulk endpoint exists to make it atomic.
    expect(within(sessions_()).getByText(/没有「一键退出其它设备」的接口/)).toBeTruthy()
  })

  it("一条会话都没有时给出空状态而不是空白", () => {
    renderAccount({ sessions: [] })
    expect(
      within(sessions_()).getByText("没有其它登录会话"),
    ).toBeTruthy()
  })
})

describe("登录会话 · 失败", () => {
  it("404 session_not_found 的说法不会暗示这条会话刚被删掉", async () => {
    failure = {
      status: 404,
      code: "session_not_found",
      message: "session not found",
      when: "/sessions/s-phone",
    }
    renderAccount()
    fireEvent.click(revokeButton(sessionRow("Safari · 10.0.0.9")))
    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "结束会话" }))

    await waitFor(() => expect(toasts().getByText("结束会话失败")).toBeTruthy())
    // Ownership is masked server-side, so "not found" also covers "not yours".
    expect(
      toasts().getByText(SESSION_REVOKE_FAILURE.session_not_found),
    ).toBeTruthy()
    expect(screen.queryByText("session not found")).toBeNull()
    expect(document.body.textContent ?? "").not.toMatch(/刚刚删除|刚才已移除|已删除该会话/)
    // And the row is still there: a failed write did not drop it locally.
    expect(sessionRow("Safari · 10.0.0.9")).toBeTruthy()
  })

  it("读取会话失败时给出可读的错误面，而不是空白页", async () => {
    failure = {
      status: 500,
      code: "internal_error",
      message: "internal server error",
      when: "/sessions",
    }
    renderAccount({ seed: false })

    expect(await within(sessions_()).findByText("无法读取登录会话")).toBeTruthy()
    // The rest of the page is independent of that one read.
    expect(within(profile()).getByText(USER.email as string)).toBeTruthy()
    expect(within(password()).getByLabelText("当前密码")).toBeTruthy()
    expect(within(tokens_()).getByRole("list", { name: "令牌列表" })).toBeTruthy()
  })

  it("用令牌访问时提示改用网页登录，而不是显示后端英文原文", async () => {
    failure = {
      status: 403,
      code: "interactive_session_required",
      message: "interactive session required",
      when: "/sessions",
    }
    renderAccount({ seed: false })

    expect(await within(sessions_()).findByText("无法读取登录会话")).toBeTruthy()
    expect(
      within(sessions_()).getByText(
        SESSION_REVOKE_FAILURE.interactive_session_required,
      ),
    ).toBeTruthy()
    expect(screen.queryByText("interactive session required")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */
/* 4. Embedded API tokens                                                     */
/* -------------------------------------------------------------------------- */

describe("API 令牌 · 嵌在这一页", () => {
  it("令牌面板被渲染出来并且可用：列表在，也能新建一条", async () => {
    renderAccount()
    await within(tokens_()).findByRole("list", { name: "令牌列表" })

    expect(within(tokens_()).getByText("grafana")).toBeTruthy()
    fireEvent.change(within(tokens_()).getByLabelText("令牌名称"), {
      target: { value: "备份脚本" },
    })
    fireEvent.click(within(tokens_()).getByRole("button", { name: "创建令牌" }))

    await waitFor(() => expect(callsTo("/api-tokens", "POST")).toHaveLength(1))
    expect(await screen.findByText(PLAINTEXT)).toBeTruthy()
  })

  it("没有「代他人管理令牌」的入口——这不是管理员的资源", () => {
    renderAccount()

    // `/api-tokens` is the signed-in account's own resource; there is no
    // `/users/{id}/tokens`, so a user picker here would offer nothing.
    expect(within(tokens_()).queryByRole("combobox")).toBeNull()
    expect(
      screen.queryByRole("textbox", { name: /用户|账号|选择/ }),
    ).toBeNull()
    expect(
      screen.queryByRole("button", {
        name: /代他人|其它用户|所有用户|某个用户|用户令牌/,
      }),
    ).toBeNull()
  })
})
