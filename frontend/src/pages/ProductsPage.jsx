import React, { useState, useEffect } from 'react'
import { Package, TrendingUp, ChevronDown, ChevronUp } from 'lucide-react'
import { listProducts, getProductHistory } from '../services/api'

export default function ProductsPage() {
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState(null)
  const [history, setHistory] = useState({})

  useEffect(() => {
    listProducts()
      .then(data => setProducts(data.products))
      .finally(() => setLoading(false))
  }, [])

  async function toggleHistory(productId) {
    if (expandedId === productId) {
      setExpandedId(null)
      return
    }
    setExpandedId(productId)
    if (!history[productId]) {
      try {
        const data = await getProductHistory(productId)
        setHistory(prev => ({ ...prev, [productId]: data.history }))
      } catch {
        setHistory(prev => ({ ...prev, [productId]: [] }))
      }
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="loading-overlay"><div className="spinner" /></div>
      </div>
    )
  }

  return (
    <div className="page">
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Product catalog</h2>
      <p style={{ fontSize: 14, color: 'var(--color-text-secondary)', marginBottom: 16 }}>
        {products.length} products tracked
      </p>

      {products.length === 0 ? (
        <div className="empty-state">
          <Package />
          <h3>No products yet</h3>
          <p>Products are added automatically when you scan invoices</p>
        </div>
      ) : (
        <div className="card" style={{ padding: '4px 16px' }}>
          {products.map(product => (
            <div key={product.id}>
              <div
                className="item-card"
                style={{ cursor: 'pointer' }}
                onClick={() => toggleHistory(product.id)}
              >
                <div className="item-info">
                  <div className="item-name">{product.name}</div>
                  <div className="item-meta">
                    {product.upc && `UPC: ${product.upc} \u00B7 `}
                    {product.category}
                  </div>
                </div>
                <div className="item-price">
                  <div className="item-retail">${product.current_retail_price.toFixed(2)}</div>
                </div>
                {expandedId === product.id ? (
                  <ChevronUp size={18} color="var(--color-text-tertiary)" />
                ) : (
                  <ChevronDown size={18} color="var(--color-text-tertiary)" />
                )}
              </div>

              {expandedId === product.id && (
                <div style={{
                  padding: '8px 0 16px',
                  borderBottom: '1px solid var(--color-border)',
                }}>
                  <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <TrendingUp size={14} /> Price history
                  </div>
                  {!history[product.id] ? (
                    <div className="spinner" style={{ width: 20, height: 20, borderWidth: 2 }} />
                  ) : history[product.id].length === 0 ? (
                    <p style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>No history available</p>
                  ) : (
                    <div style={{ fontSize: 13 }}>
                      {history[product.id].map((h, i) => (
                        <div key={i} style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          padding: '6px 0',
                          borderBottom: i < history[product.id].length - 1 ? '1px solid var(--color-border)' : 'none',
                        }}>
                          <span style={{ color: 'var(--color-text-secondary)' }}>
                            {new Date(h.recorded_at).toLocaleDateString()}
                          </span>
                          <span>
                            Case: ${h.case_cost.toFixed(2)} &middot; Unit: ${h.unit_cost.toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
