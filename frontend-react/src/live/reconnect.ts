/**
 * Reconnection policy for a tile that lost its stream.
 *
 * The behaviour this replaces: a failed resolve wrote an error string and
 * stopped. Nothing retried, so a camera that came back thirty seconds later
 * stayed black until the operator changed something else on the page — and in
 * strict-sync mode, a tile stuck in that state kept every other camera paused
 * behind it with no path out.
 *
 * The policy here is therefore deliberately *persistent*: attempts back off to
 * a cap and then keep going at that cadence. A tile whose camera is genuinely
 * off should not spin, but recovery must be automatic because the common case
 * is a brief blip, not a dead camera.
 */
import { RECONNECT_DELAYS_MS } from "./transports"

export interface ReconnectSchedulerOptions {
  /** Perform one attempt. Rejections are treated as "keep trying". */
  attempt: () => void | Promise<void>
  delaysMs?: readonly number[]
  /** Called on every attempt so the UI can show it is trying. */
  onAttemptStart?: (attempt: number) => void
}

export class ReconnectScheduler {
  private attemptCount = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private running = false
  private readonly delays: readonly number[]

  constructor(private readonly options: ReconnectSchedulerOptions) {
    this.delays = options.delaysMs ?? RECONNECT_DELAYS_MS
  }

  get attemptNumber(): number {
    return this.attemptCount
  }

  get isPending(): boolean {
    return this.timer !== null
  }

  /** Queues a retry unless one is already queued. */
  schedule(): void {
    if (this.running || this.timer !== null) return
    const delay = this.delays[
      Math.min(this.attemptCount, this.delays.length - 1)
    ]
    this.timer = setTimeout(() => {
      this.timer = null
      this.run()
    }, delay)
  }

  /**
   * Runs an attempt now, ignoring the backoff. This is what the retry button
   * calls: an operator who has just fixed something on the camera should not
   * have to wait out the remaining backoff.
   */
  retryNow(): void {
    this.clearTimer()
    this.attemptCount = 0
    this.run()
  }

  /** A healthy stream resets the ladder entirely. */
  succeed(): void {
    this.attemptCount = 0
    this.clearTimer()
  }

  /** Stops retrying — unmount, or a source the user deliberately changed. */
  stop(): void {
    this.clearTimer()
    this.running = false
  }

  private run(): void {
    if (this.running) return
    this.running = true
    this.attemptCount += 1
    this.options.onAttemptStart?.(this.attemptCount)

    let result: void | Promise<void>
    try {
      result = this.options.attempt()
    } catch {
      // A synchronous throw is just another failed attempt.
      this.running = false
      this.schedule()
      return
    }

    if (result && typeof (result as Promise<void>).then === "function") {
      void (result as Promise<void>).then(
        () => {
          this.running = false
        },
        () => {
          this.running = false
          this.schedule()
        },
      )
      return
    }

    this.running = false
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }
}
