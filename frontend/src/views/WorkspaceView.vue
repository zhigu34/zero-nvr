<script setup lang="ts">
import { computed } from "vue"
import { useRoute } from "vue-router"
import { useI18n } from "vue-i18n"

const route = useRoute()
const { t } = useI18n({ useScope: "global" })
const title = computed(() => String(route.meta.title ?? t("workspace.title")))
const description = computed(() =>
  String(route.meta.description ?? t("workspace.description"))
)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">zero-nvr</p>
        <h1>{{ title }}</h1>
        <p class="page-subtitle">{{ description }}</p>
      </div>
    </div>

    <section class="panel workspace-placeholder">
      <span class="workspace-placeholder__mark">0</span>
      <div>
        <strong>{{ t("workspace.frontendSlice", { title }) }}</strong>
        <p>
          {{ t("workspace.apiBoundaryHint") }}
        </p>
      </div>
    </section>
  </div>
</template>
