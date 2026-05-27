import { create } from 'zustand'
import { useGameStore } from './gameStore'

interface WsState {
  connected: boolean
  roomId: number | null
  _ws: WebSocket | null
  connect: (roomId: number, token: string) => void
  disconnect: () => void
  send: (data: any) => void
}

export const useWsStore = create<WsState>()((set, get) => ({
  connected: false,
  roomId: null,
  _ws: null as WebSocket | null,

  connect: (roomId: number, token: string) => {
    const existing = get()._ws
    if (existing && get().roomId === roomId) return

    if (existing) {
      existing.close()
    }

    const wsUrl = `/ws/rooms/${roomId}?token=${token}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      set({ connected: true, roomId })
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        useGameStore.getState().applyWsUpdate(data)
      } catch { /* ignore */ }
    }

    ws.onclose = () => {
      set({ connected: false })
    }

    ws.onerror = () => {
      set({ connected: false })
    }

    set({ _ws: ws, roomId })
  },

  disconnect: () => {
    const ws = get()._ws
    if (ws) {
      ws.close()
    }
    set({ _ws: null, connected: false, roomId: null })
  },

  send: (data: any) => {
    const ws = get()._ws
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
    }
  },
}))