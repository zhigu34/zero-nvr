<script setup lang="ts">
import { reactive, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import {
  retireCamera,
  restoreCamera,
  setCameraEnabled,
  updateCamera,
  type CameraDetail,
  type CameraFormFactor,
  type CameraTimeSyncMode
} from "../../../api/cameras"
import { errorMessage } from "../../../api/client"

const props = defineProps<{
  camera: CameraDetail
  canConfigure: boolean
}>()

const emit = defineEmits<{
  updated: [camera: CameraDetail]
  changed: []
  notice: [msg: string]
  error: [msg: string]
}>()

const { t } = useI18n({ useScope: "global" })

const savingGeneral = ref(false)
const retirementSaving = ref(false)

const POPULAR_MANUFACTURERS = [
  "Hikvision (海康威视)",
  "Dahua (大华)",
  "Uniview (宇视)",
  "TP-LINK (普联)",
  "Xiaomi (小米/米家)",
  "Imou (乐橙)",
  "Ezviz (萤石)",
  "Axis (安讯士)",
  "Hanwha (韩华)",
  "Tiandy (天地伟业)"
]

const formFactorOptions: Array<{ value: CameraFormFactor; label: string }> = [
  { value: "unknown", label: "未指定 (Default)" },
  { value: "bullet", label: "枪机 (Bullet)" },
  { value: "dome", label: "半球 (Dome)" },
  { value: "turret", label: "海螺 / 炮塔 (Turret)" },
  { value: "ptz", label: "云台 (PTZ)" },
  { value: "doorbell", label: "门铃 (Doorbell)" }
]

const generalForm = reactive({
  name: "",
  location: "",
  storageLabel: "",
  manufacturer: "",
  model: "",
  formFactor: "unknown" as CameraFormFactor,
  timeSyncMode: "manage_ntp" as CameraTimeSyncMode
})

function resetForm(value: CameraDetail): void {
  generalForm.name = value.name
  generalForm.location = value.location ?? ""
  generalForm.storageLabel = value.storage_label ?? ""
  generalForm.manufacturer = value.manufacturer ?? ""
  generalForm.model = value.model ?? ""
  generalForm.formFactor = value.form_factor ?? "unknown"
  generalForm.timeSyncMode = value.time_sync_mode ?? "manage_ntp"
}

watch(
  () => props.camera,
  (val) => {
    if (val) resetForm(val)
  },
  { immediate: true }
)

async function saveGeneral(): Promise<void> {
  savingGeneral.value = true
  try {
    const updated = await updateCamera(props.camera.id, {
      name: generalForm.name.trim(),
      location: generalForm.location.trim() || null,
      storage_label: generalForm.storageLabel.trim() || null,
      manufacturer: generalForm.manufacturer.trim() || null,
      model: generalForm.model.trim() || null,
      form_factor: generalForm.formFactor,
      time_sync_mode: generalForm.timeSyncMode
    })
    emit("updated", updated)
    resetForm(updated)
    emit("notice", t("cameras.detail.settingsSaved"))
    emit("changed")
  } catch (caught) {
    emit("error", errorMessage(caught))
  } finally {
    savingGeneral.value = false
  }
}

async function toggleEnabled(): Promise<void> {
  try {
    const updated = await setCameraEnabled(props.camera.id, !props.camera.enabled)
    emit("updated", updated)
    emit(
      "notice",
      updated.enabled
        ? t("cameras.detail.enabledNotice")
        : t("cameras.detail.disabledNotice")
    )
    emit("changed")
  } catch (caught) {
    emit("error", errorMessage(caught))
  }
}

async function toggleRetired(): Promise<void> {
  if (!props.canConfigure) return

  const restoring = Boolean(props.camera.retired_at)
  if (
    !restoring &&
    !window.confirm(
      t("cameras.detail.retireConfirm", { name: props.camera.name })
    )
  ) {
    return
  }

  retirementSaving.value = true
  try {
    const updated = restoring
      ? await restoreCamera(props.camera.id)
      : await retireCamera(props.camera.id)
    emit("updated", updated)
    emit(
      "notice",
      restoring
        ? t("cameras.detail.restoredNotice")
        : t("cameras.detail.retiredNotice")
    )
    emit("changed")
  } catch (caught) {
    emit("error", errorMessage(caught))
  } finally {
    retirementSaving.value = false
  }
}

async function toggleMaintenance(): Promise<void> {
  if (!props.canConfigure) return
  try {
    const nextState = !props.camera.maintenance
    const updated = await updateCamera(props.camera.id, { maintenance: nextState })
    emit("updated", updated)
    emit(
      "notice",
      nextState
        ? `机位 [${props.camera.name}] 已进入维护模式`
        : `机位 [${props.camera.name}] 已退出维护模式，恢复正常运行`
    )
    emit("changed")
  } catch (caught) {
    emit("error", errorMessage(caught))
  }
}
</script>

<template>
  <form class="camera-detail-form" @submit.prevent="saveGeneral">
    <label>
      <span>{{ t("cameras.name") }}</span>
      <input v-model="generalForm.name" required maxlength="128" />
    </label>

    <label>
      <span>设备厂商 (Manufacturer)</span>
      <input
        v-model="generalForm.manufacturer"
        maxlength="128"
        placeholder="例如: Hikvision, Dahua, Uniview, TP-LINK..."
      />
      <div class="manufacturer-pills">
        <button
          v-for="brand in POPULAR_MANUFACTURERS"
          :key="brand"
          type="button"
          class="brand-pill"
          @click="generalForm.manufacturer = brand"
        >
          {{ brand }}
        </button>
      </div>
    </label>

    <div class="form-row-two">
      <label>
        <span>设备型号 (Model)</span>
        <input
          v-model="generalForm.model"
          maxlength="128"
          placeholder="例如: DS-2CD2T87G2-L"
        />
      </label>

      <label>
        <span>外形类型 (Form Factor)</span>
        <select v-model="generalForm.formFactor">
          <option
            v-for="opt in formFactorOptions"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </option>
        </select>
      </label>
    </div>

    <label>
      <span>{{ t("cameras.location") }}</span>
      <input v-model="generalForm.location" maxlength="256" placeholder="例如: 园区东门、办公区前台" />
    </label>

    <div class="form-row-two">
      <label>
        <span>{{ t("cameras.storageLabel") }}</span>
        <input v-model="generalForm.storageLabel" maxlength="128" placeholder="例如: local-nvme, pool-1" />
      </label>

      <label>
        <span>NTP 时钟同步策略</span>
        <select v-model="generalForm.timeSyncMode">
          <option value="manage_ntp">Managed NTP (主动下发校时)</option>
          <option value="monitor">Monitor (仅监控时钟漂移)</option>
          <option value="ignore">Ignore (忽略时钟)</option>
        </select>
      </label>
    </div>

    <div class="camera-detail-actions">
      <button
        v-if="canConfigure && !camera.retired_at"
        class="button button--ghost"
        type="button"
        @click="toggleEnabled"
      >
        {{ camera.enabled ? t("cameras.detail.disableCamera") : t("cameras.detail.enableCamera") }}
      </button>
      <button
        v-if="canConfigure && !camera.retired_at"
        class="button button--ghost"
        type="button"
        @click="toggleMaintenance"
      >
        {{ camera.maintenance ? '退出维护模式' : '进入维护模式' }}
      </button>
      <button
        v-if="canConfigure"
        class="button button--ghost"
        type="button"
        :disabled="retirementSaving"
        @click="toggleRetired"
      >
        {{
          retirementSaving
            ? t("cameras.detail.saving")
            : camera.retired_at
              ? t("cameras.detail.restoreCamera")
              : t("cameras.detail.retireCamera")
        }}
      </button>
      <button
        class="button button--primary"
        type="submit"
        :disabled="savingGeneral || !canConfigure"
      >
        {{ savingGeneral ? t("cameras.detail.saving") : t("cameras.detail.save") }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.camera-detail-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.camera-detail-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--uf-text-secondary);
}

.camera-detail-form span {
  font-weight: 500;
}

.camera-detail-form input,
.camera-detail-form select {
  height: 38px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  font-size: 13px;
  transition: all 0.15s ease;
}

.camera-detail-form input:focus,
.camera-detail-form select:focus {
  outline: none;
  border-color: var(--uf-accent);
  box-shadow: 0 0 0 3px var(--uf-accent-soft);
}

.form-row-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.manufacturer-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.brand-pill {
  padding: 3px 8px;
  font-size: 11px;
  border-radius: 4px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.brand-pill:hover {
  border-color: var(--uf-accent);
  color: var(--uf-accent);
  background: var(--uf-accent-soft);
}

.camera-detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--uf-border);
  margin-top: 8px;
}

.button {
  height: 36px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.button--primary {
  background: var(--uf-accent);
  color: #ffffff;
}

.button--primary:hover:not(:disabled) {
  opacity: 0.9;
}

.button--ghost {
  background: transparent;
  border-color: var(--uf-border);
  color: var(--uf-text-secondary);
}

.button--ghost:hover:not(:disabled) {
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
  border-color: var(--uf-text-muted);
}
</style>
