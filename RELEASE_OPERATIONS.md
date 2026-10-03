# DevDB Release Operations

This runbook covers the operational steps that should accompany a release of DevDB.

## Pre-release checks

1. Build the application image from the exact source revision being released:

   ```bash
   docker compose build app migration
   ```

2. Run the complete test suite in the built image:

   ```bash
   docker compose run --rm app pytest -q
   ```

3. Verify the migration head before deployment:

   ```bash
   docker compose run --rm app alembic current
   docker compose run --rm app alembic heads
   ```

4. Confirm production settings include:
   - `ENVIRONMENT=production`
   - `DEBUG=False`
   - `COOKIE_SECURE=True`
   - a unique, high-entropy `SECRET_KEY`
   - a strong PostgreSQL password
   - HTTPS at the externally exposed reverse proxy/load balancer

## PostgreSQL backup before a migration

Take a logical backup before applying a migration to an existing environment. Run the backup from a host that can reach PostgreSQL and store the resulting file outside the database container/volume.

Example:

```bash
pg_dump \\
  --format=custom \\
  --file=devdb-pre-migration-$(date +%Y%m%d-%H%M%S).dump \\
  "$DATABASE_URL"
```

Verify the dump can be read:

```bash
pg_restore --list devdb-pre-migration-YYYYMMDD-HHMMSS.dump >/dev/null
```

Do not delete or overwrite the pre-migration backup until the migration has been verified successfully.

## Apply the release

The normal Compose deployment sequence is:

```bash
docker compose up -d postgres
docker compose run --rm migration
docker compose up -d app
```

The migration service must complete successfully before the application is started.

## Post-deployment verification

Check both health endpoints:

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
```

Expected responses:

- `/healthz`: `{"status":"ok"}`
- `/readyz`: `{"status":"ready"}`

Then verify the database is at the expected Alembic head:

```bash
docker compose run --rm app alembic current
docker compose run --rm app alembic heads
```

Finally perform a small authenticated application smoke test: login, open My Media, open a detail modal, and edit a watch entry.

## Restore procedure

If a migration must be rolled back at the database level, restore the verified pre-migration dump into a separate PostgreSQL instance first. Validate the restored database before replacing the active database.

For a custom-format dump:

```bash
createdb devdb_restore
pg_restore \\
  --clean \\
  --if-exists \\
  --dbname=devdb_restore \\
  devdb-pre-migration-YYYYMMDD-HHMMSS.dump
```

Do not restore over the active database until the restored copy has been validated.

## Azure / semi-production note

The semi-production migration rehearsal is currently deferred because the Azure database is unavailable. Do not substitute a destructive development reset for that rehearsal. When the database becomes available, use the backup-first procedure above and perform a non-destructive migration rehearsal.
