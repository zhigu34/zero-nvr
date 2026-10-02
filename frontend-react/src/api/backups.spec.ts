import { afterEach, describe, expect, it, vi } from "vitest"

import {
  backupStateTone,
  buildCredentialEdit,
  buildRetention,
  buildSchedule,
  createBackupPolicy,
  describeBackupReason,
  emptyPolicyForm,
  policyFormFromView,
  getRecoveryKitStatus,
  isVerifiable,
  passphraseAccepted,
  passphraseByteLength,
  listBackupPolicies,
  listBackupSets,
  RETENTION_MAX,
  runBackupNow,
  runPersistedAnyway,
  scheduleDraft,
  scheduleIsCleared,
  validateBackupPolicyForm,
  verifyBackupSet,
  type BackupPolicyForm,
  type BackupSetView,
} from "./backups"
import { ApiError } from "./client"

/**
 * Three traps this file exists for, all of which fail with a 200:
 *
 * 1. **`schedule: {}` unschedules the policy.** It is a legal value meaning
 *    "never", and a form that sends it because the cron box is empty has
 *    silently disabled the schedule.
 * 2. **A 503 from `POST /backups/run` can mean the backup already exists.** The
 *    row is committed before the enqueue; retrying creates a second one.
 * 3. **PATCHing `credentials.environment` with one key deletes the rest.** The
 *    server falls back to the whole stored dict when the key is absent — and the
 *    stored environment is unreadable, so the form cannot re-read it.
 */

const TZ = "Asia/Shanghai"

function policy(overrides: Partial<BackupPolicyForm> = {}): BackupPolicyForm {
  return { ...emptyPolicyForm(TZ), name: "每日全量", ...overrides }
}

function backup(overrides: Partial<BackupSetView> = {}): BackupSetView {
  return {
    id: "b1",
    backup_policy_id: "p1",
    state: "COMPLETED",
    reason: "manual",
    started_at: "2026-10-01T00:00:00Z",
    completed_at: "2026-10-01T00:10:00Z",
    app_version: "1.0.0",
    schema_revision: "12",
    database_engine: "sqlite",
    restic_snapshot_id: "snap-1",
    size_bytes: 1024,
    verification_state: "VERIFIED",
    last_verified_at: "2026-10-01T00:11:00Z",
    error_code: null,
    sanitized_error: null,
    created_at: "2026-10-01T00:00:00Z",
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
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return seen
}

describe("endpoints", () => {
  it("lists backup sets at a path with no trailing slash", async () => {
    const seen = capture()
    await listBackupPolicies()
    await listBackupSets({ policyId: "p1", state: "FAILED", limit: 20 })
    await runBackupNow({ policy_id: "p1" })
    await verifyBackupSet("b1")

    // `@router.get("")` on prefix="/backups" means exactly `/api/v1/backups`.
    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/backups/policies",
      "GET /api/v1/backups?policy_id=p1&state=FAILED&limit=20",
      "POST /api/v1/backups/run",
      "POST /api/v1/backups/b1/verify",
    ])
  })

  it("passes policy_id to the kit status as a query parameter, not a path segment", async () => {
    const seen = capture()
    await getRecoveryKitStatus("p 1/2")
    expect(seen[0].url).toBe("/api/v1/backups/recovery-kit/status?policy_id=p%201%2F2")
  })
})

describe("runPersistedAnyway", () => {
  it("recognises a 503 whose row was already committed", () => {
    const error = new ApiError(503, "backup_task_queue_unavailable", "queue down", {
      backup_persisted: true,
      backup_id: "b9",
    })
    expect(runPersistedAnyway(error)).toEqual({ persisted: true, backupId: "b9" })
  })

  it("treats an ordinary 503 as a real failure", () => {
    const error = new ApiError(503, "backup_task_queue_unavailable", "queue down", {})
    expect(runPersistedAnyway(error)).toBeNull()
  })

  it("ignores a non-ApiError", () => {
    expect(runPersistedAnyway(new Error("network"))).toBeNull()
    expect(runPersistedAnyway(null)).toBeNull()
  })
})

describe("schedule objects", () => {
  it("treats an empty object as deliberately cleared, not as absent data", () => {
    expect(scheduleIsCleared({})).toBe(true)
    expect(scheduleIsCleared(undefined)).toBe(true)
    expect(scheduleIsCleared({ cron: "0 3 * * *" })).toBe(false)
  })

  it("builds {} when the cron box is empty, which is what unschedules", () => {
    expect(buildSchedule({ cron: "   ", timezone: "Asia/Shanghai" })).toEqual({})
  })

  it("builds both keys when a cron is present", () => {
    // The server requires exactly {cron, timezone}; a stray key is a 400.
    expect(buildSchedule({ cron: " 0 3 * * * ", timezone: " Asia/Shanghai " })).toEqual(
      { cron: "0 3 * * *", timezone: "Asia/Shanghai" },
    )
  })

  it("seeds an empty draft with the system timezone rather than a blank", () => {
    expect(scheduleDraft({}, "Asia/Shanghai")).toEqual({
      cron: "",
      timezone: "Asia/Shanghai",
    })
  })
})

