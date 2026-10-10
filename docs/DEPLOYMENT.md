# Deployment and recovery

## Debian service in an LXC or host

Install Python 3.12+, Node 22.12+ for building the UI, `libusb-1.0-0` and `usbutils`.
Clone/copy the project to `/opt/labels`, create a `labels` service user, and create
a `labelprinter` group. Install dependencies, build the frontend and migrate:

```sh
python3 -m venv .venv
.venv/bin/pip install -c requirements.lock .
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/alembic upgrade head
```

Copy `.env.example` to `.env` for server and notification configuration. Add the
printer under **Printers & groups** in the web UI. USB serial is optional for one
Brother device and required on every device when several are used. Locate USB
devices with `lsusb -d 04f9:20af`; inspect `lsusb -v` for `iSerial`, which may differ
from the physical serial label by a prefix. All device settings are stored in the
database and edited with **Configure**, including the first printer.

Install `deploy/70-label-printer.rules` under `/etc/udev/rules.d/` on the host
owning the USB device, reload udev rules and reconnect the printer. Add the service
user to `labelprinter`. Ensure the data directory is writable by `labels`.
Install `deploy/labels.service`, adjust paths/bind address if needed, and start it
with systemd. Migrations remain an explicit stopped-service upgrade step.
Do not run P-touch Editor, CUPS or another process against the same printer.

## Proxmox LXC USB access

The printer must be accessible on the Proxmox host first. On versions exposing
`dev[n]`, pass the specific `/dev/bus/usb/BBB/DDD` node to the stopped container,
with a writable mode and the intended in-container uid/gid. For example, adapting
container ID, node and user IDs to your installation:

```sh
pct set 123 -dev0 path=/dev/bus/usb/001/005,uid=10001,gid=10001,mode=0660
```

