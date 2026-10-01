# Frontend Refactor Audit — `frontend/src/` (Vue 3 + TS + Pinia)

Scope: `frontend/src/` only. All line numbers verified by reading files. Repo root `/Users/zhi/Documents/ChatGPT/zero-nvr`.

## Corpus baseline (measured)

| Metric | Value |
|---|---|
| `.vue` files | 36 |
| Total `.vue` LOC | 40,740 (`views/` 23,604 · `components/` 17,136) |
| Global `styles.css` | 5,259 lines / ~757 class rules |
| Scoped `<style>` LOC inside `.vue` | **10,744** (67% of all CSS lives in components) |
| Files using `defineProps` | 13 / 36 |
| Files using `defineEmits` | 9 / 36 |
| `components/ui/` | 3 files only (`LanguageControl`, `ThemeControl`, `UiIcon`) |
| Hardcoded CJK chars in `.vue` | 6,924 across 15 files (vs. `t()` elsewhere) |
| `<table>` elements | 14 across 10 files, no shared table component |
| `<select>` elements | 42 across 20 files, no shared select |

Two structural facts drive almost every finding:

1. **A "drawer/editor shell" visual language already exists in `styles.css` but was never componentized** (`.storage-editor__*` @ 3750–3950, `.system-drawer` @ 4928, `.unifi-drawer-backdrop` @ 4909), so 12 files hand-roll the same shell.
2. **There is no utility layer.** `utils/` contains only `uuid.ts`. Every formatter, confirm, toast, refresh listener and cloning helper was re-written per view.

---

# Findings, ranked by impact ÷ effort

---

## 1. `<DrawerDialog>` / `<EditorDrawer>` — the drawer + modal shell (impact ★★★★★ / effort ★★★☆☆)

**Pattern.** `<backdrop @click.self="close"> <aside|div> <header: title + subtitle + close button> <form> … <div class="actions"> cancel/save </div> </form> </aside> </backdrop>`

**Every occurrence** (open→close tag range, measured by tag pairing):

| File | Line range | LOC |
|---|---|---|
| `components/system/SystemAccessControlPanel.vue` | 840–933 (user) | 94 |
| ″ | 935–1014 (password reset) | 80 |
| ″ | 1016–1188 (OIDC) | 173 |
| ″ | 1190–1274 (role) | 85 |
| ″ | 1276–1396 (scope) | 121 |
| `components/system/SystemAlertRulesPanel.vue` | 484–719 | 236 |
| `components/system/SystemApiTokensPanel.vue` | 232–340 | 109 |
| `components/system/SystemOidcPanel.vue` | 287–459 | 173 |
| `components/cameras/CameraGroupsPanel.vue` | 242–340 | 99 |
| `components/cameras/CameraDetailPanel.vue` | 329–654 | 326 |
| `views/StorageView.vue` | 1293–1354 (switch) | 62 |
| ″ | 1359–1593 (target editor) | 235 |
| ″ | 1598–1733 (policy editor) | 136 |
| `views/EventsView.vue` | 859–1001 (evidence inspector) | 143 |
| `views/PlaybackView.vue` | 3188–3415 (diagnostics) | 228 |
| ″ | 3445–3794 (protect/export/share panel) | 350 |
| `views/SystemView.vue` | 2282–2357 (notification) | 76 |
| ″ | 3050–3176 (backup policy) | 127 |
| `views/RecordingScheduleView.vue` | 865–1252 (plan dialog) | 388 |
| `views/CamerasView.vue` | 812–1030 (PTZ modal) | 219 |
| **Total** | | **3,460** |

**Shared-class evidence** (proves the shell is already conceptually one thing):
- `.storage-editor__header` ×11, `.storage-editor__form` ×8, `.storage-editor__actions` ×12 — definitions at `styles.css:3762`, `3789`, `3886`
- `class="system-drawer"` ×10, `class="unifi-drawer__form"` ×4
- 4 different backdrop class names for the same behaviour: `.sidebar-backdrop` (`styles.css:1070`), `.unifi-drawer-backdrop` (`4909`), `.camera-group-drawer-backdrop` (`CameraGroupsPanel.vue:439`), `.camera-detail-drawer-backdrop` (`CameraDetailPanel.vue:660`), `.dialog-backdrop` (`RecordingScheduleView.vue`), `.ptz-modal-backdrop` (`CamerasView.vue`)
- 6 different close-button treatments: `<UiIcon name="close">` ×19, literal `✕` at `EventsView.vue:659,871`, `CamerasView.vue:834`, `LiveView.vue:1000,1065,1166`, `PlaybackView.vue:2803`

**Proposed API.**

```vue
<!-- components/ui/DrawerDialog.vue -->
<script setup lang="ts">
defineProps<{
  open: boolean
  title: string
  subtitle?: string
  variant?: 'drawer' | 'centered' | 'modal'   // system-drawer | dialog-card | ptz style
  width?: string                              // default min(480px, 94vw)
  closeOnBackdrop?: boolean                   // default true
  closeOnEscape?: boolean                     // default true
  busy?: boolean                              // disables backdrop/escape close
}>()
defineEmits<{ close: [] }>()
</script>
<template>
  <Teleport to="body">
    <div v-if="open" class="ui-drawer-backdrop" @click.self="closeOnBackdrop && emit('close')">
      <aside class="ui-drawer" :class="`ui-drawer--${variant}`" :style="{ width }" role="dialog">
        <header class="storage-editor__header">
          <div><strong>{{ title }}</strong><span v-if="subtitle">{{ subtitle }}</span></div>
          <slot name="header-actions" />
          <button class="icon-button" @click="emit('close')"><UiIcon name="close" :size="16" /></button>
        </header>
        <slot />
        <div v-if="$slots.footer" class="storage-editor__actions"><slot name="footer" /></div>
      </aside>
    </div>
  </Teleport>
</template>
```

