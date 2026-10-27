
import os
import sys

from sqlalchemy import MetaData, create_engine, insert, select, text
from sqlalchemy.engine import make_url

SOURCE_URL = os.getenv("SOURCE_DATABASE_URL")
TARGET_URL = os.getenv("STAGING_DATABASE_URL")
CONFIRM = os.getenv("COPY_CATALOGUE_TO_STAGING")

# Catalogue tables only. No users, orders, payments, or reviews.
TABLE_ORDER = [
    "colors",
    "category",
    "categories",
    "products",
    "product_colors",
    "product_images",
    "product_videos",
    "product_tags",
    "product_sizes",
]

REQUIRED_TABLES = {
    "products",
    "product_colors",
    "product_images",
    "product_sizes",
}


def normalize_url(url):
    # Railway URLs may use the older postgres:// prefix.
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def database_identity(url):
    parsed = make_url(url)
    return (
        parsed.host,
        parsed.port,
        parsed.database,
    )


def main():
    if not SOURCE_URL or not TARGET_URL:
        sys.exit(
            "STOP: SOURCE_DATABASE_URL and STAGING_DATABASE_URL "
            "must be configured securely."
        )

    if CONFIRM != "YES":
        sys.exit(
            "STOP: Set COPY_CATALOGUE_TO_STAGING=YES "
            "only after verifying both database URLs."
        )

    source_url = normalize_url(SOURCE_URL)
    target_url = normalize_url(TARGET_URL)

    try:
        if database_identity(source_url) == database_identity(target_url):
            sys.exit("STOP: Source and target appear to be the same database.")
    except Exception:
        sys.exit("STOP: Could not validate database identities.")

    source_engine = create_engine(source_url, pool_pre_ping=True)
    target_engine = create_engine(target_url, pool_pre_ping=True)

    try:
        source_meta = MetaData()
        target_meta = MetaData()

        source_meta.reflect(bind=source_engine)
        target_meta.reflect(bind=target_engine)

        source_tables = source_meta.tables
        target_tables = target_meta.tables

        missing_source = REQUIRED_TABLES - set(source_tables)
        missing_target = REQUIRED_TABLES - set(target_tables)

        if missing_source or missing_target:
            sys.exit(
                "STOP: Required tables are missing. "
                f"Source: {sorted(missing_source)}; "
                f"staging: {sorted(missing_target)}."
            )

        tables = [
            name for name in TABLE_ORDER
            if name in source_tables and name in target_tables
        ]

        # Refuse to overwrite anything in the staging catalogue tables.
        with target_engine.connect() as conn:
            existing = {}
            for name in tables:
                table = target_tables[name]
                count = conn.execute(
                    select(text("COUNT(*)")).select_from(table)
                ).scalar_one()

                if count:
                    existing[name] = count

        if existing:
            sys.exit(
                "STOP: Staging catalogue tables are not empty: "
                f"{existing}. Nothing was copied or deleted."
            )

        copied = {}

        # All target inserts happen in one transaction.
        with target_engine.begin() as target_conn:
            with source_engine.connect() as source_conn:
                for name in tables:
                    src = source_tables[name]
                    dst = target_tables[name]

                    rows = source_conn.execute(select(src)).mappings().all()
                    shared_columns = [
                        col.name for col in src.columns
                        if col.name in dst.columns
                    ]

                    copied[name] = len(rows)

                    if rows and not shared_columns:
                        raise RuntimeError(
                            f"No matching columns found for {name}."
                        )

                    if rows:
                        values = [
                            {column: row[column] for column in shared_columns}
                            for row in rows
                        ]
                        target_conn.execute(insert(dst), values)

                    skipped = sorted(
                        set(src.columns.keys()) - set(dst.columns.keys())
                    )
                    if skipped:
                        print(
                            f"NOTE: {name}: source-only columns not copied: "
                            f"{skipped}"
                        )

            # Update PostgreSQL ID sequences after copying explicit IDs.
            for name in tables:
                dst = target_tables[name]

                if "id" not in dst.columns:
                    continue

                max_id = target_conn.execute(
                    select(text("MAX(id)")).select_from(dst)
                ).scalar_one()

                if max_id is None:
                    continue

                qualified_name = (
                    f"{dst.schema}.{dst.name}"
                    if dst.schema
                    else dst.name
                )

                sequence_name = target_conn.execute(
                    text(
                        "SELECT pg_get_serial_sequence(:table_name, 'id')"
                    ),
                    {"table_name": qualified_name},
                ).scalar_one()

                if sequence_name:
                    target_conn.execute(
                        text(
                            "SELECT setval(:sequence_name, :max_id, true)"
                        ),
                        {
                            "sequence_name": sequence_name,
                            "max_id": max_id,
                        },
                    )

        print("Catalogue copy completed.")
        for name, count in copied.items():
            print(f"{name}: {count} rows copied")

    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
