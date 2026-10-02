import { describe, expect, it } from "vitest"

import { isProtected, overlapsProtection, type RecordingProtectionView } from "./protections"

/**
 * A protection is a time window on a camera, not a flag on a recording, so
 * "is this clip protected" is an interval question. The boundary convention is
 * the whole test: recordings are half-open everywhere else in this codebase,
 * and a protection that covered both sides of a shared instant would silently
 * protect a recording that starts the moment the previous one ended.
 */

function protection(over: Partial<RecordingProtectionView> = {}): RecordingProtectionView {
  return {
    id: "p1",
    camera_id: "c1",
    started_at: "2026-10-01T10:00:00.000Z",
    ended_at: "2026-10-01T11:00:00.000Z",
    reason: "取证",
    created_by: null,
    expires_at: null,
    created_at: "2026-10-01T00:00:00.000Z",
    updated_at: "2026-10-01T00:00:00.000Z",
    ...over,
  }
}

const T = (iso: string) => Date.parse(iso)

describe("isProtected", () => {
  it("covers an instant strictly inside the window", () => {
    const p = protection()
    expect(isProtected(p, T("2026-10-01T10:30:00.000Z"))).toBe(true)
  })

  it("treats both ends as open", () => {
    const p = protection()
    expect(isProtected(p, T("2026-10-01T10:00:00.000Z"))).toBe(true)
    expect(isProtected(p, T("2026-10-01T11:00:00.000Z"))).toBe(false)
  })

  it("ignores an expired protection", () => {
    const p = protection({ expires_at: "2026-10-01T10:30:00.000Z" })
    // After the expiry, inside the window that is otherwise covered.
    expect(isProtected(p, T("2026-10-01T10:45:00.000Z"), T("2026-10-02T00:00:00.000Z"))).toBe(
      false,
    )
    // Before it, still protected.
    expect(isProtected(p, T("2026-10-01T10:15:00.000Z"), T("2026-10-01T10:20:00.000Z"))).toBe(
      true,
    )
  })

  it("reads a null expires_at as no expiry, not as unknown", () => {
    // The opposite of the `recording: boolean | null` convention used for
    // runtime state, where null means "cannot observe".
    expect(
      isProtected(protection({ expires_at: null }), T("2026-10-01T10:30:00.000Z"), T("2099-01-01T00:00:00.000Z")),
    ).toBe(true)
  })

  it("protects nothing when the window cannot be parsed", () => {
    expect(isProtected(protection({ started_at: "nope" }), T("2026-10-01T10:30:00.000Z"))).toBe(
      false,
    )
  })
})

describe("overlapsProtection", () => {
  const p = protection()

  it("protects a recording fully inside the window", () => {
    expect(
      overlapsProtection([p], "2026-10-01T10:15:00.000Z", "2026-10-01T10:45:00.000Z"),
    ).toBe(true)
  })

  it("protects a recording that starts before and ends inside the window", () => {
    expect(
      overlapsProtection([p], "2026-10-01T09:00:00.000Z", "2026-10-01T10:30:00.000Z"),
    ).toBe(true)
  })

  it("does not protect a recording that only touches the start", () => {
    // Touching is not overlapping: half-open on both sides.
    expect(
      overlapsProtection([p], "2026-10-01T09:00:00.000Z", "2026-10-01T10:00:00.000Z"),
    ).toBe(false)
  })

  it("does not protect a recording that only touches the end", () => {
    expect(
      overlapsProtection([p], "2026-10-01T11:00:00.000Z", "2026-10-01T11:30:00.000Z"),
    ).toBe(false)
  })

  it("protects a recording that spans the whole window", () => {
    expect(
      overlapsProtection([p], "2026-10-01T08:00:00.000Z", "2026-10-01T12:00:00.000Z"),
    ).toBe(true)
  })

  it("is satisfied by any one of several windows", () => {
    const other = protection({
      id: "p2",
      started_at: "2026-10-01T20:00:00.000Z",
      ended_at: "2026-10-01T21:00:00.000Z",
    })
    expect(
      overlapsProtection(
        [p, other],
        "2026-10-01T20:30:00.000Z",
        "2026-10-01T20:45:00.000Z",
      ),
    ).toBe(true)
  })

  it("reports unprotected when there are no windows at all", () => {
    expect(
      overlapsProtection([], "2026-10-01T10:15:00.000Z", "2026-10-01T10:45:00.000Z"),
    ).toBe(false)
  })

  it("does not protect a recording whose bounds cannot be parsed", () => {
    expect(overlapsProtection([p], "nope", "2026-10-01T10:45:00.000Z")).toBe(false)
  })
})
