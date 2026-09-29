import { describe, expect, it } from "vitest"
import { generateUUID } from "./uuid"

describe("generateUUID", () => {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

  it("generates a valid UUID v4 when crypto.randomUUID is present", () => {
    const id = generateUUID()
    expect(id).toMatch(uuidRegex)
  })

  it("falls back to getRandomValues when crypto.randomUUID is undefined", () => {
    const originalRandomUUID = crypto.randomUUID
    ;(crypto as { randomUUID?: unknown }).randomUUID = undefined
    try {
      const id = generateUUID()
      expect(id).toMatch(uuidRegex)
    } finally {
      ;(crypto as { randomUUID?: unknown }).randomUUID = originalRandomUUID
    }
  })

  it("falls back to Math.random when web crypto is completely undefined", () => {
    const originalCrypto = globalThis.crypto
    delete (globalThis as { crypto?: unknown }).crypto
    try {
      const id = generateUUID()
      expect(id).toMatch(uuidRegex)
    } finally {
      ;(globalThis as { crypto?: unknown }).crypto = originalCrypto
    }
  })
})
