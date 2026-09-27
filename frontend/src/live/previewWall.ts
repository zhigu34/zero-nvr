export type PreviewGridSlots = 4 | 9 | 16

export interface PreviewWallListener {
  onFrame(jpeg: Blob): void
  onReady(): void
  onError(message: string): void
  onReconnecting(): void
}

export interface PreviewWallRegistration {
  firstFrame: Promise<boolean>
  close(): void
}

export interface PreviewWallSubscriptionInput {
  slot: number
  cameraId: string
  mediaSessionId: string
}

export interface LivePreviewWallClient {
  setLayout(slots: PreviewGridSlots | null): void
  subscribe(
    input: PreviewWallSubscriptionInput,
    listener: PreviewWallListener
  ): PreviewWallRegistration
  close(): void
}

interface WebSocketLike {
  binaryType: BinaryType
  readyState: number
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  onerror: ((event: Event) => void) | null
  send(data: string): void
  close(): void
}

export interface PreviewWallClientOptions {
  createWebSocket?: (url: string) => WebSocketLike
}

interface ActiveSubscription {
  input: PreviewWallSubscriptionInput
  listener: PreviewWallListener
  subscriptionId: number
  resolveFirstFrame: (value: boolean) => void
  firstFrameSettled: boolean
  closed: boolean
}

function previewWallUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${scheme}//${window.location.host}/api/v1/live/previews/ws`
}

function defaultCreateWebSocket(url: string): WebSocketLike {
  return new WebSocket(url)
}

