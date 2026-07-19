import { create } from 'zustand'
import { useAuthStore } from './authStore'

interface CardData {
  suit: 'spades' | 'hearts' | 'diamonds' | 'clubs'
  rank: number
}

interface Player {
  player_id: number
  user_id: number
  nickname: string
  avatar_url: string
  seat_number: number
  chip_count: number
  bet_this_round: number
  is_folded: boolean
  role: string | null
}

interface Pot {
  pot_id: number
  pot_type: string
  pot_level: number
  amount: number
}

interface Evaluation {
  hand_type: number
  hand_type_name: string
  score?: number[]
}

interface HandState {
  hand_id: number
  hand_number: number
  current_round: string
  status: string
  pot_total: number
  turn_player_id: number | null
  /** 本轮最小加注增量 (后端与下注校验同一口径) */
  min_raise?: number
  pots: Pot[]
  players: Player[]
  bets: any[]
  community_cards: CardData[]
  my_hole_cards: CardData[]
  all_hole_cards: Record<string, CardData[]>
  evaluations: Record<string, Evaluation>
  ended_by_fold: boolean
  muck_player_id: number | null
  last_aggressor_id: number | null
  revealed_players: number[]
  mucked_players: number[]
  /** 我的实时牌型评估 (flop/turn/river 时后端计算，preflop 时为 null) */
  my_evaluation: { hand_type: number; hand_type_name: string } | null
}

interface GameState {
  roomId: number
  roomCode: string
  roomName: string
  roomStatus: string
  ownerId: number
  bbAmount: number
  initialChips: number
  currentHand: HandState | null
  myUserId: number
  isOwner: boolean
  lobbyVersion: number  // 用于触发 lobby 重新加载
  settleResults: { winner_id: number; amount_won: number; is_split: number }[] | null
  /** 触发 showdown 翻牌动画 (由 WS round_advance 设置) */
  showdownReveal: boolean
  /** 牌局因 fold 结束 (WS 传入) */
  endedByFold: boolean
  /** 最终结算数据 (牌局结束时) */
  finalSettlement: SettlementItem[] | null
  /** 最近一次已结算的牌局 id (用于前端「牌局回顾」按钮) */
  lastSettledHandId: number | null
  /** 每个玩家最近一次操作 (用于界面展示 check/call/raise 等) */
  playerActions: Record<number, { action: string; amount: number }>

  loadRoom: (code: string) => Promise<void>
  loadGameState: (roomId: number) => Promise<void>
  sit: (roomId: number, seatNumber: number) => Promise<void>
  stand: (roomId: number) => Promise<void>
  startGame: (roomId: number) => Promise<void>
  applyWsUpdate: (data: any) => void
  /** 加载最近一次已结算牌局的完整回顾数据 */
  loadHistoryHand: (handId: number) => Promise<HistoryHand>
  reset: () => void
}

/** 牌局回顾数据结构 (后端 GET /v1/hands/{id} 返回) */
export interface HistoryHand {
  hand_id: number
  hand_number: number
  status: string
  pot_total: number
  community_cards: CardData[]
  my_hole_cards: CardData[]
  all_hole_cards: Record<string, CardData[]>
  evaluations: Record<string, { hand_type: number; hand_type_name: string }>
  players: {
    player_id: number
    user_id: number
    nickname: string
    avatar_url: string
    seat_number: number
    chip_count: number
    bet_this_round: number
    is_folded: boolean
    role: string | null
  }[]
  results: { winner_id: number; amount_won: number; is_split: number }[]
  bets: { player_id: number; amount: number }[]
  ended_by_fold: boolean
  muck_player_id: number | null
}

export interface SettlementItem {
  player_id: number
  user_id: number
  nickname: string
  initial_chips: number
  final_chips: number
  rebuy_total: number
  net_profit: number
}

const API_BASE = '/v1'

const getAuthHeaders = () => {
  const token = localStorage.getItem('island-bells-auth')
  if (token) {
    try {
      const parsed = JSON.parse(token)
      return { Authorization: `Bearer ${parsed?.state?.token || ''}`, 'Content-Type': 'application/json' }
    } catch { /* ignore */ }
  }
  return { 'Content-Type': 'application/json' }
}

/** 统一 fetch 封装: 401 (token 失效) 时登出并跳转首页，各调用点无需重复处理 */
const apiFetch = async (url: string, options: RequestInit = {}): Promise<Response> => {
  const res = await fetch(url, { ...options, headers: getAuthHeaders() })
  if (res.status === 401) {
    useAuthStore.getState().logout()
    if (window.location.pathname !== '/') {
      window.location.href = '/'
    }
    throw new Error('登录已过期，请重新登录')
  }
  return res
}

