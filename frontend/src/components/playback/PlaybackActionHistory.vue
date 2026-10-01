<script setup lang="ts">
import { useI18n } from "vue-i18n"

import { exportDownloadUrl, type ExportJob } from "../../api/exports"
import type { RecordingProtection } from "../../api/recordings"
import UiIcon from "../ui/UiIcon.vue"

defineProps<{
  mode: "protect" | "export"
  protections: RecordingProtection[]
  exports: ExportJob[]
  formatTimestamp: (date: Date) => string
  translatedStatus: (value: string) => string
}>()

const emit = defineEmits<{
  "edit-protection": [item: RecordingProtection]
  "remove-protection": [item: RecordingProtection]
  "open-share": [item: ExportJob]
  "remove-export": [item: ExportJob]
}>()

const { t } = useI18n({ useScope: "global" })

function exportStateClass(state: string): string {
  const normalized = state.toUpperCase()
  if (normalized === "COMPLETED") return "status-pill--ok"
  if (normalized === "FAILED") return "status-pill--error"
  return "status-pill--muted"
}
</script>

<template>
  <section
    v-if="mode === 'protect' && protections.length"
    class="playback-action-history"
  >
    <h3>{{ t("playback.protectedRanges") }}</h3>
    <article
      v-for="item in protections"
      :key="item.id"
    >
      <div>
        <strong>{{ item.reason }}</strong>
        <span>
          {{ formatTimestamp(new Date(item.started_at)) }}
          →
          {{ formatTimestamp(new Date(item.ended_at)) }}
        </span>
        <span v-if="item.expires_at">
          {{ t("playback.expires", { time: formatTimestamp(new Date(item.expires_at)) }) }}
        </span>
      </div>
      <button
        class="icon-button"
        type="button"
        :title="t('playback.editProtection')"
        @click="emit('edit-protection', item)"
      >
        <UiIcon name="shield" :size="13" />
      </button>
      <button
        class="icon-button icon-button--danger"
        type="button"
        :title="t('playback.removeProtection')"
        @click="emit('remove-protection', item)"
      >
        <UiIcon name="trash" :size="13" />
      </button>
    </article>
  </section>

  <section
    v-if="mode === 'export' && exports.length"
    class="playback-action-history"
  >
    <h3>{{ t("playback.recentExports") }}</h3>
    <article
      v-for="item in exports"
      :key="item.id"
    >
      <div>
        <strong>
          {{ formatTimestamp(new Date(item.start_at)) }}
        </strong>
        <span>
          {{ Math.round(item.requested_duration_ms / 1000) }}s ·
          {{ item.codec_mode }}
        </span>
      </div>
      <span
        class="status-pill"
        :class="exportStateClass(item.state)"
      >
        {{ translatedStatus(item.state) }}
      </span>
      <button
        v-if="item.state === 'COMPLETED'"
        class="icon-button"
        type="button"
        :title="t('playback.manageShareLink')"
        @click="emit('open-share', item)"
      >
        <UiIcon name="share" :size="13" />
      </button>
      <a
        v-if="item.state === 'COMPLETED'"
        class="icon-button"
        :href="exportDownloadUrl(item.id)"
        :title="t('playback.downloadMp4')"
      >
        <UiIcon name="download" :size="13" />
      </a>
      <button
        class="icon-button icon-button--danger"
        type="button"
        :title="t('playback.deleteExport')"
        @click="emit('remove-export', item)"
      >
        <UiIcon name="trash" :size="13" />
      </button>
    </article>
  </section>

</template>

<style scoped>
.playback-action-history {
  padding: 11px 12px;
}

.playback-action-history h3 {
  margin: 0 0 7px;
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-weight: 600;
}

.playback-action-history article {
  display: flex;
  min-height: 48px;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-action-history article:last-child {
  border-bottom: 0;
}

.playback-action-history article > div {
  min-width: 0;
  flex: 1;
}

.playback-action-history strong,
.playback-action-history div > span {
  display: block;
}

.playback-action-history strong {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.playback-action-history div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 11px;
}
</style>
