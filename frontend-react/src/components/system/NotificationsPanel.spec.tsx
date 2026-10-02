import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { NotificationsPanel } from "./NotificationsPanel"
import { renderWithProviders } from "../../test-utils"
import { NOTIFICATIONS } from "../../lib/queries"
import type {
  NotificationDeliveryView,
  NotificationTargetView,
} from "../../api/notifications"

/**
 * The panel's whole reason to exist is the write-only secret.
 *
 * `url` and the SMTP password never come back from the server, so every test
 * below is really a statement about what the editor does *not* send: an
 * operator who opens the editor and presses save without typing must leave
 * both secrets exactly as they were, and the only way to guarantee that is for
 * the request body to carry no secret field at all.
 *
 * The tests that do send a secret assert on the **verb** (`url_action`), not
 * on a value — because `url: null` is the ambiguity the schema was designed to
 * remove, and an assertion that only checked "the body mentions the url" would
 * pass on exactly the wrong implementation.
 */

const SMTP: NotificationTargetView = {
  id: "t1",
  name: "主 SMTP",
  kind: "smtp",
  enabled: true,
  // Deliberately not `failure`: the notify type is rendered as a badge, and a
  // target badged 失败 next to a failed delivery in the log below is two
  // different meanings of one word in one screen.
  config: { notify_type: "info", password_reset: false },
  url_configured: true,
  credentials_configured: true,
}

const APPRISE: NotificationTargetView = {
  id: "t2",
  name: "企业微信",
  kind: "apprise",
  enabled: true,
  config: { notify_type: "warning", password_reset: true },
  url_configured: true,
  credentials_configured: false,
}

/** A target with no URL at all — legal in the read model, useless in practice. */
const URL_LESS: NotificationTargetView = {
  id: "t3",
  name: "占位目标",
  kind: "apprise",
  enabled: false,
  config: {},
  url_configured: false,
  credentials_configured: false,
}

const DELIVERY: NotificationDeliveryView = {
  id: "d1",
  alert_id: "a1",
  purpose: "alert",
  notification_target_id: "t1",
  state: "FAILED",
  attempt_count: 3,
  title: "前门：有人",
  body: "…",
  last_attempt_at: "2026-10-01T00:00:00Z",
  sent_at: null,
  last_error_code: "smtp_auth_failed",
  provider_message_id: null,
  correlation_id: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:05Z",
}

type Call = { method: string; url: string; body: unknown }

let calls: Call[] = []
/** Set by a test to make the next write fail with a specific backend code. */
let failure: { status: number; code: string; message: string } | null = null

afterEach(() => {
  calls = []
  failure = null
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderPanel(
  targets: NotificationTargetView[] = [SMTP, APPRISE],
  securityEmail: string | null = "t1",
  deliveries: NotificationDeliveryView[] = [],
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(NOTIFICATIONS.targets, targets)
  client.setQueryData(NOTIFICATIONS.securityEmail, { target_id: securityEmail })
  client.setQueryData(
    NOTIFICATIONS.deliveries({ targetId: undefined, alertId: undefined }),
    deliveries,
  )

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })

      if (method !== "GET") {
        if (failure) {
          return json(
            { error: { code: failure.code, message: failure.message } },
            failure.status,
          )
        }
        return json({})
      }
      // The security-email pointer lives under /notification-targets, so the
      // more specific path has to be matched first.
      if (url.includes("/notification-targets/security-email-default")) {
        return json({ target_id: securityEmail })
      }
      if (url.includes("/notification-deliveries")) return json(deliveries)
      if (url.includes("/notification-targets")) return json(targets)
      return json({})
    }),
  )

  return renderWithProviders(<NotificationsPanel />, { client })
}

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

/** The one method body of a secret, named by its visible field label. */
function secretGroup(label: string) {
  return screen.getByRole("group", { name: label })
}

function chooseSecret(label: string, action: "保持不变" | "替换" | "清空") {
  fireEvent.click(within(secretGroup(label)).getByRole("button", { name: action }))
}

/**
 * A target's row, scoped to the list.
 *
 * A target's name appears in three places at once — the row, the security
 * email dropdown and the delivery filter — so an unscoped text query is
 * ambiguous by construction rather than by accident.
 */
