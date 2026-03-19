import React, { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Camera, Upload, Plus, X, Zap } from 'lucide-react'
import { useAuth } from '../App'
import { scanInvoice } from '../services/api'

export default function ScanPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const fileRef = useRef(null)
  const [photos, setPhotos] = useState([])  // { file, preview }
  const [margin, setMargin] = useState(user?.default_margin || 30)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)

  function addFiles(fileList) {
    const newPhotos = []
    for (const f of fileList) {
      if (!f.type.startsWith('image/')) continue
      const reader = new FileReader()
      reader.onload = e => {
        setPhotos(prev => [...prev, { file: f, preview: e.target.result, id: Date.now() + Math.random() }])
      }
      reader.readAsDataURL(f)
    }
  }

  function removePhoto(id) {
    setPhotos(prev => prev.filter(p => p.id !== id))
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }

  async function handleScan() {
    if (!photos.length) return
    setLoading(true)
    setError('')
    try {
      const files = photos.map(p => p.file)
      const data = await scanInvoice(files, margin)
      navigate(`/review/${data.invoice.id}`)
    } catch (err) {
      if (err.message.includes('already exists')) {
        setError(err.message)
      } else {
        setError(err.message)
      }
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="loading-overlay">
          <div className="spinner" />
          <p style={{ fontWeight: 600, fontSize: 16 }}>
            Scanning {photos.length} {photos.length === 1 ? 'page' : 'pages'}...
          </p>
          <p>
            AI is reading every line item and calculating prices.
            {photos.length > 1 && ' Multi-page invoices take a bit longer.'}
            {' '}This usually takes {photos.length > 1 ? '15 to 30' : '5 to 15'} seconds.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700 }}>Scan invoice</h2>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: 14, marginTop: 4 }}>
          Take photos of your invoice. Add multiple pages if needed.
        </p>
      </div>

      {error && (
        <div className="error-msg" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span>{error}</span>
          {error.includes('clearly') && (
            <span style={{ fontSize: 12, opacity: 0.8 }}>
              Tip: Make sure the invoice is flat, well-lit, and the text is in focus.
            </span>
          )}
          {error.includes('already exists') && (
            <button
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 4 }}
              onClick={() => navigate('/invoices')}
            >
              View existing invoices
            </button>
          )}
        </div>
      )}

      {/* Photo grid / upload area */}
      {photos.length === 0 ? (
        <>
          <div
            className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
            onClick={() => fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
          >
            <Camera />
            <p className="upload-cta">Tap to take a photo</p>
            <p>or drag and drop invoice images</p>
          </div>

          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            style={{ display: 'none' }}
            onChange={e => addFiles(e.target.files)}
          />

          <div style={{ textAlign: 'center', margin: '16px 0', color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            or
          </div>

          <button
            className="btn btn-secondary"
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = 'image/*'
              input.multiple = true
              input.onchange = e => addFiles(e.target.files)
              input.click()
            }}
          >
            <Upload size={18} />
            Choose from gallery
          </button>
        </>
      ) : (
        <>
          {/* Photo thumbnails */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: photos.length === 1 ? '1fr' : '1fr 1fr',
            gap: 8,
            marginBottom: 16,
          }}>
            {photos.map((photo, idx) => (
              <div key={photo.id} style={{
                position: 'relative',
                borderRadius: 'var(--radius-md)',
                overflow: 'hidden',
                border: '1px solid var(--color-border)',
              }}>
                <img
                  src={photo.preview}
                  alt={`Page ${idx + 1}`}
                  style={{
                    width: '100%',
                    height: photos.length === 1 ? 'auto' : 160,
                    objectFit: 'cover',
                    display: 'block',
                  }}
                />
                {/* Page number badge */}
                <div style={{
                  position: 'absolute', top: 6, left: 6,
                  background: 'rgba(0,0,0,0.6)', color: 'white',
                  fontSize: 11, fontWeight: 600, padding: '2px 8px',
                  borderRadius: 100,
                }}>
                  Page {idx + 1}
                </div>
                {/* Remove button */}
                <button
                  onClick={() => removePhoto(photo.id)}
                  style={{
                    position: 'absolute', top: 6, right: 6,
                    width: 28, height: 28, borderRadius: '50%',
                    background: 'rgba(0,0,0,0.6)', color: 'white',
                    border: 'none', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <X size={14} />
                </button>
              </div>
            ))}

            {/* Add more button */}
            <button
              onClick={() => {
                const input = document.createElement('input')
                input.type = 'file'
                input.accept = 'image/*'
                input.multiple = true
                input.capture = 'environment'
                input.onchange = e => addFiles(e.target.files)
                input.click()
              }}
              style={{
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 6,
                minHeight: photos.length === 1 ? 80 : 160,
                borderRadius: 'var(--radius-md)',
                border: '2px dashed var(--color-border-strong)',
                background: 'var(--color-surface)',
                cursor: 'pointer', color: 'var(--color-primary)',
                fontSize: 12, fontWeight: 600,
                fontFamily: 'var(--font)',
                transition: 'border-color 0.15s',
              }}
            >
              <Plus size={24} />
              Add page
            </button>
          </div>

          {/* Photo count info */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '10px 14px', borderRadius: 'var(--radius-sm)',
            background: 'var(--color-primary-light)', marginBottom: 12,
            fontSize: 13, color: 'var(--color-primary-dark)',
          }}>
            <Zap size={14} />
            <span>
              <strong>{photos.length} {photos.length === 1 ? 'page' : 'pages'}</strong> ready to scan.
              {photos.length > 1 && ' Items across all pages will be merged and deduplicated.'}
            </span>
          </div>

          {/* Margin control */}
          <div className="margin-control">
            <label>Margin</label>
            <input
              type="range"
              min="10"
              max="60"
              value={margin}
              onChange={e => setMargin(Number(e.target.value))}
            />
            <span className="margin-value">{margin}%</span>
          </div>

          {/* Actions */}
          <button className="btn btn-primary" onClick={handleScan}>
            <Camera size={18} />
            Scan {photos.length > 1 ? `all ${photos.length} pages` : 'and price items'}
          </button>

          <button
            className="btn btn-ghost"
            style={{ marginTop: 8 }}
            onClick={() => { setPhotos([]); setError('') }}
          >
            Start over
          </button>
        </>
      )}
    </div>
  )
}
