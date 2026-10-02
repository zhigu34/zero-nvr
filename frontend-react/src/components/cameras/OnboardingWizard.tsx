import { useMemo, useState } from "react"
import {
  Check,
  Download,
  Film,
  Info,
  KeyRound,
  Play,
  Search,
  SearchX,
  TriangleAlert,
} from "lucide-react"

import {
  CAMERA_LOCATION_MAX,
  CAMERA_NAME_MAX,
  CAMERA_STORAGE_LABEL_MAX,
  DISCOVERY_MAX_SOURCE_ADDRESSES,
  IDENTITY_STATE_LABEL,
  ONVIF_TIMEOUT_BUDGET_MS,
  buildManualCameraInput,
  buildOnvifImportInput,
  buildOnvifProbeInput,
  describeProbeStream,
  describeProfile,
  emptyManualCameraForm,
  emptyOnvifForm,
  identityAction,
  identityBlockedReason,
  importPersistedAnyway,
  importableProfiles,
  validateManualCameraForm,
  validateOnvifForImport,
  validateOnvifForm,
  type CameraCreateInput,
  type CameraProbeResult,
  type DiscoveryCandidateView,
  type DiscoverySessionView,
  type ManualCameraForm,
  type ManualFormField,
  type OnvifForm,
  type OnvifFormField,
  type OnvifInspectionView,
  type OnvifProfileView,
  type OnvifImportResult,
} from "../../api/onboarding"
import {
  useCreateManualCamera,
  useImportOnvifDevice,
  useInspectOnvif,
  useRefreshOnvifCapabilities,
  useStartDiscovery,
  useTestManualCamera,
} from "../../lib/onboardingMutations"
import { Badge, Button, Input } from "../ui/primitives"
import {
  Callout,
  Checkbox,
  EmptyState,
  KeyValue,
  Mono,
  PrototypeNote,
  Tabs,
} from "../ui/display"

/**
 * 摄像机接入向导。
 *
 * Four ways in — WS-Discovery, ONVIF inspection, ONVIF import, manual RTSP —
 * and one shell, because three of them share the same credential handling and
 * the same create step. The shell exists mostly to keep five separate things
 * from being collapsed into one "add camera" button:
 *
 * 1. **Discovery is a multicast broadcast-domain probe, not a subnet scan.**
 *    `POST /cameras/discovery` waits 3 s for WS-Discovery replies
 *    (`core/config/settings.py:76`), so a camera on another subnet never
 *    appears and the empty state has to say so — otherwise "no results" reads
 *    as "no cameras there".
 * 2. **Inspection is read-only and 10 s; import is the write.** Import re-runs
 *    the inspection and then opens a real ZLM proxy per selected profile
 *    (`onvif_onboarding.py:1149-1176`), 12 s each. Four profiles is about a
 *    minute, so the pending state names the budget instead of spinning.
 * 3. **Identity is a four-state machine.** `new_device` imports,
 *    `same_device` offers *two* different things (read-only refresh, and
 *    re-import to reconfigure), `probable_match_requires_confirmation` needs an
 *    explicit confirmation, and `identity_conflict` has no forward path at all
 *    (`onvif_onboarding.py:462-481`) — so no button is rendered for it.
 *    `same_device` must not collapse to just the refresh: `CameraUpdate` has no
 *    credential fields and `POST /cameras/{id}/onvif/refresh` takes no body, so
 *    re-import (`_reconfigure_existing`, `onvif_onboarding.py:590`) is the *only*
 *    way an already-imported device's password can ever be changed.
 * 4. **`POST /cameras` does not probe.** It validates `invalid_rtsp_url` syntax
 *    only (`cameras/service.py:104,112`), so the manual path keeps test and
 *    create as two operator-driven steps, and the create button appears only
 *    when a successful test covers the exact body that would be created.
 *
 * Two form rules the component is responsible for, both easy to get backwards:
 *
 * - **`profile_tokens: null` means "every profile"**, `[]` means "none" and can
 *   reach 422 `onvif_no_usable_profiles` (`onvif_onboarding.py:229-230`). So
 *   `selectionTouched` flips the moment a checkbox is touched and never on
 *   render; until then the checkboxes read as "all" because that is the body
 *   that will be sent.
 * - **`confirm_existing_device_id` is the server's `matched_device_id`,
 *   verbatim.** It arrives here through `confirmationIdFor` and nowhere else;
 *   deriving one locally produces a second, different 409 for one mistake
 *   (`:490, :547`).
 *
 * Nothing in this file renders a stream URI, a password or a stored credential:
 * the server never returns one (`api/onboarding.ts` module docblock), and
 * inspection only reports `stream_uri_available: boolean`.
 */
