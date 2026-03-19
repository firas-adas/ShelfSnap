import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { FileText, ChevronRight } from 'lucide-react'
import { listInvoices } from '../services/api'

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listInvoices()
      .then(data => setInvoices(data.invoices))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page">
        <div className="loading-overlay"><div className="spinner" /></div>
      </div>
    )
  }

  return (
    <div className="page">
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>Invoice history</h2>

      {invoices.length === 0 ? (
        <div className="empty-state">
          <FileText />
          <h3>No invoices yet</h3>
          <p>Scan your first wholesale invoice to get started</p>
        </div>
      ) : (
        invoices.map(inv => (
          <Link key={inv.id} to={`/review/${inv.id}`} className="invoice-row">
            <div className="inv-icon">
              <FileText size={20} />
            </div>
            <div className="inv-info">
              <div className="inv-name">{inv.distributor}</div>
              <div className="inv-date">
                {inv.invoice_date || 'No date'} &middot; {inv.item_count} items &middot;{' '}
                <span className={`badge ${inv.status === 'confirmed' ? 'badge-confirmed' : 'badge-pending'}`}>
                  {inv.status === 'confirmed' ? 'Confirmed' : 'Review'}
                </span>
              </div>
            </div>
            {inv.total_amount > 0 && (
              <div className="inv-amount">${inv.total_amount.toFixed(2)}</div>
            )}
            <ChevronRight size={18} color="var(--color-text-tertiary)" />
          </Link>
        ))
      )}
    </div>
  )
}
