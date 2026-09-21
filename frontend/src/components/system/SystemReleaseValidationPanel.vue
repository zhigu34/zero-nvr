<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import {
  getReleaseValidation,
  type ReleaseValidation,
  type ReleaseValidationArtifact
} from "../../api/system"
import { errorMessage } from "../../api/client"
import UiIcon from "../ui/UiIcon.vue"

const validation = ref<ReleaseValidation | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function numberValue(
  source: Record<string, unknown>,
  key: string
): number | null {
  const value = source[key]
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : null
}

function stringValue(
  source: Record<string, unknown>,
  key: string
): string | null {
  const value = source[key]
  return typeof value === "string" ? value : null
}

function booleanValue(
  source: Record<string, unknown>,
  key: string
): boolean | null {
  const value = source[key]
  return typeof value === "boolean" ? value : null
}

function stringList(
  source: Record<string, unknown>,
  key: string
): string[] {
  const value = source[key]
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is string => typeof item === "string"
  )
}

function artifactStatus(
  artifact: ReleaseValidationArtifact
): "PASS" | "FAIL" | "MISSING" | "INVALID" {
  if (artifact.state !== "AVAILABLE") return artifact.state
  return booleanValue(artifact.report ?? {}, "passed") === true
    ? "PASS"
    : "FAIL"
}

function statusClass(
  artifact: ReleaseValidationArtifact
): string {
  const status = artifactStatus(artifact)
  if (status === "PASS") return "status-pill--ok"
  if (status === "FAIL" || status === "INVALID") {
    return "status-pill--error"
  }
  return "status-pill--muted"
}

function formatTime(value: string | null): string {
  if (!value) return "Never"
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value))
}

