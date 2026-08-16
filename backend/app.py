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
import anthropic
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

TASK: Look at ALL invoice page images provided. They may be separate pages of the same invoice, or different invoices entirely. Extract every line item across all pages. If pages overlap (show same items), deduplicate them.

=== STEP 1: IDENTIFY THE INVOICE FORMAT ===

Read the column headers carefully. Common distributor formats:

FORMAT A - "DET / Home Juice style" (Price, Deposit, Disc, Net Dlvd Price, Qty, Ext Cost):
- "Net Dlvd Price" = cost per case (AFTER discounts). USE THIS for case_cost.
- Do NOT use the "Price" column (that is BEFORE discounts).
- "Qty" = number of cases ordered. If Qty > 1, Ext Cost = Net Dlvd Price * Qty. Use Net Dlvd Price (per single case) as case_cost.
- Units per case are embedded in the description: "8/2L" = 8 bottles, "24/24oz" = 24 cans, "12/16oz" = 12 cans.
- The first number before the "/" is units per case.

FORMAT B - "Bakery style" (UPC, Description, Total Units, Net Price, Ext Amount):
- "Total Units" = total individual items ordered (the quantity).
- "Net Price" = cost per single item (e.g. $1.75 per pastry).
- "Ext Amount" = Total Units * Net Price = total cost for that line.
- case_cost = Ext Amount. units_per_case = Total Units. Each unit is one individual item.

FORMAT C - "Bimbo / bread distributor style" (UPC, Item No, Description, QTY, Sugg Retail, Retail Amount, Wholesale Price, Wholesale Amount):
- "QTY" = total number of retail units delivered. This is units_per_case.
- "Wholesale Price" = cost per single retail unit.
- "Wholesale Amount" = QTY * Wholesale Price = total cost. This is case_cost.
- IGNORE "Sugg Retail" and "Retail Amount" columns entirely.

PACK CODE DECODER (critical -- read this carefully):
- "SS2P" or "2P" = each retail unit is a 2-pack. retail_unit = "2-pack"
- "SS4P" or "4P" = each retail unit is a 4-pack. retail_unit = "4-pack"
- "FS6P" or "6P" = each retail unit is a 6-pack. retail_unit = "6-pack"
- "FS FC" or "FC" with NO pack number = individual full-size item. retail_unit = "each"
- "BX" = box. retail_unit = "box"

WORKED EXAMPLES from a real Bimbo invoice:
- "BIM CUERNITO SS2P FC" QTY=40, WholesalePrice=1.51, WholesaleAmt=60.40
  -> product="Bimbo Cuernito 2-pack", qty_cases=40, net_per_case=1.51, units_in_case=1, retail_unit="2-pack"
- "BIM ROLE CAN FS6P FC" QTY=8, WholesalePrice=3.02, WholesaleAmt=24.16
  -> product="Bimbo Roles Canela 6-pack", qty_cases=8, net_per_case=3.02, units_in_case=1, retail_unit="6-pack"
- "BIM CONCHAS SS2P FC" QTY=16, WholesalePrice=1.51, WholesaleAmt=24.16
  -> product="Bimbo Conchas 2-pack", qty_cases=16, net_per_case=1.51, units_in_case=1, retail_unit="2-pack"
- "BIM PANQUE NUE FS FC" QTY=2, WholesalePrice=2.41, WholesaleAmt=4.82
  -> product="Bimbo Panque Nuez Full Size", qty_cases=2, net_per_case=2.41, units_in_case=1, retail_unit="each"
- "MLA GANSITO SS2P BX" QTY=8, WholesalePrice=1.51, WholesaleAmt=12.08
  -> product="Marinela Gansito 2-pack Box", qty_cases=8, net_per_case=1.51, units_in_case=1, retail_unit="2-pack"
- "BIM HRSH MIN CROSS6P" QTY=12, WholesalePrice=1.51, WholesaleAmt=18.12
  -> product="Bimbo Hershey Mini Croissant 6-pack", qty_cases=12, net_per_case=1.51, units_in_case=1, retail_unit="6-pack"
- "MLA" prefix = Marinela brand. "BIM" prefix = Bimbo brand. "BAR TAK" = Barcel Takis.
- CROSS-CHECK: For every line, verify that Wholesale Amount / Wholesale Price = QTY. If your QTY reading doesn't match this math, trust the math. Example: if amount=60.40 and price=1.51, then QTY must be 40 (60.40/1.51=40), not 8.

