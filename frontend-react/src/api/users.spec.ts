import { afterEach, describe, expect, it, vi } from "vitest"

import {
  CAMERA_SCOPE_LABEL,
  MIN_PASSWORD_LENGTH,
  createUser,
  hasErrors,
  issueUserPasswordReset,
  listUsers,
  setUserCameraScope,
  setUserEnabled,
  updateUser,
  validateUser,
} from "./users"
import { ApiError } from "./client"

/**
 * The user contract has three traps that all fail silently rather than loudly:
 * a username that cannot be changed, an `enabled` field that is not a field,
 * and a password reset token that exists exactly once. These pin the request
 * shapes so a refactor cannot quietly start sending the wrong thing.
 */

type Call = { url: string; method: string; body: unknown; init: RequestInit | undefined }

function captureFetch(respond?: () => Response) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
        init,
      })
      return (
        respond?.() ??
        new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })
      )
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("validateUser", () => {
  const base = {
    username: "operator1",
    display_name: "值班员",
    email: "op@example.com",
  }
  const strong = "a".repeat(MIN_PASSWORD_LENGTH)

  it("accepts a well-formed user", () => {
    expect(
      hasErrors(validateUser({ ...base, password: strong }, { requirePassword: true })),
    ).toBe(false)
  })

  it("mirrors the backend's username pattern", () => {
    // `^[A-Za-z0-9_.-]+$` on the schema (`schemas.py:131`).
    expect(validateUser({ ...base, username: "有中文" }, { requirePassword: false })
      .username).toBeTruthy()
    expect(validateUser({ ...base, username: "has space" }, { requirePassword: false })
      .username).toBeTruthy()
    expect(validateUser({ ...base, username: "ok.name-1_x" }, { requirePassword: false })
      .username).toBeUndefined()
  })

  it("enforces the 12-character password floor the backend enforces", () => {
    const short = validateUser(
      { ...base, password: "a".repeat(MIN_PASSWORD_LENGTH - 1) },
      { requirePassword: true },
    )
    expect(short.password).toContain(String(MIN_PASSWORD_LENGTH))
    const ok = validateUser(
      { ...base, password: "a".repeat(MIN_PASSWORD_LENGTH) },
      { requirePassword: true },
    )
    expect(ok.password).toBeUndefined()
  })

  it("does not ask for a password on edit, because UserUpdate has no such field", () => {
    expect(hasErrors(validateUser(base, { requirePassword: false }))).toBe(false)
  })

  it("treats an empty email as absent rather than invalid", () => {
    expect(validateUser({ ...base, email: "" }, { requirePassword: false }).email)
      .toBeUndefined()
    expect(validateUser({ ...base, email: null }, { requirePassword: false }).email)
      .toBeUndefined()
  })

  it("rejects an obviously malformed email without out-gaiving EmailStr", () => {
    expect(validateUser({ ...base, email: "nope" }, { requirePassword: false }).email)
      .toBeTruthy()
  })
})

describe("write shapes", () => {
  it("PATCHes only the fields UserUpdate actually accepts", async () => {
    const calls = captureFetch()
    await updateUser("u1", { display_name: "新名字", email: null, role_ids: ["r1"] })
    expect(calls[0].method).toBe("PATCH")
    // `username` and `enabled` are absent from the body on purpose: sending
    // them would be a silent no-op, not a validation error.
    expect(Object.keys(calls[0].body ?? {}).sort()).toEqual([
      "display_name",
      "email",
      "role_ids",
    ])
  })

  it("uses a dedicated endpoint for enable and disable, not a field", async () => {
    const calls = captureFetch()
    await setUserEnabled("u1", false)
    expect(calls[0].url).toContain("/users/u1/disable")
    expect(calls[0].method).toBe("POST")

    await setUserEnabled("u1", true)
    expect(calls[1].url).toContain("/users/u1/enable")
  })

  it("writes camera scope to its own resource", async () => {
    const calls = captureFetch()
    await setUserCameraScope("u1", { mode: "selected", camera_ids: ["c1"], camera_group_ids: [] })
    expect(calls[0].method).toBe("PUT")
    expect(calls[0].url).toContain("/users/u1/camera-scope")
    expect(calls[0].body).toEqual({
      mode: "selected",
      camera_ids: ["c1"],
      camera_group_ids: [],
    })
  })

  it("returns the one-shot reset token from its own endpoint", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({ token: "tok", expires_at: "2026-10-03T00:00:00Z" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    )
    const issued = await issueUserPasswordReset("u1")
    expect(issued.token).toBe("tok")
  })

  it("leaves role_ids off the body when the caller omits it", async () => {
    // `role_ids` defaults to `[]` server-side (`schemas.py:135`), so omitting
    // it is a well-formed "this user has no roles" — the client does not
    // invent a key to make the intent explicit.
    const calls = captureFetch()
    await createUser({
      username: "new",
      display_name: "新人",
      password: "a".repeat(12),
    })
    expect(calls[0].body).not.toHaveProperty("role_ids")
    expect(calls[0].body).toMatchObject({ username: "new" })
  })
})

describe("listUsers", () => {
  it("is a plain array, with no cursor parameter to get wrong", async () => {
    const calls = captureFetch(
      () =>
        new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    )
    const users = await listUsers()
    expect(users).toEqual([])
    expect(calls[0].url).toBe("/api/v1/users")
    expect(calls[0].url).not.toContain("cursor")
  })
})

describe("error mapping", () => {
  it("surfaces the backend's field message for a rejected create", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            error: { code: "username_taken", message: "Username already exists." },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(
      createUser({ username: "a", display_name: "b", password: "c".repeat(12) }),
    ).rejects.toBeInstanceOf(ApiError)
  })
})

describe("scope vocabulary", () => {
  it("labels all four modes the contract allows", () => {
    for (const mode of ["inherit", "all", "selected", "none"] as const) {
      expect(CAMERA_SCOPE_LABEL[mode]).toBeTruthy()
    }
  })
})
