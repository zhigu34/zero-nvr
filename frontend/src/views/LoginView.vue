<script setup lang="ts">
import { ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import {
  completePasswordReset,
  requestPasswordReset
} from "../api/auth"
import { errorMessage } from "../api/client"
import ThemeControl from "../components/ui/ThemeControl.vue"
import { useAuthStore } from "../stores/auth"

type AuthMode = "login" | "request-reset" | "complete-reset"

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

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
    notice.value =
      "If the account exists and password reset email is configured, a one-time token has been sent."
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
    error.value = "Passwords do not match."
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
    notice.value =
      "Password reset complete. Sign in with your new password."
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <ThemeControl class="auth-theme-control" />

    <section class="auth-card">
      <div class="brand brand--auth">
        <div class="brand__mark">0</div>
        <div class="brand__copy">
          <strong>zero-nvr</strong>
          <span>self-hosted NVR</span>
        </div>
      </div>

      <div class="auth-card__heading">
        <p class="eyebrow">Control plane</p>
        <h1>
          {{
            mode === "login"
              ? "Sign in"
              : mode === "request-reset"
                ? "Reset password"
                : "Enter reset token"
          }}
        </h1>
        <p v-if="mode === 'login'">
          Use your local zero-nvr account. Camera credentials never
          leave the control plane.
        </p>
        <p v-else-if="mode === 'request-reset'">
          Enter your username or email. The response is intentionally
          the same whether or not the account exists.
        </p>
        <p v-else>
          Paste the one-time token from your reset email and choose a
          new password.
        </p>
      </div>

      <form
        v-if="mode === 'login'"
        class="form-stack"
        @submit.prevent="submit"
      >
        <label class="field">
          <span>Username</span>
          <input
            v-model="username"
            autocomplete="username"
            required
            autofocus
          />
        </label>

        <label class="field">
          <span>Password</span>
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
          {{ submitting ? "Signing in…" : "Sign in" }}
        </button>

        <div class="auth-recovery-actions">
          <button
            class="button button--ghost button--wide"
            type="button"
            @click="setMode('request-reset')"
          >
            Forgot password
          </button>
          <button
            class="button button--ghost button--wide"
            type="button"
            @click="setMode('complete-reset')"
          >
            I have a reset token
          </button>
        </div>
      </form>

      <form
        v-else-if="mode === 'request-reset'"
        class="form-stack"
        @submit.prevent="submitResetRequest"
      >
        <label class="field">
          <span>Username or email</span>
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
          {{ submitting ? "Requesting…" : "Send reset token" }}
        </button>
        <button
          class="button button--ghost button--wide"
          type="button"
          @click="setMode('login')"
        >
          Back to sign in
        </button>
      </form>

      <form
        v-else
        class="form-stack"
        @submit.prevent="submitResetComplete"
      >
        <p v-if="notice" class="field-hint" role="status">{{ notice }}</p>

        <label class="field">
          <span>Reset token</span>
          <input
            v-model="resetToken"
            autocomplete="one-time-code"
            required
            spellcheck="false"
          />
        </label>

        <label class="field">
          <span>New password</span>
          <input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            required
          />
        </label>

        <label class="field">
          <span>Confirm password</span>
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
          {{ submitting ? "Resetting…" : "Reset password" }}
        </button>
        <button
          class="button button--ghost button--wide"
          type="button"
          @click="setMode('login')"
        >
          Back to sign in
        </button>
      </form>
    </section>
  </div>
</template>
