# Companion stations

A companion runs the USB printer adapters and a small web interface. The main
server renders labels and owns permissions, queues, cartridge inventory, and
accounting. The companion connects outward over HTTPS; the main server never
needs an inbound connection to the station.

## Register a station

1. Add its location in **Locations & access**.
2. As an administrator, open **Companions**, add the station, and grant its users
   or roles Companion access. Printer and cartridge permissions remain separate.
3. Copy the generated API key. It is displayed once. Replacing or revoking the key
   disconnects the old installation credential.
4. Copy `.env.companion.example` to `.env.companion`, restrict its permissions with
   `chmod 600 .env.companion`, and fill in the server URL and key. Keep this file
   private. Both Git and Docker build contexts exclude it.

The main server's **Companions** page refreshes every five seconds and shows each
station's connection status, last contact time and last reported software version.
A station is offline after 30 seconds without contact; unused and revoked keys
show **Never connected** and **Key revoked** respectively. Version differences
from the main server are flagged. Older companions show **Version unknown** until
updated to report their version. Apply migration `171718e92fe5` on the main server
before running code with companion-version reporting.

In user-picker mode, each user sets a personal PIN in the main server's Account
settings. It works at companions they may access. For single-user mode, an admin
selects the station user on the main server; set that same account ID in
`LABEL_COMPANION_SINGLE_USER_ID` and a 4–12 digit `LABEL_COMPANION_SHARED_PIN`.
The companion's settings dialog shows the deployment user ID for copying.
Anyone with that shared PIN can exercise the bound account's permissions at the
station. The API key cannot select an arbitrary account.

The unlock dialog shows a card for each eligible user. Select a card to enter the
PIN, or choose **Change user** to return to the picker. In single-user mode it
opens PIN entry directly. Profile pictures can be uploaded or removed in the main
server's account settings; rounded-square avatars fall back to initials. Pictures
are visible before unlock only for accounts eligible to use that companion.

The bottom indicator distinguishes the main server being offline from the browser
losing contact with the companion. The page retries automatically and recovers
without a browser refresh. Print and other control requests are never replayed.

After a companion frontend update, the page reloads automatically once the local
service is ready, the station is locked, no dialog is open, and no control request
is pending. The new shell must match the server's build identity before reload;
a stale cached shell cannot cause a repeated reload loop. Printing is owned by
the companion service and is not restarted by a browser reload. An already-open
page from before this feature needs one manual refresh to load the new behavior.

The dashboard shows each printer's queue counts, cartridge estimate, active batch
size, last batch result, and confirmed labels printed in the last 24 hours. Shared
group queues are counted separately. Batch results update after confirmation;
the display does not estimate per-label progress. During an outage, cached
summaries are marked as last known server data.

Operational details are visible while locked by default. Set
`LABEL_COMPANION_SHOW_LOCKED_DASHBOARD_DETAILS=false` in `.env.companion` and restart
the companion to hide these details until an operator with **View printer**
permission unlocks it. The basic printer list and connection indicator remain
visible. Label artwork, requester names and financial data are never included in
the public operational summary.

Set `LABEL_COMPANION_PIN_KEYPAD_ENABLED=true` for an on-screen PIN keypad.
`LABEL_COMPANION_PIN_KEYPAD_SHUFFLE` selects `none` (fixed number order), `once`
(shuffle when opening PIN entry, changing users or starting another attempt), or
`each_keypress` (also shuffle after digit entry, Backspace or Clear). Physical
keyboard input remains available; the keypad suppresses the touchscreen's native
keyboard. Defaults are `false` and `none`. Restart the companion after changing
these deployment settings.

While unlocked, the header shows the remaining inactivity time beside **Lock**.
It follows `LABEL_COMPANION_LOCK_TIMEOUT_SECONDS` and resets after accepted activity.

Open the companion web interface, unlock it with an account that has printer
management permission, and choose **Add printer**. Set a USB serial when attaching
multiple printers of one model. Registrations and configuration persist in the
companion data directory. Printers are initially unowned, inherit the station
location, and remain governed by main-server permissions. Edit their configuration
through either web interface. **Remove printer** disables it without deleting
history or queued work; **Restore printer** brings back the same registration.
Removal is refused while a batch is printing or awaiting review.

