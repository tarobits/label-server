# MariaDB

The main server supports MariaDB 10.11 and newer using PyMySQL. Integration tests
run against **MariaDB 11.8.6**. SQLite remains the default. Companion stations keep
their local SQLite journal so authorized batches can finish during a network outage.

Run one main-server process per database. A MariaDB connection holds a named
ownership lock to exclude another server or maintenance operation, even from
another host. Losing that lock blocks subsequent database operations; investigate
and restart the main server after restoring connectivity. This is not an active-active
or automatic failover deployment.

## Database and configuration

Create a dedicated empty database on the backed-up MariaDB server:

```sql
CREATE DATABASE labels CHARACTER SET utf8mb4 COLLATE utf8mb4_nopad_bin;
```

Provision a dedicated login restricted to the main server's source address. Grant
privileges on `labels.*` only, including schema creation, alteration, indexes and
drop for migrations and rollback; no global administrator privileges are needed.
Tables use InnoDB, case-sensitive comparisons and full Unicode. Do not share this
schema with other applications or add custom tables, views or triggers.

Set these values in the main server's private `.env`:

```dotenv
LABEL_DATABASE_URL="mariadb+pymysql://labels:CHANGE_ME@database.example.com:3306/labels?charset=utf8mb4&ssl_ca=/path/to/ca.pem&ssl_check_hostname=true"
LABEL_DATA_DIR=./data
```

Replace the placeholder password and percent-encode special characters in the
username and password. Use a trusted CA file and matching server hostname for
verified TLS. The CA path must be readable by the service user (and mounted at
that path in Docker). Keep database access restricted to trusted hosts; do not
expose MariaDB publicly just because the main web server is public.

From pre3, uploaded images/fonts, profile pictures and review evidence are stored
in the database and included in its backups. `LABEL_DATA_DIR` holds the disposable
rendering cache, archived legacy assets, authentication files and update state.
When upgrading an existing installation, keep it at the **old SQLite file's parent
directory** so the first startup can import and verify legacy assets, then move
that directory into `backups/assets-…`. Private configuration, authentication keys
and local rollback archives still need separate backups.

For a fresh native installation, place only the connection URL, without a variable
name, in a protected file outside the repository, then run:

```sh
sudo python3 scripts/install.py --database-url-file /secure/path/database-url
```

The selected release must contain MariaDB support. The installer stores the URL
in the protected deployment configuration and initializes the schema. Credentials
are not passed as command arguments or printed. For a manual installation, install
the main dependencies with `pip install -c requirements.lock .` and run
`alembic upgrade head` with the configured `.env` before starting the server.

The bundled Compose file explicitly selects SQLite. For MariaDB in Docker, use
a local Compose override to set `services.labels.environment.LABEL_DATABASE_URL`
to the configured URL and `LABEL_DATA_DIR` to `/srv/labels/data`; retain the data
volume and mount the TLS CA file read-only. Merely changing `.env` does not override
the bundled Compose database setting.

## Move an existing SQLite installation

1. Upgrade the SQLite installation to the release containing this tool. Finish or
   review any in-flight printing, and reconnect companions so every authorized
   batch has reported its result. Stop `labels.service` and any manual main-server
   process. Keep the service stopped throughout the copy and configuration change.
2. Back up the complete local data directory and `.env`. Apply this release's
   SQLite schema migrations while the old SQLite URL is still configured. The
   source must be at this checkout's Alembic head. Before copying, complete the
   asset import by starting pre3 once and stopping it again, or by running
   `.venv/bin/python scripts/migrate_assets.py --env-file .env` as the service user
   while stopped. The migration tool refuses a source whose asset import is incomplete.
3. Create an empty MariaDB database as above. **Do not initialize or start the
   application against it first**: seeded application rows make it nonempty.
   Put the target `LABEL_DATABASE_URL="..."` line in a separate protected file
   readable by the service user, for example `/secure/path/mariadb.env`.
