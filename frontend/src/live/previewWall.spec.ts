import { describe, expect, it, vi } from "vitest"

import {
  createLivePreviewWallClient,
  type PreviewWallListener
} from "./previewWall"


class FakeWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  binaryType: BinaryType = "blob"
  readyState = FakeWebSocket.CONNECTING
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readonly sent: string[] = []
  closeCount = 0

  constructor(readonly url: string) {}

  open(): void {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.(new Event("open"))
  }

  message(data: string | ArrayBuffer): void {
    this.onmessage?.(new MessageEvent("message", { data }))
  }

  disconnect(): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.(new CloseEvent("close"))
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closeCount += 1
    this.readyState = FakeWebSocket.CLOSED
  }
}


function listener(): PreviewWallListener {
  return {
    onFrame: vi.fn(),
    onReady: vi.fn(),
    onError: vi.fn(),
    onReconnecting: vi.fn()
  }
}


function encodedFrame(
  slot: number,
  subscriptionId: number,
  jpeg = new Uint8Array([0xff, 0xd8, 1, 2, 0xff, 0xd9])
): ArrayBuffer {
  const frame = new Uint8Array(6 + jpeg.length)
  frame[0] = 1
  frame[1] = slot
  new DataView(frame.buffer).setUint32(2, subscriptionId)
  frame.set(jpeg, 6)
  return frame.buffer
}


async function flushMicrotasks(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
}


