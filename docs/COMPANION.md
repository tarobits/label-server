# Companion stations

A companion runs the USB printer adapters and a small web interface. The main
server renders labels and owns permissions, queues, cartridge inventory, and
accounting. The companion connects outward over HTTPS; the main server never
needs an inbound connection to the station.

## Manual-only printers

Enable **No automatic printing** in a printer's configuration on the main server
or in the companion's configuration dialog for an existing printer. This persists
across restarts and prevents automatic dispatch, including through printer groups.
Only changing that configuration setting can restore automatic printing; Hold and
Resume controls are hidden and their API endpoints reject changes while it is enabled.
Manual print actions remain available and retain their normal permission checks.

The companion shows **Manual only** or **Automatic** beside each printer's name,
separately from its operational status. An idle, connected manual-only printer
shows **Ready**; errors, cartridge checks and investigation blocks still take priority.
Apply main-server migration `19191a0b41a7` before using this setting.

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
The connection bar also shows the companion's running version, source and license
links, and project credit. Connection status stays centered.

When a newer stable release is available, a small **Update available** link appears
beside the station summary, including while locked. The companion compares its own
version with the main server's cached GitHub release check; it does not contact
GitHub separately. Set `LABEL_COMPANION_SHOW_UPDATE_NOTICE=false` to hide it.
The main server's `LABEL_CHECK_FOR_UPDATES` must be enabled. Updates remain manual;
the notice does not install software or interrupt printing.

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

Queue entries show their tape profile; CSV runs stay grouped with expandable
rows. **Print current tape queue** starts the eligible queue for the installed
cartridge's profile and selected destination, including entries beyond the
current page. Existing print permissions, funding holds and price checks apply.
Operators with **View everyone’s print activity** permission can open **Pack labels** on a
printer to browse completed batches, preview labels and sort them by requester.
Locking the station closes packing and hides its private content.

Set `LABEL_COMPANION_LOG_LEVEL` to `DEBUG`, `INFO` (default), `WARNING`, `ERROR`
or `CRITICAL`. Successful HTTP requests (2xx) are logged only at `DEBUG`; 4xx
responses are warnings and 5xx responses are errors. Redirects and other 3xx
responses appear at `INFO`. Request query strings are omitted from access logs.
The main server uses its own `LABEL_LOG_LEVEL` setting.

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

## Read-only status API for external displays

Set `LABEL_COMPANION_STATUS_API_KEY` in the companion's private `.env.companion`
and restart it. A blank value disables these endpoints. Generate a separate random
key, for example with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
The key must contain 32–512 ASCII characters without whitespace and must differ
from `LABEL_COMPANION_API_KEY`, which authenticates the companion to the main server.

Send `Authorization: Bearer <status-api-key>` to the **companion**, not the main
server. A browser station session, query parameter or main-server key does not
authorize this API. The status key grants no station controls, proxy access or
label previews. It works while the station is locked, independently of
`LABEL_COMPANION_SHOW_LOCKED_DASHBOARD_DETAILS`. Use HTTPS when accessing the
companion over a network, as for its existing web interface. CORS access is not
enabled; call this API from your operating environment's backend/native client.

| Method and endpoint | Result |
| --- | --- |
| `GET /api/status` | Companion name and all enabled local printer registrations |
| `GET /api/status/printers/{local_id}` | Same envelope with one printer; unknown or removed IDs return 404 |

```sh
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${COMPANION_STATUS_API_KEY}" \
  https://station.example.com/api/status
```

Example response (illustrative values):

```json
{
  "schema_version": 1,
  "name": "Packing station",
  "online": true,
  "printers": [
    {
      "local_id": "desk",
      "name": "Desk printer",
      "status": "ready",
      "connected": true,
      "printing": false,
      "blocked": false,
      "held": false,
      "cartridge_check_pending": false,
      "queued_labels": 7,
      "shared_queued_labels": 3,
      "cartridge": {
        "name": "White cassette",
        "profile_name": "Black on white 12 mm",
        "foreground": "#000000",
        "background": "#ffffff",
        "width_mm": 12,
        "remaining_mm": 4990,
        "nominal_length_mm": 8000,
        "uncertain": false
      },
      "snapshot_age_seconds": 1.5,
      "stale": false
    }
  ]
}
```

`queued_labels` counts queued **copies** addressed directly to that printer.
`shared_queued_labels` counts copies in groups containing it; those copies are not
reserved for that printer and must not be summed across printers as unique work.
Cartridge dimensions and length estimates are in millimetres; `uncertain` flags
unreconciled consumption. Colors use the tape profile's foreground/background values.

`status` is one of `unknown`, `disconnected`, `error`, `printing`, `held`,
`awaiting_cartridge_confirmation`, or `ready`. Blocking takes precedence, followed
by local printing, unknown/disconnected state, pending cartridge confirmation,
other reported errors, and hold. The individual flags preserve simultaneous states.
`ready` describes the last reported operational state, not permission or a promise
that any particular queued label is eligible to print. Raw error text is omitted.

`online` means the companion has recently contacted the main server. Queue and
cartridge data are cached server summaries: `snapshot_age_seconds` gives their age,
and `stale` is true when no summary exists, it is over 30 seconds old, or the main
server is offline. Cached counts and cartridge details remain available during
an outage. Before the first summary, counts, hold/confirmation flags, cartridge
and age are null; the companion name falls back to `Companion` until synchronized.
When stale, `connected` is null and `status` is `unknown`, except that locally known
blocking or active printing still takes precedence. A null cartridge with a fresh
summary means none is installed.

Polling every 3–5 seconds is sufficient. Reads use cached data without opening the
printer, contacting the main server or extending the station's unlock timeout.
Responses use `Cache-Control: no-store`. Missing/invalid credentials return 401;
disabled endpoints return 404; update validation temporarily returns 503. Rotate
or revoke the key by changing or clearing the setting and restarting the companion.

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

An idle disconnect reconnects without human clearance. Hardware faults, interrupted
execution, or a process crash during a batch block the affected printer. Review
uncertain output on the main server, investigate the device, then use **Clear
block**. Other printers can continue independently. A ready hardware status alone
does not clear an investigation block.

A cartridge-confirmation notice alone does not create an investigation block.
For the PT-P710BT, an open cover, removed cartridge, or wrong-media warning during
an idle cartridge change also clears without fault clearance. These conditions
still prevent printing and cartridge confirmation while present. Close the cover,
confirm the cartridge on either interface, and allow the next companion status
updates to apply it. Routine server polling does not prevent an idle companion's
cartridge selection or confirmation. Actual hardware faults and uncertain execution
still need explicit clearance, even if a cartridge is subsequently confirmed.
Older versions may have latched an investigation block for cartridge access or a
confirmation notice; after inspecting the printer, use **Clear block** once. The
stored flag cannot distinguish that old
false alarm from a genuine fault. Update the main server before the companion so
it accepts the status distinction; both sides need the fix.

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
