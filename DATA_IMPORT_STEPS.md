# Railway Data Import Steps

This is a one-time, non-destructive copy from the local SQLite database at
`instance/site.db` into Railway PostgreSQL. The importer preserves IDs, copies
missing rows only, and never deletes or resets production rows.

## 1. Get the Railway PostgreSQL URL

Use the PostgreSQL service connection URL from Railway. When running the script
on your computer, use Railway's public TCP proxy URL, not a
`postgres.railway.internal` URL. Treat this value as a secret and do not commit
it.

PowerShell:

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@PUBLIC_HOST:PORT/railway"
```

macOS or Linux:

```bash
export DATABASE_URL="postgresql://USER:PASSWORD@PUBLIC_HOST:PORT/railway"
```

## 2. Run a dry run first

Dry run is the default. It connects to both databases and prints the number of
rows that would be copied per table without writing production data.

```powershell
$env:DRY_RUN="True"
python scripts/copy_local_data_to_railway.py
```

Review the printed table order, counts, and any missing-target warnings. If a
target table is missing, deploy the existing safe migration before importing.

## 3. Run the actual import

```powershell
python scripts/copy_local_data_to_railway.py --execute
```

At the prompt, type exactly:

```text
YES_TO_IMPORT
```

The script inserts missing rows, preserves primary-key IDs and relationships,
and advances PostgreSQL sequences after explicit ID inserts. It does not delete
or reset production data.

## 4. Verify Railway counts

Run the importer again in dry-run mode:

```powershell
$env:DRY_RUN="True"
python scripts/copy_local_data_to_railway.py
```

For a completed import, populated tables should report `would_copy=0` with the
local rows counted under `skipped_existing`.

You can also check counts directly with Railway's PostgreSQL shell:

```sql
SELECT 'users' AS table_name, COUNT(*) FROM users
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'product_images', COUNT(*) FROM product_images
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'blog', COUNT(*) FROM blog
UNION ALL SELECT 'homepage_media', COUNT(*) FROM homepage_media;
```
