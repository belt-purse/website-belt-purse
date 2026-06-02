"""add product size type

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b, aa0b1c2d3e4f
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2d3e4f5a6b7c"
down_revision = ("1c2d3e4f5a6b", "aa0b1c2d3e4f")
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

    if "size_type" not in columns:
        op.add_column(
            "products",
            sa.Column("size_type", sa.String(length=30), server_default="specific", nullable=True),
        )

    op.execute("UPDATE products SET size_type = 'specific' WHERE size_type IS NULL OR size_type = ''")


def downgrade():
    columns = _column_names("products")

    if "size_type" in columns:
        op.drop_column("products", "size_type")
