import { formatBells } from '@/utils/terms'
import { PlayingCard } from './PlayingCard'
import './ShowdownModal.css'

interface CardData {
  suit: 'spades' | 'hearts' | 'diamonds' | 'clubs'
  rank: number
}

interface PlayerInfo {
  player_id: number
  user_id: number
  nickname: string
  chip_count: number
  is_folded: boolean
}

interface PotInfo {
  pot_id: number
  pot_type: string
  pot_level: number
  amount: number
}

interface ResultInfo {
  winner_id: number
  amount_won: number
  is_split: number
}

interface Evaluation {
  hand_type: number
  hand_type_name: string
  score?: number[]
}

interface ShowdownModalProps {
  players: PlayerInfo[]
  communityCards: CardData[]
  myHoleCards: CardData[]
  allHoleCards: Record<string, CardData[]>
  evaluations: Record<string, Evaluation>
  results: ResultInfo[]
  /** 本局下注流水 (用于计算输家的「本局投入」) */
  bets: { player_id: number; amount: number }[]
  isOwner?: boolean
  onSettle?: () => void
  onNewHand?: () => void
  /** 岛主点击最终结算 */
  onFinalSettle?: () => void
  settled: boolean
  myUserId: number
  endedByFold?: boolean
  muckPlayerId?: number | null
  /** 输光玩家关闭弹窗回调 (设置后显示"关闭"按钮) */
  onBustClose?: () => void
  /** 只读模式: 牌局回顾弹窗。只展示数据 + 「关闭」按钮，不出现岛主操作。 */
  readonly?: boolean
  /** 只读模式下的关闭回调 */
  onClose?: () => void
}

