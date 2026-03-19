import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Printer, Check, ChevronLeft, Pencil, X, ChevronDown, Tag, Trash2 } from 'lucide-react'
import { getInvoice, updateItem, confirmInvoice, generateLabels, deleteInvoice } from '../services/api'

const MARGIN_PRESETS = [
  { key: 'single_beer',   label: 'Single beer/soda',  margin: 45, range: '40-55%', color: '#E8621A' },
  { key: '6pack',         label: '6-pack',             margin: 30, range: '25-35%', color: '#1B8C5A' },
  { key: '12pack',        label: '12-pack',            margin: 25, range: '20-30%', color: '#1976D2' },
  { key: '24pack',        label: '24/30-pack',         margin: 18, range: '15-22%', color: '#7B1FA2' },
  { key: 'energy',        label: 'Energy drink',       margin: 50, range: '45-55%', color: '#D32F2F' },
  { key: 'snack',         label: 'Chips/snacks',       margin: 45, range: '40-50%', color: '#F57F17' },
  { key: 'candy',         label: 'Candy/gum',          margin: 50, range: '45-55%', color: '#C2185B' },
  { key: 'tobacco',       label: 'Tobacco',            margin: 12, range: '8-15%',  color: '#5D4037' },
  { key: 'water',         label: 'Water/juice',        margin: 50, range: '45-55%', color: '#0288D1' },
  { key: 'custom',        label: 'Custom',             margin: 30, range: '',       color: '#666' },
]

function getUnitCost(item) {
  return item.case_cost / (item.units_per_case || 1)
}

function calcRetail(unitCost, marginPct) {
  if (marginPct >= 100) marginPct = 50
  return unitCost / (1 - marginPct / 100)
}

