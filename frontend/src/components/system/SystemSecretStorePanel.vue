<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import { errorMessage } from "../../api/client"
import {
  getSecretStoreHealth,
  rotateSecretStore,
  type SecretStoreHealth
} from "../../api/system"
import { useAuthStore } from "../../stores/auth"
import UiIcon from "../ui/UiIcon.vue"

const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })
const health = ref<SecretStoreHealth | null>(null)
const loading = ref(false)
const rotating = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

function statusClass(
  value: SecretStoreHealth["status"]
): string {
  if (value === "OK") return "status-pill--ok"
  if (value === "ERROR") return "status-pill--error"
  return "status-pill--muted"
}

function statusMessage(
  value: SecretStoreHealth
): string {
  if (value.status === "ERROR") {
    return t("system.secretStore.unreadableMessage", {
      count: value.unreadable_records
    })
  }
  if (value.status === "ROTATION_REQUIRED") {
    return t("system.secretStore.rotationRequiredMessage", {
      count: value.stale_records
    })
  }
  return t("system.secretStore.allCurrent")
}

function statusLabel(value: SecretStoreHealth["status"]): string {
  if (value === "OK") return t("system.secretStore.ok")
  if (value === "ROTATION_REQUIRED") return t("system.secretStore.rotationRequired")
  return t("system.secretStore.error")
}

