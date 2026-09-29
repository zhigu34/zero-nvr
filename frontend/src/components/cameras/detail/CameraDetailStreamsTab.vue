<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import {
  refreshOnvifCapabilities,
  replaceCameraBindings,
  verifyCameraStream,
  type CameraDetail,
  type CameraStreamBinding,
  type CameraStreamProfile
} from "../../../api/cameras"
import { errorMessage } from "../../../api/client"
import UiIcon from "../../ui/UiIcon.vue"

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

const { t, te } = useI18n({ useScope: "global" })

const savingStreams = ref(false)
const refreshingCapabilities = ref(false)
const verifyingStreamId = ref<string | null>(null)

const purposes: CameraStreamBinding["purpose"][] = [
  "RECORD",
  "LIVE_HIGH",
  "LIVE_LOW",
  "AI_DETECT",
  "SNAPSHOT",
  "AUDIO"
]

const bindingForm = reactive<Record<string, string>>({
  RECORD: "",
  LIVE_HIGH: "",
  LIVE_LOW: "",
  AI_DETECT: "",
  SNAPSHOT: "",
  AUDIO: ""
})

const audioStreams = computed(() =>
  (props.camera.streams ?? []).filter((s) => s.has_audio)
)

const videoStreams = computed(() =>
  (props.camera.streams ?? []).filter((s) => s.codec?.toLowerCase() !== "aac")
)

function streamsForPurpose(
  purpose: CameraStreamBinding["purpose"]
): CameraStreamProfile[] {
  return purpose === "AUDIO"
    ? audioStreams.value
    : videoStreams.value
}

function streamDescription(stream: CameraStreamProfile): string {
  const pieces = [
    stream.codec?.toUpperCase(),
    stream.width && stream.height ? `${stream.width}×${stream.height}` : null,
    stream.fps ? `${Math.round(stream.fps)} fps` : null,
    stream.bitrate_kbps ? `${stream.bitrate_kbps} kbps` : null,
    stream.has_audio ? t("cameras.detail.audio") : null
  ].filter(Boolean)
  return pieces.join(" · ") || stream.adapter_profile_key
}

function purposeLabel(value: CameraStreamBinding["purpose"]): string {
  const keys: Record<CameraStreamBinding["purpose"], string> = {
    RECORD: "cameras.detail.purpose.recording",
    LIVE_HIGH: "cameras.detail.purpose.liveHigh",
    LIVE_LOW: "cameras.detail.purpose.liveLow",
    AI_DETECT: "cameras.detail.purpose.aiDetection",
    SNAPSHOT: "cameras.detail.purpose.snapshot",
    AUDIO: "cameras.detail.purpose.audio"
  }
  return t(keys[value])
}

function streamStatusLabel(value: string): string {
  const key = `cameras.detail.streamStatus.${value.toLowerCase()}`
  return te(key) ? t(key) : value
}

function resetBindings(value: CameraDetail): void {
  for (const purpose of purposes) {
    bindingForm[purpose] =
      value.bindings.find((item) => item.purpose === purpose)
        ?.stream_profile_id ?? ""
  }
}

watch(
  () => props.camera,
  (val) => {
    if (val) resetBindings(val)
  },
  { immediate: true }
)

async function saveStreams(): Promise<void> {
  savingStreams.value = true
  try {
    const bindings = purposes
      .filter((purpose) => Boolean(bindingForm[purpose]))
      .map((purpose) => ({
        purpose,
        stream_profile_id: bindingForm[purpose],
        selection_mode: "manual" as const
      }))

    const updatedBindings = await replaceCameraBindings(props.camera.id, bindings)
    const updated = { ...props.camera, bindings: updatedBindings }
    emit("updated", updated)
    resetBindings(updated)
    emit("notice", t("cameras.detail.bindingsSaved"))
    emit("changed")
  } catch (caught) {
    emit("error", errorMessage(caught))
  } finally {
    savingStreams.value = false
  }
}

async function refreshCapabilities(): Promise<void> {
  if (props.camera.adapter_type !== "onvif" || !props.canConfigure) return

  refreshingCapabilities.value = true
  try {
    const result = await refreshOnvifCapabilities(props.camera.id)
    const refreshed = result.cameras.find((item) => item.id === props.camera.id)
    if (refreshed) {
      emit("updated", refreshed)
      resetBindings(refreshed)
    }

    const messages: string[] = []
    if (result.diff.profiles_missing.length) {
      messages.push(
        t("cameras.detail.refreshMissing", { items: result.diff.profiles_missing.join(", ") })
      )
    }
    if (result.diff.profiles_recovered.length) {
      messages.push(
        t("cameras.detail.refreshRecovered", { items: result.diff.profiles_recovered.join(", ") })
      )
    }
    if (result.diff.profiles_added.length) {
      messages.push(
        t("cameras.detail.refreshAdded", { items: result.diff.profiles_added.join(", ") })
      )
    }
    if (result.diff.profiles_changed.length) {
      messages.push(
        t("cameras.detail.refreshChanged", { items: result.diff.profiles_changed.join(", ") })
      )
    }
    if (result.diff.capabilities_added.length) {
      messages.push(
        t("cameras.detail.capabilitiesAdded", { items: result.diff.capabilities_added.join(", ") })
      )
    }
    if (result.diff.capabilities_removed.length) {
      messages.push(
        t("cameras.detail.capabilitiesRemoved", { items: result.diff.capabilities_removed.join(", ") })
      )
    }

    emit(
      "notice",
      messages.length
        ? t("cameras.detail.refreshComplete", { details: messages.join(" · ") })
        : t("cameras.detail.refreshUnchanged")
    )
    emit("changed")
  } catch (caught) {
    emit("error", errorMessage(caught))
  } finally {
    refreshingCapabilities.value = false
  }
}

