"""add homepage media mobile public id

Revision ID: aa0b1c2d3e4f
Revises: a9d0e1f2a3b4
Create Date: 2026-05-23 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "aa0b1c2d3e4f"
down_revision = "a9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "homepage_media" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("homepage_media")}
    if "mobile_public_id" not in columns:
        with op.batch_alter_table("homepage_media") as batch_op:
            batch_op.add_column(sa.Column("mobile_public_id", sa.String(length=255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "homepage_media" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("homepage_media")}
    if "mobile_public_id" in columns:
        with op.batch_alter_table("homepage_media") as batch_op:
            batch_op.drop_column("mobile_public_id")