export function ShowdownModal({
  players,
  communityCards,
  myHoleCards,
  allHoleCards,
  evaluations,
  results,
  bets,
  isOwner,
  onSettle,
  onNewHand,
  onFinalSettle,
  settled,
  myUserId,
  endedByFold,
  muckPlayerId,
  onBustClose,
  readonly = false,
  onClose,
}: ShowdownModalProps) {
  const playerMap = Object.fromEntries(players.map((p) => [p.player_id, p]))

  // 找到赢家信息 (平分底池时含多个赢家，按 winner_id 去重)
  const winnerIds = [...new Set((results || []).map((r) => r.winner_id))]
  const winners = winnerIds.map((id) => playerMap[id]).filter(Boolean)
  const winnerNicknames = winners.map((w) => w.nickname).join('、')

  // 检查赢家是否盖牌
  const isWinnerMucked = muckPlayerId ? winnerIds.includes(muckPlayerId) : false

  // 所有未盖牌赢家的手牌 (平分底池时展示每位赢家) — 如果盖牌则为空
  const winnerHands = winnerIds
    .filter((id) => id !== muckPlayerId)
    .map((id) => ({
      playerId: id,
      nickname: playerMap[id]?.nickname || '未知',
      cards: allHoleCards[String(id)] || [],
      eval: evaluations[String(id)] || null,
    }))
    .filter((w) => w.cards.length > 0)

  // 找到我的手牌对应的 player_id
  const myPlayer = players.find((p) => p.user_id === myUserId)
  const myPlayerId = myPlayer?.player_id
  const isMeWinner = myPlayerId ? winnerIds.includes(myPlayerId) : false
  const myEval = myPlayerId ? evaluations[String(myPlayerId)] : null

  // 每个玩家的本局总下注 (用于计算净收益)
  const betMap = (bets || []).reduce((acc, b) => {
    acc[b.player_id] = (acc[b.player_id] || 0) + b.amount
    return acc
  }, {} as Record<number, number>)

  // 计算有效下注 (与后端 fold 退款口径一致):
  // - 正常 showdown (有人 fold 但至少 2 人存活): 不做任何 cap，所有人 (含 fold 者) 投入全额入池
  // - ended_by_fold (fold 到只剩 1 人): 仅唯一存活者超出其他所有玩家 (含 fold 者)
  //   最大投入的「无人跟注」部分退回本人，其余人投入全额入池
  const effectiveBetMap = (() => {
    const map = { ...betMap }
    if (endedByFold) {
      const alivePlayers = players.filter((p) => !p.is_folded)
      if (alivePlayers.length === 1) {
        const survivorId = alivePlayers[0].player_id
        const survivorBet = betMap[survivorId] || 0
        const maxOtherBet = Math.max(
          0,
          ...Object.keys(betMap)
            .filter((k) => Number(k) !== survivorId)
            .map((k) => betMap[Number(k)]),
        )
        if (survivorBet > maxOtherBet) {
          map[survivorId] = maxOtherBet
        }
      }
    }
    return map
  })()

  // 我的本局投入 (有效下注)
  const myBetTotal = myPlayerId != null ? (effectiveBetMap[myPlayerId] || 0) : 0

  // 收获汇总：按 winner_id 聚合净收益 (总奖金 - 自己的下注 = 净赚)
  const winSummary = (results || []).reduce((acc, r) => {
    const key = r.winner_id
    if (!acc[key]) {
      const w = playerMap[r.winner_id]
      acc[key] = {
        winner_id: r.winner_id,
        nickname: w?.nickname || '未知',
        total: 0,
        isMe: r.winner_id === myPlayerId,
      }
    }
    acc[key].total += r.amount_won
    return acc
  }, {} as Record<number, { winner_id: number; nickname: string; total: number; isMe: boolean }>)
  // 减去每位赢家自己的有效下注，得到净收益
  for (const key of Object.keys(winSummary)) {
    const pid = Number(key)
    winSummary[pid].total -= (effectiveBetMap[pid] || 0)
  }
  const winSummaryList = Object.values(winSummary).sort((a, b) => b.total - a.total)

  // 我的净收益 (赢为正，输为负)
  const myWonTotal = myPlayerId != null
    ? (results || []).filter((r) => r.winner_id === myPlayerId).reduce((s, r) => s + r.amount_won, 0)
    : 0
  const myNetGain = myWonTotal - myBetTotal

  // 回顾弹窗 header: 星星图标 + 「上一局回顾」
  const headerIcon = readonly
    ? <img className="showdown-header-icon-img" src="/elements/star_fragment_large.png" alt="history" />
    : <div className="showdown-icon">{settled ? '🏆' : '⏳'}</div>
  const headerTitle = readonly
    ? '上一局回顾'
    : (settled ? '收获结算完成' : '收获时刻')

  return (
    <div className="showdown-overlay">
      <div className="showdown-modal">
        <div className="showdown-header">
          {headerIcon}
          <h3 className="showdown-title">{headerTitle}</h3>
        </div>

        {/* 收获汇总 (只在 settled 后显示，按赢家聚合总收益) */}
        {settled && winSummaryList.length > 0 && (
          <div className="showdown-section showdown-summary">
            <div className="showdown-section-label">🎉 收获汇总</div>
            <div className="showdown-summary-list">
              {winSummaryList.map((s) => (
                <div key={s.winner_id} className={`showdown-summary-row ${s.isMe ? 'is-me' : ''}`}>
                  <span className="showdown-summary-name">
                    {s.nickname}
                    {s.isMe && <span className="showdown-summary-mine">(我)</span>}
                  </span>
                  <span className={`showdown-summary-amount ${s.total >= 0 ? 'gain' : 'loss'}`}>
                    {s.total >= 0 ? '+' : ''}{formatBells(s.total)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 赢家手牌 (平分底池时展示每位赢家) */}
        {settled && winnerHands.map((w) => (
          <div key={w.playerId} className="showdown-section">
            <div className="showdown-section-label">
              🏆 {w.nickname} 的手牌
              {w.eval && <span className="hand-type-badge">{w.eval.hand_type_name}</span>}
            </div>
            <div className="showdown-cards-row">
              {w.cards.map((card, i) => (
                <PlayingCard key={i} suit={card.suit} rank={card.rank} size="normal" />
              ))}
            </div>
          </div>
        ))}

        {/* 赢家盖牌提示 */}
        {settled && isWinnerMucked && endedByFold && (
          <div className="showdown-section showdown-mucked">
            <div className="showdown-section-label">
              🏆 {winnerNicknames} 选择了盖牌
            </div>
          </div>
        )}

        {/* 公共牌 */}
        {communityCards.length > 0 && (
          <div className="showdown-section">
            <div className="showdown-section-label">公共牌</div>
            <div className="showdown-cards-row">
              {communityCards.map((card, i) => (
                <PlayingCard key={i} suit={card.suit} rank={card.rank} size="normal" />
              ))}
            </div>
          </div>
        )}

        {/* 我的手牌 */}
        {myHoleCards.length > 0 && (
          <div className="showdown-section">
            <div className="showdown-section-label">
              我的手牌
              {myEval && <span className="hand-type-badge">{myEval.hand_type_name}</span>}
              {isMeWinner && settled && <span className="winner-badge">🏆 赢家</span>}
            </div>
            <div className="showdown-cards-row">
              {myHoleCards.map((card, i) => (
                <PlayingCard key={i} suit={card.suit} rank={card.rank} size="large" />
              ))}
            </div>
          </div>
        )}

        {/* 我的战绩: 始终展示 (显示净收益：赢为正 / 输为负) */}
        {settled && myPlayerId != null && myBetTotal + myWonTotal > 0 && (
          <div className="showdown-section showdown-my-result">
            <div className="showdown-section-label">我的战绩</div>
            <div className="showdown-my-row">
              <span className="showdown-my-label">本局投入</span>
              <span className="showdown-my-amount">{formatBells(myBetTotal)}</span>
            </div>
            <div className="showdown-my-row">
              <span className="showdown-my-label">净收益</span>
              <span className={`showdown-my-amount ${myNetGain >= 0 ? 'gain' : 'loss'}`}>
                {myNetGain >= 0 ? '+' : '-'}{formatBells(Math.abs(myNetGain))}
              </span>
            </div>
          </div>
        )}

        {/* 岛主操作按钮: readonly 模式只展示「关闭」 */}
        <div className="showdown-actions">
          {readonly ? (
            onClose && (
              <button className="showdown-btn showdown-btn-newhand" onClick={onClose}>
                关闭
              </button>
            )
          ) : (
            <>
              {isOwner && !settled && onSettle && (
                <button className="showdown-btn showdown-btn-settle" onClick={onSettle}>
                  🎉 确认结算
                </button>
              )}
              {isOwner && settled && !onBustClose && (
                <>
                  {onNewHand && (
                    <button className="showdown-btn showdown-btn-newhand" onClick={onNewHand}>
                      🌱 开始新一季
                    </button>
                  )}
                  {onFinalSettle && (
                    <button className="showdown-btn showdown-btn-settle" onClick={onFinalSettle}>
                      🏁 最终结算
                    </button>
                  )}
                </>
              )}
              {onBustClose && settled && (
                <button className="showdown-btn showdown-btn-settle" onClick={onBustClose}>
                  查看完毕
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default ShowdownModal
