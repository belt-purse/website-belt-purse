"""upgrade coupon system

Revision ID: f7b8c9d0e1f2
Revises: 2d3e4f5a6b7c
Create Date: 2026-06-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f7b8c9d0e1f2"
down_revision = "2d3e4f5a6b7c"
branch_labels = None
depends_on = None


def _table_names():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name, column):
    if column.name not in _column_names(table_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)


def upgrade():
    if "coupons" in _table_names():
        _add_column_if_missing("coupons", sa.Column("description", sa.Text(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("coupon_type", sa.String(length=50), nullable=True))
        _add_column_if_missing("coupons", sa.Column("applicable_category_id", sa.Integer(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("applicable_category", sa.String(length=50), nullable=True))
        _add_column_if_missing("coupons", sa.Column("min_quantity_required", sa.Integer(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("required_product_price", sa.Float(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("final_payable_amount", sa.Float(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("one_time_per_customer", sa.Boolean(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("auto_apply", sa.Boolean(), nullable=True))
        _add_column_if_missing("coupons", sa.Column("allow_combination", sa.Boolean(), nullable=True))

        op.execute("UPDATE coupons SET coupon_type = 'fixed_amount' WHERE coupon_type IS NULL OR coupon_type = ''")
        op.execute("UPDATE coupons SET applicable_category = 'all' WHERE applicable_category IS NULL OR applicable_category = ''")
        op.execute("UPDATE coupons SET one_time_per_customer = TRUE WHERE one_time_per_customer IS NULL")
        op.execute("UPDATE coupons SET auto_apply = FALSE WHERE auto_apply IS NULL")
        op.execute("UPDATE coupons SET allow_combination = FALSE WHERE allow_combination IS NULL")

    if "coupon_products" not in _table_names():
        op.create_table(
            "coupon_products",
            sa.Column("coupon_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"]),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.PrimaryKeyConstraint("coupon_id", "product_id"),
        )

    if "orders" in _table_names():
        _add_column_if_missing("orders", sa.Column("applied_coupon_code", sa.String(length=50), nullable=True))
        _add_column_if_missing("orders", sa.Column("coupon_discount_amount", sa.Float(), nullable=True))


def downgrade():
    if "coupon_products" in _table_names():
        op.drop_table("coupon_products")

    if "coupons" in _table_names():
        columns = _column_names("coupons")
        with op.batch_alter_table("coupons") as batch_op:
            for column_name in (
                "allow_combination",
                "auto_apply",
                "one_time_per_customer",
                "final_payable_amount",
                "required_product_price",
                "min_quantity_required",
                "applicable_category",
                "applicable_category_id",
                "coupon_type",
                "description",
            ):
                if column_name in columns:
                    batch_op.drop_column(column_name)

    if "orders" in _table_names():
        columns = _column_names("orders")
        with op.batch_alter_table("orders") as batch_op:
            if "coupon_discount_amount" in columns:
                batch_op.drop_column("coupon_discount_amount")
            if "applied_coupon_code" in columns:
                batch_op.drop_column("applied_coupon_code")
