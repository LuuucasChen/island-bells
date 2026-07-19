import { create } from 'zustand'
import { useGameStore } from './gameStore'
import { useAuthStore } from './authStore'

/** 连接状态: connecting 表示正在连接/重连中 */
type ConnStatus = 'connected' | 'disconnected' | 'connecting'

interface WsState {
  status: ConnStatus
  /** 兼容旧代码: connected === (status === 'connected') */
  connected: boolean
  /** 是否正在重连 (断线后自动重连中) */
  reconnecting: boolean
  /** 当前重连尝试次数 */
  reconnectAttempts: number
  roomId: number | null
  _ws: WebSocket | null
  _reconnectTimer: ReturnType<typeof setTimeout> | null
  _pingTimer: ReturnType<typeof setInterval> | null
  _token: string | null
  connect: (roomId: number, token: string) => void
  disconnect: () => void
  send: (data: any) => void
}

/** 指数退避: 1s → 2s → 4s → 8s → 16s → 30s(上限) */
function getReconnectDelay(attempts: number): number {
  const delay = Math.min(1000 * Math.pow(2, attempts), 30000)
  // 加随机抖动，避免雷群效应
  return delay + Math.random() * 500
}

const MAX_RECONNECT_ATTEMPTS = 20

export const useWsStore = create<WsState>()((set, get) => ({
  status: 'disconnected',
  connected: false,
  reconnecting: false,
  reconnectAttempts: 0,
  roomId: null,
  _ws: null as WebSocket | null,
  _reconnectTimer: null as ReturnType<typeof setTimeout> | null,
  _pingTimer: null as ReturnType<typeof setInterval> | null,
  _token: null,

  connect: (roomId: number, token: string) => {
    const state = get()

    // 已连接到同一房间，跳过
    if (state._ws && state.roomId === roomId && state.status === 'connected') return

    // 关闭旧连接
    if (state._ws) {
      state._ws.onclose = null  // 防止触发旧 onclose 的重连逻辑
      state._ws.close()
    }
    if (state._reconnectTimer) {
      clearTimeout(state._reconnectTimer)
    }
    if (state._pingTimer) {
      clearInterval(state._pingTimer)
    }

    set({ _token: token, status: 'connecting', connected: false, reconnecting: false, reconnectAttempts: 0 })
    _createConnection(roomId, token)
  },

  disconnect: () => {
    const state = get()
    if (state._reconnectTimer) {
      clearTimeout(state._reconnectTimer)
    }
    if (state._pingTimer) {
      clearInterval(state._pingTimer)
    }
    if (state._ws) {
      state._ws.onclose = null  // 阻止触发重连
      state._ws.close()
    }
    set({
      _ws: null,
      status: 'disconnected',
      connected: false,
      reconnecting: false,
      reconnectAttempts: 0,
      roomId: null,
      _reconnectTimer: null,
      _pingTimer: null,
      _token: null,
    })
  },

  send: (data: any) => {
    const ws = get()._ws
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
    }
  },
}))

/** 内部: 创建 WebSocket 连接并注册事件 */
function _createConnection(roomId: number, token: string) {
  const wsUrl = `/ws/rooms/${roomId}?token=${token}`
  const ws = new WebSocket(wsUrl)

  useWsStore.setState({ _ws: ws, roomId })

  ws.onopen = () => {
    // 连接成功，启动心跳
    const pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 25000) // 每 25 秒发一次心跳

    const wasReconnecting = useWsStore.getState().reconnecting
    useWsStore.setState({
      status: 'connected',
      connected: true,
      reconnecting: false,
      reconnectAttempts: 0,
      _reconnectTimer: null,
      _pingTimer: pingTimer,
    })

    // 重连成功后: 拉取最新游戏状态，追平断线期间的变更
    if (wasReconnecting) {
      const gameRoomId = useGameStore.getState().roomId
      if (gameRoomId) {
        useGameStore.getState().loadGameState(gameRoomId)
      }
    }
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      // 忽略心跳响应，不传入业务层
      if (data.type === 'pong') return
      useGameStore.getState().applyWsUpdate(data)
    } catch { /* ignore */ }
  }

  ws.onclose = (event) => {
    // 4001: 后端鉴权失败 —— 停止重连并登出; 4003: 非房间成员 —— 停止重连
    if (event.code === 4001 || event.code === 4003) {
      const state = useWsStore.getState()
      if (state._pingTimer) {
        clearInterval(state._pingTimer)
      }
      useWsStore.setState({
        status: 'disconnected',
        connected: false,
        reconnecting: false,
        _pingTimer: null,
        roomId: null, // 置空 roomId，阻断 _handleDisconnect 的自动重连
      })
      if (event.code === 4001) {
        useAuthStore.getState().logout()
        if (window.location.pathname !== '/') {
          window.location.href = '/'
        }
      }
      return
    }
    _handleDisconnect(roomId)
  }

  ws.onerror = () => {
    // onerror 后一定会跟一个 onclose，所以这里只做标记
    useWsStore.setState({ status: 'disconnected', connected: false })
  }
}

/** 内部: 断线处理 —— 触发指数退避重连 */
function _handleDisconnect(roomId: number) {
  const state = useWsStore.getState()

  // 清理心跳定时器
  if (state._pingTimer) {
    clearInterval(state._pingTimer)
  }

  // 如果是主动 disconnect (roomId 已被清空)，不重连
  if (useWsStore.getState().roomId === null) return

  const attempts = state.reconnectAttempts

  // 超过最大重连次数，停止重连
  if (attempts >= MAX_RECONNECT_ATTEMPTS) {
    useWsStore.setState({ status: 'disconnected', connected: false, reconnecting: false })
    return
  }

  const delay = getReconnectDelay(attempts)
  useWsStore.setState({
    status: 'connecting',
    connected: false,
    reconnecting: true,
    reconnectAttempts: attempts + 1,
    _pingTimer: null,
  })

  const timer = setTimeout(() => {
    const token = useWsStore.getState()._token
    if (token && useWsStore.getState().roomId === roomId) {
      _createConnection(roomId, token)
    }
  }, delay)

  useWsStore.setState({ _reconnectTimer: timer })
}