import { useState } from "react"
import { Archive, Cloud, HardDrive, Pencil, Plus, RotateCw, TriangleAlert } from "lucide-react"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Select,
  Separator,
  Switch,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/primitives"
import {
  Callout,
  KeyValue,
  PageHeader,
  ProgressBar,
  PrototypeNote,
  RowActions,
  Section,
  StatCard,
  StatusLabel,
} from "../components/ui/display"
import {
  auditEntries,
  backupPolicies,
  formatGb,
  retentionPolicies,
  storageTargets,
  type BackupPolicy,
  type RetentionPolicy,
  type StorageTarget,
} from "../lib/mock"
import { cn } from "../lib/utils"

const HEALTH: Record<
  StorageTarget["health"],
  { label: string; tone: "online" | "degraded" | "offline" }
> = {
  online: { label: "正常", tone: "online" },
  degraded: { label: "写入异常", tone: "degraded" },
  offline: { label: "不可用", tone: "offline" },
}

const KIND_ICON: Record<StorageTarget["kind"], typeof HardDrive> = {
  本地磁盘: HardDrive,
  云盘归档: Cloud,
  备份: Archive,
}

const BACKUP_RESULT: Record<
  BackupPolicy["lastResult"],
  { label: string; variant: "success" | "danger" | "warning" }
> = {
  success: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "danger" },
  running: { label: "执行中", variant: "warning" },
}

