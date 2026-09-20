<script setup lang="ts">
import { ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import { errorMessage } from "../api/client"
import ThemeControl from "../components/ui/ThemeControl.vue"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref("")
const password = ref("")
const submitting = ref(false)
const error = ref<string | null>(null)

async function submit(): Promise<void> {
  error.value = null
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
        <h1>Sign in</h1>
        <p>
          Use your local zero-nvr account. Camera credentials never
          leave the control plane.
        </p>
      </div>

      <form class="form-stack" @submit.prevent="submit">
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

        <button
          class="button button--primary button--wide"
          type="submit"
          :disabled="submitting"
        >
          {{ submitting ? "Signing in…" : "Sign in" }}
        </button>
      </form>
    </section>
  </div>
</template>
