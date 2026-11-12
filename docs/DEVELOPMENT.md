# Development and testing

[All guides](README.md) · [Project overview](../README.md)

This guide is for contributors who want to run the source code, change the application or build releases. Run commands from the repository root unless a command changes directories. For a normal installation, use the [installer](DEPLOYMENT.md#github-installer).

## Run locally

Requires Python 3.12+, Node.js 20.19+ (20.x) or 22.12+, and system libusb for USB printing on Linux
or macOS. Node.js is needed only to build or develop the UI. See
[deployment](DEPLOYMENT.md) for USB permissions and service setup.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000>. On first launch, read `data/auth-setup-token` on the
server to create an administrator account. Logs show only its location. The token file
is removed after setup. New installations have no printers configured.

Run **one server process per database**. Do not use multiple Uvicorn workers.
The main application database pool allows up to 25 simultaneous connections
(five retained connections plus 20 temporary overflow connections).

SQLite is the default; main servers can also use MariaDB 10.11+ (tested with
11.8.6). See [MariaDB setup and SQLite migration](MARIADB.md) for the verified
migration tool, native installation, and database backup/recovery instructions.
Migrations must be applied explicitly before starting the local server.

For frontend development, keep the backend on port 8000 and run
`npm run dev --prefix frontend` in another terminal. Open the URL Vite prints;
it proxies `/api` to the backend. Production serves `frontend/dist` by default;
`LABEL_FRONTEND_DIST` overrides that path.

## Architecture and checks

Database integrity changes use an [administrator repair screen and maintenance
restart](RELATIONSHIP_MIGRATION.md). See the
[security model and operational limits](SECURITY.md),
[concurrency and ownership rules](PRINTER_ARCHITECTURE.md#concurrency-and-ownership),
and [deployment checklist](DEPLOYMENT_CHECKLIST.md) before changing or deploying
sensitive paths.

The backend uses FastAPI, SQLAlchemy, Alembic, and SQLite or MariaDB; the frontend uses Vue 3, Pinia,
TypeScript, and Vite. Printer-specific protocols stay in `app/printer`; queue and
domain code use the generic backend contract. See [printer architecture](PRINTER_ARCHITECTURE.md)
for implementation constraints and [DESIGN.md](../DESIGN.md) for interface conventions.

Pinia owns shared authentication, workspace, administration and request caches.
Concurrent reads share a request; catalogs load on relevant pages and remain cached
for a minute. Live queue and printer data refresh every five seconds, with longer
intervals for summaries and session checks. One scheduler pauses polling in hidden
tabs. Successful writes invalidate affected resources before the UI reloads them;
session and permission changes clear private caches. Cached data stays in memory.

Run backend and frontend checks with the development dependencies installed:

```sh
.venv/bin/pytest -q
.venv/bin/ruff check app tests migrations
.venv/bin/ruff format --check app tests migrations
.venv/bin/mypy app
.venv/bin/pyright
npm run build --prefix frontend
npm run format:check --prefix frontend
```

Pylance and `.venv/bin/pyright` share the standard-mode configuration in
`pyproject.toml`, including deprecation warnings. The check covers all application,
companion, migration, script and test Python files; generated build copies and
third-party dependencies are outside that scope.

Build the frontend before running browser tests:

```sh
cd frontend
npm run build:all
npm run test:i18n
npx playwright install chromium
npm run test:e2e
```

Tests use isolated databases and simulated printer hardware, without contacting
real printers, ntfy, or SMTP providers. Browser screenshots are written to `frontend/test-results`.

The companion has a separate native installation role and frontend build. See
[Companion stations](COMPANION.md) for installation, updates, and its local
SQLite database. Main and companion run on separate machines. Use
`npm run build:companion --prefix frontend` for the station alone; `build:main`
(or `build`) builds the main UI, and `build:all` builds both for browser tests.

### Release frontend builds

The `Release frontend` GitHub Actions workflow builds each published stable or
prerelease tag and uploads `label-server-frontend.zip` and
`label-companion-frontend.zip` directly to that release. The updater selects the
archive for the installed server role.
It uses a standard Ubuntu runner without Actions artifact uploads or dependency
caching. Standard runner compute is free for public repositories; release assets
are separate from Actions artifact storage. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
and [release storage](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

Wait for the workflow to finish before running the native updater, which downloads
the prebuilt frontend by default. Use `--build-frontend` to build locally instead.
Builds are architecture-independent static files; the main build also
includes its service worker and install icons. See [deployment instructions](DEPLOYMENT.md) for
verification and updater handoffs. The workflow can also be run manually with a
published release tag containing the packaging script. Existing assets are not
overwritten. Repositories with immutable releases must attach assets before
publication instead of using this post-publication workflow.

Release builds use a clean tagged checkout and receive no deployment `.env`,
database, uploads, VAPID private key, or application credentials. The packager
accepts only static build files and records the source commit. Checkout credentials
are not persisted, and `GH_TOKEN` is supplied only to the release-upload step.
The workflow needs the built-in GitHub token with `contents: write`; no personal
token or deployment secret is needed. All frontend code is public: never put
secrets in source files or `VITE_*` settings, which Vite can embed in bundles.
SHA-256 verifies the download against GitHub's metadata; it does not replace trust
in the repository and its release maintainers.

To reproduce packaging from a clean release checkout without frontend `.env*`
files (example tag):

```sh
npm ci --prefix frontend
npm run build --prefix frontend
python3 -m scripts.package_frontend --tag v0.12.0-pre5
```

The frontend overrides Workbox's `glob` dependency to 14.0.3 or newer to include
the `glob` cancellation and `minimatch` pattern-amplification security fixes.
Remove this scoped override when Workbox adopts patched versions itself; verify
the production build and PWA browser tests when changing it.

As of 2026-11-04, `npm audit` still reports the low-severity
[deepmerge advisory](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) through
Workbox's Rollup resolver. No patched release is available. The installed resolver
uses it only to clone its built-in defaults during the build, not to process label
data or requests. Review this assessment when updating the resolver. Avoid
`npm audit fix --force`: its suggested PWA downgrade is not a verified fix.

## Test the mobile app

PWA registration runs only in production builds. For local testing, build the
frontend and use the backend on `localhost` or `127.0.0.1`; plain HTTP on a LAN
address does not support service workers. Remote installations require HTTPS.

Install icons are derived from `frontend/public/favicon.svg`. Regenerate them with
`.venv/bin/python scripts/generate_app_icons.py` after changing the source icon.
