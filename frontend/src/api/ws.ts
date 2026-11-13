import { useEffect, useRef, useState } from 'react'
import type { LiveEvent } from '../types'
import { API_URL } from './client'

const WS_URL = API_URL.replace(/^http/, 'ws') + '/ws'

/** Subscribe to live backend events; reconnects automatically. */
export function useLiveEvents(onEvent: (event: LiveEvent) => void): boolean {
  const [connected, setConnected] = useState(false)
  const handler = useRef(onEvent)
  useEffect(() => {
    handler.current = onEvent
  })

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let closed = false

    const connect = () => {
      ws = new WebSocket(WS_URL)
      ws.onopen = () => setConnected(true)
      ws.onmessage = (msg) => handler.current(JSON.parse(msg.data) as LiveEvent)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = setTimeout(connect, 2000)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return connected
}
