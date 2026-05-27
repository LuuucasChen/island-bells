import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import './styles/global.css'
import './styles/seats.css'
import './styles/game.css'
import App from './App'

// Demo auto-login: 如果没有 token，自动以"居民"身份登录
const { token } = useAuthStore.getState()
if (!token) {
  useAuthStore.getState().demoLogin('居民')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)