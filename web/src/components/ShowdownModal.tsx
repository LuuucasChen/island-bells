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

  // 收获汇总：按 winner_id 聚合总收入（避免在每个池子里重复展示赢家，防止误导）
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
  const winSummaryList = Object.values(winSummary).sort((a, b) => b.total - a.total)

  // 我的本局投入 (输家时展示)
  const myBetTotal = myPlayerId != null
    ? (bets || []).filter((b) => b.player_id === myPlayerId).reduce((s, b) => s + b.amount, 0)
    : 0

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
                  <span className="showdown-summary-amount">+{formatBells(s.total)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

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

        {/* 我的战绩: 仅输家时展示 (赢家已在收获汇总中高亮，避免重复) */}
        {settled && !isMeWinner && myPlayerId != null && myBetTotal > 0 && (
          <div className="showdown-section showdown-my-result">
            <div className="showdown-section-label">我的战绩</div>
            <div className="showdown-my-row">
              <span className="showdown-my-label">本局投入</span>
              <span className="showdown-my-amount loss">-{formatBells(myBetTotal)}</span>
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
