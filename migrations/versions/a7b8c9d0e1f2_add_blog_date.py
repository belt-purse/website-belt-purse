"""add blog date

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
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
    if "blog_date" not in _column_names("blog"):
        op.add_column("blog", sa.Column("blog_date", sa.Date(), nullable=True))


def downgrade():
    if "blog_date" in _column_names("blog"):
        op.drop_column("blog", "blog_date")