Confirm the option against your installed `pct help set` and the
[Proxmox container documentation](https://pve.proxmox.com/pve-docs/pct.1.html).
Start the container and verify `lsusb` and device permissions there before
starting the application. USB node numbers can change after reconnect: update
the passthrough mapping and restart affected containers. Unprivileged LXC ID
mapping must match your service user. Do not enable all-device or privileged
access merely to bypass an incorrect mapping. Older Proxmox versions require
their documented cgroup/device bind configuration instead of `dev[n]`.

## Docker

The base Compose file starts with no configured printers and exposes localhost by default:

```sh
docker compose up -d --build
```

For real USB, supply the specific node and its group in `.env` and use the explicit
override. It grants that device, not the entire USB bus:

```sh
# .env: LABEL_USB_DEVICE=/dev/bus/usb/001/005
# .env: LABEL_USB_GID=<numeric group owning the node>
docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d --build
```

The image runs as UID 10001 and includes libusb. With Docker inside LXC, both
layers need that device mapped and accessible. Recreate the service after USB
node renumbering. The image applies migrations before starting one Uvicorn worker.
Stop the old container before an upgrade; do not run a second service on the same
database/device. No Docker build was executed in the development session because
the Docker daemon was unavailable; Compose configuration was validated.

## Settings and exposure

Under **Printers & groups → Configure**, the page timeout bounds each completion
wait (default 120 seconds). **Cut each label** requests individual labels; disabling
it requests a strip with final feed. Feed and leader estimates can be adjusted in
the same form. Finish queued work and saved drafts before changing these settings.

Choose **180 × 360 dpi** for higher resolution along the tape, or **180 × 180 dpi**
for normal output. Templates can override the device default. Saved jobs and CSV
drafts retain their original rendering settings. The first high-resolution physical
comparison was reported successful by the user. Configuration changes apply
without a server restart.

The initial administrator uses the one-time `auth-setup-token` file beside the
database. For Compose, read it using
`docker compose exec labels cat /srv/labels/data/auth-setup-token`. For native
deployment, read `data/auth-setup-token` as the service owner. Enter the token in
the browser setup screen; it is removed after registration. Existing workspace
records belong to this first administrator. Subsequent users require registration
codes by default and need a directly assigned role with Request only or higher
access to a printer or distribution group before submitting approval requests.
Print skips approval; Moderator adds scoped queue/request management; Full adds
configuration. Template groups share templates and never hand out roles.
Queued labels paused before initial administrator setup stay paused until the
administrator releases or cancels them from the dashboard.

While initial setup is pending, the same token is also printed in the startup logs
as `Initial administrator setup token: …`. Use `docker compose logs labels` for
Compose, `journalctl -u labels.service` for systemd, or the native server's terminal.
Restarts reuse and log the pending token; after the first administrator is created,
startup no longer logs a setup token.

For an existing installation, stop the service and run
`.venv/bin/alembic upgrade head` before restarting with the rebuilt frontend.
Migration `e84a91c607d2` adds saved print attribution. Existing history remains
available; requester, approver or batch-starter details without reliable historical
evidence are shown as Not recorded.

Use HTTPS through your reverse proxy for access beyond localhost. Forward the
original scheme/host only from a trusted proxy; the browser origin must match
the public server origin. Session cookies become Secure on HTTPS. Configure
users, roles, groups and approval notifications through **Administration**.
Access-changing role and membership edits require a before/after impact preview
and confirmation. Accounts disabled or deprived of required printer access leave
their queued jobs paused for an administrator release/cancel decision on the
dashboard. Restoring permissions does not automatically resume those jobs.
Set `LABEL_PUBLIC_URL` to a browser-reachable origin for notification links. ntfy
credentials stay in the environment; failed notifications use the durable outbox.
The anonymous `/api/health` healthcheck proves the server responds, not that the
printer is connected. Workspace and printer APIs require sign-in.

## Backup, restore, upgrades

Stop the service and copy the entire data directory/volume, including database,
WAL/SHM files if present, and `assets/fonts` and `assets/images`. Preserve `.env`
separately. Do not copy only the database while uploads or printing are active.
On restore, stop every old worker, restore permissions and the complete data,
apply migrations and start a single server process. A stale lock file can remain on disk;
the operating-system lock, not file existence, prevents concurrent workers.

Back up before upgrading, stop, install dependencies, migrate and rebuild the UI,
then restart. Treat printing interrupted by any shutdown as requiring review.
Never delete a review record or reissue a job with a new retry key merely to clear
an uncertain physical result. Reconcile copies and tape consumption in the UI.


## Multiple USB printers

The application runs one physical worker per registered device, inside one server
process. Keep one Uvicorn process and the database ownership lock. Register every printer with its own
USB serial under **Printers & groups**. Map every required USB device into
the container/LXC; the sample Compose USB override maps one device and must be
extended with the additional current device nodes. Both need the configured
udev/group permissions. A group is a routing destination, not a USB device.

## Environment configuration

Supported application variables are `LABEL_DATABASE_URL`,
`LABEL_WORKER_INTERVAL_SECONDS`, `LABEL_FRONTEND_DIST`, `LABEL_NTFY_URL`,
`LABEL_NTFY_TOPIC`, `LABEL_NTFY_TOKEN` and `LABEL_PUBLIC_URL`. Compose additionally
uses `LABEL_BIND_ADDRESS`, `LABEL_USB_DEVICE` and `LABEL_USB_GID` for deployment.
Printer connections, resolution, feed, cuts and timeout are configured in the UI.
The anonymous health check uses `/api/health` and succeeds before a printer is registered.

For an existing installation, run the migration once with its old environment
available before removing the obsolete printer entries. It imports the physical
printer's settings into its database registration and retires simulated printers.
Subsequent startups read printer configuration only from the database.

For a Compose upgrade, make the previous `.env` available to the one-off migration
before starting the new service (the normal Compose environment no longer forwards
printer variables):

```sh
docker compose stop labels
docker compose build labels
docker compose run --rm -v "$PWD/.env:/srv/labels/.env:ro" labels alembic upgrade head
docker compose up -d
```

Keep using your usual USB Compose override for commands if one is configured.
After migration, remove the old printer entries from your local `.env`.

The physical-width migration converts old 4 mm media references to 3.5 mm and
adds a revised editable template where needed. Job snapshots, historical template
revisions and saved run render documents keep their original pixels. Run the
migration with the service stopped, then rebuild the frontend. Invalid imported
printer settings remain visible on the printer card and can be repaired using
**Configure**.

Physical printer testing of the current implementation was validated by the user
on 2026-10-04 after the review fixes. See the [hardware verification record](HARDWARE_VERIFICATION.md).
The confirmation did not specify a Docker/LXC environment or provide new
consumption calibration measurements.
