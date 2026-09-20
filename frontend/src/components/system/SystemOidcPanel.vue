<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"

import { errorMessage } from "../../api/client"
import {
  createOidcProvider,
  deleteOidcProvider,
  listOidcProviderConfigs,
  listRoles,
  updateOidcProvider,
  type OidcProvider,
  type Role
} from "../../api/system"
import UiIcon from "../ui/UiIcon.vue"

const providers = ref<OidcProvider[]>([])
const roles = ref<Role[]>([])
const loading = ref(false)
const saving = ref(false)
const editorOpen = ref(false)
const editing = ref<OidcProvider | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const form = reactive({
  key: "",
  name: "",
  enabled: true,
  issuer: "",
  clientId: "",
  clientSecret: "",
  autoProvision: false,
  emailLinking: false,
  defaultRoleIds: [] as string[]
})

const callbackUrl = computed(() => {
  const key = editing.value?.key || form.key.trim().toLowerCase()
  if (!key) return ""
  return (
    window.location.origin +
    "/api/v1/auth/oidc/" +
    encodeURIComponent(key) +
    "/callback"
  )
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    ;[providers.value, roles.value] = await Promise.all([
      listOidcProviderConfigs(),
      listRoles()
    ])
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  form.key = ""
  form.name = ""
  form.enabled = true
  form.issuer = ""
  form.clientId = ""
  form.clientSecret = ""
  form.autoProvision = false
  form.emailLinking = false
  form.defaultRoleIds = []
  error.value = null
  notice.value = null
  editorOpen.value = true
}

function openEdit(item: OidcProvider): void {
  editing.value = item
  form.key = item.key
  form.name = item.name
  form.enabled = item.enabled
  form.issuer = item.issuer
  form.clientId = item.client_id
  form.clientSecret = ""
  form.autoProvision = item.auto_provision
  form.emailLinking = item.email_linking
  form.defaultRoleIds = [...item.default_role_ids]
  error.value = null
  notice.value = null
  editorOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    if (editing.value) {
      const changes: {
        name: string
        enabled: boolean
        issuer: string
        client_id: string
        auto_provision: boolean
        email_linking: boolean
        default_role_ids: string[]
        client_secret?: string
      } = {
        name: form.name.trim(),
        enabled: form.enabled,
        issuer: form.issuer.trim(),
        client_id: form.clientId.trim(),
        auto_provision: form.autoProvision,
        email_linking: form.emailLinking,
        default_role_ids: [...form.defaultRoleIds]
      }
      if (form.clientSecret) {
        changes.client_secret = form.clientSecret
      }
      await updateOidcProvider(editing.value.key, changes)
      notice.value = form.name.trim() + " updated."
    } else {
      await createOidcProvider({
        key: form.key.trim().toLowerCase(),
        name: form.name.trim(),
        enabled: form.enabled,
        issuer: form.issuer.trim(),
        client_id: form.clientId.trim(),
        client_secret: form.clientSecret,
        auto_provision: form.autoProvision,
        email_linking: form.emailLinking,
        default_role_ids: [...form.defaultRoleIds]
      })
      notice.value = form.name.trim() + " created."
    }
    form.clientSecret = ""
    editorOpen.value = false
    editing.value = null
    await load()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function remove(item: OidcProvider): Promise<void> {
  if (
    !window.confirm(
      'Delete OIDC provider "' +
        item.name +
        '"? Existing linked identities remain in zero-nvr, but this provider can no longer sign in.'
    )
  ) {
    return
  }

  error.value = null
  try {
    await deleteOidcProvider(item.key)
    notice.value = item.name + " deleted."
    await load()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="oidc-panel">
    <header class="system-page-header">
      <div>
        <strong>OpenID Connect</strong>
        <span>
          External SSO through Authentik, Authelia, Keycloak or another OIDC provider.
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        Add provider
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

    <div v-if="loading" class="empty-state">
      Loading OIDC providers…
    </div>

    <div v-else-if="!providers.length" class="empty-state empty-state--large">
      <strong>No OIDC providers configured</strong>
      <p>
        Local authentication and host-local recovery remain available even when SSO is enabled.
      </p>
    </div>

    <div v-else class="oidc-provider-grid">
      <article
        v-for="item in providers"
        :key="item.id"
        class="oidc-provider-card"
      >
        <div class="oidc-provider-card__main">
          <div>
            <strong>{{ item.name }}</strong>
            <span>{{ item.issuer }}</span>
          </div>
          <span
            class="status-pill"
            :class="
              item.enabled
                ? 'status-pill--ok'
                : 'status-pill--muted'
            "
          >
            {{ item.enabled ? "Enabled" : "Disabled" }}
          </span>
        </div>

        <dl>
          <div>
            <dt>Key</dt>
            <dd>{{ item.key }}</dd>
          </div>
          <div>
            <dt>Client</dt>
            <dd>{{ item.client_id }}</dd>
          </div>
          <div>
            <dt>Provisioning</dt>
            <dd>
              {{
                item.auto_provision
                  ? item.default_role_ids.length + " default role(s)"
                  : "Link existing users only"
              }}
            </dd>
          </div>
          <div>
            <dt>Email linking</dt>
            <dd>{{ item.email_linking ? "Verified email allowed" : "Off" }}</dd>
          </div>
        </dl>

        <footer>
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="openEdit(item)"
          >
            Edit
          </button>
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="remove(item)"
          >
            Delete
          </button>
        </footer>
      </article>
    </div>

    <aside v-if="editorOpen" class="system-drawer">
      <header class="storage-editor__header">
        <div>
          <strong>
            {{ editing ? "Edit OIDC provider" : "Add OIDC provider" }}
          </strong>
          <span>Authorization Code + OpenID Connect discovery</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="editorOpen = false"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form
        class="storage-editor__form"
        @submit.prevent="save"
      >
        <label>
          <span>Provider key</span>
          <input
            v-model="form.key"
            required
            maxlength="64"
            pattern="[a-z0-9][a-z0-9_-]{0,63}"
            :disabled="Boolean(editing)"
            placeholder="authentik"
          />
          <small>
            Stable URL identifier. It cannot be changed after creation.
          </small>
        </label>

        <label>
          <span>Display name</span>
          <input
            v-model="form.name"
            required
            maxlength="128"
            placeholder="Authentik"
          />
        </label>

        <label>
          <span>Issuer URL</span>
          <input
            v-model="form.issuer"
            required
            type="url"
            placeholder="https://id.example.com/application/o/zero-nvr/"
          />
          <small>
            HTTPS is required except localhost/loopback development.
          </small>
        </label>

        <label>
          <span>Client ID</span>
          <input
            v-model="form.clientId"
            required
            autocomplete="off"
          />
        </label>

        <label>
          <span>Client secret</span>
          <input
            v-model="form.clientSecret"
            type="password"
            :required="!editing"
            autocomplete="new-password"
          />
          <small>
            {{
              editing
                ? "Leave blank to preserve the encrypted client secret."
                : "Stored encrypted through zero-nvr SecretStore."
            }}
          </small>
        </label>

        <label v-if="callbackUrl">
          <span>Redirect / callback URL</span>
          <input
            :value="callbackUrl"
            readonly
          />
          <small>
            Register this exact URL in the OIDC provider.
          </small>
        </label>

        <label class="storage-check">
          <input
            v-model="form.enabled"
            type="checkbox"
          />
          <span>Provider enabled</span>
        </label>

        <label class="storage-check">
          <input
            v-model="form.emailLinking"
            type="checkbox"
          />
          <span>
            Allow verified-email linking
            <small>
              Only email_verified=true may link an existing local user.
            </small>
          </span>
        </label>

        <label class="storage-check">
          <input
            v-model="form.autoProvision"
            type="checkbox"
          />
          <span>
            Auto-provision new users
            <small>
              New users receive only the default roles selected below.
            </small>
          </span>
        </label>

        <fieldset class="system-role-list">
          <legend>Default roles</legend>
          <label
            v-for="role in roles"
            :key="role.id"
          >
            <input
              v-model="form.defaultRoleIds"
              type="checkbox"
              :value="role.id"
            />
            <span>
              <strong>{{ role.name }}</strong>
              <small>{{ role.description || "No description" }}</small>
            </span>
          </label>
        </fieldset>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="editorOpen = false"
          >
            Cancel
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{
              saving
                ? "Saving…"
                : editing
                  ? "Save provider"
                  : "Create provider"
            }}
          </button>
        </div>
      </form>
    </aside>
  </section>
</template>

<style scoped>
.oidc-panel {
  display: grid;
  gap: 12px;
}

.oidc-provider-grid {
  display: grid;
  gap: 8px;
}

.oidc-provider-card {
  display: grid;
  gap: 10px;
  padding: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.oidc-provider-card__main,
.oidc-provider-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.oidc-provider-card__main > div > strong,
.oidc-provider-card__main > div > span {
  display: block;
}

.oidc-provider-card__main > div > strong {
  font-size: 10px;
}

.oidc-provider-card__main > div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.oidc-provider-card dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.oidc-provider-card dl > div {
  min-width: 0;
  padding: 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.oidc-provider-card dt {
  color: var(--text-muted);
  font-size: 7px;
}

.oidc-provider-card dd {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--text-secondary);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.oidc-provider-card footer {
  justify-content: flex-end;
}

@media (max-width: 900px) {
  .oidc-provider-card dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
