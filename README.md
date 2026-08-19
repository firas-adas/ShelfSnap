# ShelfSnap

Scan wholesale invoices with AI, calculate retail prices at your margin, and print shelf labels. Built for gas station and convenience store owners — in real use by multiple independent store owners today.

## Tech stack

- **Backend:** Python, Flask, SQLAlchemy, PostgreSQL (SQLite for dev)
- **Frontend:** React, Vite, React Router, Lucide Icons
- **AI:** Claude (claude-sonnet-4) for invoice OCR and structured extraction, with distributor-specific prompt formatting and parallel per-page processing
- **Labels:** ReportLab PDF generation (Avery 5160 format)

## Quick start

### 1. Backend

```bash
cd backend
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your Anthropic API key

# Run the server
python app.py
```

Backend runs at `http://localhost:5000`

### 2. Frontend

```bash
cd frontend
# Install dependencies
npm install

# Run dev server
npm run dev
```

Frontend runs at `http://localhost:5173` with API proxy to backend.

### 3. Environment variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (Claude access) |
| `JWT_SECRET` | Random secret for JWT tokens |
| `DATABASE_URL` | Database connection string (defaults to SQLite) |

## Project structure

```
shelfsnap/
  backend/
    app.py              # Flask app (models, routes, AI, labels)
    requirements.txt
    .env.example
    uploads/            # Stored invoice images
  frontend/
    src/
      App.jsx           # Router, auth context, app shell
      index.css         # Design system
      services/
        api.js          # API client
      pages/
        AuthPage.jsx    # Login / register
        ScanPage.jsx    # Camera upload + margin slider
        ReviewPage.jsx  # Edit parsed items + print labels
        InvoicesPage.jsx # Invoice history
        ProductsPage.jsx # Product catalog + price history
        SettingsPage.jsx # Store settings
```

## API endpoints

### Auth
- `POST /api/auth/register` - Create account
- `POST /api/auth/login` - Sign in
- `GET /api/auth/me` - Get current user
- `PUT /api/auth/settings` - Update margin/store name

### Invoices
- `POST /api/invoices/scan` - Upload + AI parse + price
- `GET /api/invoices` - List all invoices
- `GET /api/invoices/:id` - Get invoice with items
- `PUT /api/invoices/:id/items/:itemId` - Edit a line item
- `POST /api/invoices/:id/confirm` - Mark as confirmed

### Labels
- `POST /api/labels/generate` - Generate PDF label sheet

### Products
- `GET /api/products` - List product catalog
- `GET /api/products/:id/history` - Price history for a product

## Database schema

Five tables: `users`, `invoices`, `invoice_items`, `products`, `price_history`. The product catalog and price history build automatically as you scan invoices. See `app.py` for full schema.

## How it works

1. Owner snaps a photo of their wholesale invoice
2. Pages are processed in parallel and sent to Claude with a distributor-specific extraction prompt (Coca-Cola, Bimbo, Home Juice, Bon Appetit, and others each have their own prompt formatting to handle differences in invoice layout)
3. AI returns structured line items as JSON (`qty_cases`, `net_per_case`, `units_in_case`)
4. Backend calculates unit cost and retail price at the owner's margin %
5. Owner reviews, edits any mistakes, selects items
6. Backend generates a PDF of Avery 5160 shelf labels
7. Products and prices are cataloged for cost tracking over time

## Known limitations

- Coca-Cola invoices occasionally bleed category subtotals into line-item extraction — being actively worked on
- Item matching across distributors is currently manual; no cross-distributor SKU crosswalk yet

## Deployment

For production, swap SQLite for PostgreSQL via the `DATABASE_URL` env var. Deploy the Flask backend on Render/Railway/Fly.io with gunicorn. Build the React frontend with `npm run build` and serve the `dist/` folder from the same server or a CDN.

## Roadmap

Currently building out the data layer: landing raw invoice extractions before parsing, modeling cost history over time, and reconciling invoices against distributor order data (starting with H.T. Hackney) to catch cost increases and billing errors automatically.

## Monetization

Target pricing: $5-10/month or a one-time fee. Free tier could allow 3 scans/month. Paid tier gets unlimited scans, label templates, and price alerts when distributor costs change.