export function StorageView() {
  const [threshold, setThreshold] = useState("90")
  const [retention, setRetention] = useState<RetentionPolicy[]>(retentionPolicies)
  const [backups, setBackups] = useState<BackupPolicy[]>(backupPolicies)

  const totalGb = storageTargets.reduce((a, t) => a + t.totalGb, 0)
  const usedGb = storageTargets.reduce((a, t) => a + t.usedGb, 0)
  const usedPct = (usedGb / totalGb) * 100
  const writeMbps = storageTargets.reduce((a, t) => a + t.writeMbps, 0)
  const recTarget = storageTargets.find((t) => t.isRecordingTarget)
  const lastSweep = auditEntries.find((a) => a.action === "retention.sweep")
  const sweepFailed = lastSweep?.result === "failed"
  const failedBackups = backups.filter((b) => b.lastResult === "failed")

  return (
    <div className="space-y-4 p-5">
      <PageHeader
        title="存储"
        description="本地存储目标、云盘归档（OpenList）、保留策略、容量水位。先归档后删除是安全阀。"
        actions={
          <Button size="sm">
            <Plus /> 添加存储目标
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="总容量"
          value={formatGb(totalGb)}
          icon={<HardDrive className="size-4" />}
          hint={`${storageTargets.length} 个目标 · 含备份盘`}
        />
        <StatCard
          label="已用容量"
          value={formatGb(usedGb)}
          unit={`${usedPct.toFixed(0)}%`}
          tone={usedPct >= 85 ? "degraded" : "unknown"}
        />
        <StatCard
          label="写入速率"
          value={writeMbps.toFixed(1)}
          unit="Mbps"
          hint={`录像 ${recTarget?.writeMbps ?? 0} · 归档 6.4`}
        />
        <StatCard
          label="归档状态"
          value={sweepFailed ? "上次失败" : "正常"}
          tone={sweepFailed ? "offline" : "online"}
          icon={<Archive className="size-4" />}
          hint={sweepFailed ? `${lastSweep?.time} · ${lastSweep?.resource}` : "最近一次执行成功"}
        />
      </div>

      <Section
        title="存储目标"
        description="只有标记为「当前录像目标」的本地磁盘承载实时写入，其余用于归档与备份。"
        actions={
          <>
            <span className="text-xs text-muted-foreground">告警水位</span>
            <Select
              className="w-24"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            >
              <option value="80">80%</option>
              <option value="85">85%</option>
              <option value="90">90%</option>
              <option value="95">95%</option>
            </Select>
          </>
        }
      >
        <div className="grid gap-3 lg:grid-cols-3">
          {storageTargets.map((t) => {
            const pct = (t.usedGb / t.totalGb) * 100
            const overWater = pct >= Number(threshold)
            const alarm = overWater || t.health !== "online"
            const Icon = KIND_ICON[t.kind]
            const free = t.totalGb - t.usedGb
            return (
              <Card
                key={t.id}
                className={cn(
                  "flex flex-col",
                  alarm && "border-status-offline/40",
                )}
              >
                <CardHeader>
                  <div className="min-w-0">
                    <CardTitle className="flex items-center gap-2">
                      <Icon className="size-4 text-muted-foreground" />
                      {t.name}
                    </CardTitle>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{t.kind}</Badge>
                      {t.isRecordingTarget && (
                        <Badge variant="default">当前录像目标</Badge>
                      )}
                      {overWater && (
                        <Badge variant="danger">超告警水位</Badge>
                      )}
                    </div>
                  </div>
                  <StatusLabel
                    tone={HEALTH[t.health].tone}
                    className="shrink-0 pt-0.5"
                  >
                    {HEALTH[t.health].label}
                  </StatusLabel>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-3">
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="text-muted-foreground">位置</span>
                    <span className="truncate font-mono text-muted-foreground">
                      {t.location}
                    </span>
                  </div>
                  <div>
                    <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
                      <span className="text-muted-foreground">容量</span>
                      <span className="tabular-nums">
                        {formatGb(t.usedGb)} / {formatGb(t.totalGb)}
                      </span>
                    </div>
                    <ProgressBar
                      value={pct}
                      tone={alarm ? "offline" : "online"}
                      showLabel
                    />
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      剩余 {formatGb(free)}
                    </p>
                  </div>
                  <KeyValue label="写入速率">
                    <span className="tabular-nums">
                      {t.writeMbps} {t.writeMbps > 0 ? "Mbps" : "Mbps（无写入）"}
                    </span>
                  </KeyValue>
                  {t.health !== "online" && (
                    <div className="mt-auto rounded-lg border border-status-offline/30 bg-status-offline/8 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground">
                      <span className="mb-0.5 flex items-center gap-1.5 font-medium text-foreground">
                        <TriangleAlert className="size-3.5 text-status-offline" />
                        该目标不会随保留策略释放空间
                      </span>
                      写入速率已归零，今日 02:30 的「每日全量」备份失败后没有新的数据
                      落盘。写入恢复前，它对可用留存量没有贡献。
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </Section>

      <Section
        title="保留策略"
        description="决定录像在本地保留多久、超期后是否先归档。清理执行由后台 sweep 触发。"
      >
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <THead>
              <TR>
                <TH>目标</TH>
                <TH>保留天数</TH>
                <TH>归档阈值</TH>
                <TH>先归档</TH>
                <TH>最近执行</TH>
                <TH className="text-right">操作</TH>
              </TR>
            </THead>
            <TBody>
              {retention.map((r) => (
                <TR key={r.id}>
                  <TD className="font-medium">{r.target}</TD>
                  <TD>
                    <span className="tabular-nums">{r.retainDays} 天</span>
                  </TD>
                  <TD className="text-muted-foreground">
                    {r.archiveAfterHours > 0 ? (
                      <span className="tabular-nums">
                        超期 {r.archiveAfterHours} 小时后归档
                      </span>
                    ) : (
                      <span>到期直接清理</span>
                    )}
                  </TD>
                  <TD>
                    <Switch
                      aria-checked={r.archiveEnabled}
                      aria-label={`${r.target} 先归档`}
                      onClick={() =>
                        setRetention((prev) =>
                          prev.map((x) =>
                            x.id === r.id
                              ? { ...x, archiveEnabled: !x.archiveEnabled }
                              : x,
                          ),
                        )
                      }
                    />
                  </TD>
                  <TD
                    className={cn(
                      "text-xs",
                      r.lastRun === "—" && "text-muted-foreground",
                    )}
                  >
                    {r.lastRun}
                  </TD>
                  <TD>
                    <RowActions>
                      <Button variant="ghost" size="icon-sm" title="编辑策略">
                        <Pencil className="size-3.5" />
                      </Button>
                    </RowActions>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>

        <Callout tone="online" title="先归档，后删除">
          保留策略的清理不是删除。sweep 会先把待清理片段写入云盘归档目标，只有归档
          成功才删除本地副本；<span className="text-foreground">归档失败时文件保留在原地</span>
          ，状态记为「保留未删除」，等下次执行重试。磁盘因此不会因为一次归档故障而
          被清空——代价是这段时间容量只涨不降。
        </Callout>
      </Section>

      <Section
        title="备份"
        description="备份是副本，不是保留策略的替代。备份盘写满后同样受保留策略约束。"
      >
        {failedBackups.length > 0 && (
          <Callout tone="offline" title="每日全量备份上次执行失败">
            今天 02:30 的「每日全量」没有完成，7.4 TB 录像仍只在
            {recTarget?.name} 上。失败期间该机位只有一份副本，磁盘故障即全部丢失。
            下一次调度前需要人工确认原因。
          </Callout>
        )}

        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <Table>
            <THead>
              <TR>
                <TH>名称</TH>
                <TH>目标位置</TH>
                <TH>计划</TH>
                <TH>上次执行</TH>
                <TH>结果</TH>
                <TH>数据量</TH>
                <TH className="text-right">操作</TH>
              </TR>
            </THead>
            <TBody>
              {backups.map((b) => (
                <TR
                  key={b.id}
                  className={cn(
                    b.lastResult === "failed" &&
                      "bg-status-offline/5 hover:bg-status-offline/10",
                  )}
                >
                  <TD className="font-medium">{b.name}</TD>
                  <TD className="font-mono text-xs text-muted-foreground">
                    {b.destination}
                  </TD>
                  <TD className="text-muted-foreground">{b.schedule}</TD>
                  <TD className="text-xs text-muted-foreground">{b.lastRun}</TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <Badge variant={BACKUP_RESULT[b.lastResult].variant}>
                        {BACKUP_RESULT[b.lastResult].label}
                      </Badge>
                      {b.lastResult === "failed" && (
                        <span className="text-[11px] text-destructive">
                          副本未更新
                        </span>
                      )}
                    </div>
                  </TD>
                  <TD>
                    <span className="tabular-nums">{b.size}</span>
                  </TD>
                  <TD>
                    <div className="flex justify-end">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={b.lastResult === "running"}
                        onClick={() =>
                          setBackups((prev) =>
                            prev.map((x) =>
                              x.id === b.id ? { ...x, lastResult: "running" } : x,
                            ),
                          )
                        }
                      >
                        <RotateCw /> {b.lastResult === "failed" ? "重试" : "立即执行"}
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>

        <Separator className="my-1" />

        <p className="text-xs leading-relaxed text-muted-foreground">
          备份失败不会阻塞录像，也不会自动降低保留天数。容量吃紧时唯一可选的动作是
          人工处理——这正是把失败显式展示出来的原因。
        </p>
      </Section>

      <PrototypeNote>
        容量、写入速率与执行结果全部来自静态 fixture，不代表真实磁盘状态；「重试」与
        「先归档」开关只在本次会话内改变本地状态。
      </PrototypeNote>
    </div>
  )
}
