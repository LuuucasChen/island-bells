import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { getRandomCharacterName } from '@/utils/constants'
import { useApi } from '@/hooks/useApi'
import './JoinIsland.css'

function JoinIsland() {
  const navigate = useNavigate()
  const api = useApi()
  const [code, setCode] = useState('')
  const [nickname, setNickname] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleJoin = async () => {
    if (!code.trim()) {
      setError('请输入渡渡鸟码')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.post(`/rooms/${code.trim()}/join`, {
        nickname: nickname || undefined,
      })
      navigate(`/lobby/${code.trim()}`)
    } catch (e) {
      setError('加入失败，请检查渡渡鸟码是否正确')
    }
    setLoading(false)
  }

  return (
    <Layout title="加入岛屿" back>
      <div className="join-page">
        {/* 顶部引导 */}
        <div className="join-hero-mini">
          <span className="join-hero-emoji">🐦</span>
          <span className="join-hero-text">渡渡鸟航空</span>
        </div>

        {/* 居中表单卡片 */}
        <div className="join-form-card">
          <div className="join-field">
            <label className="join-field-label">渡渡鸟码</label>
            <div className="join-underline-input">
              <input
                className="join-raw-input"
                value={code}
                onChange={(e) => { setCode(e.target.value.toUpperCase()); setError('') }}
                placeholder="如 KKTYG3"
                maxLength={6}
              />
              <div className="join-underline" />
            </div>
            {error && <div className="join-error">{error}</div>}
          </div>

          <div className="join-divider" />

          <div className="join-field">
            <label className="join-field-label">你的昵称</label>
            <div className="join-underline-row">
              <div className="join-underline-input join-underline-input--flex">
                <input
                  className="join-raw-input"
                  value={nickname}
                  onChange={(e) => setNickname(e.target.value)}
                  placeholder="留空随机生成"
                />
                <div className="join-underline" />
              </div>
              <button className="join-dice-btn" onClick={() => setNickname(getRandomCharacterName())}>
                🎲
              </button>
            </div>
          </div>
        </div>

        {/* 出发按钮 */}
        <button
          className={`join-go-btn ${loading ? 'join-go-btn-loading' : ''}`}
          onClick={handleJoin}
          disabled={loading}
        >
          <span className="join-go-btn-icon">✈️</span>
          <span>{loading ? '正在飞往...' : '出发！'}</span>
        </button>
      </div>
    </Layout>
  )
}

export default JoinIsland