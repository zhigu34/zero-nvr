import { useState } from "react"
import {
  Check,
  KeyRound,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  TriangleAlert,
  Wifi,
} from "lucide-react"

import {
  FRIGATE_MAX_LOOKBACK,
  FRIGATE_MIN_LOOKBACK,
  FRIGATE_MODE_LABEL,
  buildFrigatePut,
  frigateFormFromView,
  isNotConfigured,
  validateFrigateForm,
  type FrigateCameraMapping,
  type FrigateCredentialsInput,
  type FrigateForm,
  type FrigateFormField,
  type FrigateFormError,
  type FrigateMode,
  type SecretAction,
} from "../../api/frigate"
import type { CameraSummary } from "../../api/cameras"
import { useCameras, useFrigateProvider } from "../../lib/queries"
import {
  formatLookback,
  useQueueFrigateBackfill,
  useSaveFrigateProvider,
  useTestFrigateProvider,
} from "../../lib/frigateMutations"
import { useConfirm } from "../ui/Confirm"
import { Badge, Button, Input, Select, Switch } from "../ui/primitives"
import { Callout, Field, Mono, PrototypeNote, Section, Segmented, StatusDot } from "../ui/display"

/**
 * Frigate 集成。
 *
 * Four contract facts shape this panel, and each one is a way a naive editor
 * silently does the wrong thing rather than failing:
 *
 * 1. **"Not configured" is a 404, and it is the normal first-run state.**
 *    `GET /system/integrations/frigate` raises `frigate_not_configured` when no
 *    row exists (`api.py:309-325`), *before* the response schema's
 *    `configured: bool = True` (`schemas.py:51`) can ever say False. So the
 *    branch is `isNotConfigured(error)` → a first-run form; anything else →
 *    a failure surface. An operator who has never touched Frigate must never
 *    be shown 读取失败 for a state the system is telling them is normal.
 * 2. **The PUT is a whole-object replace.** `FrigateProviderPut` has no
 *    optional field that means "leave this alone" (`schemas.py:27-49`,
 *    `api.py:429-443`): `enabled`, `mode`, `base_url`, `mqtt_*` and
 *    `camera_map` are all replaced wholesale. A body built from a diff of
 *    changed fields wipes the rest, so the body always comes from
 *    `buildFrigatePut(form)` over the whole form — including the fields the
 *    operator never opened.
 * 3. **Credentials are write-only and are a five-field set.** The read model
 *    carries `credentials_configured: boolean` and nothing else
 *    (`schemas.py:62`); values are accepted only with
 *    `credentials_action: "replace"` (`api.py:355-381`), and a replace stages a
 *    brand-new secret blob and deletes the old one (`frigate.py:411-435`) — so
 *    it replaces all five fields at once, with no per-field verb. That is why
 *    the editor shows all five together and says that omitting one clears it.
 * 4. **`instance_id` is server-owned.** It is minted on first PUT and reused
 *    afterwards (`frigate.py:384-387`); the form never writes it.
 *
 * The two side-effecting actions stay explicit clicks: `/test` makes a real
 * outbound HTTP call to the configured Frigate with a 10s server timeout
 * (`api.py:556-561`), and `/backfill` enqueues a job that writes to the event
 * table and is refused with 409 `frigate_not_enabled` unless the *stored*
 * config is both configured and enabled (`api.py:578-595`).
 */
