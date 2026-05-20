"""add product type and requires size fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
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

    if "product_type" not in columns:
        op.add_column(
            "products",
            sa.Column("product_type", sa.String(length=50), server_default="belt", nullable=True),
        )

    if "requires_size" not in columns:
        op.add_column(
            "products",
            sa.Column("requires_size", sa.Boolean(), server_default=sa.true(), nullable=True),
        )

    op.execute("UPDATE products SET product_type = 'belt' WHERE product_type IS NULL OR product_type = ''")
    op.execute("UPDATE products SET requires_size = TRUE WHERE requires_size IS NULL")


def downgrade():
    columns = _column_names("products")

    if "requires_size" in columns:
        op.drop_column("products", "requires_size")

    if "product_type" in columns:
        op.drop_column("products", "product_type")
