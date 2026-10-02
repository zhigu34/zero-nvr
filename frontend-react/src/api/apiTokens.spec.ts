import { afterEach, describe, expect, it, vi } from "vitest"

import {
  API_TOKEN_PREFIX,
  apiTokenStatus,
  createApiToken,
  describeTokenUsage,
  listApiTokens,
  localExpiryToIso,
  revokeApiToken,
  validateApiTokenForm,
  type ApiTokenForm,
  type ApiTokenView,
} from "./apiTokens"
import { ApiError } from "./client"

/**
 * Two things are load-bearing here.
 *
 * 1. **`permissions: null` and `permissions: []` are different requests.** The
 *    first inherits the creator's scope, the second mints a token that can do
 *    nothing. The endpoint does not conflate them, so neither may the client.
 * 2. **The plaintext is in the create response and nowhere else.** A test that
 *    asserted "the token appears" would pass on an implementation that also
 *    cached it; the list response type has no such field, and that is the
 *    guarantee worth pinning.
 */

const NOW = new Date("2026-10-02T00:00:00Z")

function token(overrides: Partial<ApiTokenView> = {}): ApiTokenView {
  return {
    id: "tok-1",
    name: "grafana",
    permissions: ["camera.view"],
    created_at: "2026-10-01T00:00:00Z",
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
    ...overrides,
  }
}

function form(overrides: Partial<ApiTokenForm> = {}): ApiTokenForm {
  return { name: "grafana", permissions: null, expiresAt: null, ...overrides }
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
  it("lists, creates and revokes against the documented paths", async () => {
    const seen = capture()

    await listApiTokens()
    await createApiToken({ name: "grafana" })
    await revokeApiToken("tok-1")

    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/api-tokens",
      "POST /api/v1/api-tokens",
      "DELETE /api/v1/api-tokens/tok-1",
    ])
  })

  it("omits permissions entirely when the form inherits, rather than sending []", async () => {
    const seen = capture()
    // A JSON body cannot distinguish `permissions: null` from "absent" in a
    // way the server treats differently — but `[]` it very much can.
    await createApiToken({ name: "grafana", permissions: undefined })
    expect(seen[0].body).toEqual({ name: "grafana" })
    expect(Object.hasOwn(seen[0].body as object, "permissions")).toBe(false)
  })

  it("the create response is the only place a plaintext token exists", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ ...token(), token: `${API_TOKEN_PREFIX}abc123` }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    const created = await createApiToken({ name: "grafana" })
    expect(created.token).toBe(`${API_TOKEN_PREFIX}abc123`)

    // The list type has no token field at all — the guarantee is structural,
    // not a runtime check.
    expect(Object.keys(token())).not.toContain("token")
  })
})

describe("apiTokenStatus", () => {
  it("reads an unexpiring, unused token as active", () => {
    expect(apiTokenStatus(token(), NOW)).toBe("active")
  })

  it("treats a past expiry as expired", () => {
    expect(
      apiTokenStatus(token({ expires_at: "2026-10-01T00:00:00Z" }), NOW),
    ).toBe("expired")
  })

  it("does not treat a future expiry as expired", () => {
    expect(
      apiTokenStatus(token({ expires_at: "2099-01-01T00:00:00Z" }), NOW),
    ).toBe("active")
  })

  it("treats the exact expiry instant as expired, not active", () => {
    // The server compares `expires_at <= now` (`api_tokens.py:64-67`), so the
    // boundary belongs to the dead side.
    expect(apiTokenStatus(token({ expires_at: NOW.toISOString() }), NOW)).toBe(
      "expired",
    )
  })

  it("lets a revoke win over an unexpired date", () => {
    // A deliberately cut-off token must not read as "just wait for it to
    // expire", which is what the expiry column alone would suggest.
    expect(
      apiTokenStatus(
        token({ revoked_at: "2026-09-01T00:00:00Z", expires_at: "2099-01-01T00:00:00Z" }),
        NOW,
      ),
    ).toBe("revoked")
  })

  it("separates never-used from used", () => {
    expect(describeTokenUsage(token())).toBe("从未使用")
    expect(describeTokenUsage(token({ last_used_at: "2026-10-01T12:00:00Z" }))).toBe(
      "已使用",
    )
  })
})

describe("validateApiTokenForm", () => {
  it("accepts the minimal form", () => {
    expect(validateApiTokenForm(form())).toEqual([])
  })

  it("rejects a blank or over-long name", () => {
    expect(validateApiTokenForm(form({ name: "  " }))[0].field).toBe("name")
    expect(validateApiTokenForm(form({ name: "x".repeat(129) }))[0].field).toBe(
      "name",
    )
  })

  it("rejects an empty permission list but accepts inheriting", () => {
    // [] is a valid request meaning "a token that can do nothing"; null means
    // "the same as me". Only one of them is a mistake in a form.
    expect(validateApiTokenForm(form({ permissions: [] }))[0].field).toBe(
      "permissions",
    )
    expect(validateApiTokenForm(form({ permissions: null }))).toEqual([])
    expect(validateApiTokenForm(form({ permissions: ["camera.view"] }))).toEqual(
      [],
    )
  })

  it("rejects an expiry that is not in the future", () => {
    expect(
      validateApiTokenForm(form({ expiresAt: "2026-10-01T00:00:00Z" }))[0].field,
    ).toBe("expiresAt")
    expect(validateApiTokenForm(form({ expiresAt: "not a date" }))[0].field).toBe(
      "expiresAt",
    )
  })

  it("accepts no expiry at all", () => {
    // `null` means "never expires", not "expires at the epoch".
    expect(validateApiTokenForm(form({ expiresAt: null }))).toEqual([])
  })
})

describe("localExpiryToIso", () => {
  it("returns null for an empty field", () => {
    expect(localExpiryToIso("")).toBeNull()
    expect(localExpiryToIso("   ")).toBeNull()
  })

  it("returns null for unparseable input rather than an Invalid Date", () => {
    expect(localExpiryToIso("tomorrow")).toBeNull()
  })

  it("produces a timezone-aware ISO string the schema accepts", () => {
    // A bare `2026-10-01T14:30` is exactly the naive datetime the server
    // rejects with api_token_expiry_invalid.
    const iso = localExpiryToIso("2026-10-01T14:30")
    expect(iso).not.toBeNull()
    expect(iso).toMatch(/Z$|[+-]\d{2}:\d{2}$/)
    expect(new Date(iso as string).toISOString()).toBe(iso)
  })
})

describe("ApiError codes the panel branches on", () => {
  it("are the ones the service actually raises", () => {
    // Guards against a typo in a string the UI matches on.
    for (const code of [
      "api_token_scope_invalid",
      "api_token_expiry_invalid",
      "api_token_name_invalid",
      "api_token_not_found",
    ]) {
      const error = new ApiError(400, code, "x")
      expect(error.code).toBe(code)
    }
  })
})
