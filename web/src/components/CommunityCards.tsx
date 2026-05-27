import { useEffect, useState, useRef } from 'react'
import { PlayingCard } from './PlayingCard'
import './CommunityCards.css'

interface CardData {
  suit: 'spades' | 'hearts' | 'diamonds' | 'clubs'
  rank: number
}

interface CommunityCardsProps {
  cards: CardData[]
  currentRound: string
  /** 是否进入逐张翻牌模式 (showdown reveal) */
  revealing?: boolean
  /** 翻牌全部完成回调 */
  onRevealComplete?: () => void
}

export function CommunityCards({ cards, currentRound, revealing, onRevealComplete }: CommunityCardsProps) {
  // 根据当前轮次决定应该有几张公共牌
  const expectedCount = currentRound === 'preflop' ? 0
    : currentRound === 'flop' ? 3
    : currentRound === 'turn' ? 4
    : 5

  // 翻牌动画状态: 已翻开的牌数量
  const [revealedCount, setRevealedCount] = useState(revealing ? 0 : 5)
  const revealTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // 记录 revealing 开始前的牌数（已亮起的牌不需要再翻）
  const previouslyVisibleRef = useRef(0)

  // 追踪 cards 变化：在 revealing 开始前记住已有几张牌
  const prevCardsLenRef = useRef(cards.length)
  if (!revealing) {
    prevCardsLenRef.current = cards.length
  }

  useEffect(() => {
    if (!revealing) {
      setRevealedCount(5)
      return
    }

    // revealing 开始时，之前已经亮起的牌数
    const alreadyShown = prevCardsLenRef.current
    previouslyVisibleRef.current = alreadyShown

    if (alreadyShown >= 5) {
      // 所有牌都已经亮过了，跳过翻牌动画
      setRevealedCount(5)
      onRevealComplete?.()
      return
    }

    // 从已亮起的数量开始翻，只翻新增的牌
    setRevealedCount(alreadyShown)
    let count = alreadyShown
    revealTimerRef.current = setInterval(() => {
      count++
      setRevealedCount(count)
      if (count >= 5) {
        if (revealTimerRef.current) clearInterval(revealTimerRef.current)
        revealTimerRef.current = null
        onRevealComplete?.()
      }
    }, 800)

    return () => {
      if (revealTimerRef.current) {
        clearInterval(revealTimerRef.current)
        revealTimerRef.current = null
      }
    }
  }, [revealing, cards.length])

  // 翻牌模式下，5张都应该是可见的（从后端获取的 showdown 数据）
  const displayCards = revealing ? (cards.length >= 5 ? cards : cards) : cards

  return (
    <div className="community-cards">
      <div className="community-label">公共牌</div>
      <div className="community-row">
        {Array.from({ length: 5 }).map((_, i) => {
          const card = displayCards[i]

          if (revealing) {
            if (card) {
              const isRevealed = i < revealedCount
              // 翻牌前就已经亮起的牌，直接显示不需要翻转动画
              const wasAlreadyShown = i < previouslyVisibleRef.current
              if (wasAlreadyShown) {
                return (
                  <PlayingCard
                    key={i}
                    suit={card.suit}
                    rank={card.rank}
                    size="normal"
                    className="community-card-item"
                  />
                )
              }
              return (
                <div
                  key={i}
                  className={`community-card-flip-wrapper ${isRevealed ? 'revealed' : 'face-down'}`}
                >
                  <PlayingCard
                    suit={card.suit}
                    rank={card.rank}
                    size="normal"
                    faceDown={!isRevealed}
                    className="community-card-item"
                  />
                </div>
              )
            }
            return <div key={i} className="community-card-placeholder" />
          }

          // 正常模式
          if (card) {
            return (
              <PlayingCard
                key={i}
                suit={card.suit}
                rank={card.rank}
                size="normal"
                className="community-card-item"
              />
            )
          }
          // 未发的牌显示占位
          if (i < expectedCount) {
            return <div key={i} className="community-card-placeholder dealing" />
          }
          return <div key={i} className="community-card-placeholder" />
        })}
      </div>
    </div>
  )
}

export default CommunityCards
