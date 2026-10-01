<script setup lang="ts">
/**
 * The system overview tab: overall health, version, database and update cards,
 * plus the per-component health list.
 *
 * Extracted from `SystemView` verbatim. Its markup only uses globally defined
 * classes (`system-page-header`, `system-overview-card`, `health-component`, …),
 * so nothing here depends on a scoped rule in the parent — that is what made the
 * move safe without touching the stylesheet.
 *
 * The storage-health readers below are only used by this tab, so they moved with
 * it rather than being passed down from the view.
 */
import { computed } from "vue"
import { useI18n } from "vue-i18n"

import {
  type HealthComponent,
  type SystemHealth,
  type SystemInfo,
  type SystemUpdateInfo
} from "../../api/system"
import { useSystemFormatters } from "../../composables/useSystemFormatters"
import { formatBytes } from "../../utils/format"
import StatusPill from "../ui/StatusPill.vue"
import UiIcon from "../ui/UiIcon.vue"
import SystemSecretStorePanel from "./SystemSecretStorePanel.vue"

const props = defineProps<{
  health: SystemHealth | null
  info: SystemInfo | null
  updateInfo: SystemUpdateInfo | null
  loading: boolean
  canViewSecretStore: boolean
}>()

const emit = defineEmits<{ refresh: [] }>()

const { t } = useI18n({ useScope: "global" })
const { stateLabel, pretty, statusVariant } = useSystemFormatters()

const healthComponents = computed(() =>
  Object.entries(props.health?.components ?? {})
)

function healthMessage(item: HealthComponent): string {
  return item.message || t("system.main.healthy")
}

interface StorageHealthTarget {
  id: string
  name: string
  path?: string
  level: "normal" | "warning" | "high" | "critical" | "unavailable"
  used_percent?: number
  free_bytes?: number
  total_bytes?: number
  warning_percent?: number
  high_percent?: number
  critical_percent?: number
  error?: string
}

/**
 * Narrow the loosely typed `target_details` payload.
 *
 * The backend reports this as an untyped list, so every field is probed rather
 * than assumed; a malformed entry is dropped instead of rendered as blanks.
 */
function storageHealthTargets(
  component: HealthComponent
): StorageHealthTarget[] {
  const value = component.details?.target_details
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is StorageHealthTarget =>
      Boolean(
        item &&
          typeof item === "object" &&
          typeof (item as StorageHealthTarget).id === "string" &&
          typeof (item as StorageHealthTarget).name === "string" &&
          typeof (item as StorageHealthTarget).level === "string"
      )
  )
}

function storageHealthSummary(item: StorageHealthTarget): string {
  if (item.level === "unavailable") {
    return pretty(item.error || "unavailable")
  }
  const used =
    typeof item.used_percent === "number"
      ? t("system.main.storageUsed", { used: item.used_percent.toFixed(1) })
      : t("system.main.usageUnavailable")
  const free =
    typeof item.free_bytes === "number"
      ? t("system.main.storageFree", { free: formatBytes(item.free_bytes) })
      : null
  return [used, free].filter(Boolean).join(" · ")
}

/** Collapse a per-target threshold level onto the component status vocabulary. */
function storageHealthStatus(
  item: StorageHealthTarget
): HealthComponent["status"] {
  if (item.level === "critical" || item.level === "unavailable") {
    return "ERROR"
  }
  if (item.level === "warning" || item.level === "high") {
    return "DEGRADED"
  }
  return "OK"
}

function storageWatermarkSummary(item: StorageHealthTarget): string | null {
  if (
    typeof item.warning_percent !== "number" ||
    typeof item.high_percent !== "number" ||
    typeof item.critical_percent !== "number"
  ) {
    return null
  }
  return t("system.main.watermarks", {
    warning: item.warning_percent,
    high: item.high_percent,
    critical: item.critical_percent
  })
}
</script>

<template>
  <header class="system-page-header">
    <div>
      <strong>{{ t("system.main.overview") }}</strong>
      <span>{{ t("system.main.coreHealth") }}</span>
    </div>
    <button
      class="button button--ghost"
      type="button"
      :disabled="loading"
      @click="emit('refresh')"
    >
      <UiIcon name="refresh" :size="14" />
      {{ t("system.main.refresh") }}
    </button>
  </header>

  <div class="system-overview-grid">
    <article class="system-overview-card system-overview-card--hero">
      <div>
        <span>{{ t("system.main.overallHealth") }}</span>
        <strong>{{ health?.status ? stateLabel(health.status) : "—" }}</strong>
      </div>
      <span
        class="system-health-orb"
        :class="`system-health-orb--${(health?.status || 'DISABLED').toLowerCase()}`"
      />
    </article>
    <article class="system-overview-card">
      <span>{{ t("system.main.version") }}</span>
      <strong>{{ info?.version || "—" }}</strong>
      <small>{{ info?.environment || "—" }}</small>
    </article>
    <article class="system-overview-card">
      <span>{{ t("system.main.database") }}</span>
      <strong>{{ pretty(info?.database_backend || "—") }}</strong>
      <small>{{ t("system.main.activeBackend") }}</small>
    </article>
    <article class="system-overview-card">
      <span>{{ t("system.main.updates") }}</span>
      <strong>{{ updateInfo?.status ? stateLabel(updateInfo.status) : t("system.main.unknown") }}</strong>
      <small>{{ updateInfo?.latest_version || t("system.main.noRemoteVersion") }}</small>
    </article>
  </div>

  <div class="system-section">
    <div class="system-section__heading">
      <strong>{{ t("system.main.components") }}</strong>
      <span>{{ t("system.main.liveHealth") }}</span>
    </div>
    <div class="health-component-grid">
      <article
        v-for="[name, component] in healthComponents"
        :key="name"
        class="health-component"
        :class="{
          'health-component--storage': name === 'storage'
        }"
      >
        <div class="health-component__title">
          <strong>{{ pretty(name) }}</strong>
          <StatusPill :variant="statusVariant(component.status)">
            {{ stateLabel(component.status) }}
          </StatusPill>
        </div>
        <p>{{ healthMessage(component) }}</p>
        <div
          v-if="name === 'storage' && storageHealthTargets(component).length"
          class="storage-health-list"
        >
          <div
            v-for="target in storageHealthTargets(component)"
            :key="target.id"
            class="storage-health-row"
          >
            <div class="storage-health-row__main">
              <strong>{{ target.name }}</strong>
              <span>{{ storageHealthSummary(target) }}</span>
            </div>
            <StatusPill :variant="statusVariant(storageHealthStatus(target))">
              {{ stateLabel(target.level) }}
            </StatusPill>
            <small v-if="storageWatermarkSummary(target)">
              {{ storageWatermarkSummary(target) }}
            </small>
          </div>
        </div>
      </article>
    </div>
  </div>

  <SystemSecretStorePanel v-if="canViewSecretStore" />
</template>