export function OnboardingWizard() {
  const [mode, setMode] = useState<"onvif" | "manual">("onvif")

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">接入新设备</h3>
        <p className="mt-1 text-[11px] text-muted-foreground">
          两条路：让支持 ONVIF 的设备自己报地址，或手填 RTSP 地址。密码只写不读——录入之后服务端不会再返回它，这里也不会回显。
        </p>
      </div>

      <Tabs
        tabs={[
          { key: "onvif", label: "ONVIF 设备" },
          { key: "manual", label: "手动 RTSP" },
        ]}
        active={mode}
        onChange={(key) => setMode(key === "manual" ? "manual" : "onvif")}
      />

      {mode === "onvif" ? <OnvifWizard /> : <ManualWizard />}

      <PrototypeNote>
        这里没有批量导入：服务端没有批量接口，也没有试运行，导入本身就是唯一一次写入。批量只能是前端逐台串行调用，任何一步失败都不会回滚已经写入的设备。
      </PrototypeNote>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Failure surfacing                                                          */
/* -------------------------------------------------------------------------- */

type StepFailure = { code: string | null; message: string }

function toFailure(error: unknown): StepFailure {
  const code = (error as { code?: string } | null)?.code
  return {
    code: typeof code === "string" ? code : null,
    message: error instanceof Error ? error.message : String(error),
  }
}

/**
 * What to try next, per error code.
 *
 * Deliberately *not* a second translation of the code: the canonical wording
 * lives in `onboardingMutations.describeFailure` and already arrives in the
 * toast. This adds the two things a toast cannot — what to do about the step on
 * screen, and an honest statement of what the server refuses to tell us (one
 * ONVIF failure covers wrong password, wrong IP and firewall alike,
 * `onvif_adapter.py:471-479`).
 */
function stepAdvice(code: string | null): string {
  switch (code) {
    case "onvif_connection_failed":
      return "地址、端口、凭据、网络策略任一不对都会得到这个结果，服务端不会告诉你是哪一项。请逐项确认后重试。"
    case "onvif_timeout":
      return "服务端只等 10 秒。设备过载、链路被中间设备拖慢时会出现；确认设备在线再重试。"
    case "onvif_no_usable_profiles":
    case "invalid_onvif_profile_tokens":
    case "onvif_stream_uri_unavailable":
      return "重新检查这台设备，再按新的码流列表选择：取不到可用流地址的码流无法导入。"
    case "onvif_device_identity_confirmation_required":
      return "服务端要求先确认这是同一台设备。请重新检查设备，勾选确认后再导入。"
    case "onvif_device_identity_confirmation_invalid":
      return "确认用的设备 id 必须原样回传服务端给的 matched_device_id，不能在这里重新生成。请重新检查设备后再试。"
    case "onvif_device_topology_changed":
      return "设备码流结构在检查之后变了。重新检查后再导入。"
    case "onvif_discovery_failed":
      return "确认设备与本机在同一广播域，且组播没有被交换机或防火墙拦截。"
    case "onvif_discovery_source_address_invalid":
      return `源地址必须是本机可用的非组播、非回环 IPv4，最多 ${DISCOVERY_MAX_SOURCE_ADDRESSES} 个。`
    case "discovery_candidate_mismatch":
      return "填写的地址与所选的发现候选不一致。重新选择候选，或把地址改回候选里的那个。"
    case "device_credential_unavailable":
      return "密钥环里取不到这台设备的凭据，密钥可能已被轮换。请到系统设置里检查密钥环。"
    case "invalid_rtsp_url":
      return "地址必须是 rtsp:// 开头、带主机名的完整 URL；这里只检查写法，能不能播由连通性测试决定。"
    default:
      return code
        ? `后端返回 ${code}。请按上面的说明修正后重试。`
        : "请按上面的说明修正后重试。"
  }
}

function FailureNotice({
  title,
  failure,
}: {
  title: string
  failure: StepFailure
}) {
  return (
    <Callout tone="offline" title={`${title}（${failure.code ?? "未知错误"}）`}>
      <p>{failure.message}</p>
      <p className="mt-1">{stepAdvice(failure.code)}</p>
    </Callout>
  )
}

/** Label + hint + control + error, stacked: a wizard field has a hint under it. */
function FormField({
  id,
  label,
  hint,
  error,
  icon,
  children,
}: {
  id: string
  label: string
  hint?: string
  error?: string | null
  icon?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="flex items-center gap-1 text-xs font-medium">
        {icon && <span className="text-muted-foreground">{icon}</span>}
        {label}
      </label>
      {hint && (
        <p className="text-[11px] leading-relaxed text-muted-foreground">{hint}</p>
      )}
      {children}
      {error && <p className="text-[11px] text-status-offline">{error}</p>}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* ONVIF                                                                      */
/* -------------------------------------------------------------------------- */

const ONVIF_STEPS = [
  { key: "discover", label: "发现设备" },
  { key: "inspect", label: "连接与检查" },
  { key: "import", label: "导入建机位" },
] as const

function OnvifWizard() {
  const [form, setForm] = useState<OnvifForm>(() => emptyOnvifForm())
  const [sourceAddresses, setSourceAddresses] = useState("")
  const [sourceError, setSourceError] = useState<string | null>(null)
  const [session, setSession] = useState<DiscoverySessionView | null>(null)
  const [pickedCandidateId, setPickedCandidateId] = useState<string | null>(null)
  const [inspection, setInspection] = useState<OnvifInspectionView | null>(null)
  const [confirmChecked, setConfirmChecked] = useState(false)
  const [result, setResult] = useState<OnvifImportResult | null>(null)
  const [persisted, setPersisted] = useState<{ deviceId: string | null } | null>(null)

  const [discoveryFailure, setDiscoveryFailure] = useState<StepFailure | null>(null)
  const [inspectAttempted, setInspectAttempted] = useState(false)
  const [inspectFailure, setInspectFailure] = useState<StepFailure | null>(null)
  const [importAttempted, setImportAttempted] = useState(false)
  const [importFailure, setImportFailure] = useState<StepFailure | null>(null)

  const discovery = useStartDiscovery()
  const inspect = useInspectOnvif()
  const importDevice = useImportOnvifDevice()
  const identity = inspection?.identity ?? null
  // The endpoint is device-scoped, so the refresh has nothing to call without
  // a matched id. Passing "" would build a request to `/cameras//onvif/refresh`.
  const refresh = useRefreshOnvifCapabilities(identity?.matched_device_id ?? "")

  const importable = importableProfiles(inspection)
  const excluded = (inspection?.profiles ?? []).filter((p) => !p.stream_uri_available)

  // Form validity and request-body validity are two different questions. The
  // profile rule is the second kind — an untouched empty selection is how the
  // body says "every profile" — so gating the *inspection* step on it would
  // block a step it has nothing to do with.
  const formErrors = validateOnvifForm(form)
  const importErrors = validateOnvifForImport(form)
  const errorFor = (field: OnvifFormField) =>
    formErrors.find((e) => e.field === field)?.message ?? null
  const importErrorFor = (field: OnvifFormField) =>
    importErrors.find((e) => e.field === field)?.message ?? null

  // A connection edit invalidates the last inspection, for the same reason
  // picking a different candidate does: the profile list and the identity
  // verdict describe the host that was checked, and importing them against a
  // host nobody checked is how a camera gets created for the wrong body.
  const connectionAttempted = inspectAttempted || importAttempted

  const step = inspection ? 3 : session ? 2 : 1

  function invalidateInspection() {
    setInspection(null)
    setResult(null)
    setPersisted(null)
    setConfirmChecked(false)
    setInspectFailure(null)
    setImportFailure(null)
    setImportAttempted(false)
  }

  function editConnection(patch: Partial<OnvifForm>) {
    setForm((current) => ({ ...current, ...patch }))
    invalidateInspection()
  }

  function pickCandidate(candidate: DiscoveryCandidateView) {
    setPickedCandidateId(candidate.id)
    setForm((current) => ({
      ...current,
      // A candidate without a host or port leaves the typed value alone rather
      // than blanking it: the candidate row simply carries no address to fill.
      host: candidate.host ?? current.host,
      port: candidate.port ?? current.port,
      discoveryCandidateId: candidate.id,
    }))
    invalidateInspection()
    setInspectAttempted(false)
  }

  function runDiscovery() {
    // `disabled` is a courtesy, not the lock: a 3 s POST that is re-entered
    // while pending is a second multicast round and a second row in the audit
    // log, so the guard is in the handler too.
    if (discovery.isPending) return
    const addresses = sourceAddresses
      .split(/[\s,，]+/)
      .map((value) => value.trim())
      .filter(Boolean)
    if (addresses.length > DISCOVERY_MAX_SOURCE_ADDRESSES) {
      setSourceError(
        `最多 ${DISCOVERY_MAX_SOURCE_ADDRESSES} 个源地址，当前填了 ${addresses.length} 个。`,
      )
      return
    }
    setSourceError(null)
    setDiscoveryFailure(null)
    discovery.mutate(addresses, {
      onSuccess: (data) => setSession(data),
      onError: (error) => setDiscoveryFailure(toFailure(error)),
    })
  }

  function runInspect() {
    if (inspect.isPending) return
    setInspectAttempted(true)
    // Inspection carries no profile tokens, so an emptied selection is not an
    // inspection failure — it only matters to the import body.
    if (formErrors.length > 0) return
    setInspectFailure(null)
    setResult(null)
    setPersisted(null)
    setConfirmChecked(false)
    inspect.mutate(buildOnvifProbeInput(form), {
      onSuccess: (data) => setInspection(data),
      onError: (error) => setInspectFailure(toFailure(error)),
    })
  }

  function runImport() {
    if (importDevice.isPending) return
    setImportAttempted(true)
    if (importErrors.length > 0) return
    setImportFailure(null)
    setResult(null)
    setPersisted(null)
    importDevice.mutate(buildOnvifImportInput(form, identity), {
      // The mutation is typed `unknown`; the endpoint always answers with this
      // shape, and the result panel is the only thing that reads it.
      onSuccess: (data) => setResult((data ?? null) as OnvifImportResult | null),
      onError: (error) => {
        setImportFailure(toFailure(error))
        const anyway = importPersistedAnyway(error)
        if (anyway) setPersisted({ deviceId: anyway.deviceId })
      },
    })
  }

  function toggleProfile(token: string, on: boolean) {
    setForm((current) => {
      // Untouched means "all", so the first click is computed against every
      // importable profile rather than against an empty list.
      const effective = current.selectionTouched
        ? current.selectedProfileTokens
        : importable.map((p) => p.token)
      const next = on
        ? [...new Set([...effective, token])]
        : effective.filter((t) => t !== token)
      return { ...current, selectedProfileTokens: next, selectionTouched: true }
    })
  }

  return (
    <div className="space-y-4">
      <ol
        role="list"
        aria-label="ONVIF 接入步骤"
        className="flex flex-wrap items-center gap-1.5"
      >
        {ONVIF_STEPS.map((item, index) => {
          const number = index + 1
          const current = step === number
          return (
            <li
              key={item.key}
              aria-current={current ? "step" : undefined}
              className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs ${
                current
                  ? "border-primary bg-primary/10 font-medium"
                  : "border-border text-muted-foreground"
              }`}
            >
              <span className="tabular-nums">{number}</span>
              <span>{item.label}</span>
              {number < 3 && <span aria-hidden>›</span>}
            </li>
          )
        })}
      </ol>

      <DiscoverySection
        session={session}
        pickedCandidateId={pickedCandidateId}
        onPick={pickCandidate}
        onRun={runDiscovery}
        busy={discovery.isPending}
        failure={discoveryFailure}
        sourceAddresses={sourceAddresses}
        onSourceAddresses={(value) => {
          setSourceAddresses(value)
          setSourceError(null)
        }}
        sourceError={sourceError}
      />

      <section className="space-y-3">
        <h4 className="text-xs font-semibold">2 · 连接与检查</h4>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          这一步只读：连一次设备、读一次设备信息与码流列表，不写入任何东西。跳过发现直接填地址也可以，服务端最多等 10 秒。
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <FormField
            id="onvif-host"
            label="设备地址"
            hint="只填主机名或 IP，不要带协议、路径、端口或账号密码。"
            error={connectionAttempted ? errorFor("host") : null}
          >
            <Input
              id="onvif-host"
              value={form.host}
              aria-invalid={Boolean(connectionAttempted && errorFor("host"))}
              onChange={(event) => editConnection({ host: event.target.value })}
            />
          </FormField>

          <FormField
            id="onvif-port"
            label="ONVIF 端口"
            hint="设备 Web 管理端口，通常是 80、8000 或 2020。"
            error={connectionAttempted ? errorFor("port") : null}
          >
            <Input
              id="onvif-port"
              type="number"
              value={form.port}
              onChange={(event) =>
                editConnection({ port: Number(event.target.value) })
              }
            />
          </FormField>

          <FormField id="onvif-username" label="用户名" hint="可以留空：无认证的设备也能检查。">
            <Input
              id="onvif-username"
              value={form.username}
              onChange={(event) => editConnection({ username: event.target.value })}
            />
          </FormField>

          <FormField
            id="onvif-password"
            label="设备密码"
            icon={<KeyRound className="size-3" />}
            hint="只写不读：保存后服务端不会再返回它，这里也不会回显。"
            error={connectionAttempted ? errorFor("password") : null}
          >
            <Input
              id="onvif-password"
              type="password"
              value={form.password}
              onChange={(event) => editConnection({ password: event.target.value })}
            />
          </FormField>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium">机位信息</p>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            这三项由导入那一步一起写入，设备检查不会用到它们，所以改它们不会让上面的检查结果作废。
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <FormField
              id="onvif-name"
              label="机位名称"
              hint={`留空＝由服务端按设备信息命名，最长 ${CAMERA_NAME_MAX} 个字符。`}
              error={connectionAttempted ? errorFor("name") : null}
            >
              <Input
                id="onvif-name"
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </FormField>
            <FormField
              id="onvif-location"
              label="位置"
              hint={`最长 ${CAMERA_LOCATION_MAX} 个字符。`}
              error={connectionAttempted ? errorFor("location") : null}
            >
              <Input
                id="onvif-location"
                value={form.location}
                onChange={(event) =>
                  setForm({ ...form, location: event.target.value })
                }
              />
            </FormField>
            <FormField
              id="onvif-storage"
              label="存储标签"
              hint={`最长 ${CAMERA_STORAGE_LABEL_MAX} 个字符。`}
              error={connectionAttempted ? errorFor("storageLabel") : null}
            >
              <Input
                id="onvif-storage"
                value={form.storageLabel}
                onChange={(event) =>
                  setForm({ ...form, storageLabel: event.target.value })
                }
              />
            </FormField>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            // Disabled only while in flight. A blocked submit reveals *why*
            // instead of being a dead button, which is the only thing that
            // tells the operator which field to fix.
            disabled={inspect.isPending}
            onClick={runInspect}
          >
            <Search />
            {inspect.isPending ? "检查中…" : "检查设备"}
          </Button>
          {inspect.isPending && (
            <span className="text-[11px] text-muted-foreground">
              正在连接设备并读取码流列表，服务端最多等 10 秒。
            </span>
          )}
        </div>

        {inspectFailure && <FailureNotice title="设备检查失败" failure={inspectFailure} />}
      </section>

      {inspection && (
        <section className="space-y-3">
          <h4 className="text-xs font-semibold">设备信息与码流</h4>

          <div className="rounded-lg border border-border px-3 py-1">
            <KeyValue label="厂商 / 型号">
              {[inspection.device.manufacturer, inspection.device.model]
                .filter(Boolean)
                .join(" ") || "设备未提供"}
            </KeyValue>
            <KeyValue label="固件 / 序列号">
              {[inspection.device.firmware_version, inspection.device.serial_number]
                .filter(Boolean)
                .join(" · ") || "设备未提供"}
            </KeyValue>
            <KeyValue label="身份判定">
              {IDENTITY_STATE_LABEL[inspection.identity.state]}
            </KeyValue>
            <div className="flex items-start justify-between gap-4 border-t border-border py-2">
              <span className="shrink-0 text-xs text-muted-foreground">设备能力</span>
              <span className="flex flex-wrap justify-end gap-1">
                {inspection.capabilities.length > 0 ? (
                  inspection.capabilities.map((capability) => (
                    <Badge key={capability} variant="muted">
                      {capability}
                    </Badge>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground">未上报任何能力</span>
                )}
              </span>
            </div>
          </div>

          <ProfileSection
            form={form}
            importable={importable}
            excluded={excluded}
            onToggle={toggleProfile}
            onSelectAll={() =>
              setForm((current) => ({
                ...current,
                selectedProfileTokens: [],
                selectionTouched: false,
              }))
            }
            error={importAttempted ? importErrorFor("profiles") : null}
          />

          <ImportSection
            identity={identity}
            form={form}
            canImport={importable.length > 0}
            confirmChecked={confirmChecked}
            onConfirmChecked={(on) => {
              setConfirmChecked(on)
              if (!on) setImportAttempted(false)
            }}
            onImport={runImport}
            onRefresh={() => {
              if (refresh.isPending) return
              setImportFailure(null)
              refresh.mutate(undefined, {
                onError: (error) => setImportFailure(toFailure(error)),
              })
            }}
            onReinspect={runInspect}
            importing={importDevice.isPending}
            refreshing={refresh.isPending}
            attempted={importAttempted}
            failure={importFailure}
            persisted={persisted}
            result={result}
          />
        </section>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Step 1 — discovery                                                         */
/* -------------------------------------------------------------------------- */

function candidateName(candidate: DiscoveryCandidateView): string {
  const name = candidate.display_info?.name
  if (typeof name === "string" && name.trim() !== "") return name.trim()
  return candidate.host ?? "未知地址"
}

function DiscoverySection({
  session,
  pickedCandidateId,
  onPick,
  onRun,
  busy,
  failure,
  sourceAddresses,
  onSourceAddresses,
  sourceError,
}: {
  session: DiscoverySessionView | null
  pickedCandidateId: string | null
  onPick: (candidate: DiscoveryCandidateView) => void
  onRun: () => void
  busy: boolean
  failure: StepFailure | null
  sourceAddresses: string
  onSourceAddresses: (value: string) => void
  sourceError: string | null
}) {
  const candidates = session?.candidates ?? []

  return (
    <section className="space-y-3">
      <h4 className="text-xs font-semibold">1 · 发现设备（可选）</h4>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        发现走的是 WS-Discovery 组播广播，服务端只等 3 秒。它<b>不是</b>
        扫网段：只有与本机处于同一广播域的设备才会出现，跨网段的摄像机永远不会被发现。也可以跳过这一步，直接在上面填地址。
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <Button size="sm" disabled={busy} onClick={onRun}>
          <Search />
          {busy ? "发现中…" : "开始发现"}
        </Button>
        {busy && (
          <span className="text-[11px] text-muted-foreground">
            正在广播并等待设备回应，服务端最多等 3 秒。
          </span>
        )}
      </div>

      <FormField
        id="onvif-source-addresses"
        label="本机源地址（可选）"
        hint={`多网卡主机上可以指定从哪个地址发起，最多 ${DISCOVERY_MAX_SOURCE_ADDRESSES} 个，逗号分隔。留空＝用默认网卡。`}
        error={sourceError}
      >
        <Input
          id="onvif-source-addresses"
          className="w-72"
          placeholder="192.168.1.10"
          value={sourceAddresses}
          onChange={(event) => onSourceAddresses(event.target.value)}
        />
      </FormField>

      {failure && <FailureNotice title="设备发现失败" failure={failure} />}

      {session && candidates.length === 0 && (
        <EmptyState
          icon={<SearchX />}
          title="没有发现到任何设备"
          description="发现是组播广播，只能看到与本机同一广播域的设备；不在同一网段的摄像机不会出现在这里。请确认设备已上电、与本机同网段，或直接在上面手动填写地址。"
        />
      )}

      {candidates.length > 0 && (
        <ul role="list" aria-label="发现候选列表" className="space-y-1.5">
          {candidates.map((candidate) => (
            <li key={candidate.id}>
              <button
                type="button"
                aria-pressed={candidate.id === pickedCandidateId}
                aria-label={`选择设备 ${candidateName(candidate)} ${
                  candidate.host ?? "无地址"
                }`}
                onClick={() => onPick(candidate)}
                className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs ${
                  candidate.id === pickedCandidateId
                    ? "border-primary bg-primary/10"
                    : "border-border hover:bg-accent"
                }`}
              >
                <Search className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="font-medium">{candidateName(candidate)}</span>
                <Mono>
                  {candidate.host ?? "无地址"}
                  {candidate.port ? `:${candidate.port}` : ""}
                </Mono>
                <span className="ml-auto text-muted-foreground">
                  {candidate.id === pickedCandidateId ? "已选用" : "选用"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Profiles                                                                   */
/* -------------------------------------------------------------------------- */

function ProfileSection({
  form,
  importable,
  excluded,
  onToggle,
  onSelectAll,
  error,
}: {
  form: OnvifForm
  importable: OnvifProfileView[]
  excluded: OnvifProfileView[]
  onToggle: (token: string, on: boolean) => void
  onSelectAll: () => void
  error: string | null
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium">
          可导入的码流
          <span className="ml-2 font-normal text-muted-foreground">
            {form.selectionTouched
              ? `已选 ${form.selectedProfileTokens.length} / ${importable.length} 个`
              : `未改动选择：将导入全部 ${importable.length} 个`}
          </span>
        </p>
        {form.selectionTouched && (
          <Button variant="ghost" size="sm" onClick={onSelectAll}>
            恢复默认：导入全部
          </Button>
        )}
      </div>

      <div
        role="group"
        aria-label="可导入的码流"
        className="max-h-52 space-y-1 overflow-y-auto rounded-lg border border-border p-2"
      >
        {importable.length === 0 ? (
          <p className="px-1 text-[11px] text-muted-foreground">
            这台设备没有可导入的码流：每个 profile 都取不到可用的流地址。
          </p>
        ) : (
          importable.map((profile) => (
            <span key={profile.token} className="flex items-center gap-2 text-xs">
              <Checkbox
                id={`onvif-profile-${profile.token}`}
                // Untouched reads as "all ticked" because that is literally the
                // body that will be sent (`profile_tokens: null`).
                checked={
                  !form.selectionTouched ||
                  form.selectedProfileTokens.includes(profile.token)
                }
                onChange={(event) => onToggle(profile.token, event.target.checked)}
              />
              <label htmlFor={`onvif-profile-${profile.token}`}>
                {profile.name} <Mono>{profile.token}</Mono>
              </label>
              <span className="text-muted-foreground">
                {describeProfile(profile)}
              </span>
            </span>
          ))
        )}
      </div>

      {excluded.length > 0 && (
        <div
          role="group"
          aria-label="无法导入的码流"
          className="space-y-1 rounded-lg border border-dashed border-border p-2"
        >
          <p className="text-[11px] text-muted-foreground">
            {`有 ${excluded.length} 个码流取不到可用的流地址，无论怎么选都不会被导入：`}
          </p>
          {excluded.map((profile) => (
            <p key={profile.token} className="text-[11px] text-muted-foreground">
              <Film className="mr-1 inline size-3 align-[-2px]" />
              {profile.name} <Mono>{profile.token}</Mono>
              {" · "}
              {describeProfile(profile)}
              {" · 无可用流地址"}
            </p>
          ))}
        </div>
      )}

      {error && <p className="text-[11px] text-status-offline">{error}</p>}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Step 3 — the write, and what identity allows                                */
/* -------------------------------------------------------------------------- */

function ImportSection({
  identity,
  form,
  canImport,
  confirmChecked,
  onConfirmChecked,
  onImport,
  onRefresh,
  onReinspect,
  importing,
  refreshing,
  attempted,
  failure,
  persisted,
  result,
}: {
  identity: NonNullable<OnvifInspectionView["identity"]> | null
  form: OnvifForm
  /** False when every profile was excluded: an import could only 422. */
  canImport: boolean
  confirmChecked: boolean
  onConfirmChecked: (on: boolean) => void
  onImport: () => void
  onRefresh: () => void
  onReinspect: () => void
  importing: boolean
  refreshing: boolean
  attempted: boolean
  failure: StepFailure | null
  persisted: { deviceId: string | null } | null
  result: OnvifImportResult | null
}) {
  if (!identity) return null

  const action = identityAction(identity)
  const blocked = identityBlockedReason(identity)

  return (
    <div className="space-y-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold">3 · 导入并建立机位</h4>
        <Badge variant={action === "blocked" ? "danger" : "warning"}>
          {IDENTITY_STATE_LABEL[identity.state]}
        </Badge>
        {identity.matched_device_name && (
          <Mono>匹配到：{identity.matched_device_name}</Mono>
        )}
      </div>

      <ImportBudgetNote form={form} />

      {!canImport && (
        <Callout tone="offline" title="没有可导入的码流">
          这台设备的每个 profile 都取不到可用的流地址，导入必然失败，因此这里不提供导入按钮。确认地址、端口与凭据无误后再检查一次。
        </Callout>
      )}

      {result && <ImportedCameras result={result} />}

      {attempted && failure && <FailureNotice title="导入失败" failure={failure} />}

      {persisted && (
        <Callout tone="degraded" title="设备与机位已经落库，请勿重复导入">
          {`这台设备与它的机位已经建立（${persisted.deviceId ?? "设备 id 未知"}），只是运行队列不可用。再次导入同一份表单会造出第二台同名设备——请先到机位列表确认已经存在的记录。`}
          <div className="mt-2 flex items-center gap-2">
            {/* Read-only: re-inspecting can never write a second device, and it
                is the only way to get back to a state that names what exists. */}
            <Button variant="outline" size="sm" disabled={importing} onClick={onReinspect}>
              {importing ? "检查中…" : "重新检查该设备"}
            </Button>
          </div>
        </Callout>
      )}

      {!persisted && blocked && (
        <Callout tone="offline" title="无法通过导入新增这台设备">
          {blocked}
          {identity.reason ? `（服务端原因：${identity.reason}）` : ""}
        </Callout>
      )}

      {!persisted && canImport && action === "import" && (
        <>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            这是一次写入：会建立设备、机位、码流、凭据与播放端点。名称、位置与存储标签都会一起写入。
          </p>
          <Button size="sm" disabled={importing} onClick={onImport}>
            <Download />
            {importing ? "导入中…" : "导入设备并创建机位"}
          </Button>
        </>
      )}

      {!persisted && action === "refresh" && (
        <>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            这台设备已经在本系统里，不会新建第二台记录。下面两件事不同，按需要选：
          </p>
          {identity.matched_device_id ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={refreshing || importing}
                onClick={onRefresh}
              >
                {refreshing ? "重新读取中…" : "重新读取设备能力"}
              </Button>
              <span className="text-[11px] text-muted-foreground">
                只读。不碰任何已存的配置。
              </span>
            </div>
          ) : (
            <Callout tone="offline" title="无法重新读取">
              服务端没有给出设备 id，这里没有可以调用的对象。请到机位列表中确认这条记录。
            </Callout>
          )}
          {/* The only path that can rotate an ONVIF device's credentials.
              `POST /cameras/{id}/onvif/refresh` takes no body, and `CameraUpdate`
              has no credential fields, so a changed password can only reach the
              secret store by re-running import — which the server routes into
              `_reconfigure_existing` (`onvif_onboarding.py:590`). Without this
              button the wizard can read an existing device but never fix its
              password. */}
          {canImport && (
            <div className="rounded-lg border border-border p-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={importing || refreshing}
                  onClick={onImport}
                >
                  <Download />
                  {importing ? "重新导入中…" : "重新导入以更新凭据"}
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  改了上面表格里的密码、地址或码流勾选，就用这个。
                </span>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                仍然走同一条导入路径：重新连接设备、逐个重探所选码流，然后更新这一台已有设备——不会新建机位，也不会动其它机位。密码确实变了才会换掉旧密钥；名称、位置与存储标签按当前表单一起写入。
              </p>
            </div>
          )}
        </>
      )}

      {!persisted && canImport && action === "confirm" && (
        <>
          <Callout tone="degraded" title="疑似与已录入的设备是同一台">
            {`服务端判断这台设备与已录入的「${identity.matched_device_name ?? "同名设备"}」高度相似，但还不足以直接合并。继续导入会把两台记录视为同一台设备。`}
          </Callout>
          <div
            role="group"
            aria-label="身份确认"
            className="flex items-start gap-2 rounded-lg border border-border p-2 text-xs"
          >
            <Checkbox
              id="onvif-confirm-identity"
              checked={confirmChecked}
              onChange={(event) => onConfirmChecked(event.target.checked)}
            />
            <label htmlFor="onvif-confirm-identity">
              {`我确认这台设备就是已录入的「${identity.matched_device_name ?? "同名设备"}」，继续导入`}
            </label>
          </div>
          <Button
            size="sm"
            // The id echoed back is the server's own `matched_device_id`, not
            // anything derived here: any other value returns a *different* 409
            // for the same mistake (`onvif_onboarding.py:490, :547`).
            disabled={importing || !confirmChecked}
            onClick={onImport}
          >
            <Check />
            {importing ? "导入中…" : "确认是同一台并导入"}
          </Button>
        </>
      )}

      {importing && (
        <p className="text-[11px] text-muted-foreground">
          正在重新检查设备并逐个探测所选码流，请勿重复点击，也不要关掉页面。
        </p>
      )}
    </div>
  )
}

/**
 * What the write is about to cost in time.
 *
 * Import is inspection (10 s) plus one real ZLM probe per selected profile
 * (12 s each, `core/config/settings.py:64`), so the number is the sum rather
 * than a guess — and nothing here sets a client timeout below it.
 */
function ImportBudgetNote({ form }: { form: OnvifForm }) {
  const seconds = Math.round(
    (ONVIF_TIMEOUT_BUDGET_MS.inspection +
      Math.max(1, form.selectedProfileTokens.length) *
        ONVIF_TIMEOUT_BUDGET_MS.probePerStream) /
      1000,
  )
  return (
    <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
      <Info className="mt-0.5 size-3 shrink-0" />
      {`导入会重新检查设备（最长 ${ONVIF_TIMEOUT_BUDGET_MS.inspection / 1000} 秒），再对每个选中的码流各探测一次（每个最长 ${ONVIF_TIMEOUT_BUDGET_MS.probePerStream / 1000} 秒）。按现在的选择，最长约 ${seconds} 秒。`}
    </p>
  )
}

/**
 * The cameras the import actually made.
 *
 * Cameras are grouped by `video_source_token`
 * (`onvif_onboarding.py:1149-1176`), so a four-profile device can produce six
 * cameras and a two-profile device can produce one. The list is therefore
 * exactly the response's `cameras`, and no number here is derived from the
 * profile count.
 */
function ImportedCameras({ result }: { result: OnvifImportResult }) {
  const cameras = Array.isArray(result.cameras) ? result.cameras : []
  // `reconfigured: true` means the server matched an existing device and updated
  // it in place (`_reconfigure_existing`) — nothing was created. Saying "created
  // N cameras" there would be a lie the operator then has to disprove by hand.
  const reconfigured = result.reconfigured === true
  return (
    <div
      role="group"
      aria-label={reconfigured ? "本次重新导入更新的机位" : "本次导入创建的机位"}
      className="rounded-lg border border-status-online/30 bg-status-online/5 p-2"
    >
      <p className="text-[11px] font-medium text-status-online">
        {reconfigured
          ? `重新导入完成：已更新已有的 ${cameras.length} 个机位，没有新建设备。`
          : `导入完成：实际创建 ${cameras.length} 个机位。`}
      </p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        {reconfigured
          ? "这轮用的是当前表格里的地址、凭据与码流勾选，密码变了才换密钥。机位按 video_source_token 分组。"
          : "机位按 video_source_token 分组，数量由设备决定，与所选码流数不一定相同。"}
      </p>
      <ul className="mt-1.5 space-y-0.5">
        {cameras.map((camera, index) => (
          <li key={cameraId(camera) ?? index} className="text-[11px]">
            · {cameraName(camera, index)}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The import result is typed `unknown` on the wire contract, so the two accessors
 * narrow instead of asserting a whole camera shape the endpoint never promised.
 */
function cameraName(camera: unknown, index: number): string {
  const name = (camera as { name?: unknown } | null)?.name
  return typeof name === "string" && name !== "" ? name : `机位 ${index + 1}`
}

function cameraId(camera: unknown): string | null {
  const id = (camera as { id?: unknown } | null)?.id
  return typeof id === "string" ? id : null
}

/* -------------------------------------------------------------------------- */
/* Manual RTSP                                                                */
/* -------------------------------------------------------------------------- */

/**
 * G-38, in the only place it can still be said: `CameraUpdate` has no stream
 * or credential field (`cameras/schemas.py:36`), so a manual camera's RTSP
 * password can only be changed by deleting and recreating the camera — and the
 * delete takes its recording policy, protections and alert scope with it.
 */
const MANUAL_CREDENTIAL_WARNING =
  "RTSP 地址与密码之后无法在此修改：更新机位的接口没有码流与凭据字段。要换密码只能删除并重建这个机位，而删除会一并丢掉它上面的录制计划、录像保护与告警范围。"

function ManualWizard() {
  const [form, setForm] = useState<ManualCameraForm>(() => emptyManualCameraForm())
  const [probe, setProbe] = useState<CameraProbeResult | null>(null)
  // The exact body the successful test covered. Create is offered only while
  // this still equals the form's body, so nobody creates something nobody tested.
  const [testedBody, setTestedBody] = useState<CameraCreateInput | null>(null)
  const [testAttempted, setTestAttempted] = useState(false)
  const [testFailure, setTestFailure] = useState<StepFailure | null>(null)
  const [createFailure, setCreateFailure] = useState<StepFailure | null>(null)
  const [created, setCreated] = useState(false)

  const test = useTestManualCamera()
  const create = useCreateManualCamera()

  const body = useMemo(() => buildManualCameraInput(form), [form])
  const errors = validateManualCameraForm(form)
  const errorFor = (field: ManualFormField) =>
    errors.find((e) => e.field === field)?.message ?? null

  const stale = testedBody !== null && JSON.stringify(testedBody) !== JSON.stringify(body)
  const createOffered = probe !== null && !stale

  function runTest() {
    if (test.isPending) return
    setTestAttempted(true)
    if (errors.length > 0) return
    setTestFailure(null)
    setCreated(false)
    test.mutate(body, {
      onSuccess: (data) => {
        setProbe(data as CameraProbeResult)
        setTestedBody(body)
      },
      onError: (error) => setTestFailure(toFailure(error)),
    })
  }

  function runCreate() {
    if (!testedBody || create.isPending) return
    setCreateFailure(null)
    create.mutate(testedBody, {
      onSuccess: () => setCreated(true),
      onError: (error) => setCreateFailure(toFailure(error)),
    })
  }

  return (
    <div className="space-y-4">
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        设备不支持 ONVIF，或已经在别处配置好了 RTSP 地址时用这条路。这里的两个步骤是分开的：创建机位<b>不会</b>探测地址，服务端只检查写法（<Mono>cameras/service.py:104,112</Mono>
        ），所以没测过就创建，正是造出一台死机位的最短路径。
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          id="manual-name"
          label="机位名称"
          hint={`最长 ${CAMERA_NAME_MAX} 个字符。`}
          error={testAttempted ? errorFor("name") : null}
        >
          <Input
            id="manual-name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </FormField>

        <FormField
          id="manual-location"
          label="位置"
          hint={`可选，最长 ${CAMERA_LOCATION_MAX} 个字符。`}
        >
          <Input
            id="manual-location"
            value={form.location}
            onChange={(event) => setForm({ ...form, location: event.target.value })}
          />
        </FormField>

        <FormField
          id="manual-storage"
          label="存储标签"
          hint={`可选，最长 ${CAMERA_STORAGE_LABEL_MAX} 个字符。`}
        >
          <Input
            id="manual-storage"
            value={form.storageLabel}
            onChange={(event) =>
              setForm({ ...form, storageLabel: event.target.value })
            }
          />
        </FormField>

        <FormField
          id="manual-primary-name"
          label="主码流名称"
          error={testAttempted ? errorFor("primaryName") : null}
        >
          <Input
            id="manual-primary-name"
            value={form.primaryName}
            onChange={(event) =>
              setForm({ ...form, primaryName: event.target.value })
            }
          />
        </FormField>
      </div>

      <FormField
        id="manual-primary-url"
        label="主码流地址"
        icon={<KeyRound className="size-3" />}
        hint="rtsp:// 开头、带主机名的完整 URL。地址里可以带账号密码，它会被加密存进密钥环，之后不再返回。"
        error={testAttempted ? errorFor("primaryUrl") : null}
      >
        <Input
          id="manual-primary-url"
          value={form.primaryUrl}
          onChange={(event) =>
            setForm({ ...form, primaryUrl: event.target.value })
          }
        />
      </FormField>

      <div
        role="group"
        aria-label="子码流"
        className="space-y-3 rounded-lg border border-border p-2"
      >
        <span className="flex items-center gap-2 text-xs">
          <Checkbox
            id="manual-has-secondary"
            checked={form.hasSecondary}
            onChange={(event) => {
              setForm({ ...form, hasSecondary: event.target.checked })
              setTestedBody(null)
              setProbe(null)
            }}
          />
          <label htmlFor="manual-has-secondary">
            添加子码流（无法从地址推断，必须显式勾选）
          </label>
        </span>

        {form.hasSecondary && (
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField
              id="manual-secondary-name"
              label="子码流名称"
              error={testAttempted ? errorFor("secondaryName") : null}
            >
              <Input
                id="manual-secondary-name"
                value={form.secondaryName}
                onChange={(event) =>
                  setForm({ ...form, secondaryName: event.target.value })
                }
              />
            </FormField>
            <FormField
              id="manual-secondary-url"
              label="子码流地址"
              error={testAttempted ? errorFor("secondaryUrl") : null}
            >
              <Input
                id="manual-secondary-url"
                value={form.secondaryUrl}
                onChange={(event) =>
                  setForm({ ...form, secondaryUrl: event.target.value })
                }
              />
            </FormField>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Button size="sm" disabled={test.isPending} onClick={runTest}>
          <Play />
          {test.isPending ? "测试中…" : "测试连通性"}
        </Button>
        {test.isPending && (
          <p className="text-[11px] text-muted-foreground">
            正在真实拉流，服务端每个码流最多等 12 秒。
          </p>
        )}
        {testFailure && <FailureNotice title="连通性测试失败" failure={testFailure} />}
      </div>

      {probe && (
        <ul
          role="list"
          aria-label="连通性测试结果"
          className="space-y-1 rounded-lg border border-status-online/30 bg-status-online/5 p-2"
        >
          {probe.streams.map((stream) => (
            <li key={stream.role} className="text-[11px]">
              {describeProbeStream(stream)}
            </li>
          ))}
        </ul>
      )}

      <Callout tone="degraded" title="创建之后，这些都改不了">
        {MANUAL_CREDENTIAL_WARNING}
      </Callout>

      {!createOffered && (
        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
          <TriangleAlert className="mt-0.5 size-3 shrink-0" />
          {stale
            ? "表单在测试之后被改过。请重新测试连通性——现在创建的不会是被测过的那一个。"
            : "还没有一次成功的连通性测试，因此这里不提供「创建机位」。"}
        </p>
      )}

      {createFailure && <FailureNotice title="创建机位失败" failure={createFailure} />}

      {createOffered && (
        <div className="space-y-2">
          <Button size="sm" disabled={create.isPending} onClick={runCreate}>
            <Download />
            {create.isPending ? "创建中…" : "创建机位"}
          </Button>
          {created && (
            <Callout tone="online" title="机位已创建">
              {MANUAL_CREDENTIAL_WARNING}
            </Callout>
          )}
        </div>
      )}
    </div>
  )
}
