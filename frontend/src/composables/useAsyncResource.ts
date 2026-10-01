/**
 * Run an async loader with shared loading / error state.
 *
 * Seventeen components opened with the same five statements —
 * `loading.value = true`, `error.value = null`, `try`, `catch` mapping the
 * failure through `errorMessage`, `finally` resetting `loading` — and several
 * named the wrapper `load()` verbatim. The repetition is not just noise: a site
 * that forgot `finally` (or `await`) could leave a spinner running after a
 * failure, and every copy re-decided what "no error" means.
 *
 * The loader is passed per call rather than to the constructor. That matters for
 * two shapes the sites actually have: a loader that takes a parameter
 * (`selectReadinessTarget(target)`) and a function that computes values *before*
 * its `try` (`refresh()` derives a time window first). Both keep their signature
 * and their local scope; only the guarded section moves inside the callback.
 *
 * `run` always clears the previous error before loading and always resets
 * `loading` in `finally`, so a rejected load cannot strand the UI.
 */

import { ref, type Ref } from "vue"

import { errorMessage } from "../api/client"

interface RunOptions {
  /**
   * Map a thrown value to the message shown to the operator.
   *
   * Defaults to `errorMessage`, which unwraps an `ApiClientError` into the
   * backend's own message and falls back to a generic string.
   */
  onError?: (caught: unknown) => string
}

export function useAsyncResource(): {
  loading: Ref<boolean>
  error: Ref<string | null>
  run: (
    loader: () => Promise<void> | void,
    options?: RunOptions
  ) => Promise<void>
} {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function run(
    loader: () => Promise<void> | void,
    { onError }: RunOptions = {}
  ): Promise<void> {
    loading.value = true
    error.value = null
    try {
      await loader()
    } catch (caught) {
      error.value = onError ? onError(caught) : errorMessage(caught)
    } finally {
      loading.value = false
    }
  }

  return { loading, error, run }
}
