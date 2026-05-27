import { useNavigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { CONCEPT_TERMS } from '@/utils/terms'
import { useAuthStore } from '@/stores/authStore'
import './HomePage.css'

function HomePage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const nickname = useAuthStore((s) => s.user?.nickname)
  const loading = useAuthStore((s) => s.loading)
  const demoLogin = useAuthStore((s) => s.demoLogin)

  return (
    <Layout noNav>
      <div className="home-container">
        {/* Hero 区 */}
        <div className="home-hero">
          <div className="home-bell-icon">🔔</div>
          <h1 className="home-title">岛屿铃钱记</h1>
          <p className="home-desc">线下铃钱管理助手，让每一季的收获都清晰可见</p>
        </div>

        {/* 登录状态 */}
        {user && (
          <div className="home-welcome">
            <span className="home-welcome-avatar">🐾</span>
            <span>欢迎，<strong>{nickname}</strong></span>
          </div>
        )}

        {!user && !loading && (
          <button className="home-login-btn" onClick={() => demoLogin('居民')}>
            <span className="home-login-btn-icon">🏝️</span>
            <span>开始登岛</span>
          </button>
        )}

        {loading && (
          <div className="home-loading">正在登岛...</div>
        )}

        {/* NookPhone 风格应用网格 */}
        {user && (
          <div className="home-app-grid">
            <button className="home-app-card home-app-teal" onClick={() => navigate('/create')}>
              <div className="home-app-icon">🏝️</div>
              <div className="home-app-label">创建岛屿</div>
            </button>
            <button className="home-app-card home-app-yellow" onClick={() => navigate('/join')}>
              <div className="home-app-icon">🐦</div>
              <div className="home-app-label">加入岛屿</div>
            </button>
            <button className="home-app-card home-app-blue" onClick={() => navigate('/history')}>
              <div className="home-app-icon">📜</div>
              <div className="home-app-label">收获记录</div>
            </button>
          </div>
        )}

        {/* 底部提示 */}
        <div className="home-tips">
          <p>💡 <strong>{CONCEPT_TERMS.roomCode}</strong>：创建岛屿后生成的6位码，分享给朋友即可加入</p>
        </div>
      </div>
    </Layout>
  )
}

export default HomePage
