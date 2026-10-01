<script setup lang="ts">
import { useI18n } from "vue-i18n"

import type { PlaybackGap, PlaybackResolve, TimelineSegment } from "../../api/playback"
import type { MasterClockSnapshot } from "../../playback/masterClock"

interface MediaDiagnostics {
  readyState: string
  currentTimeSeconds: number
  mediaTimeMs: number | null
  driftMs: number | null
  playbackRate: number
  paused: boolean
  seeking: boolean
}

interface CameraLabel {
  id: string
  name: string
}

interface SyncTileStatus {
  state: string
  blocksStrict: boolean
}

defineProps<{
  diagnosticClock: MasterClockSnapshot
  diagnosticResolverState: string
  playbackControlActive: boolean
  playbackRate: number
  multiCameraMode: boolean
  syncMode: "tolerant" | "strict"
  playbackParticipants: CameraLabel[]
  skipGaps: boolean
  activeSegmentId: string | null
  activeTimelineSegment: TimelineSegment | null
  standbySegment: TimelineSegment | null
  standbyReady: boolean
  playbackResult: PlaybackResolve | null
  gapResult: PlaybackGap | null
  activeMediaDiagnostics: MediaDiagnostics | null
  syncTileStates: Record<string, SyncTileStatus>
  formatTimestamp: (date: Date) => string
  formatDiagnosticMs: (value: number | null) => string
  translatedStatus: (value: string) => string
  translatedReason: (value: string) => string
}>()

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <aside
    class="playback-diagnostics"
  >
    <header>
      <div>
        <strong>{{ t("playback.diagnosticsTitle") }}</strong>
        <span>
          {{ t("playback.diagnosticsDescription") }}
        </span>
      </div>
      <button
        class="media-button media-button--text"
        type="button"
        @click="emit('close')"
      >
        {{ t("playback.close") }}
      </button>
    </header>

    <div class="playback-diagnostics__grid">
      <section>
        <strong>{{ t("playback.masterClock") }}</strong>
        <dl>
          <div>
            <dt>{{ t("playback.state") }}</dt>
            <dd>{{ translatedStatus(diagnosticClock.state) }}</dd>
          </div>
          <div>
            <dt>{{ t("playback.intent") }}</dt>
            <dd>
              {{
                playbackControlActive
                  ? t("playback.play")
                  : t("playback.pause")
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.rate") }}</dt>
            <dd>{{ playbackRate }}x</dd>
          </div>
          <div>
            <dt>{{ t("playback.clock") }}</dt>
            <dd>
              {{
                formatTimestamp(
                  new Date(
                    diagnosticClock.currentTimeMs
                  )
                )
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.sync") }}</dt>
            <dd>
              {{
                multiCameraMode
                  ? `${translatedStatus(syncMode)} · ${playbackParticipants.length}`
                  : t("playback.single")
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.skipGapsLabel") }}</dt>
            <dd>{{ skipGaps ? t("playback.on") : t("playback.off") }}</dd>
          </div>
        </dl>
      </section>

      <section>
        <strong>{{ t("playback.resolver") }}</strong>
        <dl>
          <div>
            <dt>{{ t("playback.statusLabel") }}</dt>
            <dd>{{ translatedStatus(diagnosticResolverState) }}</dd>
          </div>
          <div>
            <dt>{{ t("playback.segment") }}</dt>
            <dd>
              {{ activeSegmentId || "—" }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.availability") }}</dt>
            <dd>
              {{
                activeTimelineSegment
                  ?.availability ? translatedStatus(activeTimelineSegment.availability) : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.standby") }}</dt>
            <dd>
              {{
                standbySegment
                  ? standbyReady
                    ? t("playback.ready")
                    : t("playback.loading")
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.transport") }}</dt>
            <dd>
              {{
                playbackResult?.status ===
                "playable"
                  ? playbackResult.transport
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.gap") }}</dt>
            <dd>
              {{
                gapResult?.reason ? translatedReason(gapResult.reason) : "—"
              }}
            </dd>
          </div>
        </dl>
      </section>

      <section v-if="!multiCameraMode">
        <strong>{{ t("playback.activeMedia") }}</strong>
        <dl>
          <div>
            <dt>{{ t("playback.mediaReady") }}</dt>
            <dd>
              {{
                activeMediaDiagnostics
                  ?.readyState
                  ? translatedStatus(
                      activeMediaDiagnostics.readyState
                    )
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.mediaTime") }}</dt>
            <dd>
              {{
                activeMediaDiagnostics
                  ? `${activeMediaDiagnostics.currentTimeSeconds.toFixed(3)} s`
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.drift") }}</dt>
            <dd>
              {{
                formatDiagnosticMs(
                  activeMediaDiagnostics
                    ?.driftMs ?? null
                )
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.mediaRate") }}</dt>
            <dd>
              {{
                activeMediaDiagnostics
                  ? `${activeMediaDiagnostics.playbackRate.toFixed(3)}x`
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.paused") }}</dt>
            <dd>
              {{
                activeMediaDiagnostics
                  ? activeMediaDiagnostics.paused
                    ? t("playback.yes")
                    : t("playback.no")
                  : "—"
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("playback.seeking") }}</dt>
            <dd>
              {{
                activeMediaDiagnostics
                  ? activeMediaDiagnostics.seeking
                    ? t("playback.yes")
                    : t("playback.no")
                  : "—"
              }}
            </dd>
          </div>
        </dl>
      </section>

      <section v-else>
        <strong>{{ t("playback.syncChannels") }}</strong>
        <div class="playback-diagnostics__channels">
          <div
            v-for="camera in playbackParticipants"
            :key="camera.id"
          >
            <span>{{ camera.name }}</span>
            <strong>
              {{
                syncTileStates[camera.id]
                  ?.state ? translatedStatus(syncTileStates[camera.id].state) : translatedStatus("resolving")
              }}
            </strong>
            <small>
              {{
                syncTileStates[camera.id]
                  ?.blocksStrict
                  ? t("playback.strictBlocker")
                  : t("playback.nonBlocking")
              }}
            </small>
          </div>
        </div>
      </section>
    </div>
  </aside>
</template>
