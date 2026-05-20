"""add color hex code

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    columns = _column_names("colors")

    if "hex_code" not in columns:
        op.add_column("colors", sa.Column("hex_code", sa.String(length=20), nullable=True))

    op.execute("""
        UPDATE colors
        SET hex_code = code
        WHERE (hex_code IS NULL OR hex_code = '')
          AND code IS NOT NULL
          AND code != ''
    """)


def downgrade():
    columns = _column_names("colors")
    if "hex_code" in columns:
        op.drop_column("colors", "hex_code")