`LABEL_COMPANION_PRINTERS` is optional deployment bootstrap for unattended setup.
It accepts a JSON array of stable local IDs, names, drivers, and configurations.
It seeds missing registrations only; it never overwrites web edits or restores a
printer removed through the interface.

## Run on Linux or a Pi

The native installer supports Debian 13+ and installs one `labels.service` per
machine. Register the companion and prepare its private `.env.companion` as above,
then run from a checkout of a release that includes companion support:

```sh
sudo python3 scripts/install.py --role companion \
  --companion-config "$PWD/.env.companion"
```

The installer creates `/opt/labels`, a minimal `.venv`, the local database, USB
permissions, and the systemd service. It builds only the companion frontend and
binds to `127.0.0.1:8001` by default. Use `--public-url` and `--host` to configure
an HTTPS reverse-proxy deployment. `--check` shows the installation plan.
Existing settings in `--companion-config` are preserved. Explicit `--host`, `--port`
and `--public-url` options replace their respective settings; missing settings use
local defaults. The installer uses the configured bind address and port for its
health check. A custom data directory outside the installation must already be
writable by the `labels` service user.

Installation asks for confirmation before making changes; `--yes` allows unattended
installation. The installer provisions native systemd installations.

Main and companion are mutually exclusive native installation roles. Both use
`labels.service`: installing either role refuses an existing service, even when a
different installation directory is chosen. The `.label-server-role` file records
the installed role; starting the other application from that installation fails.
Do not remove the marker or install a second service to bypass this restriction.

For a manual checkout, use Python 3.12+ and Node 22.12+:

```sh
python3 -m venv .venv
.venv/bin/pip install -c requirements.lock -r companion/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build:companion
.venv/bin/python -m companion
```

Install `libusb-1.0-0` and grant the process user access to the printer's USB device.
The automated installer sets up the USB group and udev rule. A manual installation
needs equivalent permissions; see the [deployment guide](DEPLOYMENT.md).
Rendering libraries and the main server's database migrations are not needed.
Pillow is used by the printer adapter for raster data.

### Separate frontend builds

- `npm run build:companion --prefix frontend`: companion only, in `frontend/dist-companion`.
- `npm run build:main --prefix frontend` (or `npm run build`): main UI and its PWA, in `frontend/dist`.
- `npm run build:all --prefix frontend`: both, for development and browser tests.

Each build checks its own TypeScript entry point and shared imports. The companion
build excludes the main application's editor, views, and service worker. Building
one frontend does not erase the other build. Docker images also build only their
own frontend.

Alternatively, the container definition builds the web UI and installs only the
companion's Python dependencies:

```sh
LABEL_USB_GID="$(getent group plugdev | cut -d: -f3)" \
  docker compose -f docker-compose.companion.yml up -d --build
```

Use the group that actually owns the host's printer USB devices; `plugdev` is an
example. The container runs as an unprivileged user with that supplemental group.
The compose file maps the USB bus to support reconnects and permits USB character
device access; host device permissions still apply. Keep the persistent
`companion-data` volume across upgrades and restarts.

## Web interface and locking

Open `http://localhost:8001` on the companion's touchscreen browser. Localhost is
the default binding. To serve another device, use an HTTPS reverse proxy and set
`LABEL_COMPANION_PUBLIC_URL` to its external origin. Non-local HTTP origins are
rejected. Configure trusted proxy forwarding at the proxy boundary; the companion
does not trust arbitrary forwarded headers.

The dashboard remains visible when locked. Unlocking enables only the current
user's permitted printer controls, queue, cartridge changes, and configuration.
Actual interaction renews the configurable inactivity timeout; polling does not.
Locking does not stop printing. Local emergency/stop-after-label controls while
locked or offline are separate deployment options and default to disabled. A
locked, offline station requires both relevant options to be enabled.

## Local database

The companion uses SQLite at `data/companion/journal.db` by default. It uses
Python's built-in `sqlite3` module, so no database service, SQLAlchemy, or Alembic
is required. The journal stores local printer registrations and configuration,
station binding, downloaded batches, execution state, results awaiting upload,
investigation blocks, and pending local stop audit events. Transactions use
`PRAGMA synchronous=FULL` to make state durable before hardware execution.

