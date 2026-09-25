<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"

import { errorMessage } from "../../api/client"
import {
  downloadRecoveryKit,
  getRecoveryKitStatus,
  type BackupPolicy,
  type RecoveryKitStatus
} from "../../api/system"
import { useAuthStore } from "../../stores/auth"
import UiIcon from "../ui/UiIcon.vue"

const props = defineProps<{
  policies: BackupPolicy[]
}>()

const auth = useAuthStore()
const { locale, t } = useI18n({ useScope: "global" })
const policyId = ref("")
const status = ref<RecoveryKitStatus | null>(null)
const passphrase = ref("")
const confirmation = ref("")
const loading = ref(false)
const generating = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const selectedPolicy = computed(
  () =>
    props.policies.find(
      (item) => item.id === policyId.value
    ) ?? null
)

function statusClass(): string {
  if (status.value?.status === "current") {
    return "status-pill--ok"
  }
  if (status.value?.status === "stale") {
    return "status-pill--error"
  }
  return "status-pill--muted"
}

function statusLabel(): string {
  const value = status.value?.status
  if (value === "current") return t("system.recoveryKit.current")
  if (value === "stale") return t("system.recoveryKit.stale")
  if (value === "never_generated") {
    return t("system.recoveryKit.notGenerated")
  }
  return t("system.recoveryKit.unknown")
}

function formatTime(value: string | null): string {
  if (!value) return t("system.recoveryKit.never")
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(new Date(value))
}

