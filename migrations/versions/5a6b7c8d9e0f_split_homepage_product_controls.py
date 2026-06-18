"""split homepage product controls by device

Revision ID: 5a6b7c8d9e0f
Revises: 3e4f5a6b7c8d
Create Date: 2026-06-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "5a6b7c8d9e0f"
down_revision = "3e4f5a6b7c8d"
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    columns = _column_names("products")

    if "show_on_homepage_desktop" not in columns:
        op.add_column(
            "products",
            sa.Column("show_on_homepage_desktop", sa.Boolean(), server_default=sa.false(), nullable=True),
        )

    if "homepage_desktop_position" not in columns:
        op.add_column(
            "products",
            sa.Column("homepage_desktop_position", sa.Integer(), nullable=True),
        )

    if "show_on_homepage_mobile" not in columns:
        op.add_column(
            "products",
            sa.Column("show_on_homepage_mobile", sa.Boolean(), server_default=sa.false(), nullable=True),
        )

    if "homepage_mobile_position" not in columns:
        op.add_column(
            "products",
            sa.Column("homepage_mobile_position", sa.Integer(), nullable=True),
        )

    columns = _column_names("products")
    if "show_on_homepage" in columns:
        op.execute("""
            UPDATE products
            SET show_on_homepage_desktop = show_on_homepage
            WHERE show_on_homepage = TRUE
              AND COALESCE(show_on_homepage_desktop, FALSE) = FALSE
        """)
        op.execute("""
            UPDATE products
            SET show_on_homepage_mobile = show_on_homepage
            WHERE show_on_homepage = TRUE
              AND COALESCE(show_on_homepage_mobile, FALSE) = FALSE
        """)

    if "homepage_sort_order" in columns:
        op.execute("""
            UPDATE products
            SET homepage_desktop_position = NULLIF(homepage_sort_order, 0)
            WHERE homepage_desktop_position IS NULL
              AND COALESCE(show_on_homepage_desktop, FALSE) = TRUE
        """)
        op.execute("""
            UPDATE products
            SET homepage_mobile_position = NULLIF(homepage_sort_order, 0)
            WHERE homepage_mobile_position IS NULL
              AND COALESCE(show_on_homepage_mobile, FALSE) = TRUE
        """)

    op.execute("UPDATE products SET show_on_homepage_desktop = FALSE WHERE show_on_homepage_desktop IS NULL")
    op.execute("UPDATE products SET show_on_homepage_mobile = FALSE WHERE show_on_homepage_mobile IS NULL")


def downgrade():
    columns = _column_names("products")

    if "homepage_mobile_position" in columns:
        op.drop_column("products", "homepage_mobile_position")

    if "show_on_homepage_mobile" in columns:
        op.drop_column("products", "show_on_homepage_mobile")

    if "homepage_desktop_position" in columns:
        op.drop_column("products", "homepage_desktop_position")

    if "show_on_homepage_desktop" in columns:
        op.drop_column("products", "show_on_homepage_desktop")
