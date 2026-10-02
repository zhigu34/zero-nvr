import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CameraGroupsPanel } from "./CameraGroupsPanel"
import { renderWithProviders } from "../../test-utils"
import { ADMIN, CAMS } from "../../lib/queries"
import { type CameraSummary } from "../../api/cameras"
import { type CameraGroupView } from "../../api/cameraGroups"

/**
 * 摄像机组：四个摄像机，其中 `c2`、`c3` 同时属于两个分组。
 *
 * The overlap is deliberate. A "covers N cameras" figure that adds instead of
 * unioning would report 6 for `园区` instead of 4, and that is the number an
 * operator reads as "how much does granting this group actually hand out".
 *
 * The three per-group counts are 1 / 2 / 3 on purpose. Rows nest, so a parent
 * row's scope contains its children's text as well, and equal counts would make
 * every count assertion ambiguous the moment a second child is added.
 */
function camera(id: string, name: string): CameraSummary {
  return {
    id,
    name,
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: null,
    storage_label: null,
    adapter_type: "onvif",
    time_sync_mode: "monitor",
    ptz_capable: false,
    manufacturer: null,
    model: null,
    form_factor: "box",
    ip: null,
    port: null,
    rtsp_path: null,
    sub_rtsp_path: null,
    video_codec: null,
    width: null,
    height: null,
    fps: null,
    audio_codec: null,
    connectivity_status: "unknown",
    last_probe_at: null,
    last_online_at: null,
  }
}

const CAMERAS = [
  camera("c1", "门口"),
  camera("c2", "院子"),
  camera("c3", "车库"),
  camera("c4", "仓库"),
]

const GROUPS: CameraGroupView[] = [
  { id: "g1", name: "园区", description: "全园区", parent_id: null, camera_ids: ["c1"] },
  { id: "g2", name: "东区", description: null, parent_id: "g1", camera_ids: ["c2", "c3"] },
  {
    id: "g3",
    name: "西区",
    description: null,
    parent_id: "g1",
    camera_ids: ["c2", "c3", "c4"],
  },
]

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
  groups: CameraGroupView[] = GROUPS,
  cameras: CameraSummary[] = CAMERAS,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(ADMIN.cameraGroups, groups)
  client.setQueryData(CAMS.list(false), cameras)

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
      if (url.includes("/camera-groups")) return json(groups)
      if (url.includes("/cameras")) return json(cameras)
      return json({})
    }),
  )

  return renderWithProviders(<CameraGroupsPanel />, { client })
}

function callsTo(fragment: string, method?: string) {
  return calls.filter(
    (c) => c.url.includes(fragment) && (!method || c.method === method),
  )
}

/**
 * A group's row, scoped to the list.
 *
 * Group names repeat across the panel — the row, the editor's parent dropdown
 * and the editor's own heading — so an unscoped text query is ambiguous by
 * construction. Note that a row's scope also contains its children's rows, which
 * is why the action buttons carry the group name in their own label.
 */
function rowOf(name: string): HTMLElement {
  const list = screen.getByRole("list", { name: "分组列表" })
  return within(list).getByText(name).closest("li") as HTMLElement
}

function editor() {
  return screen.getByRole("dialog", { name: "分组编辑器" })
}

function saveButton() {
  return within(editor()).getByRole("button", { name: "保存" }) as HTMLButtonElement
}

function memberPicker() {
  return within(editor()).getByRole("group", { name: "摄像机成员" })
}

async function openEditorFor(name: string) {
  fireEvent.click(
    within(rowOf(name)).getByRole("button", { name: `编辑分组 ${name}` }),
  )
  await screen.findByRole("dialog", { name: "分组编辑器" })
}

async function startCreate() {
  fireEvent.click(screen.getByRole("button", { name: /新建分组/ }))
  await screen.findByRole("dialog", { name: "分组编辑器" })
}

function toggleCamera(name: string, on: boolean) {
  const box = within(memberPicker()).getByRole("checkbox", { name })
  expect((box as HTMLInputElement).checked).toBe(!on)
  fireEvent.click(box)
}

