"""One-time, non-destructive SQLite to Railway PostgreSQL data importer."""

import argparse
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DB = BASE_DIR / "instance" / "site.db"
DOTENV_PATH = BASE_DIR / ".env"
CONFIRMATION_PHRASE = "YES_TO_IMPORT"
SYSTEM_TABLES = {"alembic_version"}

# Used only as a stable tie-breaker. Foreign keys determine the real order.
PREFERRED_TABLE_ORDER = [
    "users",
    "category",
    "categories",
    "colors",
    "sizes",
    "tag",
    "tags",
    "products",
    "product_images",
    "product_videos",
    "product_colors",
    "product_sizes",
    "product_tags",
    "reviews",
    "addresses",
    "payment_methods",
    "orders",
    "order_items",
    "cart",
    "wishlist",
    "blog",
    "blogs",
    "warranty",
    "warranties",
    "wallet_transactions",
    "tickets",
    "coupons",
    "homepage_media",
    "auto_slider_images",
    "hero_images",
    "crafted_videos",
]
PREFERRED_RANK = {name: index for index, name in enumerate(PREFERRED_TABLE_ORDER)}


def parse_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(database_url):
    if database_url and database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url and database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def visible_database_url(database_url):
    return make_url(database_url).render_as_string(hide_password=True)


def table_sort_key(table_name):
    return (PREFERRED_RANK.get(table_name, len(PREFERRED_RANK)), table_name)


def is_copyable_table(table_name):
    return not table_name.startswith("sqlite_") and table_name not in SYSTEM_TABLES


def dependency_order(inspector, table_names):
    table_names = set(table_names)
    dependencies = {table_name: set() for table_name in table_names}
    dependents = defaultdict(set)

    for table_name in table_names:
        for foreign_key in inspector.get_foreign_keys(table_name):
            parent = foreign_key.get("referred_table")
            if parent in table_names and parent != table_name:
                dependencies[table_name].add(parent)
                dependents[parent].add(table_name)

    ready = sorted(
        [name for name, parents in dependencies.items() if not parents],
        key=table_sort_key,
    )
    ordered = []

    while ready:
        table_name = ready.pop(0)
        ordered.append(table_name)
        for child in sorted(dependents[table_name], key=table_sort_key):
            dependencies[child].discard(table_name)
            if not dependencies[child] and child not in ordered and child not in ready:
                ready.append(child)
        ready.sort(key=table_sort_key)

    unresolved = sorted(table_names.difference(ordered), key=table_sort_key)
    if unresolved:
        print(
            "WARNING: cyclic or unresolved foreign-key dependencies detected for: "
            + ", ".join(unresolved)
        )
        ordered.extend(unresolved)

    return ordered


def identity_columns(inspector, table_name, common_columns):
    primary_keys = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
    if primary_keys and all(name in common_columns for name in primary_keys):
        return primary_keys, "primary key"

    for constraint in inspector.get_unique_constraints(table_name):
        columns = constraint.get("column_names") or []
        if columns and all(name in common_columns for name in columns):
            return columns, "unique constraint"

    return common_columns, "full row"


def row_key(row, column_names):
    return tuple(row[name] for name in column_names)