Users, permissions, accounting, and the authoritative queue remain on the main
server. The companion database supplies the durable local state needed to finish
already-authorized work offline and avoid printing a batch twice after a crash.
Keep the entire data directory across upgrades and back it up with the service
stopped. Never delete or reset the journal to clear a printer error.

## Recovery and updates

Native installations use the same updater as the main server:

```sh
cd /opt/labels
sudo python3 scripts/update.py --mode native --check
sudo python3 scripts/update.py --mode native
```

`--mode` is optional: the updater detects the matching systemd service or Compose
containers, including stopped installations. Explicit `--mode native` or
`--mode docker` overrides detection. Updates ask for confirmation; `--yes` skips
the prompt for automation, while `--check` remains read-only and never prompts.

The updater detects `.label-server-role`, with `.env.companion` as a fallback for
older companion installations, and verifies the systemd entry point. Conflicting
main and companion configuration is rejected. Native deployments use `.venv`
and the role's environment file; custom data directories are read from settings.

It selects companion dependencies and frontend assets, preserves `.env.companion`
and printer configuration, and backs up the SQLite journal, code, and Python
environment. It does not run the main server's Alembic migrations. Startup remains
paused, including communication with the main server and local controls, until
the health check succeeds. Failed updates restore the previous code and state
before resuming; an uncertain activation leaves the service stopped for recovery.

To avoid building the frontend on a Pi, use its verified release archive:

```sh
sudo python3 scripts/update.py --mode native --prebuilt-frontend
```

The release workflow publishes `label-companion-frontend.zip` separately from
`label-server-frontend.zip`. The updater verifies the asset digest, source commit,
and server role before stopping the service. The archive must exist on the chosen
release; there is no silent fallback. `--channel beta` and `--tag` work for both roles.
Compose companions use `--mode docker`; `.env.companion` selects the companion
Compose service and data volume automatically.

The companion verifies and durably stores a complete batch before requesting the
main server's go-ahead. An authorized running batch may finish during an outage.
Results are stored locally and retried without repeating hardware execution.
Ordinary controls and new work need a main-server connection.

An idle disconnect reconnects without human clearance. Printer errors, interrupted
execution, or a process crash during a batch block the affected printer. Review
uncertain output on the main server, investigate the device, then use **Clear
block**. Other printers can continue independently. A ready hardware status alone
does not clear an investigation block.

Run one companion process per data directory. Main and companion servers belong
on different machines. Never delete the companion journal to recover printing: it prevents duplicate attempts. Stop or
finish printing before upgrades; a forced process termination is treated as
uncertain output on restart. Keep the main server and companion on compatible
versions; the initial batch protocol is version 1.

Automated tests use simulated adapters. Physical USB printing, Pi packaging, and
real network interruption still require hardware acceptance on the deployment.

## Moving an existing main-server printer

After adding the physical printer through the companion's web interface, an
administrator can open **Printers & groups** on the main server and choose
**Move to companion** on the original printer. Select the new companion
registration. Both registrations must be idle and have matching drivers and
rendering capabilities, including resolution. Cancel any pending flush on the
original first; its labels stay queued.

The original printer keeps its ID, ownership, explicit permissions, history,
groups and queued work. It inherits the companion's location and therefore that
location's access grants. The duplicate registration is retired, retaining its
own history. Finish or reroute its pending work, remove it from groups and
uninstall its cartridge before moving. The original cartridge selection remains,
but its physical confirmation is reset. Its recorded location is unchanged.

Printing is held after the move. Check the installed cartridge and resume
printing when ready. Updated companions refresh the binding automatically;
companions running **0.13.0-pre1 must be restarted after the move**. This workflow
currently moves main-server printers to companions.

**Retire printer** removes an obsolete registration from active views and stops
its worker without deleting history or audit records. It requires the printer's
Configure permission. Unfinished work, group membership, unresolved batches and
companion error blocks must be resolved first. Retirement uninstalls its
cartridge and disables its companion slot when applicable. Retired registrations
cannot be restored with the companion's local Restore control.
