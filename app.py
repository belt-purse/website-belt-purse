from collections import defaultdict
from flask_login import login_required, current_user
import cloudinary
import cloudinary.uploader
from flask import Flask, flash, render_template, request, jsonify, session, redirect, abort, url_for, make_response
from sqlalchemy import exists, text,inspect
from sqlalchemy.orm import joinedload
from models import Address, Blog, Cart, Category, Color, Coupon, CouponUsage, EmailHistory, EmailTrack, HomepageMedia, Order, OrderItem, PasswordResetToken, ProductColor, ProductSize, Review, Tag, Warranty, db, User, Product, ProductImage, ProductVideo, ProductTag, PaymentMethod, WalletTransaction, Ticket
from flask_login import LoginManager, login_user
from functools import wraps
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
from datetime import date, datetime
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from flask_migrate import Migrate

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path=".env"):
        if not os.path.exists(path):
            return False

        with open(path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)

        return True

try:
    import resend
except ImportError:
    resend = None

try:
    import razorpay
except ImportError:
    razorpay = None


load_dotenv(DOTENV_PATH)

from config import Config

app = Flask(__name__)
app.config.from_object(Config)

print("Razorpay Key ID loaded:", "yes" if app.config.get("RAZORPAY_KEY_ID") else "no")
print("Razorpay Secret loaded:", "yes" if app.config.get("RAZORPAY_KEY_SECRET") else "no")
key_id = app.config.get("RAZORPAY_KEY_ID", "")
key_secret = app.config.get("RAZORPAY_KEY_SECRET", "")

print("Razorpay Key Prefix:", key_id[:8] if key_id else "missing")
print("Razorpay Secret Length:", len(key_secret) if key_secret else 0)
# ✅ Cloudinary config (KEEP)
cloudinary.config(
    cloud_name=app.config["CLOUDINARY_CLOUD_NAME"],
    api_key=app.config["CLOUDINARY_API_KEY"],
    api_secret=app.config["CLOUDINARY_API_SECRET"]
)

# ✅ DB init (KEEP)
db.init_app(app)

# ✅ Login Manager (KEEP)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ✅ Mail (KEEP - but env vars required)
mail = Mail(app)

# ✅ Migrations (IMPORTANT for Railway)
migrate = Migrate(app, db)

# ❌ REMOVE LOCAL STORAGE (Railway pe useless)
# UPLOAD_FOLDER = app.config["UPLOAD_FOLDER"]
# IMAGE_UPLOAD_FOLDER = os.path.join(app.root_path, "static/images")
# VIDEO_UPLOAD_FOLDER = os.path.join(app.root_path, "static/videos")
# os.makedirs(...)

# ❌ REMOVE THESE (DANGEROUS IN PRODUCTION)
# def ensure_column(...)
# def ensure_variant_columns(...)

# ❌ REMOVE THIS BLOCK COMPLETELY
# with app.app_context():
#     db.create_all()
#     ensure_variant_columns()

# ✅ OPTIONAL DEBUG PRINT (SAFE)
def describe_database_url(url):
    if url.drivername.startswith("sqlite"):
        return f"type=sqlite database={url.database or ':memory:'}"

    host = url.host or "unknown"
    database = url.database or "unknown"
    port = f":{url.port}" if url.port else ""
    return f"type={url.drivername} host={host}{port} database={database}"

def table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def ensure_column_exists(table_name, column_name, column_sql, fallback_column_sql=None):
    inspector = inspect(db.engine)

    if not table_exists(inspector, table_name):
        print(f"SAFE DB MIGRATION: skipped {table_name}.{column_name}; table does not exist")
        return

    dialect_name = db.engine.dialect.name
    fallback_column_sql = fallback_column_sql or column_sql

    if dialect_name == "postgresql":
        with db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_sql}"))
        print(f"SAFE DB MIGRATION: ensured {table_name}.{column_name}")
        return

    existing_columns = [col["name"] for col in inspector.get_columns(table_name)]
    if column_name in existing_columns:
        print(f"SAFE DB MIGRATION: {table_name}.{column_name} already exists")
        return

    with db.engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {fallback_column_sql}"))
    print(f"SAFE DB MIGRATION: added {table_name}.{column_name}")


def ensure_live_db_columns():
    print("SAFE DB MIGRATION: checking required columns")
    # ✅ Warranty page fix
    ensure_column_exists("warranty", "order_id", "order_id INTEGER")
    ensure_column_exists("warranty", "product_name", "product_name VARCHAR(255)")
    ensure_column_exists("warranty", "purchase_date", "purchase_date DATE")
    ensure_column_exists("warranty", "message", "message TEXT")

    # ✅ Product archive fix
    ensure_column_exists("products", "is_archived", "is_archived BOOLEAN DEFAULT FALSE")
    ensure_column_exists("products", "product_type", "product_type VARCHAR(50) DEFAULT 'belt'")
    ensure_column_exists("products", "requires_size", "requires_size BOOLEAN DEFAULT TRUE")
    ensure_column_exists("products", "size_type", "size_type VARCHAR(30) DEFAULT 'specific'")
    ensure_column_exists("products", "composition_care", "composition_care TEXT")
    ensure_column_exists("products", "additional_details", "additional_details TEXT")
    ensure_column_exists("products", "show_on_homepage", "show_on_homepage BOOLEAN DEFAULT FALSE")
    ensure_column_exists("products", "homepage_sort_order", "homepage_sort_order INTEGER DEFAULT 0")
    ensure_column_exists("colors", "hex_code", "hex_code VARCHAR(20)")
    ensure_column_exists("blog", "blog_date", "blog_date DATE")
    ensure_column_exists("orders", "coupon_code", "coupon_code VARCHAR(50)")
    ensure_column_exists("orders", "applied_coupon_code", "applied_coupon_code VARCHAR(50)")
    ensure_column_exists("orders", "discount_amount", "discount_amount DOUBLE PRECISION", "discount_amount FLOAT")
    ensure_column_exists("orders", "coupon_discount_amount", "coupon_discount_amount DOUBLE PRECISION DEFAULT 0", "coupon_discount_amount FLOAT DEFAULT 0")
    ensure_column_exists("orders", "subtotal_amount", "subtotal_amount DOUBLE PRECISION", "subtotal_amount FLOAT")
    ensure_column_exists("orders", "final_amount", "final_amount DOUBLE PRECISION", "final_amount FLOAT")
    ensure_column_exists("coupons", "discount_type", "discount_type VARCHAR(20) DEFAULT 'fixed'")
    ensure_column_exists("coupons", "discount_value", "discount_value DOUBLE PRECISION DEFAULT 0", "discount_value FLOAT DEFAULT 0")
    ensure_column_exists("coupons", "description", "description TEXT")
    ensure_column_exists("coupons", "coupon_type", "coupon_type VARCHAR(50) DEFAULT 'fixed_amount'")
    ensure_column_exists("coupons", "min_order_amount", "min_order_amount DOUBLE PRECISION", "min_order_amount FLOAT")
    ensure_column_exists("coupons", "max_discount_amount", "max_discount_amount DOUBLE PRECISION", "max_discount_amount FLOAT")
    ensure_column_exists("coupons", "applicable_category_id", "applicable_category_id INTEGER")
    ensure_column_exists("coupons", "applicable_category", "applicable_category VARCHAR(50) DEFAULT 'all'")
    ensure_column_exists("coupons", "min_quantity_required", "min_quantity_required INTEGER")
    ensure_column_exists("coupons", "required_product_price", "required_product_price DOUBLE PRECISION", "required_product_price FLOAT")
    ensure_column_exists("coupons", "final_payable_amount", "final_payable_amount DOUBLE PRECISION", "final_payable_amount FLOAT")
    ensure_column_exists("coupons", "valid_from", "valid_from DATE")
    ensure_column_exists("coupons", "valid_until", "valid_until DATE")
    ensure_column_exists("coupons", "usage_limit", "usage_limit INTEGER")
    ensure_column_exists("coupons", "used_count", "used_count INTEGER DEFAULT 0")
    ensure_column_exists("coupons", "per_user_limit", "per_user_limit INTEGER DEFAULT 1")
    ensure_column_exists("coupons", "one_time_per_customer", "one_time_per_customer BOOLEAN DEFAULT TRUE")
    ensure_column_exists("coupons", "auto_apply", "auto_apply BOOLEAN DEFAULT FALSE")
    ensure_column_exists("coupons", "allow_combination", "allow_combination BOOLEAN DEFAULT FALSE")
    ensure_column_exists("coupons", "show_on_product_page", "show_on_product_page BOOLEAN DEFAULT FALSE")
    ensure_column_exists("coupons", "product_page_priority", "product_page_priority INTEGER DEFAULT 0")
    ensure_column_exists("coupons", "updated_at", "updated_at TIMESTAMP WITHOUT TIME ZONE", "updated_at DATETIME")
    ensure_column_exists("homepage_media", "media_type", "media_type VARCHAR(30)")
    ensure_column_exists("homepage_media", "title", "title VARCHAR(255)")
    ensure_column_exists("homepage_media", "subtitle", "subtitle VARCHAR(500)")
    ensure_column_exists("homepage_media", "button_text", "button_text VARCHAR(100)")
    ensure_column_exists("homepage_media", "button_link", "button_link VARCHAR(500)")
    ensure_column_exists("homepage_media", "media_url", "media_url VARCHAR(500)")
    ensure_column_exists("homepage_media", "mobile_media_url", "mobile_media_url VARCHAR(500)")
    ensure_column_exists("homepage_media", "public_id", "public_id VARCHAR(255)")
    ensure_column_exists("homepage_media", "mobile_public_id", "mobile_public_id VARCHAR(255)")
    ensure_column_exists("homepage_media", "alt_text", "alt_text VARCHAR(255)")
    ensure_column_exists("homepage_media", "sort_order", "sort_order INTEGER DEFAULT 0")
    ensure_column_exists("homepage_media", "is_active", "is_active BOOLEAN DEFAULT TRUE")
    ensure_column_exists("homepage_media", "created_at", "created_at TIMESTAMP WITHOUT TIME ZONE", "created_at DATETIME")
    ensure_column_exists("homepage_media", "updated_at", "updated_at TIMESTAMP WITHOUT TIME ZONE", "updated_at DATETIME")
    ensure_column_exists(
        "tickets",
        "updated_at",
        "updated_at TIMESTAMP WITHOUT TIME ZONE",
        "updated_at DATETIME"
    )

    inspector = inspect(db.engine)

    if table_exists(inspector, "products"):
        with db.engine.begin() as conn:
            result = conn.execute(text("""
                UPDATE products
                SET product_type = 'belt'
                WHERE product_type IS NULL OR product_type = ''
            """))
            print(f"SAFE DB MIGRATION: backfilled products.product_type rows={result.rowcount}")
            result = conn.execute(text("""
                UPDATE products
                SET requires_size = TRUE
                WHERE requires_size IS NULL
            """))
            print(f"SAFE DB MIGRATION: backfilled products.requires_size rows={result.rowcount}")
            result = conn.execute(text("""
                UPDATE products
                SET size_type = 'specific'
                WHERE size_type IS NULL OR size_type = ''
            """))
            print(f"SAFE DB MIGRATION: backfilled products.size_type rows={result.rowcount}")
            result = conn.execute(text("""
                UPDATE products
                SET show_on_homepage = FALSE
                WHERE show_on_homepage IS NULL
            """))
            print(f"SAFE DB MIGRATION: backfilled products.show_on_homepage rows={result.rowcount}")
            result = conn.execute(text("""
                UPDATE products
                SET homepage_sort_order = 0
                WHERE homepage_sort_order IS NULL
            """))
            print(f"SAFE DB MIGRATION: backfilled products.homepage_sort_order rows={result.rowcount}")
    else:
        print("SAFE DB MIGRATION: skipped products backfill; table does not exist")

    if table_exists(inspector, "colors"):
        with db.engine.begin() as conn:
            result = conn.execute(text("""
                UPDATE colors
                SET hex_code = code
                WHERE (hex_code IS NULL OR hex_code = '')
                  AND code IS NOT NULL
                  AND code != ''
            """))
            print(f"SAFE DB MIGRATION: backfilled colors.hex_code rows={result.rowcount}")
            result = conn.execute(text("""
                UPDATE colors
                SET code = hex_code
                WHERE (code IS NULL OR code = '')
                  AND hex_code IS NOT NULL
                  AND hex_code != ''
            """))
            print(f"SAFE DB MIGRATION: backfilled colors.code rows={result.rowcount}")
    else:
        print("SAFE DB MIGRATION: skipped colors backfill; table does not exist")

    if table_exists(inspector, "tickets"):
        ticket_columns = [col["name"] for col in inspect(db.engine).get_columns("tickets")]
        if "updated_at" in ticket_columns:
            with db.engine.begin() as conn:
                if "created_at" in ticket_columns:
                    result = conn.execute(text("""
                        UPDATE tickets
                        SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
                        WHERE updated_at IS NULL
                    """))
                else:
                    result = conn.execute(text("""
                        UPDATE tickets
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE updated_at IS NULL
                    """))
                print(f"SAFE DB MIGRATION: backfilled tickets.updated_at rows={result.rowcount}")
    else:
        print("SAFE DB MIGRATION: skipped tickets backfill; table does not exist")

    print("SAFE DB MIGRATION: completed")


def ensure_default_coupons():
    default_coupons = [
        {
            "code": "WELCOME100",
            "title": "Welcome Rs.100 OFF",
            "description": "First order discount for new customers.",
            "coupon_type": "first_order_discount",
            "discount_type": "fixed",
            "discount_value": 100,
            "min_order_amount": None,
            "max_discount_amount": None,
            "applicable_category": "all",
            "min_quantity_required": None,
            "required_product_price": None,
            "final_payable_amount": None,
            "first_order_only": True,
            "one_time_per_customer": True,
            "usage_limit": None,
            "per_user_limit": 1,
            "auto_apply": False,
            "allow_combination": False,
            "show_on_product_page": True,
            "product_page_priority": 100,
        },
        {
            "code": "BUY2SAVE",
            "title": "Buy 2 Belts Pay Rs.799",
            "description": "Buy any two Rs.599 belts in one order and pay Rs.799 for those two belts.",
            "coupon_type": "buy_x_fixed_payable",
            "discount_type": "fixed",
            "discount_value": 0,
            "min_order_amount": None,
            "max_discount_amount": None,
            "applicable_category": "belt",
            "min_quantity_required": 2,
            "required_product_price": 599,
            "final_payable_amount": 799,
            "first_order_only": False,
            "one_time_per_customer": False,
            "usage_limit": None,
            "per_user_limit": 0,
            "auto_apply": False,
            "allow_combination": False,
            "show_on_product_page": True,
            "product_page_priority": 90,
        },
        {
            "code": "FIRST30",
            "title": "Rs.30 OFF First Order",
            "description": "Legacy first order coupon.",
            "coupon_type": "first_order_discount",
            "discount_type": "fixed",
            "discount_value": 30,
            "min_order_amount": None,
            "max_discount_amount": None,
            "applicable_category": "all",
            "min_quantity_required": None,
            "required_product_price": None,
            "final_payable_amount": None,
            "first_order_only": True,
            "one_time_per_customer": True,
            "usage_limit": None,
            "per_user_limit": 1,
            "auto_apply": False,
            "allow_combination": False,
            "show_on_product_page": True,
            "product_page_priority": 80,
        },
    ]

    for coupon_data in default_coupons:
        coupon = Coupon.query.filter_by(code=coupon_data["code"]).first()
        if not coupon:
            coupon = Coupon(code=coupon_data["code"])
            db.session.add(coupon)
            coupon.title = coupon_data["title"]
            coupon.description = coupon_data["description"]
            coupon.coupon_type = coupon_data["coupon_type"]
            coupon.discount_type = coupon_data["discount_type"]
            coupon.discount_value = coupon_data["discount_value"]
            coupon.min_order_amount = coupon_data["min_order_amount"]
            coupon.max_discount_amount = coupon_data["max_discount_amount"]
            coupon.applicable_category = coupon_data["applicable_category"]
            coupon.min_quantity_required = coupon_data["min_quantity_required"]
            coupon.required_product_price = coupon_data["required_product_price"]
            coupon.final_payable_amount = coupon_data["final_payable_amount"]
            coupon.first_order_only = coupon_data["first_order_only"]
            coupon.one_time_per_customer = coupon_data["one_time_per_customer"]
            coupon.usage_limit = coupon_data["usage_limit"]
            coupon.per_user_limit = coupon_data["per_user_limit"]
            coupon.auto_apply = coupon_data["auto_apply"]
            coupon.allow_combination = coupon_data["allow_combination"]
            coupon.show_on_product_page = coupon_data["show_on_product_page"]
            coupon.product_page_priority = coupon_data["product_page_priority"]
            coupon.is_active = True
            coupon.updated_at = datetime.utcnow()
        elif not coupon.discount_value and coupon_data["discount_value"]:
            coupon.discount_type = coupon.discount_type or coupon_data["discount_type"]
            coupon.discount_value = coupon_data["discount_value"]
            coupon.min_order_amount = coupon.min_order_amount if coupon.min_order_amount is not None else coupon_data["min_order_amount"]
            coupon.per_user_limit = coupon.per_user_limit if coupon.per_user_limit is not None else coupon_data["per_user_limit"]
            if coupon.show_on_product_page is None:
                coupon.show_on_product_page = coupon_data["show_on_product_page"]
            if coupon.product_page_priority is None:
                coupon.product_page_priority = coupon_data["product_page_priority"]
        else:
            coupon.description = coupon.description or coupon_data["description"]
            coupon.coupon_type = coupon.coupon_type or coupon_data["coupon_type"]
            coupon.applicable_category = coupon.applicable_category or coupon_data["applicable_category"]
            coupon.one_time_per_customer = coupon.one_time_per_customer if coupon.one_time_per_customer is not None else coupon_data["one_time_per_customer"]
            coupon.auto_apply = coupon.auto_apply if coupon.auto_apply is not None else coupon_data["auto_apply"]
            coupon.allow_combination = coupon.allow_combination if coupon.allow_combination is not None else coupon_data["allow_combination"]
            if coupon.min_quantity_required is None:
                coupon.min_quantity_required = coupon_data["min_quantity_required"]
            if coupon.required_product_price is None:
                coupon.required_product_price = coupon_data["required_product_price"]
            if coupon.final_payable_amount is None:
                coupon.final_payable_amount = coupon_data["final_payable_amount"]

    db.session.commit()

with app.app_context():
    print("DB IN USE:", describe_database_url(db.engine.url))
    print("SAFE DB MIGRATION: creating missing tables with db.create_all(checkfirst=True)")
    db.create_all()
    ensure_live_db_columns()
    ensure_default_coupons()

# TEMPORARY: remove this registration and temporary_db_json_transfer.py after
# the Railway internal database-to-database JSON transfer is complete.
from temporary_db_json_transfer import register_temporary_db_json_transfer_routes
register_temporary_db_json_transfer_routes(app, db)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "webm"}

# Keep this for old local blog image fallback support
BLOG_UPLOAD_SUBDIR = "uploads/blogs"

# Local folder saving is not needed for new blog images
# BLOG_UPLOAD_FOLDER = os.path.join(app.static_folder, "uploads", "blogs")

DEFAULT_IMAGE_URL = "/static/images/default.png"

# Do not create local upload folder for production storage
# os.makedirs(BLOG_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename, filetype="image"):
    if "." not in filename:
        return False

    ext = filename.rsplit(".", 1)[1].lower()

    if filetype == "image":
        return ext in ALLOWED_IMAGE_EXTENSIONS
    else:
        return ext in ALLOWED_VIDEO_EXTENSIONS


def save_blog_image(file):
    if not file or not file.filename or not allowed_file(file.filename, "image"):
        return None

    try:
        result = cloudinary.uploader.upload(
            file,
            folder="blogs",
            resource_type="image"
        )
        return result.get("secure_url")
    except Exception as e:
        app.logger.error("Cloudinary blog image upload failed: %s", e)
        return None


def request_blog_image_file():
    for field_name in ("cover_image_cropped", "cover_image", "image"):
        file = request.files.get(field_name)
        if file and file.filename:
            return file
    return None


def blog_image_url(image):
    if not image:
        return DEFAULT_IMAGE_URL

    image = str(image).strip().replace("\\", "/")
    if not image:
        return DEFAULT_IMAGE_URL

    if image.startswith(("http://", "https://", "//", "data:")):
        return image

    if image.startswith("/static/"):
        return image

    if image.startswith("static/"):
        return f"/{image}"

    if image.startswith("/uploads/blogs/"):
        return url_for("static", filename=image.lstrip("/"))

    if image.startswith(BLOG_UPLOAD_SUBDIR + "/"):
        return url_for("static", filename=image)

    static_marker = f"static/{BLOG_UPLOAD_SUBDIR}/"
    if static_marker in image:
        return f"/{image[image.index(static_marker):]}"

    return url_for("static", filename=f"{BLOG_UPLOAD_SUBDIR}/{os.path.basename(image)}")


app.jinja_env.globals["blog_image_url"] = blog_image_url


