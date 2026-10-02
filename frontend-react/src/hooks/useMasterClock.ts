import { useCallback, useEffect, useRef, useState } from "react"

import { MasterPlaybackClock, type MasterClockState } from "../playback/masterClock"

/**
 * Drives a `MasterPlaybackClock` from an animation frame loop.
 *
 * The clock object itself is imperative and framework-free; this hook only
 * republishes it into React state so the timeline playhead moves. The frame
 * loop is deliberately *not* a `setInterval`: the clock already derives its
 * position from `performance.now()`, so the loop only has to cause a repaint,
 * and running it while paused would burn frames for a playhead that cannot
 * move.
 */
export interface UseMasterClock {
  /** Current position in milliseconds. */
  currentMs: number
  state: MasterClockState
  playbackRate: number
  play: (atMs?: number, rate?: number) => void
  pause: () => void
  toggle: () => void
  seek: (atMs: number) => void
  setRate: (rate: number) => void
}

export function useMasterClock(initialMs: number): UseMasterClock {
  const clockRef = useRef<MasterPlaybackClock | null>(null)
  if (clockRef.current === null) {
    clockRef.current = new MasterPlaybackClock(initialMs)
  }
  const clock = clockRef.current

  const [currentMs, setCurrentMs] = useState(initialMs)
  const [state, setState] = useState<MasterClockState>(clock.state)
  const [playbackRate, setPlaybackRate] = useState(clock.playbackRate)
  const frameRef = useRef<number | null>(null)

  const stopLoop = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }, [])

  const startLoop = useCallback(() => {
    if (frameRef.current !== null) return
    const tick = () => {
      setCurrentMs(clock.currentTimeMs())
      frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
  }, [clock])

  useEffect(() => stopLoop, [stopLoop])

  // Seeking parks the clock in `seeking` until playback resumes, so the loop
  // has to stop or it would repaint a frozen playhead at full frame rate.
  useEffect(() => {
    if (state === "playing") startLoop()
    else stopLoop()
  }, [state, startLoop, stopLoop])

  const play = useCallback(
    (atMs?: number, rate?: number) => {
      clock.play(atMs, rate)
      setState(clock.state)
      setPlaybackRate(clock.playbackRate)
      setCurrentMs(clock.currentTimeMs())
    },
    [clock],
  )

  const pause = useCallback(() => {
    clock.pause()
    setState(clock.state)
    setCurrentMs(clock.currentTimeMs())
  }, [clock])

  const seek = useCallback(
    (atMs: number) => {
      clock.seek(atMs)
      setState(clock.state)
      setCurrentMs(atMs)
    },
    [clock],
  )

  const setRate = useCallback(
    (rate: number) => {
      clock.setPlaybackRate(rate)
      setPlaybackRate(clock.playbackRate)
      setCurrentMs(clock.currentTimeMs())
    },
    [clock],
  )

  const toggle = useCallback(() => {
    if (clock.state === "playing") pause()
    else play()
  }, [clock, pause, play])

  return {
    currentMs,
    state,
    playbackRate,
    play,
    pause,
    toggle,
    seek,
    setRate,
  }
}
