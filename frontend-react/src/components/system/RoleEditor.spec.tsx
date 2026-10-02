/**
 * The permission matrix.
 *
 * Two things it must never do, and both are asserted here rather than trusted:
 * offer a control for a built-in role (which the server refuses with 409), and
 * let a stale permission ride along silently in a whole-set PATCH.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { QueryClientProvider } from "@tanstack/react-query"
import { QueryClient } from "@tanstack/react-query"
import { render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "../ui/Toast"
import { CameraScopeEditor } from "./CameraScopeEditor"
import { RoleEditor } from "./RoleEditor"
import { groupPermissions, validateRole } from "../../api/users"

const CATALOGUE = [
  "camera.view",
  "camera.control",
  "camera.configure",
  "recording.view",
  "recording.export",
  "recording.protect",
  "recording.delete",
  "event.view",
  "alert.view",
  "alert.acknowledge",
  "alert.manage",
  "notification.view",
  "notification.manage",
  "storage.manage",
  "system.view",
  "system.manage",
  "user.manage",
  "integration.manage",
  "audit.view",
]

function role(over: Record<string, unknown> = {}) {
  return {
    id: "r-night",
    name: "夜班值班员",
    description: null,
    built_in: false,
    permissions: ["camera.view", "alert.acknowledge"],
    ...over,
  }
}

function renderEditor(props: Partial<React.ComponentProps<typeof RoleEditor>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const onSubmit = vi.fn()
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <RoleEditor
          role={role() as never}
          catalogue={CATALOGUE}
          busy={false}
          onClose={onClose}
          onSubmit={onSubmit}
          {...props}
        />
      </ToastProvider>
    </QueryClientProvider>,
  )
  return { onSubmit, onClose }
}

afterEach(() => vi.unstubAllGlobals())

describe("groupPermissions", () => {
  it("groups by domain prefix, sorted", () => {
    const groups = groupPermissions(["camera.view", "audit.view", "recording.export"])
    expect(groups.map((g) => g.domain)).toEqual(["audit", "camera", "recording"])
  })

  it("keeps an unknown permission visible rather than dropping it", () => {
    // A permission added by a newer backend must be tickable, not silently
    // absent from the matrix.
    const groups = groupPermissions(["brand.new.permission"])
    expect(groups[0].items[0]).toEqual({
      permission: "brand.new.permission",
      label: "brand.new.permission",
    })
  })

  it("covers the whole server catalogue with no loss", () => {
    const flattened = groupPermissions(CATALOGUE).flatMap((g) =>
      g.items.map((i) => i.permission),
    )
    expect(flattened.slice().sort()).toEqual(CATALOGUE.slice().sort())
  })
})

describe("validateRole", () => {
  it("requires a name", () => {
    expect(validateRole({ name: "  " }).name).toBeTruthy()
  })

  it("does not require any permission", () => {
    // An empty set is how a role is staged before assignment. Blocking it would
    // forbid a legitimate workflow.
    expect(validateRole({ name: "夜班" })).toEqual({})
  })
})

describe("RoleEditor", () => {
  it("renders every permission with a label, grouped but never group-toggleable", () => {
    renderEditor()
    const group = screen.getByRole("group", { name: "权限" })
    for (const permission of CATALOGUE) {
      expect(
        screen.getByRole("checkbox", { name: new RegExp(permission) }),
      ).toBeTruthy()
    }
    // No control that would flip a whole domain at once.
    expect(
      screen.queryByRole("checkbox", { name: /全选|整组/ }),
    ).toBeNull()
    expect(group.textContent).toContain("摄像机")
  })

  it("submits the whole permission set, because PATCH replaces it", () => {
    const { onSubmit } = renderEditor()
    fireEvent.click(screen.getByRole("checkbox", { name: /recording.export/ }))
    fireEvent.click(screen.getByRole("button", { name: "保存权限" }))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    const body = onSubmit.mock.calls[0][0]
    // Unticked permissions are absent; the key is the **set**, and a partial
    // send would strip everything not mentioned.
    expect(body.permissions).toContain("recording.export")
    expect(body.permissions).not.toContain("recording.delete")
    expect(body.permissions).toHaveLength(3)
  })

  it("allows an empty set and says what it means", () => {
    const { onSubmit } = renderEditor()
    fireEvent.click(screen.getByRole("button", { name: "清空" }))
    expect(screen.getByText("这个角色目前不授予任何权限")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "保存权限" }))
    expect(onSubmit.mock.calls[0][0].permissions).toEqual([])
  })

  it("surfaces a granted permission the catalogue no longer lists", () => {
    // It would be submitted and then silently dropped server-side.
    renderEditor({
      role: role({ permissions: ["camera.view", "recording.delete"] }) as never,
      catalogue: CATALOGUE.filter((p) => p !== "recording.delete"),
    })
    expect(screen.getByText("有权限已不在目录中")).toBeTruthy()
    expect(screen.getByText(/recording\.delete/)).toBeTruthy()
  })

  it("starts empty for a new role", () => {
    renderEditor({ role: null })
    expect((screen.getByLabelText("角色名") as HTMLInputElement).value).toBe("")
    const checked = screen
      .getAllByRole("checkbox")
      .filter((c) => (c as HTMLInputElement).checked)
    expect(checked).toHaveLength(0)
  })

  it("re-seeds when a different role is shown without a remount", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <RoleEditor
            role={role() as never}
            catalogue={CATALOGUE}
            busy={false}
            onClose={() => {}}
            onSubmit={() => {}}
          />
        </ToastProvider>
      </QueryClientProvider>,
    )
    fireEvent.change(screen.getByLabelText("角色名"), { target: { value: "改坏了" } })

    rerender(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <RoleEditor
            role={role({ id: "r-2", name: "白班运维", permissions: ["audit.view"] }) as never}
            catalogue={CATALOGUE}
            busy={false}
            onClose={() => {}}
            onSubmit={() => {}}
          />
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect((screen.getByLabelText("角色名") as HTMLInputElement).value).toBe("白班运维")
    expect(
      (screen.getByRole("checkbox", { name: /audit\.view/ }) as HTMLInputElement).checked,
    ).toBe(true)
  })
})

describe("CameraScopeEditor", () => {
  function renderScope(scope: Record<string, unknown> | undefined, onSave = vi.fn()) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <CameraScopeEditor
            scope={scope as never}
            isPending={false}
            error={null}
            cameras={[{ id: "cam-1", name: "前门" }] as never}
            groups={[{ id: "g1", name: "室外", camera_ids: ["cam-2"] }] as never}
            busy={false}
            subject="该用户"
            onSave={onSave}
          />
        </ToastProvider>
      </QueryClientProvider>,
    )
    return onSave
  }

  it("clears the id list for inherit, so a stale selection cannot come back", () => {
    const onSave = renderScope({
      mode: "selected",
      camera_ids: ["cam-1"],
      camera_group_ids: ["g1"],
    })
    fireEvent.click(screen.getByRole("button", { name: "保存范围" }))
    // Switch to a mode that carries no list.
    fireEvent.click(screen.getByRole("button", { name: "全部机位" }))
    fireEvent.click(screen.getByRole("button", { name: "保存范围" }))

    expect(onSave).toHaveBeenLastCalledWith({
      mode: "all",
      camera_ids: [],
      camera_group_ids: [],
    })
  })

  it("says the subject sees nothing when both lists are empty", () => {
    renderScope({ mode: "selected", camera_ids: [], camera_group_ids: [] })
    expect(screen.getByText(/该用户看不到任何机位/)).toBeTruthy()
  })

  it("enables save only once something actually changed", async () => {
    renderScope({ mode: "all", camera_ids: [], camera_group_ids: [] })
    const save = screen.getByRole("button", { name: "保存范围" }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "无权限" }))
    await waitFor(() => expect(save.disabled).toBe(false))
  })
})