def normalize_optional_int(value):
    if value in (None, "", "null", "None", "undefined"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def request_color_id(data=None):
    data = data or {}
    return normalize_optional_int(
        data.get("color_id")
        or data.get("product_color_id")
        or request.args.get("color_id")
        or request.args.get("product_color_id")
        or request.args.get("color")
    )


def nullable_match_sql(column_name, param_name):
    return f"(({column_name} IS NULL AND :{param_name} IS NULL) OR {column_name}=:{param_name})"


SUPPORT_EMAIL = os.environ.get("ADMIN_EMAIL") or os.environ.get("SUPPORT_EMAIL") or "beltpurse.com@gmail.com"
RESEND_FROM_EMAIL = (
    os.environ.get("MAIL_FROM")
    or os.environ.get("RESEND_FROM_EMAIL")
    or "Belt Purse <noreply@belt-purse.com>"
)
app.logger.info(
    "Email provider=resend api_key_loaded=%s from=%s support_recipient=%s",
    bool(os.environ.get("RESEND_API_KEY")),
    RESEND_FROM_EMAIL,
    SUPPORT_EMAIL
)


def json_error(message="Something went wrong", status_code=500):
    return jsonify({"success": False, "message": message}), status_code


def user_counts(user_id):
    cart_count = db.session.execute(text("""
        SELECT COALESCE(SUM(quantity),0) FROM cart WHERE user_id=:uid
    """), {"uid": user_id}).scalar() or 0
    wishlist_count = db.session.execute(text("""
        SELECT COUNT(*) FROM wishlist WHERE user_id=:uid
    """), {"uid": user_id}).scalar() or 0
    return int(cart_count), int(wishlist_count)


def cart_totals_payload(user_id):
    bag_total = db.session.execute(text("""
        SELECT COALESCE(SUM(p.price * c.quantity),0)
        FROM cart c
        JOIN products p ON p.id = c.product_id
        WHERE c.user_id=:uid
    """), {"uid": user_id}).scalar() or 0
    bag_total = float(bag_total)
    discount = 0
    shipping = 0
    payable = bag_total - discount + shipping
    cart_count, wishlist_count = user_counts(user_id)
    return {
        "cart_count": cart_count,
        "wishlist_count": wishlist_count,
        "bag_total": bag_total,
        "discount": discount,
        "shipping": shipping,
        "payable": payable,
        "subtotal": bag_total,
        "is_empty": cart_count <= 0
    }


def cart_line_total(user_id, product_id, color_id=None, size_id=None):
    return db.session.execute(text("""
        SELECT COALESCE(p.price * c.quantity,0) AS item_total
        FROM cart c
        JOIN products p ON p.id = c.product_id
        WHERE c.user_id=:uid AND c.product_id=:pid
        AND ((c.color_id IS NULL AND :cid IS NULL) OR c.color_id=:cid)
        AND ((c.size_id IS NULL AND :sid IS NULL) OR c.size_id=:sid)
        LIMIT 1
    """), {"uid": user_id, "pid": product_id, "cid": color_id, "sid": size_id}).scalar() or 0


def request_cart_item_id(data=None):
    data = data or {}
    return normalize_optional_int(
        data.get("cart_item_id")
        or data.get("cart_id")
        or request.args.get("cart_item_id")
        or request.args.get("cart_id")
    )


def cart_item_total(cart_item):
    if not cart_item:
        return 0
    product = cart_item.product or Product.query.get(cart_item.product_id)
    if not product:
        return 0
    return float(product.price or 0) * int(cart_item.quantity or 0)


def cart_item_payload(cart_item):
    if not cart_item:
        return {}
    product = cart_item.product or Product.query.get(cart_item.product_id)
    size_label = ""
    if cart_item.size:
        size_label = cart_item.size.size_label
    elif product and product_size_type(product) == "universal":
        size_label = "Universal Size"
    return {
        "cart_item_id": cart_item.id,
        "product_id": cart_item.product_id,
        "color_id": cart_item.color_id,
        "size_id": cart_item.size_id,
        "size_label": size_label,
        "quantity": int(cart_item.quantity or 0),
        "item_total": cart_item_total(cart_item),
    }


def validate_cart_lines_for_checkout(cart_lines):
    for line in cart_lines or []:
        product = line.get("product")
        if not product:
            return False, "A product in your cart is no longer available."
        if product_requires_size(product.id) and not line.get("size_id"):
            return False, f"Please select a size for {product.name} before checkout."
    return True, None


def consolidate_cart_duplicates(user_id):
    grouped = defaultdict(list)
    items = Cart.query.filter_by(user_id=user_id).order_by(Cart.id.asc()).all()
    changed = False

    for item in items:
        if not product_requires_size(item.product_id) and item.size_id is not None:
            item.size_id = None
            changed = True
        grouped[(item.product_id, item.color_id, item.size_id)].append(item)

    for duplicates in grouped.values():
        if len(duplicates) <= 1:
            continue

        keeper = duplicates[0]
        keeper.quantity = sum(int(item.quantity or 0) for item in duplicates)
        for duplicate in duplicates[1:]:
            db.session.delete(duplicate)
        changed = True

    if changed:
        db.session.commit()


def parse_optional_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def save_homepage_media_file(file, media_type):
    if not file or not file.filename:
        return None, None

    filetype = "video" if media_type == "style_video" else "image"
    if not allowed_file(file.filename, filetype):
        return None, None

    result = cloudinary.uploader.upload(
        file,
        folder="homepage",
        resource_type="video" if filetype == "video" else "image"
    )
    return result.get("secure_url"), result.get("public_id")


def parse_optional_float(value):
    value = (value or "").strip()
    if value == "":
        return None
    return float(value)


def parse_optional_int(value):
    value = (value or "").strip()
    if value == "":
        return None
    return int(value)


def add_cart_item(user, product_id, color_id=None, size_id=None, quantity=1):
    quantity = max(int(quantity or 1), 1)
    size_id = normalize_cart_size_id(product_id, size_id)
    clear_wallet_cart_sizes(product_id, user.id)

    existing_items = Cart.query.filter_by(
        user_id=user.id,
        product_id=product_id,
        color_id=color_id,
        size_id=size_id
    ).order_by(Cart.id.asc()).all()

    if existing_items:
        existing = existing_items[0]
        existing.quantity = int(existing.quantity or 0) + quantity
        for duplicate in existing_items[1:]:
            existing.quantity += int(duplicate.quantity or 0)
            db.session.delete(duplicate)
        return existing

    cart_item = Cart(
        user_id=user.id,
        product_id=product_id,
        color_id=color_id,
        size_id=size_id,
        quantity=quantity
    )
    db.session.add(cart_item)
    return cart_item


def product_requires_size(product_id):
    product = Product.query.get(product_id)
    if not product:
        return False
    if is_wallet_product(product):
        return False
    if normalize_size_type(product.size_type) in ("universal", "none"):
        return False
    if product.requires_size is not None:
        return bool(product.requires_size)
    return (product.product_type or "belt") == "belt"


def is_wallet_product(product):
    product_type = (getattr(product, "product_type", "") or "").strip().lower()
    return product_type in ("wallet", "wallets", "purse", "purses")


def normalize_size_type(size_type=None):
    value = (size_type or "specific").strip().lower()
    if value in ("universal", "none"):
        return value
    return "specific"


def product_size_type(product):
    if is_wallet_product(product):
        return None
    return normalize_size_type(product.size_type)


def normalize_cart_size_id(product_id, size_id):
    if not product_requires_size(product_id):
        return None
    return normalize_optional_int(size_id)


def clear_wallet_cart_sizes(product_id, user_id=None):
    if product_requires_size(product_id):
        return

    query = Cart.query.filter_by(product_id=product_id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    query.filter(Cart.size_id.isnot(None)).update(
        {Cart.size_id: None},
        synchronize_session=False
    )
    db.session.flush()


def is_valid_product_size(product_id, size_id):
    if not size_id:
        return not product_requires_size(product_id)
    return ProductSize.query.filter_by(id=size_id, product_id=product_id).first() is not None


def normalize_guest_cart_item(item):
    if not isinstance(item, dict):
        return None

    product_id = normalize_optional_int(
        item.get("productId")
        or item.get("product_id")
        or item.get("id")
    )
    if not product_id:
        return None

    color_id = normalize_optional_int(
        item.get("colorId")
        or item.get("color_id")
        or item.get("product_color_id")
    )
    size_id = normalize_optional_int(
        item.get("sizeId")
        or item.get("size_id")
        or item.get("selected_size_id")
    )

    try:
        quantity = int(item.get("qty") or item.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1

    return {
        "product_id": product_id,
        "color_id": color_id,
        "size_id": size_id,
        "quantity": max(quantity, 1),
    }


def merge_guest_cart_items_to_user(user, items):
    merged_count = 0
    for item in items or []:
        normalized = normalize_guest_cart_item(item)
        if not normalized:
            continue

        product = Product.query.get(normalized["product_id"])
        if not product or product.is_archived:
            continue
        normalized["size_id"] = normalize_cart_size_id(product.id, normalized["size_id"])
        if not is_valid_product_size(product.id, normalized["size_id"]):
            continue

        add_cart_item(
            user,
            normalized["product_id"],
            normalized["color_id"],
            normalized["size_id"],
            normalized["quantity"]
        )
        merged_count += normalized["quantity"]

    if merged_count:
        db.session.commit()
        consolidate_cart_duplicates(user.id)

    return merged_count


def merge_session_guest_cart_to_user(user):
    guest_items = []
    for key in ("cart", "guest_cart", "cart_items"):
        value = session.get(key)
        if not value:
            continue
        if isinstance(value, dict):
            guest_items.extend(value.values())
        elif isinstance(value, list):
            guest_items.extend(value)

    merged_count = merge_guest_cart_items_to_user(user, guest_items)

    for key in ("cart", "guest_cart", "cart_items"):
        session.pop(key, None)
    session.modified = True

    return merged_count


def send_resend_email(subject, body="", attachments=None, to_email=None, html=None):
    if resend is None:
        raise RuntimeError("resend package is not installed. Run: pip install resend")

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY environment variable is not set")

    resend.api_key = api_key
    params = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email or SUPPORT_EMAIL],
        "subject": subject,
    }

    if html:
        params["html"] = html
    else:
        params["text"] = body

    if attachments:
        params["attachments"] = attachments

    return resend.Emails.send(params)


def send_resend_email_safe(subject, body="", attachments=None, to_email=None, html=None):
    try:
        result = send_resend_email(subject, body=body, attachments=attachments, to_email=to_email, html=html)
        app.logger.info("Email accepted by Resend for subject %s to %s", subject, to_email or SUPPORT_EMAIL)
        return True, result
    except Exception:
        app.logger.exception("Email send failed for subject %s to %s", subject, to_email or SUPPORT_EMAIL)
        return False, None


def get_logged_in_user():
    if 'email' not in session:
        return None

    return User.query.filter_by(email=session['email']).first()


def get_razorpay_client():
    key_id = app.config.get("RAZORPAY_KEY_ID")
    key_secret = app.config.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        raise RuntimeError(
            "Razorpay credentials missing. Please create .env from .env.example "
            "and add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET."
        )

    if razorpay is None:
        raise RuntimeError("razorpay package is not installed")

    return razorpay.Client(auth=(key_id, key_secret))


def cart_snapshot_for_user(user_id):
    consolidate_cart_duplicates(user_id)
    cart_items = Cart.query.filter_by(user_id=user_id).all()
    order_lines = []
    total = 0.0

    for cart_item in cart_items:
        product = cart_item.product or Product.query.get(cart_item.product_id)
        if not product:
            continue

        quantity = int(cart_item.quantity or 1)
        price = float(product.price or 0)
        item_total = price * quantity
        total += item_total
        order_lines.append({
            "product": product,
            "product_id": product.id,
            "size_id": cart_item.size_id,
            "color_id": cart_item.color_id,
            "quantity": quantity,
            "price": price,
            "item_total": item_total,
        })

    return order_lines, total


SUCCESSFUL_ORDER_STATUSES = (
    "placed",
    "confirmed",
    "shipped",
    "delivered",
)

NON_SUCCESSFUL_ORDER_STATUSES = (
    "Cancelled",
    "Failed",
    "Payment Failed",
)


def user_has_successful_order(user_id):
    return Order.query.filter(
        Order.user_id == user_id,
        db.or_(
            db.func.lower(Order.order_status).in_(SUCCESSFUL_ORDER_STATUSES),
            db.func.lower(Order.status).in_(SUCCESSFUL_ORDER_STATUSES),
        )
    ).first() is not None


def coupon_usage_count(coupon_id):
    return CouponUsage.query.filter_by(coupon_id=coupon_id).count()


def coupon_user_usage_count(coupon_id, user_id):
    return CouponUsage.query.filter_by(coupon_id=coupon_id, user_id=user_id).count()


def normalize_coupon_category(value):
    value = (value or "all").strip().lower()
    if value in ("belts", "belt"):
        return "belt"
    if value in ("wallets", "wallet", "purse", "purses"):
        return "wallet"
    return "all"


def coupon_product_ids(coupon):
    return {product.id for product in getattr(coupon, "applicable_products", [])}


def coupon_applicable_lines(coupon, cart_lines, check_required_price=True):
    category = normalize_coupon_category(getattr(coupon, "applicable_category", "all"))
    selected_product_ids = coupon_product_ids(coupon)
    required_price = getattr(coupon, "required_product_price", None)
    applicable = []

    for line in cart_lines or []:
        product = line.get("product")
        if not product:
            continue
        if category != "all" and normalize_product_type(getattr(product, "product_type", None)) != category:
            continue
        if selected_product_ids and product.id not in selected_product_ids:
            continue
        if check_required_price and required_price is not None and float(line.get("price") or 0) != float(required_price):
            continue
        applicable.append(line)

    return applicable


def eligible_unit_prices(lines, limit=None):
    unit_prices = []
    for line in lines:
        quantity = int(line.get("quantity") or 0)
        price = float(line.get("price") or 0)
        unit_prices.extend([price] * quantity)
    unit_prices.sort()
    return unit_prices[:limit] if limit else unit_prices


def coupon_scope_message(coupon, quantity_short=False):
    category = normalize_coupon_category(getattr(coupon, "applicable_category", "all"))
    if category == "belt":
        min_qty = int(getattr(coupon, "min_quantity_required", None) or 0)
        if quantity_short and min_qty >= 2:
            return f"Add {min_qty} belts to use this offer"
        return "This coupon is not valid for wallet products"
    if category == "wallet":
        return "This coupon is not valid for belt products"
    return "Coupon is not valid for these products"


def calculate_coupon_discount(coupon, subtotal, cart_lines):
    coupon_type = (coupon.coupon_type or "").strip().lower()
    discount_type = (coupon.discount_type or "fixed").strip().lower()
    applicable_lines = coupon_applicable_lines(coupon, cart_lines)
    category = normalize_coupon_category(getattr(coupon, "applicable_category", "all"))
    selected_product_ids = coupon_product_ids(coupon)
    has_scope_rule = category != "all" or bool(selected_product_ids) or coupon.required_product_price is not None

    if has_scope_rule and not applicable_lines:
        broader_lines = coupon_applicable_lines(coupon, cart_lines, check_required_price=False)
        if broader_lines and coupon.required_product_price is not None:
            return None, f"This coupon is only valid for Rs.{int(coupon.required_product_price)} products"
        return None, coupon_scope_message(coupon)

    scoped_lines = applicable_lines if has_scope_rule else (cart_lines or [])
    scoped_total = sum(float(line.get("item_total") or 0) for line in scoped_lines)
    scoped_qty = sum(int(line.get("quantity") or 0) for line in scoped_lines)
    min_qty = int(coupon.min_quantity_required or 0)
    if min_qty and scoped_qty < min_qty:
        return None, coupon_scope_message(coupon, quantity_short=True)

    if coupon_type == "buy_x_fixed_payable":
        if not min_qty:
            return None, "Minimum quantity is required for this coupon"
        if coupon.final_payable_amount is None:
            return None, "Final payable amount is required for this coupon"
        unit_prices = eligible_unit_prices(scoped_lines, min_qty)
        selected_total = sum(unit_prices)
        discount_amount = selected_total - float(coupon.final_payable_amount or 0)
    elif coupon_type == "buy_x_get_y_discount":
        unit_prices = eligible_unit_prices(scoped_lines, min_qty or None)
        selected_total = sum(unit_prices) if min_qty else scoped_total
        if discount_type == "percent":
            discount_amount = selected_total * float(coupon.discount_value or 0) / 100
        else:
            discount_amount = float(coupon.discount_value or 0)
    elif discount_type in ("percent", "percentage"):
        discount_base = scoped_total if has_scope_rule else subtotal
        discount_amount = discount_base * float(coupon.discount_value or 0) / 100
    else:
        discount_amount = float(coupon.discount_value or 0)

    if coupon.max_discount_amount is not None:
        discount_amount = min(discount_amount, float(coupon.max_discount_amount or 0))

    return min(max(discount_amount, 0), subtotal), None


def validate_coupon_for_user(user, coupon_code, subtotal=None, shipping_amount=0, cart_lines=None):
    code = (coupon_code or "").strip().upper()
    if cart_lines is None and user:
        cart_lines, calculated_subtotal = cart_snapshot_for_user(user.id)
        subtotal = calculated_subtotal if subtotal is None else subtotal
    subtotal = float(subtotal or 0)
    shipping_amount = float(shipping_amount or 0)
    today = date.today()

    if not code:
        return {
            "valid": True,
            "coupon": None,
            "coupon_code": None,
            "discount_amount": 0.0,
            "subtotal_amount": subtotal,
            "shipping_amount": shipping_amount,
            "final_amount": subtotal + shipping_amount,
            "message": "",
        }

    coupon = Coupon.query.filter(db.func.upper(Coupon.code) == code).first()
    if not coupon:
        return {"valid": False, "message": "Invalid coupon code"}

    if not coupon.is_active:
        return {"valid": False, "message": "Coupon is inactive"}

    if coupon.valid_from and coupon.valid_from > today:
        return {"valid": False, "message": "Coupon is not active yet"}

    if coupon.valid_until and coupon.valid_until < today:
        return {"valid": False, "message": "Coupon expired"}

    if coupon.first_order_only and user_has_successful_order(user.id):
        return {"valid": False, "message": "This coupon is only valid on first order"}

    usage_count = max(int(coupon.used_count or 0), coupon_usage_count(coupon.id))
    if coupon.usage_limit is not None and usage_count >= int(coupon.usage_limit):
        return {"valid": False, "message": "Coupon usage limit reached"}

    per_user_limit = int(coupon.per_user_limit if coupon.per_user_limit is not None else 1)
    if coupon.one_time_per_customer and (per_user_limit <= 0 or per_user_limit > 1):
        per_user_limit = 1
    if per_user_limit > 0 and coupon_user_usage_count(coupon.id, user.id) >= per_user_limit:
        return {"valid": False, "message": "Coupon already used"}

    min_order_amount = float(coupon.min_order_amount or 0)
    if min_order_amount and subtotal < min_order_amount:
        return {"valid": False, "message": f"{coupon.code} is valid only on orders above Rs.{int(min_order_amount)}"}

    discount_amount, discount_error = calculate_coupon_discount(coupon, subtotal, cart_lines or [])
    if discount_error:
        return {"valid": False, "message": discount_error}

    final_amount = max(subtotal - discount_amount + shipping_amount, 0)

    return {
        "valid": True,
        "coupon": coupon,
        "coupon_code": coupon.code,
        "discount_amount": discount_amount,
        "subtotal_amount": subtotal,
        "shipping_amount": shipping_amount,
        "final_amount": final_amount,
        "message": f"{coupon.title} applied",
    }


def best_auto_coupon_for_user(user, subtotal, cart_lines=None, shipping_amount=0):
    today = date.today()
    best_result = None
    coupons = Coupon.query.filter(
        Coupon.is_active == True,
        Coupon.auto_apply == True,
        db.or_(Coupon.valid_from.is_(None), Coupon.valid_from <= today),
        db.or_(Coupon.valid_until.is_(None), Coupon.valid_until >= today),
    ).order_by(Coupon.product_page_priority.desc(), Coupon.id.asc()).all()

    for coupon in coupons:
        result = validate_coupon_for_user(
            user,
            coupon.code,
            subtotal,
            shipping_amount=shipping_amount,
            cart_lines=cart_lines,
        )
        if result["valid"] and float(result.get("discount_amount") or 0) > 0:
            if not best_result or result["discount_amount"] > best_result["discount_amount"]:
                best_result = result

    return best_result or validate_coupon_for_user(user, None, subtotal, shipping_amount, cart_lines)


def product_page_coupon_condition(coupon):
    title = (coupon.title or "").strip()
    discount_value = int(coupon.discount_value or 0)
    discount_type = (coupon.discount_type or "fixed").lower()

    if title:
        fixed_prefix = f"Rs.{discount_value} OFF "
        percent_prefix = f"{discount_value}% OFF "
        if title.lower().startswith(fixed_prefix.lower()):
            return title[len(fixed_prefix):].strip()
        if title.lower().startswith(percent_prefix.lower()):
            return title[len(percent_prefix):].strip()
        return title

    if coupon.min_order_amount:
        return f"Above {int(coupon.min_order_amount)}"

    return "Offer"


def product_page_coupon_display_text(coupon):
    code = (coupon.code or "").strip().upper()
    coupon_type = (coupon.coupon_type or "").lower()
    discount_type = (coupon.discount_type or "fixed").lower()
    discount_value = int(coupon.discount_value or 0)

    if coupon_type == "buy_x_fixed_payable" and coupon.min_quantity_required and coupon.final_payable_amount:
        category = normalize_coupon_category(coupon.applicable_category)
        category_label = "belts" if category == "belt" else "items"
        return f"Buy {int(coupon.min_quantity_required)} {category_label} pay Rs.{int(coupon.final_payable_amount)} - Code {code}"

    if discount_type == "percent":
        if coupon.max_discount_amount:
            return f"{discount_value}% OFF up to Rs.{int(coupon.max_discount_amount)} · Code {code}"
        return f"{discount_value}% OFF {product_page_coupon_condition(coupon)} · Code {code}"

    return f"Rs.{discount_value} OFF {product_page_coupon_condition(coupon)} · Code {code}"


def get_product_page_coupons(user):
    today = date.today()
    query = Coupon.query.filter(
        Coupon.is_active == True,
        Coupon.show_on_product_page == True,
        db.or_(Coupon.valid_from.is_(None), Coupon.valid_from <= today),
        db.or_(Coupon.valid_until.is_(None), Coupon.valid_until >= today),
    ).order_by(
        Coupon.product_page_priority.desc(),
        Coupon.created_at.desc(),
        Coupon.id.desc(),
    )

    has_successful_order = user.is_authenticated and user_has_successful_order(user.id)
    eligible = []
    first_order_coupon = None

    for coupon in query.all():
        if coupon.first_order_only and has_successful_order:
            continue

        usage_count = max(int(coupon.used_count or 0), coupon_usage_count(coupon.id))
        if coupon.usage_limit is not None and usage_count >= int(coupon.usage_limit):
            continue

        coupon.display_text = product_page_coupon_display_text(coupon)
        if coupon.first_order_only and not first_order_coupon:
            first_order_coupon = coupon
        else:
            eligible.append(coupon)

    product_page_coupons = []
    if first_order_coupon:
        product_page_coupons.append(first_order_coupon)

    for coupon in eligible:
        if len(product_page_coupons) >= 2:
            break
        product_page_coupons.append(coupon)

    return product_page_coupons


def current_coupon_code():
    return (session.get("coupon_code") or "").strip().upper()


@app.route('/apply-coupon', methods=['POST'])
def apply_coupon():
    user = get_logged_in_user()
    if not user:
        return json_error("Please login to apply coupon", 401)

    data = request.get_json(silent=True) or {}
    coupon_code = (data.get("coupon_code") or "").strip().upper()
    if not coupon_code:
        session.pop("coupon_code", None)
        session.modified = True
        _, subtotal = cart_snapshot_for_user(user.id)
        return jsonify({
            "success": True,
            "message": "Coupon removed",
            "coupon_code": None,
            "discount_amount": 0,
            "subtotal_amount": subtotal,
            "shipping_amount": 0,
            "final_amount": subtotal,
        })

    existing_coupon_code = current_coupon_code()
    if existing_coupon_code and existing_coupon_code != coupon_code:
        return jsonify({
            "success": False,
            "message": "Only one coupon can be applied per order",
            "coupon_code": existing_coupon_code,
        }), 400

    cart_lines, subtotal = cart_snapshot_for_user(user.id)
    if subtotal <= 0:
        return json_error("Cart is empty", 400)

    coupon_result = validate_coupon_for_user(user, coupon_code, subtotal, cart_lines=cart_lines)
    if not coupon_result["valid"]:
        session.pop("coupon_code", None)
        session.modified = True
        return jsonify({
            "success": False,
            "message": coupon_result["message"],
            "coupon_code": None,
            "discount_amount": 0,
            "subtotal_amount": subtotal,
            "shipping_amount": 0,
            "final_amount": subtotal,
        }), 400

    session["coupon_code"] = coupon_result["coupon_code"]
    session.modified = True

    return jsonify({
        "success": True,
        "message": coupon_result["message"],
        "coupon_code": coupon_result["coupon_code"],
        "discount_amount": coupon_result["discount_amount"],
        "subtotal_amount": coupon_result["subtotal_amount"],
        "final_amount": coupon_result["final_amount"],
    })


def create_pending_order_from_cart(user, selected_address, payment_method="Razorpay", coupon_code=None):
    order_lines, total = cart_snapshot_for_user(user.id)
    if not order_lines:
        return None, "Cart is empty"
    cart_valid, cart_error = validate_cart_lines_for_checkout(order_lines)
    if not cart_valid:
        return None, cart_error

    coupon_result = validate_coupon_for_user(user, coupon_code, total, cart_lines=order_lines)
    if not coupon_result["valid"]:
        session.pop("coupon_code", None)
        session.modified = True
        return None, coupon_result["message"]

    discount_amount = coupon_result["discount_amount"]
    final_amount = coupon_result["final_amount"]

    temp_razorpay_order_id = f"TEMP-{user.id}-{uuid.uuid4().hex[:16]}"

    order = Order(
        user_id=user.id,
        address_id=selected_address.id,
        total_amount=final_amount,
        subtotal_amount=total,
        discount_amount=discount_amount,
        coupon_discount_amount=discount_amount,
        final_amount=final_amount,
        coupon_code=coupon_result["coupon_code"],
        applied_coupon_code=coupon_result["coupon_code"],
        status="Pending",
        order_status="Pending",
        payment_status="Pending",
        payment_method=payment_method,
        tracking_number=f"TRK{user.id}{int(datetime.utcnow().timestamp())}",

        # ✅ Railway DB me razorpay_order_id Not NULL ban gaya hai,
        # isliye pending order create karte time temporary value deni zaroori hai.
        razorpay_order_id=temp_razorpay_order_id,

        # ✅ Ye columns nullable hone chahiye, but safe ke liye None rehne do
        razorpay_payment_id=None,
        razorpay_signature=None,
        paid_at=None,
        courier_partner=None,
        tracking_url=None
    )

    db.session.add(order)
    db.session.flush()

    for line in order_lines:
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=line["product_id"],
            size_id=line["size_id"],
            color_id=line["color_id"],
            quantity=line["quantity"],
            price=line["price"]
        ))

    db.session.commit()
    return order, None
def reusable_pending_order(user_id, address_id, total, coupon_code=None):
    cutoff = datetime.utcnow() - timedelta(hours=2)
    coupon_code = (coupon_code or "").strip().upper() or None
    return Order.query.filter(
        Order.user_id == user_id,
        Order.address_id == address_id,
        Order.payment_status == "Pending",
        Order.order_status == "Pending",
        Order.razorpay_order_id.isnot(None),
        Order.razorpay_order_id.like("order_%"),   # ✅ only real Razorpay order IDs
        Order.created_at >= cutoff,
        Order.total_amount == total,
        Order.coupon_code == coupon_code
    ).order_by(Order.id.desc()).first()

def verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    key_secret = app.config.get("RAZORPAY_KEY_SECRET")
    if not key_secret:
        raise RuntimeError("Razorpay secret is not configured")

    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        message,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, razorpay_signature or "")


