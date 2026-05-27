import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Button, Card } from 'animal-island-ui'
import { CONCEPT_TERMS, ROOM_STATUS_TERMS, formatBells } from '@/utils/terms'
import { SEAT_NUMBERS } from '@/utils/constants'
import { useGameStore } from '@/stores/gameStore'
import { useAuthStore } from '@/stores/authStore'
import { useApi } from '@/hooks/useApi'
import { useWebSocket } from '@/hooks/useWebSocket'
import './IslandLobby.css'

interface SeatInfo {
  seat_number: number
  user_id: number | null
  nickname: string | null
  chip_count: number | null
}

function IslandLobby() {
  const { code } = useParams<{ code: string }>()
  const navigate = useNavigate()
  const api = useApi()
  const game = useGameStore()
  const token = useAuthStore((s) => s.token)
  const [seats, setSeats] = useState<SeatInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [sitLoading, setSitLoading] = useState<number | null>(null)
  const [joined, setJoined] = useState(false)
  const [error, setError] = useState(false)
  const [showCopyToast, setShowCopyToast] = useState(false)

  // WS 连接（roomId 为 0 时不会建立连接，loadRoom 后会更新）
  useWebSocket(game.roomId || null)
  const lobbyVersion = useGameStore((s) => s.lobbyVersion)
  const prevLobbyVersion = useRef(0)

  const loadRoom = async () => {
    if (!code) return
    try {
      await game.loadRoom(code)
      const { roomId: currentRoomId } = useGameStore.getState()
      if (!currentRoomId) {
        setError(true)
        setLoading(false)
        return
      }
      const playersData = await api.get(`/rooms/${currentRoomId}/players`)
      const players = playersData.players || []
      const seatData: SeatInfo[] = SEAT_NUMBERS.map((num) => {
        const player = players.find((p: any) => p.seat_number === num)
        return {
          seat_number: num,
          user_id: player?.user_id ?? null,
          nickname: player?.nickname ?? null,
          chip_count: player?.chip_count ?? null,
        }
      })
      setSeats(seatData)
      const { myUserId: currentMyUserId, roomStatus: currentStatus } = useGameStore.getState()
      const isAlreadyJoined = players.some((p: any) => p.user_id === currentMyUserId)
      setJoined(isAlreadyJoined)
      setError(false)
      if (currentStatus === 'playing') {
        navigate(`/game/${currentRoomId}`)
      }
    } catch (e) {
      console.error('加载岛屿信息失败:', e)
      setError(true)
    }
    setLoading(false)
  }

  useEffect(() => {
    if (!code || !token) return
    let cancelled = false

    const doLoad = async () => {
      try {
        await game.loadRoom(code)
        if (cancelled) return
        const { roomId: currentRoomId } = useGameStore.getState()
        if (!currentRoomId) { setError(true); setLoading(false); return }
        const playersData = await api.get(`/rooms/${currentRoomId}/players`)
        if (cancelled) return
        const players = playersData.players || []
        const seatData: SeatInfo[] = SEAT_NUMBERS.map((num) => {
          const player = players.find((p: any) => p.seat_number === num)
          return { seat_number: num, user_id: player?.user_id ?? null, nickname: player?.nickname ?? null, chip_count: player?.chip_count ?? null }
        })
        setSeats(seatData)
        const { myUserId: currentMyUserId, roomStatus: currentStatus } = useGameStore.getState()
        setJoined(players.some((p: any) => p.user_id === currentMyUserId))
        setError(false)
        if (currentStatus === 'playing') navigate(`/game/${currentRoomId}`)
      } catch (e) {
        if (!cancelled) { console.error('加载岛屿信息失败:', e); setError(true) }
      }
      if (!cancelled) setLoading(false)
    }

    doLoad()
    return () => { cancelled = true }
  }, [code, token])

  const handleJoin = async () => {
    if (error) return
    try {
      await api.post(`/rooms/${code}/join`, {})
      setJoined(true)
      await loadRoom()
    } catch (e) {
      console.error('加入岛屿失败:', e)
      setError(true)
    }
  }

  const joinAttempted = useRef(false)
  useEffect(() => {
    if (!loading && !joined && !error && code && !joinAttempted.current) {
      joinAttempted.current = true
      handleJoin()
    }
  }, [loading, joined, error])

  useEffect(() => {
    if (lobbyVersion > prevLobbyVersion.current) {
      prevLobbyVersion.current = lobbyVersion
      if (game.roomStatus === 'playing' && game.roomId) {
        navigate(`/game/${game.roomId}`)
      } else if (!loading && !error && game.roomId) {
        loadRoom()
      }
    }
  }, [lobbyVersion, game.roomStatus, game.roomId])

  const handleSit = async (seatNumber: number) => {
    if (!joined) {
      await handleJoin()
    }
    setSitLoading(seatNumber)
    try {
      await game.sit(game.roomId, seatNumber)
      await loadRoom()
    } catch (e) {
      alert('登岛失败')
    }
    setSitLoading(null)
  }

  const handleStart = async () => {
    try {
      await game.startGame(game.roomId)
      navigate(`/game/${game.roomId}`)
    } catch (e) {
      alert('开始失败: ' + (e as Error).message)
    }
  }

  const isOwner = game.isOwner
  const myUserId = game.myUserId
  const seatedPlayers = seats.filter((s) => s.user_id !== null)
  const roomName = game.roomName || '未知岛屿'

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(game.roomCode || '')
      setShowCopyToast(true)
      setTimeout(() => setShowCopyToast(false), 3000)
    } catch {
      // fallback
      const ta = document.createElement('textarea')
      ta.value = game.roomCode || ''
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setShowCopyToast(true)
      setTimeout(() => setShowCopyToast(false), 3000)
    }
  }

  if (loading) {
    return <Layout title="岛屿大厅" back><div className="app-empty">正在加载...</div></Layout>
  }

  if (error) {
    return (
      <Layout title="岛屿大厅" back>
        <div className="app-empty">
          <div style={{ fontSize: 36, marginBottom: 12 }}>🏝️</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#794f27', marginBottom: 8 }}>岛屿不存在或已关闭</div>
          <div style={{ fontSize: 13, color: '#9f927d', marginBottom: 20 }}>请检查渡渡鸟码是否正确</div>
          <Button type="primary" onClick={() => navigate('/')}>返回首页</Button>
        </div>
      </Layout>
    )
  }

  return (
    <Layout
      title={roomName}
      back
      right={isOwner ? (
        <button className="lobby-start-btn" onClick={handleStart}>开始游戏</button>
      ) : undefined}
    >
      {/* 岛屿信息卡 — 包含渡渡鸟码 */}
      <Card color="app-teal" style={{ marginBottom: 20 }}>
        <div className="lobby-island-header">
          <span className="lobby-island-icon">🏝️</span>
          <div className="lobby-island-info">
            <div className="lobby-island-name">{roomName}</div>
            <div className="lobby-island-meta">
              {ROOM_STATUS_TERMS[game.roomStatus] || game.roomStatus}
              <span className="lobby-dot">·</span>
              {seatedPlayers.length} 位居民
              <span className="lobby-dot">·</span>
              初始 {formatBells(game.initialChips || 10000)} 🔔
            </div>
          </div>
        </div>
        {/* 渡渡鸟码 — 卡片内分隔线下方 */}
        <div className="lobby-code-row">
          <span className="lobby-code-label">✈️ 渡渡鸟码</span>
          <strong className="lobby-code-value">{game.roomCode}</strong>
          <button className="lobby-copy-btn" onClick={handleCopyCode} title="复制渡渡鸟码">📋</button>
        </div>
      </Card>

      {/* 复制成功 toast */}
      {showCopyToast && (
        <div className="lobby-copy-toast">✅ 已复制渡渡鸟码</div>
      )}

      {/* 座位区 */}
      <div className="lobby-section-title">🪑 岛屿座位</div>
      <div className="seats-grid">
        {seats.map((seat) => {
          const isMe = seat.user_id === myUserId
          const isOccupied = seat.user_id !== null

          return (
            <div
              key={seat.seat_number}
              className={`seat-card ${isOccupied ? (isMe ? 'seat-mine' : '') : 'seat-empty'}`}
              onClick={!isOccupied && joined ? () => handleSit(seat.seat_number) : undefined}
            >
              {isOccupied ? (
                <>
                  <div className="seat-nickname">{seat.nickname}</div>
                  <div className="seat-bells">🔔 {formatBells(seat.chip_count!)}</div>
                </>
              ) : (
                <div className="seat-plus">+ 登岛</div>
              )}
              {sitLoading === seat.seat_number && <div className="seat-loading">...</div>}
            </div>
          )
        })}
      </div>

      {seatedPlayers.some((s) => s.user_id === myUserId) && !isOwner && seatedPlayers.length >= 2 && (
        <div className="app-empty" style={{ marginTop: 16 }}>
          等待岛主开始游戏...
        </div>
      )}
    </Layout>
  )
}

export default IslandLobby