import React, { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  Camera, TrendingUp, AlertTriangle,
  FileText, Package, ArrowRight, DollarSign, BarChart3
} from 'lucide-react'
import { useAuth } from '../App'
import { getDashboard, getPriceAlerts } from '../services/api'

export default function DashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [latestInvoice, setLatestInvoice] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([getDashboard(), getPriceAlerts()])
      .then(([dashData, alertData]) => {
        setStats(dashData.stats)
        setLatestInvoice(dashData.latest_invoice)
        setAlerts(alertData.alerts)
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page">
        <div className="loading-overlay"><div className="spinner" /></div>
      </div>
    )
  }

  const hasData = stats && stats.total_invoices > 0

  return (
    <div className="page">
      {/* Greeting */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700 }}>
          {getGreeting()}{user?.store_name ? `, ${user.store_name}` : ''}
        </h2>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: 14, marginTop: 2 }}>
          {hasData ? "Here's your store snapshot" : 'Scan your first invoice to get started'}
        </p>
      </div>

      {/* Scan CTA */}
      <button
        onClick={() => navigate('/scan')}
        style={{
          width: '100%', padding: '18px 20px', borderRadius: 'var(--radius-lg)',
          border: 'none', background: 'var(--color-primary)', color: 'white',
          display: 'flex', alignItems: 'center', gap: 14, cursor: 'pointer',
          fontFamily: 'var(--font)', marginBottom: 16, transition: 'background 0.15s',
        }}
      >
        <div style={{
          width: 44, height: 44, borderRadius: 12, background: 'rgba(255,255,255,0.2)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Camera size={22} />
        </div>
        <div style={{ textAlign: 'left', flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Scan new invoice</div>
          <div style={{ fontSize: 12, opacity: 0.85, marginTop: 1 }}>
            Take a photo or upload from your gallery
          </div>
        </div>
        <ArrowRight size={20} />
      </button>

      {/* First-time empty state */}
      {!hasData && (
        <div style={{
          padding: '32px 20px', borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--color-border)', background: 'var(--color-surface)',
          textAlign: 'center', marginBottom: 16,
        }}>
          <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.3 }}>
            <FileText size={48} />
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>No invoices yet</h3>
          <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            Snap a photo of any wholesale invoice from your distributor.
            ShelfSnap will read every product, calculate what to charge at your margin,
            and generate shelf labels you can print.
          </p>
          <div style={{
            display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16,
            fontSize: 13, textAlign: 'left', maxWidth: 280, margin: '16px auto 0',
          }}>
            {[
              { step: '1', text: 'Take a photo of your wholesale invoice' },
              { step: '2', text: 'AI reads every product and case cost' },
              { step: '3', text: 'Pick your margin per category' },
              { step: '4', text: 'Print shelf labels instantly' },
            ].map(s => (
              <div key={s.step} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 24, height: 24, borderRadius: '50%',
                  background: 'var(--color-primary)', color: 'white',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 12, fontWeight: 700, flexShrink: 0,
                }}>{s.step}</div>
                <span style={{ color: 'var(--color-text-secondary)' }}>{s.text}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stats (only show with data) */}
      {hasData && (
        <>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16,
          }}>
            <StatCard
              icon={<FileText size={16} />}
              label="Invoices scanned"
              value={stats.total_invoices}
              sub={`${stats.invoices_this_month} this month`}
              color="#E8621A"
            />
            <StatCard
              icon={<Package size={16} />}
              label="Products tracked"
              value={stats.total_products}
              sub={`${stats.total_items_priced} items priced`}
              color="#1976D2"
            />
            <StatCard
              icon={<DollarSign size={16} />}
              label="Total wholesale cost"
              value={`$${stats.total_cost.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
              sub="confirmed invoices"
              color="#5D4037"
            />
            <StatCard
              icon={<BarChart3 size={16} />}
              label="Estimated profit"
              value={`$${stats.total_profit.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
              sub={stats.total_cost > 0 ? `${((stats.total_profit / stats.total_cost) * 100).toFixed(0)}% avg margin` : 'from retail pricing'}
              color="#1B8C5A"
            />
          </div>

          {/* Price alerts */}
          <div style={{ marginBottom: 16 }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10
            }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
                <AlertTriangle size={16} color="#F57F17" />
                Price alerts
              </h3>
              {alerts.length > 0 && (
                <span style={{
                  fontSize: 11, fontWeight: 600, background: '#FFF8E1', color: '#F57F17',
                  padding: '2px 10px', borderRadius: 100,
                }}>
                  {alerts.length} increase{alerts.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>

            {alerts.length === 0 ? (
              <div style={{
                padding: '16px', borderRadius: 'var(--radius-md)',
                border: '1px solid var(--color-border)', background: 'var(--color-surface)',
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
                  padding: '10px 12px', borderRadius: 8, background: '#FFF8E1',
                }}>
                  <TrendingUp size={18} color="#F57F17" />
                  <div style={{ fontSize: 13, color: '#5D4037' }}>
                    <span style={{ fontWeight: 600 }}>How this works:</span> Scan the same products
                    across multiple invoices and we'll automatically detect when your distributor
                    raises prices.
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', textAlign: 'center' }}>
                  Keep scanning invoices and alerts will appear here
                </div>
              </div>
            ) : (
              <div style={{
                borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)',
                background: 'var(--color-surface)', overflow: 'hidden',
              }}>
                {alerts.slice(0, 5).map((alert, i) => (
                  <div key={alert.product_id} style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '12px 14px',
                    borderBottom: i < Math.min(alerts.length, 5) - 1 ? '1px solid var(--color-border)' : 'none',
                  }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: 8,
                      background: '#FFF0EF', display: 'flex', alignItems: 'center',
                      justifyContent: 'center', flexShrink: 0,
                    }}>
                      <TrendingUp size={16} color="#D93025" />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 13, fontWeight: 600,
                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      }}>
                        {alert.product_name}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
                        ${alert.old_cost.toFixed(2)} &rarr; ${alert.new_cost.toFixed(2)} per unit
                      </div>
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#D93025', flexShrink: 0 }}>
                      +{alert.percent_change}%
                    </div>
                  </div>
                ))}
                {alerts.length > 5 && (
                  <Link to="/products" style={{
                    display: 'block', textAlign: 'center', padding: '10px',
                    fontSize: 13, color: 'var(--color-primary)', fontWeight: 600,
                    textDecoration: 'none',
                  }}>
                    View all {alerts.length} alerts
                  </Link>
                )}
              </div>
            )}
          </div>

          {/* Latest invoice */}
          {latestInvoice && (
            <div style={{ marginBottom: 16 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Latest invoice</h3>
              <Link to={`/review/${latestInvoice.id}`} className="invoice-row">
                <div className="inv-icon"><FileText size={20} /></div>
                <div className="inv-info">
                  <div className="inv-name">{latestInvoice.distributor}</div>
                  <div className="inv-date">
                    {latestInvoice.invoice_date || 'No date'} &middot; {latestInvoice.item_count} items
                  </div>
                </div>
                {latestInvoice.total_amount > 0 && (
                  <div className="inv-amount">${latestInvoice.total_amount.toFixed(2)}</div>
                )}
                <ArrowRight size={16} color="var(--color-text-tertiary)" />
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function StatCard({ icon, label, value, sub, color }) {
  return (
    <div style={{
      padding: '14px 14px 12px', borderRadius: 'var(--radius-md)',
      border: '1px solid var(--color-border)', background: 'var(--color-surface)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        marginBottom: 8, color: color, opacity: 0.8,
      }}>
        {icon}
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.3px' }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>{sub}</div>
    </div>
  )
}

function getGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}
