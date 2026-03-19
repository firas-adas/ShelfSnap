import os
import json
import base64
import io
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from werkzeug.utils import secure_filename
from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from PIL import Image, ImageEnhance, ImageFilter, ExifTags

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist", "assets"),
    static_url_path="/assets",
)

# Fix Render's postgres:// URL to postgresql:// for SQLAlchemy
db_url = os.getenv("DATABASE_URL", "sqlite:///shelfsnap.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET", "change-me-in-production")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload
app.config["UPLOAD_FOLDER"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "uploads"
)

CORS(app, origins=["http://localhost:5173", "http://localhost:3000"])
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ---------------------------------------------------------------------------
# Database models
# ---------------------------------------------------------------------------

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    store_name = db.Column(db.String(255), default="")
    default_margin = db.Column(db.Float, default=30.0)  # percent
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    invoices = db.relationship("Invoice", backref="owner", lazy=True)
    products = db.relationship("Product", backref="owner", lazy=True)


class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    distributor = db.Column(db.String(255), default="Unknown")
    invoice_date = db.Column(db.Date, nullable=True)
    total_amount = db.Column(db.Float, default=0.0)
    image_path = db.Column(db.String(500), default="")
    status = db.Column(db.String(50), default="pending_review")
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    items = db.relationship(
        "InvoiceItem", backref="invoice", lazy=True,
        cascade="all, delete-orphan"
    )


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id"), nullable=False
    )
    product_name = db.Column(db.String(255), nullable=False)
    upc = db.Column(db.String(50), default="")
    case_cost = db.Column(db.Float, nullable=False)
    units_per_case = db.Column(db.Integer, default=1)
    unit_cost = db.Column(db.Float, nullable=False)
    retail_price = db.Column(db.Float, nullable=False)
    margin_used = db.Column(db.Float, nullable=False)
    manually_edited = db.Column(db.Boolean, default=False)
    retail_unit = db.Column(db.String(50), default="each")


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    upc = db.Column(db.String(50), default="")
    current_retail_price = db.Column(db.Float, default=0.0)
    category = db.Column(db.String(100), default="General")


class PriceHistory(db.Model):
    __tablename__ = "price_history"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id"), nullable=False
    )
    invoice_item_id = db.Column(
        db.Integer, db.ForeignKey("invoice_items.id"), nullable=True
    )
    case_cost = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    product = db.relationship("Product", backref="price_history")


# ---------------------------------------------------------------------------
# AI service: GPT-4 Vision invoice parsing
# ---------------------------------------------------------------------------

