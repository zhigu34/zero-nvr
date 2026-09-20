<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"

import { errorMessage } from "../api/client"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const router = useRouter()
const username = ref("admin")
const displayName = ref("Administrator")
const email = ref("")
const password = ref("")
const passwordConfirm = ref("")
const submitting = ref(false)
const error = ref<string | null>(null)

async function submit(): Promise<void> {
  error.value = null
  if (password.value !== passwordConfirm.value) {
    error.value = "Passwords do not match."
    return
  }

  submitting.value = true
  try {
    await auth.createInitialAdministrator({
      username: username.value,
      display_name: displayName.value,
      email: email.value.trim() || null,
      password: password.value
    })
    await router.replace({
      name: "login",
      query: { initialized: "1" }
    })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <section class="auth-card auth-card--wide">
      <div class="brand brand--auth">
        <div class="brand__mark">0</div>
        <div>
          <strong>zero-nvr</strong>
          <span>first-run setup</span>
        </div>
      </div>

      <div class="auth-card__heading">
        <p class="eyebrow">One-time bootstrap</p>
        <h1>Create the administrator</h1>
        <p>
          zero-nvr ships without a default account or password.
          This form is available only before the first administrator exists.
        </p>
      </div>

      <form class="form-stack" @submit.prevent="submit">
        <div class="form-grid">
          <label class="field">
            <span>Username</span>
            <input v-model="username" autocomplete="username" required />
          </label>
          <label class="field">
            <span>Display name</span>
            <input v-model="displayName" autocomplete="name" required />
          </label>
        </div>

        <label class="field">
          <span>Email <small>optional</small></span>
          <input v-model="email" type="email" autocomplete="email" />
        </label>

        <div class="form-grid">
          <label class="field">
            <span>Password</span>
            <input
              v-model="password"
              type="password"
              minlength="12"
              autocomplete="new-password"
              required
            />
          </label>
          <label class="field">
            <span>Confirm password</span>
            <input
              v-model="passwordConfirm"
              type="password"
              minlength="12"
              autocomplete="new-password"
              required
            />
          </label>
        </div>

        <p class="field-hint">
          Minimum 12 characters. Emergency recovery remains available
          through the deploy.sh administrator recovery path.
        </p>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <button
          class="button button--primary button--wide"
          type="submit"
          :disabled="submitting"
        >
          {{ submitting ? "Creating administrator…" : "Create administrator" }}
        </button>
      </form>
    </section>
  </div>
</template>
