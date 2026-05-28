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
          <div className="home-bell-icon">
            <img src="/elements/Bells_Icon.png" alt="铃钱" className="home-bell-img" />
          </div>
          <h1 className="home-title">岛屿铃钱记</h1>
          <p className="home-desc">围坐牌桌比大小，铃钱输赢一键记</p>
          {/* 季节飘落装饰 */}
          <div className="seasonal-float">
            <img className="seasonal-item seasonal-1" src="/elements/Cherry_Blossom_Petal.png" alt="" />
            <img className="seasonal-item seasonal-2" src="/elements/Maple_Leaf.png" alt="" />
            <img className="seasonal-item seasonal-3" src="/elements/Snowflake.png" alt="" />
            <img className="seasonal-item seasonal-4" src="/elements/Cherry_Blossom_Petal.png" alt="" />
            <img className="seasonal-item seasonal-5" src="/elements/Maple_Leaf.png" alt="" />
          </div>
        </div>

        {/* 登录状态 */}
        {user && (
          <div className="home-welcome">
            <span className="home-welcome-avatar">🐾</span>
            <span><strong>{nickname}</strong>，欢迎回到岛屿！</span>
          </div>
        )}

        {!user && !loading && (
          <button className="home-login-btn" onClick={() => demoLogin()}>
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
              <img className="home-app-img" src="/elements/Tent.png" alt="创建岛屿" />
              <div className="home-app-label">创建岛屿</div>
            </button>
            <button className="home-app-card home-app-yellow" onClick={() => navigate('/join')}>
              <img className="home-app-img" src="/elements/Nook_Miles_Ticket.png" alt="加入岛屿" />
              <div className="home-app-label">加入岛屿</div>
            </button>
            <button className="home-app-card home-app-blue" onClick={() => navigate('/history')}>
              <img className="home-app-img" src="/elements/DIY_Recipe.png" alt="收获记录" />
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