/** The one PATCH sent for `id`, as a plain object for key-by-key assertions. */
function patchTo(id: string) {
  return callsTo(`/camera-groups/${id}`, "PATCH")[0]?.body as Record<string, unknown>
}

/* -------------------------------------------------------------------------- */

describe("摄像机分组 · 成员是一次性替换，不是增量", () => {
  it("加一台摄像机发送的是完整成员列表", async () => {
    renderPanel()
    await openEditorFor("东区")

    toggleCamera("仓库", true)
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g2", "PATCH")).toHaveLength(1)
    })
    // The whole point: `c2` and `c3` were not touched but still have to travel,
    // because the endpoint deletes every membership and re-inserts
    // (`groups.py:154-168`).
    expect(patchTo("g2")).toEqual({ camera_ids: ["c2", "c3", "c4"] })
  })

  it("取消勾选全部发送 camera_ids: []，而不是省略这个键", async () => {
    renderPanel()
    await openEditorFor("西区") // c2 + c3 + c4

    toggleCamera("院子", false)
    toggleCamera("车库", false)
    toggleCamera("仓库", false)
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g3", "PATCH")).toHaveLength(1)
    })
    // Omitting the key would mean "keep the members", so the empty group would
    // silently keep all three of them.
    expect(patchTo("g3")).toEqual({ camera_ids: [] })
  })

  it("只改名称时根本不发送 camera_ids", async () => {
    renderPanel()
    await openEditorFor("东区")

    fireEvent.change(within(editor()).getByLabelText("分组名称"), {
      target: { value: "东区新" },
    })
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g2", "PATCH")).toHaveLength(1)
    })
    expect(patchTo("g2")).toEqual({ name: "东区新" })
    expect(patchTo("g2")).not.toHaveProperty("camera_ids")
  })

  it("列表里看不到的成员不会被顺手删掉", async () => {
    // A retired camera the caller cannot list. Rebuilding the picker from the
    // visible rows would drop it on any unrelated save.
    const groups: CameraGroupView[] = [
      { id: "g1", name: "旧组", description: null, parent_id: null, camera_ids: ["c-gone"] },
    ]
    renderPanel(groups)
    await openEditorFor("旧组")

    expect(
      within(editor()).getByText(/有 1 个成员没有出现在摄像机列表里/),
    ).toBeTruthy()

    fireEvent.change(within(editor()).getByLabelText("分组名称"), {
      target: { value: "旧组新" },
    })
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g1", "PATCH")).toHaveLength(1)
    })
    expect(patchTo("g1")).toEqual({ name: "旧组新" })
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机分组 · 留空不是保持不变", () => {
  it("清空说明发送 description: null", async () => {
    renderPanel()
    await openEditorFor("园区") // description "全园区"

    fireEvent.change(within(editor()).getByLabelText("分组说明"), {
      target: { value: "" },
    })
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g1", "PATCH")).toHaveLength(1)
    })
    // For this field `null` means "remove it" — an omitted key would have
    // preserved "全园区" instead.
    expect(patchTo("g1")).toEqual({ description: null })
  })

  it("没动说明时不发送 description 这个键", async () => {
    renderPanel()
    await openEditorFor("东区") // description is already null

    fireEvent.change(within(editor()).getByLabelText("分组名称"), {
      target: { value: "东区二" },
    })
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g2", "PATCH")).toHaveLength(1)
    })
    expect(patchTo("g2")).toEqual({ name: "东区二" })
    expect(patchTo("g2")).not.toHaveProperty("description")
  })

  it("移到顶级发送 parent_id: null", async () => {
    renderPanel()
    await openEditorFor("东区")

    fireEvent.change(within(editor()).getByLabelText("上级分组"), {
      target: { value: "" },
    })
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups/g2", "PATCH")).toHaveLength(1)
    })
    expect(patchTo("g2")).toEqual({ parent_id: null })
  })

  it("没改过任何东西时保存按钮禁用，不会发出空的 PATCH", async () => {
    renderPanel()
    await openEditorFor("园区")

    expect(saveButton().disabled).toBe(true)
    fireEvent.click(saveButton())
    expect(callsTo("/camera-groups/g1", "PATCH")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机分组 · 删除是硬删除", () => {
  it("有下级的分组不能删，理由点名是哪几个下级", async () => {
    renderPanel()
    const row = rowOf("园区")

    const remove = within(row).getByRole("button", { name: "删除分组 园区" })
    expect((remove as HTMLButtonElement).disabled).toBe(true)
    // The reason names the children, not just the condition.
    expect(
      within(row).getByText("该分组还有下级分组，请先删除或移动下级。（东区、西区）"),
    ).toBeTruthy()
    expect(callsTo("/camera-groups/g1", "DELETE")).toHaveLength(0)
  })

  it("叶子分组：先确认，取消不发 DELETE", async () => {
    renderPanel()
    fireEvent.click(
      within(rowOf("东区")).getByRole("button", { name: "删除分组 东区" }),
    )

    const dialog = await screen.findByRole("alertdialog")
    expect(within(dialog).getByText(/确定删除分组「东区」？/)).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).toBeNull()
    })
    expect(callsTo("/camera-groups/g2", "DELETE")).toHaveLength(0)
  })

  it("叶子分组：确认后发送 DELETE", async () => {
    renderPanel()
    fireEvent.click(
      within(rowOf("东区")).getByRole("button", { name: "删除分组 东区" }),
    )

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }))

    await waitFor(() => {
      expect(callsTo("/camera-groups/g2", "DELETE")).toHaveLength(1)
    })
  })

  it("被用户/角色范围引用时给出人话，而不是一个 409 代码", async () => {
    failure = {
      status: 409,
      code: "camera_group_in_use",
      message: "Camera group is referenced by an access scope.",
    }
    renderPanel()
    fireEvent.click(
      within(rowOf("东区")).getByRole("button", { name: "删除分组 东区" }),
    )

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }))

    await waitFor(() => {
      expect(callsTo("/camera-groups/g2", "DELETE")).toHaveLength(1)
    })
    expect(
      await screen.findByText(
        "该分组仍被某个用户或角色的摄像机范围引用，请先在那边移除。",
      ),
    ).toBeTruthy()
    // The raw code must not be what the operator is left with.
    expect(screen.queryByText(/camera_group_in_use/)).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机分组 · 树是从 parent_id 重建的", () => {
  it("渲染出嵌套层级", async () => {
    renderPanel()
    await screen.findByText("园区")

    // Both groups are rendered, and 东区 lives inside 园区's row while 园区
    // does not live inside 东区's.
    expect(rowOf("园区").contains(rowOf("东区"))).toBe(true)
    expect(rowOf("东区").contains(rowOf("园区"))).toBe(false)
    expect(rowOf("园区").contains(rowOf("西区"))).toBe(true)
  })

  it("点哪一行的编辑就打开哪一个分组", async () => {
    renderPanel()
    await openEditorFor("西区")

    // The rows are recursive; a handler bound at the top of a branch would open
    // 园区 here and quietly save the wrong group.
    expect(within(editor()).getByText("编辑分组：西区")).toBeTruthy()
    expect(within(editor()).getByLabelText("分组名称")).toHaveProperty(
      "value",
      "西区",
    )
  })

  it("上级不存在的分组仍然出现，按顶级渲染", async () => {
    const groups: CameraGroupView[] = [
      { id: "g9", name: "孤儿组", description: null, parent_id: "g-gone", camera_ids: [] },
    ]
    renderPanel(groups)

    const list = screen.getByRole("list", { name: "分组列表" })
    const row = within(list).getByText("孤儿组").closest("li") as HTMLElement
    // Promoted to a top-level node rather than dropped — a group whose parent
    // vanished is still a group with a scope attached to it.
    expect(row.parentElement).toBe(list)
  })

  it("数据成环时渲染不会卡住", async () => {
    const groups: CameraGroupView[] = [
      { id: "g1", name: "甲", description: null, parent_id: "g2", camera_ids: ["c1"] },
      { id: "g2", name: "乙", description: null, parent_id: "g1", camera_ids: ["c2"] },
    ]
    renderPanel(groups)

    // `buildGroupTree` promotes anything unreached from a root and refuses to
    // recurse into it; a cycle in the table is a 409 upstream, not a reason to
    // hang the screen.
    await screen.findByText("甲")
    expect(screen.getByText("乙")).toBeTruthy()
  })

  it("有下级时说明这个分组实际覆盖多少台摄像机", async () => {
    renderPanel()

    // 园区 holds c1; 东区 holds c2 + c3; 西区 holds c2 + c3 + c4. c2 and c3 are
    // shared, so the honest figure is the union — 4, not 1 + 2 + 3.
    expect(within(rowOf("园区")).getByText("连同下级共覆盖 4 个摄像机")).toBeTruthy()
    expect(within(rowOf("园区")).getByText("本组 1 个摄像机")).toBeTruthy()
    // A leaf has nothing to expand, so it shows only its own count.
    expect(within(rowOf("东区")).queryByText(/连同下级共覆盖/)).toBeNull()
    expect(within(rowOf("东区")).getByText("本组 2 个摄像机")).toBeTruthy()
  })

  it("编辑器里点明一次授权会连带覆盖哪些下级分组", async () => {
    renderPanel()
    await openEditorFor("园区")

    // The order the names come out in is `descendantsOf`'s traversal order, not
    // the order the groups are stored in, so this asserts the set and the
    // count — the two things the claim actually rests on.
    const hint = within(editor()).getByText(/会连带授权 2 个下级分组：/)
    expect(hint.textContent).toContain("东区")
    expect(hint.textContent).toContain("西区")
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机分组 · 新建", () => {
  it("发送名称、上级与完整成员列表", async () => {
    renderPanel()
    await startCreate()

    fireEvent.change(within(editor()).getByLabelText("分组名称"), {
      target: { value: "新组" },
    })
    fireEvent.change(within(editor()).getByLabelText("上级分组"), {
      target: { value: "g2" },
    })
    toggleCamera("门口", true)
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups", "POST")).toHaveLength(1)
    })
    expect(callsTo("/camera-groups", "POST")[0].body).toEqual({
      name: "新组",
      parent_id: "g2",
      camera_ids: ["c1"],
    })
  })

  it("只填空格的名称在本地就被挡住，不发 POST", async () => {
    renderPanel()
    await startCreate()
    fireEvent.change(within(editor()).getByLabelText("分组名称"), {
      target: { value: "   " },
    })

    expect(within(editor()).getByText("请填写分组名称")).toBeTruthy()
    expect(saveButton().disabled).toBe(true)
    fireEvent.click(saveButton())
    expect(callsTo("/camera-groups", "POST")).toHaveLength(0)
  })

  it("重名给出的是解释，不是 camera_group_name_conflict", async () => {
    failure = {
      status: 409,
      code: "camera_group_name_conflict",
      message: "Camera group name already exists.",
    }
    renderPanel()
    await startCreate()
    fireEvent.change(within(editor()).getByLabelText("分组名称"), {
      target: { value: "东区" },
    })
    fireEvent.click(saveButton())

    await waitFor(() => {
      expect(callsTo("/camera-groups", "POST")).toHaveLength(1)
    })
    expect(
      await screen.findByText("同名分组已存在。分组名称全局唯一。"),
    ).toBeTruthy()
    expect(screen.queryByText(/camera_group_name_conflict/)).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机分组 · 读不出来和没有分组", () => {
  it("一个分组都没有时给出空状态", async () => {
    renderPanel([])
    expect(await screen.findByText("还没有任何分组")).toBeTruthy()
  })

  it("读失败时说清是哪里坏了", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: { code: "boom", message: "分组服务未就绪" } }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    renderWithProviders(<CameraGroupsPanel />, { client })

    expect(await screen.findByText("无法读取摄像机分组")).toBeTruthy()
    expect(screen.getByText("分组服务未就绪")).toBeTruthy()
  })
})
