const API_BASE = '/api'

function getToken() {
  return localStorage.getItem('shelfsnap_token')
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function handleResponse(res) {
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || 'Request failed')
  return data
}

// Auth
export async function register(email, password, storeName) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, store_name: storeName }),
  })
  return handleResponse(res)
}

export async function login(email, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return handleResponse(res)
}

export async function getMe() {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}

export async function updateSettings(settings) {
  const res = await fetch(`${API_BASE}/auth/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(settings),
  })
  return handleResponse(res)
}

// Invoices
export async function scanInvoice(imageFiles, margin) {
  const form = new FormData()
  // Accept single file or array of files
  const files = Array.isArray(imageFiles) ? imageFiles : [imageFiles]
  files.forEach(f => form.append('images', f))
  if (margin) form.append('margin', margin.toString())

  const res = await fetch(`${API_BASE}/invoices/scan`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  })
  return handleResponse(res)
}

export async function listInvoices() {
  const res = await fetch(`${API_BASE}/invoices`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}

export async function getInvoice(id) {
  const res = await fetch(`${API_BASE}/invoices/${id}`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}

export async function updateItem(invoiceId, itemId, updates) {
  const res = await fetch(`${API_BASE}/invoices/${invoiceId}/items/${itemId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(updates),
  })
  return handleResponse(res)
}

export async function confirmInvoice(id) {
  const res = await fetch(`${API_BASE}/invoices/${id}/confirm`, {
    method: 'POST',
    headers: authHeaders(),
  })
  return handleResponse(res)
}

export async function deleteInvoice(id) {
  const res = await fetch(`${API_BASE}/invoices/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  return handleResponse(res)
}

// Labels
export async function generateLabels(itemIds) {
  const res = await fetch(`${API_BASE}/labels/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ item_ids: itemIds }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.error || 'Label generation failed')
  }
  return res.blob()
}

// Products
export async function listProducts() {
  const res = await fetch(`${API_BASE}/products`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}

export async function getProductHistory(productId) {
  const res = await fetch(`${API_BASE}/products/${productId}/history`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}

// Dashboard
export async function getDashboard() {
  const res = await fetch(`${API_BASE}/dashboard`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}

export async function getPriceAlerts() {
  const res = await fetch(`${API_BASE}/dashboard/price-alerts`, {
    headers: authHeaders(),
  })
  return handleResponse(res)
}