describe("preview wall client synchronization", () => {
  it("uses one socket for nine and sixteen subscriptions", async () => {
    const sockets: FakeWebSocket[] = []
    const client = createLivePreviewWallClient({
      createWebSocket: (url) => {
        const socket = new FakeWebSocket(url)
        sockets.push(socket)
        return socket
      }
    })
    client.setLayout(9)
    const registrations = Array.from({ length: 9 }, (_, slot) =>
      client.subscribe(
        {
          slot,
          cameraId: `00000000-0000-0000-0000-${String(slot + 1).padStart(12, "0")}`,
          mediaSessionId: `10000000-0000-0000-0000-${String(slot + 1).padStart(12, "0")}`
        },
        listener()
      )
    )

    expect(sockets).toHaveLength(1)
    expect(sockets[0].url).toBe(
      "ws://localhost:3000/api/v1/live/previews/ws"
    )
    expect(sockets[0].binaryType).toBe("arraybuffer")
    sockets[0].open()
    await flushMicrotasks()

    let sync = JSON.parse(sockets[0].sent.at(-1) ?? "null")
    expect(sync.layout_slots).toBe(9)
    expect(sync.streams).toHaveLength(9)
    expect(
      sync.streams.every(
        (item: { subscription_id: number }) =>
          Number.isInteger(item.subscription_id) &&
          item.subscription_id >= 0 &&
          item.subscription_id <= 0xffffffff
      )
    ).toBe(true)

    client.setLayout(16)
    for (let slot = 9; slot < 16; slot += 1) {
      registrations.push(
        client.subscribe(
          {
            slot,
            cameraId: `00000000-0000-0000-0000-${String(slot + 1).padStart(12, "0")}`,
            mediaSessionId: `10000000-0000-0000-0000-${String(slot + 1).padStart(12, "0")}`
          },
          listener()
        )
      )
    }
    await flushMicrotasks()

    expect(sockets).toHaveLength(1)
    sync = JSON.parse(sockets[0].sent.at(-1) ?? "null")
    expect(sync.layout_slots).toBe(16)
    expect(sync.streams).toHaveLength(16)

    const previousId = sync.streams[0].subscription_id
    registrations[0].close()
    const replacement = client.subscribe(
      {
        slot: 0,
        cameraId: "20000000-0000-0000-0000-000000000001",
        mediaSessionId: "30000000-0000-0000-0000-000000000001"
      },
      listener()
    )
    await flushMicrotasks()
    sync = JSON.parse(sockets[0].sent.at(-1) ?? "null")
    expect(sync.streams[0].subscription_id).not.toBe(previousId)

    replacement.close()
    await flushMicrotasks()
    sync = JSON.parse(sockets[0].sent.at(-1) ?? "null")
    expect(
      sync.streams.some((item: { slot: number }) => item.slot === 0)
    ).toBe(false)

    client.close()
  })

  it("routes only current ready errors and complete JPEG frames", async () => {
    const sockets: FakeWebSocket[] = []
    const firstListener = listener()
    const secondListener = listener()
    const client = createLivePreviewWallClient({
      createWebSocket: (url) => {
        const socket = new FakeWebSocket(url)
        sockets.push(socket)
        return socket
      }
    })
    client.setLayout(4)
    const first = client.subscribe(
      {
        slot: 2,
        cameraId: "00000000-0000-0000-0000-000000000001",
        mediaSessionId: "10000000-0000-0000-0000-000000000001"
      },
      firstListener
    )
    sockets[0].open()
    await flushMicrotasks()
    const firstId = JSON.parse(sockets[0].sent.at(-1) ?? "null")
      .streams[0].subscription_id as number

    sockets[0].message(
      JSON.stringify({
        type: "ready",
        slot: 2,
        subscription_id: firstId
      })
    )
    expect(firstListener.onReady).toHaveBeenCalledOnce()
    sockets[0].message(
      JSON.stringify({
        type: "ready",
        slot: 2,
        subscription_id: (firstId + 1) >>> 0
      })
    )
    expect(firstListener.onReady).toHaveBeenCalledOnce()

    const second = client.subscribe(
      {
        slot: 2,
        cameraId: "00000000-0000-0000-0000-000000000002",
        mediaSessionId: "10000000-0000-0000-0000-000000000002"
      },
      secondListener
    )
    await flushMicrotasks()
    const secondId = JSON.parse(sockets[0].sent.at(-1) ?? "null")
      .streams[0].subscription_id as number

    sockets[0].message(encodedFrame(2, firstId))
    expect(firstListener.onFrame).not.toHaveBeenCalled()
    expect(secondListener.onFrame).not.toHaveBeenCalled()

    sockets[0].message(new Uint8Array([1, 2]).buffer)
    sockets[0].message(encodedFrame(2, secondId, new Uint8Array([1, 2])))
    sockets[0].message(encodedFrame(2, secondId))
    expect(secondListener.onFrame).toHaveBeenCalledOnce()
    const delivered = vi.mocked(secondListener.onFrame).mock.calls[0][0]
    expect(delivered.type).toBe("image/jpeg")
    await expect(second.firstFrame).resolves.toBe(true)

    sockets[0].message(
      JSON.stringify({
        type: "error",
        slot: 2,
        subscription_id: secondId,
        message: "Camera is offline."
      })
    )
    expect(secondListener.onError).toHaveBeenCalledWith(
      "Camera is offline."
    )

    const thirdListener = listener()
    const third = client.subscribe(
      {
        slot: 2,
        cameraId: "00000000-0000-0000-0000-000000000003",
        mediaSessionId: "10000000-0000-0000-0000-000000000003"
      },
      thirdListener
    )
    await flushMicrotasks()
    const thirdId = JSON.parse(sockets[0].sent.at(-1) ?? "null")
      .streams[0].subscription_id as number
    sockets[0].message(
      JSON.stringify({
        type: "error",
        slot: 2,
        subscription_id: thirdId,
        message: "Session expired."
      })
    )
    await expect(third.firstFrame).resolves.toBe(false)
    expect(thirdListener.onError).toHaveBeenCalledWith("Session expired.")
    client.close()
  })

  it("reconnects with bounded backoff and current subscriptions only", async () => {
    vi.useFakeTimers()
    try {
      const sockets: FakeWebSocket[] = []
      const activeListener = listener()
      const client = createLivePreviewWallClient({
        createWebSocket: (url) => {
          const socket = new FakeWebSocket(url)
          sockets.push(socket)
          return socket
        }
      })
      client.setLayout(9)
      client.setLayout(16)
      client.setLayout(9)
      const old = client.subscribe(
        {
          slot: 0,
          cameraId: "00000000-0000-0000-0000-000000000001",
          mediaSessionId: "10000000-0000-0000-0000-000000000001"
        },
        activeListener
      )
      expect(sockets).toHaveLength(1)
      sockets[0].open()
      sockets[0].disconnect()
      expect(activeListener.onReconnecting).toHaveBeenCalledOnce()

      client.subscribe(
        {
          slot: 1,
          cameraId: "00000000-0000-0000-0000-000000000002",
          mediaSessionId: "10000000-0000-0000-0000-000000000002"
        },
        activeListener
      )
      old.close()
      await vi.advanceTimersByTimeAsync(999)
      expect(sockets).toHaveLength(1)
      await vi.advanceTimersByTimeAsync(1)
      expect(sockets).toHaveLength(2)
      sockets[1].open()
      await flushMicrotasks()
      let sync = JSON.parse(sockets[1].sent.at(-1) ?? "null")
      expect(sync.streams.map((item: { slot: number }) => item.slot)).toEqual([
        1
      ])

      sockets[1].disconnect()
      for (const [index, delay] of [2000, 4000, 8000, 15000].entries()) {
        await vi.advanceTimersByTimeAsync(delay - 1)
        expect(sockets).toHaveLength(index + 2)
        await vi.advanceTimersByTimeAsync(1)
        expect(sockets).toHaveLength(index + 3)
        sockets[index + 2].disconnect()
      }

      client.close()
      const count = sockets.length
      await vi.advanceTimersByTimeAsync(15000)
      expect(sockets).toHaveLength(count)
    } finally {
      vi.useRealTimers()
    }
  })
})
