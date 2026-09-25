<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import {
  getReleaseReadiness,
  getReleaseValidation,
  type ReleaseReadiness,
  type ReleaseReadinessCheck,
  type ReleaseValidation,
  type ReleaseValidationArtifact
} from "../../api/system"
import { errorMessage } from "../../api/client"
import UiIcon from "../ui/UiIcon.vue"

const { locale, t } = useI18n({ useScope: "global" })

const validation = ref<ReleaseValidation | null>(null)
const readiness = ref<ReleaseReadiness | null>(null)
const readinessTarget = ref<8 | 16>(8)
const loading = ref(false)
const error = ref<string | null>(null)
const copiedCommand = ref<string | null>(null)

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
  if (!value) return t("system.releaseValidation.never")
  return new Intl.DateTimeFormat(locale.value, {
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

const readinessCommand = computed(
  () => `./deploy.sh release-check ${readinessTarget.value}`
)

function readinessName(name: ReleaseReadinessCheck["name"]): string {
  if (name === "benchmark") return t("system.releaseValidation.cameraBenchmark")
  if (name === "soak") return t("system.releaseValidation.recordingSoak")
  return t("system.releaseValidation.verifiedBackup")
}

function artifactStatusLabel(artifact: ReleaseValidationArtifact): string {
  const value = artifactStatus(artifact)
  if (value === "PASS") return t("system.releaseValidation.pass")
  if (value === "FAIL") return t("system.releaseValidation.fail")
  if (value === "MISSING") return t("system.releaseValidation.missing")
  return t("system.releaseValidation.invalid")
}

function readinessDetail(check: ReleaseReadinessCheck): string {
  const profile = stringValue(check.details, "profile")
  const timestamp =
    stringValue(check.details, "generated_at") ||
    stringValue(check.details, "completed_at")
  if (profile && timestamp) {
    return `${profile} · ${formatTime(timestamp)}`
  }
  if (timestamp) return formatTime(timestamp)
  if (profile) return profile
  return check.passed ? t("system.releaseValidation.current") : check.code
}

async function selectReadinessTarget(target: 8 | 16): Promise<void> {
  if (
    readinessTarget.value === target &&
    readiness.value?.expected_cameras === target
  ) {
    return
  }
  readinessTarget.value = target
  readiness.value = null
  loading.value = true
  error.value = null
  try {
    readiness.value = await getReleaseReadiness(target)
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function copyCommand(command: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(command)
    copiedCommand.value = command
    window.setTimeout(() => {
      if (copiedCommand.value === command) {
        copiedCommand.value = null
      }
    }, 1600)
  } catch {
    copiedCommand.value = null
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [nextValidation, nextReadiness] = await Promise.all([
      getReleaseValidation(),
      getReleaseReadiness(readinessTarget.value)
    ])
    validation.value = nextValidation
    readiness.value = nextReadiness
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
        <strong>{{ t("system.releaseValidation.title") }}</strong>
        <span>
          {{ t("system.releaseValidation.description") }}
        </span>
      </div>
      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="14" />
        {{ loading ? t("system.releaseValidation.refreshing") : t("system.releaseValidation.refresh") }}
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
            <strong>{{ t("system.releaseValidation.cameraBenchmark") }}</strong>
            <span>
              {{
                stringValue(benchmarkReport, "profile") ||
                t("system.releaseValidation.noBenchmark")
              }}
            </span>
          </div>
          <span
            class="status-pill"
            :class="statusClass(validation.benchmark)"
          >
            {{ artifactStatusLabel(validation.benchmark) }}
          </span>
        </header>

        <template v-if="validation.benchmark.state === 'AVAILABLE'">
          <div class="release-validation-metrics">
            <div>
              <span>{{ t("system.releaseValidation.enabledCameras") }}</span>
              <strong>
                {{
                  numberValue(benchmarkRuntime, "enabled_cameras") ?? "—"
                }}
              </strong>
            </div>
            <div>
              <span>{{ t("system.releaseValidation.activeRecorders") }}</span>
              <strong>
                {{
                  numberValue(benchmarkRuntime, "recorders_active") ?? "—"
                }}
              </strong>
            </div>
            <div>
              <span>{{ t("system.releaseValidation.controlPeak") }}</span>
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
              <span>{{ t("system.releaseValidation.coreImageSize") }}</span>
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
            <strong>{{ t("system.releaseValidation.failures") }}</strong>
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
              ? t("system.releaseValidation.runBenchmark")
              : t("system.releaseValidation.invalidBenchmark")
          }}
        </p>

        <footer>
          <span>
            {{ t("system.releaseValidation.updatedAt", { time: formatTime(validation.benchmark.updated_at) }) }}
          </span>
          <code>{{ validation.benchmark.command }}</code>
        </footer>
      </article>

      <article class="release-validation-card">
        <header>
          <div>
            <strong>{{ t("system.releaseValidation.recordingSoak") }}</strong>
            <span>
              {{
                stringValue(soakReport, "profile") ||
                t("system.releaseValidation.noSoak")
              }}
            </span>
          </div>
          <span
            class="status-pill"
            :class="statusClass(validation.soak)"
          >
            {{ artifactStatusLabel(validation.soak) }}
          </span>
        </header>

        <template v-if="validation.soak.state === 'AVAILABLE'">
          <div class="release-validation-metrics">
            <div>
              <span>{{ t("system.releaseValidation.duration") }}</span>
              <strong>
                {{
                  formatDuration(
                    numberValue(soakReport, "duration_seconds")
                  )
                }}
              </strong>
            </div>
            <div>
              <span>{{ t("system.releaseValidation.samples") }}</span>
              <strong>
                {{ numberValue(soakReport, "sample_count") ?? "—" }}
              </strong>
            </div>
            <div>
              <span>{{ t("system.releaseValidation.failedSamples") }}</span>
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
              <span>{{ t("system.releaseValidation.activeRecorders") }}</span>
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
            <strong>{{ t("system.releaseValidation.failures") }}</strong>
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
              ? t("system.releaseValidation.runSoak")
              : t("system.releaseValidation.invalidSoak")
          }}
        </p>

        <footer>
          <span>
            {{ t("system.releaseValidation.updatedAt", { time: formatTime(validation.soak.updated_at) }) }}
          </span>
          <code>{{ validation.soak.command }}</code>
        </footer>
      </article>
    </div>

    <section class="release-validation-gate">
      <div class="release-validation-gate__heading">
        <div>
          <strong>{{ t("system.releaseValidation.productionGate") }}</strong>
          <span>
            {{ t("system.releaseValidation.productionGateHint") }}
          </span>
        </div>

        <div class="release-validation-gate__controls">
          <div class="release-validation-targets">
            <button
              class="button button--ghost button--compact"
              :class="{ 'is-active': readinessTarget === 8 }"
              type="button"
              :disabled="loading"
              @click="selectReadinessTarget(8)"
            >
              {{ t("system.releaseValidation.cameras8") }}
            </button>
            <button
              class="button button--ghost button--compact"
              :class="{ 'is-active': readinessTarget === 16 }"
              type="button"
              :disabled="loading"
              @click="selectReadinessTarget(16)"
            >
              {{ t("system.releaseValidation.cameras16") }}
            </button>
          </div>

          <span
            class="status-pill"
            :class="
              !readiness
                ? 'status-pill--muted'
                : readiness.passed
                  ? 'status-pill--ok'
                  : 'status-pill--error'
            "
          >
            {{
              !readiness
                ? t("system.releaseValidation.unknown")
                : readiness.passed
                  ? t("system.releaseValidation.ready")
                  : t("system.releaseValidation.notReady")
            }}
          </span>
        </div>
      </div>

      <div
        v-if="readiness"
        class="release-validation-gate__checks"
      >
        <article
          v-for="check in readiness.checks"
          :key="check.name"
          class="release-validation-gate__check"
        >
          <div>
            <strong>{{ readinessName(check.name) }}</strong>
            <span>{{ readinessDetail(check) }}</span>
          </div>
          <span
            class="status-pill"
            :class="
              check.passed
                ? 'status-pill--ok'
                : 'status-pill--error'
            "
          >
            {{ check.passed ? t("system.releaseValidation.pass") : t("system.releaseValidation.blocked") }}
          </span>
          <code v-if="!check.passed">{{ check.code }}</code>
        </article>
      </div>

      <div class="release-validation-gate__command">
        <div>
          <span>{{ t("system.releaseValidation.finalHostVerification") }}</span>
          <code>{{ readinessCommand }}</code>
        </div>
        <button
          class="button button--ghost button--compact"
          type="button"
          @click="copyCommand(readinessCommand)"
        >
          {{
            copiedCommand === readinessCommand
              ? t("system.releaseValidation.copied")
              : t("system.releaseValidation.copy")
          }}
        </button>
      </div>
    </section>

    <div class="release-validation-panel__note">
      <UiIcon name="activity" :size="15" />
      <span>
        {{ t("system.releaseValidation.hostOnlyHint") }}
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

.release-validation-gate {
  display: grid;
  gap: 10px;
  padding: 10px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.release-validation-gate__heading,
.release-validation-gate__controls,
.release-validation-gate__command {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.release-validation-gate__heading > div:first-child strong,
.release-validation-gate__heading > div:first-child span {
  display: block;
}

.release-validation-gate__heading > div:first-child strong {
  font-size: 10px;
}

.release-validation-gate__heading > div:first-child span {
  max-width: 680px;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.release-validation-gate__controls {
  flex: 0 0 auto;
}

.release-validation-targets {
  display: flex;
  gap: 4px;
}

.release-validation-targets .is-active {
  border-color: var(--border-strong);
  background: var(--surface-active);
  color: var(--text-primary);
}

.release-validation-gate__checks {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.release-validation-gate__check {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 5px 8px;
  align-items: start;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.release-validation-gate__check strong,
.release-validation-gate__check span {
  display: block;
}

.release-validation-gate__check strong {
  font-size: 9px;
}

.release-validation-gate__check div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.4;
}

.release-validation-gate__check code {
  grid-column: 1 / -1;
  overflow-x: auto;
  color: var(--text-secondary);
  font-size: 8px;
  white-space: nowrap;
}

.release-validation-gate__command {
  padding-top: 2px;
}

.release-validation-gate__command > div {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.release-validation-gate__command span {
  color: var(--text-muted);
  font-size: 8px;
}

.release-validation-gate__command code {
  overflow-x: auto;
  padding: 6px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  color: var(--text-secondary);
  font-size: 8px;
  white-space: nowrap;
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
  .release-validation-panel__grid,
  .release-validation-gate__checks {
    grid-template-columns: 1fr;
  }

  .release-validation-gate__heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .release-validation-gate__controls {
    width: 100%;
  }
}
</style>
