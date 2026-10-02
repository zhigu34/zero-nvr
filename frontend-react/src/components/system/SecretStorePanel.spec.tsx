import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SecretStorePanel } from "./SecretStorePanel"
import { renderWithProviders } from "../../test-utils"
import { SECRET_STORE } from "../../lib/queries"
import {
  describeRotation,
  rotationBlockedReason,
  SECRET_STORE_STATUS_LABEL,
  type SecretStoreHealth,
  type SecretStoreRotation,
} from "../../api/secretStore"

/**
 * The panel is a ladder, and the tests below are mostly about which rung
 * permits a write.
 *
 * The one that matters is `ERROR`. `rotate_records` decrypts every record
 * before it writes anything (`secret_store.py:474-485`), so a rotate pressed
 * from that state is a request that throws partway through and leaves the
 * operator with a 500 that says nothing about the record that could not be
 * read. A naive panel gates the button on `status === "ROTATION_REQUIRED"`,
 * or worse on the server's own `rotation_ready`, and would offer exactly that
 * write. Hence the contradictory payload test below: the server field says
 * yes, the unreadable count says no, and the count wins.
 *
 * The second theme is that the three statuses are three different situations
 * rather than three words for one. A panel that renders only a coloured dot
 * passes a screenshot review and fails the operator.
 */

const HEALTHY: SecretStoreHealth = {
  status: "OK",
  total_records: 12,
  current_records: 12,
  stale_records: 0,
  unreadable_records: 0,
  previous_key_count: 0,
  primary_key_id: "key-2026-02",
  rotation_ready: false,
}

const STALE: SecretStoreHealth = {
  status: "ROTATION_REQUIRED",
  total_records: 12,
  current_records: 9,
  stale_records: 3,
  unreadable_records: 0,
  previous_key_count: 1,
  primary_key_id: "key-2026-02",
  rotation_ready: true,
}

const BROKEN: SecretStoreHealth = {
  status: "ERROR",
  total_records: 12,
  current_records: 8,
  stale_records: 4,
  unreadable_records: 2,
  previous_key_count: 1,
  primary_key_id: "key-2026-02",
  rotation_ready: false,
}

/** The server's own answer contradicts the counts it shipped alongside them. */
const LIES_ABOUT_READINESS: SecretStoreHealth = {
  ...BROKEN,
  rotation_ready: true,
}

/** After a real rotation: everything moved to the primary key. */
const ROTATED: SecretStoreRotation = {
  total_records: 12,
  rotated_records: 3,
  already_current_records: 9,
  // The superseded key stays in the config, so it stays in the count too —
  // rotation moves records, it does not unload keys.
  health: {
    ...STALE,
    status: "OK",
    current_records: 12,
    stale_records: 0,
    rotation_ready: false,
  },
}

const NOTHING_TO_DO: SecretStoreRotation = {
  total_records: 12,
  rotated_records: 0,
  already_current_records: 12,
  health: HEALTHY,
}

type Call = { method: string; url: string; body: unknown }

let calls: Call[] = []
/** Swapped by the write handler, so the refetch sees the post-rotation truth. */
let report: SecretStoreHealth
let rotation: SecretStoreRotation | null = null
let readError: { status: number; code: string; message: string } | null = null
let writeError: { status: number; code: string; message: string } | null = null

afterEach(() => {
  calls = []
  report = HEALTHY
  rotation = null
  readError = null
  writeError = null
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderPanel(health: SecretStoreHealth = HEALTHY) {
  report = health
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  // Seeded rather than fetched so a test starts on a settled report; the read
  // is real work on the server and the panel must not refetch it on mount.
  client.setQueryData(SECRET_STORE.health, health)

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })

      if (method !== "GET") {
        if (writeError) {
          return json(
            { error: { code: writeError.code, message: writeError.message } },
            writeError.status,
          )
        }
        if (!rotation) return json({})
        // The response carries the report taken after the rotation
        // (`api.py:253-254`); the refetch has to agree with it.
        report = rotation.health
        return json(rotation)
      }

      if (readError) {
        return json(
          { error: { code: readError.code, message: readError.message } },
          readError.status,
        )
      }
      return json(report)
    }),
  )

  return renderWithProviders(<SecretStorePanel />, { client })
}

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

/* ------------------------------------------------- scoping, never indices */

function statusGroup() {
  return screen.getByRole("group", { name: "密钥环状态" })
}

function statsGroup() {
  return screen.getByRole("group", { name: "密钥环统计" })
}

function rotateGroup() {
  return screen.getByRole("group", { name: "密钥轮换" })
}

function rotateButton() {
  return within(rotateGroup()).getByRole("button", { name: /轮换/ })
}