Slots: default (body/form), `header-actions`, `footer`. Consumers replace 3,460 lines with ~2,000 declared lines; the 5 backdrop classes collapse to one; Escape/backdrop/focus-trap behaviour (currently inconsistent — `StorageView` has no Escape handling at all, `RecordingScheduleView.vue:868` only handles backdrop) becomes uniform. **Delete `styles.css:3750–3950` duplication into one component-scoped block, keep `.system-drawer` as one variant.**

---

## 2. `<RecordingWindowsEditor>` — weekly recording-window editor, built twice (impact ★★★★★ / effort ★★★☆☆)

This is the highest-value *logic* duplication in the codebase: two fully independent implementations of "pick weekdays + start/end time, with presets".

**Implementation A — `views/RecordingScheduleView.vue`**
- Constants `ALL_DAYS`/`WORK_DAYS`/`WEEKEND`/`WEEKDAY_OPTIONS`: 50–65
- Helpers `normalizedDays` 112–116, `cloneWindows` 117–124, `sameDays` 125–128, `dayLabel` 129–136, `crossesMidnight` 137–140, `windowDurationLabel` 141–156
- Ops `addWindow` 441–448, `removeWindow` 449–452, `setWindowPresetDays` 453–456, `toggleWindowDay` 457–464, `applySchedulePreset` 465–479, `validateWindows` 480–503
- Template editor `977–1134` (158 lines: preset buttons, window cards, day picker, time interval pickers, delete)
- Script subtotal ≈ 130 lines

**Implementation B — `components/cameras/detail/CameraDetailRecordingTab.vue`**
- `weekdays` computed 63–70
- Ops `addWindow` 260–267, `removeWindow` 268–271, `toggleDay` 273–, `applySchedulePreset` 354–374 (same four presets: `24x7`/`workdays`/`night`/`weekend`)
- `copyWindowToAllDays` 375–378, `copyWindowToWorkdays` 379–382, coverage functions 385–410
- Template editor `736–793` (58 lines) + 7-day coverage matrix `700–715`
- Script subtotal ≈ 160 lines

**Duplicated total: ~290 LOC of logic + ~215 LOC of markup.** Both implement the identical four presets with slightly different magic strings (`'all_day'|'workdays'|'night'|'weekend_plus'` vs `'24x7'|'workdays'|'night'|'weekend'`) and different weekday ordering (`mon..sun` vs `sun..sat`), so behaviour already diverges.

**Proposed API.**

```vue
<!-- components/recording/RecordingWindowsEditor.vue -->
const model = defineModel<RecordingScheduleWindow[]>({ required: true })
defineProps<{
  disabled?: boolean
  showPresets?: boolean          // A: true (4 preset buttons), B: true
  showCoverageMatrix?: boolean   // only CameraDetailRecordingTab
  weekStartsOn?: 0 | 1           // reconcile sun-first vs mon-first
  minWindows?: number            // default 0; B enforces >= 1
  timezone?: string              // v-model:timezone for the input
}>()
defineEmits<{ 'update:timezone': [value: string] }>()
// also export the pure helpers from utils/recordingWindows.ts:
//   ALL_DAYS, WORK_DAYS, WEEKEND, normalizeDays, cloneWindows, sameDays,
//   dayLabel, crossesMidnight, windowDurationLabel, validateWindows, PRESETS
```
`validateWindows` currently only lives in A; moving it to the shared module gives B the same guard for free.

---

## 3. `useToast()` + `<ToastHost>` — 4 identical timeouts, 4 class names (impact ★★★★☆ / effort ★☆☆☆☆)

**Every occurrence** — the `showToast` bodies are the same 4-line function with only the duration differing (2500/3000/3200/4000 ms):

| File | state | `showToast` | template | CSS (class / lines) |
|---|---|---|---|---|
| `views/EventsView.vue` | 52–53 | 68–75 | 1004–1007 | `.toast-popup` 1962–1975 (14) |
| `views/CamerasView.vue` | 60 | 88–95 | 497–501 | `.toast-banner` 1048–1074 (27) |
| `views/FilesView.vue` | 110 | 465–472 | 1576–1583 | `.toast-notification`+`.toast-dot` 2654–2684 (31) |
| `views/RecordingScheduleView.vue` | 77 | 105–110 | 589–593 | `.schedule-toast` 1269–1285 (17) |

≈ 40 lines of script/markup + **89 lines of near-duplicate CSS**, 4 positions (bottom-center, top-center, bottom-right, top-right), 4 durations, 3 of which lack the timer cleanup the 4th has (`EventsView` clears `toastTimer`; the other three leak a `setTimeout` on unmount — `CamerasView.showToast` has no cleanup and no unmount guard at 490–493).

**Proposed API.**

```ts
// composables/useToast.ts
export function useToast() {
  const toast = ref<{ id: number; message: string; tone: 'info'|'success'|'error' } | null>(null)
  function showToast(message: string, opts?: { durationMs?: number; tone?: 'info'|'success'|'error' }): void
  function dismiss(): void
  onBeforeUnmount(/* clear timer */)
  return { toast, showToast, dismiss }
}
```
```vue
<!-- components/ui/ToastHost.vue --> props: { toast, position?: 'top-right'|'top-center'|'bottom-right'|'bottom-center' } ; emits: { dismiss: [] }
```
Mount once per view; delete ~89 CSS lines.

---

## 4. `<StatusPill>` + `statusClass()` — 99 usages, 6 re-implementations, 2 undefined variants (impact ★★★★☆ / effort ★☆☆☆☆)

