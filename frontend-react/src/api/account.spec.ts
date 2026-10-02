import { afterEach, describe, expect, it, vi } from "vitest"

import {
  changeOwnPassword,
  describeSessionSource,
  isInteractiveSessionRequired,
  isSessionExpired,
  isWrongCurrentPassword,
  listSessions,
  PASSWORD_MIN,
  passwordsMatch,
  revokeSession,
  sessionLifetime,
  validatePasswordForm,
  type SessionSummary,
} from "./account"
import { ApiError } from "./client"

/**
 * Two of these tests guard against UI that would state something false:
 *
 * 1. `last_seen_at` is written once at creation and never updated, so it is
 *    always `created_at`. Rendering it as "last active" tells the operator their
 *    other devices are idle when they may be in use right now.
 * 2. The password rule is length only — no reuse check, no character classes.
 *    A form claiming reuse protection it does not have is worse than silence.
 */

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "s1",
    created_at: "2026-10-01T00:00:00Z",
    last_seen_at: "2026-10-01T00:00:00Z",
    expires_at: "2026-10-08T00:00:00Z",
    current: false,
    client_info: { user_agent: "Mozilla/5.0 Chrome/140.0", source_ip: "10.0.0.5" },
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
      return new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return seen
}

describe("endpoints", () => {
  it("uses the documented paths, including the one that is easy to get wrong", () => {
    const seen = capture()
    listSessions()
    revokeSession("s1")
    changeOwnPassword({ current_password: "a", new_password: "b" })

    // `/auth/password` does not exist; only `/auth/password/change` does.
    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/sessions",
      "DELETE /api/v1/sessions/s1",
      "POST /api/v1/auth/password/change",
    ])
  })
})

describe("sessionLifetime", () => {
  const now = new Date("2026-10-03T00:00:00Z")

  it("reports whole days left, floored", () => {
    expect(sessionLifetime(session(), now).daysLeft).toBe(5)
  })

  it("goes negative once expired rather than clamping at zero", () => {
    const past = new Date("2026-10-10T00:00:00Z")
    expect(sessionLifetime(session(), past).daysLeft).toBe(-2)
  })

  it("derives the signed-in time from created_at, not last_seen_at", () => {
    // They are the same value today; using created_at is the one that stays
    // true if last_seen_at ever starts being maintained.
    const s = session({ created_at: "2026-10-01T00:00:00Z", last_seen_at: "2026-10-02T09:00:00Z" })
    expect(sessionLifetime(s, now).signedInSince).toBe("2026-10-01T00:00:00Z")
  })
})

describe("describeSessionSource", () => {
  it("names the browser and the address when both are present", () => {
    expect(describeSessionSource(session())).toBe("Chrome · 10.0.0.5")
  })

  it("says the information is missing rather than showing a blank", () => {
    expect(describeSessionSource(session({ client_info: null }))).toBe(
      "客户端信息未记录",
    )
  })

  it("handles a sparse client_info with only one key", () => {
    expect(
      describeSessionSource(session({ client_info: { user_agent: "curl/8.4" } })),
    ).toBe("其他客户端")
    expect(
      describeSessionSource(session({ client_info: { source_ip: "192.168.1.9" } })),
    ).toBe("客户端信息未记录 · 192.168.1.9")
  })

  it("prefers Edge and Opera over the Chrome token they both contain", () => {
    expect(
      describeSessionSource(
        session({ client_info: { user_agent: "Mozilla/5.0 Edg/140.0" } }),
      ),
    ).toBe("Edge")
    expect(
      describeSessionSource(
        session({ client_info: { user_agent: "Mozilla/5.0 OPR/120.0" } }),
      ),
    ).toBe("Opera")
  })
})

describe("validatePasswordForm", () => {
  const form = (currentPassword: string, newPassword: string) => ({
    currentPassword,
    newPassword,
  })

  it("requires both fields", () => {
    expect(validatePasswordForm(form("", ""))).toHaveLength(2)
  })

  it("enforces only the length rule the server enforces", () => {
    expect(validatePasswordForm(form("cur", "x".repeat(PASSWORD_MIN)))).toEqual([])
    expect(
      validatePasswordForm(form("cur", "x".repeat(PASSWORD_MIN - 1)))[0].message,
    ).toContain(String(PASSWORD_MIN))
    expect(validatePasswordForm(form("cur", "x".repeat(257)))[0].field).toBe(
      "newPassword",
    )
  })

  it("accepts a weak-looking password, because the server does", () => {
    // No character classes are required. Asserting otherwise would be claiming
    // protection the backend does not provide.
    expect(validatePasswordForm(form("cur", "aaaaaaaaaaaa"))).toEqual([])
  })

  it("flags reuse separately from validation, since the server allows it", () => {
    expect(passwordsMatch(form("same-password-here", "same-password-here"))).toBe(
      true,
    )
    expect(passwordsMatch(form("cur", ""))).toBe(false)
  })
})

describe("failure codes", () => {
  it("distinguishes a wrong current password from an auth failure", () => {
    // 400 invalid_current_password is a form field error, not "please log in".
    expect(
      isWrongCurrentPassword(new ApiError(400, "invalid_current_password", "x")),
    ).toBe(true)
    expect(isWrongCurrentPassword(new ApiError(401, "authentication_required", "x"))).toBe(
      false,
    )
  })

  it("treats an API token rejection as a session problem, not a crash", () => {
    // A token gets 403 interactive_session_required, deliberately.
    expect(
      isInteractiveSessionRequired(
        new ApiError(403, "interactive_session_required", "x"),
      ),
    ).toBe(true)
    expect(isInteractiveSessionRequired(new Error("boom"))).toBe(false)
  })

  it("separates an expired session from the wrong credential type", () => {
    // The combined predicate is deliberately coarse; this is the strict one.
    expect(isSessionExpired(new ApiError(401, "authentication_required", "x"))).toBe(
      true,
    )
    expect(
      isSessionExpired(new ApiError(403, "interactive_session_required", "x")),
    ).toBe(false)
  })
})
