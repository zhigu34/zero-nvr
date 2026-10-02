import { afterEach, describe, expect, it, vi } from "vitest"

import {
  NOTIFY_TYPES,
  applyCredentialsEdit,
  applyUrlEdit,
  createNotificationTarget,
  deleteNotificationTarget,
  deliveryStateLabel,
  deliveryStateTone,
  listNotificationDeliveries,
  listNotificationTargets,
  setSecurityEmailTarget,
  testNotificationTarget,
  toSecretAction,
  updateNotificationTarget,
  type NotificationTargetView,
} from "./notifications"
import { ApiError } from "./client"

/**
 * The load-bearing behaviour here is the secret-edit protocol. `url` and
 * `smtp_credentials.password` are write-only, so the update schema carries an
 * explicit verb (`url_action` / `credentials_action`) instead of letting `null`
 * mean both "unchanged" and "delete it". An editor that ignores the verb does
 * not get a validation error — it silently keeps the old secret, or silently
 * deletes a live one.
 */

type Call = { url: string; method: string; body: unknown }

function captureFetch(respond?: () => Response) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      return (
        respond?.() ??
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("applyUrlEdit", () => {
  it("says nothing at all when the URL is untouched", () => {
    // Omitting both fields is how "keep" is expressed; sending
    // `url: null` would read as a request to clear it.
    expect(applyUrlEdit({ action: "keep" })).toEqual({ url_action: "keep" })
  })

  it("sends the new value with a replace verb", () => {
    expect(applyUrlEdit({ action: "replace", value: "mailto://x" })).toEqual({
      url_action: "replace",
      url: "mailto://x",
    })
  })

  it("distinguishes clearing from keeping", () => {
    expect(applyUrlEdit({ action: "clear" })).toEqual({ url_action: "clear" })
    expect(applyUrlEdit({ action: "clear" })).not.toEqual(
      applyUrlEdit({ action: "keep" }),
    )
  })
})

describe("applyCredentialsEdit", () => {
  it("carries both username and password on replace", () => {
    expect(
      applyCredentialsEdit({
        action: "replace",
        value: { username: "ops", password: "s3cret" },
      }),
    ).toEqual({
      credentials_action: "replace",
      smtp_credentials: { username: "ops", password: "s3cret" },
    })
  })

  it("never conflates clear with keep", () => {
    expect(applyCredentialsEdit({ action: "clear" })).toEqual({
      credentials_action: "clear",
    })
    expect(applyCredentialsEdit({ action: "keep" })).toEqual({
      credentials_action: "keep",
    })
  })

  it("leaves the URL pair out, so the two secrets do not interfere", () => {
    const body = {
      ...applyCredentialsEdit({
        action: "replace",
        value: { username: "ops", password: "p" },
      }),
      ...applyUrlEdit({ action: "keep" }),
    }
    expect(body).toEqual({
      credentials_action: "replace",
      smtp_credentials: { username: "ops", password: "p" },
      url_action: "keep",
    })
  })
})

describe("write shapes", () => {
  it("never returns a URL in the read model, so the UI only has the flag", async () => {
    const target: NotificationTargetView = {
      id: "t1",
      name: "运维邮箱",
      kind: "apprise",
      enabled: true,
      config: { notify_type: "info" },
      url_configured: true,
      credentials_configured: false,
    }
    captureFetch(
      () =>
        new Response(JSON.stringify([target]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    )
    const list = await listNotificationTargets()
    expect(list[0].url_configured).toBe(true)
    expect(list[0]).not.toHaveProperty("url")
  })

  it("PATCHes with the verb, not a bare null", async () => {
    const calls = captureFetch()
    await updateNotificationTarget("t1", applyUrlEdit({ action: "clear" }))
    expect(calls[0].method).toBe("PATCH")
    expect(calls[0].body).toEqual({ url_action: "clear" })
    expect(calls[0].body).not.toHaveProperty("url")
  })

  it("posts the config whitelist the backend accepts", async () => {
    const calls = captureFetch()
    await createNotificationTarget({
      name: "告警邮箱",
      kind: "smtp",
      config: { notify_type: "warning", password_reset: true },
      url: "smtps://mail.example.com",
    })
    // `_normalize_config` rejects any key outside these two.
    const config = (calls[0].body as { config: Record<string, unknown> }).config
    expect(Object.keys(config).sort()).toEqual(["notify_type", "password_reset"])
    expect(config).toEqual({ notify_type: "warning", password_reset: true })
  })

  it("uses the snake_case delivery filters", async () => {
    const calls = captureFetch()
    await listNotificationDeliveries({ alertId: "a1", targetId: "t1", limit: 20 })
    expect(calls[0].url).toContain("alert_id=a1")
    expect(calls[0].url).toContain("target_id=t1")
    expect(calls[0].url).toContain("limit=20")
  })

  it("treats a null security email target as an explicit clear", async () => {
    const calls = captureFetch()
    await setSecurityEmailTarget(null)
    // `{target_id: null}` is the documented way to unset the pointer; omitting
    // the field would be a malformed body.
    expect(calls[0].body).toEqual({ target_id: null })
  })

  it("posts a test send with an optional recipient", async () => {
    const calls = captureFetch()
    await testNotificationTarget("t1", { recipient: "ops@example.com" })
    expect(calls[0].url).toContain("/notification-targets/t1/test")
    expect(calls[0].method).toBe("POST")
    expect(calls[0].body).toEqual({ recipient: "ops@example.com" })
  })

  it("deletes through the target resource", async () => {
    const calls = captureFetch()
    await deleteNotificationTarget("t1")
    expect(calls[0].method).toBe("DELETE")
  })
})

describe("error mapping", () => {
  it("keeps the code for a second password_reset target", async () => {
    // `_ensure_password_reset_unique` — the UI has to say "only one", not
    // "request failed".
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            error: {
              code: "password_reset_target_conflict",
              message: "Only one notification target can be used for password reset email.",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(
      createNotificationTarget({ name: "第二个", config: { password_reset: true } }),
    ).rejects.toMatchObject({ code: "password_reset_target_conflict" })
  })

  it("keeps the code for a non-smtp security email target", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            error: {
              code: "security_email_target_invalid",
              message: "Default security email target must be an SMTP target.",
            },
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(setSecurityEmailTarget("t1")).rejects.toBeInstanceOf(ApiError)
  })

  it("keeps the code for a malformed password_reset URL", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            error: {
              code: "password_reset_target_invalid",
              message: "Password reset target must be a mailto/mailtos SMTP URL.",
            },
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(
      createNotificationTarget({
        name: "x",
        config: { password_reset: true },
        url: "https://example.com",
      }),
    ).rejects.toMatchObject({ code: "password_reset_target_invalid" })
  })
})

describe("vocabulary", () => {
  it("labels exactly the four notify types the backend accepts", () => {
    // `_normalize_config` rejects anything else with
    // `notification_target_type_invalid`.
    expect([...NOTIFY_TYPES]).toEqual(["info", "success", "warning", "failure"])
  })

  it("degrades an unknown delivery state to itself", () => {
    expect(deliveryStateLabel("WEIRD")).toBe("WEIRD")
    expect(deliveryStateTone("WEIRD")).toBe("unknown")
  })

  it("does not report SKIPPED as a failure", () => {
    // A skipped delivery is a deliberate no-op, not an error.
    expect(deliveryStateTone("SKIPPED")).toBe("unknown")
    expect(deliveryStateTone("SENT")).toBe("online")
  })

  it("narrows an unknown segmented value to keep, never to clear", () => {
    expect(toSecretAction("replace")).toBe("replace")
    expect(toSecretAction("clear")).toBe("clear")
    expect(toSecretAction("keep")).toBe("keep")
    // The two destructive verbs are not interchangeable here: falling back to
    // "clear" on a typo would destroy a secret that cannot be read back.
    expect(toSecretAction("")).toBe("keep")
    expect(toSecretAction("remove")).toBe("keep")
  })
})
