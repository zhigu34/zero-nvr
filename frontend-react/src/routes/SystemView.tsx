import { useMemo, useState } from "react"

import { Button, Input, Select } from "../components/ui/primitives"
import {
  Callout,
  PageHeader,
  Section,
  StatusDot,
  Tabs,
  type HealthTone,
} from "../components/ui/display"
import { NotificationsPanel } from "../components/system/NotificationsPanel"
import { SecretStorePanel } from "../components/system/SecretStorePanel"
import { FrigatePanel } from "../components/system/FrigatePanel"
import { ApiTokensPanel } from "../components/system/ApiTokensPanel"
import {
  useCameraClockHealth,
  useNotificationTargets,
  useSystemHealth,
  useSystemSettings,
} from "../lib/queries"
import {
  useApplyCameraNtp,
  useSaveSystemSettings,
} from "../lib/systemMutations"
import {
  RUNTIME_FIELDS,
  diffRuntime,
  formatByUnit,
  formatBytes,
  ntpModeForServers,
  parseServerList,
  validateRuntime,
  type SettingsError,
} from "../lib/systemSettingsSchema"
import type { HealthComponent } from "../api/systemSettings"

/**
 * System settings.
 *
 * Two things drive the layout:
 *
 * 1. **The `general` group mirrors `time`.** `display_timezone` is populated
 *    from `time.recording_timezone` on every read, and a write to it is
 *    redirected there (`system/api.py:1068`). `camera_ntp_servers` is worse:
 *    writing a non-empty list *also* forces the NTP mode to `manual`
 *    (`system/api.py:1086`). So the page writes through `time.*` once and
 *    shows the mirrors, instead of presenting two fields that quietly
 *    overwrite each other.
 *
 * 2. **`recording_timezone` has no consumer.** Policy evaluation uses each
 *    camera's own `schedule_timezone`. The field is shown because it exists,
 *    labelled so nobody assumes setting it changes when recordings are cut.
 */

const COMPONENT_LABEL: Record<string, string> = {
  database: "数据库",
  media: "媒体服务",
  worker: "后台任务",
  storage: "存储",
  scheduler: "调度器",
}

const COMPONENT_TONE: Record<HealthComponent["status"], HealthTone> = {
  OK: "online",
  DEGRADED: "degraded",
  ERROR: "offline",
  DISABLED: "unknown",
}

type SystemTab =
  | "settings"
  | "notifications"
  | "secrets"
  | "frigate"
  | "tokens"

/**
 * System settings, notification channels, key ring, Frigate and API tokens.
 *
 * The tab shell sits **outside** the settings loading and error guards, and
 * that placement is the point rather than an accident of layout. Settings are
 * three nested groups read as one payload, so a partial or failing response
 * takes down everything that depends on it — but the notification targets, the
 * key ring report, the Frigate config and the token list are separate
 * endpoints with separate failure modes. Hoisting the shell means "system
 * settings is broken" never also means "you cannot see that alerts are failing
 * to send", which is exactly the moment somebody needs to read the delivery
 * log.
 */
export function SystemView() {
  const [tab, setTab] = useState<SystemTab>("settings")
  // Fetched here only for the tab badge, so the operator can see that there are
  // no targets at all without switching tabs first. A plain GET, no side effect.
  const targets = useNotificationTargets()

  return (
    <div className="space-y-4 p-5">
      <PageHeader title="系统设置" description="系统参数、通知渠道与集成。" />

      <Tabs
        active={tab}
        onChange={(key) => setTab(key as SystemTab)}
        tabs={[
          { key: "settings", label: "系统设置" },
          {
            key: "notifications",
            label: "通知渠道",
            count: targets.data?.length,
          },
          { key: "secrets", label: "密钥环" },
          { key: "frigate", label: "Frigate 集成" },
          // Named "我的" because the endpoints are the signed-in account's own
          // resources: there is no `/users/{id}/tokens`, so an admin cannot
          // manage anybody else's token from here (G-32). The tab will move to
          // the personal account page when that page exists.
          { key: "tokens", label: "API 令牌（我的）" },
        ]}
      />

      {tab === "settings" ? <SystemSettingsTab /> : null}
      {tab === "notifications" ? <NotificationsPanel /> : null}
      {tab === "secrets" ? <SecretStorePanel /> : null}
      {tab === "frigate" ? <FrigatePanel /> : null}
      {tab === "tokens" ? <ApiTokensPanel /> : null}
    </div>
  )
}

