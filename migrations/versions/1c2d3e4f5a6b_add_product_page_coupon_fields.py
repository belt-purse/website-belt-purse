"""add product page coupon fields

Revision ID: 1c2d3e4f5a6b
Revises: 0b2c3d4e5f6a
Create Date: 2026-05-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1c2d3e4f5a6b"
down_revision = "0b2c3d4e5f6a"
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    columns = _column_names("coupons")

    if "show_on_product_page" not in columns:
        op.add_column(
            "coupons",
            sa.Column("show_on_product_page", sa.Boolean(), server_default=sa.false(), nullable=True),
        )

    if "product_page_priority" not in columns:
        op.add_column(
            "coupons",
            sa.Column("product_page_priority", sa.Integer(), server_default="0", nullable=True),
        )

    op.execute("""
        UPDATE coupons
        SET show_on_product_page = TRUE,
            product_page_priority = CASE
                WHEN UPPER(code) = 'FIRST30' THEN 100
                WHEN UPPER(code) = 'FIRST50' THEN 50
                ELSE COALESCE(product_page_priority, 0)
            END
        WHERE UPPER(code) IN ('FIRST30', 'FIRST50')
    """)


def downgrade():
    columns = _column_names("coupons")

    if "product_page_priority" in columns:
        op.drop_column("coupons", "product_page_priority")

    if "show_on_product_page" in columns:
        op.drop_column("coupons", "show_on_product_page")
