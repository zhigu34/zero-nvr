import { KeyRound, RefreshCw } from "lucide-react"

import {
  SECRET_STORE_STATUS_LABEL,
  rotationBlockedReason,
  secretStoreTone,
  type SecretStoreHealth,
  type SecretStoreStatus,
} from "../../api/secretStore"
import { useSecretStoreHealth } from "../../lib/queries"
import { useRotateSecretStore } from "../../lib/secretStoreMutations"
import { useConfirm } from "../ui/Confirm"
import { cn } from "../../lib/utils"
import { Button } from "../ui/primitives"
import {
  Callout,
  PrototypeNote,
  StatusDot,
  type HealthTone,
} from "../ui/display"

/**
 * 密钥环健康状况。
 *
 * 这个面板替代的 Vue 面板名叫「密钥列表」，但它从来就不列密钥——
 * `GET /system/secret-store` 只回计数，任何接口都不会返回可解密的内容
 * （`system/api.py:219-277`）。所以这里画的是一份健康报告，不是一张密钥表。
 *
 * 三个状态是一段严格的阶梯，不是同一个状况的三种说法
 * （`secret_store.py:437-442`）：
 *
 * | status | 何时出现 | 含义 |
 * |---|---|---|
 * | `OK` | 无陈旧、无不可读 | 每条记录都在当前密钥上 |
 * | `ROTATION_REQUIRED` | stale > 0 且 unreadable == 0 | 可重写，值得做 |
 * | `ERROR` | unreadable > 0 | 至少一条记录用任何已知密钥都解不开 |
 *
 * 真正需要小心的是 `ERROR` 下的轮换按钮。`rotate_records` 会先把所有记录
 * 解密一遍才开始写（`secret_store.py:474-485`），而 `decrypt_bytes` 遇到
 * 读不出来的会抛异常。所以从 `ERROR` 发起轮换不是「降级轮换」，是一次写到
 * 中途就炸掉的请求，操作者能看到的只有一个跟那条坏记录毫无关系的 500。
 * 按钮因此直接由 `rotationBlockedReason(health) !== null` 控制，并把它的原因
 * 原文显示在按钮旁边——按钮可见但不可用，而不是消失。
 *
 * 计数也不是六个互不相干的数字：`current + stale == total` 恒成立
 * （`secret_store.py:422-424`，每条记录要么在主密钥上要么不在），而
 * `unreadable` 是**另一根轴**——它统计的是解密失败，范围与上面两者重叠，
 * 不能加进总数，否则会算出一个不存在的记录数。
 */
export function SecretStorePanel() {
  const health = useSecretStoreHealth()
  const rotate = useRotateSecretStore()
  const confirm = useConfirm()

  if (health.isPending) {
    return <p className="text-xs text-muted-foreground">读取中…</p>
  }

  // A read that failed says so. A blank panel here would be read as "no
  // records", which is the one conclusion the operator must not draw from a
  // request that never came back.
  if (health.error || !health.data) {
    return (
      <Callout tone="offline" title="无法读取密钥环状态">
        {health.error?.message ?? "服务端没有返回密钥环报告。"}
      </Callout>
    )
  }

  const report = health.data
  // `null` is the only state in which rotation is available, so the button and
  // the reason next to it can never disagree about why.
  const blocked = rotationBlockedReason(report)
  const tone = secretStoreTone(report.status)

  async function onRotate() {
    const ok = await confirm({
      title: "轮换密钥环",
      message:
        `将把 ${report.stale_records} 条仍在旧密钥上的记录重新加密到当前密钥` +
        `（${report.primary_key_id}）。这些记录的内容会被重写，轮换之后没有任何` +
        `接口能把它们退回旧密钥——旧密钥仍在配置里，但记录不会再变回旧的。`,
      confirmLabel: "轮换",
      danger: true,
    })
    if (ok) rotate.mutate(undefined)
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-border">
        <div className="flex items-center gap-1.5 border-b border-border px-3 py-2.5">
          <KeyRound className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">密钥环</h3>
        </div>

        <div className="space-y-3 p-3">
          <div
            role="group"
            aria-label="密钥环状态"
            className="flex flex-wrap items-center gap-2"
          >
            <StatusDot tone={tone} />
            <span className={cn("text-sm font-semibold", TONE_TEXT[tone])}>
              {SECRET_STORE_STATUS_LABEL[report.status]}
            </span>
            <p className="text-[11px] text-muted-foreground">
              {STATUS_NOTE[report.status](report)}
            </p>
          </div>

          <KeyRingCounts health={report} />

          {report.status === "ERROR" && (
            <Callout tone="offline" title="需要人工处理">
              轮换无法救回这些记录：它会先把全部记录解密一遍再动手，读不出来的
              那几条会让整个操作中断。请先确认应加载的历史密钥是否仍在密钥环配置里。
            </Callout>
          )}
          {report.status === "ROTATION_REQUIRED" && (
            <Callout tone="degraded" title="建议尽快轮换">
              历史密钥一旦从配置里移除，停在旧密钥上的记录就再也读不出来了。
            </Callout>
          )}

          <div
            role="group"
            aria-label="密钥轮换"
            className="flex flex-wrap items-center gap-2"
          >
            <Button
              size="sm"
              disabled={blocked !== null || rotate.isPending}
              onClick={onRotate}
            >
              <RefreshCw />
              {rotate.isPending ? "轮换中…" : "轮换密钥环"}
            </Button>
            {blocked && (
              <p
                className={cn(
                  "text-[11px]",
                  report.unreadable_records > 0
                    ? "text-status-offline"
                    : "text-muted-foreground",
                )}
              >
                {blocked}
              </p>
            )}
          </div>
        </div>
      </section>

      <PrototypeNote>
        这份报告会为了计数而解密每一条记录，所以它不是随手刷新的数据；轮换本身
        不可撤销。接口从不返回密钥内容，这里能看到的只有计数和当前密钥的标识。
      </PrototypeNote>
    </div>
  )
}