function targetRow(name: string) {
  const list = screen.getByRole("list", { name: "通知目标列表" })
  return within(list).getByText(name).closest("li") as HTMLElement
}

async function openEditorFor(name: string) {
  fireEvent.click(within(targetRow(name)).getByTitle("编辑"))
  await screen.findByText(/^编辑：/)
}

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 只写字段的三态协议", () => {
  it("打开编辑器后两个秘密都停在「保持不变」，保存不发送任何秘密字段", async () => {
    renderPanel()
    await openEditorFor("主 SMTP")

    // Both secrets default to keep, and say so.
    expect(within(secretGroup("服务器 URL")).getByText("已配置")).toBeTruthy()
    expect(within(secretGroup("SMTP 凭据")).getByText("已配置")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() => {
      expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(1)
    })

    const sent = callsTo("/notification-targets/t1", "PATCH")[0].body as Record<
      string,
      unknown
    >
    // Not one of these may appear. `url: null` in particular would be
    // indistinguishable from a clear, which is the ambiguity being avoided.
    expect(sent).not.toHaveProperty("url")
    expect(sent).not.toHaveProperty("url_action")
    expect(sent).not.toHaveProperty("smtp_credentials")
    expect(sent).not.toHaveProperty("credentials_action")
  })

  it("清空 URL 发送的是 url_action，不是 url: null", async () => {
    renderPanel()
    await openEditorFor("主 SMTP")
    chooseSecret("服务器 URL", "清空")
    expect(within(secretGroup("服务器 URL")).getByText("将清空")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() => {
      expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(1)
    })

    const sent = callsTo("/notification-targets/t1", "PATCH")[0].body as Record<
      string,
      unknown
    >
    expect(sent.url_action).toBe("clear")
    expect(sent).not.toHaveProperty("url")
  })

  it("替换 URL 不牵动已存的 SMTP 凭据", async () => {
    renderPanel()
    await openEditorFor("主 SMTP")
    chooseSecret("服务器 URL", "替换")
    fireEvent.change(within(secretGroup("服务器 URL")).getByLabelText("新的 URL"), {
      target: { value: "smtp://new:secret@mail.example.com" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() => {
      expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(1)
    })

    const sent = callsTo("/notification-targets/t1", "PATCH")[0].body as Record<
      string,
      unknown
    >
    expect(sent.url_action).toBe("replace")
    expect(sent.url).toBe("smtp://new:secret@mail.example.com")
    // The username and password are still stored server-side and must be
    // left alone by an unrelated URL edit.
    expect(sent).not.toHaveProperty("credentials_action")
    expect(sent).not.toHaveProperty("smtp_credentials")
  })

  it("替换却不填值会被挡住——空串会清掉已存的秘密且无法恢复", async () => {
    renderPanel()
    await openEditorFor("主 SMTP")
    chooseSecret("服务器 URL", "替换")
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    expect(
      screen.getByText("请填写新的 URL"),
    ).toBeTruthy()
    expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(0)
  })

  it("替换 SMTP 凭据时用户名与密码都要填", async () => {
    renderPanel()
    await openEditorFor("主 SMTP")
    chooseSecret("SMTP 凭据", "替换")
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    expect(screen.getByText("SMTP 凭据需要用户名")).toBeTruthy()
    expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(0)

    fireEvent.change(within(secretGroup("SMTP 凭据")).getByLabelText("用户名"), {
      target: { value: "noreply" },
    })
    expect(
      screen.getByText("请填写新密码——替换空密码会清掉已存的密码且无法恢复"),
    ).toBeTruthy()
    expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 密码重置的 mailto 约束", () => {
  it("开启密码重置后，URL 形状的规则在提交前就说清", async () => {
    renderPanel()
    await openEditorFor("主 SMTP")
    fireEvent.click(screen.getByRole("switch", { name: "用于密码重置" }))
    chooseSecret("服务器 URL", "替换")
    fireEvent.change(within(secretGroup("服务器 URL")).getByLabelText("新的 URL"), {
      target: { value: "smtp://a:b@mail.example.com" },
    })

    expect(
      screen.getByText(
        "用于密码重置时，URL 必须是 mailto: 或 mailtos: 形式，且不能带收件人路径",
      ),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    expect(callsTo("/notification-targets/t1", "PATCH")).toHaveLength(0)

    // mailtos: is equally valid, and mailto with a trailing slash is the one
    // form the backend regex allows (`service.py:119-134`).
    fireEvent.change(within(secretGroup("服务器 URL")).getByLabelText("新的 URL"), {
      target: { value: "mailtos://ops@example.com/" },
    })
    expect(
      screen.queryByText(
        "用于密码重置时，URL 必须是 mailto: 或 mailtos: 形式，且不能带收件人路径",
      ),
    ).toBeNull()
  })

  it("密码重置目标的 URL 不能被清空", async () => {
    // 企业微信 is the target carrying `password_reset: true`.
    renderPanel()
    await openEditorFor("企业微信")
    chooseSecret("Apprise URL", "清空")

    expect(
      screen.getByText("该目标承担密码重置，清空 URL 会让它永远收不到重置邮件。"),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    expect(callsTo("/notification-targets/t2", "PATCH")).toHaveLength(0)
  })

  it("第二个密码重置目标会得到指名道姓的解释，而不是一句英文 409", async () => {
    failure = {
      status: 409,
      code: "password_reset_target_conflict",
      message: "another target already handles password reset",
    }
    renderPanel()
    await openEditorFor("主 SMTP")
    fireEvent.click(screen.getByRole("switch", { name: "用于密码重置" }))
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(
        screen.getByText(
          "密码重置邮件只能由一个通知目标承担。请先在其它目标上关闭「用于密码重置」。",
        ),
      ).toBeTruthy()
    })
  })
})

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 新建", () => {
  it("URL 默认进入「替换」并要求填写，不会造出永远收不到通知的目标", async () => {
    renderPanel([])
    fireEvent.click(screen.getByRole("button", { name: /新建目标/ }))

    expect(within(secretGroup("Apprise URL")).getByText("将替换")).toBeTruthy()
    expect(screen.getByText("请填写新的 URL")).toBeTruthy()
    expect(callsTo("/notification-targets", "POST")).toHaveLength(0)

    fireEvent.change(screen.getByLabelText("目标名称"), {
      target: { value: "钉钉" },
    })
    fireEvent.change(within(secretGroup("Apprise URL")).getByLabelText("新的 URL"), {
      target: { value: "tgram://token@chat" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/notification-targets", "POST")).toHaveLength(1)
    })
    const sent = callsTo("/notification-targets", "POST")[0].body as Record<
      string,
      unknown
    >
    expect(sent.name).toBe("钉钉")
    expect(sent.url).toBe("tgram://token@chat")
  })

  it("重名会被本地挡住，不必等后端 409", async () => {
    renderPanel()
    fireEvent.click(screen.getByRole("button", { name: /新建目标/ }))
    fireEvent.change(screen.getByLabelText("目标名称"), {
      target: { value: "主 SMTP" },
    })
    expect(screen.getByText("名称已存在")).toBeTruthy()
    expect(callsTo("/notification-targets", "POST")).toHaveLength(0)
  })

  it("SMTP 凭据在新建时默认不发送——无认证是合法配置", async () => {
    renderPanel([])
    fireEvent.click(screen.getByRole("button", { name: /新建目标/ }))
    fireEvent.change(screen.getByLabelText("目标名称"), {
      target: { value: "内网 SMTP" },
    })
    fireEvent.click(screen.getByRole("switch", { name: "启用该目标" })) // back on
    fireEvent.change(screen.getByLabelText("目标类型"), {
      target: { value: "smtp" },
    })
    fireEvent.change(within(secretGroup("服务器 URL")).getByLabelText("新的 URL"), {
      target: { value: "smtp://mail.internal" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/notification-targets", "POST")).toHaveLength(1)
    })
    const sent = callsTo("/notification-targets", "POST")[0].body as Record<
      string,
      unknown
    >
    expect(sent.kind).toBe("smtp")
    expect(sent).not.toHaveProperty("smtp_credentials")
  })
})

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 安全邮件目标", () => {
  it("只列出 SMTP 目标：Apprise 无法承担这个角色", async () => {
    renderPanel()
    const select = (await screen.findByLabelText(
      "安全邮件目标",
    )) as HTMLSelectElement
    const options = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent)
    expect(options).toContain("主 SMTP")
    expect(options).not.toContain("企业微信")
  })

  it("清空安全邮件目标要先确认，取消则不写", async () => {
    renderPanel()
    const select = (await screen.findByLabelText(
      "安全邮件目标",
    )) as HTMLSelectElement

    fireEvent.change(select, { target: { value: "" } })
    const dialog = await screen.findByRole("alertdialog")
    expect(
      within(dialog).getByText(
        "将清空安全邮件目标，此后安全类邮件没有发送渠道。",
      ),
    ).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull()
    })
    expect(callsTo("/security-email-default", "PUT")).toHaveLength(0)
  })

  it("确认后写入空指针", async () => {
    renderPanel()
    const select = (await screen.findByLabelText(
      "安全邮件目标",
    )) as HTMLSelectElement
    fireEvent.change(select, { target: { value: "" } })

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(callsTo("/security-email-default", "PUT")).toHaveLength(1)
    })
    expect(callsTo("/security-email-default", "PUT")[0].body).toEqual({
      target_id: null,
    })
  })

  it("一个 SMTP 目标都没有时说明原因，而不是给一个空下拉框", async () => {
    renderPanel([APPRISE], null)
    expect(
      await screen.findByText("当前没有 SMTP 类型的目标，无法设置。"),
    ).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 测试发送与投递记录", () => {
  it("挂载时不发任何测试请求", async () => {
    renderPanel()
    await screen.findByText("通知目标")
    expect(callsTo("/test")).toHaveLength(0)
  })

  it("测试发送是一次真实 POST，带上自填收件人", async () => {
    renderPanel()
    const row = targetRow("主 SMTP")
    fireEvent.change(within(row).getByLabelText("测试收件人"), {
      target: { value: "  me@example.com  " },
    })
    fireEvent.click(within(row).getByRole("button", { name: /发送测试/ }))

    await waitFor(() => {
      expect(callsTo("/notification-targets/t1/test", "POST")).toHaveLength(1)
    })
    // Trimmed before it leaves: the server stores this string in a delivery
    // record and a trailing space is not something to discover later.
    expect(callsTo("/notification-targets/t1/test", "POST")[0].body).toEqual({
      recipient: "me@example.com",
    })
  })

  it("没有 URL 的目标不能发送测试", async () => {
    renderPanel([URL_LESS])
    const row = targetRow("占位目标")
    const send = within(row).getByRole("button", { name: /发送测试/ })
    expect((send as HTMLButtonElement).disabled).toBe(true)
  })

  it("失败投递露出错误码与重试次数", async () => {
    renderPanel([SMTP, APPRISE], "t1", [DELIVERY])
    const log = await screen.findByRole("list", { name: "投递记录列表" })
    expect(within(log).getByText("前门：有人")).toBeTruthy()
    expect(within(log).getByText("smtp_auth_failed")).toBeTruthy()
    expect(within(log).getByText(/第 3 次尝试/)).toBeTruthy()
    expect(within(log).getByText("失败")).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 删除", () => {
  it("删除不可逆，先确认；取消不删", async () => {
    renderPanel()
    fireEvent.click(within(targetRow("主 SMTP")).getByTitle("删除"))

    const dialog = await screen.findByRole("alertdialog")
    expect(within(dialog).getByText(/确定删除「主 SMTP」？/)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull()
    })
    expect(callsTo("/notification-targets/t1", "DELETE")).toHaveLength(0)
  })

  it("确认后删除", async () => {
    renderPanel()
    fireEvent.click(within(targetRow("主 SMTP")).getByTitle("删除"))

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }))

    await waitFor(() => {
      expect(callsTo("/notification-targets/t1", "DELETE")).toHaveLength(1)
    })
  })
})

/* -------------------------------------------------------------------------- */

describe("通知渠道 · 读取失败", () => {
  it("目标读不出来时说清是哪里坏了", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: { code: "boom", message: "通知服务未就绪" },
            }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    renderWithProviders(<NotificationsPanel />, { client })

    expect(await screen.findByText("无法读取通知目标")).toBeTruthy()
    expect(screen.getByText("通知服务未就绪")).toBeTruthy()
  })
})
