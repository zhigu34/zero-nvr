<script setup lang="ts">
import { useI18n } from "vue-i18n"

defineProps<{
  mode: "protect" | "export"
  editingProtectionId: string | null
  saving: boolean
}>()

const actionStart = defineModel<string>("actionStart", { required: true })
const actionEnd = defineModel<string>("actionEnd", { required: true })
const protectionReason = defineModel<string>("protectionReason", { required: true })
const protectionExpiresAt = defineModel<string>("protectionExpiresAt", { required: true })
const exportCodecMode = defineModel<"auto" | "copy" | "h264">("exportCodecMode", { required: true })
const exportGapPolicy = defineModel<"skip" | "fail">("exportGapPolicy", { required: true })

const emit = defineEmits<{
  close: []
  "save-protection": []
  "save-export": []
}>()

const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <form
    class="playback-action-form"
    @submit.prevent="
      mode === 'protect'
        ? emit('save-protection')
        : emit('save-export')
    "
  >
    <label>
      <span>{{ t("playback.start") }}</span>
      <input
        v-model="actionStart"
        type="datetime-local"
        step="1"
        required
      />
    </label>
    <label>
      <span>{{ t("playback.end") }}</span>
      <input
        v-model="actionEnd"
        type="datetime-local"
        step="1"
        required
      />
    </label>

    <template v-if="mode === 'protect'">
      <label>
        <span>{{ t("playback.reason") }}</span>
        <input
          v-model="protectionReason"
          required
          maxlength="1024"
        />
      </label>
      <label>
        <span>{{ t("playback.expiresAt") }}</span>
        <input
          v-model="protectionExpiresAt"
          type="datetime-local"
          step="60"
        />
        <small>{{ t("playback.indefiniteHint") }}</small>
      </label>
    </template>

    <template v-else>
      <label>
        <span>{{ t("playback.codec") }}</span>
        <select v-model="exportCodecMode">
          <option value="auto">{{ t("playback.auto") }}</option>
          <option value="copy">{{ t("playback.copyWhenPossible") }}</option>
          <option value="h264">{{ t("playback.transcodeH264") }}</option>
        </select>
      </label>
      <label>
        <span>{{ t("playback.gaps") }}</span>
        <select v-model="exportGapPolicy">
          <option value="skip">{{ t("playback.skipGapsOption") }}</option>
          <option value="fail">{{ t("playback.failOnGaps") }}</option>
        </select>
      </label>
    </template>

    <div class="playback-action-form__actions">
      <button
        class="button button--ghost"
        type="button"
        @click="emit('close')"
      >
        {{ t("playback.cancel") }}
      </button>
      <button
        class="button button--primary"
        type="submit"
        :disabled="saving"
      >
        {{
          saving
            ? t("playback.saving")
            : mode === "protect"
              ? editingProtectionId
                ? t("playback.saveProtection")
                : t("playback.protectRange")
              : t("playback.createExport")
        }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.playback-action-form {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-action-form label {
  display: grid;
  gap: 5px;
}

.playback-action-form label > span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}


.playback-action-form label > small {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.35;
}

.playback-action-form input,
.playback-action-form select {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-base);
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
}

.playback-action-form input:focus,
.playback-action-form select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.playback-action-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding-top: 3px;
}
</style>