/**
 * The counts, arranged so the arithmetic is visible.
 *
 * `current + stale` is the whole store (`secret_store.py:422-424`), so it is
 * stated as one line rather than as two unrelated figures. `unreadable` is
 * reported separately and deliberately not added in: it counts decrypt
 * failures, and a record that is already on the current key can still be one
 * of them.
 *
 * A zero is a result, not missing data, so each one is phrased as something
 * that is fine — a panel that merely prints `0` reads like a broken report.
 */
function KeyRingCounts({ health }: { health: SecretStoreHealth }) {
  return (
    <div
      role="group"
      aria-label="密钥环统计"
      className="divide-y divide-border rounded-lg border border-border"
    >
      <div className="flex items-start justify-between gap-4 px-3 py-2">
        <span className="text-xs text-muted-foreground">记录总数</span>
        <div className="text-right">
          <p className="text-sm font-semibold tabular-nums">
            {health.total_records} 条
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {health.stale_records === 0
              ? `全部 ${health.total_records} 条都在当前密钥上。`
              : `其中 ${health.current_records} 条在当前密钥上，` +
                `${health.stale_records} 条还在旧密钥上。`}
          </p>
        </div>
      </div>

      <div className="flex items-start justify-between gap-4 px-3 py-2">
        <span className="text-xs text-muted-foreground">无法解密</span>
        <p
          className={cn(
            "text-right text-[11px]",
            health.unreadable_records > 0
              ? "text-status-offline"
              : "text-muted-foreground",
          )}
        >
          {health.unreadable_records === 0
            ? "0 条，没有任何记录读不出来"
            : `${health.unreadable_records} 条，用已加载的密钥都解不开`}
        </p>
      </div>

      <div className="flex items-start justify-between gap-4 px-3 py-2">
        <span className="text-xs text-muted-foreground">历史密钥</span>
        <p className="text-right text-[11px] text-muted-foreground">
          {health.previous_key_count === 0
            ? "0 个，只加载了当前密钥"
            : `${health.previous_key_count} 个（已被取代，仍在配置里，用于解密旧记录）`}
        </p>
      </div>

      <div className="flex items-start justify-between gap-4 px-3 py-2">
        <span className="text-xs text-muted-foreground">当前密钥 ID</span>
        <div className="text-right">
          <p className="font-mono text-xs">{health.primary_key_id}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            这是标识，不是密钥本身。
          </p>
        </div>
      </div>
    </div>
  )
}

/** What each rung of the ladder means, said in the operator's terms. */
const STATUS_NOTE: Record<SecretStoreStatus, (health: SecretStoreHealth) => string> = {
  OK: () => "每条记录都在当前密钥上，无需处理。",
  ROTATION_REQUIRED: (health) =>
    `有 ${health.stale_records} 条记录仍用旧密钥加密，可以安全重写。`,
  ERROR: (health) =>
    `有 ${health.unreadable_records} 条记录用任何已加载的密钥都解不开，` +
    `轮换在当前状态下不可用。`,
}

const TONE_TEXT: Record<HealthTone, string> = {
  online: "text-status-online",
  degraded: "text-status-degraded",
  offline: "text-status-offline",
  unknown: "text-muted-foreground",
}
