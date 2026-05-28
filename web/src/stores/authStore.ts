import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface User {
  id: number
  nickname: string
  avatar_url: string
}

interface AuthState {
  token: string | null
  user: User | null
  loading: boolean
  demoLogin: (nickname?: string) => Promise<void>
  fetchUserInfo: () => Promise<void>
  logout: () => void
}

const API_BASE = '/v1'

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      loading: false,

      demoLogin: async (nickname?: string) => {
        set({ loading: true })
        try {
          const res = await fetch(`${API_BASE}/auth/demo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nickname: nickname || '' }),
          })
          const data = await res.json()
          set({ token: data.token, user: data.user, loading: false })
        } catch {
          set({ loading: false })
        }
      },

      fetchUserInfo: async () => {
        const token = get().token
        if (!token) return
        try {
          const res = await fetch(`${API_BASE}/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
          })
          if (res.ok) {
            const data = await res.json()
            set({ user: { id: data.id, nickname: data.nickname, avatar_url: data.avatar_url } })
          }
        } catch {
          // ignore
        }
      },

      logout: () => {
        set({ token: null, user: null })
      },
    }),
    { name: 'island-bells-auth' }
  )
)