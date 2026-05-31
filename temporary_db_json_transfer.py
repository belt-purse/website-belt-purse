"""TEMPORARY Railway-internal JSON database transfer routes.

Remove this module and its registration from app.py after the data transfer.
"""

import base64
import hmac
import io
import json
import os
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from flask import jsonify, request, send_file
from sqlalchemy import JSON, Date, DateTime, LargeBinary, MetaData, Numeric, Table, Time
from sqlalchemy import func, inspect, select, text


BASE_DIR = Path(__file__).resolve().parent
ROOT_EXPORT_FILE = BASE_DIR / "railway_data_export.json"
EXPORT_FILENAME = "railway_data_export.json"
SYSTEM_TABLES = {"alembic_version", "sqlite_sequence"}
INTERNAL_TABLE_MARKERS = ("cache", "session")
REQUESTED_TABLES = [
    "users",
    "categories",
    "products",
    "product_images",
    "product_videos",
    "product_colors",
    "product_sizes",
    "colors",
    "sizes",
    "tags",
    "product_tags",
    "reviews",
    "cart",
    "wishlist",
    "addresses",
    "orders",
    "order_items",
    "blogs",
    "payment_methods",
    "warranties",
    "wallet_transactions",
    "tickets",
    "coupons",
    "homepage_media",
    "auto_slider_images",
    "hero_images",
    "crafted_videos",
]

# Foreign keys determine the final order. This list keeps output predictable
# and covers both requested names and the aliases used by this application.
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
    "addresses",
    "orders",
    "order_items",
    "reviews",
    "cart",
    "wishlist",
    "blog",
    "blogs",
    "blog_tags",
    "payment_methods",
    "warranty",
    "warranties",
    "wallet_transactions",
    "tickets",
    "coupons",
    "coupon_usage",
    "homepage_media",
    "auto_slider_images",
    "hero_images",
    "crafted_videos",
    "email_history",
    "email_track",
    "password_reset_tokens",
]
PREFERRED_RANK = {name: index for index, name in enumerate(PREFERRED_TABLE_ORDER)}