def verify_razorpay_webhook(raw_body, signature):
    webhook_secret = app.config.get("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError("Razorpay webhook secret is not configured")

    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature or "")

@app.route("/check-razorpay-order-status", methods=["POST"])
@app.route("/check-razorpay-payment-status", methods=["POST"])
def check_razorpay_order_status():
    print("CHECK RAZORPAY ORDER STATUS HIT")
    print("Status check data:", request.get_json())

    user = get_logged_in_user()
    if not user:
        return json_error("Please login to continue", 401)

    data = request.get_json() or {}

    local_order_id = (
        data.get("pending_order_id")
        or data.get("local_order_id")
        or data.get("order_id")
    )
    razorpay_order_id = data.get("razorpay_order_id")

    if not local_order_id or not razorpay_order_id:
        return json_error("Missing order details", 400)

    order = Order.query.filter_by(
        id=local_order_id,
        user_id=user.id
    ).first()

    if not order:
        return json_error("Order not found", 404)

    if order.payment_status == "Paid":
        return jsonify({
            "success": True,
            "payment_status": "Paid",
            "message": "Order already confirmed",
            "order_id": order.id,
            "redirect": url_for("order_success", order_id=order.id),
            "redirect_url": url_for("order_success", order_id=order.id)
        })

    if order.razorpay_order_id != razorpay_order_id:
        return json_error("Order mismatch", 400)

    try:
        client = get_razorpay_client()

        payments = client.order.payments(razorpay_order_id)
        print("Razorpay order payments:", payments)

        payment_items = payments.get("items", []) if isinstance(payments, dict) else []

        paid_payment = None

        for payment in payment_items:
            if payment.get("status") in ["captured", "authorized"]:
                paid_payment = payment
                break

        if not paid_payment:
            return jsonify({
                "success": False,
                "payment_status": "Pending",
                "message": "Payment is not completed yet. Your cart is safe."
            }), 200

        razorpay_payment_id = paid_payment.get("id")

        # ✅ Mark order paid using your existing safe function
        mark_order_paid(
            order,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=None,
            send_emails=True
        )

        return jsonify({
            "success": True,
            "payment_status": "Paid",
            "message": "Payment confirmed successfully",
            "order_id": order.id,
            "redirect": url_for("order_success", order_id=order.id),
            "redirect_url": url_for("order_success", order_id=order.id)
        })

    except Exception as exc:
        db.session.rollback()
        print("Razorpay fallback status check error:", exc)
        app.logger.error(
            "Razorpay fallback status check failed for order %s: %s",
            order.id,
            exc
        )
        return json_error("Could not verify payment status. Please contact support.", 500)
    
def build_order_email_lines(order):
    lines = []
    for item in order.items:
        product_name = item.product.name if item.product else f"Product #{item.product_id}"
        if item.size:
            size_label = f", Size: {item.size.size_label}"
        elif item.product and product_size_type(item.product) == "universal":
            size_label = ", Size: Universal"
        else:
            size_label = ""
        color_name = f", Color: {item.color.name}" if item.color else ""
        lines.append(
            f"{product_name}{size_label}{color_name} x {item.quantity} - INR {item.price * item.quantity}"
        )
    return lines


def format_order_address(order):
    address = Address.query.get(order.address_id) if order.address_id else None
    if not address:
        return "Not provided"

    return (
        f"{address.full_name}, {address.phone}, {address.address_line}, "
        f"{address.city}, {address.state} - {address.pincode}"
    )


def order_item_image_url(item):
    image = None
    if item.color_id:
        image = ProductImage.query.filter_by(
            product_id=item.product_id,
            color_id=item.color_id
        ).first()
    if not image:
        image = ProductImage.query.filter_by(product_id=item.product_id).first()
    return image.image_url if image else DEFAULT_IMAGE_URL


app.jinja_env.globals["order_item_image_url"] = order_item_image_url


def send_paid_order_emails(order):
    address = Address.query.get(order.address_id) if order.address_id else None
    user = order.user
    item_lines = build_order_email_lines(order)
    address_text = format_order_address(order)

    admin_body = "\n".join([
        "New paid order received.",
        "",
        f"Order ID: {order.id}",
        f"Customer: {user.username if user else ''}",
        f"Email: {user.email if user else ''}",
        f"Phone: {address.phone if address else (user.phone if user else '')}",
        f"Full Address: {address_text}",
        f"Amount: INR {order.total_amount}",
        f"Razorpay Payment ID: {order.razorpay_payment_id or ''}",
        f"Razorpay Order ID: {order.razorpay_order_id or ''}",
        f"Payment Status: {order.payment_status}",
        f"Order Status: {order.order_status}",
        "Products:",
        *item_lines,
    ])

    customer_body = "\n".join([
        f"Hi {user.username if user else 'there'},",
        "",
        f"Your BeltPurse order #{order.id} is confirmed.",
        f"Order ID: {order.id}",
        f"Amount: INR {order.total_amount}",
        f"Payment Status: {order.payment_status}",
        f"Order Status: {order.order_status}",
        f"Delivery Address: {address_text}",
        "Products:",
        *item_lines,
    ])

    try:
        send_resend_email("New Paid Order Received - BeltPurse", admin_body)
    except Exception as exc:
        app.logger.error("Admin paid order email failed for order %s: %s", order.id, exc)

    if user and user.email:
        try:
            send_resend_email(
                "Your BeltPurse Order is Confirmed",
                customer_body,
                to_email=user.email
            )
        except Exception as exc:
            app.logger.error("Customer paid order email failed for order %s: %s", order.id, exc)


def build_order_status_email(order):
    user = order.user
    item_lines = build_order_email_lines(order)
    tracking_text = f"\nTracking Number / AWB: {order.tracking_number}" if order.tracking_number else ""
    courier_text = f"\nCourier Partner: {order.courier_partner}" if order.courier_partner else ""
    tracking_url_text = f"\nTracking URL: {order.tracking_url}" if order.tracking_url else ""

    if order.order_status == "Shipped":
        subject = f"Your BeltPurse Order #{order.id} Has Shipped"
        body = (
            f"Hi {user.username if user else 'there'},\n\n"
            f"Your order #{order.id} has been shipped.\n"
            f"Order Status: Shipped"
            f"{courier_text}{tracking_text}{tracking_url_text}\n\n"
            "BeltPurse Team"
        )
        return subject, body

    if order.order_status == "Delivered":
        subject = f"Your BeltPurse Order #{order.id} Was Delivered"
        body = "\n".join([
            f"Hi {user.username if user else 'there'},",
            "",
            f"Your order #{order.id} has been delivered.",
            "Order Status: Delivered",
            "Products:",
            *item_lines,
            "",
            "Thank you for shopping with BeltPurse.",
            f"For support, contact {SUPPORT_EMAIL}.",
        ])
        return subject, body

    subject = f"Your BeltPurse Order #{order.id} Update"
    body = (
        f"Hi {user.username if user else 'there'},\n\n"
        f"Your order #{order.id} status is now: {order.order_status}."
        f"{courier_text}{tracking_text}{tracking_url_text}\n\n"
        "BeltPurse Team"
    )
    return subject, body


def send_order_status_email(order):
    if not order.user or not order.user.email:
        return

    subject, body = build_order_status_email(order)
    send_resend_email_safe(subject, body, to_email=order.user.email)


def mark_order_paid(order, razorpay_payment_id=None, razorpay_signature=None, send_emails=True):
    already_paid = order.payment_status == "Paid"

    if razorpay_payment_id and not order.razorpay_payment_id:
        order.razorpay_payment_id = razorpay_payment_id
    if razorpay_signature and not order.razorpay_signature:
        order.razorpay_signature = razorpay_signature

    order.payment_status = "Paid"
    order.order_status = "Confirmed"
    order.status = "Confirmed"
    order.payment_method = order.payment_method or "Razorpay"
    if not order.paid_at:
        order.paid_at = datetime.utcnow()

    if not already_paid:
        Cart.query.filter_by(user_id=order.user_id).delete()
        if order.coupon_code and float(order.discount_amount or 0) > 0:
            coupon = Coupon.query.filter(db.func.upper(Coupon.code) == order.coupon_code.upper()).first()
            usage_exists = CouponUsage.query.filter_by(order_id=order.id).first()
            if coupon and not usage_exists:
                db.session.add(CouponUsage(
                    coupon_id=coupon.id,
                    user_id=order.user_id,
                    order_id=order.id,
                    discount_amount=float(order.discount_amount or 0)
                ))
                coupon.used_count = coupon_usage_count(coupon.id) + 1
                coupon.updated_at = datetime.utcnow()
        if session.get("coupon_code") == (order.coupon_code or ""):
            session.pop("coupon_code", None)
            session.modified = True

    db.session.commit()

    if send_emails and not already_paid:
        send_paid_order_emails(order)

    return already_paid


def get_base_url():
    base_url = (os.environ.get("BASE_URL") or "").strip().rstrip("/")
    if base_url:
        return base_url
    return request.url_root.rstrip("/")


def build_reset_password_url(token):
    return f"{get_base_url()}{url_for('reset_password', token=token)}"


def password_is_strong(password):
    return (
        len(password or "") >= 8
        and re.search(r"[A-Za-z]", password or "") is not None
        and re.search(r"\d", password or "") is not None
    )


def build_password_reset_email(reset_url, username):
    display_name = html.escape(username or "there")
    safe_reset_url = html.escape(reset_url, quote=True)
    return f"""
    <div style="margin:0;padding:0;background:#f7f3ec;font-family:Arial,sans-serif;color:#183633;">
      <div style="max-width:560px;margin:0 auto;padding:32px 18px;">
        <div style="background:#ffffff;border:1px solid #eadfce;border-radius:16px;padding:28px;box-shadow:0 12px 34px rgba(8,62,58,0.08);">
          <h2 style="margin:0 0 12px;color:#083E3A;font-size:24px;">Reset your Belt Purse password</h2>
          <p style="margin:0 0 18px;line-height:1.6;color:#38504d;">Hi {display_name},</p>
          <p style="margin:0 0 22px;line-height:1.6;color:#38504d;">
            We received a request to reset your password. This secure link will expire in 30 minutes.
          </p>
          <a href="{safe_reset_url}" style="display:inline-block;background:#0A5C56;color:#ffffff;text-decoration:none;padding:13px 22px;border-radius:999px;font-weight:600;">
            Reset Password
          </a>
          <p style="margin:24px 0 0;line-height:1.6;color:#6a7c78;font-size:13px;">
            If the button does not work, open this link:<br>
            <a href="{safe_reset_url}" style="color:#0A5C56;">{safe_reset_url}</a>
          </p>
          <p style="margin:18px 0 0;line-height:1.6;color:#6a7c78;font-size:13px;">
            If you did not request this, you can ignore this email.
          </p>
        </div>
      </div>
    </div>
    """


def create_password_reset_token(user):
    PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({"used": True})
    token = secrets.token_urlsafe(48)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        used=False,
    )
    db.session.add(reset_token)
    db.session.flush()
    return token


def send_password_reset_link(user):
    token = create_password_reset_token(user)
    reset_url = build_reset_password_url(token)
    send_resend_email(
        "Reset your Belt Purse password",
        body=f"Open this link to reset your Belt Purse password: {reset_url}",
        to_email=user.email,
        html=build_password_reset_email(reset_url, user.username),
    )
    return reset_url


def build_resend_attachment(file_storage):
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename) or "invoice"
    content = base64.b64encode(file_storage.read()).decode("utf-8")
    file_storage.stream.seek(0)

    return {
        "filename": filename,
        "content": content,
    }


def format_support_timestamp():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if not session.get("admin"):
            abort(404)

        email = session.get("email")

        if not email:
            abort(404)

        user = User.query.filter_by(email=email).first()

        if not user or not user.is_admin:
            abort(404)

        return f(*args, **kwargs)

    return decorated_function


from flask import send_from_directory
import os

@app.route('/googlef86ab741e88ae339.html')
def google_site_verification():
    return send_from_directory(
        os.getcwd(),
        'googlef86ab741e88ae339.html'
    )

from werkzeug.security import generate_password_hash
from flask import request

@app.route("/create-admin-once")
def create_admin_once():
    secret = request.args.get("secret")

    # Security token - isko same URL me use karna
    if secret != "makeadmin123":
        return "Unauthorized", 403

    email = "admin@gmail.com"
    password = "admin123"

    admin = User.query.filter_by(email=email).first()

    if admin:
        admin.username = "admin"
        admin.password = generate_password_hash(password)
        admin.is_admin = True
        admin.email_verified = True
        admin.phone_verified = False
        if hasattr(admin, "balance") and admin.balance is None:
            admin.balance = 0
        db.session.commit()
        return "Admin updated successfully. Login with admin@gmail.com / admin123"

    admin = User(
        username="admin",
        email=email,
        password=generate_password_hash(password),
        is_admin=True,
        email_verified=True,
        phone_verified=False,
        balance=0
    )

    db.session.add(admin)
    db.session.commit()

    return "Admin created successfully. Login with admin@gmail.com / admin123"

@app.route("/__seed__", methods=["GET"])
def run_seed_route():
    if os.environ.get("ENABLE_SEED_ROUTE") != "true":
        return "Seed route disabled", 403

    seed_key = os.environ.get("SEED_ROUTE_KEY")
    if not seed_key or request.args.get("key") != seed_key:
        return "Forbidden", 403

    from seed import seed_colors, seed_products, seed_admin

    with app.app_context():
        seed_colors()
        seed_products()
        seed_admin()

    return "Seed Done Successfully"





from datetime import timedelta

app.permanent_session_lifetime = timedelta(days=7)  # 🔥 7 days login

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        data = request.get_json(silent=True)

        # fallback for HTML form
        if not data:
            data = request.form

        email = data.get("email")
        password = data.get("password")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password) and user.is_admin:

            session['admin'] = True
            session['email'] = user.email

            session.permanent = bool(data.get("remember"))

            return jsonify({"message": "Admin login success"})

        return jsonify({"message": "Invalid admin credentials"}), 401

    return render_template("admin/login.html")

@app.route("/secure-admin-portal-9821")
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_orders = Order.query.count()
    total_products = Product.query.count()

    return render_template(
        "admin/dashboard.html",
        users=total_users,
        orders=total_orders,
        products=total_products
    )


@app.route("/admin")
def admin_root():
    return redirect("/secure-admin-portal-9821")

from werkzeug.security import generate_password_hash

@app.route("/admin/admins", methods=["GET", "POST"])
@admin_required
def admin_list():

    if request.method == "POST":
        username = request.form.get("username")   # ✅ sabse pehle lo
        email = request.form.get("email")
        password = request.form.get("password")

        # ❌ validation
        if not username or not email or not password:
            flash("All fields are required", "error")
            return redirect("/admin/admins")

        # ❌ username already exists
        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return redirect("/admin/admins")

        # ❌ email already exists
        if User.query.filter_by(email=email).first():
            flash("Email already exists", "error")
            return redirect("/admin/admins")

        # ✅ create admin
        new_admin = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            is_admin=True
        )

        db.session.add(new_admin)
        db.session.commit()

        flash("Admin created successfully", "success")
        return redirect("/admin/admins")

    admins = User.query.filter_by(is_admin=True).all()
    return render_template("admin/admin_list.html", admins=admins)

@app.route("/admin/delete-admin/<int:id>", methods=["POST"])
@admin_required
def delete_admin(id):

    admin = User.query.get_or_404(id)

    # ❌ self delete block
    if admin.email == session.get("email"):
        flash("You cannot delete yourself", "error")
        return redirect("/admin/admins")

    # ❌ only admin delete
    if not admin.is_admin:
        abort(404)

    db.session.delete(admin)
    db.session.commit()

    flash("Admin deleted successfully", "success")
    return redirect("/admin/admins")
@app.route("/admin-logout")
def admin_logout():
    session.clear()   # 🔥 FULL session remove

    return redirect("/admin-login")  # ✅ correct route

@app.route("/admin/products")
@admin_required
def admin_products():
    return render_template("admin/product_categories.html")


def normalize_product_type(product_type=None):
    value = (product_type or request.args.get("type") or request.form.get("product_type") or "belt").strip().lower()
    if value in ("wallet", "wallets", "purse", "purses"):
        return "wallet"
    return "belt"


def product_type_settings(product_type):
    product_type = normalize_product_type(product_type)
    if product_type == "wallet":
        return {
            "product_type": "wallet",
            "requires_size": False,
            "plural_label": "Wallets / Purses",
            "singular_label": "Wallet / Purse",
            "list_url": "/admin/products/wallets",
            "add_url": "/admin/products/wallets/add"
        }
    return {
        "product_type": "belt",
        "requires_size": True,
        "plural_label": "Belts",
        "singular_label": "Belt",
        "list_url": "/admin/products/belts",
        "add_url": "/admin/products/belts/add"
    }


def validate_product_name(name):
    if not name:
        return None, "Product name cannot be empty."
    if name != name.strip():
        return None, "Product name cannot start or end with spaces."
    if re.search(r"\s{2,}", name):
        return None, "Product name cannot contain multiple spaces between words."
    return name, None


def validate_belt_sizes(sizes_text):
    sizes_text = sizes_text or ""
    if not sizes_text:
        return None, "Size is required for belt products."
    if re.search(r"\s", sizes_text):
        return None, "Enter sizes without spaces. Example: 26,28,30"
    if not re.fullmatch(r"\d+(,\d+)*", sizes_text):
        return None, "Enter sizes without spaces. Example: 26,28,30"
    return sizes_text, None


def normalize_product_tag_text(tags_text):
    tags = []
    seen = set()
    for tag in (tags_text or "").split(","):
        clean_tag = tag.strip()
        tag_key = clean_tag.lower()
        if clean_tag and tag_key not in seen:
            tags.append(clean_tag)
            seen.add(tag_key)
    return tags


def update_product_tags_if_changed(product_id, submitted_tags):
    existing_tags = ProductTag.query.filter_by(product_id=product_id).order_by(ProductTag.id.asc()).all()
    existing_normalized = normalize_product_tag_text(",".join(tag.tag or "" for tag in existing_tags))
    submitted_normalized = normalize_product_tag_text(submitted_tags)

    if existing_normalized == submitted_normalized:
        return False

    ProductTag.query.filter_by(product_id=product_id).delete()
    for tag in submitted_normalized:
        db.session.add(ProductTag(product_id=product_id, tag=tag))
    return True


def product_form_data():
    return request.form.to_dict(flat=True)


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def homepage_product_limit(product_type):
    product_type = normalize_product_type(product_type)
    if product_type == "wallet":
        return int(app.config.get("INDEX_WALLETS_LIMIT", 5))
    return int(app.config.get("INDEX_BELTS_LIMIT", 3))


def homepage_limit_message(product_type):
    product_type = normalize_product_type(product_type)
    label = "wallets" if product_type == "wallet" else "belts"
    limit = homepage_product_limit(product_type)
    return f"Homepage {label} limit is {limit}. Please remove another {label[:-1]} first."


def homepage_selection_count(product_type, exclude_product_id=None):
    query = Product.query.filter(
        Product.product_type == normalize_product_type(product_type),
        Product.show_on_homepage == True
    )
    if exclude_product_id:
        query = query.filter(Product.id != exclude_product_id)
    return query.count()


def validate_homepage_selection(product_type, show_on_homepage, product_id=None):
    if not show_on_homepage:
        return None
    if homepage_selection_count(product_type, product_id) >= homepage_product_limit(product_type):
        return homepage_limit_message(product_type)
    return None


def selected_color_ids_from_request():
    selected = []
    for color_id in request.form.getlist("colors"):
        try:
            selected.append(int(color_id))
        except (TypeError, ValueError):
            continue
    return selected


def normalize_hex_code(hex_code):
    if not hex_code:
        return None
    return hex_code.strip().lower()


def validate_color_form(name, hex_code, color_id=None):
    if not name:
        return None, None, "Color name is required."
    if name != name.strip():
        return None, None, "Color name cannot start or end with spaces."
    if re.search(r"\s{2,}", name):
        return None, None, "Color name cannot contain multiple spaces between words."

    clean_name = name.strip()
    clean_hex = normalize_hex_code(hex_code)
    if not clean_hex:
        return None, None, "Hex code is required."
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", clean_hex):
        return None, None, "Hex code must be a valid format like #000000 or #ffffff."

    duplicate_query = Color.query.filter(db.func.lower(Color.name) == clean_name.lower())
    if color_id:
        duplicate_query = duplicate_query.filter(Color.id != color_id)
    if duplicate_query.first():
        return None, None, "A color with this name already exists."

    return clean_name, clean_hex, None


