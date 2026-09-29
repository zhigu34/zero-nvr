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
const menuOpen = ref(false)

const options = computed<
  Array<{
    value: ThemePreference
    label: string
    icon: string
  }>
>(() => [
  { value: "light", label: t("theme.light"), icon: "sun" },
  { value: "dark", label: t("theme.dark"), icon: "moon" },
  { value: "system", label: t("theme.system"), icon: "monitor" }
])

const currentIcon = computed(() => {
  return resolvedTheme.value === "dark" ? "moon" : "sun"
})

const buttonTitle = computed(() => {
  const modeName = resolvedTheme.value === "dark" ? "深色模式" : "浅色模式"
  const targetName = resolvedTheme.value === "dark" ? "浅色模式" : "深色模式"
  return `深浅模式切换 (当前: ${modeName}，点击切换为${targetName}，右键选择更多)`
})

function toggleTheme(): void {
  const next: ThemePreference = resolvedTheme.value === "dark" ? "light" : "dark"
  setTheme(next)
  menuOpen.value = false
}

function openMenu(): void {
  menuOpen.value = !menuOpen.value
}

function choose(preference: ThemePreference): void {
  setTheme(preference)
  menuOpen.value = false
}

function closeOnOutside(event: PointerEvent): void {
  if (!menuOpen.value || root.value?.contains(event.target as Node)) return
  menuOpen.value = false
}

function closeOnEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") menuOpen.value = false
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
      class="theme-toggle-button"
      type="button"
      :aria-label="buttonTitle"
      :title="buttonTitle"
      @click="toggleTheme"
      @contextmenu.prevent="openMenu"
    >
      <UiIcon :name="currentIcon" :size="18" />
    </button>

    <div
      v-if="menuOpen"
      class="theme-menu theme-menu--dock"
      role="menu"
      :aria-label="t('theme.title')"
    >
      <div class="theme-menu__header">
        <span>外观主题 (Theme)</span>
      </div>
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
        <UiIcon :name="option.icon" :size="15" />
        <span>{{ option.label }}</span>
        <UiIcon
          v-if="themePreference === option.value"
          class="theme-menu__check"
          name="check"
          :size="14"
        />
      </button>
    </div>
  </div>
</template>

<style scoped>
.theme-control {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.theme-toggle-button {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: transparent;
  border: none;
  color: var(--uf-text-muted, #9ca3af);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.theme-toggle-button:hover {
  color: var(--uf-text-primary, #ffffff);
  background: var(--uf-bg-hover, rgba(255, 255, 255, 0.08));
}

.theme-menu--dock {
  position: absolute;
  left: calc(100% + 12px);
  bottom: 0;
  top: auto;
  right: auto;
  z-index: 1000;
  width: 156px;
  padding: 6px;
  border: 1px solid var(--uf-border, rgba(255, 255, 255, 0.1));
  border-radius: 12px;
  background: var(--uf-bg-card, #141722);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(16px);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-menu__header {
  padding: 6px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--uf-text-muted, #9ca3af);
  border-bottom: 1px solid var(--uf-border, rgba(255, 255, 255, 0.06));
  margin-bottom: 4px;
}

.theme-menu__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--uf-text-secondary, #d1d5db);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  width: 100%;
}

.theme-menu__item:hover {
  background: var(--uf-bg-hover, rgba(255, 255, 255, 0.08));
  color: var(--uf-text-primary, #ffffff);
}

.theme-menu__item--active {
  background: var(--uf-accent-glow, rgba(37, 99, 235, 0.15));
  color: var(--uf-accent, #3b82f6);
  font-weight: 600;
}

.theme-menu__check {
  margin-left: auto;
  color: var(--uf-accent, #3b82f6);
}
</style>
