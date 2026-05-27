import { formatBells } from '@/utils/terms'
import type { SettlementItem } from '@/stores/gameStore'
import './ShowdownModal.css'

interface FinalSettlementModalProps {
  settlement: SettlementItem[]
  myUserId: number
  onClose: () => void
}

export function FinalSettlementModal({ settlement, myUserId, onClose }: FinalSettlementModalProps) {
  const maxProfit = Math.max(...settlement.map(s => Math.abs(s.net_profit)), 1)

  return (
    <div className="showdown-overlay" style={{ zIndex: 1100 }}>
      <div className="showdown-modal" style={{ maxWidth: 480 }}>
        <div className="showdown-header">
          <div className="showdown-icon">🏝️</div>
          <h3 className="showdown-title">岛屿结算</h3>
          <div style={{ color: '#999', fontSize: 13, marginTop: 4 }}>冒险结束，收获盘点</div>
        </div>

        <div style={{ padding: '0 16px 16px' }}>
          {/* 表头 */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 80px 80px 90px',
            gap: 4,
            padding: '8px 0',
            borderBottom: '1px solid rgba(255,255,255,0.1)',
            fontSize: 12,
            color: '#999',
          }}>
            <span>居民</span>
            <span style={{ textAlign: 'right' }}>最终铃钱</span>
            <span style={{ textAlign: 'right' }}>补给</span>
            <span style={{ textAlign: 'right' }}>净收益</span>
          </div>

          {/* 玩家列表 */}
          {settlement.map((s, i) => {
            const isMe = s.user_id === myUserId
            const profitColor = s.net_profit > 0 ? '#4caf50' : s.net_profit < 0 ? '#f44336' : '#999'
            const barWidth = Math.abs(s.net_profit) / maxProfit * 100

            return (
              <div key={s.player_id} style={{
                padding: '10px 0',
                borderBottom: '1px solid rgba(255,255,255,0.05)',
                background: isMe ? 'rgba(255,255,255,0.05)' : 'transparent',
                borderRadius: isMe ? 8 : 0,
                paddingLeft: isMe ? 8 : 0,
                paddingRight: isMe ? 8 : 0,
              }}>
                {/* 排名行 */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 80px 80px 90px',
                  gap: 4,
                  alignItems: 'center',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: '50%',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 12, fontWeight: 700,
                      background: i === 0 ? '#f5c31c' : i === 1 ? '#c0c0c0' : i === 2 ? '#cd7f32' : '#555',
                      color: '#fff',
                    }}>
                      {i + 1}
                    </span>
                    <span style={{
                      fontWeight: isMe ? 700 : 400,
                      color: isMe ? '#fff' : '#ccc',
                    }}>
                      {s.nickname}
                      {isMe && <span style={{ fontSize: 11, color: '#999', marginLeft: 4 }}>(我)</span>}
                    </span>
                  </div>
                  <span style={{ textAlign: 'right', fontSize: 13, color: '#ccc' }}>
                    {formatBells(s.final_chips)}
                  </span>
                  <span style={{ textAlign: 'right', fontSize: 13, color: s.rebuy_total > 0 ? '#ff9800' : '#666' }}>
                    {s.rebuy_total > 0 ? formatBells(s.rebuy_total) : '-'}
                  </span>
                  <span style={{
                    textAlign: 'right',
                    fontSize: 14,
                    fontWeight: 700,
                    color: profitColor,
                  }}>
                    {s.net_profit > 0 ? '+' : ''}{formatBells(s.net_profit)}
                  </span>
                </div>

                {/* 收益条 */}
                <div style={{
                  marginTop: 4,
                  height: 3,
                  background: 'rgba(255,255,255,0.05)',
                  borderRadius: 2,
                  overflow: 'hidden',
                }}>
                  <div style={{
                    width: `${barWidth}%`,
                    height: '100%',
                    background: profitColor,
                    borderRadius: 2,
                    transition: 'width 0.5s ease',
                  }} />
                </div>
              </div>
            )
          })}
        </div>

        <div className="showdown-actions">
          <button className="showdown-btn showdown-btn-newhand" onClick={onClose}>
            🏠 返回大厅
          </button>
        </div>
      </div>
    </div>
  )
}

export default FinalSettlementModal
