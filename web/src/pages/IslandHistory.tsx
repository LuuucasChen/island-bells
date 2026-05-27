import { useState, useEffect } from 'react'
import { Layout } from '@/components/Layout'
import { Card } from 'animal-island-ui'
import { CONCEPT_TERMS, formatBells } from '@/utils/terms'
import { formatDate } from '@/utils/format'
import { useApi } from '@/hooks/useApi'
import './IslandHistory.css'

interface HistoryItem {
  room_id: number
  room_code: string
  nickname: string
  final_chips: number
  initial_chips: number
  profit: number
  created_at: string
  finished_at: string
}

function IslandHistory() {
  const api = useApi()
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadHistory()
  }, [])

  const loadHistory = async () => {
    try {
      // 使用 my-rooms 端点获取房间历史
      const data = await api.get('/rooms/my-rooms')
      setHistory(data.rooms || [])
    } catch {
      // 如果端点不存在，使用空列表
      setHistory([])
    }
    setLoading(false)
  }

  return (
    <Layout title="收获记录" back>
      {loading && <div className="app-empty">正在加载...</div>}

      {!loading && history.length === 0 && (
        <div className="app-empty">
          <div className="history-empty-icon">📜</div>
          <p>还没有收获记录</p>
          <p>去创建或加入一个岛屿吧！</p>
        </div>
      )}

      {!loading && history.length > 0 && (
        <div className="history-list">
          {history.map((item) => (
            <Card key={item.room_id} color="app-teal" style={{ marginBottom: 12 }}>
              <div className="history-item">
                <div className="history-header">
                  <span className="history-code">🏝️ {CONCEPT_TERMS.roomCode}: {item.room_code}</span>
                  <span className="history-date">{formatDate(item.finished_at || item.created_at)}</span>
                </div>
                <div className="history-body">
                  <span>{item.nickname}</span>
                  <span className="history-profit">
                    {item.profit >= 0 ? '+' : ''}{formatBells(item.profit)} 🔔
                  </span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </Layout>
  )
}

export default IslandHistory