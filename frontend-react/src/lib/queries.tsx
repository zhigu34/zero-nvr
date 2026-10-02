import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import * as camerasApi from "../api/cameras"
import * as eventsApi from "../api/events"
import * as storageApi from "../api/storage"
import * as playbackApi from "../api/playback"

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
