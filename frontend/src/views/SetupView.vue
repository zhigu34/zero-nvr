<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import { errorMessage } from "../api/client"
import LanguageControl from "../components/ui/LanguageControl.vue"
import ThemeControl from "../components/ui/ThemeControl.vue"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n({ useScope: "global" })
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
    error.value = t("auth.passwordsDoNotMatch")
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
    <LanguageControl class="auth-language-control" />
    <ThemeControl class="auth-theme-control" />

    <section class="auth-card auth-card--wide">
      <div class="brand brand--auth">
        <div class="brand__mark">0</div>
        <div class="brand__copy">
          <strong>zero-nvr</strong>
          <span>{{ t("brand.firstRunSetup") }}</span>
        </div>
      </div>

      <div class="auth-card__heading">
        <p class="eyebrow">{{ t("setup.oneTimeBootstrap") }}</p>
        <h1>{{ t("setup.createAdministrator") }}</h1>
        <p>
          {{ t("setup.description") }}
        </p>
      </div>

      <form class="form-stack" @submit.prevent="submit">
        <div class="form-grid">
          <label class="field">
            <span>{{ t("setup.username") }}</span>
            <input v-model="username" autocomplete="username" required />
          </label>
          <label class="field">
            <span>{{ t("setup.displayName") }}</span>
            <input v-model="displayName" autocomplete="name" required />
          </label>
        </div>

        <label class="field">
          <span>{{ t("setup.email") }} <small>{{ t("setup.optional") }}</small></span>
          <input v-model="email" type="email" autocomplete="email" />
        </label>

        <div class="form-grid">
          <label class="field">
            <span>{{ t("setup.password") }}</span>
            <input
              v-model="password"
              type="password"
              minlength="12"
              autocomplete="new-password"
              required
            />
          </label>
          <label class="field">
            <span>{{ t("setup.confirmPassword") }}</span>
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
          {{ t("setup.minimumHint") }}
        </p>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <button
          class="button button--primary button--wide"
          type="submit"
          :disabled="submitting"
        >
          {{ submitting ? t("setup.creatingAdministrator") : t("setup.createAdministratorAction") }}
        </button>
      </form>
    </section>
  </div>
</template>