FORMAT D - Other/Unknown:
- Find the column that represents the TOTAL COST for each line (usually rightmost dollar column, often labeled "Ext", "Amount", "Total", or "Ext Cost").
- Find the per-unit or per-case cost column if separate.
- If there is a quantity/cases column, and amount = price * qty, then case_cost = amount / qty for one case.

FORMAT E - "Coca-Cola / Pepsi / major beverage distributor style" (DESCRIPTION, MAT#, QTY, PRICE, CON#, RATE, NET, EXTENDED):

CRITICAL: This format has TWO types of lines. You MUST tell them apart or you will get WRONG numbers.

TYPE 1 - CATEGORY HEADER (DO NOT OUTPUT AS AN ITEM):
These are SHORT lines that name a product category. They look like:
  "SPARKLIN 160Z 1-Ls 24"
  "           6/144                    177.96"
  "ENERGY D 160Z 1-Ls 24"
  "           8/192                    398.64"
HOW TO RECOGNIZE: No MAT# (6-digit number), no QTY/PRICE/RATE/NET columns. Just a product type, size, pack info, a fraction like "X/Y", and a dollar subtotal on the right.
- "1-Ls 12" = each case has 12 loose items. "1-Ls 24" = 24 loose items per case.
- "15-Pk 30" = retail unit is 15-pack, 30 cans per case = 2 fifteen-packs per case.
- "X/Y" (e.g. "6/144") = total cases / total units across all flavors below.
- The dollar amount (177.96) is a SUBTOTAL for the entire category. SKIP IT. NEVER use it as a case_cost.

TYPE 2 - PRODUCT LINE (OUTPUT EACH ONE AS AN ITEM):
These are LONG lines with many columns of numbers. They look like:
  "16ZCAN24LS SPRITE    144089  1  34.25 ZDCS  -4.59  29.66    29.66"
  "049000053432         24"
HOW TO RECOGNIZE: Has a 6-digit MAT# (like 144089, 145278, 133115), followed by QTY, PRICE, contract code (ZDCS), RATE, NET, EXTENDED. The next line has a UPC and unit count.

EVERY product line is a SEPARATE item. The category header above it just tells you what type of product it is and how many units per case.

COLUMN RULES FOR PRODUCT LINES:
- QTY = number of cases ordered (1, 2, 3, etc.)
- PRICE = cost per case BEFORE discount (ignore this)
- RATE = discount amount (negative number)
- NET = cost per case AFTER discount. This is the real cost per case.
- EXTENDED = QTY * NET = total cost for this flavor.
- case_cost = EXTENDED
- units_per_case = QTY * (units per case from the category header above)
  Example: category says "1-Ls 24", product line has QTY=2. units_per_case = 2 * 24 = 48.
- If category says "15-Pk 30": each case has 30/15=2 fifteen-packs. QTY=3 means 3*2=6 fifteen-packs. retail_unit="15-pack".
- If category says "1-Ls": retail_unit = "single can" or "single bottle" (CAN vs PET in description).

CROSS-CHECK: EXTENDED must equal QTY * NET. If EXTENDED seems too large (like 177.96 when QTY=1 and NET=29.66), you grabbed the category subtotal by mistake. Go back and find the real EXTENDED for that product line.

DESCRIPTION CODE DECODER for product names:
- Product line codes: "VW" = Vitaminwater, "DT" = Diet, "ZRO" = Zero Sugar, "SGR" = Sugar
- "PET" = plastic bottle, "CAN" = aluminum can, "BIB" = bag-in-box syrup
- "SPARKLIN" category = sodas and carbonated drinks (Coke, Sprite, Dr Pepper, Fanta)
- "ENERGY D" category = Monster, Reign, Bang, NOS
- "ENHNCD W" category = Vitaminwater, Smartwater
- "ADVANCED" category = Bodyarmor
- "DAIRY BE" category = Fairlife, Core Power
- "JUICE DR" category = Minute Maid, Simply, Hi-C
- Do NOT call Coca-Cola products "Pepsi"
- Read the actual flavor/brand name from the product line, not just the category header

WORKED EXAMPLES:
- Category header: "ENHNCD W 200Z 1-Ls 12   3/36   66.69"  <-- 66.69 is SUBTOTAL, skip it
  Product line 1: "20PETI2LS VW XXX  156089  1  26.20 ZDCS  -3.97  22.23  22.23"
  -> product="Vitaminwater XXX 20oz", qty_cases=1, net_per_case=22.23, units_in_case=12, retail_unit="single bottle"
  Product line 2: "20ZPET12LS VW PWR C  156030  1  26.20 ZDCS  -3.97  22.23  22.23"
  -> product="Vitaminwater Power-C 20oz", qty_cases=1, net_per_case=22.23, units_in_case=12, retail_unit="single bottle"

- Category header: "SPARKLIN 160Z 1-Ls 24   6/144   177.96"  <-- SKIP 177.96
  Product line: "16ZCAN24LS SPRITE  144089  1  34.25 ZDCS  -4.59  29.66  29.66"
  -> product="Sprite 16oz", qty_cases=1, net_per_case=29.66, units_in_case=24, retail_unit="single can"

- Category header: "SPARKLIN 120Z 15-Pk 30   10/20   169.80"  <-- SKIP 169.80
  Product line: "12ZCAN15PX2 COKE  133115  3  18.19 ZDCS  -1.21  16.98  50.94"
  -> product="Coca-Cola 12oz 15-Pack", qty_cases=3, net_per_case=16.98, units_in_case=2, retail_unit="15-pack"
  (units_in_case=2 because each case has 30 cans / 15 per pack = 2 fifteen-packs per case)

=== STEP 2: DETERMINE RETAIL UNITS ===

For each line, figure out what a customer picks up at the register:
- Pack codes: "6P"/"6PK" = 6-pack, "12P"/"12PK" = 12-pack, "4PK" = 4-pack, "SS2P"/"2P" = 2-pack
- If "24/24oz PET" the first number (24) is units per case, each is a single 24oz bottle
- If no pack code, the unit is usually a single item (can, bottle, bag, bar, pastry, loaf)
- "LSE"/"LOOSE" = individual items
- Bakery items (bread, cake, muffins, croissants, conchas) are typically sold individually

=== STEP 3: SANITY CHECK YOUR NUMBERS ===

BEFORE outputting, verify each line:
- unit_cost = case_cost / units_per_case
- A single drink (can/bottle) should cost the store $0.30 to $3.00. If you get $15+ for a single can, your units_per_case is wrong.
- A single pastry/bread item should cost $1.00 to $4.00.
- A 6-pack should cost $4 to $10. A 12-pack $8 to $18.
- If case_cost is very high (e.g. $60) and you have units_per_case=1, that is almost certainly wrong.

=== STEP 4: OUTPUT ===

For each item return:
- product: CLEAN human-readable name. Expand abbreviations. Include size.
  Good: "Faygo Grape 2L", "Blueberry Cream Cheese Danish", "Bimbo Cuernito 2-pack"
  Bad: "FAY Grape 8/2L", "BLUEBERRY CREAM", "BIM CUERNITO SS2P FC"
- qty_cases: number of cases/units ordered on this line (the QTY column). For most invoices this is 1. For Coca-Cola style, read the QTY column directly from the product line.
- net_per_case: cost per single case AFTER discounts. For DET style = Net Dlvd Price. For Coca-Cola style = NET column. For bakery = Net Price. For Bimbo = Wholesale Price. If there is no discount, this equals the unit price.
- units_in_case: how many sellable retail units are in ONE case (not total across all cases). For DET: the first number in the description (e.g. "24/24oz" = 24). For Coca-Cola: from category header (e.g. "1-Ls 24" = 24). For bakery/Bimbo: this equals 1 if qty_cases represents individual items.
- retail_unit: what one unit is ("each", "single can", "single bottle", "2-pack", "6-pack", "loaf", etc.)
- upc: UPC/barcode if visible (empty string if not)

IMPORTANT: Do NOT calculate case_cost yourself. Just give me qty_cases, net_per_case, and units_in_case and I will calculate the totals. This avoids accidentally using category subtotals.

Header info:
- distributor: vendor/distributor name from the invoice header
- invoice_date: in YYYY-MM-DD format (null if not visible)
- total: invoice grand total if visible (null if not)

Return ONLY valid JSON, no markdown fences, no explanation:
{
  "distributor": "...",
  "invoice_date": "YYYY-MM-DD or null",
  "total": 0.00,
  "items": [
    {"product": "...", "qty_cases": 1, "net_per_case": 0.00, "units_in_case": 1, "retail_unit": "each", "upc": ""}
  ]
}"""


def enhance_invoice_image(image_bytes: bytes) -> bytes:
    """Sharpen, boost contrast, and auto-orient an invoice photo.
    Optimized for OCR accuracy on small dot-matrix receipt text.
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

    # Resize -- 2048 gives better accuracy on small text (worth the extra tokens)
    max_dim = 2048
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Convert to grayscale -- removes color noise, makes text pop for OCR
    img = img.convert("L")

    # UnsharpMask is much better than basic SHARPEN for making small text crisp
    # radius=2: targets fine text detail, percent=150: strong sharpening,
    # threshold=3: only sharpens edges (not noise)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))

    # High contrast to separate text from background
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.6)

    # Slight brightness bump for dark photos
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.1)

    # Convert back to RGB for JPEG encoding
    img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _parse_single_image(client, image_bytes: bytes) -> dict:
    """Parse a single invoice page image with Claude."""
    enhanced = enhance_invoice_image(image_bytes)
    b64 = base64.b64encode(enhanced).decode("utf-8")

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64,
            },
        },
        {"type": "text", "text": INVOICE_PARSE_PROMPT},
    ]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)


