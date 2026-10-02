import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import * as camerasApi from "../api/cameras"
import * as eventsApi from "../api/events"
import * as storageApi from "../api/storage"
import * as playbackApi from "../api/playback"
import * as policyApi from "../api/recordingPolicies"
import * as systemApi from "../api/systemSettings"
import * as exportsApi from "../api/exports"
import * as protectionsApi from "../api/protections"
import * as usersApi from "../api/users"
import * as auditApi from "../api/audit"
import * as alertsApi from "../api/alerts"
import * as notificationsApi from "../api/notifications"
import * as tokensApi from "../api/apiTokens"
import * as secretStoreApi from "../api/secretStore"
import * as frigateApi from "../api/frigate"
import * as accountApi from "../api/account"
import * as backupsApi from "../api/backups"

/**
 * Query defaults tuned for this product rather than copied from a default
 * preset:
 *
 * - `retry: false` on reads. A 401/403 here means "this role cannot see this",
 *   and retrying cannot change that; retrying just delays the error state.
 * - `staleTime` is short for the live-ish screens (cameras, events) and long
 *   for the near-static ones (storage targets, retention policies). Camera
 *   connectivity changes on a scale of seconds, retention policy changes on
 *   the scale of weeks.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: true,
    },
  },
})

export const CAMS = {
  list: (includeRetired = false) => ["cameras", "list", includeRetired] as const,
  detail: (id: string) => ["cameras", "detail", id] as const,
}

export const EVENTS = {
  list: (filters: eventsApi.EventFilters) => ["events", "list", filters] as const,
}

export const STORAGE = {
  targets: ["storage", "targets"] as const,
  retention: ["storage", "retention"] as const,
}

export function useCameras(includeRetired = false) {
  return useQuery({
    queryKey: CAMS.list(includeRetired),
    queryFn: ({ signal }) => camerasApi.listCameras({ includeRetired }, signal),
    staleTime: 10_000,
  })
}

export function useCamera(id: string | null) {
  return useQuery({
    queryKey: CAMS.detail(id ?? ""),
    queryFn: ({ signal }) => camerasApi.getCamera(id!, signal),
    enabled: Boolean(id),
    staleTime: 10_000,
  })
}

/**
 * `GET /events` is keyset paginated (`next_cursor`), so this is an infinite
 * query rather than a page index. Accumulating pages by hand in component
 * state is what produced a "load more shows nothing" bug once already.
 */
export function useEvents(filters: eventsApi.EventFilters) {
  return useInfiniteQuery({
    queryKey: EVENTS.list(filters),
    queryFn: ({ pageParam, signal }) =>
      eventsApi.listEvents({ ...filters, cursor: pageParam }, signal),
    initialPageParam: filters.cursor,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 5_000,
  })
}

export function useStorageTargets() {
  return useQuery({
    queryKey: STORAGE.targets,
    queryFn: ({ signal }) => storageApi.listTargets(signal),
    staleTime: 300_000,
  })
}

