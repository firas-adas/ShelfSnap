import React, { useState, useEffect, createContext, useContext } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useNavigate } from 'react-router-dom'
import { Camera, FileText, Package, Settings, Zap, Home } from 'lucide-react'
import { getMe } from './services/api'
import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import ScanPage from './pages/ScanPage'
import ReviewPage from './pages/ReviewPage'
import InvoicesPage from './pages/InvoicesPage'
import ProductsPage from './pages/ProductsPage'
import SettingsPage from './pages/SettingsPage'

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('shelfsnap_token')
    if (!token) {
      setLoading(false)
      return
    }
    getMe()
      .then(data => setUser(data.user))
      .catch(() => localStorage.removeItem('shelfsnap_token'))
      .finally(() => setLoading(false))
  }, [])

  function loginUser(token, userData) {
    localStorage.setItem('shelfsnap_token', token)
    setUser(userData)
  }

  function logout() {
    localStorage.removeItem('shelfsnap_token')
    setUser(null)
  }

  function updateUser(userData) {
    setUser(userData)
  }

  if (loading) {
    return (
      <div className="loading-overlay" style={{ minHeight: '100dvh' }}>
        <div className="spinner" />
      </div>
    )
  }

  return (
    <AuthContext.Provider value={{ user, loginUser, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  )
}

function ProtectedRoute({ children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/auth" replace />
  return children
}

function AppShell() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/auth" replace />

  return (
    <div className="app-shell">
      <div className="top-bar">
        <NavLink to="/" className="logo">
          <div className="logo-icon">
            <Zap size={18} />
          </div>
          ShelfSnap
        </NavLink>
      </div>

      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/scan" element={<ScanPage />} />
        <Route path="/review/:invoiceId" element={<ReviewPage />} />
        <Route path="/invoices" element={<InvoicesPage />} />
        <Route path="/products" element={<ProductsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      <nav className="bottom-nav">
        <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <Home size={22} />
          Home
        </NavLink>
        <NavLink to="/scan" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <Camera size={22} />
          Scan
        </NavLink>
        <NavLink to="/invoices" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <FileText size={22} />
          Invoices
        </NavLink>
        <NavLink to="/products" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <Package size={22} />
          Products
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <Settings size={22} />
          Settings
        </NavLink>
      </nav>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
