<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"

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

function formatTime(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat(undefined, {
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
    notice.value =
      "Token created. Copy it now; the plaintext will not be shown again."
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
      `Revoke API token "${item.name}"? Existing clients will stop authenticating immediately.`
    )
  ) {
    return
  }
  error.value = null
  try {
    await revokeApiToken(item.id)
    notice.value = `${item.name} revoked.`
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
    notice.value = "Token copied to clipboard."
  } catch {
    notice.value =
      "Copy was blocked by the browser. Select the token and copy it manually."
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
        <strong>Personal API tokens</strong>
        <span>
          Bearer credentials for Home Assistant, scripts and automation.
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        Create token
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
            <th>Token</th>
            <th>Permissions</th>
            <th>Status</th>
            <th>Last used</th>
            <th>Expires</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="6">Loading tokens…</td>
          </tr>
          <tr v-else-if="!tokens.length">
            <td colspan="6">No personal API tokens.</td>
          </tr>
          <tr v-for="item in tokens" :key="item.id">
            <td>
              <strong>{{ item.name }}</strong>
              <small>Created {{ formatTime(item.created_at) }}</small>
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
                {{ status(item) }}
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
                Revoke
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <aside v-if="panelOpen" class="system-drawer">
      <header class="storage-editor__header">
        <div>
          <strong>Create API token</strong>
          <span>Plaintext is displayed exactly once</span>
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
        <strong>Save this token now</strong>
        <p>
          zero-nvr stores only its hash. Losing it requires creating a
          replacement token.
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
            Copy token
          </button>
          <button
            class="button button--primary"
            type="button"
            @click="panelOpen = false"
          >
            Done
          </button>
        </div>
      </div>

      <form
        v-else
        class="storage-editor__form"
        @submit.prevent="save"
      >
        <label>
          <span>Name</span>
          <input
            v-model="form.name"
            required
            maxlength="128"
            placeholder="Home Assistant"
          />
        </label>

        <label>
          <span>Expires after</span>
          <select v-model.number="form.expiryDays">
            <option :value="30">30 days</option>
            <option :value="90">90 days</option>
            <option :value="365">1 year</option>
            <option :value="0">Never</option>
          </select>
        </label>

        <fieldset class="system-role-list">
          <legend>Permissions</legend>
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
                Cannot exceed your current account permissions.
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
            Cancel
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? "Creating…" : "Create token" }}
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