`.status-pill` is used **99 times across 16 files**. Global definition at `styles.css:3695` (`--ok` 3707, `--muted` 3713, `--error` 4394). It is then re-declared in 3 scoped blocks: `CameraDetailPanel.vue:1173–1189`, `CameraDetailStreamsTab.vue:380`, `CamerasView.vue:1512–1541` (`--online`/`--offline`/`--maintenance`/`--disabled`/`--retired`).

Six copies of the same string→class mapper:

| Function | File:line |
|---|---|
| `statusClass` | `views/SystemView.vue:474–492` |
| `statusClass` | `components/system/SystemSecretStorePanel.vue:23–28` |
| `artifactStatusClass` | `components/system/SystemReleaseValidationPanel.vue:81–86` |
| `statusClass` | `components/system/SystemRecoveryKitPanel.vue:37–45` |
| `stateClass` / `deliveryClass` | `views/AlertsView.vue:137–148` |
| inline ternary chain | `components/system/SystemApiTokensPanel.vue:205–210`, `SystemOidcPanel.vue:232–237` |

**Live bug found:** `status-pill--warning` (`AlertsView.vue:140,147`) and `status-pill--danger` (`AlertsView.vue:145`) are **referenced but defined nowhere** (variant inventory: used `ok`×24, `muted`×19, `error`×10, `warning`×2, `danger`×1, `online/offline/maintenance/disabled/retired`×2 each; defined: `ok`, `muted`, `error`, `online`, `offline`, `maintenance`, `disabled`, `retired`). Those pills currently render unstyled.

**Proposed API.**

```vue
<!-- components/ui/StatusPill.vue -->
defineProps<{ tone?: 'ok'|'warn'|'error'|'muted'|'info'; label: string; title?: string }>()
```
```ts
// utils/status.ts
export type StatusTone = 'ok' | 'warn' | 'error' | 'muted' | 'info'
export function toneFromStatus(value: string | null | undefined, map?: Record<string, StatusTone>): StatusTone
```
Add `--warning`/`--danger` aliases (or migrate callers to `warn`/`error`) at the same time.

---

## 5. `<NoticeBanner>` — 21 error banners, 6 success banners, 9 class names (impact ★★★★★ / effort ★☆☆☆☆)

**Error banner.** Shape `<div v-if="error" class="X"><UiIcon name="warning" :size="N" /><span>{{ error }}</span></div>`

| File:line | class |
|---|---|
| `views/SystemView.vue:1473–1476` | `events-error` |
| `views/DashboardView.vue:307–310` | `events-error` |
| `views/AlertsView.vue:352–355` | `events-error` |
| `components/system/SystemApiTokensPanel.vue:165–168` | `events-error` |
| `components/system/SystemOidcPanel.vue:200–203` | `events-error` |
| `components/system/SystemReleaseValidationPanel.vue:262–265` | `events-error` |
| `components/system/SystemAccessControlPanel.vue:634–637` | `events-error` |
| `components/system/SystemAlertRulesPanel.vue:408–411` | `events-error` |
| `views/CamerasView.vue:557–560` | `notice-error` (scoped @1146) |
| `views/StorageView.vue:802–805` | `unifi-banner unifi-banner--danger` (scoped @1873–1887) |
| `views/RecordingScheduleView.vue:646–650` | `alert-banner alert-banner--error` (scoped @1412–1426) |
| `components/system/SystemSecretStorePanel.vue:125–128` | `secret-store-panel__message--error` (scoped @377–395) |
| `components/system/SystemRecoveryKitPanel.vue:174–178` | `recovery-kit-panel__message--error` (scoped @377) |
| `components/cameras/CameraGroupsPanel.vue:189` | `notice notice--error` (`styles.css:863`) |
| `components/cameras/CameraDetailPanel.vue:608–610` | `camera-detail-message--error` (scoped @1248) |
| `components/account/AccountPanel.vue:153–155` | `account-panel__message--error` (scoped @366) |
| `components/cameras/CameraOnboardingPanel.vue:1177–1179` | `notice notice--error` |
| `views/LiveView.vue:859–861` | `live-panel-error` (`styles.css:1666`) |
| `views/LoginView.vue:192, 254, 311` | `form-error` |
| `views/SetupView.vue:114` | `form-error` |

**Success banner.** `views/SystemView.vue:1478–1481`, `SystemApiTokensPanel.vue:169–172`, `SystemOidcPanel.vue:204–207`, `SystemAccessControlPanel.vue:638–641`, `SystemAlertRulesPanel.vue:413–416`, `AlertsView.vue:357–360` — all `storage-notice` + `<UiIcon name="check" :size="14">`.

**Proof of copy-paste:** `styles.css:3126–3136` (`.events-error`) and `styles.css:3536–3546` (`.storage-notice`) are **byte-identical except the two colour tokens**. `.form-error` is declared **twice** in the same file (`styles.css:863–867` and `1063–1069`) with conflicting padding/font-size. 19 inline `warning` icons and 12 inline `check` icons all exist purely to decorate these banners.

**Proposed API.**

```vue
<!-- components/ui/NoticeBanner.vue -->
defineProps<{
  tone: 'error' | 'success' | 'warning' | 'info'
  message?: string | null      // v-if inside; no v-if at call site
  dismissible?: boolean
  size?: 'sm' | 'md'
}>()
defineEmits<{ dismiss: [] }>()
<template><slot>{{ message }}</slot></template>
```
Migrating removes ~20 template blocks and ~120 lines of duplicated CSS.

---

## 6. `<CameraListPanel>` + `<CameraListRow>` — the "live camera row" is written 5 times (impact ★★★★☆ / effort ★★★☆☆)

`.live-camera-row*` is defined **once globally** (`styles.css:1682–1790`) but the markup is hand-rolled in 5 places:

