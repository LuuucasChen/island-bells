import './PlayingCard.css'

interface PlayingCardProps {
  suit: 'spades' | 'hearts' | 'diamonds' | 'clubs'
  rank: number  // 2-14 (14=Ace)
  faceDown?: boolean
  size?: 'small' | 'normal' | 'large'
  className?: string
}

const SUIT_SYMBOLS: Record<string, string> = {
  spades: '♠',
  hearts: '♥',
  diamonds: '♦',
  clubs: '♣',
}

const RANK_DISPLAY: Record<number, string> = {
  2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8',
  9: '9', 10: '10', 11: 'J', 12: 'Q', 13: 'K', 14: 'A',
}

export function PlayingCard({ suit, rank, faceDown, size = 'normal', className = '' }: PlayingCardProps) {
  const isRed = suit === 'hearts' || suit === 'diamonds'
  const symbol = SUIT_SYMBOLS[suit] || '?'
  const rankStr = RANK_DISPLAY[rank] || String(rank)

  if (faceDown) {
    return (
      <div className={`playing-card card-back card-${size} ${className}`}>
        <div className="card-back-pattern">🍃</div>
      </div>
    )
  }

  return (
    <div className={`playing-card card-face card-${size} ${isRed ? 'card-red' : 'card-black'} ${className}`}>
      <div className="card-rank-top">{rankStr}</div>
      <div className="card-center">
        <span className="card-suit-large">{symbol}</span>
      </div>
      <div className="card-rank-bottom">{rankStr}</div>
    </div>
  )
}

export default PlayingCard
