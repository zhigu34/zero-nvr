<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useI18n } from "vue-i18n"

import {
  type AppLocale,
  useAppLocale
} from "../../i18n"

const { t } = useI18n({ useScope: "global" })
const { locale, setLocale } = useAppLocale()
const root = ref<HTMLElement | null>(null)
const open = ref(false)

const options = computed<
  Array<{
    value: AppLocale
    label: string
    short: string
  }>
>(() => [
  {
    value: "en-US",
    label: t("language.english"),
    short: "EN"
  },
  {
    value: "zh-CN",
    label: t("language.simplifiedChinese"),
    short: "简"
  }
])

const currentShort = computed(
  () =>
    options.value.find(
      (item) => item.value === locale.value
    )?.short ?? "EN"
)

function choose(next: AppLocale): void {
  setLocale(next)
  open.value = false
}

function closeOnOutside(event: PointerEvent): void {
  if (
    !open.value ||
    root.value?.contains(event.target as Node)
  ) {
    return
  }
  open.value = false
}

function closeOnEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") open.value = false
}

onMounted(() => {
  window.addEventListener(
    "pointerdown",
    closeOnOutside
  )
  window.addEventListener(
    "keydown",
    closeOnEscape
  )
})

onBeforeUnmount(() => {
  window.removeEventListener(
    "pointerdown",
    closeOnOutside
  )
  window.removeEventListener(
    "keydown",
    closeOnEscape
  )
})
</script>

<template>
  <div ref="root" class="language-control">
    <button
      class="icon-button topbar-icon-button language-control__button"
      type="button"
      :aria-label="t('language.change')"
      :aria-expanded="open"
      :title="t('language.title')"
      @click="open = !open"
    >
      <span>{{ currentShort }}</span>
    </button>

    <div
      v-if="open"
      class="language-menu"
      role="menu"
      :aria-label="t('language.title')"
    >
      <button
        v-for="option in options"
        :key="option.value"
        class="language-menu__item"
        :class="{
          'language-menu__item--active':
            locale === option.value
        }"
        type="button"
        role="menuitemradio"
        :aria-checked="locale === option.value"
        @click="choose(option.value)"
      >
        <span class="language-menu__short">
          {{ option.short }}
        </span>
        <span>{{ option.label }}</span>
        <span
          v-if="locale === option.value"
          class="language-menu__check"
          aria-hidden="true"
        >
          ✓
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.language-control {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.language-control__button {
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
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.language-control__button:hover {
  color: var(--uf-text-primary, #ffffff);
  background: var(--uf-bg-hover, rgba(255, 255, 255, 0.08));
}

.language-menu {
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

.language-menu__item {
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

.language-menu__item:hover {
  background: var(--uf-bg-hover, rgba(255, 255, 255, 0.08));
  color: var(--uf-text-primary, #ffffff);
}

.language-menu__item--active {
  background: var(--uf-accent-glow, rgba(37, 99, 235, 0.15));
  color: var(--uf-accent, #3b82f6);
  font-weight: 600;
}

.language-menu__short {
  color: var(--uf-text-muted, #9ca3af);
  font-size: 10px;
  font-weight: 700;
  min-width: 18px;
}

.language-menu__check {
  margin-left: auto;
  color: var(--uf-accent, #3b82f6);
  font-weight: bold;
}
</style>
