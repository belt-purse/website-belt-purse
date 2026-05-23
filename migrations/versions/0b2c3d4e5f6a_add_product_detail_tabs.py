"""add product detail tab fields

Revision ID: 0b2c3d4e5f6a
Revises: f6a7b8c9d0e1
Create Date: 2026-05-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0b2c3d4e5f6a"
down_revision = "f6a7b8c9d0e1"
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

    if "composition_care" not in columns:
        op.add_column("products", sa.Column("composition_care", sa.Text(), nullable=True))

    if "additional_details" not in columns:
        op.add_column("products", sa.Column("additional_details", sa.Text(), nullable=True))


def downgrade():
    columns = _column_names("products")

    if "additional_details" in columns:
        op.drop_column("products", "additional_details")

    if "composition_care" in columns:
        op.drop_column("products", "composition_care")
