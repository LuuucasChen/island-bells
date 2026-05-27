import React from 'react'
import { useNavigate } from 'react-router-dom'
import { CONCEPT_TERMS } from '@/utils/terms'
import './NavBar.css'

interface NavBarProps {
  title?: string
  back?: boolean
  right?: React.ReactNode
  onBack?: () => void
}

export const NavBar: React.FC<NavBarProps> = ({ title = CONCEPT_TERMS.room, back = false, right, onBack }) => {
  const navigate = useNavigate()

  const handleBack = () => {
    if (onBack) {
      onBack()
    } else {
      navigate(-1)
    }
  }

  return (
    <nav className="nav-bar">
      {back && (
        <button className="nav-back" onClick={handleBack} aria-label="返回">
          ←
        </button>
      )}
      <div className="nav-title">{title}</div>
      {right && <div className="nav-right">{right}</div>}
    </nav>
  )
}