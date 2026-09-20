<script setup lang="ts">
import { computed } from "vue"
import { useRoute } from "vue-router"

const route = useRoute()
const title = computed(() => String(route.meta.title ?? "Workspace"))
const description = computed(() =>
  String(
    route.meta.description ??
      "This workspace will be connected to its existing zero-nvr backend APIs."
  )
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
        <strong>{{ title }} frontend slice</strong>
        <p>
          This page stays inside /api/v1 and will be filled without bypassing
          zero-nvr to third-party admin APIs.
        </p>
      </div>
    </section>
  </div>
</template>
