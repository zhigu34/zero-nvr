<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import {
  type ThemePreference,
  useTheme
} from "../../theme"
import UiIcon from "./UiIcon.vue"

const { themePreference, resolvedTheme, setTheme } = useTheme()
const root = ref<HTMLElement | null>(null)
const open = ref(false)

const options: Array<{
  value: ThemePreference
  label: string
  icon: string
}> = [
  { value: "system", label: "System", icon: "monitor" },
  { value: "light", label: "Light", icon: "sun" },
  { value: "dark", label: "Dark", icon: "moon" }
]

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
      aria-label="Change theme"
      :aria-expanded="open"
      title="Theme"
      @click="open = !open"
    >
      <UiIcon :name="currentIcon" :size="17" />
    </button>

    <div v-if="open" class="theme-menu" role="menu" aria-label="Theme">
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
