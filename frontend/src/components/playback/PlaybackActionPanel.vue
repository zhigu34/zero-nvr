<script setup lang="ts">
import { useI18n } from "vue-i18n"

import type { ExportJob, ExportShare, ExportShareCreated } from "../../api/exports"
import type { RecordingProtection } from "../../api/recordings"
import UiIcon from "../ui/UiIcon.vue"
import PlaybackActionForm from "./PlaybackActionForm.vue"
import PlaybackActionHistory from "./PlaybackActionHistory.vue"
import PlaybackShareEditor from "./PlaybackShareEditor.vue"

defineProps<{
  actionMode: "protect" | "export"
  cameraName: string | null
  editingProtectionId: string | null
  actionSaving: boolean
  cameraProtections: RecordingProtection[]
  cameraExports: ExportJob[]
  shareExport: ExportJob | null
  shareSaving: boolean
  shareCopied: boolean
  createdShare: ExportShareCreated | null
  exportShares: ExportShare[]
  formatTimestamp: (date: Date) => string
  translatedStatus: (value: string) => string
  shareUrl: (item: ExportShareCreated) => string
}>()

const actionStart = defineModel<string>("actionStart", { required: true })
const actionEnd = defineModel<string>("actionEnd", { required: true })
const protectionReason = defineModel<string>("protectionReason", { required: true })
const protectionExpiresAt = defineModel<string>("protectionExpiresAt", { required: true })
const exportCodecMode = defineModel<"auto" | "copy" | "h264">("exportCodecMode", { required: true })
const exportGapPolicy = defineModel<"skip" | "fail">("exportGapPolicy", { required: true })
const sharePassword = defineModel<string>("sharePassword", { required: true })
const shareExpiresHours = defineModel<number>("shareExpiresHours", { required: true })
const shareMaxDownloads = defineModel<number>("shareMaxDownloads", { required: true })

const emit = defineEmits<{
  close: []
  "save-protection": []
  "save-export": []
  "edit-protection": [item: RecordingProtection]
  "remove-protection": [item: RecordingProtection]
  "open-share": [item: ExportJob]
  "remove-export": [item: ExportJob]
  "close-share": []
  "save-share": []
  "copy-share-link": []
  "revoke-share": [item: ExportShare]
}>()

const { t } = useI18n({ useScope: "global" })

</script>

<template>
  <aside
    class="playback-action-panel"
  >
    <header>
      <div>
        <strong>
          {{
            actionMode === "protect"
              ? editingProtectionId
                ? t("playback.editProtection")
                : t("playback.protectRecording")
              : t("playback.exportClip")
          }}
        </strong>
        <span>{{ cameraName || t("playback.cameraFallback") }}</span>
      </div>
      <button
        class="icon-button"
        type="button"
        :title="t('playback.close')"
        @click="emit('close')"
      >
        <UiIcon name="close" :size="15" />
      </button>
    </header>

    <PlaybackActionForm
      v-model:action-start="actionStart"
      v-model:action-end="actionEnd"
      v-model:protection-reason="protectionReason"
      v-model:protection-expires-at="protectionExpiresAt"
      v-model:export-codec-mode="exportCodecMode"
      v-model:export-gap-policy="exportGapPolicy"
      :mode="actionMode"
      :editing-protection-id="editingProtectionId"
      :saving="actionSaving"
      @close="emit('close')"
      @save-protection="emit('save-protection')"
      @save-export="emit('save-export')"
    />

    <PlaybackActionHistory
      :mode="actionMode"
      :protections="cameraProtections"
      :exports="cameraExports"
      :format-timestamp="formatTimestamp"
      :translated-status="translatedStatus"
      @edit-protection="emit('edit-protection', $event)"
      @remove-protection="emit('remove-protection', $event)"
      @open-share="emit('open-share', $event)"
      @remove-export="emit('remove-export', $event)"
    />

    <PlaybackShareEditor
      v-if="actionMode === 'export' && shareExport"
      v-model:share-password="sharePassword"
      v-model:share-expires-hours="shareExpiresHours"
      v-model:share-max-downloads="shareMaxDownloads"
      :share-export="shareExport"
      :share-saving="shareSaving"
      :share-copied="shareCopied"
      :created-share="createdShare"
      :export-shares="exportShares"
      :format-timestamp="formatTimestamp"
      :share-url="shareUrl"
      @close="emit('close-share')"
      @save="emit('save-share')"
      @copy="emit('copy-share-link')"
      @revoke="emit('revoke-share', $event)"
    />
  </aside>
</template>

<style scoped>
.playback-action-panel {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  bottom: 0;
  z-index: 42;
  width: min(370px, 94vw);
  overflow-y: auto;
  border-left: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-primary);
  box-shadow: -16px 0 42px rgba(0, 0, 0, 0.2);
}

.playback-action-panel > header {
  display: flex;
  min-height: 56px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 10px 0 13px;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-action-panel > header strong,
.playback-action-panel > header span {
  display: block;
}

.playback-action-panel > header strong {
  font-size: 14px;
  font-weight: 600;
}

.playback-action-panel > header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 11px;
}

</style>
