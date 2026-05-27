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
}

interface ShowdownModalProps {
  pots: PotInfo[]
  players: PlayerInfo[]
  communityCards: CardData[]
  myHoleCards: CardData[]
  allHoleCards: Record<string, CardData[]>
  evaluations: Record<string, Evaluation>
  results: ResultInfo[]
  isOwner: boolean
  onSettle: () => void
  onNewHand: () => void
  /** 岛主点击最终结算 */
  onFinalSettle?: () => void
  settled: boolean
  myUserId: number
  endedByFold?: boolean
  muckPlayerId?: number | null
  /** 输光玩家关闭弹窗回调 (设置后显示"关闭"按钮) */
  onBustClose?: () => void
}

export function ShowdownModal({
  pots,
  players,
  communityCards,
  myHoleCards,
  allHoleCards,
  evaluations,
  results,
  isOwner,
  onSettle,
  onNewHand,
  onFinalSettle,
  settled,
  myUserId,
  endedByFold,
  muckPlayerId,
  onBustClose,
}: ShowdownModalProps) {
  const playerMap = Object.fromEntries(players.map((p) => [p.player_id, p]))

  // 找到赢家信息
  const winnerIds = results?.map((r) => r.winner_id) || []
  const winners = winnerIds.map((id) => playerMap[id]).filter(Boolean)
  const winnerNicknames = winners.map((w) => w.nickname).join('、')

  // 检查赢家是否盖牌
  const isWinnerMucked = muckPlayerId ? winnerIds.includes(muckPlayerId) : false

  // 找到赢家的手牌（取第一个赢家）— 如果盖牌则为空
  const winnerCards = !isWinnerMucked && winnerIds.length > 0
    ? (allHoleCards[String(winnerIds[0])] || [])
    : []

  // 找到我的手牌对应的 player_id
  const myPlayer = players.find((p) => p.user_id === myUserId)
  const myPlayerId = myPlayer?.player_id
  const isMeWinner = myPlayerId ? winnerIds.includes(myPlayerId) : false
  const myEval = myPlayerId ? evaluations[String(myPlayerId)] : null
  const winnerEval = winnerIds.length > 0 ? evaluations[String(winnerIds[0])] : null

  return (
    <div className="showdown-overlay">
      <div className="showdown-modal">
        <div className="showdown-header">
          <div className="showdown-icon">{settled ? '🏆' : '⏳'}</div>
          <h3 className="showdown-title">
            {settled ? '收获结算完成' : '收获时刻'}
          </h3>
        </div>

        {/* 赢家手牌 */}
        {settled && winnerCards.length > 0 && (
          <div className="showdown-section">
            <div className="showdown-section-label">
              🏆 {winnerNicknames} 的手牌
              {winnerEval && <span className="hand-type-badge">{winnerEval.hand_type_name}</span>}
            </div>
            <div className="showdown-cards-row">
              {winnerCards.map((card, i) => (
                <PlayingCard key={i} suit={card.suit} rank={card.rank} size="normal" />
              ))}
            </div>
          </div>
        )}

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

        {/* 收获篮列表 */}
        <div className="showdown-pots">
          {pots.map((pot) => {
            const potWinnerResults = results?.filter(() => true) || []
            return (
              <div key={pot.pot_id} className="showdown-pot">
                <div className="pot-info">
                  <span className="pot-type-badge">
                    {pot.pot_type === 'main' ? '🌟 主池' : `🌿 边池 ${pot.pot_level}`}
                  </span>
                  <span className="pot-amount-display">{formatBells(pot.amount)}</span>
                </div>
                {settled && potWinnerResults.length > 0 && (
                  <div className="pot-winner">
                    {potWinnerResults.map((r) => {
                      const winner = playerMap[r.winner_id]
                      return (
                        <div key={r.winner_id} className="winner-line">
                          <span className="winner-name">{winner?.nickname || '未知'}</span>
                          <span className="winner-amount">+{formatBells(r.amount_won)}</span>
                          {r.is_split === 1 && <span className="winner-split">(平分)</span>}
                        </div>
                      )
                    })}
                  </div>
                )}
                {!settled && (
                  <div className="pot-eligible">等待结算...</div>
                )}
              </div>
            )
          })}
        </div>

        {/* 岛主操作按钮 */}
        <div className="showdown-actions">
          {isOwner && !settled && (
            <button className="showdown-btn showdown-btn-settle" onClick={onSettle}>
              🎉 确认结算
            </button>
          )}
          {isOwner && settled && !onBustClose && (
            <>
              <button className="showdown-btn showdown-btn-newhand" onClick={onNewHand}>
                🌱 开始新一季
              </button>
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
        </div>
      </div>
    </div>
  )
}

export default ShowdownModal
