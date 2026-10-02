import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query"

import { useNotify } from "../components/ui/Toast"

/**
 * The shape every write in this app follows.
 *
 * Write pages in the old Vue app each grew their own error handling, which is
 * how three of them ended up swallowing failures: the request threw, the
 * screen simply stopped re-rendering, and nothing on the page changed. Central
 * it here so a write cannot be added without a visible outcome.
 *
 * Rules this enforces:
 *
 * 1. **Invalidate rather than patch the cache.** A camera save touches the
 *    list, the detail, and anything derived from them; a hand-rolled cache
 *    update that misses one of them shows a stale value right next to a fresh
 *    one. Invalidation is one extra round trip and cannot be wrong.
 * 2. **Errors are announced, not swallowed.** A failure toast persists until
 *    dismissed, because a write that quietly did nothing is the worst outcome
 *    available.
 * 3. **No automatic retry.** Repeating a write the operator did not ask to
 *    repeat is how a half-applied batch gets applied twice.
 */

export interface SaveOptions<TVariables, TData> {
  mutationFn: (variables: TVariables) => Promise<TData>
  /** Message on success; omit to stay silent. */
  success?: (data: TData) => { title: string; detail?: string } | null
  /** Message on failure; defaults to the thrown message. */
  failure?: (error: unknown) => { title: string; detail?: string } | null
  /** Query keys to invalidate once the write lands. */
  invalidates?: QueryKey[]
  onSuccess?: (data: TData, variables: TVariables) => void
  onError?: (error: unknown, variables: TVariables) => void
}

export function useSave<TVariables, TData = unknown>(
  options: SaveOptions<TVariables, TData>,
) {
  const queryClient = useQueryClient()
  const notify = useNotify()

  return useMutation({
    mutationFn: options.mutationFn,
    retry: false,
    onSuccess: (data, variables) => {
      for (const key of options.invalidates ?? []) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
      const message = options.success?.(data)
      if (message) notify.success(message.title, message.detail)
      options.onSuccess?.(data, variables)
    },
    onError: (error, variables) => {
      const message =
        options.failure?.(error) ?? {
          title: "操作失败",
          detail: error instanceof Error ? error.message : String(error),
        }
      // An explicit null means "this failure is already surfaced elsewhere".
      if (message) notify.error(message.title, message.detail)
      options.onError?.(error, variables)
    },
  })
}