async function handleVerifyStream(profileId: string): Promise<void> {
  if (!props.camera?.id || verifyingStreamId.value) return
  verifyingStreamId.value = profileId
  try {
    await verifyCameraStream(props.camera.id, profileId)
    emit("notice", "码流检测已执行，已更新最新状态与分辨率")
    emit("changed")
  } catch (caught) {
    emit("error", `码流检测失败: ${errorMessage(caught)}`)
  } finally {
    verifyingStreamId.value = null
  }
}
</script>

<template>
  <div class="camera-stream-editor">
    <section class="camera-detail-section">
      <div class="camera-detail-section__heading camera-detail-section__heading--actions">
        <div>
          <strong>{{ t("cameras.detail.availableProfiles") }}</strong>
          <span>{{ t("cameras.detail.profilesHint") }}</span>
        </div>
        <button
          v-if="camera.adapter_type === 'onvif'"
          class="button button--ghost button--compact"
          type="button"
          :disabled="refreshingCapabilities || !canConfigure"
          @click="refreshCapabilities"
        >
          <UiIcon name="refresh" :size="12" />
          {{
            refreshingCapabilities
              ? t("cameras.detail.refreshing")
              : t("cameras.detail.refreshOnvif")
          }}
        </button>
      </div>

      <article
        v-for="stream in camera.streams"
        :key="stream.id"
        class="camera-stream-profile"
      >
        <div>
          <strong>{{ stream.name }}</strong>
          <span>{{ streamDescription(stream) }}</span>
        </div>
        <div class="stream-actions">
          <span class="status-pill">
            {{ streamStatusLabel(stream.status) }}
          </span>
          <button
            v-if="canConfigure"
            type="button"
            class="button button--ghost button--compact"
            :disabled="verifyingStreamId === stream.id"
            title="通过流媒体引擎测试探测该码流"
            @click="handleVerifyStream(stream.id)"
          >
            <UiIcon
              name="search"
              :size="12"
              :class="{ 'animate-spin': verifyingStreamId === stream.id }"
            />
            <span>{{ verifyingStreamId === stream.id ? '检测中...' : '测试检测' }}</span>
          </button>
        </div>
      </article>
    </section>

    <section class="camera-detail-section">
      <div class="camera-detail-section__heading">
        <strong>{{ t("cameras.detail.purposeBindings") }}</strong>
        <span>{{ t("cameras.detail.purposeHint") }}</span>
      </div>

      <label
        v-for="purpose in purposes"
        :key="purpose"
        class="camera-binding-row"
      >
        <span>{{ purposeLabel(purpose) }}</span>
        <select
          v-model="bindingForm[purpose]"
          :disabled="!canConfigure"
        >
          <option value="">{{ t("cameras.detail.notAssigned") }}</option>
          <option
            v-for="stream in streamsForPurpose(purpose)"
            :key="stream.id"
            :value="stream.id"
          >
            {{ stream.name }} · {{ streamDescription(stream) }}
          </option>
        </select>
      </label>

      <div class="camera-detail-actions">
        <button
          class="button button--primary"
          type="button"
          :disabled="savingStreams || !canConfigure"
          @click="saveStreams"
        >
          {{ savingStreams ? t("cameras.detail.saving") : t("cameras.detail.saveBindings") }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.camera-stream-editor {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.camera-detail-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.camera-detail-section__heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.camera-detail-section__heading--actions {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.camera-detail-section__heading strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.camera-detail-section__heading span {
  font-size: 11px;
  color: var(--uf-text-muted);
}

.camera-stream-profile {
  display: flex;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  background: var(--uf-bg-card-sub);
}

.camera-stream-profile div {
  min-width: 0;
}

.camera-stream-profile strong {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.camera-stream-profile div > span {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  color: var(--uf-text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stream-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-pill {
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  background: var(--uf-bg-canvas);
}

.camera-binding-row {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
}

.camera-binding-row > span {
  color: var(--uf-text-secondary);
  font-size: 12px;
  font-weight: 500;
}

.camera-binding-row select {
  height: 38px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  font-size: 13px;
  transition: all 0.15s ease;
}

.camera-binding-row select:focus {
  outline: none;
  border-color: var(--uf-accent);
  box-shadow: 0 0 0 3px var(--uf-accent-soft);
}

.camera-detail-actions {
  display: flex;
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

.button--compact {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
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