def color_usage_count(color_id):
    return db.session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM product_colors WHERE color_id = :cid) +
            (SELECT COUNT(*) FROM product_images WHERE color_id = :cid) +
            (SELECT COUNT(*) FROM product_videos WHERE color_id = :cid) +
            (SELECT COUNT(*) FROM cart WHERE color_id = :cid) +
            (SELECT COUNT(*) FROM wishlist WHERE color_id = :cid) +
            (SELECT COUNT(*) FROM order_items WHERE color_id = :cid)
    """), {"cid": color_id}).scalar() or 0


def redirect_to_product_list(product):
    return redirect(product_type_settings(getattr(product, "product_type", "belt"))["list_url"])


def admin_products_by_type(product_type):
    settings = product_type_settings(product_type)
    homepage_filter = (request.args.get("filter") or "all").strip().lower()
    products = Product.query.options(
        db.joinedload(Product.images),
        db.joinedload(Product.videos), 
        db.joinedload(Product.product_colors).joinedload(ProductColor.color)
    ).filter(Product.product_type == settings["product_type"])

    if homepage_filter == "homepage":
        products = products.filter(Product.show_on_homepage == True)

    products = products.order_by(Product.id.desc()).all()

    unique_products = []
    seen_product_ids = set()
    for product in products:
        if product.id in seen_product_ids:
            continue
        unique_products.append(product)
        seen_product_ids.add(product.id)

    return render_template(
        "admin/products.html",
        products=unique_products,
        homepage_filter=homepage_filter,
        homepage_limit=homepage_product_limit(settings["product_type"]),
        homepage_selected_count=homepage_selection_count(settings["product_type"]),
        **settings
    )


@app.route("/admin/products/belts")
@admin_required
def admin_belt_products():
    return admin_products_by_type("belt")


@app.route("/admin/products/wallets")
@admin_required
def admin_wallet_products():
    return admin_products_by_type("wallet")


@app.route("/admin/products/homepage/<int:id>", methods=["POST"])
@admin_required
def toggle_product_homepage(id):
    product = Product.query.get_or_404(id)
    product_type = normalize_product_type(product.product_type)
    show_on_homepage = request.form.get("show_on_homepage") == "true"
    sort_order = parse_int(request.form.get("homepage_sort_order"), product.homepage_sort_order or 0)

    error = validate_homepage_selection(product_type, show_on_homepage, product.id)
    if error:
        return jsonify({
            "success": False,
            "message": error,
            "show_on_homepage": bool(product.show_on_homepage),
            "homepage_selected_count": homepage_selection_count(product_type),
        }), 400

    product.show_on_homepage = show_on_homepage
    product.homepage_sort_order = sort_order
    db.session.commit()

    return jsonify({
        "success": True,
        "show_on_homepage": bool(product.show_on_homepage),
        "homepage_sort_order": product.homepage_sort_order or 0,
        "homepage_selected_count": homepage_selection_count(product_type),
        "homepage_limit": homepage_product_limit(product_type),
    })


@app.route("/admin/colors", methods=["GET", "POST"])
@admin_required
def admin_colors():
    if request.method == "POST":
        name, hex_code, error = validate_color_form(
            request.form.get("name"),
            request.form.get("hex_code") or request.form.get("code")
        )
        if error:
            flash(error, "error")
            return redirect("/admin/colors")

        color = Color(name=name, code=hex_code, hex_code=hex_code)
        db.session.add(color)
        db.session.commit()
        flash("Color added successfully.", "success")
        return redirect("/admin/colors")

    colors = Color.query.order_by(Color.name.asc(), Color.id.asc()).all()
    return render_template("admin/colors.html", colors=colors, usage_count=color_usage_count)


@app.route("/admin/colors/edit/<int:id>", methods=["POST"])
@admin_required
def edit_color(id):
    color = Color.query.get_or_404(id)
    name, hex_code, error = validate_color_form(
        request.form.get("name"),
        request.form.get("hex_code") or request.form.get("code"),
        color_id=id
    )
    if error:
        flash(error, "error")
        return redirect("/admin/colors")

    color.name = name
    color.code = hex_code
    color.hex_code = hex_code
    db.session.commit()
    flash("Color updated successfully.", "success")
    return redirect("/admin/colors")


@app.route("/admin/colors/delete/<int:id>")
@admin_required
def delete_color(id):
    color = Color.query.get_or_404(id)
    if color_usage_count(id) > 0:
        flash("This color is used in products or orders and cannot be deleted.", "error")
        return redirect("/admin/colors")

    db.session.delete(color)
    db.session.commit()
    flash("Color deleted successfully.", "success")
    return redirect("/admin/colors")


@app.route("/admin/products/add", methods=["GET", "POST"])
@app.route("/admin/products/belts/add", methods=["GET", "POST"])
@app.route("/admin/products/wallets/add", methods=["GET", "POST"])
@admin_required
def add_product():
    product_type = normalize_product_type("wallet" if request.path.endswith("/wallets/add") else None)
    settings = product_type_settings(product_type)

    if request.method == "POST":
        errors = {}
        form_data = product_form_data()
        selected_color_ids = selected_color_ids_from_request()
        name, name_error = validate_product_name(request.form.get("name"))
        if name_error:
            errors["name"] = name_error
        size_type = normalize_size_type(request.form.get("size_type")) if settings["requires_size"] else None
        requires_size = settings["requires_size"] and size_type == "specific"
        sizes = request.form.get("sizes") if requires_size else None
        if requires_size:
            sizes, sizes_error = validate_belt_sizes(sizes)
            if sizes_error:
                errors["sizes"] = sizes_error
        show_on_homepage = bool(request.form.get("show_on_homepage"))
        homepage_sort_order = parse_int(request.form.get("homepage_sort_order"), 0)
        homepage_error = validate_homepage_selection(settings["product_type"], show_on_homepage)
        if homepage_error:
            errors["homepage"] = homepage_error

        if errors:
            colors = Color.query.order_by(Color.name.asc(), Color.id.asc()).all()
            return render_template(
                "admin/add_product.html",
                colors=colors,
                product=None,
                selected_color_ids=selected_color_ids,
                errors=errors,
                form_data=form_data,
                homepage_limit=homepage_product_limit(settings["product_type"]),
                homepage_selected_count=homepage_selection_count(settings["product_type"]),
                **settings
            )

        guarantee = request.form.get("guarantee")
        material = request.form.get("material")
        description = request.form.get("description")
        composition_care = request.form.get("composition_care")
        additional_details = request.form.get("additional_details")

        original_price = float(request.form.get("original_price", 0))
        discount_percent = float(request.form.get("discount_percent", 0))
        rating = request.form.get("rating")
        size_unit = request.form.get("size_unit", "inch") if requires_size else None

        final_price = original_price - (original_price * discount_percent / 100)

        product = Product(
            name=name,
            product_type=settings["product_type"],
            requires_size=requires_size,
            size_type=size_type,
            price=int(final_price),
            original_price=original_price,
            discount_percent=discount_percent,
            rating=float(rating) if rating else None,
            size_unit=size_unit,
            offer=f"{discount_percent}% OFF" if discount_percent > 0 else None,
            guarantee=guarantee,
            material=material,
            description=description,
            composition_care=composition_care,
            additional_details=additional_details,
            show_on_homepage=show_on_homepage,
            homepage_sort_order=homepage_sort_order
        )

        db.session.add(product)
        db.session.commit()
        if not requires_size:
            product.size_unit = None

        # =========================
        # ✅ SIZES
        # =========================
        if requires_size and sizes:
            for s in sizes.split(","):
                s = s.strip()
                if s:
                    db.session.add(ProductSize(
                        product_id=product.id,
                        size_label=s,
                        size_value=float(s)
                    ))

        # =========================
        # 🎨 COLORS + IMAGES
        # =========================
        selected_colors = request.form.getlist("colors")

        for color_id in selected_colors:

            db.session.add(ProductColor(
                product_id=product.id,
                color_id=int(color_id)
            ))

            images = request.files.getlist(f"color_images_{color_id}")

            first_for_color = False   # 🔥 IMPORTANT (per color)

            for img in images:
                if img and allowed_file(img.filename, "image"):

                    result = cloudinary.uploader.upload(
                        img,
                        folder="products/images",
                        resource_type="image"
                    )
                    image_url = result.get("secure_url")
                    print("Uploaded image URL:", image_url)

                    db.session.add(ProductImage(
                        product_id=product.id,
                        image_url=image_url,
                        color_id=int(color_id),
                        is_primary=not first_for_color   # ✅ per color primary
                    ))

                    first_for_color = True

        # =========================
        # 🔥 DEFAULT (NO COLOR)
        # =========================
        default_images = request.files.getlist("images")

        first_default = False

        for img in default_images:
            if img and allowed_file(img.filename, "image"):

                result = cloudinary.uploader.upload(
                    img,
                    folder="products/images",
                    resource_type="image"
                )
                image_url = result.get("secure_url")
                print("Uploaded image URL:", image_url)

                db.session.add(ProductImage(
                    product_id=product.id,
                    image_url=image_url,
                    color_id=None,
                    is_primary=not first_default
                ))

                first_default = True

        # =========================
        # 🎥 VIDEOS
        # =========================
        for color_id in selected_colors:
            videos = request.files.getlist(f"color_videos_{color_id}")

            for vid in videos:
                if vid and allowed_file(vid.filename, "video"):

                    result = cloudinary.uploader.upload(
                        vid,
                        resource_type="video",
                        folder="products/videos"
                    )

                    db.session.add(ProductVideo(
                        product_id=product.id,
                        video_url=result["secure_url"],
                        color_id=int(color_id)
                    ))

        # =========================
        # 🏷 TAGS
        # =========================
        tags = request.form.get("tags")
        if tags:
            for t in tags.split(","):
                db.session.add(ProductTag(
                    product_id=product.id,
                    tag=t.strip()
                ))

        db.session.commit()
        print("Product saved ID:", product.id)
        return redirect(settings["list_url"])

    # GET
    colors = Color.query.order_by(Color.name.asc(), Color.id.asc()).all()
    return render_template(
        "admin/add_product.html",
        colors=colors,
        product=None,
        selected_color_ids=[],
        errors={},
        form_data={},
        homepage_limit=homepage_product_limit(settings["product_type"]),
        homepage_selected_count=homepage_selection_count(settings["product_type"]),
        **settings
    )
@app.route("/admin/products/edit/<int:id>", methods=["GET", "POST"])
@admin_required
def edit_product(id):

    product = Product.query.get_or_404(id)
    if not product.product_type:
        product.product_type = "belt"
    if product.requires_size is None:
        product.requires_size = product.product_type == "belt"
    if not product.size_type:
        product.size_type = "specific"
    settings = product_type_settings(product.product_type)

    if request.method == "POST":
        errors = {}
        form_data = product_form_data()
        selected_color_ids = selected_color_ids_from_request()

        # =========================
        # BASIC DETAILS
        # =========================
        name, name_error = validate_product_name(request.form.get("name"))
        if name_error:
            errors["name"] = name_error
        size_type = normalize_size_type(request.form.get("size_type")) if settings["requires_size"] else None
        requires_size = settings["requires_size"] and size_type == "specific"
        sizes_text = request.form.get("sizes") if requires_size else None
        if requires_size:
            sizes_text, sizes_error = validate_belt_sizes(sizes_text)
            if sizes_error:
                errors["sizes"] = sizes_error
        show_on_homepage = bool(request.form.get("show_on_homepage"))
        homepage_sort_order = parse_int(request.form.get("homepage_sort_order"), product.homepage_sort_order or 0)
        homepage_error = validate_homepage_selection(settings["product_type"], show_on_homepage, product.id)
        if homepage_error:
            errors["homepage"] = homepage_error

        if errors:
            colors = Color.query.order_by(Color.name.asc(), Color.id.asc()).all()
            return render_template(
                "admin/edit_product.html",
                product=product,
                colors=colors,
                selected_color_ids=selected_color_ids,
                errors=errors,
                form_data=form_data,
                homepage_limit=homepage_product_limit(settings["product_type"]),
                homepage_selected_count=homepage_selection_count(settings["product_type"], product.id),
                **settings
            )

        product.name = name
        product.product_type = settings["product_type"]
        product.requires_size = requires_size
        product.size_type = size_type
        product.guarantee = request.form.get("guarantee")
        product.material = request.form.get("material")
        product.description = request.form.get("description")
        product.composition_care = request.form.get("composition_care")
        product.additional_details = request.form.get("additional_details")
        product.size_unit = request.form.get("size_unit", "inch") if requires_size else None
        product.show_on_homepage = show_on_homepage
        product.homepage_sort_order = homepage_sort_order

        # =========================
        # PRICE
        # =========================
        original_price = float(request.form.get("original_price", 0))
        discount_percent = float(request.form.get("discount_percent", 0))
        rating = request.form.get("rating")

        final_price = original_price - (original_price * discount_percent / 100)

        product.original_price = int(original_price)
        product.discount_percent = int(discount_percent)
        product.price = int(final_price)
        product.rating = float(rating) if rating else None

        product.offer = f"{discount_percent}% OFF" if discount_percent > 0 else None

        # =========================
        # COLORS RESET
        # =========================
        ProductColor.query.filter_by(product_id=id).delete()

        selected_colors = request.form.getlist("colors")

        # =========================
        # ADD COLORS + NEW IMAGES
        # =========================
        for color_id in selected_colors:

            db.session.add(ProductColor(
                product_id=id,
                color_id=int(color_id)
            ))

            images = request.files.getlist(f"color_images_{color_id}")

            for img in images:
                if img and allowed_file(img.filename, "image"):

                    result = cloudinary.uploader.upload(
                        img,
                        folder="products/images",
                        resource_type="image"
                    )
                    image_url = result.get("secure_url")
                    print("Uploaded image URL:", image_url)

                    db.session.add(ProductImage(
                        product_id=id,
                        image_url=image_url,
                        color_id=int(color_id),
                        is_primary=False
                    ))

        # =========================
        # DEFAULT IMAGES (NO COLOR)
        # =========================
        default_images = request.files.getlist("images")

        for img in default_images:
            if img and allowed_file(img.filename, "image"):

                result = cloudinary.uploader.upload(
                    img,
                    folder="products/images",
                    resource_type="image"
                )
                image_url = result.get("secure_url")
                print("Uploaded image URL:", image_url)

                db.session.add(ProductImage(
                    product_id=id,
                    image_url=image_url,
                    color_id=None,
                    is_primary=False
                ))

        # =========================
        # 🔥 ENSURE PRIMARY PER COLOR
        # =========================
        colors = ProductColor.query.filter_by(product_id=id).all()

        for pc in colors:

            primary = ProductImage.query.filter_by(
                product_id=id,
                color_id=pc.color_id,
                is_primary=True
            ).first()

            if not primary:
                first_img = ProductImage.query.filter_by(
                    product_id=id,
                    color_id=pc.color_id
                ).first()

                if first_img:
                    first_img.is_primary = True

        # =========================
        # 🔥 DEFAULT PRIMARY (NO COLOR)
        # =========================
        no_color_primary = ProductImage.query.filter_by(
            product_id=id,
            color_id=None,
            is_primary=True
        ).first()

        if not no_color_primary:
            first_img = ProductImage.query.filter_by(
                product_id=id,
                color_id=None
            ).first()

            if first_img:
                first_img.is_primary = True

        # =========================
        # VIDEOS
        # =========================
        for color_id in selected_colors:

            videos = request.files.getlist(f"color_videos_{color_id}")

            for vid in videos:
                if vid and allowed_file(vid.filename, "video"):

                    result = cloudinary.uploader.upload(
                        vid,
                        resource_type="video",
                        folder="products/videos"
                    )

                    db.session.add(ProductVideo(
                        product_id=id,
                        video_url=result["secure_url"],
                        color_id=int(color_id)
                    ))

        # =========================
        # SIZES
        # =========================
        # NOTE: Only update sizes if the sizes field was actually submitted.
        # This prevents accidentally deleting sizes when editing other fields
        # like description, composition_care, additional_details, etc.
        if requires_size and sizes_text is not None:
            existing_sizes = ProductSize.query.filter_by(product_id=id).all()
            old_labels = ",".join([s.size_label for s in existing_sizes])
            if sizes_text != old_labels:
                # Only clear cart if sizes actually changed
                Cart.query.filter_by(product_id=id).delete()
                # Delete and recreate sizes only when changed
                ProductSize.query.filter_by(product_id=id).delete()
                if sizes_text:
                    for s in sizes_text.split(","):
                        s = s.strip()
                        if s:
                            db.session.add(ProductSize(
                                product_id=id,
                                size_label=s,
                                size_value=float(s)
                            ))
        elif not requires_size:
            clear_wallet_cart_sizes(id)
            ProductSize.query.filter_by(product_id=id).delete()
        # If a belt request omits sizes_text, keep existing sizes unchanged.

        # =========================
        # TAGS
        # =========================
        if "tags" in request.form:
            update_product_tags_if_changed(id, request.form.get("tags"))

        # =========================
        # SAVE
        # =========================
        db.session.commit()

        return redirect(settings["list_url"])

    # GET
    colors = Color.query.order_by(Color.name.asc(), Color.id.asc()).all()

    return render_template(
        "admin/edit_product.html",
        product=product,
        colors=colors,
        errors={},
        form_data={},
        homepage_limit=homepage_product_limit(settings["product_type"]),
        homepage_selected_count=homepage_selection_count(settings["product_type"], product.id),
        **settings
    )

@app.route("/admin/products/delete/<int:id>")
@admin_required
def delete_product(id):

    product = Product.query.get_or_404(id)

    try:
        # ✅ Remove cart and wishlist first
        db.session.execute(text("DELETE FROM cart WHERE product_id = :pid"), {"pid": id})
        db.session.execute(text("DELETE FROM wishlist WHERE product_id = :pid"), {"pid": id})

        # ✅ Remove reviews
        db.session.execute(text("DELETE FROM reviews WHERE product_id = :pid"), {"pid": id})

        # ✅ Remove from order items also
        # WARNING: old orders will not show this product item after this
        db.session.execute(text("DELETE FROM order_items WHERE product_id = :pid"), {"pid": id})

        # ✅ Remove product child data
        db.session.execute(text("DELETE FROM product_tags WHERE product_id = :pid"), {"pid": id})
        db.session.execute(text("DELETE FROM product_colors WHERE product_id = :pid"), {"pid": id})
        db.session.execute(text("DELETE FROM product_sizes WHERE product_id = :pid"), {"pid": id})
        db.session.execute(text("DELETE FROM product_images WHERE product_id = :pid"), {"pid": id})
        db.session.execute(text("DELETE FROM product_videos WHERE product_id = :pid"), {"pid": id})

        # ✅ Finally delete product
        db.session.delete(product)
        db.session.commit()

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "product_id": id,
                "message": "Product permanently deleted successfully"
            })

        return redirect_to_product_list(product)

    except Exception as e:
        db.session.rollback()
        app.logger.error("Product delete failed for product %s: %s", id, e)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "message": "Product delete failed. Please check logs."
            }), 500

        return """
        <script>
            alert("❌ Product delete failed. Please check logs.");
            window.location.href = "/admin/products";
        </script>
        """


@app.route("/admin/products/archive/<int:id>")
@admin_required
def archive_product(id):

    product = Product.query.get_or_404(id)
    product.is_archived = True
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "product_id": id,
            "is_archived": True,
            "message": "Product archived successfully"
        })

    flash("Product archived successfully", "success")
    return redirect_to_product_list(product)


@app.route("/admin/products/unarchive/<int:id>")
@admin_required
def unarchive_product(id):

    product = Product.query.get_or_404(id)
    product.is_archived = False
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "product_id": id,
            "is_archived": False,
            "message": "Product unarchived successfully"
        })

    flash("Product unarchived successfully", "success")
    return redirect_to_product_list(product)

@app.route("/admin/video/delete/<int:id>")
@admin_required
def delete_video(id):
    video = ProductVideo.query.get_or_404(id)

    db.session.delete(video)
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": id, "message": "Video deleted"})

    return redirect(request.referrer)

@app.route("/admin/image/delete/<int:id>")
@admin_required
def delete_image(id):
    image = ProductImage.query.get_or_404(id)
    product_id = image.product_id
    color_id = image.color_id
    was_primary = image.is_primary

    db.session.delete(image)
    db.session.flush()

    if was_primary:
        replacement = ProductImage.query.filter_by(
            product_id=product_id,
            color_id=color_id
        ).order_by(ProductImage.id).first()
        if replacement:
            replacement.is_primary = True

    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": id, "message": "Image deleted"})

    return redirect(request.referrer)

@app.route("/admin/image/primary/<int:id>")
@admin_required
def set_primary_image(id):
    image = ProductImage.query.get_or_404(id)

    # 🔥 ONLY same color reset
    ProductImage.query.filter_by(
        product_id=image.product_id,
        color_id=image.color_id
    ).update({"is_primary": False})

    image.is_primary = True

    db.session.commit()

    return redirect(request.referrer)


def generate_slug(title, blog_id=None):
    base_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not base_slug:
        base_slug = uuid.uuid4().hex[:8]
    slug = base_slug
    counter = 1

    while True:
        existing = Blog.query.filter_by(slug=slug).first()
        if not existing or existing.id == blog_id:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


def get_blog_date_from_form():
    blog_date_value = (request.form.get("blog_date") or "").strip()
    if blog_date_value:
        try:
            return datetime.strptime(blog_date_value, "%Y-%m-%d").date()
        except ValueError:
            return date.today()
    return date.today()

# 📚 All Blogs (Admin Panel)
@app.route('/admin/blogs')
@admin_required
def admin_blogs():
    blogs = Blog.query.order_by(
        Blog.blog_date.is_(None),
        Blog.blog_date.desc(),
        Blog.created_at.is_(None),
        Blog.created_at.desc(),
        Blog.id.desc()
    ).all()
    categories = Category.query.all()

    return render_template(
        "admin/blogs.html",
        blogs=blogs,
        categories=categories
    )

# ➕ Add Blog
@app.route('/admin/blogs/add', methods=['GET', 'POST'])
@admin_required
def add_blog():

    categories =  Category.query.all()
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        author = request.form['author']


        category_id = request.form.get('category')
        seo_title = request.form.get('seo_title') or title
        seo_description = request.form.get('seo_description') or content[:150]
        blog_date = get_blog_date_from_form()
        # 🔥 SEO Friendly Slug
        slug = generate_slug(title)

        # 🔥 Image Upload
        file = request_blog_image_file()

        image_filename = save_blog_image(file)
        app.logger.info("Blog cover image saved: %s", image_filename)


        tag_names = request.form.get('tags', "").split(",")

        tag_objects = []
        for tag in tag_names:
            tag = tag.strip().lower()
            if tag:
                existing = Tag.query.filter_by(name=tag).first()
                if existing:
                    tag_objects.append(existing)
                else:
                    new_tag = Tag(name=tag)
                    db.session.add(new_tag)
                    tag_objects.append(new_tag)


        new_blog = Blog(
            title=title,
            slug=slug,
            content=content,
            image=image_filename,
            author=author,
            category_id=category_id,
            seo_title=seo_title,
            seo_description=seo_description,
            tags=tag_objects,
            blog_date=blog_date,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_published=True
        )

        db.session.add(new_blog)
        db.session.commit()

        return redirect('/admin/blogs')

    return render_template("admin/add_blog.html")


# ✏️ Edit Blog
@app.route('/admin/blogs/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_blog(id):
    blog = Blog.query.get_or_404(id)
    categories =  Category.query.all()
    if request.method == 'POST':
        blog.title = request.form['title']
        blog.content = request.form['content']
        blog.author = request.form['author']


        blog.category_id = request.form.get('category')
        blog.seo_title = request.form.get('seo_title') or blog.title
        blog.seo_description = request.form.get('seo_description') or blog.content[:150]
        blog.blog_date = get_blog_date_from_form()

        blog.slug=generate_slug(blog.title, blog.id)

        # 🔥 Image update
        file = request_blog_image_file()
        image_filename = save_blog_image(file)
        if image_filename:
            blog.image = image_filename
            app.logger.info("Blog %s cover image updated: %s", blog.id, image_filename)
         

        tag_names = request.form.get('tags', "").split(",")
        blog.tags.clear()

        for tag in tag_names:
            tag = tag.strip().lower()
            if tag:
                existing = Tag.query.filter_by(name=tag).first()
                if existing:
                    blog.tags.append(existing)
                else:
                    new_tag = Tag(name=tag)
                    db.session.add(new_tag)
                    blog.tags.append(new_tag)

                
        blog.is_published = True if request.form.get('is_published') else False
        blog.updated_at = datetime.utcnow()

        db.session.commit()
        return redirect('/admin/blogs')

    return render_template("admin/edit_blog.html", blog=blog)


# 🗑 Delete Blog
@app.route('/admin/blogs/delete/<int:id>')
@admin_required
def delete_blog(id):
    blog = Blog.query.get_or_404(id)

    # optional: delete image file
    

    db.session.delete(blog)
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "blog_id": id,
            "message": "Blog deleted successfully"
        })

    return redirect('/admin/blogs')

@app.route('/upload-image', methods=['POST'])
@admin_required
def upload_image():
    file = request.files.get('image')

    if not file:
        return jsonify({"error": "No file"}), 400
    
    result = cloudinary.uploader.upload(file)

    return jsonify({
        "url": result["secure_url"]
    })




@app.route('/admin/orders')
@admin_required
def admin_orders():
    status_filter = (request.args.get("status") or "").strip()
    payment_filter = (request.args.get("payment_status") or "").strip()

    query = Order.query
    if status_filter:
        query = query.filter(Order.order_status == status_filter)
    if payment_filter:
        query = query.filter(Order.payment_status == payment_filter)

    orders = query.order_by(Order.id.desc()).all()
    return render_template(
        "admin/orders.html",
        orders=orders,
        status_filter=status_filter,
        payment_filter=payment_filter
    )


def coupon_form_payload():
    code = (request.form.get("code") or "").strip().upper()
    coupon_type = (request.form.get("coupon_type") or "fixed_amount").strip().lower()
    allowed_coupon_types = {
        "fixed_amount",
        "percentage",
        "first_order_discount",
        "buy_x_fixed_payable",
        "buy_x_get_y_discount",
        "category_based_discount",
        "product_based_discount",
        "cart_total_based_discount",
    }
    if coupon_type not in allowed_coupon_types:
        coupon_type = "fixed_amount"

    discount_type = (request.form.get("discount_type") or "fixed").strip().lower()
    if discount_type not in ("fixed", "percent"):
        discount_type = "fixed"

    per_user_limit = parse_optional_int(request.form.get("per_user_limit"))
    if per_user_limit is None:
        per_user_limit = 1

    selected_product_ids = []
    for product_id in request.form.getlist("applicable_product_ids"):
        parsed_id = parse_optional_int(product_id)
        if parsed_id:
            selected_product_ids.append(parsed_id)

    first_order_only = bool(request.form.get("first_order_only")) or coupon_type == "first_order_discount"

    return {
        "code": code,
        "title": (request.form.get("title") or "").strip() or None,
        "description": (request.form.get("description") or "").strip() or None,
        "coupon_type": coupon_type,
        "discount_type": discount_type,
        "discount_value": float(request.form.get("discount_value") or 0),
        "min_order_amount": parse_optional_float(request.form.get("min_order_amount")),
        "max_discount_amount": parse_optional_float(request.form.get("max_discount_amount")),
        "applicable_category_id": parse_optional_int(request.form.get("applicable_category_id")),
        "applicable_category": normalize_coupon_category(request.form.get("applicable_category")),
        "selected_product_ids": selected_product_ids,
        "min_quantity_required": parse_optional_int(request.form.get("min_quantity_required")),
        "required_product_price": parse_optional_float(request.form.get("required_product_price")),
        "final_payable_amount": parse_optional_float(request.form.get("final_payable_amount")),
        "valid_from": parse_optional_date(request.form.get("valid_from")),
        "valid_until": parse_optional_date(request.form.get("valid_until")),
        "usage_limit": parse_optional_int(request.form.get("usage_limit")),
        "per_user_limit": per_user_limit,
        "first_order_only": first_order_only,
        "one_time_per_customer": bool(request.form.get("one_time_per_customer")),
        "show_on_product_page": bool(request.form.get("show_on_product_page")),
        "product_page_priority": parse_optional_int(request.form.get("product_page_priority")) or 0,
        "auto_apply": bool(request.form.get("auto_apply")),
        "allow_combination": bool(request.form.get("allow_combination")),
        "is_active": bool(request.form.get("is_active")),
    }


def apply_coupon_payload(coupon, payload):
    coupon.code = payload["code"]
    coupon.title = payload["title"]
    coupon.description = payload["description"]
    coupon.coupon_type = payload["coupon_type"]
    coupon.discount_type = payload["discount_type"]
    coupon.discount_value = payload["discount_value"]
    coupon.min_order_amount = payload["min_order_amount"]
    coupon.max_discount_amount = payload["max_discount_amount"]
    coupon.applicable_category_id = payload["applicable_category_id"]
    coupon.applicable_category = payload["applicable_category"]
    coupon.min_quantity_required = payload["min_quantity_required"]
    coupon.required_product_price = payload["required_product_price"]
    coupon.final_payable_amount = payload["final_payable_amount"]
    coupon.valid_from = payload["valid_from"]
    coupon.valid_until = payload["valid_until"]
    coupon.usage_limit = payload["usage_limit"]
    coupon.per_user_limit = payload["per_user_limit"]
    coupon.first_order_only = payload["first_order_only"]
    coupon.one_time_per_customer = payload["one_time_per_customer"]
    coupon.show_on_product_page = payload["show_on_product_page"]
    coupon.product_page_priority = payload["product_page_priority"]
    coupon.auto_apply = payload["auto_apply"]
    coupon.allow_combination = payload["allow_combination"]
    coupon.is_active = payload["is_active"]
    coupon.applicable_products = Product.query.filter(Product.id.in_(payload["selected_product_ids"])).all() if payload["selected_product_ids"] else []
    coupon.updated_at = datetime.utcnow()


def coupon_form_context(coupon=None, form_data=None):
    if form_data:
        selected_product_ids = [
            int(product_id)
            for product_id in form_data.getlist("applicable_product_ids")
            if str(product_id).isdigit()
        ]
    elif coupon:
        selected_product_ids = [product.id for product in coupon.applicable_products]
    else:
        selected_product_ids = []

    return {
        "coupon": coupon,
        "form_data": form_data or {},
        "products": Product.query.filter(
            db.or_(Product.is_archived == False, Product.is_archived.is_(None))
        ).order_by(Product.product_type.asc(), Product.name.asc()).all(),
        "categories": Category.query.order_by(Category.name.asc()).all(),
        "selected_product_ids": selected_product_ids,
    }


@app.route('/admin/coupons')
@admin_required
def admin_coupons():
    coupons = Coupon.query.order_by(Coupon.created_at.desc(), Coupon.id.desc()).all()
    return render_template("admin/coupons.html", coupons=coupons, coupon_usage_count=coupon_usage_count)


@app.route('/admin/coupons/add', methods=['GET', 'POST'])
@admin_required
def admin_add_coupon():
    if request.method == 'POST':
        try:
            payload = coupon_form_payload()
        except ValueError:
            flash("Please enter valid coupon values.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(None, request.form))

        if not payload["code"]:
            flash("Coupon code is required.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(None, request.form))

        if payload["coupon_type"] == "buy_x_fixed_payable":
            if not payload["min_quantity_required"] or payload["final_payable_amount"] is None:
                flash("Minimum quantity and final payable amount are required for Buy X fixed payable coupons.", "error")
                return render_template("admin/coupon_form.html", **coupon_form_context(None, request.form))
        elif payload["discount_value"] <= 0:
            flash("Discount value is required.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(None, request.form))

        existing = Coupon.query.filter(db.func.upper(Coupon.code) == payload["code"]).first()
        if existing:
            flash("Coupon code already exists. Please edit the existing coupon instead.", "error")
            return redirect(url_for("admin_edit_coupon", coupon_id=existing.id))

        coupon = Coupon()
        apply_coupon_payload(coupon, payload)
        db.session.add(coupon)
        db.session.commit()
        flash("Coupon created successfully.", "success")
        return redirect(url_for("admin_coupons"))

    return render_template("admin/coupon_form.html", **coupon_form_context())


@app.route('/admin/coupons/edit/<int:coupon_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if request.method == 'POST':
        try:
            payload = coupon_form_payload()
        except ValueError:
            flash("Please enter valid coupon values.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(coupon, request.form))

        duplicate = Coupon.query.filter(
            db.func.upper(Coupon.code) == payload["code"],
            Coupon.id != coupon.id
        ).first()
        if duplicate:
            flash("Coupon code already exists. Please edit the existing coupon instead.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(coupon, request.form))

        if not payload["code"]:
            flash("Coupon code is required.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(coupon, request.form))

        if payload["coupon_type"] == "buy_x_fixed_payable":
            if not payload["min_quantity_required"] or payload["final_payable_amount"] is None:
                flash("Minimum quantity and final payable amount are required for Buy X fixed payable coupons.", "error")
                return render_template("admin/coupon_form.html", **coupon_form_context(coupon, request.form))
        elif payload["discount_value"] <= 0:
            flash("Discount value is required.", "error")
            return render_template("admin/coupon_form.html", **coupon_form_context(coupon, request.form))

        apply_coupon_payload(coupon, payload)
        db.session.commit()
        flash("Coupon updated successfully.", "success")
        return redirect(url_for("admin_coupons"))

    return render_template("admin/coupon_form.html", **coupon_form_context(coupon))


@app.route('/admin/coupons/toggle/<int:coupon_id>')
@admin_required
def admin_toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    coupon.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("admin_coupons"))


@app.route('/admin/coupons/delete/<int:coupon_id>')
@admin_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if coupon_usage_count(coupon.id) > 0 or int(coupon.used_count or 0) > 0:
        coupon.is_active = False
        coupon.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Coupon has usage history, so it was deactivated instead of deleted.", "success")
    else:
        db.session.delete(coupon)
        db.session.commit()
        flash("Coupon deleted successfully.", "success")
    return redirect(url_for("admin_coupons"))


FALLBACK_HERO_SLIDES = {
    1: "/static/images/herosection1.png",
    2: "/static/images/herosection2.png",
    3: "/static/images/herosection3.png",
}

FALLBACK_STYLE_VIDEOS = {
    1: "/static/images/videoplayback (1).mp4",
    2: "/static/images/videoplayback (2).mp4",
    3: "/static/images/videoplayback (1).mp4",
    4: "/static/images/videoplayback (2).mp4",
}

FALLBACK_AUTO_SLIDER_IMAGES = {
    1: "/static/images/20260413_153959.jpg",
    2: "/static/images/20260413_180520.jpg",
    3: "/static/images/20260413_175128.jpg",
    4: "/static/images/download (3).jpg",
    5: "/static/images/download (4).jpg",
    6: "/static/images/Feathered Edge Bridle Leather Belts.jpg",
}

FALLBACK_AUTO_SLIDER_ALT_TEXT = {
    1: "Textured formal leather belt from Belt Purse Store",
    2: "Carbon fiber design mens belt with premium buckle",
    3: "Glossy dot texture designer belt for formal wear",
    4: "Premium leather belt accessory collection",
    5: "Stylish belt and wallet accessory collection",
    6: "Feathered edge bridle leather belts",
}


def homepage_media_config(media_type):
    configs = {
        "hero_image": {
            "fallback_map": FALLBACK_HERO_SLIDES,
            "minimum_extra_position": 4,
            "label": "Hero image",
            "extra_label": "hero slide",
        },
        "style_video": {
            "fallback_map": FALLBACK_STYLE_VIDEOS,
            "minimum_extra_position": 5,
            "label": "Crafted video",
            "extra_label": "crafted video",
        },
        "auto_slider_image": {
            "fallback_map": FALLBACK_AUTO_SLIDER_IMAGES,
            "minimum_extra_position": 7,
            "label": "Auto slider image",
            "extra_label": "auto slider image",
        },
    }
    return configs.get(media_type)


def homepage_media_position_records(media_type):
    records = HomepageMedia.query.filter_by(media_type=media_type).order_by(
        HomepageMedia.sort_order.asc(), HomepageMedia.id.asc()
    ).all()
    by_position = {}
    for media in records:
        position = int(media.sort_order or 0)
        if position <= 0:
            position = media.id or 0
        if position not in by_position:
            by_position[position] = media
    return by_position


def homepage_media_cards(media_type, fallback_map):
    by_position = homepage_media_position_records(media_type)
    positions = sorted(set(fallback_map.keys()) | set(by_position.keys()))
    cards = []
    for position in positions:
        media = by_position.get(position)
        fallback_url = fallback_map.get(position)
        uses_fallback = media is None or bool(media and fallback_url and media.media_url == fallback_url and not media.public_id)
        cards.append({
            "position": position,
            "media": media,
            "preview_url": media.media_url if media and media.media_url else fallback_url,
            "mobile_preview_url": media.mobile_media_url if media and media.mobile_media_url else None,
            "is_fallback": uses_fallback,
            "is_active": True if media is None else bool(media.is_active),
            "has_fallback": fallback_url is not None,
        })
    return cards


def next_homepage_media_position(media_type, minimum_position):
    max_position = db.session.query(db.func.max(HomepageMedia.sort_order)).filter_by(
        media_type=media_type
    ).scalar()
    return max(int(max_position or 0) + 1, minimum_position)


def find_homepage_media_position(media_type, position):
    return HomepageMedia.query.filter_by(media_type=media_type, sort_order=position).order_by(
        HomepageMedia.id.asc()
    ).first()


def deactivate_duplicate_homepage_positions(media):
    duplicates = HomepageMedia.query.filter(
        HomepageMedia.media_type == media.media_type,
        HomepageMedia.sort_order == media.sort_order,
        HomepageMedia.id != media.id
    ).all()
    for duplicate in duplicates:
        duplicate.is_active = False
        duplicate.updated_at = datetime.utcnow()


def build_homepage_slides(media_type, fallback_map, include_fallback=True, fallback_alt_text=None):
    by_position = homepage_media_position_records(media_type)
    positions = sorted(set(fallback_map.keys()) | set(by_position.keys()))
    slides = []
    for position in positions:
        media = by_position.get(position)
        if media:
            if media.is_active and media.media_url:
                slides.append(media)
            continue

        fallback_url = fallback_map.get(position)
        if include_fallback and fallback_url:
            slides.append({
                "media_url": fallback_url,
                "mobile_media_url": None,
                "alt_text": (fallback_alt_text or {}).get(position, "Homepage media"),
                "title": None,
                "subtitle": None,
                "button_text": None,
                "button_link": None,
                "sort_order": position,
            })
    return slides


@app.route('/admin/homepage-media')
@admin_required
def admin_homepage_media():
    hero_cards = homepage_media_cards("hero_image", FALLBACK_HERO_SLIDES)
    video_cards = homepage_media_cards("style_video", FALLBACK_STYLE_VIDEOS)
    auto_slider_cards = homepage_media_cards("auto_slider_image", FALLBACK_AUTO_SLIDER_IMAGES)
    return render_template(
        "admin/homepage_media.html",
        hero_cards=hero_cards,
        video_cards=video_cards,
        auto_slider_cards=auto_slider_cards,
        auto_slider_fallback_alt_text=FALLBACK_AUTO_SLIDER_ALT_TEXT,
    )


@app.route('/admin/homepage-media/update/<media_type>/<int:position>', methods=['POST'])
@admin_required
def admin_update_homepage_media_position(media_type, position):
    config = homepage_media_config(media_type)
    if not config or position < 1:
        abort(404)

    media_file = request.files.get("media_file")
    media = find_homepage_media_position(media_type, position)
    is_active = bool(request.form.get("is_active"))
    fallback_map = config["fallback_map"]
    fallback_url = fallback_map.get(position)

    if not media:
        if not media_file or not media_file.filename:
            if not fallback_url:
                flash("Please choose a file to replace this position.", "error")
                return redirect(url_for("admin_homepage_media"))
            media = HomepageMedia(media_type=media_type, sort_order=position, media_url=fallback_url)
        else:
            media = HomepageMedia(media_type=media_type, sort_order=position)
        db.session.add(media)

    if media_file and media_file.filename:
        media_url, public_id = save_homepage_media_file(media_file, media_type)
        if not media_url:
            flash("Please upload a valid image/video file.", "error")
            return redirect(url_for("admin_homepage_media"))
        media.media_url = media_url
        media.public_id = public_id

    if media_type == "hero_image":
        mobile_file = request.files.get("mobile_media_file")
        if mobile_file and mobile_file.filename:
            mobile_url, mobile_public_id = save_homepage_media_file(mobile_file, media_type)
            if not mobile_url:
                flash("Please upload a valid mobile image file.", "error")
                return redirect(url_for("admin_homepage_media"))
            media.mobile_media_url = mobile_url
            media.mobile_public_id = mobile_public_id

    media.media_type = media_type
    media.sort_order = position
    media.title = None
    media.subtitle = None
    media.button_text = None
    media.button_link = None
    media.alt_text = (request.form.get("alt_text") or "").strip() or None if media_type == "auto_slider_image" else None
    media.is_active = is_active
    media.updated_at = datetime.utcnow()
    db.session.flush()
    deactivate_duplicate_homepage_positions(media)
    db.session.commit()
    flash(f"{config['label']} position {position} updated.", "success")
    return redirect(url_for("admin_homepage_media"))


@app.route('/admin/homepage-media/add-extra/<media_type>', methods=['POST'])
@admin_required
def admin_add_extra_homepage_media(media_type):
    config = homepage_media_config(media_type)
    if not config:
        abort(404)

    minimum_position = config["minimum_extra_position"]
    try:
        requested_position = int(request.form.get("position") or 0)
    except ValueError:
        requested_position = 0
    position = requested_position if requested_position >= minimum_position else next_homepage_media_position(media_type, minimum_position)

    if find_homepage_media_position(media_type, position):
        flash(f"Position {position} already exists. Change that position instead.", "error")
        return redirect(url_for("admin_homepage_media"))

    media_file = request.files.get("media_file")
    media_url, public_id = save_homepage_media_file(media_file, media_type)
    if not media_url:
        flash("Please upload a valid image/video file.", "error")
        return redirect(url_for("admin_homepage_media"))

    media = HomepageMedia(
        media_type=media_type,
        media_url=media_url,
        public_id=public_id,
        alt_text=(request.form.get("alt_text") or "").strip() or None if media_type == "auto_slider_image" else None,
        sort_order=position,
        is_active=bool(request.form.get("is_active")),
    )
    if media_type == "hero_image":
        mobile_file = request.files.get("mobile_media_file")
        if mobile_file and mobile_file.filename:
            mobile_url, mobile_public_id = save_homepage_media_file(mobile_file, media_type)
            if not mobile_url:
                flash("Please upload a valid mobile image file.", "error")
                return redirect(url_for("admin_homepage_media"))
            media.mobile_media_url = mobile_url
            media.mobile_public_id = mobile_public_id
    db.session.add(media)
    db.session.commit()
    flash(f"Extra {config['extra_label']} added at position {position}.", "success")
    return redirect(url_for("admin_homepage_media"))


@app.route('/admin/homepage-media/move/<int:media_id>', methods=['POST'])
@admin_required
def admin_move_homepage_media(media_id):
    media = HomepageMedia.query.get_or_404(media_id)
    config = homepage_media_config(media.media_type)
    if not config:
        abort(404)
    try:
        new_position = int(request.form.get("position") or media.sort_order or 0)
    except ValueError:
        flash("Please enter a valid position.", "error")
        return redirect(url_for("admin_homepage_media"))

    minimum_position = config["minimum_extra_position"]
    if new_position < minimum_position:
        flash(f"Extra media position must be {minimum_position} or higher.", "error")
        return redirect(url_for("admin_homepage_media"))

    existing = find_homepage_media_position(media.media_type, new_position)
    if existing and existing.id != media.id:
        flash(f"Position {new_position} already exists. Update that position instead.", "error")
        return redirect(url_for("admin_homepage_media"))

    media.sort_order = new_position
    media.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Position updated successfully.", "success")
    return redirect(url_for("admin_homepage_media"))


@app.route('/admin/homepage-media/add/<media_type>', methods=['GET', 'POST'])
@admin_required
def admin_add_homepage_media(media_type):
    return redirect(url_for("admin_homepage_media"))


@app.route('/admin/homepage-media/edit/<int:media_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_homepage_media(media_id):
    return redirect(url_for("admin_homepage_media"))


@app.route('/admin/homepage-media/toggle/<int:media_id>')
@admin_required
def admin_toggle_homepage_media(media_id):
    media = HomepageMedia.query.get_or_404(media_id)
    media.is_active = not media.is_active
    media.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("admin_homepage_media"))


@app.route('/admin/homepage-media/delete/<int:media_id>')
@admin_required
def admin_delete_homepage_media(media_id):
    media = HomepageMedia.query.get_or_404(media_id)
    db.session.delete(media)
    db.session.commit()
    flash("Homepage media deleted successfully.", "success")
    return redirect(url_for("admin_homepage_media"))

@app.route('/admin/orders/<int:id>')
@admin_required
def order_detail(id):
    order = Order.query.get_or_404(id)
    items = OrderItem.query.filter_by(order_id=id).all()
    address = Address.query.get(order.address_id) if order.address_id else None
    return render_template("admin/order_detail.html", order=order, items=items, address=address)


@app.route('/admin/order/<int:id>')
@admin_required
def order_detail_legacy(id):
    return redirect(url_for("order_detail", id=id))

@app.route('/admin/orders/update/<int:id>', methods=['POST'])
@admin_required
def update_order(id):
    order = Order.query.get_or_404(id)

    previous_status = order.order_status or order.status
    previous_tracking = order.tracking_number
    previous_courier = order.courier_partner
    previous_tracking_url = order.tracking_url
    order.status = request.form['status']
    order.order_status = request.form['status']
    order.tracking_number = (request.form.get('tracking_number') or '').strip() or None
    order.courier_partner = (request.form.get('courier_partner') or '').strip() or None
    order.tracking_url = (request.form.get('tracking_url') or '').strip() or None

    db.session.commit()

    if order.user and order.user.email and (
        previous_status != order.order_status
        or previous_tracking != order.tracking_number
        or previous_courier != order.courier_partner
        or previous_tracking_url != order.tracking_url
    ):
        send_order_status_email(order)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "order_id": order.id,
            "status": order.order_status,
            "tracking_number": order.tracking_number or "",
            "courier_partner": order.courier_partner or "",
            "tracking_url": order.tracking_url or "",
            "message": "Order updated successfully"
        })

    return redirect('/admin/orders')

@app.route('/my-orders')
def my_orders():
    user_id = session.get('user_id')
    if not user_id and 'email' in session:
        user = User.query.filter_by(email=session['email']).first()
        user_id = user.id if user else None

    if not user_id:
        return redirect('/?show_login=1')

    orders = Order.query.filter_by(user_id=user_id).order_by(Order.created_at.desc()).all()

    return render_template("user/orders.html", orders=orders)


def create_order(user_id, cart_items, address_id):

    total = sum(item['price'] * item['qty'] for item in cart_items)

    order = Order(
        user_id=user_id,
        address_id=address_id,
        total_amount=total,
        subtotal_amount=total,
        discount_amount=0,
        final_amount=total,
        status="Placed"
    )

    db.session.add(order)
    db.session.commit()

    # add items
    for item in cart_items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item['id'],
            quantity=item['qty'],
            price=item['price']
        )
        db.session.add(order_item)

    db.session.commit()

    return order.id


@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.order_by(User.id.desc()).all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/issues")
@admin_required
def admin_issues():
    tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    return render_template("admin/issues.html", tickets=tickets)


@app.route("/admin/warranty")
@admin_required
def admin_warranty():
    warranty_claims = Warranty.query.order_by(Warranty.created_at.desc()).all()
    return render_template("admin/warranty.html", warranty_claims=warranty_claims)

# Fetch orders for modal
@app.route("/admin/users/<int:user_id>/orders")
@admin_required
def admin_user_orders(user_id):
    orders = Order.query.filter_by(user_id=user_id).order_by(Order.id.desc()).all()
    order_list = []
    for o in orders:
        order_list.append({
            "id": o.id,
            "total_amount": o.total_amount,
            "status": o.order_status or o.status,
            "payment_status": o.payment_status,
            "created_at": o.created_at.strftime("%Y-%m-%d %H:%M"),
            "tracking_number": o.tracking_number,
            "courier_partner": o.courier_partner,
            "tracking_url": o.tracking_url
        })
    return jsonify({"orders": order_list})

# Toggle active/deactive user
@app.route("/admin/users/toggle/<int:user_id>")
@admin_required
def admin_toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if not user.is_admin:  # never toggle admin
        user.is_active = not getattr(user, 'is_active', True)
        db.session.commit()
    return redirect("/admin/users")


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():

    admin = User.query.filter_by(email=session.get("email")).first()

    if not admin:
        return redirect("/admin-login")

    if request.method == "POST":

        # ======================
        # BASIC UPDATE
        # ======================
        username = request.form.get("username")
        email = request.form.get("email")

        admin.username = username
        admin.email = email

        # ⚠️ session email bhi update karna important hai
        session["email"] = email

        # ======================
        # PASSWORD CHANGE
        # ======================
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if current_password or new_password or confirm_password:

            # ❌ check current password
            if not check_password_hash(admin.password, current_password):
                return """
                <script>
                    alert("❌ Current password incorrect");
                    window.location.href="/admin/settings";
                </script>
                """

            # ❌ match new passwords
            if new_password != confirm_password:
                return """
                <script>
                    alert("❌ Passwords do not match");
                    window.location.href="/admin/settings";
                </script>
                """

            # ✅ update password
            admin.password = generate_password_hash(new_password)

        db.session.commit()

        return """
        <script>
            alert("✅ Settings updated successfully");
            window.location.href="/admin/settings";
        </script>
        """

    return render_template("admin/settings.html", admin=admin)
# ================= HOME =================

@app.route("/", methods=["GET", "POST"])
def home():
    hero_slides = build_homepage_slides("hero_image", FALLBACK_HERO_SLIDES)
    style_videos = build_homepage_slides("style_video", FALLBACK_STYLE_VIDEOS)
    auto_slider_images = build_homepage_slides(
        "auto_slider_image",
        FALLBACK_AUTO_SLIDER_IMAGES,
        fallback_alt_text=FALLBACK_AUTO_SLIDER_ALT_TEXT,
    )

    return render_template(
        "index.html",
        hero_slides=hero_slides,
        style_videos=style_videos,
        auto_slider_images=auto_slider_images,
        index_belts_limit=int(app.config.get("INDEX_BELTS_LIMIT", 3)),
        index_wallets_limit=int(app.config.get("INDEX_WALLETS_LIMIT", 5)),
        index_mobile_products_limit=int(app.config.get("INDEX_MOBILE_PRODUCTS_LIMIT", 4)),
    )


@app.route("/about")
def about():
    return render_template("about.html")


    
# ================= REGISTER =================
from werkzeug.security import generate_password_hash

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}

    if not data:
        return jsonify({"message": "No data received"}), 400

    if not all(k in data for k in ("name", "email", "password")):
        return jsonify({"message": "Missing fields"}), 400
    if len(data['password']) < 6:
      return jsonify({"message": "Password too short"}), 400
    existing_user = User.query.filter_by(username=data['name']).first()

    if existing_user:
       return jsonify({"message": "Username already exists"}), 400

    existing_email = User.query.filter_by(email=data['email']).first()
    if existing_email:
        return jsonify({"message": "Email already registered"}), 400

    # ✅ HASH PASSWORD
    hashed_password = generate_password_hash(data['password'])

    user = User(
        username=data['name'],
        email=data['email'],
        password=hashed_password   # ✅ FIXED
    )

    db.session.add(user)
    db.session.commit()

    session['user'] = user.username
    session['email'] = user.email
    session['user_id'] = user.id

    return jsonify({"message": "Registered successfully"})

# ================= LOGIN =================
from werkzeug.security import check_password_hash
from flask import request, jsonify, session

# LOGIN FIX
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}

    if not data:
        return jsonify({"message": "Invalid request"}), 400

    email = data.get('email')
    password = data.get('password')
    remember = bool(data.get('remember'))

    if not email or not password:
        return jsonify({"message": "Email and password required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user:
        return jsonify({"message": "User not found"}), 404

    if not check_password_hash(user.password, password):
        return jsonify({"message": "Wrong password"}), 401

    preserved_guest_cart = {
        key: session.get(key)
        for key in ("cart", "guest_cart", "cart_items")
        if session.get(key)
    }

    session.clear()
    session.permanent = remember

    session['user_id'] = user.id
    session['username'] = user.username
    session['email'] = user.email
    session['is_admin'] = user.is_admin

    for key, value in preserved_guest_cart.items():
        session[key] = value

    session_merged_count = merge_session_guest_cart_to_user(user)

    return jsonify({
        "message": "Login successful",
        "name": user.username,   # ✅ IMPORTANT FIX
        "email": user.email,
        "id": user.id,
        "session_cart_merged": session_merged_count
    }), 200


@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"success": False, "message": "Email required."}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"success": False, "message": "Email/User not found."}), 404

    try:
        send_password_reset_link(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error("Password reset email error for %s: %s", email, e)
        return jsonify({"success": False, "message": "Unable to send reset link right now."}), 500

    return jsonify({"success": True, "message": "Reset password link sent to your email."}), 200


@app.route('/account/change-password', methods=['POST'])
def account_change_password():
    user = get_logged_in_user()
    if not user:
        return jsonify({"success": False, "message": "Please login to continue."}), 401

    try:
        send_password_reset_link(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error("Account password reset email error for user %s: %s", user.id, e)
        return jsonify({"success": False, "message": "Unable to send reset link right now."}), 500

    return jsonify({
        "success": True,
        "message": "Password reset link sent to your registered email."
    })


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset_token = PasswordResetToken.query.filter_by(token=token, used=False).first()
    token_valid = bool(reset_token and reset_token.expires_at >= datetime.utcnow())

    if request.method == "POST":
        if not token_valid:
            return render_template(
                "reset_password.html",
                token=token,
                token_valid=False,
                error="This password reset link is invalid or expired.",
            ), 400

        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if new_password != confirm_password:
            return render_template(
                "reset_password.html",
                token=token,
                token_valid=True,
                error="Passwords do not match.",
            ), 400

        if not password_is_strong(new_password):
            return render_template(
                "reset_password.html",
                token=token,
                token_valid=True,
                error="Password must be 8+ characters and include at least 1 letter and 1 number.",
            ), 400

        user = User.query.get(reset_token.user_id)
        if not user:
            return render_template(
                "reset_password.html",
                token=token,
                token_valid=False,
                error="This password reset link is invalid or expired.",
            ), 400

        user.password = generate_password_hash(new_password)
        reset_token.used = True
        db.session.commit()
        session.clear()
        return redirect("/?show_login=1&reset=success")

    return render_template(
        "reset_password.html",
        token=token,
        token_valid=token_valid,
        error=None if token_valid else "This password reset link is invalid or expired.",
    )

from collections import defaultdict
from flask import jsonify

@app.route('/products')
def products():
    active_filter = db.or_(
        Product.is_archived == False,
        Product.is_archived.is_(None)
    )

    if request.args.get("homepage") == "1":
        all_products = []
        mobile_limit = int(app.config.get("INDEX_MOBILE_PRODUCTS_LIMIT", 4))
        type_limits = {
            "belt": max(int(app.config.get("INDEX_BELTS_LIMIT", 3)), mobile_limit),
            "wallet": max(int(app.config.get("INDEX_WALLETS_LIMIT", 5)), mobile_limit),
        }

        for product_type, limit in type_limits.items():
            selected = Product.query.filter(
                active_filter,
                Product.product_type == product_type,
                Product.show_on_homepage == True
            ).order_by(
                Product.homepage_sort_order.asc(),
                Product.id.desc()
            ).limit(limit).all()

            if not selected:
                selected = Product.query.filter(
                    active_filter,
                    Product.product_type == product_type
                ).order_by(Product.id.desc()).limit(limit).all()

            all_products.extend(selected)
    else:
        all_products = Product.query.filter(
            active_filter
        ).all()

    result = []

    for p in all_products:
        requires_size = product_requires_size(p.id)
        product_sizes = [
            {
                "id": size.id,
                "label": size.size_label,
                "value": size.size_value
            }
            for size in ProductSize.query.filter_by(product_id=p.id).order_by(ProductSize.id.asc()).all()
        ] if requires_size else []

        # 📦 related data
        images = ProductImage.query.filter_by(product_id=p.id).order_by(
            ProductImage.color_id,
            ProductImage.is_primary.desc(),
            ProductImage.id
        ).all()

        # 🎨 color-wise images mapping
        color_images = defaultdict(list)

        for img in images:
            if img.color_id:
                color_images[img.color_id].append(img.image_url)

        # 🖼️ fallback images (no color)
        fallback_images = [img.image_url for img in images if not img.color_id]

        # ❌ SKIP if no images at all
        if not images:
            continue

        # =========================
        # ✅ CASE 1: NO COLORS PRODUCT
        # =========================
        if not p.product_colors:
            result.append({
                "id": p.id,
                "product_id": p.id,

                "name": p.name,
                "price": p.price,
                "original_price": p.original_price,
                "discount_percent": p.discount_percent or 0,
                "rating": p.rating or 0,
                "product_type": p.product_type or "belt",
                "show_on_homepage": bool(p.show_on_homepage),
                "homepage_sort_order": p.homepage_sort_order or 0,
                "size_type": product_size_type(p),
                "requires_size": requires_size,

                "images": fallback_images if fallback_images else [images[0].image_url],

                "color_variant": None,
                "colors": [],
                "sizes": product_sizes
            })

        # =========================
        # 🎨 CASE 2: COLOR VARIANTS
        # =========================
        for pc in p.product_colors:

            imgs = color_images.get(pc.color_id)

            # 🧠 fallback logic
            if not imgs:
                imgs = fallback_images if fallback_images else [images[0].image_url]

            # ❌ still empty → skip
            if not imgs:
                continue

            result.append({
                "id": f"{p.id}_{pc.color_id}",   # ✅ UNIQUE CARD ID
                "product_id": p.id,

                "name": p.name,
                "price": p.price,
                "original_price": p.original_price,
                "discount_percent": p.discount_percent or 0,
                "rating": p.rating or 0,
                "product_type": p.product_type or "belt",
                "show_on_homepage": bool(p.show_on_homepage),
                "homepage_sort_order": p.homepage_sort_order or 0,
                "size_type": product_size_type(p),
                "requires_size": requires_size,

                "images": imgs,

                "color_variant": {
                    "id": pc.color.id,
                    "name": pc.color.name,
                    "code": pc.color.hex_code or pc.color.code,
                    "hex_code": pc.color.hex_code or pc.color.code
                },

                "colors": [
                    {
                        "id": pc.color.id,
                        "name": pc.color.name,
                        "code": pc.color.hex_code or pc.color.code,
                        "hex_code": pc.color.hex_code or pc.color.code
                    }
                ],
                "sizes": product_sizes
            })

    return jsonify(result)

@app.route('/api/search')
def api_search():
    query = request.args.get('q')

    products = Product.query.filter(
       Product.name.ilike(f"%{query}%"),
       db.or_(
        Product.is_archived == False,
        Product.is_archived.is_(None)
    )
).limit(6).all()
    result = []

    for p in products:
        image = ProductImage.query.filter_by(product_id=p.id).first()

        result.append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "image": image.image_url if image else "/static/images/default.png"
        })

    return jsonify(result)


@app.route('/api/warranty', methods=['POST'])
def warranty():
    return register_warranty()


@app.route('/register-warranty', methods=['POST'])
def register_warranty():

    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    email = (request.form.get('email') or '').strip()
    address = (request.form.get('address') or '').strip()
    purchase = (request.form.get('purchase') or '').strip()
    order_id = (request.form.get('order_id') or '').strip()
    product_name = (request.form.get('product_name') or '').strip()
    purchase_date = (request.form.get('purchase_date') or '').strip()
    message = (request.form.get('message') or '').strip()

    file = request.files.get('bill')

    filename = None
    if file:
       ext = file.filename.split('.')[-1]
       filename = f"{uuid.uuid4()}.{ext}"

    if not name or not phone or not email or not purchase:
        return json_error("Name, phone, email, and purchase source are required", 400)

    new_claim = Warranty(
        name=name,
        phone=phone,
        email=email,
        address=address,
        purchase=purchase,
        order_id=order_id,
        product_name=product_name,
        purchase_date=purchase_date,
        message=message,
        bill=filename
    )

    try:
        db.session.add(new_claim)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Warranty database save failed")
        return json_error("Unable to save warranty claim right now. Please try again.", 500)

    body = (
        "New warranty registration received from Belt Purse account page.\n\n"
        f"Customer Name: {name}\n"
        f"Email: {email or 'Not provided'}\n"
        f"Phone: {phone}\n"
        f"Order ID: {order_id or 'Not provided'}\n"
        f"Product Name: {product_name or 'Not provided'}\n"
        f"Purchase Date: {purchase_date or 'Not provided'}\n"
        f"Purchase Source: {purchase}\n"
        f"Address: {address or 'Not provided'}\n"
        f"Message: {message or 'Not provided'}\n"
        f"Date/Time: {format_support_timestamp()}"
    )

    attachment = build_resend_attachment(file)
    admin_sent, _ = send_resend_email_safe(
        "New Warranty Registration - Belt Purse",
        body,
        attachments=[attachment] if attachment else None
    )
    customer_sent, _ = send_resend_email_safe(
        "Warranty Registration Received - BeltPurse",
        (
            f"Hi {name},\n\n"
            "We received your warranty registration. Our team will review it and contact you soon.\n\n"
            "BeltPurse Team"
        ),
        to_email=email
    )
    if not admin_sent or not customer_sent:
        app.logger.error(
            "Warranty email delivery incomplete for warranty %s: admin_sent=%s customer_sent=%s",
            new_claim.id,
            admin_sent,
            customer_sent
        )
        return json_error("Warranty saved, but email could not be sent right now.", 500)

    return jsonify({"success": True, "message": "Warranty claim submitted successfully"})


@app.route('/send-contact-email', methods=['POST'])
def send_contact_email():
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        message = (data.get("message") or "").strip()

        if not name or not email or not message:
            return json_error("All fields are required", 400)

        body = (
            "New contact message received from Belt Purse website.\n\n"
            f"Customer Name: {name}\n"
            f"Customer Email: {email}\n"
            f"Date/Time: {format_support_timestamp()}\n\n"
            f"Message:\n{message}"
        )

        send_resend_email("New Contact Message - Belt Purse", body)

        customer_body = (
            f"Hi {name},\n\n"
            "We received your message and our team will contact you soon.\n\n"
            "BeltPurse Team"
        )
        send_resend_email_safe(
            "We received your message - BeltPurse",
            customer_body,
            to_email=email
        )

        return jsonify({"success": True, "message": "Message sent successfully"})
    except Exception as e:
        app.logger.error("Error sending contact email: %s", e)
        return json_error("Unable to send your message right now. Please try again.", 500)


@app.route('/send-help-email', methods=['POST'])
def send_help_email():
    try:
        data = request.get_json(silent=True) or {}
        subject = (data.get("subject") or "").strip()
        message = (data.get("message") or "").strip()
        user_email = (data.get("user_email") or "").strip()
        user_name = (data.get("user_name") or "").strip()
        phone = (data.get("phone") or "").strip()
        order_id = (data.get("order_id") or "").strip()
        category = (data.get("category") or subject).strip()

        if not subject or not message:
            return json_error("Subject and message are required", 400)

        body = (
            "New support issue submitted from Belt Purse account page.\n\n"
            f"Name: {user_name or 'Not provided'}\n"
            f"Email: {user_email or 'Not provided'}\n"
            f"Phone: {phone or 'Not provided'}\n"
            f"Order ID: {order_id or 'Not provided'}\n"
            f"Issue Type: {category or 'Not provided'}\n"
            f"Date/Time: {format_support_timestamp()}\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{message}"
        )

        send_resend_email(f"New Support Issue - {subject}", body)

        if user_email:
            send_resend_email_safe(
                "We received your issue - BeltPurse",
                "We have received your issue and our team will contact you soon.",
                to_email=user_email
            )

        return jsonify({"success": True, "message": "Email sent successfully"})
    except Exception as e:
        app.logger.error("Error sending help email: %s", e)
        return json_error("Unable to send support email right now. Please try again.", 500)


@app.route('/submit-issue', methods=['POST'])
def submit_issue():
    user = get_logged_in_user()
    if not user:
        return jsonify({"success": False, "message": "Please login to continue."}), 401

    subject = (request.form.get("subject") or request.form.get("category") or "").strip()
    message = (request.form.get("message") or "").strip()
    category = (request.form.get("category") or subject).strip()
    order_id = (request.form.get("order_id") or "").strip()
    phone = (request.form.get("phone") or user.phone or "").strip()
    attachment = build_resend_attachment(request.files.get("attachment"))

    if not subject or not message:
        return json_error("Subject and message are required", 400)

    ticket = Ticket(user_id=user.id, subject=subject, message=message)
    try:
        db.session.add(ticket)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Support issue database save failed for user %s", user.id)
        return json_error("Unable to save your issue right now. Please try again.", 500)

    body = (
        "New support issue submitted from Belt Purse account page.\n\n"
        f"Name: {user.username}\n"
        f"Email: {user.email}\n"
        f"Phone: {phone or 'Not provided'}\n"
        f"Order ID: {order_id or 'Not provided'}\n"
        f"Issue Type: {category or 'Not provided'}\n"
        f"Ticket ID: {ticket.id}\n"
        f"Date/Time: {format_support_timestamp()}\n\n"
        f"Message:\n{message}"
    )

    admin_sent, _ = send_resend_email_safe(
        f"New Support Issue - {subject}",
        body,
        attachments=[attachment] if attachment else None
    )
    customer_sent, _ = send_resend_email_safe(
        "We received your issue - BeltPurse",
        "We have received your issue and our team will contact you soon.",
        to_email=user.email
    )
    if not admin_sent or not customer_sent:
        app.logger.error(
            "Support issue email delivery incomplete for ticket %s: admin_sent=%s customer_sent=%s",
            ticket.id,
            admin_sent,
            customer_sent
        )
        return json_error("Issue saved, but email could not be sent right now.", 500)

    return jsonify({"success": True, "message": "Issue submitted successfully", "ticket_id": ticket.id})


@app.route('/send-warranty-email', methods=['POST'])
def send_warranty_email():
    try:
        name = (request.form.get("w_name") or "").strip()
        phone = (request.form.get("w_phone") or "").strip()
        email = (request.form.get("w_email") or "").strip()
        purchase = (request.form.get("w_purchase") or "").strip()
        address = (request.form.get("w_address") or "").strip()
        order_id = (request.form.get("w_order_id") or "").strip()
        product_name = (request.form.get("w_product_name") or "").strip()
        purchase_date = (request.form.get("w_purchase_date") or "").strip()
        message = (request.form.get("w_message") or "").strip()

        if not name or not phone or not purchase:
            return json_error("Name, phone, and purchase source are required", 400)

        body = (
            "New warranty registration received from Belt Purse account page.\n\n"
            f"Full Name: {name}\n"
            f"Phone: {phone}\n"
            f"Email: {email or 'Not provided'}\n"
            f"Order ID: {order_id or 'Not provided'}\n"
            f"Product Name: {product_name or 'Not provided'}\n"
            f"Purchase Date: {purchase_date or 'Not provided'}\n"
            f"Purchase Source: {purchase}\n"
            f"Address: {address or 'Not provided'}\n"
            f"Message: {message or 'Not provided'}\n"
            f"Date/Time: {format_support_timestamp()}"
        )

        bill = request.files.get("w_bill")
        attachment = build_resend_attachment(bill)

        try:
            send_resend_email(
                "New Warranty Registration - Belt Purse",
                body,
                attachments=[attachment] if attachment else None
            )
        except Exception as attachment_error:
            if not attachment:
                raise
            print(f"Error sending warranty attachment, retrying without attachment: {attachment_error}")
            send_resend_email("New Warranty Registration - Belt Purse", body)

        if email:
            send_resend_email_safe(
                "Warranty Registration Received - BeltPurse",
                (
                    f"Hi {name},\n\n"
                    "We received your warranty registration. Our team will review it and contact you soon.\n\n"
                    "BeltPurse Team"
                ),
                to_email=email
            )

        return jsonify({"success": True, "message": "Email sent successfully"})
    except Exception as e:
        app.logger.error("Error sending warranty email: %s", e)
        return json_error("Unable to send warranty email right now. Please try again.", 500)
# ================= PRODUCT DETAIL =================
@app.route('/product/<int:id>')
def product_detail(id):
    product = db.session.get(Product, id)

    if not product or product.is_archived:
        return "Product not found", 404

    selected_color_id = normalize_optional_int(request.args.get("color"))

    images_query = ProductImage.query.filter_by(product_id=id).order_by(
        ProductImage.is_primary.desc(),
        ProductImage.id
    )
    images = images_query.all()
    if selected_color_id:
        images = sorted(
            images,
            key=lambda img: (
                0 if img.color_id == selected_color_id and img.is_primary else
                1 if img.color_id == selected_color_id else
                2 if img.color_id is None and img.is_primary else
                3 if img.is_primary else
                4,
                img.id
            )
        )

    images_data = [
      {
        "id": img.id,
        "image_url": img.image_url,
        "color_id": img.color_id
      }
        for img in images
   ]
    videos = ProductVideo.query.filter_by(product_id=id).all()
    tags = ProductTag.query.filter_by(product_id=id).all()
    requires_size = product_requires_size(id)
    sizes = ProductSize.query.filter_by(product_id=id).all() if requires_size else []
    colors = ProductColor.query.filter_by(product_id=id).all()
    related_products = Product.query.filter(
       Product.id != id,
       db.or_(
        Product.is_archived == False,
        Product.is_archived.is_(None)
    )
).limit(4).all()
    reviews = Review.query.options(joinedload(Review.user))\
       .filter_by(product_id=id).all()
    product_page_coupons = get_product_page_coupons(current_user)

    return render_template(
        "product.html",
        product=product,
        detail_requires_size=requires_size,
        detail_size_type=product_size_type(product),
        reviews=reviews,
        images=images_data,
        videos=videos,
        tags=tags,
        sizes=sizes,
        colors=colors,
        product_page_coupons=product_page_coupons,
        related_products=related_products
    )


@app.route('/products-page')
def products_page():
    color_id = request.args.get('color')

    base_filter = db.or_(
        Product.is_archived == False,
        Product.is_archived.is_(None)
    )

    if color_id:
        products = Product.query.join(ProductColor).filter(
            ProductColor.color_id == color_id,
            base_filter
        ).all()
    else:
        products = Product.query.filter(base_filter).all()

    return render_template("products.html", products=products)

# ================= CONTEXT =================
@app.context_processor
def inject_counts():
    if 'email' in session:
        user = User.query.filter_by(email=session['email']).first()
        if user:
            cart_count = db.session.execute(text("""
                SELECT SUM(quantity) FROM cart WHERE user_id=:uid
            """), {"uid": user.id}).scalar() or 0

            wishlist_count = db.session.execute(text("""
                SELECT COUNT(*) FROM wishlist WHERE user_id=:uid
            """), {"uid": user.id}).scalar() or 0

            # ✅ FIX: object bhej, string nahi
            return dict(
                cart_count=cart_count,
                wishlist_count=wishlist_count,
                user={
                    "username": user.username,
                    "email": user.email,
                    "avatar": user.avatar
                }
            )

    return dict(cart_count=0, wishlist_count=0, user=None)
# ================= CART =================
from sqlalchemy import text

@app.route('/cart')
def cart_page():
    if 'email' not in session:
        return render_template("cart.html", products=[], total=0, total_items=0)


    user = User.query.filter_by(email=session['email']).first()
    if not user:
        session.clear()
        return redirect('/')

    consolidate_cart_duplicates(user.id)

    # ✅ PostgreSQL compatible query (SQLAlchemy)
    rows = db.session.execute(text("""
        SELECT 
            c.id AS cart_id,
            p.id,
            p.name,
            p.price,
            c.color_id,
            c.size_id,
            CASE
                WHEN LOWER(COALESCE(p.product_type, 'belt')) = 'belt'
                     AND LOWER(COALESCE(p.size_type, 'specific')) = 'universal' THEN 'Universal Size'
                ELSE COALESCE(ps.size_label, '')
            END AS size_label,
            COALESCE(co.name, '') AS color_name,
            COALESCE(co.hex_code, co.code, '') AS color_code,
            COALESCE(
                (SELECT pi.image_url FROM product_images pi
                 WHERE pi.product_id = p.id AND c.color_id IS NOT NULL
                   AND pi.color_id = c.color_id AND pi.is_primary = TRUE
                 ORDER BY pi.id LIMIT 1),
                (SELECT pi.image_url FROM product_images pi
                 WHERE pi.product_id = p.id AND c.color_id IS NOT NULL
                   AND pi.color_id = c.color_id
                 ORDER BY pi.id LIMIT 1),
                (SELECT pi.image_url FROM product_images pi
                 WHERE pi.product_id = p.id AND pi.color_id IS NULL AND pi.is_primary = TRUE
                 ORDER BY pi.id LIMIT 1),
                (SELECT pi.image_url FROM product_images pi
                 WHERE pi.product_id = p.id AND pi.is_primary = TRUE
                 ORDER BY pi.id LIMIT 1),
                (SELECT pi.image_url FROM product_images pi
                 WHERE pi.product_id = p.id
                 ORDER BY pi.id LIMIT 1)
            ) AS image_url,
            c.quantity
        FROM cart c
        JOIN products p ON c.product_id = p.id
        LEFT JOIN colors co ON co.id = c.color_id
        LEFT JOIN product_sizes ps ON ps.id = c.size_id
        WHERE c.user_id = :uid
        ORDER BY c.id ASC
    """), {"uid": user.id}).fetchall()

    total = 0
    total_items = 0
    clean_items = []

    for p in rows:
        # 🔥 row mapping fix (important for PostgreSQL)
        p = dict(p._mapping)

        price = int(p['price']) if p['price'] else 0
        qty = int(p['quantity']) if p['quantity'] else 0

        total += price * qty
        total_items += qty

        clean_items.append({
            "cart_id": p['cart_id'],
            "id": p['id'],
            "name": p['name'],
            "price": price,
            "quantity": qty,
            "image_url": p['image_url'],
            "color_id": p['color_id'],
            "size_id": p['size_id'],
            "size_label": p['size_label'],
            "color_name": p['color_name'],
            "color_code": p['color_code']
        })

    coupon_code = current_coupon_code()
    cart_lines, _ = cart_snapshot_for_user(user.id)
    if coupon_code:
        coupon_result = validate_coupon_for_user(user, coupon_code, total, cart_lines=cart_lines)
        if not coupon_result["valid"]:
            session.pop("coupon_code", None)
            session.modified = True
            coupon_result = validate_coupon_for_user(user, None, total, cart_lines=cart_lines)
    else:
        coupon_result = validate_coupon_for_user(user, None, total, cart_lines=cart_lines)

    return render_template(
        "cart.html",
        products=clean_items,
        total=total,
        total_items=total_items,
        coupon_result=coupon_result
    )

@app.route('/remove_cart/<int:id>')
def remove_cart(id):
    if 'email' not in session:
        return jsonify({"success": False}), 401

    user = User.query.filter_by(email=session['email']).first()
    cart_item_id = request_cart_item_id()

    if cart_item_id:
        cart_item = Cart.query.filter_by(id=cart_item_id, user_id=user.id).first()
        if not cart_item:
            return jsonify({"success": False, "message": "Cart item not found"}), 404
        db.session.delete(cart_item)
    else:
        color_id = request_color_id()
        size_id = normalize_cart_size_id(id, request.args.get("size_id"))
        clear_wallet_cart_sizes(id, user.id)

        db.session.execute(text("""
            DELETE FROM cart WHERE user_id=:uid AND product_id=:pid
            AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
            AND ((size_id IS NULL AND :sid IS NULL) OR size_id=:sid)
        """), {"uid": user.id, "pid": id, "cid": color_id, "sid": size_id})

    db.session.commit()

    payload = cart_totals_payload(user.id)
    return jsonify({
        "success": True,
        **payload,
        "count": payload["cart_count"],
        "message": "Removed from cart"
    })


@app.route('/decrease_cart/<int:id>')
def decrease_cart(id):
    if 'email' not in session:
        return "Unauthorized", 401

    user = User.query.filter_by(email=session['email']).first()
    color_id = request_color_id()
    size_id = normalize_cart_size_id(id, request.args.get("size_id"))
    clear_wallet_cart_sizes(id, user.id)

    item = db.session.execute(text("""
        SELECT quantity FROM cart
        WHERE user_id=:uid AND product_id=:pid
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
        AND ((size_id IS NULL AND :sid IS NULL) OR size_id=:sid)
        LIMIT 1
    """), {"uid": user.id, "pid": id, "cid": color_id, "sid": size_id}).fetchone()

    if item:
        if item.quantity > 1:
            db.session.execute(text("""
                UPDATE cart SET quantity = quantity - 1
                WHERE user_id=:uid AND product_id=:pid
                AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
                AND ((size_id IS NULL AND :sid IS NULL) OR size_id=:sid)
            """), {"uid": user.id, "pid": id, "cid": color_id, "sid": size_id})
        else:
            db.session.execute(text("""
                DELETE FROM cart WHERE user_id=:uid AND product_id=:pid
                AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
                AND ((size_id IS NULL AND :sid IS NULL) OR size_id=:sid)
            """), {"uid": user.id, "pid": id, "cid": color_id, "sid": size_id})

    db.session.commit()
    return jsonify({"success": True, "message": "Updated"})

@app.route('/add_to_cart/<int:id>', methods=['GET', 'POST'])
def add_to_cart(id):
    if 'email' not in session:
        return jsonify({"error": "Login required"}), 401
    product = Product.query.get(id)
    if not product or product.is_archived:
        return jsonify({"error": "Product is not available"}), 404
    user     = User.query.filter_by(email=session['email']).first()
    data     = request.get_json(silent=True) or {}
    color_id = request_color_id(data)
    size_id  = normalize_cart_size_id(id, data.get('size_id') or request.args.get('size_id'))
    clear_wallet_cart_sizes(id, user.id)

    if product_requires_size(id) and not size_id:
        return jsonify({"error": "size_required", "message": "Please select a size before adding to cart."}), 400
    if size_id and not is_valid_product_size(id, size_id):
        return jsonify({"error": "invalid_size", "message": "Invalid size selected"}), 400

    add_cart_item(user, id, color_id, size_id, 1)

    db.session.commit()
    consolidate_cart_duplicates(user.id)

    payload = cart_totals_payload(user.id)
    return jsonify({
        "success": True,
        **payload,
        "count": payload["cart_count"],
        "message": "Added to cart"
    })


# ================= WISHLIST =================
@app.route('/add_to_wishlist/<int:id>')
def add_to_wishlist(id):
    if 'email' not in session:
        return jsonify({"error": "Login required"}), 401
    product = Product.query.get(id)
    if not product or product.is_archived:
        return jsonify({"error": "Product is not available"}), 404
    user = User.query.filter_by(email=session['email']).first()
    color_id = request_color_id()
    print(f"add_to_wishlist user={user.id} product={id} color={color_id}")

    # prevent duplicate
    existing = db.session.execute(text("""
        SELECT * FROM wishlist WHERE user_id=:uid AND product_id=:pid
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
    """), {"uid": user.id, "pid": id, "cid": color_id}).fetchone()

    if not existing:
        db.session.execute(text("""
            INSERT INTO wishlist (user_id, product_id, color_id)
            VALUES (:uid, :pid, :cid)
        """), {"uid": user.id, "pid": id, "cid": color_id})
        db.session.commit()

    cart_count, wishlist_count = user_counts(user.id)
    return jsonify({
        "success": True,
        "action": "added" if not existing else "exists",
        "wishlist_count": wishlist_count,
        "cart_count": cart_count,
        "count": wishlist_count,
        "message": "Added to wishlist" if not existing else "Already in wishlist"
    })

@app.route('/get_wishlist')
def get_wishlist():
    if 'email' not in session:
        return jsonify([])

    user = User.query.filter_by(email=session['email']).first()

    items = db.session.execute(text("""
        SELECT p.*, w.color_id, co.name AS color_name, COALESCE(co.hex_code, co.code) AS color_code,
               COALESCE(
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND w.color_id IS NOT NULL
                      AND pi.color_id = w.color_id AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND w.color_id IS NOT NULL
                      AND pi.color_id = w.color_id
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND pi.color_id IS NULL AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id
                    ORDER BY pi.id LIMIT 1)
               ) AS image_url
        FROM wishlist w
        JOIN products p ON w.product_id = p.id
        LEFT JOIN colors co ON w.color_id = co.id
        WHERE w.user_id = :uid
    """), {"uid": user.id}).fetchall()

    return jsonify([dict(row._mapping) for row in items])

@app.route('/remove_wishlist/<int:id>')
def remove_wishlist(id):
    if 'email' not in session:
        return "Unauthorized", 401

    user = User.query.filter_by(email=session['email']).first()
    color_id = request_color_id()
    size_id = normalize_optional_int(request.args.get("size_id"))

    db.session.execute(
        text("""
            DELETE FROM wishlist
            WHERE user_id=:uid AND product_id=:pid
            AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
        """),
        {"uid": user.id, "pid": id, "cid": color_id}
    )
    db.session.commit()

    cart_count, wishlist_count = user_counts(user.id)
    return jsonify({
        "success": True,
        "action": "removed",
        "wishlist_count": wishlist_count,
        "cart_count": cart_count,
        "message": "Removed from wishlist"
    })

def get_user():
    return User.query.filter_by(email=session.get('email')).first()

@app.route('/wishlist')
def wishlist_page():
    if 'email' not in session:
         return render_template("wishlist.html", items=[])
    user = User.query.filter_by(email=session['email']).first()
    if not user:
       session.clear()
       return redirect('/')
    
    items = db.session.execute(text("""
        SELECT p.*,
               w.color_id,
               co.name AS color_name,
               COALESCE(co.hex_code, co.code) AS color_code,
               COALESCE(
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND w.color_id IS NOT NULL
                      AND pi.color_id = w.color_id AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND w.color_id IS NOT NULL
                      AND pi.color_id = w.color_id
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND pi.color_id IS NULL AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id
                    ORDER BY pi.id LIMIT 1)
               ) AS image_url
        FROM wishlist w
        JOIN products p ON w.product_id = p.id
        LEFT JOIN colors co ON co.id = w.color_id
        WHERE w.user_id = :uid
    """), {"uid": user.id}).fetchall()

    return render_template("wishlist.html", items=items)

@app.route('/wishlist/check/<int:product_id>')
def check_wishlist(product_id):
    if 'email' not in session:
        return jsonify({"in_wishlist": False})

    user = get_user()
    if not user:
        return jsonify({"in_wishlist": False})

    color_id = request_color_id()

    exists = db.session.execute(text("""
        SELECT 1 FROM wishlist 
        WHERE user_id=:uid 
        AND product_id=:pid
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id = :cid)
    """), {"uid": user.id, "pid": product_id, "cid": color_id}).fetchone()

    return jsonify({"in_wishlist": bool(exists)})


@app.route('/wishlist/toggle/<int:product_id>', methods=["GET", "POST"])
def toggle_wishlist(product_id):
    if 'email' not in session:
        return jsonify({"error": "Login required"}), 401
    product = Product.query.get(product_id)
    if not product or product.is_archived:
        return jsonify({"error": "Product is not available"}), 404
    user = get_user()
    color_id = request_color_id()

    existing = db.session.execute(text("""
        SELECT 1 FROM wishlist 
        WHERE user_id=:uid 
        AND product_id=:pid
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id = :cid)
    """), {"uid": user.id, "pid": product_id, "cid": color_id}).fetchone()

    if existing:
        db.session.execute(text("""
            DELETE FROM wishlist 
            WHERE user_id=:uid 
            AND product_id=:pid
            AND ((color_id IS NULL AND :cid IS NULL) OR color_id = :cid)
        """), {"uid": user.id, "pid": product_id, "cid": color_id})
        in_wishlist = False
    else:
        db.session.execute(text("""
            INSERT INTO wishlist (user_id, product_id, color_id)
            VALUES (:uid, :pid, :cid)
        """), {"uid": user.id, "pid": product_id, "cid": color_id})

        in_wishlist = True

    db.session.commit()

    cart_count, wishlist_count = user_counts(user.id)

    return jsonify({
        "success": True,
        "in_wishlist": in_wishlist,
        "action": "added" if in_wishlist else "removed",
        "count": wishlist_count,
        "wishlist_count": wishlist_count,
        "cart_count": cart_count,
        "message": "Added to wishlist" if in_wishlist else "Removed from wishlist"
    })
@app.route("/cart/toggle/<int:product_id>", methods=["POST"])
def toggle_cart(product_id):

    if 'email' not in session:
        return jsonify({"error": "login required"}), 401
    
    data = request.get_json() or {}
    size_id = normalize_cart_size_id(product_id, data.get("size_id"))
    color_id = request_color_id(data)
    product = Product.query.get(product_id)
    if not product or product.is_archived:
        return jsonify({"error": "Product is not available"}), 404
    user = get_user()
    clear_wallet_cart_sizes(product_id, user.id)

    if product_requires_size(product_id) and not size_id:
        return jsonify({"error": "size_required"}), 400
    if size_id and not is_valid_product_size(product_id, size_id):
        return jsonify({"error": "invalid_size", "message": "Invalid size selected"}), 400

    existing = db.session.execute(text("""
        SELECT 1 FROM cart 
        WHERE user_id=:uid 
        AND product_id=:pid 
        AND ((size_id IS NULL AND :sid IS NULL) OR size_id=:sid)
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id = :cid)
    """), {
        "uid": user.id,
        "pid": product_id,
        "sid": size_id,
        "cid": color_id
    }).fetchone()

    if existing:
        db.session.execute(text("""
            DELETE FROM cart 
            WHERE user_id=:uid 
            AND product_id=:pid 
            AND ((size_id IS NULL AND :sid IS NULL) OR size_id=:sid)
            AND ((color_id IS NULL AND :cid IS NULL) OR color_id = :cid)
        """), {
            "uid": user.id,
            "pid": product_id,
            "sid": size_id,
            "cid": color_id
        })
        in_cart = False
    else:
        db.session.execute(text("""
            INSERT INTO cart (user_id, product_id, color_id, size_id, quantity)
            VALUES (:uid, :pid, :cid, :sid, 1)
        """), {
            "uid": user.id,
            "pid": product_id,
            "sid": size_id,
            "cid": color_id
        })
        in_cart = True

    db.session.commit()

    payload = cart_totals_payload(user.id)
    return jsonify({
        "success": True,
        "in_cart": in_cart,
        **payload,
        "count": payload["cart_count"],
        "message": "Added to cart" if in_cart else "Removed from cart"
    })

@app.route("/cart/check/<int:product_id>")
def check_cart(product_id):

    if 'email' not in session:
        return jsonify({"in_cart": False})

    user = User.query.filter_by(email=session['email']).first()
    color_id = request_color_id()

    exists = db.session.execute(text("""
        SELECT size_id FROM cart 
         WHERE user_id=:uid AND product_id=:pid
         AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
        LIMIT 1
