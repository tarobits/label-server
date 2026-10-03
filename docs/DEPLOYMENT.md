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

Copy `.env.example` to `.env`. Set `LABEL_PRINTER_BACKEND=brother-pt-p710bt` and,
if necessary, `LABEL_PRINTER_USB_SERIAL` to the USB serial descriptor. An empty
serial is allowed only when exactly one matching device is found. Use
`lsusb -d 04f9:20af` to locate it. The physical serial label and USB descriptor may
differ by a prefix; inspect `lsusb -v` for `iSerial`.

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

The base Compose file retains mock mode and exposes localhost by default:

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

`LABEL_PRINTER_TIMEOUT_SECONDS` bounds each page's completion wait (default 120).
`LABEL_PRINTER_CUT_EACH=true` requests individual labels; false requests a strip
with final feed. Feed and leader settings are described in the physical checklist.
Keep mock mode for experiments that should not consume tape.

`LABEL_PRINTER_RESOLUTION=high` selects 180 dpi across the tape and 360 dpi along
it for new Brother jobs and CSV drafts. `normal` (the default) uses 180 × 180 dpi.
Restart after changing this setting. Existing jobs/drafts retain their saved
resolution; create a fresh submission for comparisons. Printer & settings shows
the configured default resolution. Templates can override it with their Print
resolution selector; previews, new jobs and new CSV drafts use that choice.
The first high-resolution physical comparison was reported successful by the user.

Bind to a trusted LAN interface or put the service behind your existing access
proxy. Account authentication remains out of scope until phase 8 is approved.
Set `LABEL_PUBLIC_URL` to a browser-reachable origin for notification links. ntfy
credentials stay in the environment; failed notifications use the durable outbox.
The HTTP healthcheck proves the server responds, not that the printer is connected.

## Backup, restore, upgrades

Stop the service and copy the entire data directory/volume, including database,
WAL/SHM files if present, and `assets/fonts` and `assets/images`. Preserve `.env`
separately. Do not copy only the database while uploads or printing are active.
On restore, stop every old worker, restore permissions and the complete data,
apply migrations and start a single worker. A stale lock file can remain on disk;
the operating-system lock, not file existence, prevents concurrent workers.

Back up before upgrading, stop, install dependencies, migrate and rebuild the UI,
then restart. Treat printing interrupted by any shutdown as requiring review.
Never delete a review record or reissue a job with a new retry key merely to clear
an uncertain physical result. Reconcile copies and tape consumption in the UI.