def reset_postgres_sequences(connection, target_tables):
    if connection.dialect.name != "postgresql":
        return

    print("\nUpdating PostgreSQL sequences after explicit primary-key imports...")
    for table in target_tables:
        for column in table.primary_key.columns:
            sequence_name = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.fullname, "column_name": column.name},
            ).scalar_one_or_none()
            if not sequence_name:
                continue

            maximum = connection.execute(select(func.max(column))).scalar_one_or_none()
            if maximum is None:
                continue

            connection.execute(
                text("SELECT setval(CAST(:sequence_name AS regclass), :value, true)"),
                {"sequence_name": sequence_name, "value": maximum},
            )
            print(f"  {table.name}.{column.name}: sequence advanced to {maximum}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Copy local SQLite rows into Railway PostgreSQL without deleting data."
    )
    parser.add_argument(
        "--local-db",
        type=Path,
        default=DEFAULT_LOCAL_DB,
        help=f"Path to the local SQLite file (default: {DEFAULT_LOCAL_DB})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write missing rows to production after an explicit confirmation prompt.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    load_dotenv(DOTENV_PATH)

    local_db = args.local_db.resolve()
    if not local_db.exists():
        raise SystemExit(f"Local SQLite database not found: {local_db}")

    database_url = normalize_database_url(os.environ.get("DATABASE_URL"))
    if not database_url:
        raise SystemExit(
            "DATABASE_URL is not set. Use Railway's PostgreSQL connection URL."
        )
    if database_url.startswith("sqlite"):
        raise SystemExit("DATABASE_URL points to SQLite; production PostgreSQL is required.")

    dry_run = parse_bool(os.environ.get("DRY_RUN", "True"))
    if args.execute:
        dry_run = False

    local_engine = create_engine(f"sqlite:///{local_db.as_posix()}")
    target_engine = create_engine(database_url)
    local_inspector = inspect(local_engine)
    target_inspector = inspect(target_engine)

    source_tables = {
        name for name in local_inspector.get_table_names() if is_copyable_table(name)
    }
    target_tables = set(target_inspector.get_table_names())
    ordered_tables = dependency_order(local_inspector, source_tables)

    print(f"Local SQLite database: {local_db}")
    print(f"Railway database: {visible_database_url(database_url)}")
    print(f"Mode: {'DRY RUN (no production writes)' if dry_run else 'EXECUTE'}")
    print("Import order: " + ", ".join(ordered_tables))

    if not dry_run:
        print("\nThis will insert missing local rows into the Railway production database.")
        print("It will not delete or reset existing production rows.")
        confirmation = input(f"Type {CONFIRMATION_PHRASE} to continue: ").strip()
        if confirmation != CONFIRMATION_PHRASE:
            raise SystemExit("Import cancelled: confirmation phrase did not match.")

    local_metadata = MetaData()
    local_metadata.reflect(bind=local_engine, only=ordered_tables)
    copyable_target_names = sorted(source_tables.intersection(target_tables))
    target_metadata = MetaData()
    target_metadata.reflect(bind=target_engine, only=copyable_target_names)

    inserted_total = 0
    skipped_total = 0
    missing_total = 0
    imported_target_tables = []

    with local_engine.connect() as source_connection:
        target_context = (
            target_engine.begin() if not dry_run else target_engine.connect()
        )
        with target_context as target_connection:
            for table_name in ordered_tables:
                source_table = local_metadata.tables[table_name]
                source_rows = source_connection.execute(select(source_table)).mappings().all()

                if table_name not in target_tables:
                    missing_total += len(source_rows)
                    print(
                        f"{table_name}: local={len(source_rows)}, SKIPPED "
                        "(table is missing in Railway; run the existing safe migration first)"
                    )
                    continue

                target_table = target_metadata.tables[table_name]
                target_column_names = {column.name for column in target_table.columns}
                common_columns = [
                    column.name
                    for column in source_table.columns
                    if column.name in target_column_names
                ]
                if not common_columns:
                    print(f"{table_name}: SKIPPED (no shared columns)")
                    continue

                key_columns, key_type = identity_columns(
                    target_inspector, table_name, common_columns
                )
                existing_keys = {
                    tuple(row)
                    for row in target_connection.execute(
                        select(*(target_table.c[name] for name in key_columns))
                    ).all()
                }
                pending_rows = []
                skipped = 0

                for source_row in source_rows:
                    values = {name: source_row[name] for name in common_columns}
                    key = row_key(values, key_columns)
                    if key in existing_keys:
                        skipped += 1
                        continue
                    pending_rows.append(values)
                    existing_keys.add(key)

                if pending_rows and not dry_run:
                    target_connection.execute(target_table.insert(), pending_rows)
                    imported_target_tables.append(target_table)

                inserted_total += len(pending_rows)
                skipped_total += skipped
                action = "would_copy" if dry_run else "copied"
                print(
                    f"{table_name}: local={len(source_rows)}, {action}={len(pending_rows)}, "
                    f"skipped_existing={skipped}, duplicate_check={key_type}"
                )

            if not dry_run:
                reset_postgres_sequences(target_connection, imported_target_tables)

    print(
        f"\nSummary: {'would_copy' if dry_run else 'copied'}={inserted_total}, "
        f"skipped_existing={skipped_total}, skipped_missing_target={missing_total}"
    )
    if dry_run:
        print("Dry run complete. No production data was written.")
    else:
        print("Import complete. No production rows were deleted or reset.")


if __name__ == "__main__":
    main()
