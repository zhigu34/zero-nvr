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
}

.language-control__button {
  font-size: 8px;
  font-weight: 750;
  letter-spacing: 0.02em;
}

.language-menu {
  position: absolute;
  top: calc(100% + 7px);
  right: 0;
  z-index: 80;
  width: 156px;
  padding: 5px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  box-shadow: var(--shadow-lg);
}

.language-menu__item {
  display: grid;
  width: 100%;
  min-height: 32px;
  grid-template-columns: 24px 1fr 16px;
  align-items: center;
  gap: 7px;
  padding: 0 7px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 8px;
  text-align: left;
  cursor: pointer;
}

.language-menu__item:hover,
.language-menu__item--active {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.language-menu__short {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 750;
  text-align: center;
}

.language-menu__check {
  color: var(--accent);
  text-align: center;
}
</style>
