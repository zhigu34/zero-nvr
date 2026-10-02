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
