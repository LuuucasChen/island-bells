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
  /** 登录失败错误信息 (demoLogin 失败时设置，不静默写空 token) */
  error: string | null
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
      error: null,

      demoLogin: async (nickname?: string) => {
        set({ loading: true, error: null })
        try {
          const res = await fetch(`${API_BASE}/auth/demo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nickname: nickname || '' }),
          })
          if (!res.ok) {
            set({ loading: false, error: `登录失败 (${res.status})` })
            return
          }
          const data = await res.json()
          if (!data?.token) {
            // 响应异常: 不写入空 token，记录错误态
            set({ loading: false, error: '登录失败：未获取到令牌' })
            return
          }
          set({ token: data.token, user: data.user, loading: false, error: null })
        } catch {
          set({ loading: false, error: '登录失败：网络错误' })
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