"""), {"uid": user.id, "pid": product_id, "cid": color_id}).fetchone()

    return jsonify({
      "in_cart": bool(exists),
      "size_id": exists.size_id if exists else None
})

@app.route('/get_counts')
def get_counts():
    if 'email' not in session:
        return jsonify({"cart": 0, "wishlist": 0})

    user = User.query.filter_by(email=session['email']).first()
    if not user:
      session.clear()              # ← clear stale session
      return jsonify({"cart": 0, "wishlist": 0})

    cart_count, wishlist_count = user_counts(user.id)

    return jsonify({
        "cart": cart_count,
        "wishlist": wishlist_count
    })


# script.js compatibility alias
@app.route('/api/counts')
def api_counts():
    return get_counts()


@app.route('/update_quantity/<int:product_id>/<string:action>')
def update_quantity(product_id, action):
    if 'email' not in session:
        return jsonify({"success": False, "status": "error", "message": "Login required"}), 401

    user = User.query.filter_by(email=session['email']).first()
    cart_item_id = request_cart_item_id()
    cart_item = None

    if cart_item_id:
        cart_item = Cart.query.filter_by(id=cart_item_id, user_id=user.id).first()
    else:
        color_id = request_color_id()
        size_id = normalize_cart_size_id(product_id, request.args.get("size_id"))
        clear_wallet_cart_sizes(product_id, user.id)
        cart_item = Cart.query.filter(
            Cart.user_id == user.id,
            Cart.product_id == product_id,
            Cart.color_id.is_(None) if color_id is None else Cart.color_id == color_id,
            Cart.size_id.is_(None) if size_id is None else Cart.size_id == size_id
        ).order_by(Cart.id.asc()).first()

    if not cart_item:
        return jsonify({"success": False, "status": "not_found", "message": "Cart item not found"}), 404

    qty = int(cart_item.quantity) if cart_item else 0

    if action == "plus":
        qty += 1
    elif action == "minus":
        qty -= 1
    else:
        return jsonify({"success": False, "status": "error", "message": "Invalid quantity action"}), 400

    if qty <= 0:
        db.session.delete(cart_item)
    else:
        cart_item.quantity = qty

    db.session.commit()

    payload = cart_totals_payload(user.id)
    return jsonify({
        "success": True,
        "status": "ok",
        "quantity": max(qty, 0),
        "item_total": cart_item_total(cart_item) if qty > 0 else 0,
        "cart_item": cart_item_payload(cart_item) if qty > 0 else None,
        **payload,
        "message": "Cart updated"
    })



@app.route("/product/sizes/<int:product_id>")
def get_product_sizes(product_id):

    if not product_requires_size(product_id):
        return jsonify([])

    sizes = ProductSize.query.filter_by(product_id=product_id).all()

    return jsonify([
        {
            "id": s.id,
            "label": s.size_label,
            "value": s.size_value
        }
        for s in sizes
    ])
@app.route("/cart/selected_size/<int:product_id>")
def get_selected_size(product_id):

    if not product_requires_size(product_id):
        return jsonify({"size_id": None})

    if 'email' not in session:
        return jsonify({"size_id": None})

    user = User.query.filter_by(email=session['email']).first()
    color_id = request_color_id()

    row = db.session.execute(text("""
        SELECT size_id 
        FROM cart 
        WHERE user_id=:uid AND product_id=:pid
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
        LIMIT 1
    """), {"uid": user.id, "pid": product_id, "cid": color_id}).fetchone()

    return jsonify({
        "size_id": row.size_id if row else None
    })

@app.route('/api/orders', methods=['GET'])
def api_orders():
    if 'email' not in session:
        return jsonify([])

    user = User.query.filter_by(email=session['email']).first()

    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()

    return jsonify([{
        "id": o.id,
        "total": o.total_amount,
        "status": o.order_status or o.status,
        "payment_status": o.payment_status or "Pending",
        "tracking_number": o.tracking_number,
        "courier_partner": o.courier_partner,
        "tracking_url": o.tracking_url,
        "items": [{
            "product_name": item.product.name if item.product else f"Product #{item.product_id}",
            "product_image": order_item_image_url(item),
            "size": item.size.size_label if item.size else None,
            "color": item.color.name if item.color else None,
            "quantity": item.quantity,
            "price": item.price
        } for item in o.items],
        "created_at": o.created_at.isoformat() if o.created_at else None
    } for o in orders])

# ================= ADDRESS =================
@app.route('/add_address', methods=['POST'])
def add_address():
    if 'email' not in session:
        return jsonify({"message": "Login required"}), 401

    data = request.get_json() or {}
    user = User.query.filter_by(email=session['email']).first()
    if not user:
        return jsonify({"message": "Login required"}), 401

    user_phone = (user.phone or "").strip()
    alternate_phone = (data.get("alternate_phone") or "").strip()

    if not user_phone:
        return jsonify({"message": "Please add your phone number before placing order."}), 400

    if alternate_phone and not re.fullmatch(r"[6-9]\d{9}", alternate_phone):
        return jsonify({"message": "Please enter a valid 10 digit phone number"}), 400

    delivery_phone = alternate_phone or user_phone

    address = Address(
        user_id=user.id,   # ✅ FIXED
        full_name=(data.get('full_name') or '').strip(),
        phone=delivery_phone,
        address_line=(data.get('address_line') or '').strip(),
        city=(data.get('city') or '').strip(),
        state=(data.get('state') or '').strip(),
        pincode=(data.get('pincode') or '').strip()
    )

    db.session.add(address)
    db.session.commit()

    return jsonify({"message": "Address saved", "phone": delivery_phone})


@app.route('/add-address', methods=['POST'])
def add_address_alias():
    return add_address()

@app.route('/get_addresses')
def get_addresses():
    if 'email' not in session:
        return jsonify([])

    user = User.query.filter_by(email=session['email']).first()

    addresses = Address.query.filter_by(user_id=user.id).all()  # ✅ FIXED
    return jsonify([{
       "full_name": a.full_name,
        "phone": a.phone or user.phone,
        "address_line": a.address_line,
        "city": a.city,
        "state": a.state,
        "pincode": a.pincode
    } for a in addresses]) 

# ================= CART PAGE =================



@app.route("/review/add/<int:product_id>", methods=["POST"])
def add_review(product_id):

    if 'email' not in session:
        return jsonify({"error": "login_required"})

    data = request.get_json()

    user = User.query.filter_by(email=session['email']).first()

    rating = int(data.get("rating"))
    comment = data.get("comment")

    if not comment:
        return jsonify({"error": "empty_comment"})

    review = Review(
        user_id=user.id,
        product_id=product_id,
        rating=rating,
        comment=comment
    )

    db.session.add(review)
    db.session.commit()

    return jsonify({
        "success": True,
        "username": user.username,
        "rating": rating,
        "comment": comment
    })



# ================= CHECKOUT =================
@app.route('/api/checkout-review', methods=['GET'])
def checkout_review():
    """
    Get review data before checkout - shows user details, cart, and addresses
    """
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    if not user:
        return jsonify({"message": "User not found"}), 404

    consolidate_cart_duplicates(user.id)

    # ✅ Fetch cart items
    cart_items = db.session.execute(text("""
        SELECT c.id AS cart_id, c.product_id, c.color_id, c.size_id, c.quantity, ps.size_label
        FROM cart c
        LEFT JOIN product_sizes ps ON ps.id = c.size_id
        WHERE c.user_id = :uid
        ORDER BY c.id ASC
    """), {"uid": user.id}).fetchall()

    if not cart_items:
        return jsonify({
            "message": "Cart is empty",
            "cart": [],
            "total": 0
        })

    # ✅ Build cart details with product info
    cart_details = []
    total = 0
    order_lines, _ = cart_snapshot_for_user(user.id)
    cart_valid, cart_error = validate_cart_lines_for_checkout(order_lines)
    if not cart_valid:
        return jsonify({
            "success": False,
            "message": cart_error,
            "cart": [],
            "total": 0
        }), 400

    for item in cart_items:
        product = Product.query.get(item.product_id)
        if product:
            color = Color.query.get(item.color_id) if item.color_id else None
            item_total = product.price * item.quantity
            total += item_total
            cart_details.append({
                "cart_item_id": item.cart_id,
                "product_id": product.id,
                "product_name": product.name,
                "color_id": item.color_id,
                "color_name": color.name if color else None,
                "size_id": item.size_id,
                "size_label": "Universal Size" if product_size_type(product) == "universal" else item.size_label,
                "quantity": item.quantity,
                "price": product.price,
                "item_total": item_total
            })

    coupon_code = current_coupon_code()
    if coupon_code:
        coupon_result = validate_coupon_for_user(user, coupon_code, total, cart_lines=order_lines)
    else:
        coupon_result = best_auto_coupon_for_user(user, total, cart_lines=order_lines)
    if not coupon_result["valid"]:
        session.pop("coupon_code", None)
        session.modified = True
        coupon_result = validate_coupon_for_user(user, None, total)

    # ✅ Get user's addresses
    addresses = Address.query.filter_by(user_id=user.id).all()
    addresses_list = [{
        "id": a.id,
        "full_name": a.full_name,
        "phone": a.phone,
        "address_line": a.address_line,
        "city": a.city,
        "state": a.state,
        "pincode": a.pincode
    } for a in addresses]

    # ✅ Return review data
    review_data = {
        "user": {
            "name": user.username,
            "email": user.email,
            "phone": user.phone or None,
            "dob": user.dob.strftime('%Y-%m-%d') if user.dob else None,
        },
        "cart": cart_details,
        "cart_count": len(cart_details),
        "total": total,
        "subtotal_amount": coupon_result["subtotal_amount"],
        "coupon_code": coupon_result["coupon_code"],
        "discount_amount": coupon_result["discount_amount"],
        "final_amount": coupon_result["final_amount"],
        "addresses": addresses_list,
        "addresses_count": len(addresses_list),
        "ready_for_checkout": len(addresses_list) > 0 and total > 0
    }

    return jsonify(review_data)

@app.route('/profile/update-phone', methods=['POST'])
def update_profile_phone():
    user = get_logged_in_user()
    if not user:
        return jsonify({
            "success": False,
            "message": "Please login to continue",
            "phone": None
        }), 401

    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()

    if not re.fullmatch(r"[6-9]\d{9}", phone):
        return jsonify({
            "success": False,
            "message": "Please enter a valid 10 digit phone number",
            "phone": None
        }), 400

    user.phone = phone
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Phone number saved",
        "phone": user.phone
    })

@app.route('/api/sync-guest-cart', methods=['POST'])
@app.route('/cart/sync-guest', methods=['POST'])
def sync_guest_cart():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401
    user = User.query.filter_by(email=session['email']).first()
    if not user:
        return jsonify({"message": "Not logged in"}), 401

    payload = request.get_json(silent=True) or {}
    merged_count = merge_guest_cart_items_to_user(user, payload.get('items', []))
    cart_count, wishlist_count = user_counts(user.id)

    return jsonify({
        "success": True,
        "message": "Cart synced",
        "merged_count": merged_count,
        "cart_count": cart_count,
        "wishlist_count": wishlist_count
    })

@app.route('/api/sync-guest-wishlist', methods=['POST'])
def sync_guest_wishlist():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401
    user = User.query.filter_by(email=session['email']).first()
    items = request.get_json().get('items', [])
    for item in items:
        db.session.execute(text("""
            INSERT INTO wishlist (user_id, product_id, color_id)
            SELECT :uid, :pid, :cid
            WHERE NOT EXISTS (
                SELECT 1 FROM wishlist WHERE user_id=:uid AND product_id=:pid AND (color_id=:cid OR (color_id IS NULL AND :cid IS NULL))
            )
        """), {"uid": user.id, "pid": item['productId'], "cid": item.get('colorId')})
    db.session.commit()
    return jsonify({"message": "Wishlist synced"})


@app.route('/create-razorpay-order', methods=['POST'])
def create_razorpay_order():
    user = get_logged_in_user()
    if not user:
        return json_error("Please login to continue", 401)

    if not user.phone or user.phone.strip() == "":
        return jsonify({
            "success": False,
            "message": "Please add your phone number before placing order.",
            "error_type": "missing_phone",
            "redirect": "/account"
        }), 400

    data = request.get_json() or {}
    addresses = Address.query.filter_by(user_id=user.id).all()
    if not addresses:
        return json_error("No address found", 400)

    try:
        selected_index = int(data.get("address_index", 0))
    except (TypeError, ValueError):
        return json_error("Invalid address", 400)

    if selected_index < 0 or selected_index >= len(addresses):
        return json_error("Invalid address", 400)

    selected_address = addresses[selected_index]
    if not selected_address.phone:
        selected_address.phone = user.phone
        db.session.commit()
    cart_lines, cart_total = cart_snapshot_for_user(user.id)
    if not cart_lines:
        return json_error("Cart is empty", 400)

    requested_coupon_code = (data.get("coupon_code") or current_coupon_code()).strip().upper()
    if requested_coupon_code:
        coupon_result = validate_coupon_for_user(user, requested_coupon_code, cart_total, cart_lines=cart_lines)
    else:
        coupon_result = best_auto_coupon_for_user(user, cart_total, cart_lines=cart_lines)
    if not coupon_result["valid"]:
        session.pop("coupon_code", None)
        session.modified = True
        return json_error(coupon_result["message"], 400)

    final_total = coupon_result["final_amount"]
    if coupon_result["coupon_code"]:
        session["coupon_code"] = coupon_result["coupon_code"]
    else:
        session.pop("coupon_code", None)
    session.modified = True

    try:
        client = get_razorpay_client()
    except RuntimeError as exc:
        app.logger.error("Razorpay setup error: %s", exc)
        return json_error(str(exc), 500)

    existing_order = reusable_pending_order(user.id, selected_address.id, final_total, coupon_result["coupon_code"])

    if existing_order and existing_order.razorpay_order_id and existing_order.razorpay_order_id.startswith("order_"):
      return jsonify({
        "success": True,
        "key": app.config.get("RAZORPAY_KEY_ID"),
        "key_id": app.config.get("RAZORPAY_KEY_ID"),
        "amount": int(round(float(existing_order.total_amount or 0) * 100)),
        "currency": "INR",
        "razorpay_order_id": existing_order.razorpay_order_id,
        "order_id": existing_order.id,
        "pending_order_id": existing_order.id,
        "local_order_id": existing_order.id,
        "user_name": selected_address.full_name or user.username,
        "user_email": user.email,
        "user_phone": selected_address.phone or user.phone,
        "name": "BeltPurse",
        "description": f"Order #{existing_order.id}",
        "customer": {
            "name": selected_address.full_name or user.username,
            "email": user.email,
            "phone": selected_address.phone or user.phone
        }
    })

    order, error = create_pending_order_from_cart(
        user,
        selected_address,
        payment_method="Razorpay",
        coupon_code=coupon_result["coupon_code"]
    )
    if error:
        return json_error(error, 400)

    amount_paise = int(round(float(order.total_amount or 0) * 100))
    if amount_paise <= 0:
        order.payment_status = "Failed"
        order.order_status = "Payment Failed"
        order.status = "Payment Failed"
        db.session.commit()
        return json_error("Invalid order amount", 400)

    try:
        razorpay_order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"order_{order.id}",
            "payment_capture": 1,
            "notes": {
                "local_order_id": str(order.id),
                "user_id": str(user.id)
            }
        })
    except Exception as exc:
        app.logger.error("Razorpay order creation failed for local order %s: %s", order.id, exc)
        order.payment_status = "Failed"
        order.order_status = "Payment Failed"
        order.status = "Payment Failed"
        db.session.commit()
        if "Authentication failed" in str(exc):
            return json_error(
                "Razorpay authentication failed. Please check RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env.",
                500
            )
        return json_error("Payment could not be started. Please try again.", 500)

    order.razorpay_order_id = razorpay_order.get("id")
    db.session.commit()

    return jsonify({
        "success": True,
        "key": app.config.get("RAZORPAY_KEY_ID"),
        "key_id": app.config.get("RAZORPAY_KEY_ID"),
        "amount": amount_paise,
        "currency": "INR",
        "razorpay_order_id": order.razorpay_order_id,
        "order_id": order.id,
        "pending_order_id": order.id,
        "local_order_id": order.id,
        "user_name": selected_address.full_name or user.username,
        "user_email": user.email,
        "user_phone": selected_address.phone or user.phone,
        "name": "BeltPurse",
        "description": f"Order #{order.id}",
        "customer": {
            "name": selected_address.full_name or user.username,
            "email": user.email,
            "phone": selected_address.phone or user.phone
        }
    })


@app.route('/verify-payment', methods=['POST'])
@app.route('/verify-razorpay-payment', methods=['POST'])
def verify_razorpay_payment():
    print("VERIFY PAYMENT ROUTE HIT")
    print("Verify payment data:", request.get_json())

    user = get_logged_in_user()
    if not user:
        return json_error("Please login to continue", 401)

    data = request.get_json() or {}
    local_order_id = data.get("pending_order_id") or data.get("local_order_id") or data.get("order_id")
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return json_error("Missing payment details", 400)

    order = Order.query.filter_by(id=local_order_id, user_id=user.id).first()
    if not order:
        return json_error("Order not found", 404)

    if order.payment_status == "Paid":
        return jsonify({
            "success": True,
            "message": "Payment already verified",
            "order_id": order.id,
            "redirect": url_for("order_success", order_id=order.id),
            "redirect_url": url_for("order_success", order_id=order.id)
        })

    if order.razorpay_order_id != razorpay_order_id:
        order.payment_status = "Failed"
        order.order_status = "Payment Failed"
        order.status = "Payment Failed"
        db.session.commit()
        return json_error("Payment verification failed", 400)

    try:
        signature_ok = verify_razorpay_signature(
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature
        )
    except Exception as exc:
        app.logger.error("Razorpay signature verification error for order %s: %s", order.id, exc)
        signature_ok = False

    if not signature_ok:
        order.razorpay_payment_id = razorpay_payment_id
        order.razorpay_signature = razorpay_signature
        order.payment_status = "Failed"
        order.order_status = "Payment Failed"
        order.status = "Payment Failed"
        db.session.commit()
        return json_error("Payment verification failed. Your cart is safe.", 400)

    mark_order_paid(order, razorpay_payment_id, razorpay_signature)

    return jsonify({
        "success": True,
        "message": "Payment verified successfully",
        "order_id": order.id,
        "redirect": url_for("order_success", order_id=order.id),
        "redirect_url": url_for("order_success", order_id=order.id)
    })


@app.route('/razorpay-webhook', methods=['POST'])
def razorpay_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature")

    try:
        if not verify_razorpay_webhook(raw_body, signature):
            return jsonify({"success": False}), 400
    except Exception as exc:
        app.logger.error("Razorpay webhook verification error: %s", exc)
        return jsonify({"success": False}), 400

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return jsonify({"success": False}), 400

    event_name = event.get("event")
    payload = event.get("payload", {})
    payment_entity = (payload.get("payment") or {}).get("entity") or {}
    order_entity = (payload.get("order") or {}).get("entity") or {}

    razorpay_order_id = payment_entity.get("order_id") or order_entity.get("id")
    razorpay_payment_id = payment_entity.get("id")

    if event_name in ("payment.captured", "order.paid") and razorpay_order_id:
        order = Order.query.filter_by(razorpay_order_id=razorpay_order_id).first()
        if order:
            mark_order_paid(order, razorpay_payment_id=razorpay_payment_id, send_emails=True)

    return jsonify({"success": True})


@app.route('/order-success/<int:order_id>')
def order_success(order_id):
    user = get_logged_in_user()
    if not user:
        return redirect('/?show_login=1')

    order = Order.query.filter_by(id=order_id, user_id=user.id).first_or_404()
    return render_template("order_success.html", order=order)


@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'email' not in session:
        if request.method == 'GET':
               return redirect('/')
        return jsonify({"message": "login_required", "redirect": "/checkout"}), 401

    if request.method == 'GET':
        return redirect('/cart')

    return jsonify({
        "success": False,
        "message": "Please use Razorpay payment to place your order."
    }), 400

    user = User.query.filter_by(email=session['email']).first()

    # ✅ VALIDATE phone number is provided
    if not user.phone or user.phone.strip() == "":
        return jsonify({
            "error": True,
            "message": "Please add your phone number before placing order.",
            "error_type": "missing_phone",
            "redirect": "/account"
        })
    data = request.json

    # ✅ Fetch cart items
    cart_items = db.session.execute(text("""
        SELECT product_id, color_id, quantity 
        FROM cart 
        WHERE user_id = :uid
    """), {"uid": user.id}).fetchall()

    # ✅ Fix empty check
    if not cart_items:
        return jsonify({"message": "Cart is empty"})

    total = 0

    data = request.get_json() or {}

# 👉 user addresses
    addresses = Address.query.filter_by(user_id=user.id).all()

    if not addresses:
      return jsonify({"message": "No address found"})

    selected_index = data.get("address_index", 0)

    if selected_index >= len(addresses):
        return jsonify({"message": "Invalid address"})

    selected_address = addresses[selected_index]

    order = Order(
      user_id=user.id,
      address_id=selected_address.id,
      total_amount=0,
      status="Pending",
      tracking_number=f"TRK{user.id}{len(cart_items)}"
   )

    db.session.add(order)
    db.session.commit()

    # ✅ Loop properly
    for item in cart_items:
        pid = item.product_id
        qty = item.quantity

        product = Product.query.get(pid)

        if not product:
            continue

        item_total = product.price * qty
        total += item_total

        db.session.add(OrderItem(
            order_id=order.id,
            product_id=pid,
            color_id=item.color_id,
            quantity=qty,
            price=product.price
        ))

    # ✅ Update total
    order.total_amount = total
    db.session.commit()

    # ✅ Clear cart from DB (IMPORTANT)
    db.session.execute(text("""
        DELETE FROM cart WHERE user_id = :uid
    """), {"uid": user.id})
    db.session.commit()

    return jsonify({"message": "Order placed successfully"})

# ================= TRACK =================
@app.route('/track/<tracking>')
def track(tracking):
    order = Order.query.filter_by(tracking_number=tracking).first()

    if not order:
        return jsonify({"message": "Invalid tracking"}), 404

    return jsonify({
        "status": order.status,
        "tracking": order.tracking_number
    })

# ================= AVATAR =================
import os
from werkzeug.utils import secure_filename
import time

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])

    if not user and 'email' in session:
        user = User.query.filter_by(email=session['email']).first()
        if user:
            session['user_id'] = user.id

    if not user:
        return jsonify({"error": "Not logged in"}), 401

    file = request.files.get('avatar')

    if not file:
        return jsonify({"error": "No file"}), 400

    # 🔥 Upload to Cloudinary
    result = cloudinary.uploader.upload(file, folder="avatars")

    # ✅ Save URL in DB
    user.avatar = result["secure_url"]

    db.session.commit()

    return jsonify({
        "url": result["secure_url"]
    })

# ================= ACCOUNT =================
@app.route('/account')
def account():
    if 'email' not in session:
        return redirect('/?show_login=1')

    user = User.query.filter_by(email=session['email']).first()
    return render_template("account.html", user=user)

# ================= UPDATE PROFILE =================
@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    data = request.get_json()
    user = User.query.filter_by(email=session['email']).first()

    user.username = data.get("name")   # ✅ FIXED
    user.email = data.get("email")

    if data.get("password"):
        user.password = data.get("password")

    db.session.commit()

    session['user'] = user.username   # ✅ FIXED
    session['email'] = user.email

    return jsonify({"message": "Profile updated"})


# ================= API ROUTES =================
@app.route('/api/profile', methods=['PUT'])
def api_update_profile():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    try:
        data = request.get_json()
        user = User.query.filter_by(email=session['email']).first()
        
        if not user:
            return jsonify({"error": "User not found"}), 404

        # ✅ Update name (optional)
        if data.get("name") and data.get("name").strip() != "":
            user.username = data.get("name").strip()

        # ✅ Update email with uniqueness check
        if data.get("email") and data.get("email").strip() != "":
            new_email = data.get("email").strip()
            # Check if email already exists (and is not the current user's email)
            if new_email != user.email:
                existing_user = User.query.filter_by(email=new_email).first()
                if existing_user:
                    return jsonify({"error": "Email already registered"}), 400
            user.email = new_email

        # ✅ Update phone (optional)
        if data.get("phone"):
            user.phone = data.get("phone").strip()

        # ✅ Update DOB (optional)
        dob = data.get("dob")
        if dob and dob.strip() != "":
            try:
                user.dob = datetime.strptime(dob, '%Y-%m-%d').date()
                print(f"✅ DOB set to: {user.dob}")
            except ValueError as e:
                return jsonify({"error": f"Invalid date format"}), 400

        # ✅ Handle password change (optional)
        current_password = data.get("current_password")
        new_password = data.get("new_password")

        if new_password and new_password.strip() != "":
            # Must provide current password to change password
            if not current_password or current_password.strip() == "":
                return jsonify({"error": "Current password required to change password"}), 400
            
            # Verify current password
            if not check_password_hash(user.password, current_password):
                return jsonify({"error": "Current password is incorrect"}), 400
            
            # Hash and set new password
            user.password = generate_password_hash(new_password)
            print(f"✅ Password updated for user: {user.email}")

        # Commit all changes
        db.session.commit()
        print(f"✅ Profile updated for user: {user.email}")

        # Update session with new email if it changed
        session['email'] = user.email

        return jsonify({
            "message": "Profile updated successfully",
            "user": {
                "username": user.username,
                "email": user.email,
                "phone": user.phone,
                "dob": user.dob.strftime('%Y-%m-%d') if user.dob else None
            }
        })
    
    except Exception as e:
        print(f"❌ Error updating profile: {e}")
        db.session.rollback()
        return jsonify({"error": f"Error: {str(e)}"}), 500

@app.route('/api/verify-phone', methods=['POST'])
def api_verify_phone():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    user.phone_verified = True
    db.session.commit()

    return jsonify({"message": "Phone verified"})


import random

@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    """
    Send OTP to user's phone (for testing, OTP is printed to console)
    Free alternative: User can read OTP from console/logs
    """
    data = request.get_json()
    phone = data.get("phone")

    if not phone or phone.strip() == "":
        return jsonify({"message": "Phone number required"}), 400

    # Generate OTP
    otp = random.randint(100000, 999999)  # 6-digit OTP

    # Store in session
    session['otp'] = str(otp)
    session['otp_phone'] = phone
    
    # 🔥 For development/testing: Print to console and also return it
    print(f"\n{'='*50}")
    print(f"📱 OTP for {phone}: {otp}")
    print(f"{'='*50}\n")

    return jsonify({
        "message": f"OTP sent to {phone}",
        "otp": str(otp)  # 🔥 For testing during development
    })

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """
    Verify OTP entered by user
    """
    data = request.get_json()
    entered_otp = data.get("otp")

    if not entered_otp:
        return jsonify({"message": "OTP required"}), 400

    session_otp = session.get('otp')
    
    if str(entered_otp).strip() == str(session_otp).strip():
        try:
            user = User.query.filter_by(email=session['email']).first()
            if not user:
                return jsonify({"message": "User not found"}), 404
            
            user.phone_verified = True
            user.phone = session.get('otp_phone', user.phone)  # Update phone if not already there
            db.session.commit()
            
            print(f"✅ Phone verified for user: {user.email}")

            return jsonify({
                "message": "Phone verified successfully",
                "verified": True
            })
        except Exception as e:
            print(f"❌ Error verifying phone: {e}")
            return jsonify({"message": f"Error: {str(e)}"}), 500
    else:
        return jsonify({"message": "Invalid OTP"}), 400


@app.route('/api/verify-phone-direct', methods=['POST'])
def verify_phone_direct():
    """
    Direct phone verification without OTP (free option)
    Just verify the phone number without SMS
    """
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    data = request.get_json()
    phone = data.get("phone")

    if not phone or phone.strip() == "":
        return jsonify({"message": "Phone number required"}), 400

    try:
        user = User.query.filter_by(email=session['email']).first()
        if not user:
            return jsonify({"message": "User not found"}), 404
        
        user.phone = phone
        user.phone_verified = True
        db.session.commit()
        
        print(f"✅ Phone verified directly for user: {user.email} - {phone}")

        return jsonify({
            "message": "Phone verified successfully (no OTP required)",
            "verified": True
        })
    except Exception as e:
        print(f"❌ Error verifying phone: {e}")
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

@app.route('/api/addresses', methods=['GET', 'POST'])
def api_addresses():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()

    if request.method == 'GET':
        addresses = Address.query.filter_by(user_id=user.id).all()
        return jsonify([{
            "id": a.id,
            "full_name": a.full_name,
            "phone": a.phone,
            "address_line": a.address_line,
            "city": a.city,
            "state": a.state,
            "pincode": a.pincode
        } for a in addresses])

    data = request.get_json()
    address = Address(
        user_id=user.id,
        full_name=data['full_name'],
        phone=data['phone'],
        address_line=data['address_line'],
        city=data['city'],
        state=data['state'],
        pincode=data['pincode']
    )
    db.session.add(address)
    db.session.commit()
    return jsonify({"message": "Address added"})

@app.route('/api/addresses/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_address(id):
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    address = Address.query.filter_by(id=id, user_id=user.id).first()
    if not address:
        return jsonify({"message": "Address not found"}), 404

    if request.method == 'GET':
        return jsonify({
            "id": address.id,
            "full_name": address.full_name,
            "phone": address.phone,
            "address_line": address.address_line,
            "city": address.city,
            "state": address.state,
            "pincode": address.pincode
        })

    if request.method == 'PUT':
        data = request.get_json()
        address.full_name = data['full_name']
        address.phone = data['phone']
        address.address_line = data['address_line']
        address.city = data['city']
        address.state = data['state']
        address.pincode = data['pincode']
        db.session.commit()
        return jsonify({"message": "Address updated"})

    if request.method == 'DELETE':
        db.session.delete(address)
        db.session.commit()
        return jsonify({"message": "Address deleted"})

@app.route('/api/wallet', methods=['GET'])
def api_wallet():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    transactions = WalletTransaction.query.filter_by(user_id=user.id).order_by(WalletTransaction.created_at.desc()).all()
    return jsonify({
        "balance": user.balance,
        "transactions": [{
            "id": t.id,
            "amount": t.amount,
            "type": t.type,
            "description": t.description,
            "created_at": t.created_at.isoformat()
        } for t in transactions]
    })

@app.route('/api/wishlist', methods=['GET'])
def api_wishlist():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    rows = db.session.execute(text("""
        SELECT p.id, p.name, p.price, w.color_id,
               co.name AS color_name,
               COALESCE(
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND w.color_id IS NOT NULL
                      AND pi.color_id = w.color_id AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND w.color_id IS NOT NULL
                      AND pi.color_id = w.color_id
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND pi.color_id IS NULL AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id AND pi.is_primary = TRUE
                    ORDER BY pi.id LIMIT 1),
                   (SELECT pi.image_url FROM product_images pi
                    WHERE pi.product_id = p.id
                    ORDER BY pi.id LIMIT 1)
               ) AS image_url
        FROM wishlist w
        JOIN products p ON w.product_id = p.id
        LEFT JOIN colors co ON w.color_id = co.id
        WHERE w.user_id=:uid
    """), {"uid": user.id}).fetchall()

    return jsonify([{
        "id": row.id,
        "name": row.name,
        "price": row.price,
        "color_id": row.color_id,
        "color_name": row.color_name,
        "images": [{"image_url": row.image_url}] if row.image_url else []
    } for row in rows])

@app.route('/api/wishlist/<int:product_id>', methods=['DELETE'])
def api_remove_wishlist(product_id):
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    color_id = request_color_id()

    result = db.session.execute(text("""
        DELETE FROM wishlist
        WHERE user_id=:uid AND product_id=:pid
        AND ((color_id IS NULL AND :cid IS NULL) OR color_id=:cid)
    """), {"uid": user.id, "pid": product_id, "cid": color_id})
    db.session.commit()

    if result.rowcount:
        return jsonify({"message": "Removed from wishlist"})

    return jsonify({"message": "Not in wishlist"}), 404

@app.route('/api/payment-methods', methods=['GET', 'POST'])
def api_payment_methods():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()

    if request.method == 'GET':
        payments = PaymentMethod.query.filter_by(user_id=user.id).all()
        return jsonify([{
            "id": p.id,
            "type": p.type,
            "provider": p.provider,
            "last_four": p.last_four,
            "expiry_month": p.expiry_month,
            "expiry_year": p.expiry_year,
            "is_default": p.is_default
        } for p in payments])

    data = request.get_json()
    payment = PaymentMethod(
        user_id=user.id,
        type=data['type'],
        provider=data['provider'],
        last_four=data['last_four'],
        expiry_month=int(data['expiry_month']),
        expiry_year=int(data['expiry_year'])
    )
    db.session.add(payment)
    db.session.commit()
    return jsonify({"message": "Payment method added"})

@app.route('/api/payment-methods/<int:id>', methods=['DELETE'])
def api_delete_payment(id):
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    payment = PaymentMethod.query.filter_by(id=id, user_id=user.id).first()
    if not payment:
        return jsonify({"message": "Payment method not found"}), 404

    db.session.delete(payment)
    db.session.commit()
    return jsonify({"message": "Payment method deleted"})

@app.route('/api/tickets', methods=['GET', 'POST'])
def api_tickets():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()

    if request.method == 'GET':
        tickets = Ticket.query.filter_by(user_id=user.id).order_by(Ticket.created_at.desc()).all()
        return jsonify([{
            "id": t.id,
            "subject": t.subject,
            "message": t.message,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat()
        } for t in tickets])

    data = request.get_json() or {}
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()
    if not subject or not message:
        return jsonify({"message": "Subject and message are required"}), 400

    ticket = Ticket(
        user_id=user.id,
        subject=subject,
        message=message
    )
    db.session.add(ticket)
    db.session.commit()

    body = (
        "New support issue submitted from Belt Purse account page.\n\n"
        f"Name: {user.username}\n"
        f"Email: {user.email}\n"
        f"Phone: {user.phone or 'Not provided'}\n"
        f"Order ID: {data.get('order_id') or 'Not provided'}\n"
        f"Issue Type: {data.get('category') or subject}\n"
        f"Ticket ID: {ticket.id}\n"
        f"Date/Time: {format_support_timestamp()}\n\n"
        f"Message:\n{message}"
    )
    admin_sent, _ = send_resend_email_safe(f"New Support Issue - {subject}", body)
    send_resend_email_safe(
        "We received your issue - BeltPurse",
        "We have received your issue and our team will contact you soon.",
        to_email=user.email
    )

    if not admin_sent:
        return jsonify({"message": "Ticket created, but email could not be sent right now"}), 500

    return jsonify({"message": "Ticket created"})

@app.route('/api/terms', methods=['GET'])
def api_terms():
    # Return static terms content
    terms = """
