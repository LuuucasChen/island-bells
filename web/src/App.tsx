import { Routes, Route } from 'react-router-dom'
import HomePage from './pages/HomePage'
import CreateIsland from './pages/CreateIsland'
import JoinIsland from './pages/JoinIsland'
import IslandLobby from './pages/IslandLobby'
import GameTable from './pages/GameTable'
import IslandHistory from './pages/IslandHistory'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/create" element={<CreateIsland />} />
      <Route path="/join" element={<JoinIsland />} />
      <Route path="/lobby/:code" element={<IslandLobby />} />
      <Route path="/game/:roomId" element={<GameTable />} />
      <Route path="/history" element={<IslandHistory />} />
    </Routes>
  )
}

export default App