// loadGameState 请求序号: 只允许最新一次请求的响应写入 store，避免旧快照覆盖新状态
let loadGameStateSeq = 0

export const useGameStore = create<GameState>()((set, get) => ({
  roomId: 0,
  roomCode: '',
  roomName: '',
  roomStatus: '',
  ownerId: 0,
  currentHand: null,
  myUserId: 0,
  isOwner: false,
  lobbyVersion: 0,
  bbAmount: 0,
  initialChips: 0,
  settleResults: null,
  showdownReveal: false,
  endedByFold: false,
  finalSettlement: null,
  lastSettledHandId: null,
  playerActions: {},

  loadRoom: async (code: string) => {
    // 进入不同房间时，清空上一房间的对局残留 (settleResults/showdownReveal 等)，防止污染新房间
    if (get().roomCode && get().roomCode !== code) {
      set({
        currentHand: null,
        settleResults: null,
        showdownReveal: false,
        endedByFold: false,
        finalSettlement: null,
        lastSettledHandId: null,
        playerActions: {},
      })
    }
    const res = await apiFetch(`${API_BASE}/rooms/${code}`)
    if (!res.ok) {
      throw new Error(`房间加载失败 (${res.status})`)
    }
    const data = await res.json()
    const authData = JSON.parse(localStorage.getItem('island-bells-auth') || '{}')
    const myUserId = authData?.state?.user?.id || 0
    set({
      roomId: data.room_id,
      roomCode: data.room_code,
      roomName: data.name || '',
      roomStatus: data.status,
      ownerId: data.owner_id,
      myUserId,
      isOwner: data.owner_id === myUserId,
      initialChips: data.initial_chips || 10000,
    })
  },

  loadGameState: async (roomId: number) => {
    const reqId = ++loadGameStateSeq
    const res = await apiFetch(`${API_BASE}/rooms/${roomId}/state`)
    if (!res.ok) {
      throw new Error(`游戏状态加载失败 (${res.status})`)
    }
    const data = await res.json()
    // 已有更新的请求发出，丢弃这份旧快照，避免覆盖新状态
    if (reqId !== loadGameStateSeq) return
    // 设置 owner 信息（如果 API 返回了）
    if (data.owner_id) {
      const authData = JSON.parse(localStorage.getItem('island-bells-auth') || '{}')
      const myUserId = authData?.state?.user?.id || 0
      set({
        ownerId: data.owner_id,
        myUserId,
        isOwner: data.owner_id === myUserId,
      })
    }
    const prevRoomId = get().roomId
    set({
      roomId: roomId,
      // state 响应不含 room_code 字段: 同房间时保留已有值；跨房间/刷新时置空，
      // 由调用方 (如 handleStand) 对空 roomCode 做兜底
      roomCode: data.room_code || (prevRoomId === roomId ? get().roomCode : ''),
      roomName: data.room_name || '',
      roomStatus: data.room_status,
      currentHand: data.current_hand,
      bbAmount: data.bb_amount || 0,
      initialChips: data.initial_chips || 0,
      finalSettlement: data.final_settlement || null,
      lastSettledHandId: data.last_settled_hand_id ?? null,
    })
  },

  sit: async (roomId: number, seatNumber: number) => {
    const res = await apiFetch(`${API_BASE}/rooms/${roomId}/sit`, {
      method: 'POST',
      body: JSON.stringify({ seat_number: seatNumber }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || '入座失败')
    }
    await get().loadGameState(roomId)
  },

  stand: async (roomId: number) => {
    const res = await apiFetch(`${API_BASE}/rooms/${roomId}/stand`, {
      method: 'POST',
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || '站起失败')
    }
    await get().loadGameState(roomId)
  },

  startGame: async (roomId: number) => {
    const res = await apiFetch(`${API_BASE}/rooms/${roomId}/start`, {
      method: 'POST',
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || '开始游戏失败')
    }
    await get().loadGameState(roomId)
  },

  applyWsUpdate: (data: any) => {
    if (data.type === 'round_advance') {
      const wsData = data.data || {}
      // 清空上一轮的操作记录，避免跨轮残留 (只保留触发推进的操作)
      const actions: Record<number, { action: string; amount: number }> = {}
      if (wsData.player_id && wsData.action) {
        actions[wsData.player_id] = {
          action: wsData.action,
          amount: wsData.amount || 0,
        }
      }
      set({ playerActions: actions })
      // 先把 WS payload 里的轮次/公共牌写入 store，避免 loadGameState 返回前
      // 公共牌张数仍是旧值导致翻牌动画按旧张数启动、张数更新后动画重启闪烁
      const ch = get().currentHand
      if (ch && (!wsData.hand_id || wsData.hand_id === ch.hand_id)) {
        set({
          currentHand: {
            ...ch,
            current_round: wsData.current_round || ch.current_round,
            status: wsData.status || ch.status,
            pot_total: wsData.pot_total ?? ch.pot_total,
            ...(Array.isArray(wsData.community_cards)
              ? { community_cards: wsData.community_cards }
              : {}),
            ...(wsData.ended_by_fold !== undefined
              ? { ended_by_fold: !!wsData.ended_by_fold }
              : {}),
          },
        })
      }
      // 进入 showdown: 触发翻牌动画
      if (wsData.status === 'settling') {
        set({ showdownReveal: true, endedByFold: !!wsData.ended_by_fold })
      }
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'game_update') {
      // Bug fix: 记录玩家操作 (用于展示 check 等动作)
      if (data.data?.player_id && data.data?.action) {
        const actions = { ...get().playerActions }
        actions[data.data.player_id] = {
          action: data.data.action,
          amount: data.data.amount || 0,
        }
        set({ playerActions: actions })
      }
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'new_hand') {
      // BUG-1 修复: new_hand 时重置 showdownReveal，避免跨手牌残留
      set({ showdownReveal: false, endedByFold: false, playerActions: {} })
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'hand_settled') {
      // 存储结算结果
      if (data.data?.results) {
        set({ settleResults: data.data.results, showdownReveal: false })
      }
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'game_started') {
      set({ roomStatus: 'playing', settleResults: null, showdownReveal: false, endedByFold: false })
      // lobbyVersion 增加触发 lobby 跳转（由组件监听）
      set({ lobbyVersion: get().lobbyVersion + 1 })
    } else if (data.type === 'player_joined' || data.type === 'player_sat') {
      // 触发 lobby 重新加载座位
      set({ lobbyVersion: get().lobbyVersion + 1 })
    } else if (data.type === 'muck_chosen') {
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'player_revealed') {
      // Showdown 亮牌/盖牌事件: 刷新游戏状态
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'rebuy') {
      // 其他玩家补给铃钱: 刷新游戏状态 (与其他状态变更一致)
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'game_ended') {
      // 牌局结束: 存储最终结算数据
      if (data.data?.settlement) {
        set({ finalSettlement: data.data.settlement, roomStatus: 'finished' })
      }
      const roomId = get().roomId
      get().loadGameState(roomId)
    } else if (data.type === 'manual_sync') {
      // 任意玩家触发的手动同步，房间内所有人重新拉取最新状态
      // 不修改 showdownReveal / endedByFold 等任何 Showdown 字段，避免误触发翻牌动画
      const roomId = get().roomId
      get().loadGameState(roomId)
    }
  },

  loadHistoryHand: async (handId: number) => {
    // 加载指定牌局的完整回顾数据 (公共牌 / 所有人手牌 / 牌力评估 / 收获汇总)
    const res = await apiFetch(`${API_BASE}/hands/${handId}`)
    if (!res.ok) {
      throw new Error(`牌局回顾加载失败 (${res.status})`)
    }
    const data = await res.json()
    return {
      hand_id: data.hand_id,
      hand_number: data.hand_number,
      status: data.status,
      pot_total: data.pot_total,
      community_cards: data.community_cards || [],
      my_hole_cards: data.my_hole_cards || [],
      all_hole_cards: data.all_hole_cards || {},
      evaluations: data.evaluations || {},
      players: data.players || [],
      results: (data.results || []).map((r: any) => ({
        winner_id: r.winner_id,
        amount_won: r.amount_won,
        is_split: r.is_split ? 1 : 0,
      })),
      bets: (data.bets || []).map((b: any) => ({
        player_id: b.player_id,
        amount: b.amount,
      })),
      ended_by_fold: !!data.ended_by_fold,
      muck_player_id: data.muck_player_id ?? null,
    }
  },

  reset: () => {
    set({
      roomId: 0,
      roomCode: '',
      roomName: '',
      roomStatus: '',
      ownerId: 0,
      currentHand: null,
      isOwner: false,
      lobbyVersion: 0,
      bbAmount: 0,
      initialChips: 0,
      settleResults: null,
      showdownReveal: false,
      endedByFold: false,
      finalSettlement: null,
      lastSettledHandId: null,
      playerActions: {},
    })
  },
}))