| File:line | Rows | Notes |
|---|---|---|
| `views/LiveView.vue:863–921` | full `live-camera-list` with select/drag-drop/slot badge | 59 lines |
| `views/PlaybackView.vue:2611–2684` | full list + per-row sync toggle | 74 lines |
| `views/DashboardView.vue:502–517` | read-only variant | 16 lines |
| `components/cameras/CameraGroupsPanel.vue:294–318` | read-only variant w/ checkbox | 25 lines |
| `components/system/SystemAccessControlPanel.vue:1346–1368` | read-only variant w/ checkbox | 23 lines |

The surrounding panel (`live-camera-panel` / `__header` / `live-search` / `__filters` / `__quick-actions` / `__empty`, all global at `styles.css:1512–1800`) is duplicated in full twice:
- `views/LiveView.vue:775–924` (150 lines) — with filter chips + quick actions
- `views/PlaybackView.vue:2579–2693` (115 lines) — with sync toggles

**Duplicated total ≈ 415 LOC of markup** plus two independent `filteredCameras` computeds (`LiveView.vue:88–105`, `PlaybackView.vue:299–309`).

**Proposed API.**

```vue
<!-- components/cameras/CameraListRow.vue -->
defineProps<{
  camera: CameraSummary
  selected?: boolean
  disabled?: boolean
  slotNumber?: number | null
  trailingIcon?: string        // 'chevron-right' | 'check' | undefined
  draggable?: boolean
}>()
defineEmits<{ select: [cameraId: string]; dragstart: [e: DragEvent]; dragend: []; drop: [] }>()
<slot name="trailing" />       <!-- sync toggle / checkbox -->
```
```vue
<!-- components/cameras/CameraListPanel.vue -->
defineProps<{ cameras: CameraSummary[]; loading?: boolean; title: string; summary?: string }>()
defineEmits<{ refresh: []; close: [] }>()
<slot name="filters" /><slot name="quick-actions" /><slot name="row" :camera="camera" /><slot name="empty" />
```
Also unifies the empty state at `LiveView.vue:912–919` and `PlaybackView.vue:2689–2692` (identical `live-camera-list__empty`).

---

## 7. Decompose `views/SystemView.vue` — 1,866-line template hiding 7 tabs (impact ★★★★★ / effort ★★★★☆)

Measured layout: script 1–1446, **template 1447–3313 (1,866 lines)**, scoped style 3313–3484.

The view already delegates 7 tabs to child components (`SystemSecretStorePanel`, `SystemReleaseValidationPanel`, `SystemAccessControlPanel`, `SystemApiTokensPanel`, `SystemOidcPanel`, `SystemAlertRulesPanel`, `SystemRecoveryKitPanel`) — but 6 tabs remain inline. **Proposed split by the existing `v-if="tab === …"` seams:**

| Proposed component | Template range | LOC | Script state cluster | Script fns |
|---|---|---|---|---|
| `SystemOverviewTab.vue` | 1483–1584 | 102 | 90–92 (`info`/`health`/`settings`), 289–305 computeds | 530–627 |
| `SystemGeneralTab.vue` | 1589–1817 | 229 | 175–177, 197 | 856–873 |
| `SystemTimeTab.vue` | 1818–2161 | 344 | 178–182, 198–203 | 842–855, 874–976 |
| `SystemNotificationsTab.vue` | 2174–2358 | 185 | 100–111 | 687–698, 1020–1121 |
| `SystemAiFrigateTab.vue` | 2367–2521 | 155 | 112–132 | 699–729, 1122–1211 |
| **`SystemBackupTab.vue`** | **2522–3178** | **657** | 133–164 | 296–305, 730–746, 1212–1427 |
| `SystemAuditTab.vue` | 3179–3312 | 134 | 165–174 | 747–832 |
| `SystemNavSidebar.vue` | 1449–1470 | 22 | `navigation` computed 205–287 | — |

