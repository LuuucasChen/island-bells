import React from 'react'
import { NavBar } from './NavBar'
import './Layout.css'

interface LayoutProps {
  title?: string
  back?: boolean
  right?: React.ReactNode
  onBack?: () => void
  children: React.ReactNode
  noNav?: boolean
}

export const Layout: React.FC<LayoutProps> = ({ title, back, right, onBack, children, noNav }) => {
  return (
    <div className="layout">
      {!noNav && <NavBar title={title} back={back} right={right} onBack={onBack} />}
      <main className="layout-body app-page">
        {children}
      </main>
    </div>
  )
}