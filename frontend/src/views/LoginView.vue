<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import {
  completePasswordReset,
  listOidcProviders,
  requestPasswordReset,
  type OidcPublicProvider
} from "../api/auth"
import { errorMessage } from "../api/client"
import LanguageControl from "../components/ui/LanguageControl.vue"
import ThemeControl from "../components/ui/ThemeControl.vue"
import { useAuthStore } from "../stores/auth"

type AuthMode = "login" | "request-reset" | "complete-reset"

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: "global" })

const mode = ref<AuthMode>("login")
const username = ref("")
const password = ref("")
const identifier = ref("")
const resetToken = ref("")
const newPassword = ref("")
const confirmPassword = ref("")
const submitting = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const oidcProviders = ref<OidcPublicProvider[]>([])

function oidcLogin(provider: OidcPublicProvider): void {
  const redirect =
    typeof route.query.redirect === "string" &&
    route.query.redirect.startsWith("/") &&
    !route.query.redirect.startsWith("//")
      ? route.query.redirect
      : "/dashboard"
  window.location.assign(
    `/api/v1/auth/oidc/${encodeURIComponent(provider.key)}/login?next=${encodeURIComponent(redirect)}`
  )
}

onMounted(async () => {
  if (typeof route.query.oidc_error === "string") {
    error.value = t("auth.oidcFailed")
  }
  try {
    oidcProviders.value =
      await listOidcProviders()
  } catch {
    oidcProviders.value = []
  }
})

function setMode(next: AuthMode): void {
  mode.value = next
  error.value = null
  notice.value = null
}

async function submit(): Promise<void> {
  error.value = null
  notice.value = null
  submitting.value = true

  try {
    await auth.login({
      username: username.value,
      password: password.value
    })
    const redirect =
      typeof route.query.redirect === "string" &&
      route.query.redirect.startsWith("/")
        ? route.query.redirect
        : "/dashboard"
    await router.replace(redirect)
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    submitting.value = false
  }
}

async function submitResetRequest(): Promise<void> {
  error.value = null
  notice.value = null
  submitting.value = true
  try {
    await requestPasswordReset(identifier.value)
    notice.value = t("auth.resetRequestNotice")
    mode.value = "complete-reset"
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    submitting.value = false
  }
}

async function submitResetComplete(): Promise<void> {
  error.value = null
  notice.value = null
  if (newPassword.value !== confirmPassword.value) {
    error.value = t("auth.passwordsDoNotMatch")
    return
  }

  submitting.value = true
  try {
    await completePasswordReset(
      resetToken.value.trim(),
      newPassword.value
    )
    resetToken.value = ""
    newPassword.value = ""
    confirmPassword.value = ""
    mode.value = "login"
    notice.value = t("auth.resetCompleteNotice")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <LanguageControl class="auth-language-control" />
    <ThemeControl class="auth-theme-control" />

    <section class="auth-card">
      <div class="brand brand--auth">
        <div class="brand__mark">0</div>
        <div class="brand__copy">
          <strong>zero-nvr</strong>
          <span>{{ t("brand.selfHostedNvr") }}</span>
        </div>
      </div>

      <div class="auth-card__heading">
        <p class="eyebrow">{{ t("auth.controlPlane") }}</p>
        <h1>
          {{
            mode === "login"
              ? t("auth.signIn")
              : mode === "request-reset"
                ? t("auth.resetPassword")
                : t("auth.enterResetToken")
          }}
        </h1>
        <p v-if="mode === 'login'">
          {{ t("auth.signInDescription") }}
        </p>
        <p v-else-if="mode === 'request-reset'">
          {{ t("auth.resetRequestDescription") }}
        </p>
        <p v-else>
          {{ t("auth.resetTokenDescription") }}
        </p>
      </div>

      <form
        v-if="mode === 'login'"
        class="form-stack"
        @submit.prevent="submit"
      >
        <label class="field">
          <span>{{ t("auth.username") }}</span>
          <input
            v-model="username"
            autocomplete="username"
            required
            autofocus
          />
        </label>

        <label class="field">
          <span>{{ t("auth.password") }}</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <p v-if="notice" class="field-hint" role="status">{{ notice }}</p>

        <button
          class="button button--primary button--wide"
          type="submit"
          :disabled="submitting"
        >
          {{ submitting ? t("auth.signingIn") : t("auth.signIn") }}
        </button>

        <div
          v-if="oidcProviders.length"
          class="auth-oidc-providers"
        >
          <div class="auth-oidc-providers__divider">
            <span>{{ t("auth.orContinueWith") }}</span>
          </div>
          <button
            v-for="provider in oidcProviders"
            :key="provider.key"
            class="button button--ghost button--wide"
            type="button"
            @click="oidcLogin(provider)"
          >
            {{ provider.name }}
          </button>
        </div>

        <div class="auth-recovery-actions">
          <button
            class="button button--ghost button--wide"
            type="button"
            @click="setMode('request-reset')"
          >
            {{ t("auth.forgotPassword") }}
          </button>
          <button
            class="button button--ghost button--wide"
            type="button"
            @click="setMode('complete-reset')"
          >
            {{ t("auth.haveResetToken") }}
          </button>
        </div>
      </form>

      <form
        v-else-if="mode === 'request-reset'"
        class="form-stack"
        @submit.prevent="submitResetRequest"
      >
        <label class="field">
          <span>{{ t("auth.usernameOrEmail") }}</span>
          <input
            v-model="identifier"
            autocomplete="username"
            required
            autofocus
          />
        </label>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <button
          class="button button--primary button--wide"
          type="submit"
          :disabled="submitting"
        >
          {{ submitting ? t("auth.requesting") : t("auth.sendResetToken") }}
        </button>
        <button
          class="button button--ghost button--wide"
          type="button"
          @click="setMode('login')"
        >
          {{ t("auth.backToSignIn") }}
        </button>
      </form>

      <form
        v-else
        class="form-stack"
        @submit.prevent="submitResetComplete"
      >
        <p v-if="notice" class="field-hint" role="status">{{ notice }}</p>

        <label class="field">
          <span>{{ t("auth.resetToken") }}</span>
          <input
            v-model="resetToken"
            autocomplete="one-time-code"
            required
            spellcheck="false"
          />
        </label>

        <label class="field">
          <span>{{ t("auth.newPassword") }}</span>
          <input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            required
          />
        </label>

        <label class="field">
          <span>{{ t("auth.confirmPassword") }}</span>
          <input
            v-model="confirmPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            required
          />
        </label>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <button
          class="button button--primary button--wide"
          type="submit"
          :disabled="submitting"
        >
          {{ submitting ? t("auth.resetting") : t("auth.resetPassword") }}
        </button>
        <button
          class="button button--ghost button--wide"
          type="button"
          @click="setMode('login')"
        >
          {{ t("auth.backToSignIn") }}
        </button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.auth-oidc-providers {
  display: grid;
  gap: 6px;
}

.auth-oidc-providers__divider {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 8px;
}

.auth-oidc-providers__divider::before,
.auth-oidc-providers__divider::after {
  height: 1px;
  flex: 1;
  background: var(--border-subtle);
  content: "";
}
</style>
