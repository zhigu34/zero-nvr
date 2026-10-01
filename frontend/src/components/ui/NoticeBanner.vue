<script setup lang="ts">
/**
 * A single-line status message with a leading icon.
 *
 * This markup was repeated across the panels: the same
 * `<div class="…"><UiIcon name="warning"/><span>{{ error }}</span></div>` shape
 * appeared with nine different root classes, and the icon-name/icon-size pair
 * was restated every time (session panels used 14, view-level banners 15, the
 * dashboard 16). The class stays a required prop because the surfaces differ on
 * purpose: some sit inside a panel with its own colour, some are page-level
 * banners, and their CSS is scoped to the owning component.
 *
 * The root element carries the caller's class, which is also what lets a parent
 * view's scoped style keep applying — Vue stamps the parent's scope id onto a
 * child component's root node, but not onto elements nested inside it. That is
 * why the icon and message are the only children, and why no styling rule may
 * target them from outside.
 */
import { computed } from "vue"

import UiIcon from "./UiIcon.vue"

const props = withDefaults(
  defineProps<{
    /** Root class supplying this surface's colour, spacing and placement. */
    surfaceClass: string
    variant?: "error" | "success"
    /** Override the variant's default glyph size. */
    iconSize?: number
  }>(),
  { variant: "error", iconSize: undefined }
)

const icon = computed(() => (props.variant === "success" ? "check" : "warning"))

// Success confirmations are deliberately smaller than failure banners: a
// successful save should not draw the same attention as a rejected one.
const size = computed(
  () => props.iconSize ?? (props.variant === "success" ? 14 : 15)
)
</script>

<template>
  <div :class="surfaceClass">
    <UiIcon :name="icon" :size="size" />
    <span><slot /></span>
  </div>
</template>
