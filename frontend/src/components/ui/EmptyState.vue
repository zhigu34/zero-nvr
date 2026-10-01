<script setup lang="ts">
/**
 * Placeholder shown when a collection has nothing to render.
 *
 * The sites all wrote `<div class="empty-state …">` with an icon, a title and a
 * hint, but they differ in more than their class name: the shared rules style
 * *descendants* (`.empty-state strong`, `.empty-state p`, `.events-empty span`,
 * `.unifi-empty-box strong`), and each surface has its own such rules.
 *
 * Scoped CSS reaches a child component's root element but not elements nested
 * inside it, so the children stay in the caller through the default slot. That
 * keeps every descendant rule matching its own view's scope, while the root here
 * still carries the caller's surface class:
 *
 *   <EmptyState surface-class="storage-empty">
 *     <UiIcon name="bell" :size="26" />
 *     <strong>{{ t("…empty") }}</strong>
 *     <span>{{ t("…emptyHint") }}</span>
 *   </EmptyState>
 *
 * Unifying the *contents* into fixed title/hint props would be a stylesheet
 * change — it belongs with the CSS consolidation, not with this extraction.
 */
withDefaults(
  defineProps<{
    /** Root class supplying this surface's padding, alignment and colours. */
    surfaceClass: string
    /** Adds the `--large` modifier used by the full-page placeholders. */
    large?: boolean
  }>(),
  { large: false }
)
</script>

<template>
  <div
    :class="[surfaceClass, large ? 'empty-state--large' : undefined]"
  >
    <slot />
  </div>
</template>
