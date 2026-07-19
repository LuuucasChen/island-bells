import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import './styles/global.css'
import './styles/seats.css'
import './styles/game.css'
import App from './App'

// Demo auto-login: 如果没有 token，自动以"居民"身份登录
// demoLogin 内部会校验响应并在失败时设置 error 态 (不会写入空 token)
const { token } = useAuthStore.getState()
if (!token) {
  useAuthStore.getState().demoLogin('居民').finally(() => {
    const err = useAuthStore.getState().error
    if (err) {
      console.error('自动登录失败:', err)
    }
  })
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)