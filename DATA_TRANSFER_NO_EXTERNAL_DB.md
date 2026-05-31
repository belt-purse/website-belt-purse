# Railway Internal JSON Data Transfer

These temporary routes move data when Railway's external PostgreSQL TCP proxy
is unavailable. They use each deployed app's existing internal
`DATABASE_URL`. Remove the routes after the transfer.

## 1. Deploy the temporary routes to both projects

Deploy this code to the old Railway project and the new Railway project. The
application continues using its existing database configuration.

## 2. Export from the old Railway project

In the old Railway project, add a long random environment variable:

```text
DB_EXPORT_TOKEN=YOUR_LONG_RANDOM_SECRET
```

Open the old deployed app URL:

```text
https://OLD_APP_DOMAIN/admin/export-db-json-secure?token=YOUR_LONG_RANDOM_SECRET
```

The browser downloads:

```text
railway_data_export.json
```

Keep this file private. It contains users, orders, and other production data.

## 3. Import into the new Railway project

In the new Railway project, add a different long random environment variable:

```text
DB_IMPORT_TOKEN=YOUR_DIFFERENT_LONG_RANDOM_SECRET
```

Upload the downloaded JSON file with `curl`:

```bash
curl -X POST \
  -H "X-DB-Transfer-Token: YOUR_DIFFERENT_LONG_RANDOM_SECRET" \
  -F "file=@railway_data_export.json" \
  https://NEW_APP_DOMAIN/admin/import-db-json-secure
```

PowerShell:

```powershell
curl.exe -X POST `
  -H "X-DB-Transfer-Token: YOUR_DIFFERENT_LONG_RANDOM_SECRET" `
  -F "file=@railway_data_export.json" `
  https://NEW_APP_DOMAIN/admin/import-db-json-secure
```

Alternatively, place `railway_data_export.json` in the new project's root and
send the protected POST request without a file:

```bash
curl -X POST \
  -H "X-DB-Transfer-Token: YOUR_DIFFERENT_LONG_RANDOM_SECRET" \
  https://NEW_APP_DOMAIN/admin/import-db-json-secure
```

The import is non-destructive: existing primary-key rows are skipped, missing
rows are inserted with their original IDs, and PostgreSQL sequences are
advanced afterward.

## 4. Verify the result

Check the JSON response. It includes:

- `counts_before`
- `copied_counts`
- `skipped_existing_counts`
- `counts_after`
- `required_verification_counts`

The route reports `success: true` only when `users`, `products`, and
`categories` (or this app's `category` table alias) each contain at least one
row. Also verify products, users, orders, blogs, homepage media, and coupons in
the new Railway admin panel.

Running the same import again is safe: rows with existing primary keys are
skipped instead of duplicated.

## 5. Remove temporary access

After verification:

1. Remove `DB_EXPORT_TOKEN` from the old Railway project.
2. Remove `DB_IMPORT_TOKEN` from the new Railway project.
3. Remove `temporary_db_json_transfer.py`.
4. Remove its temporary registration block from `app.py`.
5. Deploy the cleanup commit to both projects.

Do not leave the export or import routes enabled after migration.
