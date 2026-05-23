"""add homepage media

Revision ID: a9d0e1f2a3b4
Revises: a8c9d0e1f2a3
Create Date: 2026-05-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a9d0e1f2a3b4"
down_revision = "a8c9d0e1f2a3"
branch_labels = None
depends_on = None


def _table_names():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if "homepage_media" not in _table_names():
        op.create_table(
            "homepage_media",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("media_type", sa.String(length=30), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("subtitle", sa.String(length=500), nullable=True),
            sa.Column("button_text", sa.String(length=100), nullable=True),
            sa.Column("button_link", sa.String(length=500), nullable=True),
            sa.Column("media_url", sa.String(length=500), nullable=False),
            sa.Column("mobile_media_url", sa.String(length=500), nullable=True),
            sa.Column("public_id", sa.String(length=255), nullable=True),
            sa.Column("alt_text", sa.String(length=255), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        return

    columns = _column_names("homepage_media")
    with op.batch_alter_table("homepage_media") as batch_op:
        if "subtitle" not in columns:
            batch_op.add_column(sa.Column("subtitle", sa.String(length=500), nullable=True))
        if "button_text" not in columns:
            batch_op.add_column(sa.Column("button_text", sa.String(length=100), nullable=True))
        if "button_link" not in columns:
            batch_op.add_column(sa.Column("button_link", sa.String(length=500), nullable=True))
        if "mobile_media_url" not in columns:
            batch_op.add_column(sa.Column("mobile_media_url", sa.String(length=500), nullable=True))


def downgrade():
    if "homepage_media" in _table_names():
        op.drop_table("homepage_media")
