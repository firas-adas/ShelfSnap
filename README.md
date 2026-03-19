# ShelfSnap

Scan wholesale invoices with AI, calculate retail prices at your margin, and print shelf labels. Built for gas station and convenience store owners.

## Tech stack

- **Backend:** Python, Flask, SQLAlchemy, PostgreSQL (SQLite for dev)
- **Frontend:** React, Vite, React Router, Lucide Icons
- **AI:** OpenAI GPT-4o Vision for invoice OCR and structured extraction
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
# Edit .env and add your OpenAI API key

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
| `OPENAI_API_KEY` | Your OpenAI API key (needs GPT-4o access) |
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
2. Image is sent to GPT-4o Vision with a structured extraction prompt
3. AI returns product names, case costs, and units per case as JSON
4. Backend calculates unit cost and retail price at the owner's margin %
5. Owner reviews, edits any mistakes, selects items
6. Backend generates a PDF of Avery 5160 shelf labels
7. Products and prices are cataloged for cost tracking over time

## Deployment

For production, swap SQLite for PostgreSQL via the `DATABASE_URL` env var. Deploy the Flask backend on Render/Railway/Fly.io with gunicorn. Build the React frontend with `npm run build` and serve the `dist/` folder from the same server or a CDN.

## Monetization

Target pricing: $5-10/month or a one-time fee. Free tier could allow 3 scans/month. Paid tier gets unlimited scans, label templates, and price alerts when distributor costs change.