function toasts() {
  return screen.getByRole("region", { name: "通知" })
}

async function rotateAndConfirm(rotationResult: SecretStoreRotation) {
  rotation = rotationResult
  fireEvent.click(rotateButton())
  const dialog = await screen.findByRole("alertdialog")
  fireEvent.click(within(dialog).getByRole("button", { name: "轮换" }))
}

/* -------------------------------------------------------------------------- */

describe("密钥环 · 三个状态是一段阶梯", () => {
  it("OK：没有可轮换的记录，按钮不可用", async () => {
    renderPanel(HEALTHY)
    await screen.findByText("正常")

    expect((rotateButton() as HTMLButtonElement).disabled).toBe(true)
    // The reason is shown even here, so "nothing to do" never looks like a
    // broken button.
    expect(
      within(rotateGroup()).getByText(rotationBlockedReason(HEALTHY)!),
    ).toBeTruthy()
    expect(rotationBlockedReason(HEALTHY)).toBe("没有待轮换的记录。")
  })

  it("ROTATION_REQUIRED：按钮可用，并且说清有多少条要重写", async () => {
    renderPanel(STALE)
    await screen.findByText("需要轮换")

    expect((rotateButton() as HTMLButtonElement).disabled).toBe(false)
    expect(within(statsGroup()).getByText(/其中 9 条在当前密钥上，3 条还在旧密钥上/)).toBeTruthy()
    expect(within(statusGroup()).getByText(/有 3 条记录仍用旧密钥加密/)).toBeTruthy()
  })

  it("ERROR：按钮不可用，并点名是几条记录解不开", async () => {
    // The single most important assertion in this file: an ERROR report must
    // not offer a write that is known to throw partway.
    renderPanel(BROKEN)
    await screen.findByText("存在无法解密的记录")

    expect((rotateButton() as HTMLButtonElement).disabled).toBe(true)
    // The reason names the count, so "fix it" is an action an operator can take.
    expect(within(rotateGroup()).getByText(/2 条记录无法解密/)).toBeTruthy()
    // …and the reason stays on screen rather than the button disappearing.
    expect(within(rotateGroup()).getByRole("button", { name: /轮换/ })).toBeTruthy()
  })

  it("ERROR：即使 rotation_ready 说可以，也照样不可用", async () => {
    // The contradictory payload. A panel gating on `rotation_ready` alone
    // would light this button up and hand the operator a 500.
    renderPanel(LIES_ABOUT_READINESS)
    await screen.findByText("存在无法解密的记录")

    expect((rotateButton() as HTMLButtonElement).disabled).toBe(true)
    expect(rotationBlockedReason(LIES_ABOUT_READINESS)).toContain("2 条记录无法解密")
  })

  it("三个状态给出三个可读的说法，而不是三个圆点", async () => {
    const seen: string[] = []
    for (const health of [HEALTHY, STALE, BROKEN]) {
      const { unmount } = renderPanel(health)
      const label = within(statusGroup()).getByText(
        SECRET_STORE_STATUS_LABEL[health.status],
      )
      seen.push(label.textContent ?? "")
      // The tone is carried by the text as well as the dot, so the three
      // outcomes differ for anyone who cannot see the colour.
      expect(label.className).toMatch(/text-status-/)
      unmount()
    }
    expect(new Set(seen).size).toBe(3)
  })
})

/* -------------------------------------------------------------------------- */

