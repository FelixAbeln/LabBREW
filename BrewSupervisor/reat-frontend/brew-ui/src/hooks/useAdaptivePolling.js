import { useEffect, useRef } from 'react'

export function useAdaptivePolling({ enabled, task, getDelay }) {
  const taskRef = useRef(task)
  const getDelayRef = useRef(getDelay)

  useEffect(() => {
    taskRef.current = task
  }, [task])

  useEffect(() => {
    getDelayRef.current = getDelay
  }, [getDelay])

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let inFlight = false
    let timeoutId = null

    const schedule = (delayMs) => {
      const delay = Math.max(250, Number(delayMs) || 1000)
      timeoutId = window.setTimeout(run, delay)
    }

    const run = async () => {
      if (cancelled) return

      if (inFlight) {
        schedule(getDelayRef.current())
        return
      }

      inFlight = true
      try {
        await taskRef.current()
      } finally {
        inFlight = false
        if (!cancelled) {
          schedule(getDelayRef.current())
        }
      }
    }

    run()

    return () => {
      cancelled = true
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId)
      }
    }
  }, [enabled])
}
