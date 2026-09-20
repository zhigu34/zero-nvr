<script setup lang="ts">
import { computed, ref } from "vue"

import {
  createManualCamera,
  discoverOnvif,
  importOnvif,
  inspectOnvif,
  testManualCamera,
  type CameraProbeResult,
  type DiscoveryCandidate,
  type DiscoverySession,
  type ManualCameraInput,
  type OnvifInspection
} from "../../api/cameras"
import { errorMessage } from "../../api/client"

const emit = defineEmits<{
  created: []
  close: []
}>()

type Mode = "onvif" | "rtsp"
type WorkingAction =
  | "discover"
  | "inspect"
  | "import"
  | "test"
  | "create"
  | null

const mode = ref<Mode>("onvif")
const working = ref<WorkingAction>(null)
const requestError = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const manualName = ref("")
const manualLocation = ref("")
const manualStorageLabel = ref("")
const primaryName = ref("Main stream")
const primaryUrl = ref("")
const secondaryEnabled = ref(false)
const secondaryName = ref("Sub stream")
const secondaryUrl = ref("")
const manualProbe = ref<CameraProbeResult | null>(null)
const manualProbeFingerprint = ref<string | null>(null)

const discovery = ref<DiscoverySession | null>(null)
const selectedCandidateId = ref<string | null>(null)
const onvifHost = ref("")
const onvifPort = ref(80)
const onvifUsername = ref("")
const onvifPassword = ref("")
const onvifName = ref("")
const onvifLocation = ref("")
const onvifStorageLabel = ref("")
const inspection = ref<OnvifInspection | null>(null)
const inspectionFingerprint = ref<string | null>(null)
const selectedProfiles = ref<string[]>([])

const canCreateManual = computed(
  () =>
    manualProbe.value !== null &&
    manualProbeFingerprint.value === JSON.stringify(manualBody()) &&
    working.value === null
)

const canImport = computed(
  () =>
    inspection.value !== null &&
    inspectionFingerprint.value === JSON.stringify(onvifCredentials()) &&
    selectedProfiles.value.length > 0 &&
    working.value === null
)

function normalizeOptional(value: string): string | null {
  const normalized = value.trim()
  return normalized || null
}

function manualBody(): ManualCameraInput {
  return {
    mode: "manual_rtsp",
    name: manualName.value.trim(),
    location: normalizeOptional(manualLocation.value),
    storage_label: normalizeOptional(manualStorageLabel.value),
    primary_stream: {
      name: primaryName.value.trim(),
      rtsp_url: primaryUrl.value.trim()
    },
    secondary_stream: secondaryEnabled.value
      ? {
          name: secondaryName.value.trim(),
          rtsp_url: secondaryUrl.value.trim()
        }
      : null
  }
}

function clearMessages(): void {
  requestError.value = null
  successMessage.value = null
}

