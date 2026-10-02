import { afterEach, describe, expect, it, vi } from "vitest"

import {
  describeRotation,
  getSecretStoreHealth,
  rotateSecretStore,
  rotationBlockedReason,
  secretStoreTone,
  SECRET_STORE_STATUS_LABEL,
  type SecretStoreHealth,
  type SecretStoreRotation,
} from "./secretStore"

/**
 * The load-bearing rule is that `ERROR` must not offer a rotation.
 *
 * `rotate_records` decrypts every record before writing anything
 * (`secret_store.py:474-485`) and `decrypt_bytes` raises on the ones it cannot
 * read — so a rotation from an `ERROR` state is a request that throws
 * partway, with a 500 that says nothing about the unreadable record. The tests
 * below assert the button is disabled *and* that it says why, because a
 * disabled control with no explanation is the thing users report as "the page
 * is broken".
 */

function health(overrides: Partial<SecretStoreHealth> = {}): SecretStoreHealth {
  return {
    status: "OK",
    total_records: 12,
    current_records: 12,
    stale_records: 0,
    unreadable_records: 0,
    previous_key_count: 0,
    primary_key_id: "k3",
    rotation_ready: false,
    ...overrides,
  }
}

afterEach(() => vi.unstubAllGlobals())

describe("endpoints", () => {
  it("reads the health report and posts the rotation", async () => {
    const seen: { method: string; url: string }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        seen.push({ method: init?.method ?? "GET", url: String(input) })
        return new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    await getSecretStoreHealth()
    await rotateSecretStore()

    expect(seen).toEqual([
      { method: "GET", url: "/api/v1/secret-store" },
      { method: "POST", url: "/api/v1/secret-store/rotate" },
    ])
  })
})

describe("rotationBlockedReason", () => {
  it("allows rotation when stale records exist and none are unreadable", () => {
    expect(
      rotationBlockedReason(
        health({
          status: "ROTATION_REQUIRED",
          current_records: 8,
          stale_records: 4,
          rotation_ready: true,
        }),
      ),
    ).toBeNull()
  })

  it("blocks rotation when records cannot be decrypted, and says how many", () => {
    const reason = rotationBlockedReason(
      health({ status: "ERROR", unreadable_records: 3, stale_records: 4 }),
    )
    expect(reason).not.toBeNull()
    expect(reason).toContain("3")
    expect(reason).toContain("无法解密")
  })

  it("blocks rotation when there is nothing to rotate", () => {
    const reason = rotationBlockedReason(health())
    expect(reason).toContain("没有待轮换")
  })

  it("defers to the server's own rotation_ready", () => {
    // stale > 0 but the server said not ready: do not second-guess it.
    expect(
      rotationBlockedReason(
        health({
          status: "ROTATION_REQUIRED",
          stale_records: 4,
          current_records: 8,
          rotation_ready: false,
        }),
      ),
    ).toContain("服务端判定")
  })

  it("blocks on unreadable records even when the server says ready", () => {
    // Contradictory payload — unreadable wins, because that is the one that
    // makes rotation throw.
    expect(
      rotationBlockedReason(
        health({ unreadable_records: 1, stale_records: 2, rotation_ready: true }),
      ),
    ).toContain("无法解密")
  })
})

describe("presentation", () => {
  it("maps the three statuses to distinct tones and labels", () => {
    expect(secretStoreTone("OK")).toBe("online")
    expect(secretStoreTone("ROTATION_REQUIRED")).toBe("degraded")
    expect(secretStoreTone("ERROR")).toBe("offline")
    expect(new Set(Object.values(SECRET_STORE_STATUS_LABEL)).size).toBe(3)
  })
})

describe("describeRotation", () => {
  const result = (overrides: Partial<SecretStoreRotation>): SecretStoreRotation => ({
    total_records: 12,
    rotated_records: 4,
    already_current_records: 8,
    health: health(),
    ...overrides,
  })

  it("reports both numbers so the sum can be checked", () => {
    const text = describeRotation(result({}))
    expect(text).toContain("4")
    expect(text).toContain("12")
    expect(text).toContain("8")
  })

  it("says plainly when there was nothing to do", () => {
    const text = describeRotation(
      result({ rotated_records: 0, already_current_records: 12 }),
    )
    expect(text).toContain("没有记录需要重写")
  })
})