function SystemSettingsTab() {
  const settingsQuery = useSystemSettings()
  const healthQuery = useSystemHealth()
  const clockQuery = useCameraClockHealth()
  const save = useSaveSystemSettings()
  const applyNtp = useApplyCameraNtp()

  const settings = settingsQuery.data

  const [systemName, setSystemName] = useState<string | null>(null)
  const [recordingTimezone, setRecordingTimezone] = useState<string | null>(null)
  const [ntpServers, setNtpServers] = useState<string | null>(null)
  const [runtimeOverrides, setRuntimeOverrides] = useState<
    Record<string, number> | null
  >(null)

  const runtime = useMemo(() => {
    if (!settings) return null
    return { ...settings.runtime, ...(runtimeOverrides ?? {}) }
  }, [settings, runtimeOverrides])

  const runtimeErrors: SettingsError[] = useMemo(
    () => validateRuntime(runtime ?? {}),
    [runtime],
  )
  const runtimeErrorFor = (key: string) =>
    runtimeErrors.find((error) => error.field === key)?.message ?? null

  if (settingsQuery.isPending) {
    return <p className="text-xs text-muted-foreground">读取中…</p>
  }

  // Settings are three nested groups. A partial payload — a group missing
  // because of contract drift or a cached value from an older build — has to
  // land in the error surface rather than crash the page on a property read.
  const groupsIntact =
    Boolean(settings?.general) &&
    Boolean(settings?.time) &&
    Boolean(settings?.runtime)

  if (settingsQuery.isError || !settings || !runtime || !groupsIntact) {
    return (
      <Callout tone="offline" title="无法加载系统设置">
        {settingsQuery.error instanceof Error
          ? settingsQuery.error.message
          : "响应结构不符合预期：缺少 general / time / runtime 分组"}
      </Callout>
    )
  }

  const effectiveName = systemName ?? settings.general.system_name
  const effectiveTimezone =
    recordingTimezone ?? settings.time.recording_timezone
  const effectiveNtpRaw =
    ntpServers ?? settings.time.managed_camera_ntp_servers.join(", ")
  const runtimeChanged = diffRuntime(settings.runtime, runtime ?? {})

  const submit = () => {
    save.mutate({
      ...(effectiveName !== settings.general.system_name
        ? { general: { system_name: effectiveName } }
        : {}),
      ...(effectiveTimezone !== settings.time.recording_timezone
        ? { time: { recording_timezone: effectiveTimezone } }
        : {}),
      // Only sent when the list actually moved, because writing it also
      // rewrites the mode whether or not that is what the operator wanted.
      ...(effectiveNtpRaw !==
      settings.time.managed_camera_ntp_servers.join(", ")
        ? { time: { ...ntpModeForServers(parseServerList(effectiveNtpRaw)) } }
        : {}),
      ...(Object.keys(runtimeChanged).length > 0
        ? { runtime: runtimeChanged }
        : {}),
    })
  }

  const dirty =
    effectiveName !== settings.general.system_name ||
    effectiveTimezone !== settings.time.recording_timezone ||
    effectiveNtpRaw !== settings.time.managed_camera_ntp_servers.join(", ") ||
    Object.keys(runtimeChanged).length > 0

  return (
    <div className="space-y-4">
      {/* The save action lives inside the tab rather than in the page header:
          the header is shared, and a 保存 button that does nothing on the
          notification tab would be a lie about what the click will do. */}
      <div className="flex justify-end">
        <Button
          size="sm"
          onClick={submit}
          disabled={!dirty || save.isPending || runtimeErrors.length > 0}
        >
          {save.isPending ? "保存中…" : "保存"}
        </Button>
      </div>

      {healthQuery.data ? (
        <Section title="服务状态">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(healthQuery.data.components).map(
              ([key, component]) => (
                <div
                  key={key}
                  className="flex items-start gap-2 rounded-lg border border-border px-3 py-2"
                >
                  <StatusDot tone={COMPONENT_TONE[component.status] ?? "unknown"} />
                  <div className="min-w-0">
                    <p className="text-xs font-medium">
                      {COMPONENT_LABEL[key] ?? key}
                    </p>
                    {component.message ? (
                      <p className="truncate text-[11px] text-muted-foreground">
                        {component.message}
                      </p>
                    ) : null}
                  </div>
                </div>
              ),
            )}
          </div>
        </Section>
      ) : null}

      <Section title="通用">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="sys-name" className="text-xs font-medium">
              系统名称
            </label>
            <Input
              id="sys-name"
              value={effectiveName}
              onChange={(event) => setSystemName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="sys-tz-alias" className="text-xs font-medium">
              显示时区（只读镜像）
            </label>
            <Input id="sys-tz-alias" value={settings.general.display_timezone} readOnly />
            <p className="text-[11px] text-muted-foreground">
              该字段由下方「录制时区」回填，修改它会被重定向。
            </p>
          </div>
        </div>
      </Section>

      <Section title="时间与 NTP">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="sys-recording-tz" className="text-xs font-medium">
              录制时区
            </label>
            <Input
              id="sys-recording-tz"
              value={effectiveTimezone}
              onChange={(event) => setRecordingTimezone(event.target.value)}
              placeholder="Asia/Shanghai"
            />
            <Callout tone="degraded" title="该设置当前不生效">
              录制计划求值用的是每机位的 <code>schedule_timezone</code>，不是这里的
              值。写入此处不改变任何录像的切分时间，录制时区需在「录制计划」中逐机位设置。
            </Callout>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="sys-ntp" className="text-xs font-medium">
              托管 NTP 服务器
            </label>
            <Input
              id="sys-ntp"
              value={effectiveNtpRaw}
              onChange={(event) => setNtpServers(event.target.value)}
              placeholder="ntp1.example.com, ntp2.example.com"
            />
            <p className="text-[11px] text-muted-foreground">
              当前模式：{settings.time.managed_camera_ntp_mode === "manual" ? "手动" : "DHCP"}。
              填入服务器会自动切到「手动」，清空则切回「DHCP」。
            </p>
            <Button
              variant="outline"
              size="sm"
              disabled={applyNtp.isPending}
              onClick={() => applyNtp.mutate(undefined)}
            >
              {applyNtp.isPending ? "下发中…" : "下发到所有托管设备"}
            </Button>
            {applyNtp.data && applyNtp.data.results.length > 0 ? (
              <ul className="space-y-0.5 text-[11px] text-muted-foreground">
                {applyNtp.data.results
                  .filter((device) => device.status === "FAILED")
                  .map((device) => (
                    <li key={device.device_id}>
                      {device.name}：{device.error_code ?? "下发失败"}
                    </li>
                  ))}
              </ul>
            ) : null}
          </div>
        </div>

        {clockQuery.data ? (
          <div className="mt-3 space-y-1">
            <p className="text-xs font-medium">
              设备时钟（{clockQuery.data.ok} 正常 / {clockQuery.data.degraded} 偏差 /{" "}
              {clockQuery.data.error} 异常）
            </p>
            <ul className="grid gap-1 sm:grid-cols-2">
              {clockQuery.data.results.slice(0, 12).map((device) => (
                <li
                  key={device.device_id}
                  className="flex items-center justify-between text-[11px]"
                >
                  <span className="truncate text-muted-foreground">
                    {device.name}
                  </span>
                  <span className="tabular-nums">
                    {device.offset_ms === null
                      ? "—"
                      : `${device.offset_ms} ms`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Section>

      <Section title="运行时调优">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {RUNTIME_FIELDS.map((spec) => {
            const value = runtime[spec.key]
            const error = runtimeErrorFor(spec.key)
            return (
              <div key={spec.key} className="space-y-1.5">
                <label
                  htmlFor={`rt-${spec.key}`}
                  className="text-xs font-medium"
                >
                  {spec.label}
                </label>
                <Input
                  id={`rt-${spec.key}`}
                  type="number"
                  min={spec.min}
                  max={spec.max}
                  step={spec.step}
                  value={Number.isFinite(value) ? value : ""}
                  onChange={(event) =>
                    setRuntimeOverrides((current) => ({
                      ...(current ?? {}),
                      [spec.key]: Number(event.target.value),
                    }))
                  }
                  aria-invalid={Boolean(error)}
                />
                <p className="text-[11px] text-muted-foreground">
                  {formatByUnit(value, spec.unit)} · {spec.hint}
                </p>
                {error ? (
                  <p className="text-xs text-status-offline">{error}</p>
                ) : null}
              </div>
            )
          })}
        </div>

        <Callout tone="degraded" title="这一组的单位是混的">
          秒、字节、kbps、路数并存，其中「转码启动超时」是唯一的浮点字段。
          每个字段下方都按自己的单位显示当前值，避免把
          {" "}{formatBytes(settings.runtime.playback_cache_max_bytes)}
          {" "}读成秒数。
        </Callout>
      </Section>
    </div>
  )
}