async function loadStatus(): Promise<void> {
  if (!policyId.value) {
    status.value = null
    return
  }
  loading.value = true
  error.value = null
  try {
    status.value = await getRecoveryKitStatus(
      policyId.value
    )
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function generate(): Promise<void> {
  if (
    !auth.hasPermission("system.manage") ||
    !policyId.value ||
    generating.value
  ) {
    return
  }

  const bytes = new TextEncoder().encode(
    passphrase.value
  ).length
  if (bytes < 16) {
    error.value = t("system.recoveryKit.passphraseMinimum")
    return
  }
  if (passphrase.value !== confirmation.value) {
    error.value = t("system.recoveryKit.passphraseMismatch")
    return
  }

  generating.value = true
  error.value = null
  notice.value = null
  try {
    const result = await downloadRecoveryKit(
      policyId.value,
      passphrase.value
    )
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download =
      result.filename ?? "zero-nvr-recovery-kit.znrk"
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(
      () => URL.revokeObjectURL(url),
      0
    )

    passphrase.value = ""
    confirmation.value = ""
    await loadStatus()
    notice.value = t("system.recoveryKit.downloaded")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    generating.value = false
  }
}

watch(
  () => props.policies,
  (policies) => {
    if (
      !policies.some(
        (item) => item.id === policyId.value
      )
    ) {
      policyId.value = policies[0]?.id ?? ""
    }
    void loadStatus()
  },
  { immediate: true }
)
</script>

<template>
  <div class="recovery-kit-panel">
    <div class="recovery-kit-panel__heading">
      <div>
        <strong>{{ t("system.recoveryKit.title") }}</strong>
        <span>
          {{ t("system.recoveryKit.description") }}
        </span>
      </div>
      <span
        class="status-pill"
        :class="statusClass()"
      >
        {{ loading ? t("system.recoveryKit.checking") : statusLabel() }}
      </span>
    </div>

    <div
      v-if="error"
      class="recovery-kit-panel__message recovery-kit-panel__message--error"
    >
      <UiIcon name="warning" :size="14" />
      <span>{{ error }}</span>
    </div>
    <div
      v-if="notice"
      class="recovery-kit-panel__message"
    >
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div
      v-if="policies.length"
      class="recovery-kit-panel__form"
    >
      <label>
        <span>{{ t("system.recoveryKit.backupPolicy") }}</span>
        <select
          v-model="policyId"
          :disabled="generating"
          @change="loadStatus"
        >
          <option
            v-for="policy in policies"
            :key="policy.id"
            :value="policy.id"
          >
            {{ policy.name }}
          </option>
        </select>
      </label>

      <div class="recovery-kit-panel__meta">
        <div>
          <span>{{ t("system.recoveryKit.lastGenerated") }}</span>
          <strong>
            {{ formatTime(status?.generated_at ?? null) }}
          </strong>
        </div>
        <div>
          <span>{{ t("system.recoveryKit.kitVersion") }}</span>
          <strong>
            {{ status?.app_version || "—" }}
          </strong>
        </div>
      </div>

      <template v-if="auth.hasPermission('system.manage')">
        <div class="recovery-kit-panel__passwords">
          <label>
            <span>{{ t("system.recoveryKit.passphrase") }}</span>
            <input
              v-model="passphrase"
              type="password"
              autocomplete="new-password"
              :placeholder="t('system.recoveryKit.atLeast16')"
            />
          </label>
          <label>
            <span>{{ t("system.recoveryKit.confirmPassphrase") }}</span>
            <input
              v-model="confirmation"
              type="password"
              autocomplete="new-password"
            />
          </label>
        </div>

        <div class="recovery-kit-panel__actions">
          <span>
            {{
              status?.status === "stale"
                ? t("system.recoveryKit.staleHint")
                : t("system.recoveryKit.storageHint")
            }}
          </span>
          <button
            class="button button--primary"
            type="button"
            :disabled="
              generating ||
              !selectedPolicy ||
              !passphrase ||
              !confirmation
            "
            @click="generate"
          >
            <UiIcon name="download" :size="14" />
            {{
              generating
                ? t("system.recoveryKit.encrypting")
                : status?.status === "stale"
                  ? t("system.recoveryKit.regenerate")
                  : t("system.recoveryKit.generate")
            }}
          </button>
        </div>
      </template>
    </div>

    <div
      v-else
      class="recovery-kit-panel__empty"
    >
      {{ t("system.recoveryKit.noPolicy") }}
    </div>
  </div>
</template>

<style scoped>
.recovery-kit-panel {
  display: grid;
  gap: 9px;
  padding: 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.recovery-kit-panel__heading,
.recovery-kit-panel__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.recovery-kit-panel__heading strong,
.recovery-kit-panel__heading span {
  display: block;
}

.recovery-kit-panel__heading strong {
  font-size: 9px;
}

.recovery-kit-panel__heading div > span,
.recovery-kit-panel__actions > span,
.recovery-kit-panel__empty {
  max-width: 680px;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.recovery-kit-panel__form,
.recovery-kit-panel label {
  display: grid;
  gap: 4px;
}

.recovery-kit-panel label > span,
.recovery-kit-panel__meta span {
  color: var(--text-muted);
  font-size: 7px;
  font-weight: 650;
  text-transform: uppercase;
}

.recovery-kit-panel select,
.recovery-kit-panel input {
  width: 100%;
  min-height: 30px;
  padding: 0 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: 8px;
}

.recovery-kit-panel select:focus,
.recovery-kit-panel input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.recovery-kit-panel__meta,
.recovery-kit-panel__passwords {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.recovery-kit-panel__meta > div {
  padding: 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
}

.recovery-kit-panel__meta strong {
  display: block;
  margin-top: 4px;
  font-size: 8px;
}

.recovery-kit-panel__message {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 7px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 8px;
  line-height: 1.45;
}

.recovery-kit-panel__message--error {
  color: var(--danger);
}

.recovery-kit-panel__actions {
  align-items: flex-end;
}

@media (max-width: 760px) {
  .recovery-kit-panel__heading,
  .recovery-kit-panel__actions {
    align-items: stretch;
    flex-direction: column;
  }

  .recovery-kit-panel__meta,
  .recovery-kit-panel__passwords {
    grid-template-columns: 1fr;
  }

  .recovery-kit-panel__actions .button {
    width: 100%;
  }
}
</style>