def register_temporary_db_json_transfer_routes(app, db):
    # TEMPORARY SECURITY-SENSITIVE ROUTES: remove after Railway data transfer.
    @app.route("/admin/export-db-json-secure", methods=["GET"])
    def export_db_json_secure():
        if not _valid_token("DB_EXPORT_TOKEN"):
            return jsonify({"error": "Forbidden"}), 403

        inspector = inspect(db.engine)
        table_names = _project_table_names(inspector)
        skipped_requested_tables = sorted(set(REQUESTED_TABLES).difference(table_names))
        for table_name in skipped_requested_tables:
            app.logger.info("DB JSON EXPORT: skipped missing requested table=%s", table_name)
        metadata = MetaData()
        metadata.reflect(bind=db.engine, only=table_names)
        ordered_names = _dependency_order(inspector, table_names)

        exported_tables = {}
        row_counts = {}
        with db.engine.connect() as connection:
            for table_name in ordered_names:
                table = metadata.tables[table_name]
                rows = connection.execute(select(table)).mappings().all()
                exported_tables[table_name] = [
                    {key: _json_safe(value) for key, value in row.items()}
                    for row in rows
                ]
                row_counts[table_name] = len(rows)
                app.logger.info("DB JSON EXPORT: %s rows=%s", table_name, len(rows))

        payload = {
            "metadata": {
                "format": "railway-db-json-transfer-v1",
                "exported_at": datetime.utcnow().isoformat() + "Z",
                "database_dialect": db.engine.dialect.name,
                "table_order": ordered_names,
                "row_counts": row_counts,
                "skipped_requested_tables": skipped_requested_tables,
            },
            "tables": exported_tables,
        }
        export_bytes = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        app.logger.info("DB JSON EXPORT: completed tables=%s", len(ordered_names))
        return send_file(
            io.BytesIO(export_bytes),
            mimetype="application/json",
            as_attachment=True,
            download_name=EXPORT_FILENAME,
        )

    @app.route("/admin/import-db-json-secure", methods=["POST"])
    def import_db_json_secure():
        if not _valid_token("DB_IMPORT_TOKEN"):
            return jsonify({"error": "Forbidden"}), 403

        try:
            payload, payload_source = _load_import_payload()
            exported_tables = payload.get("tables")
            if not isinstance(exported_tables, dict):
                raise ValueError("JSON payload must contain a tables object.")

            inspector = inspect(db.engine)
            target_names = _project_table_names(inspector)
            metadata = MetaData()
            metadata.reflect(bind=db.engine, only=target_names)
            import_names = [
                name
                for name in _dependency_order(inspector, target_names)
                if name in exported_tables
            ]
            skipped_export_tables = sorted(set(exported_tables).difference(target_names))
            before_counts = _table_counts(db.engine, metadata, target_names)
            app.logger.info("DB JSON IMPORT: counts before=%s", before_counts)

            copied_counts = {}
            skipped_counts = {}
            with db.engine.begin() as connection:
                imported_tables = []
                for table_name in import_names:
                    table = metadata.tables[table_name]
                    rows = exported_tables.get(table_name, [])
                    if not isinstance(rows, list):
                        raise ValueError(f"Table {table_name} must contain a JSON array.")

                    copied, skipped = _copy_missing_rows(connection, table, rows)
                    copied_counts[table_name] = copied
                    skipped_counts[table_name] = skipped
                    if copied:
                        imported_tables.append(table)
                    app.logger.info(
                        "DB JSON IMPORT: %s copied=%s skipped_existing=%s",
                        table_name,
                        copied,
                        skipped,
                    )

                _reset_postgres_sequences(connection, imported_tables)

            after_counts = _table_counts(db.engine, metadata, target_names)
            app.logger.info("DB JSON IMPORT: counts after=%s", after_counts)
            required_counts = _required_verification_counts(after_counts)
            success = all(count > 0 for count in required_counts.values())
            status = "success" if success else "completed_with_verification_warning"
            response = {
                "status": status,
                "success": success,
                "message": (
                    "Import completed and required data counts are greater than zero."
                    if success
                    else "Import completed, but required users/products/categories counts "
                    "are not all greater than zero. Verify the source export and admin panel."
                ),
                "payload_source": payload_source,
                "copied_counts": copied_counts,
                "skipped_existing_counts": skipped_counts,
                "skipped_export_tables_missing_in_target": skipped_export_tables,
                "counts_before": before_counts,
                "counts_after": after_counts,
                "required_verification_counts": required_counts,
            }
            return jsonify(response), 200 if success else 409
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            app.logger.exception("DB JSON IMPORT: rejected payload")
            return jsonify({"error": str(error)}), 400
        except Exception:
            app.logger.exception("DB JSON IMPORT: failed")
            return jsonify({"error": "Import failed. Check Railway logs."}), 500


def _request_token():
    authorization = request.headers.get("Authorization", "")
    bearer_token = (
        authorization[7:].strip()
        if authorization.lower().startswith("bearer ")
        else ""
    )
    return (
        request.headers.get("X-DB-Transfer-Token")
        or request.args.get("token")
        or bearer_token
        or ""
    )


def _valid_token(environment_variable):
    expected = os.environ.get(environment_variable, "")
    received = _request_token()
    return bool(expected and received and hmac.compare_digest(expected, received))


def _is_project_table(table_name):
    lowered = table_name.lower()
    return (
        table_name not in SYSTEM_TABLES
        and not lowered.startswith("sqlite_")
        and not any(marker in lowered for marker in INTERNAL_TABLE_MARKERS)
    )


def _project_table_names(inspector):
    return sorted(
        [name for name in inspector.get_table_names() if _is_project_table(name)],
        key=_table_sort_key,
    )