function formatBytes(value: number | null): string {
  if (value === null) return "—"
  const units = ["B", "KB", "MB", "GB", "TB"]
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function formatDuration(value: number | null): string {
  if (value === null) return "—"
  if (value < 60) return `${value}s`
  const minutes = Math.floor(value / 60)
  const seconds = value % 60
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`
}

const benchmarkReport = computed(() =>
  validation.value?.benchmark.report ?? {}
)
const benchmarkRuntime = computed(() =>
  objectValue(benchmarkReport.value.runtime)
)
const benchmarkResources = computed(() =>
  objectValue(benchmarkReport.value.resources)
)
const benchmarkFailures = computed(() =>
  stringList(benchmarkRuntime.value, "failures")
)

const soakReport = computed(() =>
  validation.value?.soak.report ?? {}
)
const soakFinal = computed(() =>
  objectValue(soakReport.value.final)
)
const soakRuntime = computed(() =>
  objectValue(soakFinal.value.runtime)
)
const soakFailures = computed(() => {
  const failures = stringList(soakFinal.value, "failures")
  const sampleFailures = objectValue(
    soakReport.value.sample_failure_counts
  )
  for (const [key, value] of Object.entries(sampleFailures)) {
    if (typeof value === "number" && value > 0) {
      failures.push(`${key} × ${value}`)
    }
  }
  return failures
})

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    validation.value = await getReleaseValidation()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <section class="release-validation-panel">
    <header class="system-page-header">
      <div>
        <strong>Release validation</strong>
        <span>
          Latest host-run 8/16-camera benchmark and recording soak reports.
        </span>
      </div>
      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="14" />
        {{ loading ? "Refreshing…" : "Refresh" }}
      </button>
    </header>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>

    <div
      v-if="validation"
      class="release-validation-panel__grid"
    >
      <article class="release-validation-card">
        <header>
          <div>
            <strong>Camera benchmark</strong>
            <span>
              {{
                stringValue(benchmarkReport, "profile") ||
                "No benchmark report"
              }}
            </span>
          </div>
          <span
            class="status-pill"
            :class="statusClass(validation.benchmark)"
          >
            {{ artifactStatus(validation.benchmark) }}
          </span>
        </header>

        <template v-if="validation.benchmark.state === 'AVAILABLE'">
          <div class="release-validation-metrics">
            <div>
              <span>Enabled cameras</span>
              <strong>
                {{
                  numberValue(benchmarkRuntime, "enabled_cameras") ?? "—"
                }}
              </strong>
            </div>
            <div>
              <span>Active recorders</span>
              <strong>
                {{
                  numberValue(benchmarkRuntime, "recorders_active") ?? "—"
                }}
              </strong>
            </div>
            <div>
              <span>Control peak</span>
              <strong>
                {{
                  formatBytes(
                    numberValue(
                      benchmarkResources,
                      "control_plane_memory_peak_bytes"
                    )
                  )
                }}
              </strong>
            </div>
            <div>
              <span>Core image size</span>
              <strong>
                {{
                  formatBytes(
                    numberValue(
                      benchmarkResources,
                      "core_image_virtual_size_bytes"
                    )
                  )
                }}
              </strong>
            </div>
          </div>

          <div
            v-if="benchmarkFailures.length"
            class="release-validation-failures"
          >
            <strong>Failures</strong>
            <span
              v-for="failure in benchmarkFailures"
              :key="failure"
            >
              {{ failure }}
            </span>
          </div>
        </template>

        <p v-else class="release-validation-card__empty">
          {{
            validation.benchmark.state === "MISSING"
              ? "Run a host benchmark to create the first report."
              : "The latest benchmark report is invalid; run the benchmark again."
          }}
        </p>

        <footer>
          <span>
            Updated {{ formatTime(validation.benchmark.updated_at) }}
          </span>
          <code>{{ validation.benchmark.command }}</code>
        </footer>
      </article>

      <article class="release-validation-card">
        <header>
          <div>
            <strong>Recording soak</strong>
            <span>
              {{
                stringValue(soakReport, "profile") ||
                "No soak report"
              }}
            </span>
          </div>
          <span
            class="status-pill"
            :class="statusClass(validation.soak)"
          >
            {{ artifactStatus(validation.soak) }}
          </span>
        </header>

        <template v-if="validation.soak.state === 'AVAILABLE'">
          <div class="release-validation-metrics">
            <div>
              <span>Duration</span>
              <strong>
                {{
                  formatDuration(
                    numberValue(soakReport, "duration_seconds")
                  )
                }}
              </strong>
            </div>
            <div>
              <span>Samples</span>
              <strong>
                {{ numberValue(soakReport, "sample_count") ?? "—" }}
              </strong>
            </div>
            <div>
              <span>Failed samples</span>
              <strong>
                {{
                  numberValue(
                    soakReport,
                    "failed_sample_count"
                  ) ?? "—"
                }}
              </strong>
            </div>
            <div>
              <span>Active recorders</span>
              <strong>
                {{
                  numberValue(soakRuntime, "recorders_active") ?? "—"
                }}
              </strong>
            </div>
          </div>

          <div
            v-if="soakFailures.length"
            class="release-validation-failures"
          >
            <strong>Failures</strong>
            <span
              v-for="failure in soakFailures"
              :key="failure"
            >
              {{ failure }}
            </span>
          </div>
        </template>

        <p v-else class="release-validation-card__empty">
          {{
            validation.soak.state === "MISSING"
              ? "Run a host soak to create the first report."
              : "The latest soak report is invalid; run the soak again."
          }}
        </p>

        <footer>
          <span>
            Updated {{ formatTime(validation.soak.updated_at) }}
          </span>
          <code>{{ validation.soak.command }}</code>
        </footer>
      </article>
    </div>

    <div class="release-validation-panel__note">
      <UiIcon name="activity" :size="15" />
      <span>
        The browser never starts Docker or host benchmarks. Run the shown
        deploy.sh commands on the zero-nvr host; this page only reads the
        latest persisted result.
      </span>
    </div>
  </section>
</template>

<style scoped>
.release-validation-panel {
  display: grid;
  gap: 12px;
}

.release-validation-panel__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.release-validation-card {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.release-validation-card > header,
.release-validation-card > footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.release-validation-card > header > div,
.release-validation-card > footer {
  min-width: 0;
}

.release-validation-card > header strong {
  display: block;
  font-size: 10px;
}

.release-validation-card > header span,
.release-validation-card > footer > span,
.release-validation-card__empty {
  color: var(--text-muted);
  font-size: 8px;
}

.release-validation-card > footer {
  display: grid;
  gap: 5px;
  padding-top: 2px;
}

.release-validation-card code {
  overflow: auto;
  padding: 6px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  color: var(--text-secondary);
  font-size: 8px;
  white-space: nowrap;
}

.release-validation-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.release-validation-metrics > div {
  display: grid;
  gap: 3px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.release-validation-metrics span {
  color: var(--text-muted);
  font-size: 8px;
}

.release-validation-metrics strong {
  font-size: 11px;
}

.release-validation-failures {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.release-validation-failures strong {
  width: 100%;
  font-size: 8px;
}

.release-validation-failures span {
  padding: 3px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  color: var(--text-secondary);
  font-size: 8px;
}

.release-validation-card__empty {
  margin: 0;
  min-height: 68px;
  display: flex;
  align-items: center;
}

.release-validation-panel__note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .release-validation-panel__grid {
    grid-template-columns: 1fr;
  }
}
</style>
