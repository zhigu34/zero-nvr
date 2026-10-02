import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildGroupPatch,
  buildGroupTree,
  createCameraGroup,
  deleteCameraGroup,
  descendantsOf,
  emptyGroupForm,
  groupDeleteBlocker,
  impliedBySelection,
  isGroupPatchEmpty,
  listCameraGroups,
  updateCameraGroup,
  validateGroupForm,
  type CameraGroupView,
} from "./cameraGroups"

/**
 * The load-bearing rule is that `camera_ids` is a whole replace inside a
 * field-merge PATCH. `api.py:540` uses `exclude_unset=True`, so a developer
 * reasonably concludes omitted fields are safe — and then adds one camera,
 * PATCHes only that one, and empties the group. Most of these tests exist to
 * make that specific mistake impossible to write.
 */

function group(overrides: Partial<CameraGroupView> = {}): CameraGroupView {
  return {
    id: "g1",
    name: "前院",
    description: null,
    parent_id: null,
    camera_ids: ["cam-1", "cam-2"],
    ...overrides,
  }
}

afterEach(() => vi.unstubAllGlobals())

function capture() {
  const seen: { method: string; url: string; body: unknown }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        method: init?.method ?? "GET",
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return seen
}

describe("endpoints", () => {
  it("uses the documented paths and methods", async () => {
    const seen = capture()
    await listCameraGroups()
    await createCameraGroup({ name: "前院" })
    await updateCameraGroup("g1", { name: "后院" })
    await deleteCameraGroup("g1")

    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/camera-groups",
      "POST /api/v1/camera-groups",
      "PATCH /api/v1/camera-groups/g1",
      "DELETE /api/v1/camera-groups/g1",
    ])
  })
})

describe("buildGroupPatch", () => {
  const original = group()

  it("sends nothing when the form is untouched", () => {
    const body = buildGroupPatch(original, {
      name: "前院",
      description: "",
      parentId: null,
      cameraIds: ["cam-1", "cam-2"],
    })
    expect(isGroupPatchEmpty(body)).toBe(true)
  })

  it("sends the full camera list when membership changes, not just the delta", () => {
    // The endpoint deletes every membership and re-inserts. A delta would empty
    // the group.
    const body = buildGroupPatch(original, {
      name: "前院",
      description: "",
      parentId: null,
      cameraIds: ["cam-1", "cam-2", "cam-3"],
    })
    expect(body.camera_ids).toEqual(["cam-1", "cam-2", "cam-3"])
  })

  it("sends an empty list to empty a group, rather than omitting it", () => {
    const body = buildGroupPatch(original, {
      name: "前院",
      description: "",
      parentId: null,
      cameraIds: [],
    })
    expect(body.camera_ids).toEqual([])
    // Omitting the field would mean "keep the two cameras", the opposite intent.
    expect(Object.hasOwn(body, "camera_ids")).toBe(true)
  })

  it("treats reordering and duplicates as no change", () => {
    const body = buildGroupPatch(original, {
      name: "前院",
      description: "",
      parentId: null,
      cameraIds: ["cam-2", "cam-1", "cam-1"],
    })
    expect(Object.hasOwn(body, "camera_ids")).toBe(false)
  })

  it("sends null to clear a description, and omits it to leave it alone", () => {
    const withDescription = group({ description: "门口" })
    const cleared = buildGroupPatch(withDescription, {
      name: "前院",
      description: "   ",
      parentId: null,
      cameraIds: ["cam-1", "cam-2"],
    })
    expect(cleared.description).toBeNull()

    const untouched = buildGroupPatch(withDescription, {
      name: "前院",
      description: "门口",
      parentId: null,
      cameraIds: ["cam-1", "cam-2"],
    })
    expect(Object.hasOwn(untouched, "description")).toBe(false)
  })

  it("sends null to move a group back to being a root", () => {
    const child = group({ parent_id: "g0" })
    const moved = buildGroupPatch(child, {
      name: "前院",
      description: "",
      parentId: null,
      cameraIds: ["cam-1", "cam-2"],
    })
    expect(moved.parent_id).toBeNull()
    // `name: null` and `camera_ids: null` are 400s server-side, never sent.
    expect(Object.hasOwn(moved, "name")).toBe(false)
  })
})