INVOICE_PARSE_PROMPT = """You are an expert invoice parser for wholesale distributors that supply gas stations and convenience stores. You can read ANY invoice format from ANY distributor.

YOUR TASK: Analyze this invoice image, figure out its structure, and extract every line item with correct retail unit counts.

STEP 1 - UNDERSTAND THE INVOICE LAYOUT:
- First, identify the column headers. Different distributors use different column names and layouts.
- Find the columns for: item description, quantity ordered, cost/price, total amount, and UPC if present.
- The "total" or "amount" or "ext price" column (usually the rightmost dollar column) is the total cost for that line.

STEP 2 - FIGURE OUT RETAIL UNITS PER LINE:
This is the most important step. For each line item, determine: "If a store owner buys this case, how many individual items does he put on the shelf to sell, and what IS each item?"

Think about it like this:
- A "case" from the distributor contains multiple retail units.
- A retail unit is what a customer picks up and brings to the register.
- Sometimes the retail unit is a single item (one can of soda, one bag of chips, one candy bar).
- Sometimes the retail unit is a multi-pack (a 6-pack of beer, a 12-pack of soda, a 3-pack of lighters).

CLUES TO LOOK FOR in descriptions:
- Numbers like "24", "18", "12" often indicate total individual items in the case.
- Suffixes like "6P", "6PK", "12P", "12PK", "4PK" indicate multi-pack retail units.
- If a case has 24 items and they are sold as 6-packs, that is 24/6 = 4 retail units.
- If a case has 18 items and no pack suffix, that is 18 individual retail units.
- "LSE" or "LOOSE" = individual/loose items.
- Letters like "C" or "B" before a number often mean cans or bottles (C24 = 24 cans, B12 = 12 bottles).
- Words like "SINGLE", "EA", "EACH" = individual items.
- If the invoice has a "Units" or "Qty" column separate from "Cases", that may indicate items per case.
- Some invoices list a unit price AND a case price. Use the total/extended price for case_cost.
- If "Cases" or "Qty Ordered" is greater than 1, the AMOUNT is for ALL cases combined. Divide by the number of cases to get cost per single case.

When in doubt about units_per_case, look at the total cost and think about whether the implied per-unit price makes sense for a convenience store. A single can of beer should cost $1-4, a 6-pack $6-12, a 12-pack $10-20. If your math gives $47 for a single can, something is wrong.

STEP 3 - BUILD CLEAN OUTPUT:
For each line item return:
- product: a CLEAN human-readable name. Translate any codes into plain English.
  Good: "Coors Light 12oz (18 singles)", "Corona Extra 12oz 6-pack", "Doritos Nacho 1oz"
  Bad: "COORS LIGHT C18 12OZ", "CORONA EXTRA B24 12OZ 6P"
- case_cost: total cost for that line from the invoice
- units_per_case: number of retail sellable units in the case
- retail_unit: what one sellable unit is (e.g. "single can", "single bottle", "6-pack", "12-pack", "bag", "each")
- upc: the UPC/barcode if visible (empty string if not)

Also extract from the invoice header:
- distributor: the distributor/vendor name
- invoice_date: date in YYYY-MM-DD format if visible (null if not)
- total: invoice total if visible (null if not)

Return ONLY valid JSON. No markdown fences, no explanation, no commentary:
{
  "distributor": "...",
  "invoice_date": "YYYY-MM-DD or null",
  "total": 0.00,
  "items": [
    {"product": "...", "case_cost": 0.00, "units_per_case": 1, "retail_unit": "each", "upc": ""}
  ]
}"""