export function useRetentionPolicies() {
  return useQuery({
    queryKey: STORAGE.retention,
    queryFn: ({ signal }) => storageApi.listRetentionPolicies(signal),
    staleTime: 300_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Playback                                                                  */
/* -------------------------------------------------------------------------- */

export const PLAYBACK = {
  timeline: (
    cameraId: string,
    from: string,
    to: string,
    detail: string,
  ) => ["playback", "timeline", cameraId, from, to, detail] as const,
}

/**
 * One camera's record track over a wall-clock range.
 *
 * This is a query rather than a poll: the track only changes when the clock
 * window moves, and a viewer parked on one moment should not generate traffic.
 * It does go stale quickly, because a recording that was absent a minute ago
 * can be written at any moment by a policy or a restore finishing.
 */
export function useCameraTimeline(
  cameraId: string | null,
  range: { from: string; to: string; detail?: playbackApi.TimelineDetail },
  signal?: AbortSignal,
) {
  return useQuery({
    queryKey: PLAYBACK.timeline(
      cameraId ?? "",
      range.from,
      range.to,
      range.detail ?? "minute",
    ),
    queryFn: ({ signal: querySignal }) =>
      playbackApi.getCameraTimeline(
        cameraId!,
        { from: range.from, to: range.to, detail: range.detail },
        signal ?? querySignal,
      ),
    enabled: Boolean(cameraId) && Boolean(range.from) && Boolean(range.to),
    staleTime: 15_000,
  })
}

/**
 * Multi-camera tracks for a synchronised review.
 *
 * Keyed on the sorted id list so that re-selecting the same cameras in a
 * different order reuses the cache instead of refetching the same batch.
 */
export function useAlignedTimelines(
  cameraIds: readonly string[],
  range: { from: string; to: string; detail?: playbackApi.TimelineDetail },
) {
  const key = [...cameraIds].sort().join(",")
  return useQuery({
    queryKey: ["playback", "aligned", key, range.from, range.to, range.detail ?? "minute"],
    queryFn: ({ signal }) =>
      playbackApi.getAlignedTimeline(
        {
          cameraIds: [...cameraIds],
          from: range.from,
          to: range.to,
          detail: range.detail,
        },
        signal,
      ),
    // One camera is not a synchronised review; the endpoint rejects it.
    enabled:
      cameraIds.length >= playbackApi.MIN_ALIGNED_CAMERAS &&
      cameraIds.length <= playbackApi.MAX_ALIGNED_CAMERAS &&
      Boolean(range.from) &&
      Boolean(range.to),
    staleTime: 15_000,
  })
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

/* -------------------------------------------------------------------------- */
/* Recording policies                                                         */
/* -------------------------------------------------------------------------- */

export const POLICIES = {
  list: ["recording-policies", "list"] as const,
  forCamera: (cameraId: string) =>
    ["recording-policies", "camera", cameraId] as const,
}

/**
 * Every configured policy, with its observed runtime.
 *
 * The list only contains cameras that *have* a policy — there is no implicit
 * default row — so a camera missing from here has no policy, which is a
 * normal state rather than a gap in the data.
 */
export function useRecordingPolicies() {
  return useQuery({
    queryKey: POLICIES.list,
    queryFn: ({ signal }) =>
      policyApi.listRecordingPolicies(signal).then((page) =>
        Array.isArray(page?.items) ? page.items : [],
      ),
    staleTime: 30_000,
  })
}

/* -------------------------------------------------------------------------- */
/* System                                                                     */
/* -------------------------------------------------------------------------- */

export const SYSTEM = {
  settings: ["system", "settings"] as const,
  health: ["system", "health"] as const,
  info: ["system", "info"] as const,
  clockHealth: ["system", "clock-health"] as const,
}

export function useSystemSettings() {
  return useQuery({
    queryKey: SYSTEM.settings,
    queryFn: ({ signal }) => systemApi.getSystemSettings(signal),
    staleTime: 60_000,
  })
}

export function useSystemHealth() {
  return useQuery({
    queryKey: SYSTEM.health,
    queryFn: ({ signal }) => systemApi.getSystemHealth(signal),
    staleTime: 10_000,
    refetchInterval: 30_000,
  })
}

export function useCameraClockHealth() {
  return useQuery({
    queryKey: SYSTEM.clockHealth,
    queryFn: ({ signal }) => systemApi.getCameraClockHealth(signal),
    staleTime: 60_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Files: recordings browse + exports                                         */
/* -------------------------------------------------------------------------- */

export const FILES = {
  segments: (cameraId: string, from: string, to: string) =>
    ["files", "segments", cameraId, from, to] as const,
  protections: (cameraId: string) => ["files", "protections", cameraId] as const,
  exports: (state: string) => ["files", "exports", state] as const,
  shares: (exportId: string) => ["files", "shares", exportId] as const,
}

/**
 * One camera's recording segments over a wall-clock window.
 *
 * Per camera, and only per camera: `GET /cameras/{id}/recordings` is the only
 * segment listing in the contract, so the old page's cross-camera "全部录像"
 * root has nothing behind it and is not reproduced here.
 *
 * Keyset paginated, hence an infinite query — hand-rolled page accumulation in
 * component state is what produced a "load more shows nothing" bug once
 * already on the events screen.
 */
export function useCameraRecordings(
  cameraId: string | null,
  range: { from: string; to: string },
) {
  return useInfiniteQuery({
    queryKey: FILES.segments(cameraId ?? "", range.from, range.to),
    queryFn: ({ pageParam, signal }) =>
      playbackApi.listCameraRecordings(
        cameraId!,
        { from: range.from, to: range.to, cursor: pageParam },
        signal,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: Boolean(cameraId) && Boolean(range.from) && Boolean(range.to),
    staleTime: 15_000,
  })
}

/**
 * The camera's protection windows.
 *
 * Fetched once per camera and intersected locally so the segment table can
 * mark protected rows without an N+1 over `/recordings/{id}`.
 */
export function useCameraProtections(cameraId: string | null) {
  return useQuery({
    queryKey: FILES.protections(cameraId ?? ""),
    queryFn: ({ signal }) => protectionsApi.listCameraProtections(cameraId!, signal),
    enabled: Boolean(cameraId),
    staleTime: 60_000,
  })
}

/**
 * Export jobs, newest first, optionally filtered by state.
 *
 * Polls while anything is unsettled. A job in PENDING or RUNNING is the only
 * thing on this screen that changes without the operator acting, and a job
 * that silently stops moving is indistinguishable from a slow one — so the
 * poll is what turns "stuck" into something the operator can see and act on.
 */
export function useExports(state?: string) {
  return useInfiniteQuery({
    queryKey: FILES.exports(state ?? ""),
    queryFn: ({ pageParam, signal }) =>
      exportsApi.listExports(
        { state, cursor: pageParam, limit: 50 },
        signal,
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const pages = query.state.data?.pages ?? []
      const unsettled = pages.some((page) =>
        page.items.some((job) => !exportsApi.isSettled(job.state)),
      )
      return unsettled ? 4_000 : false
    },
  })
}

/** The share links on one export. Loaded only when a row is expanded. */
export function useExportShares(exportId: string | null) {
  return useQuery({
    queryKey: FILES.shares(exportId ?? ""),
    queryFn: ({ signal }) => exportsApi.listExportShares(exportId!, signal),
    enabled: Boolean(exportId),
    staleTime: 5_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Users & audit                                                              */
/* -------------------------------------------------------------------------- */

export const ADMIN = {
  users: ["admin", "users"] as const,
  roles: ["admin", "roles"] as const,
  cameraGroups: ["admin", "camera-groups"] as const,
  userScope: (userId: string) => ["admin", "user-scope", userId] as const,
  audit: (filters: Record<string, string | undefined>) =>
    ["admin", "audit", filters] as const,
}

/**
 * The user list is a plain array — `GET /users` has no cursor
 * (`admin_api.py:116-123`), so there is no pagination to get wrong. Long
 * stale time: a user row only changes when an admin changes it, and this is
 * also the join source for actor names on the audit page.
 */
export function useUsers() {
  return useQuery({
    queryKey: ADMIN.users,
    queryFn: ({ signal }) => usersApi.listUsers(signal),
    staleTime: 60_000,
  })
}

export function useCameraGroups() {
  return useQuery({
    queryKey: ADMIN.cameraGroups,
    queryFn: ({ signal }) => usersApi.listCameraGroups(signal),
    staleTime: 300_000,
  })
}

export function useRoles() {
  return useQuery({
    queryKey: ADMIN.roles,
    queryFn: ({ signal }) => usersApi.listRoles(signal),
    staleTime: 300_000,
  })
}

/** Only fetched for the user whose scope sheet is open. */
export function useUserCameraScope(userId: string | null) {
  return useQuery({
    queryKey: ADMIN.userScope(userId ?? ""),
    queryFn: ({ signal }) => usersApi.getUserCameraScope(userId!, signal),
    enabled: Boolean(userId),
    staleTime: 60_000,
  })
}

/**
 * Keyset paginated with server-side filters, so the query key carries every
 * filter — a page that kept filters in component state would show the previous
 * filter's rows next to the new filter's header.
 */
export function useAuditEvents(filters: auditApi.AuditFilters) {
  return useInfiniteQuery({
    queryKey: ADMIN.audit({
      actorId: filters.actorId,
      action: filters.action,
      resourceType: filters.resourceType,
      cameraId: filters.cameraId,
      result: filters.result,
      from: filters.from,
      to: filters.to,
    }),
    queryFn: ({ pageParam, signal }) =>
      auditApi.listAuditEvents({ ...filters, cursor: pageParam }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 10_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Alerts                                                                     */
/* -------------------------------------------------------------------------- */

export const ALERTS = {
  policies: ["alerts", "policies"] as const,
  list: (filters: Record<string, string | undefined>) =>
    ["alerts", "list", filters] as const,
}

export function useAlertPolicies() {
  return useQuery({
    queryKey: ALERTS.policies,
    queryFn: ({ signal }) => alertsApi.listAlertPolicies(signal),
    // A plain array with no cursor, like the user list.
    staleTime: 30_000,
  })
}

/**
 * Alerts move on their own — an event fires and a row appears — so this
 * polls while anything is still open, and stops once everything is resolved.
 * A log that only refreshes on navigation hides the alert it was opened to
 * look for.
 */
export function useAlerts(filters: alertsApi.AlertFilters) {
  return useInfiniteQuery({
    queryKey: ALERTS.list({
      cameraId: filters.cameraId,
      state: filters.state,
      severity: filters.severity,
    }),
    queryFn: ({ pageParam, signal }) =>
      alertsApi.listAlerts({ ...filters, cursor: pageParam }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const pages = query.state.data?.pages ?? []
      const live = pages.some((page) =>
        page.items.some((alert) => alert.state !== "RESOLVED"),
      )
      return live ? 10_000 : false
    },
  })
}

/* -------------------------------------------------------------------------- */
/* Notifications                                                              */
/* -------------------------------------------------------------------------- */

export const NOTIFICATIONS = {
  targets: ["notifications", "targets"] as const,
  securityEmail: ["notifications", "security-email"] as const,
  deliveries: (filters: Record<string, string | undefined>) =>
    ["notifications", "deliveries", filters] as const,
}

export function useNotificationTargets() {
  return useQuery({
    queryKey: NOTIFICATIONS.targets,
    queryFn: ({ signal }) => notificationsApi.listNotificationTargets(signal),
    staleTime: 60_000,
  })
}

export function useSecurityEmailTarget() {
  return useQuery({
    queryKey: NOTIFICATIONS.securityEmail,
    queryFn: ({ signal }) => notificationsApi.getSecurityEmailTarget(signal),
    staleTime: 60_000,
  })
}

/**
 * Deliveries change on their own — a queued message moves through
 * PENDING → SENDING → SENT/FAILED without the operator doing anything — so
 * this polls while anything is in flight and stops once the log has settled.
 */
export function useNotificationDeliveries(
  filters: notificationsApi.DeliveryFilters = {},
) {
  return useQuery({
    queryKey: NOTIFICATIONS.deliveries({
      targetId: filters.targetId,
      alertId: filters.alertId,
    }),
    queryFn: ({ signal }) => notificationsApi.listNotificationDeliveries(filters, signal),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const items = query.state.data ?? []
      const inFlight = items.some((d) => d.state === "PENDING" || d.state === "SENDING")
      return inFlight ? 4_000 : false
    },
  })
}

/* -------------------------------------------------------------------------- */
/* API tokens                                                                 */
/* -------------------------------------------------------------------------- */

export const TOKENS = {
  /** Personal tokens belong to one account, so the list is not paged. */
  list: ["auth", "api-tokens"] as const,
}

export function useApiTokens() {
  return useQuery({
    queryKey: TOKENS.list,
    queryFn: ({ signal }) => tokensApi.listApiTokens(signal),
    // Token state changes only when this account creates or revokes one.
    staleTime: 30_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Secret store                                                               */
/* -------------------------------------------------------------------------- */

export const SECRET_STORE = {
  health: ["system", "secret-store"] as const,
}

/**
 * The health report decrypts every stored secret to count it
 * (`secret_store.py:422-435`). That is real work on every call, and nothing
 * about it changes on its own — a key only moves when a deployment ships one —
 * so the staleness window is generous rather than the usual few seconds.
 */
export function useSecretStoreHealth() {
  return useQuery({
    queryKey: SECRET_STORE.health,
    queryFn: ({ signal }) => secretStoreApi.getSecretStoreHealth(signal),
    staleTime: 60_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Frigate                                                                    */
/* -------------------------------------------------------------------------- */

export const FRIGATE = {
  provider: ["system", "frigate"] as const,
}

/**
 * 404s with `frigate_not_configured` on first run, which is the normal state
 * rather than a failure — the panel branches on `isNotConfigured(error)` and
 * shows a form instead of an error banner. `retry: false` keeps that 404 from
 * being retried into a delay before the empty state appears.
 */
export function useFrigateProvider() {
  return useQuery({
    queryKey: FRIGATE.provider,
    queryFn: ({ signal }) => frigateApi.getFrigateProvider(signal),
    staleTime: 60_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Self account                                                               */
/* -------------------------------------------------------------------------- */

export const ACCOUNT = {
  sessions: ["account", "sessions"] as const,
}

/**
 * Active sessions of the signed-in user. Changes only when one is opened or
 * closed, and the user cannot see anyone else's.
 */
export function useSessions() {
  return useQuery({
    queryKey: ACCOUNT.sessions,
    queryFn: ({ signal }) => accountApi.listSessions(signal),
    staleTime: 30_000,
  })
}

/* -------------------------------------------------------------------------- */
/* Backups                                                                    */
/* -------------------------------------------------------------------------- */

export const BACKUPS = {
  policies: ["backups", "policies"] as const,
  /**
   * Prefix for invalidation. `sets()` below is the per-filter key; a write has
   * to invalidate the prefix so every cursor and state combination refetches.
   */
  setList: ["backups", "sets"] as const,
  sets: (filters: Record<string, string | undefined>) =>
    ["backups", "sets", filters] as const,
}

export function useBackupPolicies() {
  return useQuery({
    queryKey: BACKUPS.policies,
    queryFn: ({ signal }) => backupsApi.listBackupPolicies(signal),
    staleTime: 60_000,
  })
}

/**
 * Backup sets move through PENDING → RUNNING → COMPLETED/FAILED on their own,
 * so this polls while anything is in flight and stops once the list settles.
 * A backup of a large database legitimately takes minutes, hence the long gap.
 */
export function useBackupSets(filters: backupsApi.BackupListFilters = {}) {
  const keyFilters = {
    policyId: filters.policyId,
    state: filters.state,
    cursor: filters.cursor,
  }
  return useQuery({
    queryKey: BACKUPS.sets(keyFilters),
    queryFn: ({ signal }) => backupsApi.listBackupSets(filters, signal),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const inFlight = items.some(
        (b) => b.state === "PENDING" || b.state === "RUNNING",
      )
      return inFlight ? 10_000 : false
    },
  })
}

export const RECOVERY_KITS = {
  /** Prefix — a generation invalidates the status of whichever policy ran. */
  prefix: ["recovery-kit"] as const,
  status: (policyId: string) => ["recovery-kit", "status", policyId] as const,
}

export function useRecoveryKitStatus(policyId: string | null) {
  return useQuery({
    queryKey: RECOVERY_KITS.status(policyId ?? ""),
    queryFn: ({ signal }) =>
      backupsApi.getRecoveryKitStatus(policyId as string, signal),
    // Disabled without a policy: the endpoint takes `policy_id` as a required
    // query parameter, so there is nothing to ask about.
    enabled: Boolean(policyId),
    staleTime: 60_000,
  })
}