Terms and Conditions

1. Acceptance of Terms
By accessing and using this website, you accept and agree to be bound by the terms and conditions of this agreement.

2. Use License
Permission is granted to temporarily download one copy of the materials on our website for personal, non-commercial transitory viewing only.

3. Disclaimer
The materials on our website are provided on an 'as is' basis. We make no warranties, expressed or implied.

4. Limitations
In no event shall we be liable for any damages arising out of the use or inability to use the materials on our website.

5. Privacy Policy
Your privacy is important to us. Please review our Privacy Policy, which also governs your use of the website.
"""
    return terms

@app.route('/api/delete-account', methods=['DELETE'])
def api_delete_account():
    if 'email' not in session:
        return jsonify({"message": "Not logged in"}), 401

    user = User.query.filter_by(email=session['email']).first()
    # In a real app, you'd want to soft delete or archive data
    db.session.delete(user)
    db.session.commit()
    session.clear()
    return jsonify({"message": "Account deleted"})


@app.route('/blogs')
def blogs():
    blogs = Blog.query.filter_by(is_published=True)\
                      .order_by(
                          Blog.blog_date.is_(None),
                          Blog.blog_date.desc(),
                          Blog.created_at.is_(None),
                          Blog.created_at.desc(),
                          Blog.id.desc()
                      )\
                      .all()
    return render_template("blogs.html", blogs=blogs)


@app.route('/blog/<slug>')
def blog_detail(slug):
    blog = Blog.query.filter_by(slug=slug).first()

    if not blog:
        return "Blog not found", 404

    return render_template("blog_detail.html", blog=blog)



@app.route('/shipping-policy')
def shipping_policy():
    return render_template("shipping.html")

@app.route('/exchange-policy')
@app.route('/return-policy')
def exchange_policy():
    return render_template("returns.html")

@app.route('/privacy-policy')
def privacy_policy():
    return render_template("privacy.html")

@app.route('/terms')
def terms():
    return render_template("terms.html")


@app.route('/robots.txt')
def robots_txt():
    body = "\n".join([
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /secure-admin-portal-9821",
        "Sitemap: https://www.belt-purse.com/sitemap.xml",
        ""
    ])
    response = make_response(body)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@app.route('/sitemap.xml')
def sitemap_xml():
    base_url = "https://www.belt-purse.com"
    today = datetime.utcnow().strftime("%Y-%m-%d")
    pages = [
        {"loc": f"{base_url}/", "changefreq": "weekly", "priority": "1.0", "lastmod": today},
        {"loc": f"{base_url}/products-page", "changefreq": "weekly", "priority": "0.9", "lastmod": today},
        {"loc": f"{base_url}/about", "changefreq": "monthly", "priority": "0.6", "lastmod": today},
        {"loc": f"{base_url}/blogs", "changefreq": "weekly", "priority": "0.7", "lastmod": today},
        {"loc": f"{base_url}/shipping-policy", "changefreq": "monthly", "priority": "0.4", "lastmod": today},
        {"loc": f"{base_url}/exchange-policy", "changefreq": "monthly", "priority": "0.4", "lastmod": today},
        {"loc": f"{base_url}/privacy-policy", "changefreq": "yearly", "priority": "0.3", "lastmod": today},
        {"loc": f"{base_url}/terms", "changefreq": "yearly", "priority": "0.3", "lastmod": today},
    ]

    products = Product.query.filter(
        db.or_(Product.is_archived == False, Product.is_archived.is_(None))
    ).all()
    for product in products:
        pages.append({
            "loc": f"{base_url}/product/{product.id}",
            "changefreq": "weekly",
            "priority": "0.8",
            "lastmod": today
        })

    blogs = Blog.query.filter_by(is_published=True).all()
    for blog in blogs:
        if not blog.slug:
            continue
        pages.append({
            "loc": f"{base_url}/blog/{blog.slug}",
            "changefreq": "monthly",
            "priority": "0.6",
            "lastmod": (blog.updated_at or blog.created_at or datetime.utcnow()).strftime("%Y-%m-%d")
        })

    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for page in pages:
        xml.append("  <url>")
        xml.append(f"    <loc>{html.escape(page['loc'])}</loc>")
        xml.append(f"    <lastmod>{page['lastmod']}</lastmod>")
        xml.append(f"    <changefreq>{page['changefreq']}</changefreq>")
        xml.append(f"    <priority>{page['priority']}</priority>")
        xml.append("  </url>")
    xml.append("</urlset>")

    response = make_response("\n".join(xml))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response

# ================= LOGOUT =================
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ================= RUN =================
if __name__ == '__main__':
    app.run()