describe("buildCredentialEdit", () => {
  it("sends nothing on keep", () => {
    const body = buildCredentialEdit(
      policy({ credentialsAction: "keep", credentials: { password: "typed", environment: {} } }),
    )
    expect(body).toEqual({ credentials_action: "keep" })
    expect(Object.hasOwn(body, "credentials")).toBe(false)
  })

  it("sends null on clear", () => {
    expect(buildCredentialEdit(policy({ credentialsAction: "clear" }))).toEqual({
      credentials_action: "clear",
      credentials: null,
    })
  })

  it("sends the whole environment on replace, because a partial one deletes the rest", () => {
    const body = buildCredentialEdit(
      policy({
        credentialsAction: "replace",
        credentials: {
          password: "pw",
          environment: { AWS_ACCESS_KEY_ID: "a", RESTIC_CACHE_DIR: "/tmp" },
        },
      }),
    )
    expect(body.credentials).toEqual({
      password: "pw",
      environment: { AWS_ACCESS_KEY_ID: "a", RESTIC_CACHE_DIR: "/tmp" },
    })
  })

  it("drops an entirely blank env row rather than sending an empty key", () => {
    const body = buildCredentialEdit(
      policy({
        credentialsAction: "replace",
        credentials: { password: "pw", environment: { "": "", GOOD: "v" } },
      }),
    )
    expect(body.credentials?.environment).toEqual({ GOOD: "v" })
  })
})

describe("buildRetention", () => {
  it("drops empty boxes and keeps integers", () => {
    const body = buildRetention(
      policy({
        retention: { keep_last: 5, keep_daily: "", keep_weekly: 0 },
      }),
    )
    // 0 is meaningful — "keep none in this bucket" — so it survives.
    expect(body).toEqual({ keep_last: 5, keep_weekly: 0 })
  })
})

describe("validateBackupPolicyForm", () => {
  it("accepts a minimal creating form", () => {
    const errors = validateBackupPolicyForm(
      policy({
        repository: "s3:s3.example.com/bucket",
        credentialsAction: "replace",
        credentials: { password: "pw", environment: {} },
      }),
      { creating: true },
    )
    expect(errors).toEqual([])
  })

  it("requires a repository only when creating or editing that field", () => {
    const form = policy({ repository: "" })
    expect(
      validateBackupPolicyForm(form, { creating: false }).map((e) => e.field),
    ).not.toContain("repository")
    expect(
      validateBackupPolicyForm(form, { creating: true }).map((e) => e.field),
    ).toContain("repository")
  })

  it("refuses credentials embedded in the URL", () => {
    // They would be a second, unrevokable copy of the secret.
    const errors = validateBackupPolicyForm(
      policy({ repository: "s3://user:pass@s3.example.com/bucket" }),
      { creating: true },
    )
    expect(errors.some((e) => e.message.includes("内嵌"))).toBe(true)
  })

  it("refuses newlines in the repository", () => {
    const errors = validateBackupPolicyForm(
      policy({ repository: "s3:s3.example.com/b\nX: 1" }),
      { creating: true },
    )
    expect(errors.map((e) => e.field)).toContain("repository")
  })

  it("rejects reserved and malformed environment names", () => {
    const errors = validateBackupPolicyForm(
      policy({
        credentialsAction: "replace",
        credentials: {
          password: "pw",
          environment: { RESTIC_PASSWORD: "x", lower_case: "y", "1BAD": "z" },
        },
      }),
      { creating: true },
    )
    expect(errors.filter((e) => e.field === "credentials")).toHaveLength(3)
  })

  it("requires a password on replace but not on keep", () => {
    expect(
      validateBackupPolicyForm(
        policy({ credentialsAction: "replace", credentials: { password: "", environment: {} } }),
        { creating: false },
      ).map((e) => e.field),
    ).toContain("credentials")
    expect(
      validateBackupPolicyForm(
        policy({ credentialsAction: "keep", credentials: { password: "", environment: {} } }),
        { creating: false },
      ).map((e) => e.field),
    ).not.toContain("credentials")
  })

  it("requires a timezone alongside a cron", () => {
    const errors = validateBackupPolicyForm(
      policy({ schedule: { cron: "0 3 * * *", timezone: "  " } }),
      { creating: false },
    )
    expect(errors.map((e) => e.field)).toContain("schedule")
  })

  it("bounds retention buckets and rejects non-integers", () => {
    for (const value of [-1, RETENTION_MAX + 1, 1.5]) {
      expect(
        validateBackupPolicyForm(policy({ retention: { keep_daily: value } }), {
          creating: false,
        }).map((e) => e.field),
      ).toContain("retentionValue")
    }
  })
})

