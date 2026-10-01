<script setup lang="ts">
import { useI18n } from "vue-i18n"

import type { ExportJob, ExportShare, ExportShareCreated } from "../../api/exports"
import UiIcon from "../ui/UiIcon.vue"

defineProps<{
  shareExport: ExportJob
  shareSaving: boolean
  shareCopied: boolean
  createdShare: ExportShareCreated | null
  exportShares: ExportShare[]
  formatTimestamp: (date: Date) => string
  shareUrl: (item: ExportShareCreated) => string
}>()

const sharePassword = defineModel<string>("sharePassword", { required: true })
const shareExpiresHours = defineModel<number>("shareExpiresHours", { required: true })
const shareMaxDownloads = defineModel<number>("shareMaxDownloads", { required: true })

const emit = defineEmits<{
  close: []
  save: []
  copy: []
  revoke: [item: ExportShare]
}>()

const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <section
    class="playback-share-editor"
  >
    <header>
      <div>
        <strong>{{ t("playback.shareExport") }}</strong>
        <span>
          {{ formatTimestamp(new Date(shareExport.start_at)) }}
        </span>
      </div>
      <button
        class="icon-button"
        type="button"
        :title="t('playback.closeShareEditor')"
        @click="emit('close')"
      >
        <UiIcon name="close" :size="13" />
      </button>
    </header>

    <form @submit.prevent="emit('save')">
      <label>
        <span>{{ t("playback.password") }}</span>
        <input
          v-model="sharePassword"
          type="password"
          :placeholder="t('playback.optional')"
          autocomplete="new-password"
        />
      </label>
      <label>
        <span>{{ t("playback.expiresAfter") }}</span>
        <select v-model.number="shareExpiresHours">
          <option :value="1">{{ t("playback.oneHour") }}</option>
          <option :value="6">{{ t("playback.sixHours") }}</option>
          <option :value="24">{{ t("playback.twentyFourHours") }}</option>
          <option :value="72">{{ t("playback.threeDays") }}</option>
          <option :value="168">{{ t("playback.sevenDays") }}</option>
          <option :value="720">{{ t("playback.thirtyDays") }}</option>
        </select>
      </label>
      <label>
        <span>{{ t("playback.maximumDownloads") }}</span>
        <input
          v-model.number="shareMaxDownloads"
          type="number"
          min="0"
          max="100000"
          :placeholder="t('playback.unlimitedDownloads')"
        />
      </label>
      <button
        class="button button--primary"
        type="submit"
        :disabled="shareSaving"
      >
        {{ shareSaving ? t("playback.creating") : t("playback.createShareLink") }}
      </button>
    </form>

    <div
      v-if="createdShare"
      class="playback-share-created"
    >
      <strong>{{ t("playback.shareLinkCreated") }}</strong>
      <span>
        {{ t("playback.oneTimeTokenHint") }}
      </span>
      <div>
        <input
          :value="shareUrl(createdShare)"
          readonly
          @focus="($event.target as HTMLInputElement).select()"
        />
        <button
          class="button button--ghost button--compact"
          type="button"
          @click="emit('copy')"
        >
          {{ shareCopied ? t("playback.copied") : t("playback.copy") }}
        </button>
      </div>
    </div>

    <div
      v-if="exportShares.length"
      class="playback-share-list"
    >
      <h4>{{ t("playback.existingShares") }}</h4>
      <article
        v-for="item in exportShares"
        :key="item.id"
      >
        <div>
          <strong>
            {{
              item.revoked_at
                ? t("playback.revoked")
                : new Date(item.expires_at) <= new Date()
                  ? t("playback.expired")
                  : t("playback.active")
            }}
          </strong>
          <span>
            {{
              item.max_downloads
                ? t("playback.downloadsLimited", {
                    downloads: item.download_count,
                    max: item.max_downloads,
                    time: formatTimestamp(new Date(item.expires_at))
                  })
                : t("playback.downloadsExpires", {
                    downloads: item.download_count,
                    time: formatTimestamp(new Date(item.expires_at))
                  })
            }}
          </span>
        </div>
        <span
          v-if="item.password_protected"
          class="status-pill"
        >
          {{ t("playback.passwordProtected") }}
        </span>
        <button
          v-if="!item.revoked_at"
          class="icon-button icon-button--danger"
          type="button"
          :title="t('playback.revokeShare')"
          @click="emit('revoke', item)"
        >
          <UiIcon name="trash" :size="13" />
        </button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.playback-share-editor {
  display: grid;
  gap: 10px;
  margin: 0 12px 12px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.playback-share-editor > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.playback-share-editor > header strong,
.playback-share-editor > header span {
  display: block;
}

.playback-share-editor > header strong {
  font-size: 13px;
  font-weight: 600;
}

.playback-share-editor > header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 11px;
}

.playback-share-editor form {
  display: grid;
  gap: 8px;
}

.playback-share-editor form label {
  display: grid;
  gap: 4px;
}

.playback-share-editor form label > span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.playback-share-editor input,
.playback-share-editor select {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
}

.playback-share-created {
  display: grid;
  gap: 5px;
  padding: 10px;
  border: 1px solid rgba(70, 170, 112, 0.2);
  border-radius: var(--radius-sm);
  background: var(--success-soft);
}

.playback-share-created > strong,
.playback-share-created > span {
  display: block;
}

.playback-share-created > strong {
  color: var(--success);
  font-size: 12px;
  font-weight: 600;
}

.playback-share-created > span {
  color: var(--text-muted);
  font-size: 11px;
}

.playback-share-created > div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 5px;
}

.playback-share-list {
  display: grid;
  gap: 4px;
}

.playback-share-list h4 {
  margin: 0 0 2px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.playback-share-list article {
  display: grid;
  min-height: 42px;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 5px;
  padding: 5px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.playback-share-list article:last-child {
  border-bottom: 0;
}

.playback-share-list strong,
.playback-share-list article div > span {
  display: block;
}

.playback-share-list strong {
  font-size: 12px;
  font-weight: 600;
}

.playback-share-list article div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 11px;
}
</style>