export function createLivePreviewWallClient(
  options: PreviewWallClientOptions = {}
): LivePreviewWallClient {
  const createWebSocket =
    options.createWebSocket ?? defaultCreateWebSocket
  const subscriptions = new Map<number, ActiveSubscription>()
  let layout: PreviewGridSlots | null = null
  let socket: WebSocketLike | null = null
  let closed = false
  let syncScheduled = false
  let reconnectAttempt = 0
  let reconnectTimer: number | null = null
  const reconnectDelays = [1000, 2000, 4000, 8000, 15000]
  const seed = new Uint32Array(1)
  crypto.getRandomValues(seed)
  let nextSubscriptionId = seed[0]

  function allocateSubscriptionId(): number {
    const allocated = nextSubscriptionId
    nextSubscriptionId = (nextSubscriptionId + 1) >>> 0
    return allocated
  }

  function socketOpen(): boolean {
    return socket?.readyState === 1
  }

  function detachAndCloseSocket(): void {
    const current = socket
    socket = null
    if (current === null) return
    current.onopen = null
    current.onmessage = null
    current.onclose = null
    current.onerror = null
    if (current.readyState < 2) current.close()
  }

  function cancelReconnect(): void {
    if (reconnectTimer === null) return
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  function notifyReconnecting(): void {
    for (const entry of subscriptions.values()) {
      if (!entry.closed) entry.listener.onReconnecting()
    }
  }

  function scheduleReconnect(): void {
    if (
      closed ||
      layout === null ||
      subscriptions.size === 0 ||
      reconnectTimer !== null
    ) {
      return
    }
    notifyReconnecting()
    const delay = reconnectDelays[
      Math.min(reconnectAttempt, reconnectDelays.length - 1)
    ]
    reconnectAttempt += 1
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      ensureSocket()
    }, delay)
  }

  function sendSync(): void {
    if (!socketOpen() || layout === null) return
    socket?.send(
      JSON.stringify({
        type: "sync",
        version: 1,
        layout_slots: layout,
        streams: [...subscriptions.values()]
          .filter((entry) => !entry.closed)
          .sort((left, right) => left.input.slot - right.input.slot)
          .map((entry) => ({
            slot: entry.input.slot,
            subscription_id: entry.subscriptionId,
            camera_id: entry.input.cameraId,
            media_session_id: entry.input.mediaSessionId
          }))
      })
    )
  }

  function scheduleSync(): void {
    if (syncScheduled) return
    syncScheduled = true
    queueMicrotask(() => {
      syncScheduled = false
      sendSync()
    })
  }

  function ensureSocket(): void {
    if (
      closed ||
      layout === null ||
      subscriptions.size === 0 ||
      socket !== null ||
      reconnectTimer !== null
    ) {
      return
    }
    const created = createWebSocket(previewWallUrl())
    socket = created
    created.binaryType = "arraybuffer"
    created.onopen = () => {
      if (socket !== created) return
      scheduleSync()
    }
    created.onmessage = (event) => {
      if (socket !== created) return
      if (typeof event.data === "string") {
        let payload: unknown
        try {
          payload = JSON.parse(event.data)
        } catch {
          return
        }
        if (typeof payload !== "object" || payload === null) return
        const message = payload as Record<string, unknown>
        if (message.type === "fatal") {
          const text =
            typeof message.message === "string"
              ? message.message
              : "Preview connection failed."
          for (const entry of subscriptions.values()) {
            if (!entry.closed) entry.listener.onError(text)
          }
          return
        }
        if (
          (message.type !== "ready" && message.type !== "error") ||
          typeof message.slot !== "number" ||
          typeof message.subscription_id !== "number"
        ) {
          return
        }
        const entry = subscriptions.get(message.slot)
        if (
          entry === undefined ||
          entry.closed ||
          entry.subscriptionId !== message.subscription_id
        ) {
          return
        }
        reconnectAttempt = 0
        if (message.type === "ready") {
          entry.listener.onReady()
        } else {
          if (!entry.firstFrameSettled) {
            entry.firstFrameSettled = true
            entry.resolveFirstFrame(false)
          }
          entry.listener.onError(
            typeof message.message === "string"
              ? message.message
              : "Preview stream failed."
          )
        }
        return
      }
      if (!(event.data instanceof ArrayBuffer)) return
      const data = event.data
      if (data.byteLength < 10 || data.byteLength > 6 + 2 * 1024 * 1024) {
        return
      }
      const view = new DataView(data)
      if (view.getUint8(0) !== 1) return
      const slot = view.getUint8(1)
      const subscriptionId = view.getUint32(2)
      const entry = subscriptions.get(slot)
      if (
        entry === undefined ||
        entry.closed ||
        entry.subscriptionId !== subscriptionId
      ) {
        return
      }
      const jpeg = new Uint8Array(data, 6)
      if (
        jpeg[0] !== 0xff ||
        jpeg[1] !== 0xd8 ||
        jpeg[jpeg.length - 2] !== 0xff ||
        jpeg[jpeg.length - 1] !== 0xd9
      ) {
        return
      }
      reconnectAttempt = 0
      entry.listener.onFrame(
        new Blob([data.slice(6)], { type: "image/jpeg" })
      )
      if (!entry.firstFrameSettled) {
        entry.firstFrameSettled = true
        entry.resolveFirstFrame(true)
      }
    }
    created.onclose = () => {
      if (socket !== created) return
      socket = null
      scheduleReconnect()
    }
  }

  function updateConnection(): void {
    if (closed || layout === null || subscriptions.size === 0) {
      cancelReconnect()
      detachAndCloseSocket()
      return
    }
    ensureSocket()
    scheduleSync()
  }

  return {
    setLayout(slots) {
      if (layout === slots) return
      layout = slots
      updateConnection()
    },

    subscribe(input, listener) {
      const previous = subscriptions.get(input.slot)
      if (previous !== undefined) {
        previous.closed = true
        if (!previous.firstFrameSettled) {
          previous.firstFrameSettled = true
          previous.resolveFirstFrame(false)
        }
      }

      let resolveFirstFrame = (_value: boolean) => {}
      const firstFrame = new Promise<boolean>((resolve) => {
        resolveFirstFrame = resolve
      })
      const entry: ActiveSubscription = {
        input,
        listener,
        subscriptionId: allocateSubscriptionId(),
        resolveFirstFrame,
        firstFrameSettled: false,
        closed: false
      }
      subscriptions.set(input.slot, entry)
      updateConnection()

      return {
        firstFrame,
        close() {
          if (entry.closed) return
          entry.closed = true
          if (subscriptions.get(input.slot) === entry) {
            subscriptions.delete(input.slot)
          }
          if (!entry.firstFrameSettled) {
            entry.firstFrameSettled = true
            entry.resolveFirstFrame(false)
          }
          updateConnection()
        }
      }
    },

    close() {
      if (closed) return
      closed = true
      for (const entry of subscriptions.values()) {
        entry.closed = true
        if (!entry.firstFrameSettled) {
          entry.firstFrameSettled = true
          entry.resolveFirstFrame(false)
        }
      }
      subscriptions.clear()
      cancelReconnect()
      detachAndCloseSocket()
    }
  }
}
