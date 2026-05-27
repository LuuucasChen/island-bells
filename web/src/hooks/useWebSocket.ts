import { useEffect, useRef } from 'react'
import { useWsStore } from '../stores/wsStore'
import { useAuthStore } from '../stores/authStore'

export function useWebSocket(roomId: number | null) {
  const connect = useWsStore((s) => s.connect)
  const disconnect = useWsStore((s) => s.disconnect)
  const connected = useWsStore((s) => s.connected)
  const send = useWsStore((s) => s.send)
  const token = useAuthStore((s) => s.token)
  const mountedRef = useRef(false)

  useEffect(() => {
    if (roomId && token && !mountedRef.current) {
      mountedRef.current = true
      connect(roomId, token)
    }
    return () => {
      if (mountedRef.current) {
        mountedRef.current = false
        disconnect()
      }
    }
  }, [roomId, token])

  return { connected, send }
}