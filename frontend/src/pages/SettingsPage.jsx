import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Save, LogOut } from 'lucide-react'
import { useAuth } from '../App'
import { updateSettings } from '../services/api'

export default function SettingsPage() {
  const { user, updateUser, logout } = useAuth()
  const navigate = useNavigate()
  const [storeName, setStoreName] = useState(user?.store_name || '')
  const [margin, setMargin] = useState(user?.default_margin || 30)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  async function handleSave() {
    setSaving(true)
    try {
      const data = await updateSettings({
        store_name: storeName,
        default_margin: margin,
      })
      updateUser(data.user)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      alert(err.message)
    } finally {
      setSaving(false)
    }
  }

  function handleLogout() {
    logout()
    navigate('/auth', { replace: true })
  }

  return (
    <div className="page">
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 20 }}>Settings</h2>

      <div className="card">
        <div className="form-group">
          <label className="form-label">Store name</label>
          <input
            className="form-input"
            value={storeName}
            onChange={e => setStoreName(e.target.value)}
            placeholder="Your store name"
          />
        </div>

        <div className="form-group" style={{ marginBottom: 8 }}>
          <label className="form-label">Default margin %</label>
          <div className="margin-control" style={{ marginBottom: 0 }}>
            <input
              type="range"
              min="10"
              max="60"
              value={margin}
              onChange={e => setMargin(Number(e.target.value))}
            />
            <span className="margin-value">{margin}%</span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 6 }}>
            This is your default gross margin for retail pricing. You can override it per invoice.
          </p>
        </div>

        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          <Save size={18} />
          {saved ? 'Saved!' : saving ? 'Saving...' : 'Save settings'}
        </button>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 4 }}>
          Signed in as
        </p>
        <p style={{ fontWeight: 600, marginBottom: 16 }}>{user?.email}</p>
        <button className="btn btn-danger" onClick={handleLogout}>
          <LogOut size={18} />
          Sign out
        </button>
      </div>

      <div style={{ textAlign: 'center', marginTop: 32, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        ShelfSnap v1.0.0
      </div>
    </div>
  )
}