async function testRtsp(): Promise<void> {
  clearMessages()
  manualProbe.value = null
  manualProbeFingerprint.value = null
  working.value = "test"
  try {
    const body = manualBody()
    manualProbe.value = await testManualCamera(body)
    manualProbeFingerprint.value = JSON.stringify(body)
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

async function createRtsp(): Promise<void> {
  clearMessages()
  working.value = "create"
  try {
    await createManualCamera(manualBody())
    successMessage.value = "Camera created and credentials stored server-side."
    primaryUrl.value = ""
    secondaryUrl.value = ""
    manualProbe.value = null
    manualProbeFingerprint.value = null
    emit("created")
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

async function runDiscovery(): Promise<void> {
  clearMessages()
  discovery.value = null
  working.value = "discover"
  try {
    discovery.value = await discoverOnvif()
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

function useCandidate(candidate: DiscoveryCandidate): void {
  if (!candidate.host) return

  selectedCandidateId.value = candidate.id
  onvifHost.value = candidate.host
  onvifPort.value = candidate.port ?? 80
  inspection.value = null
  inspectionFingerprint.value = null
  selectedProfiles.value = []
}

function onvifCredentials() {
  return {
    host: onvifHost.value.trim(),
    port: Number(onvifPort.value),
    username: onvifUsername.value.trim(),
    password: onvifPassword.value
  }
}

async function inspectDevice(): Promise<void> {
  clearMessages()
  inspection.value = null
  inspectionFingerprint.value = null
  selectedProfiles.value = []
  working.value = "inspect"

  try {
    const credentials = onvifCredentials()
    const result = await inspectOnvif(credentials)
    inspection.value = result
    inspectionFingerprint.value = JSON.stringify(credentials)
    selectedProfiles.value = result.profiles
      .filter((profile) => profile.stream_uri_available)
      .map((profile) => profile.token)
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

async function importDevice(): Promise<void> {
  if (!inspection.value || selectedProfiles.value.length === 0) return

  clearMessages()
  working.value = "import"
  try {
    await importOnvif({
      ...onvifCredentials(),
      name: normalizeOptional(onvifName.value),
      location: normalizeOptional(onvifLocation.value),
      storage_label: normalizeOptional(onvifStorageLabel.value),
      profile_tokens: [...selectedProfiles.value],
      discovery_candidate_id: selectedCandidateId.value
    })
    successMessage.value =
      "ONVIF device imported. Stream credentials remain in the zero-nvr secret store."
    onvifPassword.value = ""
    emit("created")
  } catch (caught) {
    requestError.value = errorMessage(caught)
  } finally {
    working.value = null
  }
}

function profileSummary(profile: OnvifInspection["profiles"][number]): string {
  const parts = [
    profile.codec,
    profile.width && profile.height
      ? `${profile.width}×${profile.height}`
      : null,
    profile.fps ? `${profile.fps} fps` : null
  ]
  return parts.filter(Boolean).join(" · ") || "Profile details unavailable"
}
</script>

<template>
  <section class="panel onboarding-panel">
    <div class="panel__header onboarding-panel__header">
      <div>
        <p class="eyebrow">Camera onboarding</p>
        <h2>Add a camera or device</h2>
      </div>
      <button class="button button--ghost" type="button" @click="emit('close')">
        Close
      </button>
    </div>

    <div class="segmented-tabs" role="tablist" aria-label="Camera onboarding mode">
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'onvif'"
        :class="{ 'segmented-tabs__item--active': mode === 'onvif' }"
        class="segmented-tabs__item"
        @click="mode = 'onvif'; clearMessages()"
      >
        ONVIF
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'rtsp'"
        :class="{ 'segmented-tabs__item--active': mode === 'rtsp' }"
        class="segmented-tabs__item"
        @click="mode = 'rtsp'; clearMessages()"
      >
        Manual RTSP
      </button>
    </div>

    <p v-if="requestError" class="notice notice--error" role="alert">
      {{ requestError }}
    </p>
    <p v-if="successMessage" class="notice notice--success" role="status">
      {{ successMessage }}
    </p>

    <div v-if="mode === 'onvif'" class="onboarding-grid">
      <div class="onboarding-step">
        <div class="step-heading">
          <span>1</span>
          <div>
            <strong>Find or enter the device</strong>
            <p>WS-Discovery stages candidates only. Nothing is created yet.</p>
          </div>
        </div>

        <button
          class="button button--secondary"
          type="button"
          :disabled="working !== null"
          @click="runDiscovery"
        >
          {{ working === "discover" ? "Discovering…" : "Discover ONVIF devices" }}
        </button>

        <div
          v-if="discovery && discovery.candidates.length"
          class="candidate-list"
        >
          <button
            v-for="candidate in discovery.candidates"
            :key="candidate.id"
            type="button"
            class="candidate-card"
            :class="{
              'candidate-card--selected': selectedCandidateId === candidate.id
            }"
            :disabled="!candidate.host"
            @click="useCandidate(candidate)"
          >
            <strong>{{ candidate.host || "Address unavailable" }}</strong>
            <span>
              {{ candidate.port ? `port ${candidate.port}` : "default port" }}
              · {{ candidate.state }}
            </span>
          </button>
        </div>
        <p
          v-else-if="discovery"
          class="field-hint onboarding-hint"
        >
          No ONVIF devices were discovered. Manual host entry remains available.
        </p>

        <div class="form-grid form-grid--three">
          <label class="field field--grow">
            <span>Host or IP</span>
            <input
              v-model="onvifHost"
              placeholder="192.168.1.50"
              autocomplete="off"
              required
            />
          </label>
          <label class="field">
            <span>Port</span>
            <input
              v-model.number="onvifPort"
              type="number"
              min="1"
              max="65535"
              inputmode="numeric"
            />
          </label>
          <label class="field">
            <span>Username</span>
            <input v-model="onvifUsername" autocomplete="username" />
          </label>
        </div>

        <label class="field">
          <span>Password</span>
          <input
            v-model="onvifPassword"
            type="password"
            autocomplete="current-password"
          />
        </label>

        <button
          class="button button--primary"
          type="button"
          :disabled="working !== null || !onvifHost.trim()"
          @click="inspectDevice"
        >
          {{ working === "inspect" ? "Inspecting…" : "Test & inspect" }}
        </button>
      </div>

      <div class="onboarding-step">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>Choose stream profiles</strong>
            <p>zero-nvr validates ONVIF first; ZLM verifies actual media later.</p>
          </div>
        </div>

        <div v-if="inspection" class="inspection-card">
          <div class="device-summary">
            <strong>
              {{ inspection.device.manufacturer || "ONVIF device" }}
              {{ inspection.device.model || "" }}
            </strong>
            <span v-if="inspection.device.serial_number">
              S/N {{ inspection.device.serial_number }}
            </span>
          </div>

          <div class="profile-list">
            <label
              v-for="profile in inspection.profiles"
              :key="profile.token"
              class="profile-option"
              :class="{ 'profile-option--disabled': !profile.stream_uri_available }"
            >
              <input
                v-model="selectedProfiles"
                type="checkbox"
                :value="profile.token"
                :disabled="!profile.stream_uri_available"
              />
              <span>
                <strong>{{ profile.name }}</strong>
                <small>{{ profileSummary(profile) }}</small>
              </span>
            </label>
          </div>
        </div>

        <div v-else class="step-empty">
          Test a device to load its media profiles and capabilities.
        </div>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>3</span>
          <div>
            <strong>Import into Device Center</strong>
            <p>
              One multi-channel device can produce multiple Camera records while
              preserving stable Device identity.
            </p>
          </div>
        </div>

        <div class="form-grid form-grid--three">
          <label class="field">
            <span>Name <small>optional</small></span>
            <input v-model="onvifName" placeholder="Front entrance" />
          </label>
          <label class="field">
            <span>Location <small>optional</small></span>
            <input v-model="onvifLocation" placeholder="Ground floor" />
          </label>
          <label class="field">
            <span>Storage label <small>optional</small></span>
            <input v-model="onvifStorageLabel" placeholder="entrance" />
          </label>
        </div>

        <div class="onboarding-actions">
          <span class="field-hint">
            {{ selectedProfiles.length }} profile(s) selected
          </span>
          <button
            class="button button--primary"
            type="button"
            :disabled="!canImport"
            @click="importDevice"
          >
            {{ working === "import" ? "Importing…" : "Import device" }}
          </button>
        </div>
      </div>
    </div>

    <div v-else class="onboarding-grid">
      <div class="onboarding-step">
        <div class="step-heading">
          <span>1</span>
          <div>
            <strong>Describe the camera</strong>
            <p>Manual RTSP is first-class when ONVIF is unavailable.</p>
          </div>
        </div>

        <label class="field">
          <span>Camera name</span>
          <input v-model="manualName" placeholder="Garage" required />
        </label>

        <div class="form-grid">
          <label class="field">
            <span>Location <small>optional</small></span>
            <input v-model="manualLocation" />
          </label>
          <label class="field">
            <span>Storage label <small>optional</small></span>
            <input v-model="manualStorageLabel" />
          </label>
        </div>
      </div>

      <div class="onboarding-step">
        <div class="step-heading">
          <span>2</span>
          <div>
            <strong>Configure streams</strong>
            <p>ZLMediaKit performs the actual source pull and probe.</p>
          </div>
        </div>

        <label class="field">
          <span>Primary stream name</span>
          <input v-model="primaryName" required />
        </label>
        <label class="field">
          <span>Primary RTSP URL</span>
          <input
            v-model="primaryUrl"
            type="password"
            autocomplete="off"
            placeholder="rtsp://user:password@camera/stream"
            required
          />
        </label>

        <label class="check-row">
          <input v-model="secondaryEnabled" type="checkbox" />
          <span>Add a secondary / preview stream</span>
        </label>

        <template v-if="secondaryEnabled">
          <label class="field">
            <span>Secondary stream name</span>
            <input v-model="secondaryName" required />
          </label>
          <label class="field">
            <span>Secondary RTSP URL</span>
            <input
              v-model="secondaryUrl"
              type="password"
              autocomplete="off"
              required
            />
          </label>
        </template>
      </div>

      <div class="onboarding-step onboarding-step--full">
        <div class="step-heading">
          <span>3</span>
          <div>
            <strong>Verify before creating</strong>
            <p>
              Testing opens only temporary ZLM proxies and does not persist a Camera.
            </p>
          </div>
        </div>

        <div v-if="manualProbe" class="probe-results">
          <article
            v-for="stream in manualProbe.streams"
            :key="stream.role"
            class="probe-card"
          >
            <div>
              <strong>{{ stream.name }}</strong>
              <span>{{ stream.role }}</span>
            </div>
            <p>
              Video:
              <strong>{{ stream.video?.codec || "not detected" }}</strong>
              <template v-if="stream.video?.width && stream.video?.height">
                · {{ stream.video.width }}×{{ stream.video.height }}
              </template>
            </p>
            <p>
              Audio:
              <strong>{{ stream.audio?.codec || "none" }}</strong>
            </p>
          </article>
        </div>

        <div class="onboarding-actions">
          <button
            class="button button--secondary"
            type="button"
            :disabled="
              working !== null ||
              !manualName.trim() ||
              !primaryUrl.trim()
            "
            @click="testRtsp"
          >
            {{ working === "test" ? "Testing…" : "Test streams" }}
          </button>
          <button
            class="button button--primary"
            type="button"
            :disabled="!canCreateManual"
            @click="createRtsp"
          >
            {{ working === "create" ? "Creating…" : "Create camera" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