`SystemView.vue` becomes ≈ script 120 + template 120 + style 40 ≈ **300 lines**. The 657-line backup tab is itself 3 seams: config import validation (`2522–2620`), backup-policy list + runs (`2620–3040`), policy editor drawer (`3050–3176`) → `SystemBackupPolicyDrawer.vue` (guaranteed by finding #1).

Note `SystemView.vue:436`, `1111` already `window.confirm` — those move with the tabs.

---

## 8. Decompose `views/PlaybackView.vue` — 4,512 lines, 3 giant inline panels (impact ★★★★★ / effort ★★★★☆)

Measured layout: script 1–2576 (2,576), **template 2577–3798 (1,222)**, scoped style 3799–4512 (714).

Natural seams (all `v-if`-gated blocks with their own state clusters):

| Proposed component | State (script lines) | Logic (script lines) | Template | Style | Total |
|---|---|---|---|---|---|
| `PlaybackCameraPanel.vue` | 135–137 | 299–309, 1817–1853, 1218–1264 | 2579–2693 | — (global) | ~215 |
| `PlaybackTopBar.vue` | 83–84, 122, 141, 150 | 86–118, 1886–1955 | 2696–2926 | 4089–4500 (topbar/popover) | ~640 |
| `PlaybackVideoStage.vue` | 123–135, 155–190 | 789–1200, 1266–1671, 2280–2552 | 2928–3186 | — | ~900 |
| `PlaybackDiagnosticsPanel.vue` | 190 | 361–436 (5 computeds), 409–436 | 3188–3415 | — | ~290 |
| `PlaybackActionPanel.vue` | 191–211 | 540–578, 1987–2277 (protect + export + share) | 3445–3794 | 3800–4087 | ~830 |
| `PlaybackTimelinePanel.vue` | 137–141, 151–156 | 310–360, 1895–1954 | 3400–3443 | — | ~330 |

Split `PlaybackActionPanel` further into `ProtectionForm`, `ExportForm`, `ShareEditor` (share editor = `3642–3793`, 152 lines, with its own `saveShare`/`copyShareLink`/`revokeShare` 2158–2272). The view keeps only the master-clock/transport orchestration (1295–1817) → ≈ 800 lines.

---

## 9. `<ConfirmDialog>` + `useConfirm()` — 16 native `window.confirm` calls in 11 files (impact ★★★☆☆ / effort ★☆☆☆☆)

| File:line |
|---|
| `components/cameras/CameraGroupsPanel.vue:146` |
| `components/cameras/detail/CameraDetailGeneralTab.vue:127` |
| `components/system/SystemApiTokensPanel.vue:113` |
| `components/system/SystemOidcPanel.vue:159` |
| `components/system/SystemSecretStorePanel.vue:77` |
| `components/system/SystemAccessControlPanel.vue:431` |
| `components/system/SystemAlertRulesPanel.vue:358` |
| `views/StorageView.vue:396`, `594`, `696` |
| `views/LiveView.vue:700` |
| `views/SystemView.vue:436`, `1111` |
| `views/PlaybackView.vue:2136`, `2255` |

All follow `if (!window.confirm(t("…deleteConfirm", { name }))) return`. `window.confirm` blocks the main thread, is untranslatable by i18n styling, and cannot be themed — this is both a refactor and a UX defect. `LiveView.vue:700` and `PlaybackView.vue:2136` confirmations are multi-line string concatenations that belong in a dialog with a body slot.

```ts
// composables/useConfirm.ts
const { confirm } = useConfirm()   // app-level singleton, backed by a single ConfirmDialog in AppShell
const ok = await confirm({ title: t('…'), message: t('…', { name }), tone: 'danger', confirmLabel: t('common.delete') })
```
`components/ui/ConfirmDialog.vue` props `{ title, message, tone, confirmLabel, cancelLabel, busy }`; emits `{ confirm, cancel }`. Mount once in `layouts/AppShell.vue`.

---

## 10. Composables worth extracting (impact ★★★☆☆ / effort ★★☆☆☆)

**10a. `useGlobalRefresh(handler)`** — the `zero-nvr:refresh` listener is hand-wired in **8 views**, always the same add/remove pair:

`EventsView.vue:410,414` · `AlertsView.vue:257,264` · `CamerasView.vue:487,491` · `DashboardView.vue:281,285` · `StorageView.vue:708,714,718` · `LiveView.vue:741,752,764` · `SystemView.vue:1428,1439,1443` · `PlaybackView.vue:2553,2560,2572`

≈ 40 lines of boilerplate + 8 bespoke `handleRefreshEvent` wrappers. `useGlobalRefresh(refresh)` with automatic `onMounted`/`onBeforeUnmount`.

**10b. `useAsyncResource(loader, { immediate })`** — the `loading.value = true; error.value = null; try { … } catch (e) { error.value = errorMessage(e) } finally { loading.value = false }` block appears **22 times**: `CameraGroupsPanel.vue:78`, `CameraDetailPanel.vue:193`, `SystemApiTokensPanel.vue:65`, `SystemOidcPanel.vue:52`, `SystemSecretStorePanel.vue:55`, `SystemReleaseValidationPanel.vue:195,221`, `SystemAccessControlPanel.vue:137`, `SystemRecoveryKitPanel.vue:74`, `SystemAlertRulesPanel.vue:152`, `TolerantPlaybackTile.vue:218`, `LiveCameraTile.vue:1922`, `AccountPanel.vue:60`, `EventsView.vue:241`, `AlertsView.vue:168`, `CamerasView.vue:245`, `DashboardView.vue:117`, `FilesView.vue:543`, `StorageView.vue:232`, `LiveView.vue:402`, `SystemView.vue:631`, `RecordingScheduleView.vue:315`.

Four files even name it identically (`async function load()` — `CameraDetailPanel.vue:192`, `SystemApiTokensPanel.vue:64`, `SystemOidcPanel.vue:51`, `SystemSecretStorePanel.vue:52`). Returns `{ loading, error, data, run, reset }`; also absorbs the `auth.hasPermission(...)` early-return guard repeated at `StorageView.vue:230`, `SystemSecretStorePanel.vue:53`.

**10c. `useFullscreen(targetRef)`** — 3 copies of the same toggle + change listener: `LiveView.vue:723–736`, `PlaybackView.vue:2541–2552`, `LiveCameraTile.vue:1978–1980` (+ listener 2049/2053, 2146/2150). Returns `{ fullscreen, toggle, enter, exit }`.

**10d. `useDismissable(openRef, rootRef)`** — `closeOnOutside` + `closeOnEscape` are copied verbatim in `ThemeControl.vue:52–70` and `LanguageControl.vue:54–84` (identical 30 lines). The same behaviour is then *missing* from every drawer in finding #1 and every popover (`LiveView.vue:66–77`, `PlaybackView.vue:84–93`) — those only close via an explicit close button or by opening a sibling popover.

**10e. `usePolling(fn, intervalMs)`** — timer bookkeeping is open-coded at `CameraDetailRecordingTab.vue:311`, `LiveCameraTile.vue:740,788`, `PlaybackView.vue:2079–2102` (`exportPollTimer` + `clearExportPoll` 540–545).

**10f. `useLocalStorage(key, initial)`** — `theme.ts:18,52` and `i18n.ts:3204,3239` hand-roll read/write/serialize; both are module singletons that could use one composable.

---

## 11. `<EmptyState>` — 14 sites, 5 style variants, 3 scoped overrides of one global class (impact ★★★☆☆ / effort ★☆☆☆☆)

Shape `icon → strong title → span hint → optional action button`. Sites:

`CameraGroupsPanel.vue:194–197` (global `.empty-state--large`) · `CameraDetailPanel.vue:483–487` (`preview-empty-state`, scoped @1073–1092) · `CameraOnboardingPanel.vue:1522` (`step-empty`, global @1299) · `SystemOidcPanel.vue:209–217` (global `.empty-state`) · `SystemAlertRulesPanel.vue:418–422` (`storage-empty`, global @3728) · `AccountPanel.vue:241` (`account-sessions-empty`, scoped @514–520) · `EventsView.vue:848–854` (`events-empty` + `empty-icon`/`empty-title`/`empty-desc`/`empty-btn`, global @3276 + scoped @1650–1685) · `CamerasView.vue:699–703` (`empty-state`, **overrides** the global @1587) · `DashboardView.vue:404–407, 444–447, 496–499` (`dashboard-empty`, scoped @980) · `FilesView.vue:1538–1544` (`empty-state`, **overrides** the global @2641) · `StorageView.vue:841–845, 1153–1157` (`unifi-empty-box`, scoped @2285–2307) · `LiveView.vue:1069` (`popover-empty`) · `LiveView.vue:1206–1216` (`live-empty-tile`, global @2141) · `LiveView.vue:1218–1232` (`live-empty-stage`, global @2165) · `RecordingScheduleView.vue:729,738` (`empty-state`, **overrides** the global @1749).

`.empty-state` is declared globally at `styles.css:835–852` and then re-declared scoped in **3 views** — every override silently wins, so the "global" component is dead for those views.

```vue
<!-- components/ui/EmptyState.vue -->
defineProps<{ icon?: string; title: string; description?: string; size?: 'sm'|'md'|'lg'; tone?: 'muted'|'warning' }>()
defineEmits<{ action: [] }>()
<slot name="actions" />
```

---

## 12. Decompose `views/FilesView.vue` — 2,684 lines, 4 independent zones (impact ★★★★☆ / effort ★★★☆☆)

Layout: script 1–954, **template 955–1586 (632)**, scoped style 1587–2684 (1,097 — the largest scoped block in the repo).

| Proposed component | Template | Script to move | Approx LOC |
|---|---|---|---|
| `FilesFilterHeader.vue` | 957–1074 | filters 112–120, 178–221, 775–779 | ~180 |
| `FilesMonthCalendar.vue` | 1075–1122 | `monthSegmentsMap` 125, `loadMonthTimeline` 497–537, computeds 301–464, `shiftMonth` 758–768, `selectCalendarDate` 769–774 | ~340 |
| `FilesSegmentInspector.vue` | 1125–1356 | player state 128–135, `selectSegment` 718–745, `jumpToTimeline` 795–809, `toggleSegmentLock` 813–841, `downloadRawSegment` 845–852, `triggerArchiveSync` 853–856, video handlers 895–935 | ~330 |
| `FilesHeatmapCard.vue` | 1190–1257 | `heatGrid` 257–300 (44 lines), `activeHeatBinIndex` 134, `onHeatCellClick` 783–794 | ~112 |
| `FilesSegmentTable.vue` | 1358–1574 | pagination 136–176, batch selection 858–874 | ~230 |

**High-value sub-findings inside this file:** `.blue-dot` is re-declared at `FilesView.vue:1640`, `EventsView.vue:1054`, `PlaybackView.vue:4120`; `.table-container` at `FilesView.vue:2447`, `CamerasView.vue:1408`, `RecordingScheduleView.vue:1528`; `.field-label` at `FilesView.vue:1662`, `RecordingScheduleView.vue:2287`; `.topbar-divider` at `FilesView.vue:1649`, `PlaybackView.vue:4128`.

**Bug surfaced while mapping:** `FilesView.batchExport` (883–885), `batchSyncArchive` (887–889) and `batchDelete` (891–893) only call `showToast(...)` — **no API call**. `batchProtect` (875–881) mutates `segments.value[i].protected = true` locally without persisting. `EventsView.batchProtectEvents` (359–361) and `batchExportEvents` (363–365) are likewise toast-only stubs. Any shared `BatchActionBar`/`useBatchSelection` must not codify these as working.

---

## 13. Decompose `views/StorageView.vue` + `<StorageTargetCard>` (impact ★★★★☆ / effort ★★★☆☆)

Layout: script 1–721, **template 722–1737 (1,016)**, scoped style 1738–2560 (822).

| Proposed component | Template | Script | Approx LOC |
|---|---|---|---|
| `StorageMetricsCards.vue` | 768–800 | computeds 92–119 | ~60 |
| `StorageTargetCard.vue` (local **and** WebDAV variants) | 849–1013, 1014–1128 | `targetDetail` 133–148, watermarks 149–175, badges 176–216, test 548–581, toggle 582–592 | ~380 |
| `StorageRetentionTable.vue` | 1152–1288 | `cameraName` 217–222, `scopeLabel` 223–228 | ~170 |
| `StorageSwitchTargetDrawer.vue` | 1291–1356 | 58–60, 377–427 | ~130 |
| `StorageTargetEditorDrawer.vue` | 1357–1595 | 62–79, 264–355, 428–547 | ~430 |
| `StorageRetentionEditorDrawer.vue` | 1596–1736 | 80–91, 606–707 | ~290 |

The two target cards (`849–1013` local, `1014–1128` archive) are near-identical: same `.unifi-card-header` (`856`, `1021`), same health badge, same capacity bar, same test-result box, same 4-button action footer (`951–1012` vs `1080–1127`); they differ only in the capacity-bar/watermark block and the WebDAV callout. `StorageTargetCard` props `{ target, metrics?, testResult?, busy?, testing?, canManage? }`, emits `{ edit, toggle, test, remove, open-credentials, switch-destination }`, slots `#extra` (watermarks / WebDAV callout).

---

## 14. Decompose `components/cameras/CameraOnboardingPanel.vue` — 1,881 lines, 3 mode UIs (impact ★★★★☆ / effort ★★★☆☆)

Layout: script 1–1131, **template 1132–1881 (750)**, **no scoped style** (all global — this file is the cleanest large component).

| Proposed component | Template | Script |
|---|---|---|
| `OnboardingModeTabs.vue` | 1144–1182 | `mode` 66–69 |
| `OnvifOnboardingFlow.vue` | 1184–1568 (**385**) | discovery 85–98, 602–714; inspection/import 95–119, 639–714 |
| `CsvBatchImportStep.vue` | 1569–1747 (179) | 165–168, 252–460, 817–996 |
| `RtspManualForm.vue` | 1748–1881 (134) | 74–84, 406–424, 507–540 |
| `OnvifBatchImportStep.vue` | *cross-cuts* | 120–163, 572–601, 732–1119 |

**Real duplication inside this file:** the batch-defaults form is rendered **twice** — `1329–1375` and `1651–1697` (identical `<select v-model="batchGroupId">`, `batchRecordingMode`, storage-target select, `batchTimeSyncMode` blocks, ~47 lines each, 94 lines total) — same for the credential override table. Both should be one `<BatchDefaultsForm v-model="batchDefaults" />`. Also `csvPort`/`rtspHost`/`buildRtspUrl` (252–300) and `validRtspUrl` (243–251) belong in `utils/rtsp.ts` alongside `cameraBatchCsv.ts`, which already exists as a precedent.

---

## 15. Scoped-CSS duplication: 25 classes declared in ≥2 `<style scoped>` blocks, 25 more shadowing `styles.css` (impact ★★★☆☆ / effort ★★☆☆☆)

Measured by parsing all 30 scoped blocks (10,744 lines):

**Worst offender — the three camera-detail tabs re-declare the global button system:**

| Class | Global def | `CameraDetailGeneralTab` | `CameraDetailRecordingTab` | `CameraDetailStreamsTab` |
|---|---|---|---|---|
| `.button` | `styles.css:618–640` | 366–385 | 1539–1553 | 428–442 |
| `.button--primary` | `styles.css:641–651` | 386–390 | 1565–1569 | 454–458 |
| `.button--ghost` | `styles.css:662–672` | 395–400 | 1583–1588 | 463–468 |
| `.button--compact` | `styles.css:3717` | — | 1554–1559 | 443–448 |
| `.button:disabled` | `styles.css:636` | 381–385 | 1560–1564 | 449–453 |
| `.camera-detail-actions` | — | 356–365 | 1523–1538 | 420–427 |
| `.camera-detail-section` + `__heading` + `__heading--actions` + `strong` + `span` | — | — | 1004–1032 | 312–340 |

**≈ 229 lines of duplicated scoped CSS** across 3 sibling files. Fix: delete the button overrides (the global one already wins on specificity ties only by import order — currently the scoped ones silently shadow it), and extract `<CameraDetailSection>` with `#heading` / `#actions` slots (removes 58 lines + 2 markup blocks).

**Other multi-file duplicates (verified definitions):**
`status-pill` ×3 (`CameraDetailPanel.vue:1173`, `CameraDetailStreamsTab.vue:380`, `CamerasView.vue:1512`) · `blue-dot` ×3 (`EventsView.vue:1054`, `FilesView.vue:1640`, `PlaybackView.vue:4120`) · `table-container` ×3 (`CamerasView.vue:1408`, `FilesView.vue:2447`, `RecordingScheduleView.vue:1528`) · `empty-state` ×3 (`CamerasView.vue:1587`, `FilesView.vue:2641`, `RecordingScheduleView.vue:1749`) · `btn-action`/`--primary`/`--ghost` ×2 (`CamerasView.vue:1104–1144`, `RecordingScheduleView.vue:1371–1411`) · `search-input`/`search-icon` ×2 (`EventsView.vue:1218–1246`, `RecordingScheduleView.vue:1489–1517`) · `cam-glyph-box` ×2 (`CamerasView.vue:1328`, `RecordingScheduleView.vue:1611`) · `cam-name` ×2 (`CamerasView.vue:1449`, `PlaybackView.vue:4446`) · `preset-name` ×2 (`CamerasView.vue:1842`, `LiveView.vue:1326`) · `chevron-icon` ×2 (`LiveView.vue:1331`, `PlaybackView.vue:4176`) · `topbar-divider` ×2 (`FilesView.vue:1649`, `PlaybackView.vue:4128`) · `field-label` ×2 (`FilesView.vue:1662`, `RecordingScheduleView.vue:2287`) · `text-amber`/`text-blue` ×2 (`EventsView.vue`, `PlaybackView.vue`).

**25 class names are declared both globally and in a scoped block** (scoped wins silently): `button`, `button--primary`, `button--ghost`, `button--compact`, `icon-button`, `icon-button--danger`, `status-pill`, `status-pill--ok`, `status-pill--muted`, `empty-state`, `events-empty`, `event-card`, `event-card--selected`, `app-shell`, `shell-main`, `sidebar`, `page-surface`, `status-dot`, `storage-check`, `live-stage`, `theme-control`, `theme-menu__item`, `theme-menu__item--active`, `theme-menu__check`, `unifi-drawer-backdrop`.

**Action:** promote the genuinely shared geometry/typography into `styles.css` under a `ui-` namespace, and gate the global `button`/`icon-button`/`status-pill` rules so consumers stop re-declaring them.

---

# Also worth doing (quick wins, ranked)

| # | Finding | Evidence | Effort |
|---|---|---|---|
| A | **Shared formatter module** — `formatBytes` is byte-identical in `views/SystemView.vue:518–527` and `components/system/SystemReleaseValidationPanel.vue:100–109`; `views/StorageView.vue:120–131` is a near-variant (adds `PB`, finite-check, 2-digit precision). `formatTime` (`Intl.DateTimeFormat`) is written 8× with drifting option sets: `SystemView.vue:506`, `SystemApiTokensPanel.vue:53`, `SystemReleaseValidationPanel.vue:88`, `SystemRecoveryKitPanel.vue:57`, `AccountPanel.vue:37`, `DashboardView.vue:183`, `AlertsView.vue:101`, `CameraDetailPanel.vue:131`. `pretty()` duplicated at `DashboardView.vue:203–215` / `SystemView.vue:498–504`. `formatDuration` at `FilesView.vue:237,246` / `SystemReleaseValidationPanel.vue:112`. 19 formatters total. → `utils/format.ts`: `formatBytes`, `createDateTimeFormat(locale)`, `prettyStatus`, `formatDuration`. | 19 sites, 3 files | ★☆☆☆☆ |
| B | **`<DataTable>` shell** — 14 `<table>`s in 10 files, all sharing `<div class="table-container"><table><thead>…</thead><tbody>` + a `loading`/`empty` `<td colspan>` row: `SystemApiTokensPanel.vue:175,188,191`; `SystemAccessControlPanel.vue:644,771,783`; `EventsView.vue:778`; `CamerasView.vue:710`; `FilesView.vue:1452,1538`; `StorageView.vue:1161`; `SystemView.vue:2251,2714,2737,2838,2874,2997`; `RecordingScheduleView.vue:708,729,738`. Plus one bespoke pagination bar at `FilesView.vue:1547–1573` + `styles.css`-free `.page-nav-btn` (`FilesView.vue:2619–2640`). → `<DataTable :columns :rows :loading>` + `<PaginationBar v-model:page :total-pages :total>` (also fixes `SystemApiTokensPanel.vue`'s hardcoded `colspan="6"` and `SystemAccessControlPanel.vue:783`'s `colspan="5"` drifting from their real column counts). | 14 tables | ★★★☆☆ |
| C | **`<CameraSelect>`** — the same `<option v-for="camera in cameras" :value="camera.id">{{ camera.name }}</option>` block with a placeholder: `EventsView.vue:574–581`, `AlertsView.vue:329–342`, `FilesView.vue:971–984`, `StorageView.vue:1646–1659`, `SystemView.vue:2441–2451`, `SystemAccessControlPanel.vue:1346`, `CameraGroupsPanel.vue:294`, `CameraDetailStreamsTab.vue:276`, `SystemAlertRulesPanel.vue:528`. → `<CameraSelect v-model :cameras :placeholder :allow-empty>`. | 9 sites | ★☆☆☆☆ |
| D | **Inline `<svg>` instead of `UiIcon`** — 18 inline SVGs, 7 of them chevrons/arrows duplicating `UiIcon` names already in `components/ui/UiIcon.vue`: `PlaybackView.vue:2717,2765,2779,2824`, `LiveView.vue:952,1085`, `RecordingScheduleView.vue:600`, `AppShell.vue:93,105,117,127,136,145,155,168,195`. Add `chevron-left`/`chevron-right`/`chevron-down` to `UiIcon` and delete ~70 lines of inline path data. | 18 SVGs | ★☆☆☆☆ |
| E | **i18n bypass** — 6,924 hardcoded CJK characters in `.vue` while sibling views use `t()`: `FilesView.vue` 1,575 · `RecordingScheduleView.vue` 1,317 · `CameraDetailRecordingTab.vue` 953 · `CamerasView.vue` 854 · `EventsView.vue` 528 · `AppShell.vue` 423 · `CameraDetailPanel.vue` 386 · `StorageView.vue` 379. `LiveCameraTile.vue` and `SystemView.vue` correctly use `t()`. Extracting the components in findings #1–#14 is the cheapest moment to move these into `i18n.ts` once instead of N times. | 6,924 chars | ★★★★☆ |
| F | **`AppShell.vue` nav** — 9 hand-written `<svg>`+`<RouterLink>` blocks at `93–200` with per-item duplication; drive from a `navItems` array like `SystemView.vue:205–287` already does. | 9 blocks | ★★☆☆☆ |
| G | **Class/markup drift audit** — `.form-error` declared twice with conflicting rules (`styles.css:863` and `1063`); `status-pill--warning`/`--danger` referenced but undefined (`AlertsView.vue:140,145,147`). Both disappear once findings #4 and #5 land. | 2 defects | ★☆☆☆☆ |

---

# Suggested execution order

1. **Wave 1 (low risk, high return):** #3 Toast, #4 StatusPill, #5 NoticeBanner, #9 useConfirm, #11 EmptyState, #A formatters, #10a/10c/10d composables, #G. These touch many files but each edit is mechanical and independently testable; existing specs (`LiveCameraTile.spec.ts`, `CameraDetailPanel.spec.ts`, `PlaybackView.spec.ts`, `Views/*.spec.ts`) give regression cover.
2. **Wave 2 (structural):** #1 `DrawerDialog` — land it, then convert the 12 drawer files one at a time. This is the enabling refactor for #7, #8, #12, #13.
3. **Wave 3 (decomposition):** #2 `RecordingWindowsEditor` (self-contained, immediately deletes the worst logic duplication), then #7 SystemView, #8 PlaybackView, #12 FilesView, #13 StorageView, #14 CameraOnboardingPanel, #6 CameraListPanel.
4. **Wave 4 (cleanup):** #15 scoped-CSS dedup + #B DataTable + #C CameraSelect + #D/#E/#F. Do CSS dedup *after* decomposition so promoted rules land in their final owner.