4. From the installation directory, run the readiness check as the service user:

   ```sh
   sudo -u labels .venv/bin/python -m scripts.migrate_database \
     --source data/labels.db --target-env-file /secure/path/mariadb.env
   ```

5. Run the same command with `--apply` and a private, writable backup directory:

   ```sh
   sudo -u labels .venv/bin/python -m scripts.migrate_database \
     --source data/labels.db --target-env-file /secure/path/mariadb.env \
     --backup-dir /secure/path/migration-backups --apply
   ```

6. After it reports **Copied and verified**, update the deployment's `.env` to the
   target URL and set `LABEL_DATA_DIR` to the old database directory. Preserve all
   other configuration. Start `labels.service`, then check login, printers, queued
   work, Print Activity, cartridge balances and uploaded assets before printing.

The default command checks readiness without copying or changing the target
schema. Apply creates a restricted SQLite backup, initializes MariaDB, copies all
application tables, and compares each table's row count and content hash before
committing. IDs, ownership, debts, repayments, permissions, print history and
notification state are retained. The SQLite source and deployment configuration
are never rewritten by this tool.

The tool refuses a running source, unsettled printing, a different schema version,
broken SQLite integrity/foreign keys, or an occupied target. A failed copy rolls
back inserted rows; schema creation itself is not transactional on MariaDB, so an
empty initialized schema can remain and is safe to retry. Do not delete or overwrite
a populated target to bypass a refusal.

If validation fails before the MariaDB deployment accepts work, stop it and switch
back to the unchanged SQLite configuration. Once MariaDB has accepted requests or
printed, the old SQLite database is stale: switching back could replay work or
lose accounting history. Recover from a coordinated current backup instead.

## Backups and updates

Continue the MariaDB server's regular backup policy. Also back up the main server's
local data directory and private configuration. Stop printing and the application
when taking a coordinated recovery snapshot; do not restore database and assets
from unrelated points in time.

The native updater detects MariaDB from the installed configuration. After stopping
the service it acquires database ownership, saves a restricted logical backup as
`database.json.gz`, and backs up code, dependencies, local data and configuration.
It retains ownership through migrations and releases it for validation startup.
On a failed update it restores both MariaDB and local state before restarting the
previous version. Uncertain activation leaves the service stopped for review,
because automatically restoring an older queue could duplicate physical prints.

For a manual logical backup, stop the service and run from the installation directory:

```sh
sudo -u labels .venv/bin/python -m scripts.database_maintenance \
  --backup /secure/path/database.json.gz
```

For manual recovery, keep the service stopped, restore matching code, dependencies,
configuration and local data, then restore the corresponding database snapshot:

```sh
sudo -u labels .venv/bin/python -m scripts.database_maintenance \
  --restore /secure/path/database.json.gz
```

Restore **replaces all tables in the configured database**. It validates the archive's
database name, completeness and checksums before dropping tables. MariaDB schema
changes are not transactional: if restore fails, leave the service stopped and
resolve the failure before retrying. Archives contain private application data;
keep their restricted permissions and do not commit or publish them.

Docker can run the main server with MariaDB, but the automatic **Docker updater
currently requires SQLite** and refuses remote databases. Use a coordinated manual
upgrade/backup/restore procedure for MariaDB in Docker. Native MariaDB installation
and automatic updates are supported.

## Schema maintenance and tests

Historical SQLite migrations stay unchanged. New MariaDB databases start from the
frozen `migrations/mariadb_baseline.sql` and seed data at revision `121313f47a90`,
then apply subsequent Alembic migrations normally. Do not regenerate that baseline
from newer ORM models: future changes need migrations that work on both databases.
MariaDB cannot downgrade to a revision before this baseline.

`tests/test_mariadb.py` covers actual MariaDB schema creation, SQLite copying,
verification failures, ownership exclusion, backup/restore, updater coordination,
and application authentication/printing. Set `LABEL_TEST_MARIADB_URL` to a
**disposable** MariaDB server when running it. Tests create and drop random databases
and require database-creation privileges; do not use the production application login.
