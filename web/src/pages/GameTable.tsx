import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button } from 'animal-island-ui'
import {
  CONCEPT_TERMS, ROLE_TERMS, formatBells, formatBellsWithIcon,
  getRoundText, getRoundIcon,
} from '@/utils/terms'
import { getCharacterAvatar } from '@/utils/constants'
import { useGameStore } from '@/stores/gameStore'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useApi } from '@/hooks/useApi'
import { PlayingCard } from '@/components/PlayingCard'
import { CommunityCards } from '@/components/CommunityCards'
import { ShowdownModal } from '@/components/ShowdownModal'
import { FinalSettlementModal } from '@/components/FinalSettlementModal'
import './GameTable.css'

type ShowdownPhase = 'idle' | 'revealing' | 'muck_choice' | 'showing_cards' | 'auto_settling' | 'settled'

function GameTable() {
  const { roomId } = useParams<{ roomId: string }>()
  const navigate = useNavigate()
  const api = useApi()
  const game = useGameStore()
  const { connected, reconnecting, reconnectAttempts } = useWebSocket(Number(roomId))

  // Showdown orchestration state
  const [showdownPhase, setShowdownPhase] = useState<ShowdownPhase>('idle')
  const autoSettleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 用 ref 镜像 showdownPhase，轮询/异步回调内读 ref，消除 stale closure
  const showdownPhaseRef = useRef<ShowdownPhase>('idle')
  // 标记「挂载后首次加载就发现已 settling/settled」(刷新进入):
  // 只有这种情况 busted 时才允许自动跳过结算弹窗；正常打完一局必须先展示弹窗
  const settledOnMountRef = useRef(false)
  const firstLoadDoneRef = useRef(false)

  useEffect(() => {
    showdownPhaseRef.current = showdownPhase
  }, [showdownPhase])

  const loadGame = async () => {
    if (!roomId) return
    try {
      await game.loadGameState(Number(roomId))
      // 如果加载时已经是 settling/settled (刷新页面场景)，且当前没有翻牌动画在进行，跳过翻牌
      const h = useGameStore.getState().currentHand
      const isRevealing = useGameStore.getState().showdownReveal
      if (h && (h.status === 'settling' || h.status === 'settled') && showdownPhaseRef.current === 'idle' && !isRevealing) {
        setShowdownPhase('settled')
        if (!firstLoadDoneRef.current) {
          settledOnMountRef.current = true
        }
      }
    } catch {
      // ignore
    }
    firstLoadDoneRef.current = true
  }

  useEffect(() => {
    loadGame()
  }, [roomId])

  // 每隔几秒刷新 (兜底，WS 断线时用; 连接时 8s 保证岛主数据及时同步)
  useEffect(() => {
    const timer = setInterval(loadGame, connected ? 8000 : 5000)
    return () => clearInterval(timer)
  }, [roomId, connected])

  const hand = game.currentHand
  const players = hand?.players || []
  const currentRound = hand?.current_round || 'preflop'
  const potTotal = hand?.pot_total || 0
  const myUserId = game.myUserId
  const isOwner = game.isOwner
  const communityCards = hand?.community_cards || []
  const myHoleCards = hand?.my_hole_cards || []
  const evaluations = hand?.evaluations || {}
  const turnPlayerId = hand?.turn_player_id
  const endedByFold = game.endedByFold || hand?.ended_by_fold || false
  const muckPlayerId = hand?.muck_player_id

  // 找到当前需要操作的玩家（基于后端 turn_player_id）
  const myPlayer = players.find((p) => p.user_id === myUserId)
  const isMyTurn = myPlayer && turnPlayerId === myPlayer.player_id && hand?.status === 'betting'
  const isMyAllin = myPlayer ? (myPlayer.chip_count === 0 && !myPlayer.is_folded) : false

  // === 互动状态: 连胜/赢钱动画 ===
  const [winStreak, setWinStreak] = useState(0)
  const [showBellRain, setShowBellRain] = useState(false)
  const prevHandIdRef = useRef<number | null>(null)

  // 检测结算结果: 我是否赢了
  useEffect(() => {
    if (!game.settleResults || !myPlayer) return
    const currentHandId = hand?.hand_id
    if (currentHandId && currentHandId === prevHandIdRef.current) return
    if (currentHandId) prevHandIdRef.current = currentHandId

    const myResults = game.settleResults.filter((r) => r.winner_id === myPlayer.player_id)
    const totalWon = myResults.reduce((sum, r) => sum + r.amount_won, 0)
    if (totalWon > 0) {
      setWinStreak((prev) => prev + 1)
      setShowBellRain(true)
      setTimeout(() => setShowBellRain(false), 3000)
    } else {
      setWinStreak(0)
    }
  }, [game.settleResults])

  // 新一手牌时重置赢钱动画（但不重置连胜和累计盈利）
  useEffect(() => {
    if (hand?.status === 'betting' && hand?.current_round === 'preflop') {
      setShowBellRain(false)
    }
  }, [hand?.hand_id])

  // === Showdown orchestration ===
  // When store signals showdownReveal, start the reveal phase
  useEffect(() => {
    if (game.showdownReveal && showdownPhase === 'idle') {
      setShowdownPhase('revealing')
    }
  }, [game.showdownReveal])

  // After reveal completes: fold → muck_choice, non-fold → inline card display
  const handleRevealComplete = useCallback(() => {
    if (endedByFold && myPlayer) {
      // fold 局: 唯一赢家选择是否展示
      const alivePlayers = players.filter((p) => !p.is_folded)
      if (alivePlayers.length === 1 && alivePlayers[0].player_id === myPlayer.player_id) {
        setShowdownPhase('muck_choice')
        return
      }
      setShowdownPhase('auto_settling')
      return
    }
    // 非 fold 局: 直接在座位中展示所有存活玩家手牌 (4 秒)
    setShowdownPhase('showing_cards')
  }, [endedByFold, myPlayer, players])

  const doAutoSettle = async () => {
    try {
      await api.post(`/rooms/${roomId}/settle`)
      await loadGame()
      setShowdownPhase('settled')
      // 延迟二次拉取，确保 WS 广播的状态已落库
      setTimeout(() => loadGame(), 1000)
    } catch (e) {
      console.error('自动结算失败，请岛主手动结算:', e)
    }
  }

  const handleShowCards = () => {
    // fold 局赢家选择「展示手牌」: 后端对 ended_by_fold 牌局拒绝 reveal (400)；
    // 赢家未 muck 时其手牌本就在 all_hole_cards 中返回 (未 muck 即展示)，
    // 因此不调任何 API，直接进入统一结算流程
    setShowdownPhase('auto_settling')
  }

  const handleMuck = async () => {
    // fold 局赢家选择盖牌
    try {
      await api.post(`/rooms/${roomId}/muck`)
      await loadGame()
    } catch { /* ignore */ }
    // BUG-3 修复: 统一由 auto_settling useEffect 处理结算
    setShowdownPhase('auto_settling')
  }

  // === Inline card display timer (6s) ===
  const [viewCountdown, setViewCountdown] = useState(6)
  const viewTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (showdownPhase !== 'showing_cards') {
      setViewCountdown(6)
      if (viewTimerRef.current) { clearInterval(viewTimerRef.current); viewTimerRef.current = null }
      return
    }
    setViewCountdown(6)
    viewTimerRef.current = setInterval(() => {
      setViewCountdown((prev) => {
        if (prev <= 1) {
          if (viewTimerRef.current) { clearInterval(viewTimerRef.current); viewTimerRef.current = null }
          setShowdownPhase('auto_settling')
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => {
      if (viewTimerRef.current) { clearInterval(viewTimerRef.current); viewTimerRef.current = null }
    }
  }, [showdownPhase])
  
  // 统一岛主自动结算: phase=auto_settling 且是岛主 → 2s 后调 /settle
  // BUG-3 修复: 替代所有分散的 doAutoSettle() 调用
  useEffect(() => {
    if (showdownPhase !== 'auto_settling' || !game.isOwner) return
    if (autoSettleTimerRef.current) clearTimeout(autoSettleTimerRef.current)
    autoSettleTimerRef.current = setTimeout(() => doAutoSettle(), 2000)
    return () => {
      if (autoSettleTimerRef.current) clearTimeout(autoSettleTimerRef.current)
    }
  }, [showdownPhase, game.isOwner])
  
  // 非岛主: 当岛主结算完成的自动进入 settled (补充原有逻辑)
  useEffect(() => {
    if (showdownPhase === 'auto_settling' && game.settleResults && hand?.status === 'settled') {
      setShowdownPhase('settled')
    }
  }, [showdownPhase, game.settleResults, hand?.status])

  // Cleanup timers
  useEffect(() => {
    return () => {
      if (autoSettleTimerRef.current) clearTimeout(autoSettleTimerRef.current)
    }
  }, [])

  // Reset phase when new hand starts
  useEffect(() => {
    if (hand?.status === 'betting' || game.roomStatus === 'waiting') {
      setShowdownPhase('idle')
      setShowdownDismissed(false)
      settledOnMountRef.current = false
    }
  }, [hand?.hand_id])

  // 非岛主: 当岛主完成结算后 (WS hand_settled)，自动进入 settled 阶段
  useEffect(() => {
    if (game.settleResults && hand?.status === 'settled'
      && (showdownPhase === 'idle' || showdownPhase === 'auto_settling' || showdownPhase === 'revealing')) {
      setShowdownPhase('settled')
    }
  }, [game.settleResults, hand?.status])

  // 动态计算加注金额
  const bbAmount = useGameStore((s) => s.bbAmount) || 100
  const myBetThisRound = myPlayer?.bet_this_round || 0
  const myChips = myPlayer?.chip_count || 0
  const currentMaxBet = Math.max(...players.map((p) => p.bet_this_round), 0)
  const toCall = Math.max(currentMaxBet - myBetThisRound, 0)
  // 最小加注增量以服务端口径为准 (最后一次加注的增量，可能远大于 BB)；未返回时回退 BB
  const minRaise = hand?.min_raise || bbAmount
  const minLegalRaise = Math.max(currentMaxBet + minRaise - myBetThisRound, minRaise)
  const quickAmounts = [minLegalRaise, minLegalRaise * 2, minLegalRaise * 5].filter(
    (amt, i, arr) => arr.indexOf(amt) === i && amt <= myChips
  )

  // 自定义加注金额
  const [customAmount, setCustomAmount] = useState('')
  const [customError, setCustomError] = useState('')

  const validateCustomRaise = (): number | null => {
    const amt = parseInt(customAmount, 10)
    if (isNaN(amt) || amt <= 0) {
      setCustomError('请输入有效数字')
      return null
    }
    if (amt > myChips) {
      setCustomError(`不能超过你的铃钱 (${formatBells(myChips)})`)
      return null
    }
    if (amt < minLegalRaise && amt < myChips) {
      setCustomError(`最少追加 ${formatBells(minLegalRaise)}`)
      return null
    }
    setCustomError('')
    return amt
  }

  const handleCustomRaise = () => {
    const amt = validateCustomRaise()
    if (amt !== null) {
      handleAction('raise', amt)
      setCustomAmount('')
    }
  }

  const handleAction = async (action: string, amount?: number) => {
    try {
      await api.post(`/rooms/${roomId}/action`, {
        action,
        amount: amount || undefined,
      })
      await loadGame()
    } catch (e) {
      alert('操作失败: ' + (e as Error).message)
    }
  }

  const handleSettle = async () => {
    try {
      await api.post(`/rooms/${roomId}/settle`)
      await loadGame()
      setShowdownPhase('settled')
      // 延迟二次拉取，确保 WS 广播的状态已落库
      setTimeout(() => loadGame(), 1000)
    } catch (e) {
      alert('收获失败: ' + (e as Error).message)
    }
  }

  const handleNewHand = async () => {
    try {
      await api.post(`/rooms/${roomId}/new-hand`)
      setShowdownPhase('idle')
      await loadGame()
      setTimeout(() => loadGame(), 1000)
    } catch (e) {
      alert('开始新一季失败: ' + (e as Error).message)
    }
  }

  // 补给铃钱 (输光后)
  const initialChips = useGameStore((s) => s.initialChips) || 10000
  const [showdownDismissed, setShowdownDismissed] = useState(false)
  // busted = 输光 + 结算已完成 + 结算弹窗已关闭 (先看结算，再看补给)
  const isBusted = showdownPhase === 'settled' && myPlayer
    && myPlayer.chip_count <= 0 && showdownDismissed
  const [rebuyCountdown, setRebuyCountdown] = useState(10)
  const rebuyTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 仅「刷新进入」(挂载后首次加载就发现已 settled) 且 busted 时，直接跳过结算弹窗；
  // 正常打完一局进入 settled 时不自动跳过 —— 先展示 ShowdownModal，
  // 由用户点击「查看完毕」关闭后才进入 busted/补给流程
  useEffect(() => {
    if (showdownPhase === 'settled' && myPlayer && myPlayer.chip_count <= 0 && !showdownDismissed
      && settledOnMountRef.current) {
      const h = useGameStore.getState().currentHand
      if (h?.status === 'settled') {
        setShowdownDismissed(true)
      }
    }
  }, [showdownPhase, myPlayer, showdownDismissed, hand?.status])

  // 补给倒计时: 10秒内不选择则自动离岛
  useEffect(() => {
    if (!isBusted) {
      setRebuyCountdown(10)
      if (rebuyTimerRef.current) { clearInterval(rebuyTimerRef.current); rebuyTimerRef.current = null }
      return
    }
    setRebuyCountdown(10)
    rebuyTimerRef.current = setInterval(() => {
      setRebuyCountdown((prev) => {
        if (prev <= 1) {
          if (rebuyTimerRef.current) { clearInterval(rebuyTimerRef.current); rebuyTimerRef.current = null }
          handleStand()
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => {
      if (rebuyTimerRef.current) { clearInterval(rebuyTimerRef.current); rebuyTimerRef.current = null }
    }
  }, [isBusted])

  const handleRebuy = async () => {
    if (rebuyTimerRef.current) { clearInterval(rebuyTimerRef.current); rebuyTimerRef.current = null }
    try {
      await api.post(`/rooms/${roomId}/rebuy`, { amount: initialChips })
      await loadGame()
    } catch (e) {
      alert('补给失败: ' + (e as Error).message)
    }
  }

  const handleStand = async () => {
    if (rebuyTimerRef.current) { clearInterval(rebuyTimerRef.current); rebuyTimerRef.current = null }
    try {
      await api.post(`/rooms/${roomId}/stand`)
      // roomCode 可能为空 (刷新后 state 响应不含 room_code)，兜底回首页，避免 /lobby/ 无路由白屏
      const code = useGameStore.getState().roomCode
      navigate(code ? `/lobby/${code}` : '/')
    } catch (e) {
      alert('离岛失败: ' + (e as Error).message)
    }
  }

  // === 最终结算 ===
  const [showFinalSettle, setShowFinalSettle] = useState(false)

  const handleFinalSettle = async () => {
    try {
      const res = await api.post(`/rooms/${roomId}/end-game`)
      // 直接使用 API 返回的结算数据，不依赖 loadGame 的异步更新
      if (res?.settlement) {
        useGameStore.setState({ finalSettlement: res.settlement, roomStatus: 'finished' })
      }
      await loadGame()
      setShowFinalSettle(true)
    } catch (e) {
      const errMsg = (e as Error).message || ''
      // 如果游戏已结束（重复点击），仍尝试显示结算页
      if (errMsg.includes('已结束')) {
        await loadGame()
        const state = useGameStore.getState()
        if (state.roomStatus === 'finished' && state.finalSettlement) {
          setShowFinalSettle(true)
        }
      } else {
        alert('最终结算失败: ' + errMsg)
      }
    }
  }

  // 如果进入页面时牌局已结束 (刷新场景)，自动显示最终结算
  useEffect(() => {
    if (game.roomStatus === 'finished' && game.finalSettlement && !showFinalSettle) {
      setShowFinalSettle(true)
    }
  }, [game.roomStatus, game.finalSettlement])

  // all_hole_cards for inline display during showing_cards phase
  const allHoleCards = hand?.all_hole_cards || {}
  const showInlineCards = showdownPhase === 'showing_cards'

  // 根据 evaluations 计算最佳牌型（赢家）
  // Bug fix: 使用完整 score 比较，而非仅比较 hand_type
  // Bug fix: 平分底池时 settleResults 含多个赢家，聚合所有 winner_id 用于 🏆 徽章
  const bestHandPlayerIds: Set<number> = (() => {
    // 优先使用 results (结算后确定赢家，平分底池时含多个)
    if (game.settleResults && game.settleResults.length > 0) {
      return new Set(game.settleResults.map((r) => r.winner_id))
    }
    if (!evaluations || Object.keys(evaluations).length === 0) return new Set<number>()
    let bestId: number | null = null
    let bestScore: number[] = []
    for (const [pid, ev] of Object.entries(evaluations)) {
      const score = ev.score || [ev.hand_type]
      let isBetter = false
      if (!bestId) {
        isBetter = true
      } else {
        for (let i = 0; i < Math.max(score.length, bestScore.length); i++) {
          const a = score[i] ?? 0
          const b = bestScore[i] ?? 0
          if (a > b) { isBetter = true; break }
          if (a < b) { break }
        }
      }
      if (isBetter) {
        bestScore = score
        bestId = Number(pid)
      }
    }
    return new Set(bestId != null ? [bestId] : [])
  })()

  // 获取玩家操作记录 (用于展示 check 等动作)
  const playerActions = useGameStore((s) => s.playerActions)

  // === 环形座位布局（我固定底部，其他人顺时针环绕） ===
  // 德州扑克顺时针: 我 → 左侧 → 上侧 → 右侧 → 我
  const mySeatNum = myPlayer?.seat_number ?? -1
  const othersClockwise = [...players]
    .filter((p) => p.user_id !== myUserId)
    .sort((a, b) => {
      const da = (a.seat_number - mySeatNum + 9) % 9 || 9
      const db = (b.seat_number - mySeatNum + 9) % 9 || 9
      return da - db
    })
  const n = othersClockwise.length
  // 4+人(n>=3)时左右各1人，7+人(n>=6)时左右各2人，剩余去顶部
  const leftCount = n < 3 ? 0 : n < 6 ? 1 : 2
  const rightCount = n < 3 ? 0 : n < 6 ? 1 : 2
  const topCount = Math.max(0, n - leftCount - rightCount)
  const leftPlayers = othersClockwise.slice(0, leftCount)
  const topPlayers = othersClockwise.slice(leftCount, leftCount + topCount)
  const rightPlayers = othersClockwise.slice(leftCount + topCount)

  // === 牌局回顾 ===
  // 右上角按钮点开: 加载最近一次已结算牌局的完整数据 (公共牌 / 手牌 / 收获汇总)
  const [historyHand, setHistoryHand] = useState<any>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)

  const handleOpenHistory = async () => {
    if (historyLoading || !game.lastSettledHandId) return
    setHistoryLoading(true)
    try {
      const h = await game.loadHistoryHand(game.lastSettledHandId)
      setHistoryHand(h)
      setShowHistory(true)
    } catch (e) {
      console.error('加载牌局回顾失败:', e)
    } finally {
      setHistoryLoading(false)
    }
  }

  // === 响应式缩放: 顶部玩家 >= 5 人时等比缩小座位框和牌桌 ===
  const tableScale = topCount >= 5 ? Math.max(0.72, 4.2 / topCount) : 1

  // 是否显示 showdown 弹窗 (仅在翻牌动画+结算完成后)
  const showShowdownModal = showdownPhase === 'settled' && (hand?.status === 'settled')

  // === 手动同步刷新 ===
  // 本地拉一次 + 调后端广播，让房间内所有人一起同步最新 state
  const [syncing, setSyncing] = useState(false)
  const [syncedTip, setSyncedTip] = useState(false)

  const handleManualRefresh = async () => {
    if (syncing) return
    setSyncing(true)
    try {
      // 先本地拉一次以获得即时反馈，再调后端广播让所有人同步
      await loadGame()
      try {
        await api.post(`/rooms/${roomId}/sync`)
      } catch {
        // 广播失败不影响本地反馈
      }
      setSyncedTip(true)
      setTimeout(() => setSyncedTip(false), 1200)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="game-page">
      {/* Phase Bar — 岛屿名 + 阶段 + 收获篮 */}
      <div className={`phase-bar phase-${currentRound}`}>
        <div className="phase-island-name">
          <span>🏝️</span>
          <span>{game.roomName || ''}</span>
        </div>
        <div className="phase-indicator">
          <span className="phase-icon">{getRoundIcon(currentRound)}</span>
          <span className="phase-text">{getRoundText(currentRound)}</span>
          {hand && <span className="phase-hand-num">第 {hand.hand_number} 季</span>}
        </div>
        <div className="pot-display">
          <div className="pot-label">{CONCEPT_TERMS.pot}</div>
          <div className="pot-amount">{formatBellsWithIcon(potTotal)}</div>
        </div>
      </div>

      {/* WS indicator */}
      <div className={`ws-indicator ${reconnecting ? 'ws-reconnecting' : ''}`}>
        {connected
          ? '🟢 已连接'
          : reconnecting
            ? `🟡 重连中... (${reconnectAttempts})`
            : '🔴 断线'}
      </div>

      {/* Table Area */}
      <div className="table-area">
        <div className="poker-table" style={{ '--table-scale': tableScale } as React.CSSProperties}>
          {/* 左侧玩家 */}
          {leftPlayers.length > 0 && (
            <div className="side-players side-left">
              {leftPlayers.map((player) => (
                <PlayerSeat
                  key={player.player_id}
                  player={player}
                  isMe={false}
                  isTurn={turnPlayerId === player.player_id}
                  isShowdown={showShowdownModal}
                  myUserId={myUserId}
                  players={players}
                  evaluations={evaluations}
                  inlineCards={showInlineCards ? (allHoleCards[String(player.player_id)] || null) : null}
                  isBestHand={showInlineCards && bestHandPlayerIds.has(player.player_id)}
                  lastAction={playerActions[player.player_id] || null}
                />
              ))}
            </div>
          )}

          {/* 中央区域: 上排 + 公共牌 + 下排(对手) */}
          <div className="table-main">
            {/* 上排玩家 */}
            <div className="players-row players-top">
              {topPlayers.map((player) => (
                <PlayerSeat
                  key={player.player_id}
                  player={player}
                  isMe={false}
                  isTurn={turnPlayerId === player.player_id}
                  isShowdown={showShowdownModal}
                  myUserId={myUserId}
                  players={players}
                  evaluations={evaluations}
                  inlineCards={showInlineCards ? (allHoleCards[String(player.player_id)] || null) : null}
                  isBestHand={showInlineCards && bestHandPlayerIds.has(player.player_id)}
                  lastAction={playerActions[player.player_id] || null}
                />
              ))}
            </div>

            {/* Center: Community cards + Pot */}
            <div className="table-center">
              <CommunityCards
                cards={communityCards}
                currentRound={currentRound}
                revealing={showdownPhase === 'revealing'}
                onRevealComplete={handleRevealComplete}
              />
              <div className="center-pot">
                <span className="center-pot-label">底池</span>
                <span className="center-pot-amount">{formatBells(potTotal)}</span>
              </div>
            </div>
          </div>

          {/* 右侧玩家 */}
          {rightPlayers.length > 0 && (
            <div className="side-players side-right">
              {rightPlayers.map((player) => (
                <PlayerSeat
                  key={player.player_id}
                  player={player}
                  isMe={false}
                  isTurn={turnPlayerId === player.player_id}
                  isShowdown={showShowdownModal}
                  myUserId={myUserId}
                  players={players}
                  evaluations={evaluations}
                  inlineCards={showInlineCards ? (allHoleCards[String(player.player_id)] || null) : null}
                  isBestHand={showInlineCards && bestHandPlayerIds.has(player.player_id)}
                  lastAction={playerActions[player.player_id] || null}
                />
              ))}
            </div>
          )}

          {/* 我的座位 — 牌桌底部居中 */}
          {myPlayer && (
            <div className="players-row players-mine">
              <PlayerSeat
                player={myPlayer}
                isMe={true}
                isTurn={turnPlayerId === myPlayer.player_id}
                isShowdown={showShowdownModal}
                myUserId={myUserId}
                players={players}
                evaluations={evaluations}
                inlineCards={showInlineCards ? (allHoleCards[String(myPlayer.player_id)] || null) : null}
                isBestHand={showInlineCards && bestHandPlayerIds.has(myPlayer.player_id)}
                lastAction={playerActions[myPlayer.player_id] || null}
              />
            </div>
          )}

        </div>

        {/* Fallback: owner can manually settle — 牌桌区域左下角 */}
        {isOwner && hand?.status === 'settling' && (
          <button className="table-settle-btn" onClick={handleSettle}>
            🎉 手动结算
          </button>
        )}

        {/* 手动同步按钮 — 牌桌区域右下角，按钮点击后房间内所有人一起同步 */}
        <button
          className="table-sync-btn"
          onClick={handleManualRefresh}
          disabled={syncing}
          title="若长时间未同步进度可手动刷新（房间内所有人一起同步）"
        >
          {syncing ? '同步中...' : syncedTip ? '✓ 已同步' : '🔄 同步'}
        </button>

        {/* 牌局回顾按钮 — 牌桌区域右上角，查看最近一次已结算牌局 */}
        {game.lastSettledHandId && (
          <button
            className="table-history-btn"
            onClick={handleOpenHistory}
            disabled={historyLoading}
            title="查看上一局牌局"
          >
            <img src="/elements/star_fragment_large.png" alt="history" />
          </button>
        )}
      </div>

      {/* My hole cards (large, at bottom) — 左侧头像框(含铃钱) / 中间手牌 / 右侧牌型 */}
      {myHoleCards.length > 0 && (() => {
        // 牌型分级: 根据 hand_type 映射到 tier (决定渲染效果)
        //   tier-0 高牌/一对   (弱)
        //   tier-1 两对/三条   (中)
        //   tier-2 顺子/同花   (强)
        //   tier-3 葫芦/四条/同花顺/皇家同花顺 (顶级)
        const eval_ = hand?.my_evaluation
        const ht = eval_?.hand_type ?? 0
        let tier = 0
        let tierLabel = ''
        if (ht >= 8) { tier = 3; tierLabel = '顶级' }      // 四条 / 同花顺 / 皇家同花顺
        else if (ht >= 6) { tier = 2; tierLabel = '强' }   // 葫芦 / 顺子? 这里葫芦=6，顺子=4、同花=5，调整下面
        else if (ht >= 4) { tier = 2; tierLabel = '强' }   // 顺子/同花
        else if (ht >= 2) { tier = 1; tierLabel = '中' }   // 两对/三条
        else { tier = 0; tierLabel = '弱' }                // 高牌/一对
        // 修正: 顺子(4)/同花(5) 已纳入 tier-2，葫芦(6) 也归 tier-2 或 tier-3，此处统一 tier-3
        if (ht === 6) { tier = 3; tierLabel = '顶级' }
        const showEval = eval_ && currentRound !== 'preflop'
        return (
          <div className="my-hole-cards">
            {/* 左侧：头像框 + 铃钱合并 */}
            {myPlayer && (() => {
              const avatarUrl = getCharacterAvatar(myPlayer.nickname)
              let frameClass = 'my-avatar-frame'
              if (isMyAllin) frameClass += ' my-avatar-allin'
              else if (isMyTurn) frameClass += ' my-avatar-turn'
              return (
                <div className={frameClass}>
                  <div className="my-avatar-img-wrap">
                    {avatarUrl ? (
                      <img className="my-avatar-img" src={avatarUrl} alt={myPlayer.nickname} />
                    ) : (
                      <div className="my-avatar-placeholder">{myPlayer.nickname.charAt(0)}</div>
                    )}
                    {/* 战绩角标 */}
                    {winStreak >= 2 && (
                      <span className="my-avatar-streak">🔥{winStreak}</span>
                    )}
                    {/* 赢家奖杯 (showing_cards 阶段) */}
                    {showInlineCards && myPlayer.player_id === bestHandPlayerId && (
                      <span className="my-avatar-trophy">🏆</span>
                    )}
                  </div>
                  {/* 铃钱显示(合并在头像框内) */}
                  <div className="my-avatar-bells">
                    <span className="my-avatar-bells-icon">🔔</span>
                    <span className="my-avatar-bells-amount">{formatBells(myChips)}</span>
                  </div>
                  {/* 铃钱雨动画（赢钱时从头像位置落下） */}
                  {showBellRain && (
                    <div className="bell-rain">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <span key={i} className="bell-rain-drop" style={{ animationDelay: `${i * 0.15}s`, left: `${10 + i * 11}%` }}>🔔</span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })()}

            {/* 中间：我的手牌 */}
            <div className="my-hole-cards-cards">
              {myHoleCards.map((card, i) => (
                <PlayingCard key={i} suit={card.suit} rank={card.rank} size="large" />
              ))}
            </div>

            {/* 右侧：牌型显示 (preflop 显示占位; flop+ 显示分级牌型) */}
            {showEval ? (
              <div className={`my-live-eval my-live-eval-tier-${tier}`}>
                <span className="my-live-eval-name">{eval_.hand_type_name}</span>
                <span className="my-live-eval-tier">{tierLabel}</span>
              </div>
            ) : (
              <div className="my-live-eval my-live-eval-placeholder">
                <span className="my-live-eval-name">待翻牌</span>
              </div>
            )}
          </div>
        )
      })()}

      {/* Muck choice overlay (fold winner decides whether to show cards) */}
      {showdownPhase === 'muck_choice' && (
        <div className="muck-overlay">
          <div className="muck-dialog">
            <div className="muck-title">你赢了这局!</div>
            <div className="muck-subtitle">是否展示你的手牌?</div>
            <div className="muck-buttons">
              <Button type="primary" onClick={handleShowCards}>展示手牌</Button>
              <Button type="default" onClick={handleMuck}>盖牌</Button>
            </div>
          </div>
        </div>
      )}

      {/* Auto-settling indicator */}
      {showdownPhase === 'auto_settling' && (
        <div className="auto-settle-toast">正在结算...</div>
      )}

      {/* Inline card display: showing_cards phase shows cards in player seats */}
      {showdownPhase === 'showing_cards' && (
        <div className="auto-settle-toast">
          亮牌展示 {viewCountdown > 0 ? `${viewCountdown}s` : '...'}
        </div>
      )}

      {/* Action Panel — 始终渲染，固定高度防晃动 */}
      <div className="action-panel">
        {game.roomStatus === 'playing' && isMyTurn && (
          <>
            {/* 主操作行: call/check (最突出) */}
            <div className="quick-amounts">
              {toCall > 0 ? (
                <button className="quick-chip quick-chip-call" onClick={() => handleAction('call')}>
                  {/* 跟注额超过全部筹码时按 all-in 口径显示，与后端 min(toCall, chips) 扣款一致 */}
                  {toCall >= myChips ? `All-in ${formatBells(myChips)}` : `call ${formatBells(toCall)}`}
                </button>
              ) : (
                <button className="quick-chip quick-chip-check" onClick={() => handleAction('check')}>
                  check
                </button>
              )}
              <button className="action-btn action-btn-fold action-btn-inline" onClick={() => handleAction('fold')}>
                fold
              </button>
              <button className="action-btn action-btn-allin action-btn-inline" onClick={() => handleAction('allin')}>
                all in
              </button>
            </div>
            {/* 加注行: 仅在有合法加注金额时显示 */}
            {quickAmounts.length > 0 && (
              <div className="quick-amounts quick-raise-row">
                <span className="quick-raise-label">raise:</span>
                {quickAmounts.map((amt) => (
                  <button key={amt} className="quick-chip quick-chip-raise" onClick={() => handleAction('raise', amt)}>
                    {formatBells(amt)}
                  </button>
                ))}
              </div>
            )}
            {/* 自定义加注: 仅在有筹码可加注时显示 */}
            {myChips > toCall && (
              <div className="custom-raise">
                <input
                  type="number"
                  className="custom-raise-input"
                  placeholder={`自定义 (最少${formatBells(minLegalRaise)})`}
                  value={customAmount}
                  onChange={(e) => { setCustomAmount(e.target.value); setCustomError('') }}
                  onKeyDown={(e) => e.key === 'Enter' && handleCustomRaise()}
                />
                <button className="custom-raise-btn" onClick={handleCustomRaise}>追加</button>
              </div>
            )}
            {customError && <div className="custom-raise-error">{customError}</div>}
          </>
        )}

        {game.roomStatus === 'playing' && !isMyTurn && turnPlayerId && (
          <div className="app-empty">
            等待 {players.find((p) => p.player_id === turnPlayerId)?.nickname || '其他居民'} 行动...
          </div>
        )}
        {game.roomStatus === 'playing' && !isMyTurn && !turnPlayerId && hand?.status === 'betting' && (
          <div className="app-empty">即将自动推进到下一阶段...</div>
        )}

        {/* 手动结算按钮已移至牌桌区域左下角 */}
      </div>

      {/* Showdown Modal */}
      {showShowdownModal && (
        <ShowdownModal
          players={players}
          communityCards={communityCards}
          myHoleCards={myHoleCards}
          allHoleCards={hand?.all_hole_cards || {}}
          evaluations={evaluations}
          results={game.settleResults || []}
          bets={(hand?.bets || []).map((b: any) => ({ player_id: b.player_id, amount: b.amount }))}
          isOwner={isOwner}
          onSettle={handleSettle}
          onNewHand={handleNewHand}
          onFinalSettle={isOwner ? handleFinalSettle : undefined}
          settled={hand?.status === 'settled'}
          myUserId={myUserId}
          endedByFold={endedByFold}
          muckPlayerId={muckPlayerId}
          onBustClose={myPlayer && myPlayer.chip_count <= 0 ? () => setShowdownDismissed(true) : undefined}
        />
      )}

      {/* 牌局回顾弹窗: readonly 模式, 只展示数据 + 「关闭」按钮 */}
      {showHistory && historyHand && (
        <ShowdownModal
          readonly
          players={historyHand.players}
          communityCards={historyHand.community_cards}
          myHoleCards={historyHand.my_hole_cards}
          allHoleCards={historyHand.all_hole_cards}
          evaluations={historyHand.evaluations}
          results={historyHand.results}
          bets={historyHand.bets}
          settled
          myUserId={myUserId}
          endedByFold={historyHand.ended_by_fold}
          muckPlayerId={historyHand.muck_player_id}
          onClose={() => setShowHistory(false)}
        />
      )}

      {/* Busted Rebuy Dialog */}
      {isBusted && (
        <div className="muck-overlay">
          <div className="rebuy-dialog">
            <div className="rebuy-icon">🔔</div>
            <div className="rebuy-title">铃钱耗尽!</div>
            <div className="rebuy-subtitle">
              你的铃钱已经用完了，是否补给继续冒险?
            </div>
            <div className="rebuy-amount">
              补给 {formatBells(initialChips)} 铃钱
            </div>
            <div className="rebuy-countdown">
              {rebuyCountdown > 0
                ? `${rebuyCountdown}秒后自动离岛`
                : '正在离岛...'}
            </div>
            <div className="rebuy-buttons">
              <button className="rebuy-btn rebuy-btn-yes" onClick={handleRebuy}>
                🌟 补给铃钱
              </button>
              <button className="rebuy-btn rebuy-btn-no" onClick={handleStand}>
                🏝️ 离岛
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Final Settlement Modal */}
      {showFinalSettle && game.finalSettlement && (
        <FinalSettlementModal
          settlement={game.finalSettlement}
          myUserId={myUserId}
          onClose={() => navigate('/')}
        />
      )}
    </div>
  )
}

// === 玩家座位组件 ===
interface PlayerSeatProps {
  player: any
  isMe: boolean
  isTurn: boolean
  isShowdown: boolean
  myUserId: number
  players: any[]
  evaluations: Record<string, { hand_type: number; hand_type_name: string; score?: number[] }>
  inlineCards?: { suit: 'spades' | 'hearts' | 'diamonds' | 'clubs'; rank: number }[] | null
  isBestHand?: boolean
  lastAction?: { action: string; amount: number } | null
}

function PlayerSeat({ player, isMe, isTurn, isShowdown, myUserId, players, evaluations, inlineCards, isBestHand, lastAction }: PlayerSeatProps) {
  const isFolded = player.is_folded
  const isAllin = player.chip_count === 0 && !isFolded

  let seatClass = 'seat-card'
  if (isMe) seatClass += ' seat-mine'
  if (isFolded) seatClass += ' seat-folded'
  if (isAllin) seatClass += ' seat-allin'
  if (isTurn) seatClass += ' seat-turn'

  const eval_ = evaluations[String(player.player_id)]

  const seatAvatarUrl = getCharacterAvatar(player.nickname)

  return (
    <div className={seatClass}>
      {player.role && (
        <span className="seat-role" style={{
          background: player.role === 'D' ? '#f5c31c' :
            player.role === 'SB' ? '#6fba2c' : '#19c8b9'
        }}>
          {ROLE_TERMS[player.role] || player.role}
        </span>
      )}
      <div className="seat-avatar-wrap">
        {seatAvatarUrl && (
          <img className="seat-avatar" src={seatAvatarUrl} alt={player.nickname} />
        )}
        {isBestHand && (
          <div className="seat-winner-badge">🏆</div>
        )}
      </div>
      <div className="seat-nickname">{player.nickname}</div>
      <div className="seat-bells">🔔 {formatBells(player.chip_count)}</div>
      {player.bet_this_round > 0 && (
        <div className="seat-bet">
          下注 {formatBells(player.bet_this_round)}
        </div>
      )}
      {isFolded && <div className="seat-status">已弃牌</div>}
      {isAllin && <div className="seat-status seat-allin-text">All-in</div>}
      {/* Bug fix: 显示玩家操作动作 (check/call/raise 等) */}
      {!isFolded && !isAllin && lastAction && lastAction.amount === 0 && lastAction.action === 'check' && (
        <div className="seat-status seat-action-check">过牌</div>
      )}
      {!isFolded && !isAllin && lastAction && lastAction.amount > 0 && lastAction.action !== 'fold' && lastAction.action !== 'allin' && (
        <div className="seat-status seat-action-bet">
          {lastAction.action === 'call' ? '跟注' : lastAction.action === 'raise' ? '加注' : lastAction.action} {formatBells(lastAction.amount)}
        </div>
      )}
      {/* Inline card display during showing_cards phase */}
      {inlineCards && inlineCards.length > 0 && (
        <div className="seat-inline-cards">
          {inlineCards.map((card, i) => (
            <PlayingCard key={i} suit={card.suit} rank={card.rank} size="small" />
          ))}
        </div>
      )}
      {eval_ && isShowdown && !isFolded && (
        <div className="seat-eval">{eval_.hand_type_name}</div>
      )}
    </div>
  )
}

export default GameTable
