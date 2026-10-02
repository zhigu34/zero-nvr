/**
 * Secret store contract. Mirrors `backend/app/modules/system/schemas.py:229-248`
 * and the endpoints in `system/api.py:219-277`.
 *
 * ## This is a health report, not a key listing
 *
 * Despite the Vue panel's name, nothing here returns key material, key ids
 * other than the primary, or anything decryptable. `GET /system/secret-store`
 * returns counts:
 *
 * ```text
 * total_records / current_records / stale_records / unreadable_records
 * previous_key_count / primary_key_id / rotation_ready / status
 * ```
 *
 * The three statuses are computed in `secret_store.py:437-442` and they are a
 * strict ladder, not three labels for one condition:
 *
 * | status | when | what it means |
 * |---|---|---|
 * | `OK` | no stale, no unreadable | every record is on the current key |
 * | `ROTATION_REQUIRED` | stale > 0, unreadable == 0 | re-writable, worth doing |
 * | `ERROR` | unreadable > 0 | at least one record cannot be decrypted **at all** |
 *
 * ## Why `ERROR` must not offer a rotate button
 *
 * `rotate_records` decrypts every record up front, before writing anything
 * (`secret_store.py:474-485`), and `decrypt_bytes` raises on the ones it
 * cannot read. So rotating from an `ERROR` state is not a degraded rotation, it
 * is a request that throws partway — and the operator's only symptom would be a
 * 500 that says nothing about the unreadable record.
 *
 * `rotation_ready` is the server's own answer to "is it safe to rotate right
 * now": `stale > 0 and unreadable == 0` (`secret_store.py:455-458`). The button
 * is gated on that field rather than on a guess about which status is
 * actionable.
 */
import { api } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type SecretStoreStatus = "OK" | "ROTATION_REQUIRED" | "ERROR"

export type SecretStoreHealth = {
  status: SecretStoreStatus
  total_records: number
  /** Records encrypted with `primary_key_id`. */
  current_records: number
  /** Records still on a superseded key. These are what rotation re-writes. */
  stale_records: number
  /** Records whose ciphertext cannot be decrypted with any known key. */
  unreadable_records: number
  /** Superseded keys still loaded, excluding the primary. */
  previous_key_count: number
  primary_key_id: string
  rotation_ready: boolean
}

export type SecretStoreRotation = {
  total_records: number
  /** Records actually re-encrypted in this call. */
  rotated_records: number
  /** Records that were already on the current key and were left alone. */
  already_current_records: number
  /** The report taken after the rotation, in the same call. */
  health: SecretStoreHealth
}

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

/** `system.view`. A read — it decrypts to count, but writes nothing. */
export function getSecretStoreHealth(signal?: AbortSignal) {
  return api.get<SecretStoreHealth>("/secret-store", signal)
}

/**
 * `system.manage`. Irreversible in the only direction that matters: it
 * re-encrypts stale records onto the primary key. There is no endpoint to undo
 * it, and the old keys stay loaded only because the deployment still lists them.
 */
export function rotateSecretStore() {
  return api.post<SecretStoreRotation>("/secret-store/rotate")
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

export const SECRET_STORE_STATUS_LABEL: Record<SecretStoreStatus, string> = {
  OK: "正常",
  ROTATION_REQUIRED: "需要轮换",
  ERROR: "存在无法解密的记录",
}

export type HealthTone = "online" | "degraded" | "offline" | "unknown"

export function secretStoreTone(status: SecretStoreStatus): HealthTone {
  if (status === "OK") return "online"
  if (status === "ROTATION_REQUIRED") return "degraded"
  return "offline"
}

/**
 * Why the rotate button is unavailable, in the operator's terms.
 *
 * Returns `null` when rotation is available, so the call site is a single
 * `disabled={reason !== null}` rather than a chain of conditions that can
 * disagree with the server's own `rotation_ready`.
 */
export function rotationBlockedReason(
  health: SecretStoreHealth,
): string | null {
  if (health.unreadable_records > 0) {
    return (
      `有 ${health.unreadable_records} 条记录无法解密。` +
      "轮换会先解密全部记录，遇到读不出来的就会中断，" +
      "所以这里不提供轮换按钮——先恢复密钥环配置。"
    )
  }
  if (health.stale_records === 0) {
    return "没有待轮换的记录。"
  }
  if (!health.rotation_ready) {
    return "服务端判定当前不可轮换。"
  }
  return null
}

/**
 * What a completed rotation did, in one sentence.
 *
 * `rotated_records` and `already_current_records` sum to `total_records` by
 * construction (`secret_store.py:487-503`), so a discrepancy means the report
 * and the work disagree — worth surfacing rather than summing silently.
 */
export function describeRotation(result: SecretStoreRotation): string {
  if (result.rotated_records === 0) {
    return `没有记录需要重写（${result.total_records} 条均已是当前密钥）。`
  }
  return `已重写 ${result.rotated_records} 条 / 共 ${result.total_records} 条，其余 ${result.already_current_records} 条本就是当前密钥。`
}