def enhance_invoice_image(image_bytes: bytes) -> bytes:
    """Sharpen, boost contrast, and auto-orient an invoice photo.
    This is similar to what apps like Fetch do to handle shaky photos.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Auto-orient based on EXIF data (phone rotation)
    try:
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == "Orientation":
                break
        exif = img._getexif()
        if exif and orientation in exif:
            val = exif[orientation]
            if val == 3:
                img = img.rotate(180, expand=True)
            elif val == 6:
                img = img.rotate(270, expand=True)
            elif val == 8:
                img = img.rotate(90, expand=True)
    except (AttributeError, KeyError, TypeError):
        pass

    # Resize if too large (keeps API costs down, speeds up processing)
    max_dim = 2048
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Sharpen to reduce blur from shaky hands
    img = img.filter(ImageFilter.SHARPEN)
    img = img.filter(ImageFilter.SHARPEN)

    # Boost contrast so faded text pops
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.4)

    # Slight brightness bump for dark photos
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.1)

    # Convert to RGB if needed (handles RGBA/palette images)
    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def parse_invoice_image(image_bytes: bytes) -> dict:
    """Enhance the image, send to GPT-4 Vision, and get structured items."""
    # Enhance before sending to AI
    enhanced = enhance_invoice_image(image_bytes)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    b64 = base64.b64encode(enhanced).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": INVOICE_PARSE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=4096,
        temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if the model wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(
            "Could not read this invoice clearly. "
            "Try taking another photo with better lighting and hold steady."
        )


def calculate_retail_price(unit_cost: float, margin_pct: float) -> float:
    """Calculate retail price from unit cost and desired margin %.
    margin_pct = 30 means the store wants 30% gross margin.
    retail = unit_cost / (1 - margin/100)
    """
    if margin_pct >= 100:
        margin_pct = 50.0
    return round(unit_cost / (1 - margin_pct / 100), 2)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    store_name = data.get("store_name", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    user = User(
        email=email,
        password_hash=bcrypt.generate_password_hash(password).decode("utf-8"),
        store_name=store_name,
    )
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": _user_dict(user)}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": _user_dict(user)})


@app.route("/api/auth/me", methods=["GET"])
@jwt_required()
def get_me():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": _user_dict(user)})


@app.route("/api/auth/settings", methods=["PUT"])
@jwt_required()
def update_settings():
    user = User.query.get(int(get_jwt_identity()))
    data = request.get_json()
    if "default_margin" in data:
        user.default_margin = float(data["default_margin"])
    if "store_name" in data:
        user.store_name = data["store_name"]
    db.session.commit()
    return jsonify({"user": _user_dict(user)})


def _user_dict(user):
    return {
        "id": user.id,
        "email": user.email,
        "store_name": user.store_name,
        "default_margin": user.default_margin,
    }


# ---------------------------------------------------------------------------
# Invoice routes
# ---------------------------------------------------------------------------

@app.route("/api/invoices/scan", methods=["POST"])
@jwt_required()
def scan_invoice():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    # Accept multiple images: "images" (multi-file) or single "image"
    files = request.files.getlist("images")
    if not files:
        single = request.files.get("image")
        if single:
            files = [single]
    if not files:
        return jsonify({"error": "No image files provided"}), 400

    # Parse each photo and merge results
    all_items = []
    distributor = "Unknown"
    invoice_date_str = None
    invoice_total = 0.0
    saved_filenames = []

    for idx, file in enumerate(files):
        image_bytes = file.read()

        # Save original
        filename = secure_filename(
            f"{user_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{idx}.jpg"
        )
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        saved_filenames.append(filename)

        try:
            parsed = parse_invoice_image(image_bytes)
        except Exception as e:
            return jsonify({
                "error": f"Could not read page {idx + 1}: {str(e)}"
            }), 500

        # Take distributor and date from whichever page has them
        if parsed.get("distributor") and distributor == "Unknown":
            distributor = parsed["distributor"]
        if parsed.get("invoice_date") and not invoice_date_str:
            invoice_date_str = parsed["invoice_date"]
        if parsed.get("total"):
            invoice_total = max(invoice_total, float(parsed["total"]))

        all_items.extend(parsed.get("items", []))

    # Deduplicate items by product name + UPC (same item from overlapping photos)
    seen = {}
    unique_items = []
    for item in all_items:
        # Build a dedup key from product name (normalized) and UPC
        name_key = item.get("product", "").strip().lower()
        upc_key = item.get("upc", "").strip()
        dedup_key = f"{name_key}|{upc_key}" if upc_key else name_key

        if dedup_key not in seen:
            seen[dedup_key] = True
            unique_items.append(item)

    margin = float(request.form.get("margin", user.default_margin))

    # Parse the invoice date
    inv_date = None
    if invoice_date_str:
        try:
            inv_date = datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            inv_date = None

    # Check for duplicate invoice (same distributor + same date for this user)
    if inv_date:
        existing = Invoice.query.filter_by(
            user_id=user_id,
            distributor=distributor,
            invoice_date=inv_date,
        ).first()
        if existing:
            return jsonify({
                "error": f"An invoice from {distributor} dated {inv_date.isoformat()} already exists.",
                "existing_id": existing.id,
            }), 409

    # Create invoice record
    invoice = Invoice(
        user_id=user_id,
        distributor=distributor,
        invoice_date=inv_date,
        total_amount=invoice_total,
        image_path=",".join(saved_filenames),
        status="pending_review",
    )
    db.session.add(invoice)
    db.session.flush()

    # Create line items
    items_out = []
    for item in unique_items:
        case_cost = float(item.get("case_cost", 0))
        units = int(item.get("units_per_case", 1)) or 1
        unit_cost = round(case_cost / units, 4)
        retail = calculate_retail_price(unit_cost, margin)

        inv_item = InvoiceItem(
            invoice_id=invoice.id,
            product_name=item.get("product", "Unknown"),
            upc=item.get("upc", ""),
            case_cost=case_cost,
            units_per_case=units,
            unit_cost=unit_cost,
            retail_price=retail,
            margin_used=margin,
            retail_unit=item.get("retail_unit", "each"),
        )
        db.session.add(inv_item)
        db.session.flush()

        _update_product_catalog(user_id, inv_item)

        item_out = _item_dict(inv_item)
        if unit_cost > 30 and item.get("retail_unit", "each") in (
            "each", "single can", "single bottle", "bag",
        ):
            item_out["warning"] = "Price seems high for a single item. Check units per case."
        items_out.append(item_out)

    db.session.commit()

    return jsonify({
        "invoice": _invoice_dict(invoice),
        "items": items_out,
    }), 201


@app.route("/api/invoices", methods=["GET"])
@jwt_required()
def list_invoices():
    user_id = int(get_jwt_identity())
    invoices = (
        Invoice.query
        .filter_by(user_id=user_id)
        .order_by(Invoice.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({
        "invoices": [_invoice_dict(inv) for inv in invoices]
    })


@app.route("/api/invoices/<int:invoice_id>", methods=["GET"])
@jwt_required()
def get_invoice(invoice_id):
    user_id = int(get_jwt_identity())
    invoice = Invoice.query.filter_by(
        id=invoice_id, user_id=user_id
    ).first_or_404()
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    return jsonify({
        "invoice": _invoice_dict(invoice),
        "items": [_item_dict(i) for i in items],
    })


@app.route("/api/invoices/<int:invoice_id>/items/<int:item_id>", methods=["PUT"])
@jwt_required()
def update_item(invoice_id, item_id):
    user_id = int(get_jwt_identity())
    Invoice.query.filter_by(id=invoice_id, user_id=user_id).first_or_404()
    item = InvoiceItem.query.filter_by(
        id=item_id, invoice_id=invoice_id
    ).first_or_404()

    data = request.get_json()
    if "product_name" in data:
        item.product_name = data["product_name"]
    if "case_cost" in data:
        item.case_cost = float(data["case_cost"])
        item.unit_cost = round(item.case_cost / item.units_per_case, 4)
    if "units_per_case" in data:
        item.units_per_case = int(data["units_per_case"])
        item.unit_cost = round(item.case_cost / item.units_per_case, 4)
    if "retail_price" in data:
        item.retail_price = float(data["retail_price"])
    if "margin_used" in data:
        item.margin_used = float(data["margin_used"])
        item.retail_price = calculate_retail_price(
            item.unit_cost, item.margin_used
        )
    item.manually_edited = True

    db.session.commit()
    return jsonify({"item": _item_dict(item)})


@app.route("/api/invoices/<int:invoice_id>/confirm", methods=["POST"])
@jwt_required()
def confirm_invoice(invoice_id):
    user_id = int(get_jwt_identity())
    invoice = Invoice.query.filter_by(
        id=invoice_id, user_id=user_id
    ).first_or_404()
    invoice.status = "confirmed"
    db.session.commit()
    return jsonify({"invoice": _invoice_dict(invoice)})


@app.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
@jwt_required()
def delete_invoice(invoice_id):
    user_id = int(get_jwt_identity())
    invoice = Invoice.query.filter_by(
        id=invoice_id, user_id=user_id
    ).first_or_404()
    db.session.delete(invoice)
    db.session.commit()
    return jsonify({"message": "Invoice deleted"})


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------

@app.route("/api/labels/generate", methods=["POST"])
@jwt_required()
def generate_labels():
    data = request.get_json()
    item_ids = data.get("item_ids", [])

    if not item_ids:
        return jsonify({"error": "No items selected"}), 400

    items = InvoiceItem.query.filter(InvoiceItem.id.in_(item_ids)).all()
    if not items:
        return jsonify({"error": "No items found"}), 404

    # Generate PDF with price labels
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)
    page_w, page_h = letter

    # Label grid: 3 columns x 10 rows (Avery 5160 style)
    label_w = 2.625 * inch
    label_h = 1.0 * inch
    margin_left = 0.1875 * inch
    margin_top = 0.5 * inch
    cols = 3
    rows = 10
    gutter_x = 0.125 * inch

    for idx, item in enumerate(items):
        page_idx = idx // (cols * rows)
        pos = idx % (cols * rows)

        if pos == 0 and idx > 0:
            c.showPage()

        col = pos % cols
        row = pos // cols

        x = margin_left + col * (label_w + gutter_x)
        y = page_h - margin_top - (row + 1) * label_h

        # Label border (light)
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.5)
        c.rect(x, y, label_w, label_h)

        # Product name (truncated)
        c.setFillColorRGB(0.15, 0.15, 0.15)
        c.setFont("Helvetica", 8)
        name = item.product_name[:35]
        c.drawString(x + 6, y + label_h - 16, name)

        # Retail price (large)
        c.setFont("Helvetica-Bold", 22)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(x + 6, y + 18, f"${item.retail_price:.2f}")

        # Retail unit label (e.g. "per 6-pack")
        retail_unit = getattr(item, 'retail_unit', '') or 'each'
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(x + 6, y + 8, f"per {retail_unit}")

        # Unit cost (small, bottom right)
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawRightString(
            x + label_w - 6, y + 6,
            f"Cost: ${item.unit_cost:.2f}"
        )

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="shelf_labels.pdf",
    )


# ---------------------------------------------------------------------------
# Price history / product catalog
# ---------------------------------------------------------------------------

@app.route("/api/products", methods=["GET"])
@jwt_required()
def list_products():
    user_id = int(get_jwt_identity())
    products = Product.query.filter_by(user_id=user_id).order_by(
        Product.name
    ).all()
    return jsonify({
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "upc": p.upc,
                "current_retail_price": p.current_retail_price,
                "category": p.category,
            }
            for p in products
        ]
    })


@app.route("/api/products/<int:product_id>/history", methods=["GET"])
@jwt_required()
def product_price_history(product_id):
    user_id = int(get_jwt_identity())
    product = Product.query.filter_by(
        id=product_id, user_id=user_id
    ).first_or_404()
    history = (
        PriceHistory.query
        .filter_by(product_id=product.id)
        .order_by(PriceHistory.recorded_at.desc())
        .limit(100)
        .all()
    )
    return jsonify({
        "product": product.name,
        "history": [
            {
                "case_cost": h.case_cost,
                "unit_cost": h.unit_cost,
                "recorded_at": h.recorded_at.isoformat(),
            }
            for h in history
        ],
    })


def _update_product_catalog(user_id, inv_item):
    """Find or create a product entry and log price history."""
    product = None
    if inv_item.upc:
        product = Product.query.filter_by(
            user_id=user_id, upc=inv_item.upc
        ).first()
    if not product:
        product = Product.query.filter_by(
            user_id=user_id, name=inv_item.product_name
        ).first()
    if not product:
        product = Product(
            user_id=user_id,
            name=inv_item.product_name,
            upc=inv_item.upc or "",
            current_retail_price=inv_item.retail_price,
        )
        db.session.add(product)
        db.session.flush()
    else:
        product.current_retail_price = inv_item.retail_price

    history = PriceHistory(
        product_id=product.id,
        invoice_item_id=inv_item.id,
        case_cost=inv_item.case_cost,
        unit_cost=inv_item.unit_cost,
    )

    # Deduplicate: skip if the most recent price history entry for this
    # product has the same unit cost (prevents false alerts from rescans)
    latest = (
        PriceHistory.query
        .filter_by(product_id=product.id)
        .order_by(PriceHistory.recorded_at.desc())
        .first()
    )
    if latest and abs(latest.unit_cost - inv_item.unit_cost) < 0.01:
        return  # Same price, skip duplicate entry

    db.session.add(history)


# ---------------------------------------------------------------------------
# Dashboard & analytics
# ---------------------------------------------------------------------------

@app.route("/api/dashboard", methods=["GET"])
@jwt_required()
def dashboard():
    user_id = int(get_jwt_identity())

    total_invoices = Invoice.query.filter_by(user_id=user_id).count()

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    invoices_this_month = Invoice.query.filter(
        Invoice.user_id == user_id,
        Invoice.created_at >= month_start,
    ).count()

    total_products = Product.query.filter_by(user_id=user_id).count()

    total_items_priced = (
        db.session.query(InvoiceItem)
        .join(Invoice)
        .filter(Invoice.user_id == user_id)
        .count()
    )

    confirmed_items = (
        db.session.query(InvoiceItem)
        .join(Invoice)
        .filter(Invoice.user_id == user_id, Invoice.status == "confirmed")
        .all()
    )
    total_cost = sum(i.case_cost for i in confirmed_items)
    total_retail = sum(i.retail_price * i.units_per_case for i in confirmed_items)
    total_profit = total_retail - total_cost

    latest = (
        Invoice.query
        .filter_by(user_id=user_id)
        .order_by(Invoice.created_at.desc())
        .first()
    )

    return jsonify({
        "stats": {
            "total_invoices": total_invoices,
            "invoices_this_month": invoices_this_month,
            "total_products": total_products,
            "total_items_priced": total_items_priced,
            "total_cost": round(total_cost, 2),
            "total_retail": round(total_retail, 2),
            "total_profit": round(total_profit, 2),
        },
        "latest_invoice": _invoice_dict(latest) if latest else None,
    })


@app.route("/api/dashboard/price-alerts", methods=["GET"])
@jwt_required()
def price_alerts():
    user_id = int(get_jwt_identity())
    products = Product.query.filter_by(user_id=user_id).all()

    alerts = []
    for product in products:
        history = (
            PriceHistory.query
            .filter_by(product_id=product.id)
            .order_by(PriceHistory.recorded_at.desc())
            .limit(2)
            .all()
        )
        if len(history) < 2:
            continue

        newest = history[0]
        previous = history[1]

        if newest.unit_cost > previous.unit_cost:
            increase = newest.unit_cost - previous.unit_cost
            pct = (increase / previous.unit_cost) * 100 if previous.unit_cost else 0
            # Only flag if increase is more than 2% (ignore rounding noise)
            if pct < 2.0:
                continue
            alerts.append({
                "product_id": product.id,
                "product_name": product.name,
                "old_cost": round(previous.unit_cost, 4),
                "new_cost": round(newest.unit_cost, 4),
                "increase": round(increase, 4),
                "percent_change": round(pct, 1),
                "recorded_at": newest.recorded_at.isoformat(),
            })

    alerts.sort(key=lambda a: a["percent_change"], reverse=True)
    return jsonify({"alerts": alerts})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoice_dict(inv):
    return {
        "id": inv.id,
        "distributor": inv.distributor,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "total_amount": inv.total_amount,
        "status": inv.status,
        "item_count": len(inv.items),
        "created_at": inv.created_at.isoformat(),
    }


def _item_dict(item):
    return {
        "id": item.id,
        "product_name": item.product_name,
        "upc": item.upc,
        "case_cost": item.case_cost,
        "units_per_case": item.units_per_case,
        "unit_cost": item.unit_cost,
        "retail_price": item.retail_price,
        "margin_used": item.margin_used,
        "manually_edited": item.manually_edited,
        "retail_unit": item.retail_unit or "each",
    }


# ---------------------------------------------------------------------------
# Serve React frontend in production
# ---------------------------------------------------------------------------

FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist"
)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve React app. API routes are registered first so they take priority."""
    # If requesting a file that exists in dist/, serve it
    full_path = os.path.join(FRONTEND_DIST, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIST, path)
    # Otherwise serve index.html (React Router handles client-side routing)
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(FRONTEND_DIST, "index.html")
    return jsonify({"error": "Frontend not built. Run: cd frontend && npm run build"}), 404


# ---------------------------------------------------------------------------
# Init DB and run
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
