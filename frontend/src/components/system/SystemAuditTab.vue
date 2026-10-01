<script setup lang="ts">
/**
 * Audit log tab: filter toolbar, result list and cursor pagination.
 *
 * Extracted from `SystemView`, together with the `audit-toolbar` / `audit-filter`
 * / `audit-empty` / `audit-load-more` rules that were scoped to the view. Those
 * rules style elements that moved here, so they had to travel with the markup;
 * `audit-list*` was already global and stayed in the shared sheet.
 *
 * The view owns the filter object and the cursor state (it refetches on
 * filter change and appends pages), so they are passed in and the tab asks for a
 * reload through events.
 */
import { useI18n } from "vue-i18n"

import { type AuditEvent } from "../../api/system"
import { useSystemFormatters } from "../../composables/useSystemFormatters"
import StatusPill from "../ui/StatusPill.vue"
import UiIcon from "../ui/UiIcon.vue"

export interface AuditFilters {
  period: "24h" | "7d" | "30d" | "all"
  action: string
  resourceType: string
  result: string
}

defineProps<{
  auditEvents: AuditEvent[]
  auditFilters: AuditFilters
  auditLoading: boolean
  auditLoadingMore: boolean
  auditNextCursor: string | null
}>()

const emit = defineEmits<{
  reload: []
  loadMore: []
  resetFilters: []
}>()

const { t } = useI18n({ useScope: "global" })
const { formatTime, pretty, stateLabel, statusVariant } = useSystemFormatters()
</script>

<template>
  <header class="system-page-header">
    <div>
      <strong>{{ t("system.main.audit") }}</strong>
      <span>{{ t("system.main.auditDesc") }}</span>
    </div>
    <button
      class="button button--ghost"
      type="button"
      :disabled="auditLoading"
      @click="emit('reload')"
    >
      <UiIcon name="refresh" :size="14" />
      {{ auditLoading ? t("system.main.refreshing") : t("system.main.refresh") }}
    </button>
  </header>

  <div class="audit-toolbar">
    <label class="audit-filter">
      <span>{{ t("system.main.period") }}</span>
      <select
        v-model="auditFilters.period"
        @change="emit('reload')"
      >
        <option value="24h">{{ t("system.main.last24h") }}</option>
        <option value="7d">{{ t("system.main.last7d") }}</option>
        <option value="30d">{{ t("system.main.last30d") }}</option>
        <option value="all">{{ t("system.main.allTime") }}</option>
      </select>
    </label>

    <label class="audit-filter">
      <span>{{ t("system.main.action") }}</span>
      <input
        v-model="auditFilters.action"
        placeholder="camera.update"
        @keydown.enter="emit('reload')"
      />
    </label>

    <label class="audit-filter">
      <span>{{ t("system.main.resource") }}</span>
      <input
        v-model="auditFilters.resourceType"
        placeholder="camera"
        @keydown.enter="emit('reload')"
      />
    </label>

    <label class="audit-filter">
      <span>{{ t("system.main.result") }}</span>
      <select
        v-model="auditFilters.result"
        @change="emit('reload')"
      >
        <option value="">{{ t("system.main.allResults") }}</option>
        <option value="success">{{ t("system.main.success") }}</option>
        <option value="failed">{{ t("system.main.failed") }}</option>
        <option value="denied">{{ t("system.main.denied") }}</option>
      </select>
    </label>

    <div class="audit-toolbar__actions">
      <button
        class="button button--ghost button--compact"
        type="button"
        @click="emit('resetFilters')"
      >
        {{ t("system.main.clear") }}
      </button>
      <button
        class="button button--primary button--compact"
        type="button"
        :disabled="auditLoading"
        @click="emit('reload')"
      >
        {{ t("system.main.apply") }}
      </button>
    </div>
  </div>

  <div
    v-if="auditLoading && !auditEvents.length"
    class="audit-empty"
  >
    {{ t("system.main.loadingAudit") }}
  </div>

  <div
    v-else-if="!auditEvents.length"
    class="audit-empty"
  >
    {{ t("system.main.noAudit") }}
  </div>

  <div v-else class="audit-list">
    <article v-for="item in auditEvents" :key="item.id">
      <span class="audit-list__icon">
        <UiIcon name="audit" :size="15" />
      </span>
      <div class="audit-list__main">
        <strong>{{ pretty(item.action) }}</strong>
        <span>
          {{ pretty(item.resource_type) }}
          <template v-if="item.source_ip"> · {{ item.source_ip }}</template>
          <template v-if="item.reason"> · {{ pretty(item.reason) }}</template>
        </span>
      </div>
      <StatusPill :variant="statusVariant(item.result)">
        {{ stateLabel(item.result) }}
      </StatusPill>
      <time>{{ formatTime(item.occurred_at) }}</time>
    </article>
  </div>

  <button
    v-if="auditNextCursor"
    class="audit-load-more"
    type="button"
    :disabled="auditLoadingMore"
    @click="emit('loadMore')"
  >
    {{
      auditLoadingMore
        ? t("system.main.loading")
        : t("system.main.loadMore")
    }}
  </button>
</template>

<style scoped>
.audit-toolbar {
  display: grid;
  grid-template-columns:
    minmax(120px, 0.7fr)
    minmax(160px, 1fr)
    minmax(150px, 1fr)
    minmax(130px, 0.8fr)
    auto;
  gap: 10px;
  align-items: end;
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid var(--uf-border);
  border-radius: 14px;
  background: var(--uf-bg-card);
}

.audit-filter {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.audit-filter > span {
  color: var(--uf-text-muted);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.audit-filter input,
.audit-filter select {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid var(--uf-border-strong);
  border-radius: 8px;
  outline: 0;
  background: var(--uf-bg-input);
  color: var(--uf-text-primary);
  font: inherit;
  font-size: 12px;
}

.audit-filter input:focus,
.audit-filter select:focus {
  border-color: var(--uf-accent);
  box-shadow: 0 0 0 3px var(--uf-accent-glow);
}

.audit-toolbar__actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.audit-empty {
  padding: 36px 16px;
  color: var(--uf-text-muted);
  font-size: 13px;
  text-align: center;
}

.audit-load-more {
  width: 100%;
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--uf-border);
  border-radius: 10px;
  background: var(--uf-bg-card-sub);
  color: var(--uf-text-primary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.audit-load-more:hover:not(:disabled) {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

@media (max-width: 980px) {
  .audit-toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .audit-toolbar__actions {
    grid-column: 1 / -1;
  }
}
</style>
