import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { CONCEPT_TERMS } from '@/utils/terms'
import { CHIP_PRESETS, BLIND_PRESETS, getRandomCharacterName, getRandomIslandName, getCharacterAvatar } from '@/utils/constants'
import { useApi } from '@/hooks/useApi'
import './CreateIsland.css'

function CreateIsland() {
  const navigate = useNavigate()
  const api = useApi()
  const [roomName, setRoomName] = useState('')
  const [nickname, setNickname] = useState('')
  const [chipCount, setChipCount] = useState(10000)
  const [sb, setSb] = useState(50)
  const [bb, setBb] = useState(100)
  const [loading, setLoading] = useState(false)
  const [customChips, setCustomChips] = useState('')
  const [customSb, setCustomSb] = useState('')
  const [customBb, setCustomBb] = useState('')

  const handleCreate = async () => {
    setLoading(true)
    try {
      const data = await api.post('/rooms', {
        name: roomName || undefined,
        nickname: nickname || undefined,
        initial_chips: chipCount,
        sb_amount: sb,
        bb_amount: bb,
      })
      navigate(`/lobby/${data.room_code}`)
    } catch (e) {
      alert('创建失败: ' + (e as Error).message)
    }
    setLoading(false)
  }

  return (
    <Layout title="🏝️ 创建岛屿" back>
      <div className="create-page">
        {/* 表单卡片 */}
        <div className="create-form-card">
          <div className="create-card-watermark" />
          {/* 岛屿名称 */}
          <div className="create-field">
            <label className="create-field-label">岛屿名称</label>
            <div className="create-underline-row">
              <div className="create-underline-input create-underline-input--flex">
                <input
                  className="create-raw-input"
                  value={roomName}
                  onChange={(e) => setRoomName(e.target.value)}
                  placeholder="留空则随机生成"
                />
                <div className="create-underline" />
              </div>
              <button className="create-dice-btn" onClick={() => setRoomName(getRandomIslandName())}>
                🎲
              </button>
            </div>
          </div>

          <div className="create-divider" />

          {/* 你的昵称 */}
          <div className="create-field">
            <label className="create-field-label">你的昵称</label>
            <div className="create-underline-row">
              {getCharacterAvatar(nickname) && (
                <img className="create-nickname-avatar" src={getCharacterAvatar(nickname)!} alt="" />
              )}
              <div className="create-underline-input create-underline-input--flex">
                <input
                  className="create-raw-input"
                  value={nickname}
                  onChange={(e) => setNickname(e.target.value)}
                  placeholder="留空则随机生成"
                />
                <div className="create-underline" />
              </div>
              <button className="create-dice-btn" onClick={() => setNickname(getRandomCharacterName())}>
                🎲
              </button>
            </div>
          </div>

          <div className="create-divider" />

          {/* 铃钱初始数量 */}
          <div className="create-field">
            <label className="create-field-label">
              <img className="create-inline-icon" src="/elements/Bells_Icon.png" alt="" />
              {CONCEPT_TERMS.chips}初始数量
            </label>
            <div className="create-preset-grid">
              {CHIP_PRESETS.map((p) => (
                <button
                  key={p.value}
                  className={`create-preset-btn ${chipCount === p.value ? 'create-preset-active' : ''}`}
                  onClick={() => setChipCount(p.value)}
                >
                  🔔 {p.label}
                </button>
              ))}
            </div>
            <div className="create-underline-input">
              <input
                className="create-raw-input create-raw-input--sm"
                type="number"
                value={customChips}
                onChange={(e) => {
                  setCustomChips(e.target.value)
                  const v = Number(e.target.value)
                  if (v > 0) setChipCount(v)
                }}
                placeholder="自定义数量..."
              />
              <div className="create-underline" />
            </div>
          </div>

          <div className="create-divider" />

          {/* 树苗费 / 大树费 */}
          <div className="create-field">
            <label className="create-field-label">
              <img className="create-inline-icon" src="/elements/Sapling.png" alt="" />
              {CONCEPT_TERMS.smallBlind} / {CONCEPT_TERMS.bigBlind}
            </label>
            <div className="create-preset-grid">
              {BLIND_PRESETS.map((p) => (
                <button
                  key={`${p.sb}-${p.bb}`}
                  className={`create-preset-btn ${sb === p.sb && bb === p.bb ? 'create-preset-active' : ''}`}
                  onClick={() => { setSb(p.sb); setBb(p.bb); setCustomSb(''); setCustomBb('') }}
                >
                  🌱 {p.label}
                </button>
              ))}
            </div>
            <div className="create-blind-inputs">
              <div className="create-underline-input create-underline-input--half">
                <div className="create-blind-hint">🌱 {CONCEPT_TERMS.smallBlind}</div>
                <input
                  className="create-raw-input create-raw-input--sm"
                  type="number"
                  value={customSb}
                  onChange={(e) => {
                    setCustomSb(e.target.value)
                    const v = Number(e.target.value)
                    if (v > 0) setSb(v)
                  }}
                  placeholder="自定义..."
                />
                <div className="create-underline" />
              </div>
              <div className="create-underline-input create-underline-input--half">
                <div className="create-blind-hint">🌳 {CONCEPT_TERMS.bigBlind}</div>
                <input
                  className="create-raw-input create-raw-input--sm"
                  type="number"
                  value={customBb}
                  onChange={(e) => {
                    setCustomBb(e.target.value)
                    const v = Number(e.target.value)
                    if (v > 0) setBb(v)
                  }}
                  placeholder="自定义..."
                />
                <div className="create-underline" />
              </div>
            </div>
          </div>
        </div>

        {/* 确认按钮 */}
        <button
          className={`create-go-btn ${loading ? 'create-go-btn-loading' : ''}`}
          onClick={handleCreate}
          disabled={loading}
        >
          <span className="create-go-btn-icon">
              <img className="create-btn-img" src="/elements/Tent.png" alt="" />
            </span>
          <span>{loading ? '正在创建...' : '确认创建岛屿'}</span>
        </button>
      </div>
    </Layout>
  )
}

export default CreateIsland