describe("密钥环 · 计数", () => {
  it("总数是当前密钥加旧密钥，不可解密的记录不另算一遍", async () => {
    // 8 current + 4 stale = 12. The 2 unreadable records are a *subset* of
    // those 12, not a thirteenth bucket — a panel that adds them up shows a
    // store that does not exist.
    renderPanel(BROKEN)
    await screen.findByText("存在无法解密的记录")

    expect(within(statsGroup()).getByText("12 条")).toBeTruthy()
    expect(within(statsGroup()).getByText(/2 条，用已加载的密钥都解不开/)).toBeTruthy()
  })

  it("计数为 0 读起来是「没问题」，不是「没数据」", async () => {
    renderPanel(HEALTHY)
    await screen.findByText("正常")

    expect(within(statsGroup()).getByText("全部 12 条都在当前密钥上。")).toBeTruthy()
    expect(within(statsGroup()).getByText("0 条，没有任何记录读不出来")).toBeTruthy()
    expect(within(statsGroup()).getByText("0 个，只加载了当前密钥")).toBeTruthy()
  })

  it("同一个 0 在 ERROR 下换成另一句话，不复用「正常」的说法", async () => {
    renderPanel(BROKEN)
    await screen.findByText("存在无法解密的记录")

    expect(within(statsGroup()).queryByText("0 条，没有任何记录读不出来")).toBeNull()
  })

  it("当前密钥 ID 是一个标识，不是密钥本身", async () => {
    renderPanel(STALE)
    await screen.findByText("需要轮换")

    expect(within(statsGroup()).getByText("key-2026-02")).toBeTruthy()
    expect(within(statsGroup()).getByText("这是标识，不是密钥本身。")).toBeTruthy()
    expect(within(statsGroup()).getByText(/1 个（已被取代/)).toBeTruthy()
  })

  it("挂载时不写任何东西——这份报告只是读", async () => {
    renderPanel(STALE)
    await screen.findByText("需要轮换")

    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("密钥环 · 轮换", () => {
  it("不可逆的操作要先确认，确认框说清会改什么", async () => {
    renderPanel(STALE)
    fireEvent.click(rotateButton())

    const dialog = await screen.findByRole("alertdialog")
    // The count and the target key are both named, so "yes" is an informed
    // answer rather than a reflex.
    expect(within(dialog).getByText(/3 条仍在旧密钥上的记录/)).toBeTruthy()
    expect(within(dialog).getByText(/key-2026-02/)).toBeTruthy()
    expect(within(dialog).getByText(/没有任何接口能把它们退回旧密钥/)).toBeTruthy()
  })

  it("取消不写任何东西", async () => {
    renderPanel(STALE)
    fireEvent.click(rotateButton())

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull()
    })
    expect(callsTo("/secret-store/rotate")).toHaveLength(0)
  })

  it("确认后恰好发一次轮换请求", async () => {
    renderPanel(STALE)
    await rotateAndConfirm(ROTATED)

    await waitFor(() => {
      expect(callsTo("/secret-store/rotate", "POST")).toHaveLength(1)
    })
  })

  it("成功时播报响应里的计数，并且按钮跟随返回的 health", async () => {
    renderPanel(STALE)
    await rotateAndConfirm(ROTATED)

    // The numbers come from the response, not from a hardcoded "done".
    await waitFor(() => {
      expect(within(toasts()).getByText(describeRotation(ROTATED))).toBeTruthy()
    })
    expect(within(toasts()).getByText("已重写 3 条 / 共 12 条，其余 9 条本就是当前密钥。")).toBeTruthy()

    // The mutation returns the post-rotation report and invalidates the read,
    // so the button must end up matching the new health — not stay enabled
    // next to a store that no longer has anything to rotate.
    await waitFor(() => {
      expect(screen.getByText("正常")).toBeTruthy()
    })
    expect((rotateButton() as HTMLButtonElement).disabled).toBe(true)
  })

  it("没有记录被重写时明说没有，而不是宣布轮换成功", async () => {
    // `rotated_records: 0` is a legal answer. Claiming a rotation happened
    // would credit the operator with work the server says it did not do.
    renderPanel(STALE)
    await rotateAndConfirm(NOTHING_TO_DO)

    await waitFor(() => {
      expect(within(toasts()).getByText(describeRotation(NOTHING_TO_DO))).toBeTruthy()
    })
    expect(
      within(toasts()).getByText("没有记录需要重写（12 条均已是当前密钥）。"),
    ).toBeTruthy()
    expect(within(toasts()).queryByText(/已重写/)).toBeNull()
  })

  it("失败时播报失败，不谎报成功", async () => {
    // A key can disappear between the read and the click, so the button being
    // disabled is not a guarantee the request will land.
    writeError = {
      status: 500,
      code: "secret_store_rotation_failed",
      message: "轮换中断：有记录无法解密",
    }
    renderPanel(STALE)
    await rotateAndConfirm(ROTATED)

    await waitFor(() => {
      expect(within(toasts()).getByText("轮换失败")).toBeTruthy()
    })
    expect(within(toasts()).getByText("轮换中断：有记录无法解密")).toBeTruthy()
    expect(within(toasts()).queryByText("密钥环已轮换")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("密钥环 · 读取失败", () => {
  it("读不出来时给出可读的失败面，而不是一片空白", async () => {
    // A blank panel here reads as "no records", which is the one conclusion
    // the operator must not draw from a request that never came back.
    readError = { status: 503, code: "boom", message: "密钥环未加载" }
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: { code: readError!.code, message: readError!.message },
            }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    renderWithProviders(<SecretStorePanel />, { client })

    expect(await screen.findByText("无法读取密钥环状态")).toBeTruthy()
    expect(screen.getByText("密钥环未加载")).toBeTruthy()
    // No counts, and above all no rotate button to press on a report that
    // was never received.
    expect(screen.queryByRole("group", { name: "密钥环统计" })).toBeNull()
    expect(screen.queryByRole("button", { name: /轮换/ })).toBeNull()
  })
})
