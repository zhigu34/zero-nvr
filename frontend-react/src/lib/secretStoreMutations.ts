import { describeRotation, rotateSecretStore } from "../api/secretStore"
import { SECRET_STORE } from "./queries"
import { useSave } from "./save"

/**
 * The one write in the secret store.
 *
 * It is irreversible in the direction that matters: stale records are
 * re-encrypted onto the primary key, and nothing can put them back. The panel
 * is responsible for asking first; this layer's job is to make sure the
 * operator can tell what happened afterwards, which is why the success message
 * reports the counts instead of a bare "done".
 *
 * The returned `health` is the report taken *after* the rotation, in the same
 * call (`api.py:253-254`) — invalidating the read is therefore a refetch of a
 * value the mutation response already contains, but it is still the right
 * thing to do rather than hand-patching the cache.
 */
export function useRotateSecretStore() {
  return useSave<void, Awaited<ReturnType<typeof rotateSecretStore>>>({
    mutationFn: () => rotateSecretStore(),
    invalidates: [SECRET_STORE.health],
    success: (data) => ({
      title: "密钥环已轮换",
      detail: describeRotation(data),
    }),
    failure: (error) => ({
      title: "轮换失败",
      // The likely cause is a record that cannot be decrypted, which surfaces
      // as an unhandled exception rather than an ApiError. The panel disables
      // the button in that state; this message covers arriving there another
      // way, e.g. a key disappearing between the read and the click.
      detail:
        error instanceof Error
          ? error.message
          : "轮换需要先解密全部记录，其中读不出来的会让整个操作中断。",
    }),
  })
}
