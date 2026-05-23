"""add coupons and order amount fields

Revision ID: a8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
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
    if "coupons" not in _table_names():
        op.create_table(
            "coupons",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("discount_type", sa.String(length=20), nullable=True),
            sa.Column("discount_value", sa.Float(), nullable=False),
            sa.Column("min_order_amount", sa.Float(), nullable=True),
            sa.Column("max_discount_amount", sa.Float(), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("usage_limit", sa.Integer(), nullable=True),
            sa.Column("used_count", sa.Integer(), nullable=True),
            sa.Column("per_user_limit", sa.Integer(), nullable=True),
            sa.Column("first_order_only", sa.Boolean(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
    else:
        coupon_columns = _column_names("coupons")
        with op.batch_alter_table("coupons") as batch_op:
            if "discount_type" not in coupon_columns:
                batch_op.add_column(sa.Column("discount_type", sa.String(length=20), nullable=True))
            if "discount_value" not in coupon_columns:
                batch_op.add_column(sa.Column("discount_value", sa.Float(), nullable=True))
            if "min_order_amount" not in coupon_columns:
                batch_op.add_column(sa.Column("min_order_amount", sa.Float(), nullable=True))
            if "max_discount_amount" not in coupon_columns:
                batch_op.add_column(sa.Column("max_discount_amount", sa.Float(), nullable=True))
            if "valid_from" not in coupon_columns:
                batch_op.add_column(sa.Column("valid_from", sa.Date(), nullable=True))
            if "valid_until" not in coupon_columns:
                batch_op.add_column(sa.Column("valid_until", sa.Date(), nullable=True))
            if "usage_limit" not in coupon_columns:
                batch_op.add_column(sa.Column("usage_limit", sa.Integer(), nullable=True))
            if "used_count" not in coupon_columns:
                batch_op.add_column(sa.Column("used_count", sa.Integer(), nullable=True))
            if "per_user_limit" not in coupon_columns:
                batch_op.add_column(sa.Column("per_user_limit", sa.Integer(), nullable=True))
            if "updated_at" not in coupon_columns:
                batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    if "coupon_usage" not in _table_names():
        op.create_table(
            "coupon_usage",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("coupon_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("discount_amount", sa.Float(), nullable=False),
            sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    columns = _column_names("orders")
    with op.batch_alter_table("orders") as batch_op:
        if "coupon_code" not in columns:
            batch_op.add_column(sa.Column("coupon_code", sa.String(length=50), nullable=True))
        if "discount_amount" not in columns:
            batch_op.add_column(sa.Column("discount_amount", sa.Float(), nullable=True))
        if "subtotal_amount" not in columns:
            batch_op.add_column(sa.Column("subtotal_amount", sa.Float(), nullable=True))
        if "final_amount" not in columns:
            batch_op.add_column(sa.Column("final_amount", sa.Float(), nullable=True))


def downgrade():
    columns = _column_names("orders")
    with op.batch_alter_table("orders") as batch_op:
        if "final_amount" in columns:
            batch_op.drop_column("final_amount")
        if "subtotal_amount" in columns:
            batch_op.drop_column("subtotal_amount")
        if "discount_amount" in columns:
            batch_op.drop_column("discount_amount")
        if "coupon_code" in columns:
            batch_op.drop_column("coupon_code")

    if "coupon_usage" in _table_names():
        op.drop_table("coupon_usage")

    if "coupons" in _table_names():
        op.drop_table("coupons")
