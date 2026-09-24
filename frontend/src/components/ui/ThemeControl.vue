<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import {
  type ThemePreference,
  useTheme
} from "../../theme"
import UiIcon from "./UiIcon.vue"

const { themePreference, resolvedTheme, setTheme } = useTheme()
const { t } = useI18n({ useScope: "global" })
const root = ref<HTMLElement | null>(null)
const open = ref(false)

const options = computed<
  Array<{
    value: ThemePreference
    label: string
    icon: string
  }>
>(() => [
  { value: "system", label: t("theme.system"), icon: "monitor" },
  { value: "light", label: t("theme.light"), icon: "sun" },
  { value: "dark", label: t("theme.dark"), icon: "moon" }
])

const currentIcon = computed(() => {
  if (themePreference.value === "system") return "monitor"
  return resolvedTheme.value === "dark" ? "moon" : "sun"
})

function choose(preference: ThemePreference): void {
  setTheme(preference)
  open.value = false
}

function closeOnOutside(event: PointerEvent): void {
  if (!open.value || root.value?.contains(event.target as Node)) return
  open.value = false
}

function closeOnEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") open.value = false
}

onMounted(() => {
  window.addEventListener("pointerdown", closeOnOutside)
  window.addEventListener("keydown", closeOnEscape)
})

onBeforeUnmount(() => {
  window.removeEventListener("pointerdown", closeOnOutside)
  window.removeEventListener("keydown", closeOnEscape)
})
</script>

<template>
  <div ref="root" class="theme-control">
    <button
      class="icon-button topbar-icon-button"
      type="button"
      :aria-label="t('theme.change')"
      :aria-expanded="open"
      :title="t('theme.title')"
      @click="open = !open"
    >
      <UiIcon :name="currentIcon" :size="17" />
    </button>

    <div v-if="open" class="theme-menu" role="menu" :aria-label="t('theme.title')">
      <button
        v-for="option in options"
        :key="option.value"
        class="theme-menu__item"
        :class="{ 'theme-menu__item--active': themePreference === option.value }"
        type="button"
        role="menuitemradio"
        :aria-checked="themePreference === option.value"
        @click="choose(option.value)"
      >
        <UiIcon :name="option.icon" :size="16" />
        <span>{{ option.label }}</span>
        <UiIcon
          v-if="themePreference === option.value"
          class="theme-menu__check"
          name="check"
          :size="15"
        />
      </button>
    </div>
  </div>
</template>