export default function ReviewPage() {
  const { invoiceId } = useParams()
  const navigate = useNavigate()
  const [invoice, setInvoice] = useState(null)
  const [items, setItems] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState(null)
  const [editValues, setEditValues] = useState({})
  const [printing, setPrinting] = useState(false)
  const [marginOpenId, setMarginOpenId] = useState(null)
  const [customMargins, setCustomMargins] = useState({})
  const [savingMargin, setSavingMargin] = useState(null)

  useEffect(() => {
    getInvoice(invoiceId)
      .then(data => {
        setInvoice(data.invoice)
        setItems(data.items)
        setSelected(new Set(data.items.map(i => i.id)))
      })
      .catch(() => navigate('/invoices'))
      .finally(() => setLoading(false))
  }, [invoiceId])

  function toggleSelect(id) {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  function toggleAll() {
    if (selected.size === items.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(items.map(i => i.id)))
    }
  }

  function startEdit(item) {
    setEditingId(item.id)
    setMarginOpenId(null)
    setEditValues({
      product_name: item.product_name,
      case_cost: item.case_cost,
      units_per_case: item.units_per_case,
      retail_price: item.retail_price,
    })
  }

  async function saveEdit(itemId) {
    try {
      const data = await updateItem(invoiceId, itemId, editValues)
      setItems(prev => prev.map(i => i.id === itemId ? { ...data.item, warning: i.warning } : i))
      setEditingId(null)
    } catch (err) {
      alert(err.message)
    }
  }

  async function applyMarginPreset(item, marginValue) {
    setSavingMargin(item.id)
    try {
      const data = await updateItem(invoiceId, item.id, { margin_used: marginValue })
      setItems(prev => prev.map(i => i.id === item.id ? { ...data.item, warning: i.warning } : i))
      setMarginOpenId(null)
    } catch (err) {
      alert(err.message)
    } finally {
      setSavingMargin(null)
    }
  }

  async function handleConfirm() {
    await confirmInvoice(invoiceId)
    setInvoice(prev => ({ ...prev, status: 'confirmed' }))
  }

  async function handlePrint() {
    const ids = [...selected]
    if (!ids.length) return
    setPrinting(true)
    try {
      const blob = await generateLabels(ids)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
    } catch (err) {
      alert(err.message)
    } finally {
      setPrinting(false)
    }
  }

  async function handleDelete() {
    if (!window.confirm('Delete this invoice? This cannot be undone.')) return
    try {
      await deleteInvoice(invoiceId)
      navigate('/invoices')
    } catch (err) {
      alert(err.message)
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="loading-overlay">
          <div className="spinner" />
          <p>Loading invoice...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button
          className="btn btn-ghost btn-sm"
          style={{ padding: '6px 8px' }}
          onClick={() => navigate('/invoices')}
        >
          <ChevronLeft size={20} />
        </button>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>{invoice?.distributor}</h2>
          <p style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
            {invoice?.invoice_date || 'No date'} &middot; {items.length} items
          </p>
        </div>
        <span className={`badge ${invoice?.status === 'confirmed' ? 'badge-confirmed' : 'badge-pending'}`}>
          {invoice?.status === 'confirmed' ? 'Confirmed' : 'Review'}
        </span>
      </div>

      {/* Items */}
      <div className="card" style={{ marginBottom: 12, padding: '16px 14px' }}>
        <div className="check-row" style={{ marginBottom: 12 }}>
          <input
            type="checkbox"
            checked={selected.size === items.length}
            onChange={toggleAll}
          />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-secondary)' }}>
            {selected.size} of {items.length} selected for labels
          </span>
        </div>

        {items.map(item => {
          const unitCost = getUnitCost(item)
          const isMarginOpen = marginOpenId === item.id

          return (
          <div key={item.id}>
            {editingId === item.id ? (
              <div style={{ padding: '12px 0', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <input
                    className="form-input"
                    style={{ fontSize: 13, padding: '8px 10px' }}
                    value={editValues.product_name}
                    onChange={e => setEditValues(v => ({ ...v, product_name: e.target.value }))}
                    placeholder="Product name"
                  />
                </div>
                <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>Case cost</label>
                    <input className="form-input" style={{ fontSize: 13, padding: '8px 10px' }}
                      type="number" step="0.01" value={editValues.case_cost}
                      onChange={e => setEditValues(v => ({ ...v, case_cost: parseFloat(e.target.value) || 0 }))}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>Units/case</label>
                    <input className="form-input" style={{ fontSize: 13, padding: '8px 10px' }}
                      type="number" value={editValues.units_per_case}
                      onChange={e => setEditValues(v => ({ ...v, units_per_case: parseInt(e.target.value) || 1 }))}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>Retail $</label>
                    <input className="form-input" style={{ fontSize: 13, padding: '8px 10px' }}
                      type="number" step="0.01" value={editValues.retail_price}
                      onChange={e => setEditValues(v => ({ ...v, retail_price: parseFloat(e.target.value) || 0 }))}
                    />
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-primary btn-sm" onClick={() => saveEdit(item.id)}>
                    <Check size={14} /> Save
                  </button>
                  <button className="btn btn-secondary btn-sm" onClick={() => setEditingId(null)}>
                    <X size={14} /> Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                {/* Main item row */}
                <div className="item-card" style={{ borderBottom: isMarginOpen ? 'none' : undefined }}>
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={() => toggleSelect(item.id)}
                    style={{ width: 20, height: 20, accentColor: 'var(--color-primary)', flexShrink: 0 }}
                  />
                  <div className="item-info">
                    <div className="item-name">{item.product_name}</div>
                    <div className="item-meta">
                      Case: ${item.case_cost.toFixed(2)} &middot; {item.units_per_case} {item.retail_unit || 'units'} &middot; ${unitCost.toFixed(2)} cost ea.
                      {item.manually_edited && ' (edited)'}
                    </div>
                    {item.warning && (
                      <div style={{
                        fontSize: 11, color: '#F57F17', background: '#FFF8E1',
                        padding: '3px 8px', borderRadius: 6, marginTop: 4, display: 'inline-block',
                      }}>
                        {item.warning}
                      </div>
                    )}
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div className="item-retail">${item.retail_price.toFixed(2)}</div>
                    <div className="item-cost">per {item.retail_unit || 'unit'}</div>
                    <button
                      onClick={() => setMarginOpenId(isMarginOpen ? null : item.id)}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 3,
                        marginTop: 4, padding: '2px 8px', borderRadius: 100,
                        fontSize: 11, fontWeight: 600, cursor: 'pointer',
                        border: '1px solid var(--color-border-strong)',
                        background: isMarginOpen ? 'var(--color-primary)' : 'var(--color-surface)',
                        color: isMarginOpen ? 'white' : 'var(--color-text-secondary)',
                        fontFamily: 'var(--font)', transition: 'all 0.15s',
                      }}
                    >
                      <Tag size={10} />
                      {item.margin_used}%
                      <ChevronDown size={10} style={{
                        transform: isMarginOpen ? 'rotate(180deg)' : 'none',
                        transition: 'transform 0.15s'
                      }} />
                    </button>
                  </div>
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ padding: 6, width: 'auto' }}
                    onClick={() => startEdit(item)}
                  >
                    <Pencil size={16} />
                  </button>
                </div>

                {/* Expandable margin picker */}
                {isMarginOpen && (
                  <div style={{
                    padding: '8px 4px 14px',
                    borderBottom: '1px solid var(--color-border)',
                    animation: 'fadeUp 0.15s ease',
                  }}>
                    <div style={{
                      fontSize: 11, fontWeight: 600, color: 'var(--color-text-tertiary)',
                      textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 8, paddingLeft: 2,
                    }}>
                      Select pricing category
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      {MARGIN_PRESETS.filter(p => p.key !== 'custom').map(preset => {
                        const isActive = item.margin_used === preset.margin
                        const previewPrice = calcRetail(unitCost, preset.margin)
                        const profit = previewPrice - unitCost

                        return (
                          <button
                            key={preset.key}
                            onClick={() => applyMarginPreset(item, preset.margin)}
                            disabled={savingMargin === item.id}
                            style={{
                              display: 'flex', flexDirection: 'column',
                              padding: '10px 10px 8px', borderRadius: 10, cursor: 'pointer',
                              border: isActive ? `2px solid ${preset.color}` : '1px solid var(--color-border)',
                              background: isActive ? `${preset.color}10` : 'var(--color-surface)',
                              fontFamily: 'var(--font)', textAlign: 'left',
                              transition: 'all 0.1s', outline: 'none',
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'baseline' }}>
                              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)' }}>
                                {preset.label}
                              </span>
                              <span style={{ fontSize: 15, fontWeight: 700, color: preset.color }}>
                                ${previewPrice.toFixed(2)}
                              </span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', marginTop: 3 }}>
                              <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
                                Market: {preset.range}
                              </span>
                              <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
                                +${profit.toFixed(2)} profit
                              </span>
                            </div>
                            {/* Mini margin bar */}
                            <div style={{
                              width: '100%', height: 3, borderRadius: 2, marginTop: 6,
                              background: 'var(--color-border)',
                            }}>
                              <div style={{
                                width: `${Math.min(preset.margin, 60) / 60 * 100}%`,
                                height: '100%', borderRadius: 2,
                                background: preset.color,
                                opacity: isActive ? 1 : 0.5,
                                transition: 'width 0.2s',
                              }} />
                            </div>
                          </button>
                        )
                      })}
                    </div>

                    {/* Custom slider */}
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '10px 10px', borderRadius: 10, marginTop: 6,
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-surface)',
                    }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
                        Custom
                      </span>
                      <input
                        type="range" min="5" max="70" step="1"
                        value={customMargins[item.id] ?? item.margin_used}
                        onChange={e => setCustomMargins(prev => ({ ...prev, [item.id]: Number(e.target.value) }))}
                        style={{ flex: 1, accentColor: 'var(--color-primary)' }}
                      />
                      <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-primary)', minWidth: 38, textAlign: 'right' }}>
                        {customMargins[item.id] ?? item.margin_used}%
                      </span>
                      <span style={{ fontSize: 12, color: 'var(--color-text-secondary)', minWidth: 50, textAlign: 'right' }}>
                        ${calcRetail(unitCost, customMargins[item.id] ?? item.margin_used).toFixed(2)}
                      </span>
                      <button
                        onClick={() => applyMarginPreset(item, customMargins[item.id] ?? item.margin_used)}
                        disabled={savingMargin === item.id}
                        style={{
                          padding: '5px 12px', borderRadius: 6, border: 'none',
                          background: 'var(--color-primary)', color: 'white',
                          fontSize: 12, fontWeight: 600, cursor: 'pointer',
                          fontFamily: 'var(--font)', whiteSpace: 'nowrap',
                        }}
                      >
                        Apply
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          )
        })}
      </div>

      {/* Bottom actions */}
      <div style={{ display: 'flex', gap: 8 }}>
        {invoice?.status !== 'confirmed' && (
          <button className="btn btn-secondary" onClick={handleConfirm}>
            <Check size={18} /> Confirm
          </button>
        )}
        <button
          className="btn btn-primary"
          onClick={handlePrint}
          disabled={selected.size === 0 || printing}
        >
          <Printer size={18} />
          {printing ? 'Generating...' : `Print ${selected.size} labels`}
        </button>
      </div>
      <button
        className="btn btn-danger"
        onClick={handleDelete}
        style={{ marginTop: 8 }}
      >
        <Trash2 size={16} /> Delete invoice
      </button>
    </div>
  )
}