def _table_sort_key(table_name):
    return (PREFERRED_RANK.get(table_name, len(PREFERRED_RANK)), table_name)


def _dependency_order(inspector, table_names):
    table_names = set(table_names)
    dependencies = {name: set() for name in table_names}
    dependents = defaultdict(set)
    for table_name in table_names:
        for foreign_key in inspector.get_foreign_keys(table_name):
            parent = foreign_key.get("referred_table")
            if parent in table_names and parent != table_name:
                dependencies[table_name].add(parent)
                dependents[parent].add(table_name)

    ready = sorted(
        [name for name, parents in dependencies.items() if not parents],
        key=_table_sort_key,
    )
    ordered = []
    while ready:
        table_name = ready.pop(0)
        ordered.append(table_name)
        for child in sorted(dependents[table_name], key=_table_sort_key):
            dependencies[child].discard(table_name)
            if not dependencies[child] and child not in ready and child not in ordered:
                ready.append(child)
        ready.sort(key=_table_sort_key)

    ordered.extend(sorted(table_names.difference(ordered), key=_table_sort_key))
    return ordered


def _json_safe(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"__base64__": base64.b64encode(value).decode("ascii")}
    return value


def _load_import_payload():
    uploaded_file = request.files.get("file") or request.files.get("export_file")
    if uploaded_file and uploaded_file.filename:
        return json.load(uploaded_file.stream), f"upload:{uploaded_file.filename}"
    if not ROOT_EXPORT_FILE.exists():
        raise ValueError(
            "Upload railway_data_export.json as multipart field 'file' or place it "
            "in the project root."
        )
    with ROOT_EXPORT_FILE.open("r", encoding="utf-8") as export_file:
        return json.load(export_file), str(ROOT_EXPORT_FILE)


def _deserialize_value(column, value):
    if value is None:
        return None
    if isinstance(value, dict) and set(value) == {"__base64__"}:
        return base64.b64decode(value["__base64__"])
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(column.type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(column.type, Time) and isinstance(value, str):
        return time.fromisoformat(value)
    if isinstance(column.type, Numeric) and isinstance(value, str):
        return Decimal(value)
    if isinstance(column.type, LargeBinary) and isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(column.type, JSON):
        return value
    return value


def _copy_missing_rows(connection, table, exported_rows):
    column_names = {column.name for column in table.columns}
    primary_keys = [column.name for column in table.primary_key.columns]
    identity_columns = primary_keys or [column.name for column in table.columns]
    existing_keys = {
        tuple(row)
        for row in connection.execute(
            select(*(table.c[name] for name in identity_columns))
        ).all()
    }
    pending_rows = []
    skipped = 0
    for exported_row in exported_rows:
        if not isinstance(exported_row, dict):
            raise ValueError(f"Table {table.name} contains a non-object row.")
        values = {
            name: _deserialize_value(table.c[name], value)
            for name, value in exported_row.items()
            if name in column_names
        }
        if not values:
            continue
        if any(name not in values for name in identity_columns):
            raise ValueError(
                f"Table {table.name} row is missing identity columns: {identity_columns}"
            )
        key = tuple(values[name] for name in identity_columns)
        if key in existing_keys:
            skipped += 1
            continue
        pending_rows.append(values)
        existing_keys.add(key)

    if pending_rows:
        connection.execute(table.insert(), pending_rows)
    return len(pending_rows), skipped


def _table_counts(engine, metadata, table_names):
    counts = {}
    with engine.connect() as connection:
        for table_name in sorted(table_names, key=_table_sort_key):
            table = metadata.tables[table_name]
            counts[table_name] = connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
    return counts


def _required_verification_counts(counts):
    return {
        "users": counts.get("users", 0),
        "products": counts.get("products", 0),
        "categories": counts.get("categories", counts.get("category", 0)),
    }


def _reset_postgres_sequences(connection, tables):
    if connection.dialect.name != "postgresql":
        return
    for table in tables:
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