describe("createBackupPolicy", () => {
  it("sends the repository and credentials as write-only fields", async () => {
    const seen = capture()
    await createBackupPolicy({
      name: "每日全量",
      repository: "s3:s3.example.com/bucket",
      database_backend: "sqlite",
      credentials: { password: "pw", environment: { A: "1" } },
      schedule: {},
      retention: {},
    })
    expect(seen[0].body).toMatchObject({
      repository: "s3:s3.example.com/bucket",
      credentials: { password: "pw", environment: { A: "1" } },
      schedule: {},
    })
  })
})

describe("form factories", () => {
  const view = {
    id: "p1",
    name: "每日全量",
    enabled: true,
    database_backend: "postgresql" as const,
    schedule: { cron: "0 3 * * *", timezone: "Asia/Shanghai" },
    retention: { keep_daily: 7, keep_weekly: 4 },
    verify_after_backup: false,
    repository_check_schedule: {},
    include_deployment_config: true,
    repository_configured: true,
    credentials_configured: true,
  }

  it("seeds the readable fields from a saved policy", () => {
    const form = policyFormFromView(view, "UTC")
    expect(form.name).toBe("每日全量")
    expect(form.databaseBackend).toBe("postgresql")
    expect(form.schedule).toEqual({ cron: "0 3 * * *", timezone: "Asia/Shanghai" })
    expect(form.retention).toEqual({ keep_daily: 7, keep_weekly: 4 })
    expect(form.verifyAfterBackup).toBe(false)
    expect(form.includeDeploymentConfig).toBe(true)
  })

  it("leaves the write-only fields blank and defaulted to keep", () => {
    // The view says only that a repository and credentials exist. Pre-filling
    // anything here would be inventing a value the server never sent.
    const form = policyFormFromView(view, "UTC")
    expect(form.repository).toBe("")
    expect(form.credentials).toEqual({ password: "", environment: {} })
    expect(form.credentialsAction).toBe("keep")
  })

  it("copies retention so editing the form cannot mutate the cache", () => {
    const form = policyFormFromView(view, "UTC")
    form.retention.keep_daily = 99
    expect(view.retention.keep_daily).toBe(7)
  })

  it("an empty saved schedule becomes a blank draft keeping the system zone", () => {
    const form = policyFormFromView({ ...view, schedule: {} }, "Asia/Shanghai")
    expect(form.schedule).toEqual({ cron: "", timezone: "Asia/Shanghai" })
  })

  it("starts a new policy on 'replace', because a create body requires credentials", () => {
    // "Keep" on a form with nothing stored would post an empty password and
    // fail about a field the operator never saw.
    expect(emptyPolicyForm(TZ).credentialsAction).toBe("replace")
    // The edit path is the opposite: the stored values are unreadable.
    const view = {
      id: "p1",
      name: "x",
      enabled: true,
      database_backend: "sqlite" as const,
      schedule: {},
      retention: {},
      verify_after_backup: true,
      repository_check_schedule: {},
      include_deployment_config: false,
      repository_configured: true,
      credentials_configured: true,
    }
    expect(policyFormFromView(view, TZ).credentialsAction).toBe("keep")
  })
})

describe("passphrase length", () => {
  it("measures bytes, because the service does", () => {
    // Sixteen CJK characters is 48 UTF-8 bytes: the schema would pass it and
    // so would this, but sixteen 2-byte characters would fail the service.
    expect(passphraseAccepted("a".repeat(16))).toBe(true)
    expect(passphraseAccepted("安".repeat(16))).toBe(true)
    expect(passphraseAccepted("a".repeat(15))).toBe(false)
    expect(passphraseByteLength("安")).toBe(3)
  })
})

describe("presentation", () => {
  it("maps the four states to distinct tones", () => {
    expect(backupStateTone("COMPLETED")).toBe("online")
    expect(backupStateTone("FAILED")).toBe("offline")
    expect(backupStateTone("RUNNING")).toBe("degraded")
    expect(backupStateTone("PENDING")).toBe("degraded")
    expect(backupStateTone("WEIRD")).toBe("unknown")
  })

  it("names the scheduled reason the request enum cannot express", () => {
    expect(describeBackupReason("scheduled")).toBe("定时触发")
    expect(describeBackupReason("manual")).toBe("手动触发")
    expect(describeBackupReason(null)).toBe("未知")
  })

  it("only treats a completed set with a snapshot as verifiable", () => {
    expect(isVerifiable(backup())).toBe(true)
    expect(isVerifiable(backup({ state: "FAILED" }))).toBe(false)
    expect(isVerifiable(backup({ restic_snapshot_id: null }))).toBe(false)
  })
})
