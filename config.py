import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Security
    SECRET_KEY = os.environ.get("SECRET_KEY", "fallback-secret-key")

    # Database selection is environment-driven and safe by default:
    # - Local development can use the live database only when DATABASE_URL is
    #   pasted into the local .env file.
    # - Railway/Render should keep using their platform DATABASE_URL variable.
    # - If DATABASE_URL is missing, the app falls back to local SQLite.
    # Never hardcode a real database URL in this file.
    db_url = os.environ.get("DATABASE_URL")

    if db_url:
        # Some platforms expose postgres://, but SQLAlchemy expects postgresql://.
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

        SQLALCHEMY_DATABASE_URI = db_url
    else:
        # Safe local-only fallback used when no DATABASE_URL is configured.
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "instance/site.db")

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Homepage/index product display limits. Admins choose products; developers
    # control these limits from code/config.
    INDEX_BELTS_LIMIT = int(os.environ.get("INDEX_BELTS_LIMIT", 3))
    INDEX_WALLETS_LIMIT = int(os.environ.get("INDEX_WALLETS_LIMIT", 5))
    INDEX_MOBILE_PRODUCTS_LIMIT = int(os.environ.get("INDEX_MOBILE_PRODUCTS_LIMIT", 4))

    # File uploads
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static/images")

    # Cloudinary
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

    # Razorpay
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET")

    # Email / SMTP fallback. Order emails use Resend when RESEND_API_KEY is
    # configured; these settings keep Flask-Mail ready for SMTP deployments.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes", "on")
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() in ("1", "true", "yes", "on")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or MAIL_USERNAME