async function load(): Promise<void> {
  if (!auth.hasPermission("system.view")) return

  loading.value = true
  error.value = null
  try {
    health.value = await getSecretStoreHealth()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function rotate(): Promise<void> {
  if (
    !auth.hasPermission("system.manage") ||
    !health.value?.rotation_ready ||
    rotating.value
  ) {
    return
  }

  const staleRecords = health.value.stale_records
  if (
    !window.confirm(
      t("system.secretStore.rotateConfirm", { count: staleRecords })
    )
  ) {
    return
  }

  rotating.value = true
  error.value = null
  notice.value = null
  try {
    const result = await rotateSecretStore()
    health.value = result.health
    notice.value = t("system.secretStore.rotatedNotice", {
      count: result.rotated_records
    })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    rotating.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="secret-store-panel">
    <header class="secret-store-panel__header">
      <div>
        <strong>{{ t("system.secretStore.title") }}</strong>
        <span>
          {{ t("system.secretStore.description") }}
        </span>
      </div>
      <button
        class="button button--ghost button--compact"
        type="button"
        :disabled="loading || rotating"
        @click="load"
      >
        <UiIcon name="refresh" :size="13" />
        {{ loading ? t("system.secretStore.refreshing") : t("system.secretStore.refresh") }}
      </button>
    </header>

    <div v-if="error" class="secret-store-panel__message secret-store-panel__message--error">
      <UiIcon name="warning" :size="14" />
      <span>{{ error }}</span>
    </div>

    <div v-if="notice" class="secret-store-panel__message">
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div v-if="health" class="secret-store-panel__body">
      <div class="secret-store-panel__status">
        <div>
          <span>{{ t("system.secretStore.keyringHealth") }}</span>
          <strong>{{ statusMessage(health) }}</strong>
        </div>
        <span
          class="status-pill"
          :class="statusClass(health.status)"
        >
          {{ statusLabel(health.status) }}
        </span>
      </div>

      <dl class="secret-store-panel__metrics">
        <div>
          <dt>{{ t("system.secretStore.encryptedRecords") }}</dt>
          <dd>{{ health.total_records }}</dd>
        </div>
        <div>
          <dt>{{ t("system.secretStore.activeKey") }}</dt>
          <dd>{{ health.current_records }}</dd>
        </div>
        <div>
          <dt>{{ t("system.secretStore.previousKey") }}</dt>
          <dd>{{ health.stale_records }}</dd>
        </div>
        <div>
          <dt>{{ t("system.secretStore.unreadable") }}</dt>
          <dd>{{ health.unreadable_records }}</dd>
        </div>
      </dl>

      <div class="secret-store-panel__details">
        <div>
          <span>{{ t("system.secretStore.primaryKeyId") }}</span>
          <code>{{ health.primary_key_id }}</code>
        </div>
        <div>
          <span>{{ t("system.secretStore.previousKeysConfigured") }}</span>
          <strong>{{ health.previous_key_count }}</strong>
        </div>
      </div>

      <div class="secret-store-panel__workflow">
        <strong>{{ t("system.secretStore.rotationSequence") }}</strong>
        <ol>
          <li>
            {{ t("system.secretStore.step1Prefix") }}
            <code>ZERO_NVR_SECRET_KEY</code>
            {{ t("system.secretStore.step1Middle") }}
            <code>ZERO_NVR_SECRET_KEY_PREVIOUS</code>{{ t("system.secretStore.step1Suffix") }}
          </li>
          <li>
            {{ t("system.secretStore.step2Prefix") }}
            <strong>{{ t("system.secretStore.rotationRequired") }}</strong>
            {{ t("system.secretStore.step2Suffix") }}
          </li>
          <li>
            {{ t("system.secretStore.step3") }}
          </li>
        </ol>
      </div>

      <div
        v-if="health.status === 'ERROR'"
        class="secret-store-panel__warning"
      >
        <UiIcon name="warning" :size="14" />
        <span>
          {{ t("system.secretStore.rotationBlocked") }}
        </span>
      </div>

      <div class="secret-store-panel__actions">
        <span v-if="!auth.hasPermission('system.manage')">
          {{ t("system.secretStore.permissionRequired") }}
        </span>
        <span
          v-else-if="
            health.status === 'OK' &&
            health.previous_key_count > 0
          "
        >
          {{ t("system.secretStore.currentHint") }}
        </span>
        <span
          v-else-if="
            health.status === 'ROTATION_REQUIRED' &&
            !health.rotation_ready
          "
        >
          {{ t("system.secretStore.unsafe") }}
        </span>

        <button
          v-if="auth.hasPermission('system.manage')"
          class="button button--primary"
          type="button"
          :disabled="rotating || !health.rotation_ready"
          @click="rotate"
        >
          <UiIcon name="shield" :size="14" />
          {{ rotating ? t("system.secretStore.rotating") : t("system.secretStore.rotate") }}
        </button>
      </div>
    </div>

    <div
      v-else-if="loading"
      class="secret-store-panel__empty"
    >
      {{ t("system.secretStore.checking") }}
    </div>
  </section>
</template>

<style scoped>
.secret-store-panel {
  display: grid;
  gap: 10px;
  margin-top: 12px;
  padding: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.secret-store-panel__header,
.secret-store-panel__status,
.secret-store-panel__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.secret-store-panel__header > div,
.secret-store-panel__status > div {
  min-width: 0;
}

.secret-store-panel__header strong,
.secret-store-panel__header span,
.secret-store-panel__status span,
.secret-store-panel__status strong {
  display: block;
}

.secret-store-panel__header strong {
  font-size: 10px;
}

.secret-store-panel__header div > span,
.secret-store-panel__status div > span,
.secret-store-panel__actions > span,
.secret-store-panel__empty {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.secret-store-panel__status {
  padding: 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.secret-store-panel__status strong {
  margin-top: 3px;
  max-width: 760px;
  color: var(--text-secondary);
  font-size: 8px;
  font-weight: 500;
  line-height: 1.45;
}

.secret-store-panel__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
  margin: 0;
}

.secret-store-panel__metrics > div,
.secret-store-panel__details > div {
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.secret-store-panel__metrics dt,
.secret-store-panel__details span {
  color: var(--text-muted);
  font-size: 7px;
  text-transform: uppercase;
}

.secret-store-panel__metrics dd {
  margin: 4px 0 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
}

.secret-store-panel__details {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 0.35fr);
  gap: 7px;
}

.secret-store-panel__details code,
.secret-store-panel__details strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 8px;
}

.secret-store-panel__workflow {
  padding: 9px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.secret-store-panel__workflow > strong {
  font-size: 8px;
}

.secret-store-panel__workflow ol {
  display: grid;
  gap: 5px;
  margin: 7px 0 0;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 8px;
  line-height: 1.5;
}

.secret-store-panel__workflow code {
  color: var(--text-primary);
  font-size: 8px;
}

.secret-store-panel__message,
.secret-store-panel__warning {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 8px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 8px;
  line-height: 1.45;
}

.secret-store-panel__message--error,
.secret-store-panel__warning {
  color: var(--danger);
}

.secret-store-panel__actions {
  align-items: flex-end;
}

.secret-store-panel__actions > span {
  max-width: 620px;
}

@media (max-width: 760px) {
  .secret-store-panel__header,
  .secret-store-panel__status,
  .secret-store-panel__actions {
    align-items: stretch;
    flex-direction: column;
  }

  .secret-store-panel__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .secret-store-panel__details {
    grid-template-columns: 1fr;
  }

  .secret-store-panel__actions .button {
    width: 100%;
  }
}
</style>
