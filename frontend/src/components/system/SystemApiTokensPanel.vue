<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import { useI18n } from "vue-i18n"

import {
  createApiToken,
  listApiTokens,
  revokeApiToken,
  type CreatedPersonalApiToken,
  type PersonalApiToken
} from "../../api/auth"
import { errorMessage } from "../../api/client"
import { useAuthStore } from "../../stores/auth"
import UiIcon from "../ui/UiIcon.vue"

const auth = useAuthStore()
const { locale, t } = useI18n({ useScope: "global" })
const tokens = ref<PersonalApiToken[]>([])
const loading = ref(false)
const saving = ref(false)
const panelOpen = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const created = ref<CreatedPersonalApiToken | null>(null)

const form = reactive({
  name: "",
  expiryDays: 90,
  permissions: [] as string[]
})

const availablePermissions = computed(() =>
  [...(auth.user?.permissions ?? [])].sort()
)

function status(item: PersonalApiToken): string {
  if (item.revoked_at) return "REVOKED"
  if (
    item.expires_at &&
    new Date(item.expires_at).getTime() <= Date.now()
  ) {
    return "EXPIRED"
  }
  return "ACTIVE"
}

function statusLabel(value: string): string {
  if (value === "REVOKED") return t("system.apiTokens.revoked")
  if (value === "EXPIRED") return t("system.apiTokens.expired")
  return t("system.apiTokens.active")
}

function formatTime(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value))
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    tokens.value = await listApiTokens()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  form.name = ""
  form.expiryDays = 90
  form.permissions = [...availablePermissions.value]
  created.value = null
  notice.value = null
  error.value = null
  panelOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    const expiresAt =
      form.expiryDays > 0
        ? new Date(
            Date.now() +
              form.expiryDays * 24 * 60 * 60 * 1000
          ).toISOString()
        : null
    created.value = await createApiToken({
      name: form.name.trim(),
      permissions: [...form.permissions],
      expires_at: expiresAt
    })
    notice.value = t("system.apiTokens.createdNotice")
    await load()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function revoke(item: PersonalApiToken): Promise<void> {
  if (
    !window.confirm(
      t("system.apiTokens.revokeConfirm", { name: item.name })
    )
  ) {
    return
  }
  error.value = null
  try {
    await revokeApiToken(item.id)
    notice.value = t("system.apiTokens.revokedNotice", { name: item.name })
    await load()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function copyCreated(): Promise<void> {
  if (!created.value) return
  try {
    await navigator.clipboard.writeText(
      created.value.token
    )
    notice.value = t("system.apiTokens.copied")
  } catch {
    notice.value = t("system.apiTokens.copyBlocked")
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="api-token-panel">
    <header class="system-page-header">
      <div>
        <strong>{{ t("system.apiTokens.title") }}</strong>
        <span>
          {{ t("system.apiTokens.description") }}
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        {{ t("system.apiTokens.createToken") }}
      </button>
    </header>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>
    <div v-if="notice" class="storage-notice">
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div class="system-table-wrap">
      <table class="system-table">
        <thead>
          <tr>
            <th>{{ t("system.apiTokens.token") }}</th>
            <th>{{ t("system.apiTokens.permissions") }}</th>
            <th>{{ t("system.apiTokens.status") }}</th>
            <th>{{ t("system.apiTokens.lastUsed") }}</th>
            <th>{{ t("system.apiTokens.expires") }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="6">{{ t("system.apiTokens.loading") }}</td>
          </tr>
          <tr v-else-if="!tokens.length">
            <td colspan="6">{{ t("system.apiTokens.empty") }}</td>
          </tr>
          <tr v-for="item in tokens" :key="item.id">
            <td>
              <strong>{{ item.name }}</strong>
              <small>{{ t("system.apiTokens.createdAt", { time: formatTime(item.created_at) }) }}</small>
            </td>
            <td>
              <span class="api-token-panel__permission-count">
                {{ item.permissions.length }}
              </span>
            </td>
            <td>
              <span
                class="status-pill"
                :class="
                  status(item) === 'ACTIVE'
                    ? 'status-pill--ok'
                    : 'status-pill--muted'
                "
              >
                {{ statusLabel(status(item)) }}
              </span>
            </td>
            <td>{{ formatTime(item.last_used_at) }}</td>
            <td>{{ formatTime(item.expires_at) }}</td>
            <td>
              <button
                v-if="status(item) === 'ACTIVE'"
                class="button button--ghost button--compact"
                type="button"
                @click="revoke(item)"
              >
                {{ t("system.apiTokens.revoke") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <aside v-if="panelOpen" class="system-drawer">
      <header class="storage-editor__header">
        <div>
          <strong>{{ t("system.apiTokens.createTitle") }}</strong>
          <span>{{ t("system.apiTokens.plaintextOnce") }}</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="panelOpen = false"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <div v-if="created" class="api-token-panel__created">
        <strong>{{ t("system.apiTokens.saveNow") }}</strong>
        <p>
          {{ t("system.apiTokens.hashHint") }}
        </p>
        <textarea
          :value="created.token"
          rows="4"
          readonly
          spellcheck="false"
        />
        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="copyCreated"
          >
            {{ t("system.apiTokens.copyToken") }}
          </button>
          <button
            class="button button--primary"
            type="button"
            @click="panelOpen = false"
          >
            {{ t("system.apiTokens.done") }}
          </button>
        </div>
      </div>

      <form
        v-else
        class="storage-editor__form"
        @submit.prevent="save"
      >
        <label>
          <span>{{ t("system.apiTokens.name") }}</span>
          <input
            v-model="form.name"
            required
            maxlength="128"
            :placeholder="t('system.apiTokens.homeAssistant')"
          />
        </label>

        <label>
          <span>{{ t("system.apiTokens.expiresAfter") }}</span>
          <select v-model.number="form.expiryDays">
            <option :value="30">{{ t("system.apiTokens.days30") }}</option>
            <option :value="90">{{ t("system.apiTokens.days90") }}</option>
            <option :value="365">{{ t("system.apiTokens.year1") }}</option>
            <option :value="0">{{ t("system.apiTokens.never") }}</option>
          </select>
        </label>

        <fieldset class="system-role-list">
          <legend>{{ t("system.apiTokens.permissions") }}</legend>
          <label
            v-for="permission in availablePermissions"
            :key="permission"
          >
            <input
              v-model="form.permissions"
              type="checkbox"
              :value="permission"
            />
            <span>
              <strong>{{ permission }}</strong>
              <small>
                {{ t("system.apiTokens.permissionHint") }}
              </small>
            </span>
          </label>
        </fieldset>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="panelOpen = false"
          >
            {{ t("system.apiTokens.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? t("system.apiTokens.creating") : t("system.apiTokens.createToken") }}
          </button>
        </div>
      </form>
    </aside>
  </section>
</template>

<style scoped>
.api-token-panel {
  display: grid;
  gap: 12px;
}

.api-token-panel__permission-count {
  color: var(--text-secondary);
  font-size: 8px;
}

.api-token-panel__created {
  display: grid;
  gap: 9px;
  padding: 12px;
}

.api-token-panel__created > strong {
  font-size: 10px;
}

.api-token-panel__created p {
  margin: 0;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.api-token-panel__created textarea {
  min-height: 86px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 8px;
  resize: vertical;
}
</style>