def parse_invoice_images(image_bytes_list: list) -> dict:
    """Parse invoice images. Uses per-page processing with parallel threads
    for better accuracy on dense invoices (each page gets full AI attention).
    Results are merged and deduplicated.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if len(image_bytes_list) == 1:
        # Single page: simple direct call
        try:
            return _parse_single_image(client, image_bytes_list[0])
        except (json.JSONDecodeError, KeyError):
            raise ValueError(
                "Could not read this invoice clearly. "
                "Try taking another photo with better lighting and hold steady."
            )

    # Multiple pages: process in parallel for speed + accuracy
    results = [None] * len(image_bytes_list)
    errors = []

    def process_page(idx, img_bytes):
        return idx, _parse_single_image(client, img_bytes)

    with ThreadPoolExecutor(max_workers=min(len(image_bytes_list), 4)) as executor:
        futures = {
            executor.submit(process_page, i, img): i
            for i, img in enumerate(image_bytes_list)
        }
        for future in as_completed(futures):
            try:
                idx, parsed = future.result()
                results[idx] = parsed
            except Exception as e:
                errors.append(str(e))

    if all(r is None for r in results):
        raise ValueError(
            "Could not read this invoice clearly. "
            "Try taking another photo with better lighting and hold steady."
        )

    # Merge results from all pages
    distributor = "Unknown"
    invoice_date = None
    total = None
    all_items = []

    for parsed in results:
        if parsed is None:
            continue
        if parsed.get("distributor") and distributor == "Unknown":
            distributor = parsed["distributor"]
        if parsed.get("invoice_date") and not invoice_date:
            invoice_date = parsed["invoice_date"]
        if parsed.get("total"):
            # Take the largest total (likely the real invoice total)
            page_total = float(parsed["total"])
            if total is None or page_total > total:
                total = page_total
        all_items.extend(parsed.get("items", []))

    # Deduplicate by product name (overlapping pages)
    seen = {}
    unique_items = []
    for item in all_items:
        name_key = item.get("product", "").strip().lower()
        upc_key = item.get("upc", "").strip()
        dedup_key = f"{name_key}|{upc_key}" if upc_key else name_key
        if dedup_key not in seen:
            seen[dedup_key] = True
            unique_items.append(item)

    return {
        "distributor": distributor,
        "invoice_date": invoice_date,
        "total": total,
        "items": unique_items,
    }


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

    # Read all images and save originals
    image_bytes_list = []
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
        image_bytes_list.append(image_bytes)

    # Send ALL images to GPT-4o in a single call (much faster than per-image)
    try:
        parsed = parse_invoice_images(image_bytes_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    distributor = parsed.get("distributor", "Unknown") or "Unknown"
    invoice_date_str = parsed.get("invoice_date")
    invoice_total = float(parsed.get("total") or 0)
    all_items = parsed.get("items", [])

    # Deduplicate items by product name + UPC (same item from overlapping photos)
    seen = {}
    unique_items = []
    for item in all_items:
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
        # Calculate case_cost from components (avoids category subtotal errors)
        # New format: qty_cases, net_per_case, units_in_case
        # Fallback: case_cost, units_per_case (old format)
        qty_cases = int(item.get("qty_cases", 1)) or 1
        net_per_case = item.get("net_per_case")
        units_in_case = int(item.get("units_in_case", 1)) or 1

        if net_per_case is not None:
            # New format: calculate case_cost ourselves
            net_per_case = float(net_per_case)
            case_cost = round(qty_cases * net_per_case, 2)
            units = qty_cases * units_in_case
        else:
            # Fallback to old format
            case_cost = float(item.get("case_cost", 0))
            units = int(item.get("units_per_case", 1)) or 1

        unit_cost = round(case_cost / units, 4) if units > 0 else 0
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