export function FrigatePanel() {
  const provider = useFrigateProvider()
  const cameras = useCameras()
  const confirm = useConfirm()
  const save = useSaveFrigateProvider()
  const test = useTestFrigateProvider()
  const backfill = useQueueFrigateBackfill()

  const [form, setForm] = useState<FrigateForm | null>(null)
  const [lookback, setLookback] = useState(600)

  // A 404 is data, not a failure: this is the only thing that separates the
  // first-run form from a real read failure.
  const notConfigured = isNotConfigured(provider.error)
  const view = provider.data ?? null

  // The form is seeded once, from the first settled read.
  //
  // Seeding has to survive the refetch that follows a save: a react-query query
  // that has *no data* returns to `status: 'pending'` while it refetches, so a
  // branch on `isPending` would unmount and remount the editor and throw away
  // everything the operator just typed. Holding the form state here — rather
  // than in a child seeded by props — is what makes that impossible.
  if (form === null && !provider.isPending && (view || notConfigured)) {
    setForm(frigateFormFromView(view))
  }

  if (form === null && provider.isPending) {
    return <p className="text-xs text-muted-foreground">读取中…</p>
  }

  if (provider.error && !notConfigured) {
    return (
      <div className="space-y-3">
        <Callout tone="offline" title="无法读取 Frigate 集成">
          <p>{provider.error.message}</p>
          <p className="mt-1">
            这不是「尚未配置」——未配置会返回 404
            <span className="font-mono"> frigate_not_configured</span>
            并显示配置表单。四个 Frigate 接口都需要
            <span className="font-mono"> integration.manage</span> 权限。
          </p>
        </Callout>
        <Button variant="outline" size="sm" onClick={() => provider.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (form === null) return null

  // `form` is narrowed here, but a hoisted `function` declaration is checked
  // against the pre-narrowing type, so the handlers below read this alias.
  const current = form

  const errors = validateFrigateForm(current)
  const errorFor = (field: FrigateFormField) =>
    errors.find((e: FrigateFormError) => e.field === field)?.message ?? null

  // One guard the frozen validator does not carry: `camera_id` is a UUID in
  // `FrigateCameraMapping` (`schemas.py:11-15`) and the service rejects an id
  // that is not a real camera with 400 `frigate_camera_mapping_unknown`
  // (`frigate.py:99-128`). A row with a name but no camera selected would
  // therefore always fail the request, so it is named here instead.
  const unselected = current.cameraMap.filter((m) => m.camera_id === "").length
  const blocked = errors.length > 0 || unselected > 0

  // The test and backfill endpoints read the *stored* row, not this form, so
  // their availability is decided by the server's view and not by the switches
  // below — an unsaved edit does not enable either of them.
  const storedEnabled = view?.enabled === true
  const testReason = view ? null : "尚未保存配置，无法测试。"
  const backfillReason = view
    ? storedEnabled
      ? null
      : "集成当前未启用，保存并启用后才能回填（服务端返回 409 frigate_not_enabled）。"
    : "尚未保存配置，保存并启用后才能回填。"

  function patch(next: Partial<FrigateForm>) {
    setForm((prev) => (prev ? { ...prev, ...next } : prev))
  }

  function setCameraMap(cameraMap: FrigateCameraMapping[]) {
    patch({ cameraMap })
  }

  function submit() {
    if (blocked) return
    // Always the whole form, never a diff of what changed.
    save.mutate(buildFrigatePut(current))
  }

  async function queueBackfill() {
    const seconds = clampLookback(lookback)
    const ok = await confirm({
      title: "排队回填 Frigate 事件",
      message: `将回看 ${formatLookback(seconds)}（${seconds} 秒）的 Frigate 事件并写入事件表，由后台任务执行。`,
      confirmLabel: "入队",
    })
    if (ok) backfill.mutate({ lookback_seconds: seconds })
  }

  return (
    <div className="space-y-5">
      {!view && (
        <Callout tone="unknown" title="尚未配置 Frigate">
          这是正常的首次状态：服务端还没有这条配置（读取返回 404
          <span className="font-mono"> frigate_not_configured</span>
          ）。填好下面的表单并保存后，连通性测试与事件回填才会可用。
        </Callout>
      )}

      {/* -------------------------------------------------------- status */}
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={storedEnabled ? "online" : view ? "unknown" : "degraded"} />
        <span className="text-sm font-medium">Frigate</span>
        <Badge variant={storedEnabled ? "success" : "outline"}>
          {storedEnabled ? "已启用" : view ? "已停用" : "未配置"}
        </Badge>
        <Badge variant="outline">{FRIGATE_MODE_LABEL[form.mode]}</Badge>
        {form.mqttEnabled && (
          <Badge variant="outline">
            <Wifi className="size-3" /> MQTT
          </Badge>
        )}
        {view?.credentials_configured && form.credentialsAction === "keep" && (
          <Badge variant="outline">
            <KeyRound className="size-3" /> 凭据已配置
          </Badge>
        )}
        {view && (
          <span className="text-[11px] text-muted-foreground">
            实例 ID <Mono>{view.instance_id}</Mono>
            <span className="ml-1">由服务端生成，表单不会写入它。</span>
          </span>
        )}
      </div>

      {/* ------------------------------------------------------ basics */}
      <Section title="连接">
        <div className="rounded-lg border border-border px-3">
          <Field
            label="启用"
            hint="停用后不再抓取事件；回填也会被服务端拒绝（409 frigate_not_enabled）。"
          >
            <Switch
              role="switch"
              aria-checked={form.enabled}
              aria-label="启用 Frigate 集成"
              onClick={() => patch({ enabled: !form.enabled })}
            />
          </Field>

          <Field
            label="模式"
            // The two modes have different consequences and the option labels
            // alone do not say them: managed makes the server build a Frigate
            // config plan on save while enabled (`api.py:445-470`), external
            // only tells the server where to reach a Frigate it does not run.
            hint={
              form.mode === "managed"
                ? "托管：保存并启用后由服务端生成 Frigate 配置方案。"
                : "外部：Frigate 由你自己运行，本系统只按下面的地址访问它。"
            }
          >
            <Select
              className="w-72"
              aria-label="Frigate 模式"
              value={form.mode}
              onChange={(e) => patch({ mode: e.target.value as FrigateMode })}
            >
              {(Object.keys(FRIGATE_MODE_LABEL) as FrigateMode[]).map((m) => (
                <option key={m} value={m}>
                  {FRIGATE_MODE_LABEL[m]}
                </option>
              ))}
            </Select>
          </Field>

          <Field
            label="Frigate 地址"
            // The shape rules are the server's, and it rejects the whole row on
            // the first violation (`frigate.py:73-96`), so they are stated up
            // front instead of arriving as a 400 about a field the operator
            // thought was a plain string.
            hint="http(s) 开头，不带账号密码与查询串；末尾的 / 会被服务端去掉。"
          >
            <Input
              className="w-72"
              aria-label="Frigate 地址"
              placeholder="http://frigate.local:5000"
              value={form.baseUrl}
              onChange={(e) => patch({ baseUrl: e.target.value })}
            />
          </Field>
        </div>
        {errorFor("baseUrl") && (
          <p className="text-[11px] text-status-offline">{errorFor("baseUrl")}</p>
        )}
      </Section>

      {/* ----------------------------------------------- camera mapping */}
      {/* The uniqueness rule is client-side because the server's 400 does not
          say which key collided (`api.py:345-354`) and it collapses the list
          into a dict first — so the panel names the duplicate itself. */}
      <Section
        title="摄像机映射"
        description="把 Frigate 侧的机位名对上本系统的摄像机。同一个 Frigate 机位名只能出现一次，否则服务端返回 400 frigate_camera_mapping_duplicate，而且它不会告诉你是哪一个。"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setCameraMap([...form.cameraMap, { frigate_camera: "", camera_id: "" }])
            }
          >
            <Plus /> 添加映射
          </Button>
        }
      >
        {form.cameraMap.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            还没有映射。没有映射时，Frigate 的事件不会落到本系统的摄像机上。
          </p>
        ) : (
          <ul className="space-y-2" aria-label="摄像机映射列表">
            {form.cameraMap.map((mapping, index) => (
              <li
                key={index}
                role="group"
                aria-label={`映射行 ${index + 1}`}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2"
              >
                <Input
                  className="w-48"
                  aria-label="Frigate 侧机位名"
                  placeholder="Frigate 机位名"
                  value={mapping.frigate_camera}
                  onChange={(e) =>
                    setCameraMap(
                      form.cameraMap.map((m, i) =>
                        i === index
                          ? { ...m, frigate_camera: e.target.value }
                          : m,
                      ),
                    )
                  }
                />
                <Select
                  className="w-56"
                  aria-label="本系统摄像机"
                  value={mapping.camera_id}
                  onChange={(e) =>
                    setCameraMap(
                      form.cameraMap.map((m, i) =>
                        i === index ? { ...m, camera_id: e.target.value } : m,
                      ),
                    )
                  }
                >
                  <option value="">未选择本系统摄像机</option>
                  {cameras.data?.map((c: CameraSummary) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`删除映射 ${index + 1}`}
                  title={`删除映射 ${index + 1}`}
                  onClick={() =>
                    setCameraMap(form.cameraMap.filter((_, i) => i !== index))
                  }
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        {(errorFor("cameraMap") || unselected > 0) && (
          <div className="space-y-1">
            {errorFor("cameraMap") && (
              <p className="text-[11px] text-status-offline">{errorFor("cameraMap")}</p>
            )}
            {unselected > 0 && (
              <p className="text-[11px] text-status-offline">
                还有 {unselected} 条映射没有选择本系统摄像机：camera_id 是必填的 UUID，留空会被服务端拒绝。
              </p>
            )}
          </div>
        )}
      </Section>

      {/* ---------------------------------------------------------- mqtt */}
      <Section
        title="MQTT"
        description="只有需要靠 MQTT 接收机位状态时才开启：关闭 MQTT 时保存会把 mqtt_host 写成 null，此前填过的主机不会保留。"
      >
        <div className="rounded-lg border border-border px-3">
          <Field label="启用 MQTT" hint="关闭后下面的字段不会被提交。">
            <Switch
              role="switch"
              aria-checked={form.mqttEnabled}
              aria-label="启用 MQTT"
              onClick={() => patch({ mqttEnabled: !form.mqttEnabled })}
            />
          </Field>

          {form.mqttEnabled && (
            <>
              <Field label="主机">
                <Input
                  className="w-72"
                  aria-label="MQTT 主机"
                  placeholder="mqtt.internal"
                  value={form.mqttHost}
                  onChange={(e) => patch({ mqttHost: e.target.value })}
                />
              </Field>
              <Field label="端口" hint="1–65535。">
                <Input
                  className="w-28"
                  type="number"
                  min={1}
                  max={65535}
                  aria-label="MQTT 端口"
                  value={form.mqttPort}
                  onChange={(e) => patch({ mqttPort: Number(e.target.value) })}
                />
              </Field>
              <Field label="主题前缀" hint="1–128 个字符。">
                <Input
                  className="w-72"
                  aria-label="MQTT 主题前缀"
                  value={form.mqttTopicPrefix}
                  onChange={(e) => patch({ mqttTopicPrefix: e.target.value })}
                />
              </Field>
              <Field label="使用 TLS">
                <Switch
                  role="switch"
                  aria-checked={form.mqttTls}
                  aria-label="MQTT 使用 TLS"
                  onClick={() => patch({ mqttTls: !form.mqttTls })}
                />
              </Field>
            </>
          )}
        </div>

        {errorFor("mqttHost") && (
          <p className="text-[11px] text-status-offline">{errorFor("mqttHost")}</p>
        )}
        {errorFor("mqttPort") && (
          <p className="text-[11px] text-status-offline">{errorFor("mqttPort")}</p>
        )}
        {errorFor("mqttTopicPrefix") && (
          <p className="text-[11px] text-status-offline">
            {errorFor("mqttTopicPrefix")}
          </p>
        )}
      </Section>

      {/* --------------------------------------------------- credentials */}
      <CredentialsEditor
        action={form.credentialsAction}
        onAction={(credentialsAction: SecretAction) =>
          patch({ credentialsAction })
        }
        credentials={form.credentials}
        onChange={(credentials: FrigateCredentialsInput) =>
          patch({ credentials })
        }
        configured={view?.credentials_configured === true}
        error={errorFor("credentials")}
      />

      {/* ------------------------------------------------------ actions */}
      <Section title="操作">
        <div className="rounded-lg border border-border px-3 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!view || test.isPending}
              onClick={() => test.mutate(undefined)}
            >
              <Send /> {test.isPending ? "测试中…" : "测试连接"}
            </Button>
            <span className="text-[11px] text-muted-foreground">
              {testReason ?? "会向已保存的 Frigate 发起一次真实请求（服务端 10 秒超时）；未保存的改动不参与测试。"}
            </span>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">回看窗口</span>
            <Input
              className="w-28"
              type="number"
              min={FRIGATE_MIN_LOOKBACK}
              max={FRIGATE_MAX_LOOKBACK}
              aria-label="回看窗口（秒）"
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value))}
            />
            <span className="text-[11px] text-muted-foreground">
              实际入队 {formatLookback(clampLookback(lookback))}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!view || !storedEnabled || backfill.isPending}
              onClick={queueBackfill}
            >
              <RefreshCw /> {backfill.isPending ? "入队中…" : "回填事件"}
            </Button>
          </div>
          {backfillReason && (
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-status-degraded">
              <TriangleAlert className="mt-0.5 size-3 shrink-0" />
              {backfillReason}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
            {blocked && (
              <span className="mr-auto text-[11px] text-status-degraded">
                表单还有未解决的问题，保存已被挡住。
              </span>
            )}
            <Button
              size="sm"
              disabled={blocked || save.isPending}
              onClick={submit}
            >
              <Check /> {save.isPending ? "保存中…" : "保存配置"}
            </Button>
          </div>
        </div>
      </Section>

      <PrototypeNote>
        凭据是只写字段：读取模型只给出「已配置」，保存后无法读回，也没有撤销。
        保存是整对象替换——表单里的每一个字段都会覆盖服务端，没有「保持原样」这种选项。
      </PrototypeNote>
    </div>
  )
}

/**
 * The schema window is 60…86400 (`schemas.py:71-76`). Clamping here means the
 * label and the confirmation name the lookback that will actually be queued,
 * instead of letting a typo become a 422 after the operator agreed to it.
 */
function clampLookback(seconds: number): number {
  return Math.min(
    FRIGATE_MAX_LOOKBACK,
    Math.max(FRIGATE_MIN_LOOKBACK, Math.trunc(seconds) || 0),
  )
}

/**
 * The five write-only credential fields, sharing one verb.
 *
 * `replace` stages a new secret blob and deletes the old one
 * (`frigate.py:411-435`), so it is a whole-set replace with no per-field verb —
 * unlike the notification panel, where each secret carries its own. Every field
 * is therefore shown at once, and the consequence is stated above them: a
 * replacement that omits a field clears it.
 *
 * `keep` is the only honest default. The values cannot be read, so there is
 * nothing to pre-fill, and an operator who does not type anything must not
 * replace or clear five secrets by accident.
 */
function CredentialsEditor({
  action,
  onAction,
  credentials,
  onChange,
  configured,
  error,
}: {
  action: SecretAction
  onAction: (next: SecretAction) => void
  credentials: FrigateCredentialsInput
  onChange: (next: FrigateCredentialsInput) => void
  configured: boolean
  error: string | null
}) {
  const fields: { key: keyof FrigateCredentialsInput; label: string; secret: boolean }[] = [
    { key: "http_bearer_token", label: "HTTP Bearer Token", secret: true },
    { key: "http_username", label: "HTTP 用户名", secret: false },
    { key: "http_password", label: "HTTP 密码", secret: true },
    { key: "mqtt_username", label: "MQTT 用户名", secret: false },
    { key: "mqtt_password", label: "MQTT 密码", secret: true },
  ]

  return (
    <div role="group" aria-label="Frigate 凭据" className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <KeyRound className="size-4 text-muted-foreground" />
          凭据
        </span>
        <span className="text-[11px] text-muted-foreground">
          {action === "clear"
            ? "将清空"
            : action === "replace"
              ? "将替换"
              : configured
                ? "已配置"
                : "未配置"}
        </span>
      </div>

      <Segmented
        className="mt-1.5"
        value={action}
        ariaLabel="Frigate 凭据操作"
        onChange={(v) => onAction(v as SecretAction)}
        options={[
          { value: "keep", label: "保持不变" },
          { value: "replace", label: "替换" },
          { value: "clear", label: "清空" },
        ]}
      />

      {action === "replace" && (
        <div className="mt-2 space-y-1.5">
          {fields.map((f) => (
            <Input
              key={f.key}
              type={f.secret ? "password" : "text"}
              aria-label={f.label}
              placeholder={f.label}
              value={credentials[f.key] ?? ""}
              onChange={(e) => onChange({ ...credentials, [f.key]: e.target.value })}
            />
          ))}
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            五项是一整组：「替换」只保存本次填写的项，本次没填的项会被清空并覆盖旧值。
          </p>
          {/* Stated because the operator cannot see it happening: a replace on
              an already-credentialed, enabled, external provider makes the
              server call Frigate and fail the whole PUT on a bad credential
              (`frigate.py:421-429`). */}
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            外部模式且集成已启用时，保存替换会由服务端立即向 Frigate
            发一次真实请求校验新凭据，凭据错误会直接让这次保存失败。
          </p>
          <p className="flex items-center text-[10px] text-muted-foreground">
            <Check className="mr-1 inline size-3" />
            只写字段，保存后无法读回。
          </p>
        </div>
      )}

      {action === "clear" && (
        <p className="mt-2 text-[10px] text-muted-foreground">
          清空后服务端会删除已存的凭据。若 Frigate 要求认证，事件抓取会随之失败。
        </p>
      )}

      {error && <p className="mt-1.5 text-[11px] text-status-offline">{error}</p>}
    </div>
  )
}