describe("validateGroupForm", () => {
  it("rejects a whitespace-only name, which min_length=1 lets through", () => {
    // `Field(min_length=1)` accepts " "; the service rejects it after strip.
    expect(validateGroupForm(emptyGroupForm())[0].field).toBe("name")
    expect(
      validateGroupForm({ ...emptyGroupForm(), name: "   " })[0].field,
    ).toBe("name")
  })

  it("rejects an over-long name and description", () => {
    expect(
      validateGroupForm({ ...emptyGroupForm(), name: "x".repeat(129) })[0].field,
    ).toBe("name")
    expect(
      validateGroupForm({
        ...emptyGroupForm(),
        name: "ok",
        description: "x".repeat(2049),
      })[0].field,
    ).toBe("description")
  })

  it("accepts a minimal group", () => {
    expect(validateGroupForm({ ...emptyGroupForm(), name: "前院" })).toEqual([])
  })
})

describe("buildGroupTree", () => {
  it("nests children under their parent", () => {
    const tree = buildGroupTree([
      group({ id: "g1", name: "室外" }),
      group({ id: "g2", name: "前院", parent_id: "g1" }),
      group({ id: "g3", name: "车道", parent_id: "g1" }),
      group({ id: "g4", name: "室内" }),
    ])
    expect(tree.map((n) => n.group.id)).toEqual(["g1", "g4"])
    expect(tree[0].children.map((n) => n.group.id)).toEqual(["g2", "g3"])
  })

  it("promotes a group whose parent does not exist instead of dropping it", () => {
    const tree = buildGroupTree([group({ id: "orphan", parent_id: "gone" })])
    expect(tree.map((n) => n.group.id)).toEqual(["orphan"])
  })

  it("terminates on a cycle rather than recursing forever", () => {
    // 409 camera_group_hierarchy_invalid exists because cycles can reach the DB.
    const tree = buildGroupTree([
      group({ id: "a", parent_id: "b" }),
      group({ id: "b", parent_id: "a" }),
    ])
    expect(tree.length).toBeGreaterThan(0)
    expect(tree.flatMap((n) => [n.group.id, ...n.children.map((c) => c.group.id)]))
      .toHaveLength(2)
  })
})

describe("scope expansion", () => {
  const groups = [
    group({ id: "g1", name: "室外" }),
    group({ id: "g2", name: "前院", parent_id: "g1" }),
    group({ id: "g3", name: "前院门口", parent_id: "g2" }),
    group({ id: "g4", name: "室内" }),
  ]

  it("expands a group to its descendants transitively", () => {
    // A scope grant on g1 silently includes g2 and g3.
    expect([...descendantsOf(groups, "g1")].sort()).toEqual(["g1", "g2", "g3"])
  })

  it("a leaf expands to only itself", () => {
    expect([...descendantsOf(groups, "g4")]).toEqual(["g4"])
  })

  it("union across several selected groups", () => {
    expect([...impliedBySelection(groups, ["g3", "g4"])].sort()).toEqual([
      "g3",
      "g4",
    ])
  })

  it("does not loop on a cyclic hierarchy", () => {
    const cyclic = [
      group({ id: "a", parent_id: "b" }),
      group({ id: "b", parent_id: "a" }),
    ]
    expect([...descendantsOf(cyclic, "a")].sort()).toEqual(["a", "b"])
  })
})

describe("groupDeleteBlocker", () => {
  it("blocks a parent that still has children", () => {
    const groups = [group({ id: "g1" }), group({ id: "g2", parent_id: "g1" })]
    expect(groupDeleteBlocker(groups[0], groups)).toContain("下级分组")
  })

  it("allows a leaf, while acknowledging in-use is not knowable here", () => {
    // `camera_group_in_use` depends on user/role scopes this endpoint does not
    // return, so the server's 409 stays authoritative.
    const groups = [group({ id: "g1" }), group({ id: "g2", parent_id: "g1" })]
    expect(groupDeleteBlocker(groups[1], groups)).toBeNull()
  })
})
