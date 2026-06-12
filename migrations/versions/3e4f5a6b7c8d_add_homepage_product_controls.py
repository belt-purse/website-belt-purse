"""add homepage product controls

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-06-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3e4f5a6b7c8d"
down_revision = "2d3e4f5a6b7c"
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

    if "show_on_homepage" not in columns:
        op.add_column(
            "products",
            sa.Column("show_on_homepage", sa.Boolean(), server_default=sa.false(), nullable=True),
        )

    if "homepage_sort_order" not in columns:
        op.add_column(
            "products",
            sa.Column("homepage_sort_order", sa.Integer(), server_default="0", nullable=True),
        )

    op.execute("UPDATE products SET show_on_homepage = FALSE WHERE show_on_homepage IS NULL")
    op.execute("UPDATE products SET homepage_sort_order = 0 WHERE homepage_sort_order IS NULL")


def downgrade():
    columns = _column_names("products")

    if "homepage_sort_order" in columns:
        op.drop_column("products", "homepage_sort_order")

    if "show_on_homepage" in columns:
        op.drop_column("products", "show_on_homepage")
